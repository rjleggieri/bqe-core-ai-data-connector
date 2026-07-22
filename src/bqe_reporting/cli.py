from __future__ import annotations

import argparse
from datetime import date, timedelta
import logging
from pathlib import Path
import sqlite3
import sys

import httpx

from .analysis import analyze, management_brief
from .auth import OAuthPKCE, WindowsTokenStore
from .client import BQEClient
from .config import Settings
from .mock import sync_mock
from .storage import Warehouse


MOCK_BANNER = "*** MOCK MODE — SYNTHETIC DATA ONLY; NO BQE CONNECTION ***"
LIVE_BANNER = "*** LIVE MODE — READ-ONLY GET REQUESTS; EXPLICIT APPROVAL REQUIRED ***"


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="bqe", description="BQE CORE read-only reporting proof of concept")
    root.add_argument("--db", type=Path, help="SQLite path (defaults to BQE_DB_PATH)")
    sub = root.add_subparsers(dest="command", required=True)
    auth = sub.add_parser("auth", help="manage Native App PKCE authorization")
    auth_actions = auth.add_mutually_exclusive_group()
    auth_actions.add_argument("--show-url", action="store_true", help="build an authorization URL from local BQE_CLIENT_ID")
    auth_actions.add_argument("--login", action="store_true", help="open BQE consent and capture the loopback callback")
    auth_actions.add_argument("--clear", action="store_true", help="delete the locally stored access token")
    sync = sub.add_parser("sync", help="load mock fixtures (live sync intentionally not enabled in phase 1)")
    sync.add_argument("--from", dest="date_from")
    sync.add_argument("--to", dest="date_to")
    sync.add_argument("--live", action="store_true", help="request live mode (currently stops safely)")
    analyze_cmd = sub.add_parser("analyze", help="generate CSV analyses")
    analyze_cmd.add_argument("--output", type=Path, default=Path("exports/mock"))
    brief = sub.add_parser("brief", help="generate Markdown management brief")
    brief.add_argument("--output", type=Path, default=Path("exports/mock/management_brief.md"))
    sub.add_parser("inspect-schema", help="print local analytical schema")
    test = sub.add_parser("test-connection", help="make one limited five-row read-only project request")
    test.add_argument("--live", action="store_true", required=True, help="confirm this is an approved live test")
    access = sub.add_parser("test-access", help="probe approved read-only resources without storing records")
    access.add_argument("--live", action="store_true", required=True, help="confirm these are approved live tests")
    access.add_argument(
        "resources",
        nargs="+",
        choices=("timeentry", "expenseentry", "allocation"),
        help="approved resources to probe; each is limited to five id/lastUpdated rows",
    )
    pilot = sub.add_parser("pilot-sync", help="cache a narrow approved time/expense date range")
    pilot.add_argument("--live", action="store_true", required=True, help="confirm this is an approved live extract")
    pilot.add_argument("--from", dest="date_from", required=True, help="inclusive date, YYYY-MM-DD")
    pilot.add_argument("--to", dest="date_to", required=True, help="inclusive date, YYYY-MM-DD")
    pilot.add_argument("--output-db", type=Path, default=Path("data/live_pilot.sqlite3"))
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        settings = Settings.from_env()
        logging.basicConfig(level=settings.log_level, format="%(levelname)s %(message)s")
        db_path = args.db or settings.db_path
        if args.command == "auth":
            print(MOCK_BANNER if not settings.live else LIVE_BANNER)
            print(f"Application type: Native App\nRedirect URI: {settings.redirect_uri}\nScopes: {' '.join(settings.scopes)}")
            if not settings.client_id:
                raise RuntimeError("BQE_CLIENT_ID is not configured locally")
            store = WindowsTokenStore(settings.client_id)
            if args.clear:
                store.clear()
                print("Stored BQE access token removed from Windows Credential Manager.")
                return 0
            if args.login:
                print("Opening BQE login and consent. Confirm the consent screen requests read:core only.")
                record = OAuthPKCE(settings).login()
                print(f"Authorization succeeded. Token expires at {record.expires_at}.")
                print("No company-data API request was made.")
                return 0
            if args.show_url:
                pending = OAuthPKCE(settings).prepare()
                print(f"Authorization URL (contains no secret):\n{pending.authorization_url}")
                print("State and PKCE verifier were generated in memory and are not displayed or saved.")
                return 0
            record = store.load()
            if record is None:
                print("Authorization status: no stored token. No browser opened and no request made.")
            else:
                state = "expired" if record.expired else "available"
                print(f"Authorization status: stored access token is {state}; expires at {record.expires_at}.")
            return 0
        if args.command == "sync":
            if args.live:
                settings.require_live()
                raise RuntimeError("Phase 1 intentionally stops before the first authenticated BQE request")
            print(MOCK_BANNER)
            with Warehouse(db_path) as warehouse:
                counts = sync_mock(warehouse)
            print("Loaded: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
            return 0
        if args.command == "analyze":
            print(MOCK_BANNER if settings.mode != "LIVE" else LIVE_BANNER)
            with Warehouse(db_path) as warehouse:
                paths = analyze(warehouse.connection, args.output)
            print("Generated: " + ", ".join(str(path) for path in paths.values()))
            return 0
        if args.command == "brief":
            print(MOCK_BANNER if settings.mode != "LIVE" else LIVE_BANNER)
            with Warehouse(db_path) as warehouse:
                text = management_brief(warehouse.connection)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
            print(f"Generated: {args.output}")
            return 0
        if args.command == "inspect-schema":
            with Warehouse(db_path) as warehouse:
                rows = warehouse.connection.execute(
                    "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
            for name, sql in rows:
                print(f"\n-- {name}\n{sql};")
            return 0
        if args.command == "test-connection":
            if not settings.live:
                raise RuntimeError(
                    "Live test is disabled. Set BQE_MODE=LIVE and BQE_ENABLE_LIVE=YES after approval."
                )
            if not settings.client_id:
                raise RuntimeError("BQE_CLIENT_ID is not configured")
            record = WindowsTokenStore(settings.client_id).load()
            if record is None:
                raise RuntimeError("No stored access token; run bqe auth --login first")
            if record.expired:
                raise RuntimeError("Stored access token is expired; run bqe auth --login again")
            print(LIVE_BANNER)
            try:
                with BQEClient(record.endpoint, record.access_token, utc_offset=settings.utc_offset) as client:
                    response = client.request(
                        "GET",
                        "project",
                        params=client.build_params(
                            fields="id,lastUpdated", order_by="lastUpdated desc", page=(1, 5)
                        ),
                    )
                    rows = [] if response.status_code == 204 else response.json()
            except httpx.HTTPStatusError as exc:
                response = exc.response
                print(f"BQE rejected the read-only test: HTTP {response.status_code}.", file=sys.stderr)
                try:
                    error = response.json()
                except ValueError:
                    error = None
                if isinstance(error, dict):
                    code = error.get("errorCode") or error.get("code") or error.get("error")
                    description = error.get("errorDescription") or error.get("description")
                    if code:
                        print(f"BQE error code: {code}", file=sys.stderr)
                    if description and len(str(description)) <= 300:
                        print(f"BQE description: {description}", file=sys.stderr)
                print("No response records were stored or displayed.", file=sys.stderr)
                return 3
            if not isinstance(rows, list):
                raise RuntimeError("Unexpected project response shape")
            print(f"Read-only test succeeded: HTTP {response.status_code}; rows returned={len(rows)}.")
            print(
                "Rate-limit remaining="
                f"{response.headers.get('X-Rate-Limit-Remaining', 'not supplied')}. "
                "No record identifiers or values were logged."
            )
            return 0
        if args.command == "test-access":
            if not settings.live:
                raise RuntimeError(
                    "Live tests are disabled. Set BQE_MODE=LIVE and BQE_ENABLE_LIVE=YES after approval."
                )
            if not settings.client_id:
                raise RuntimeError("BQE_CLIENT_ID is not configured")
            record = WindowsTokenStore(settings.client_id).load()
            if record is None:
                raise RuntimeError("No stored access token; run bqe auth --login first")
            if record.expired:
                raise RuntimeError("Stored access token is expired; run bqe auth --login again")
            print(LIVE_BANNER)
            failures = 0
            with BQEClient(record.endpoint, record.access_token, utc_offset=settings.utc_offset) as client:
                for resource in dict.fromkeys(args.resources):
                    try:
                        response = client.request(
                            "GET",
                            resource,
                            params=client.build_params(
                                fields="id,lastUpdated", order_by="lastUpdated desc", page=(1, 5)
                            ),
                        )
                        rows = [] if response.status_code == 204 else response.json()
                        if not isinstance(rows, list):
                            raise RuntimeError(f"Unexpected {resource} response shape")
                        print(
                            f"{resource}: HTTP {response.status_code}; rows={len(rows)}; "
                            "rate-limit-remaining="
                            f"{response.headers.get('X-Rate-Limit-Remaining', 'not supplied')}"
                        )
                    except httpx.HTTPStatusError as exc:
                        failures += 1
                        print(
                            f"{resource}: HTTP {exc.response.status_code}; access denied or unavailable; "
                            "no records stored or displayed",
                            file=sys.stderr,
                        )
            print("Completed approved access probes. No record identifiers or values were logged or cached.")
            return 3 if failures else 0
        if args.command == "pilot-sync":
            if not settings.live:
                raise RuntimeError(
                    "Live pilot sync is disabled. Set BQE_MODE=LIVE and BQE_ENABLE_LIVE=YES after approval."
                )
            if not settings.client_id:
                raise RuntimeError("BQE_CLIENT_ID is not configured")
            try:
                start = date.fromisoformat(args.date_from)
                end = date.fromisoformat(args.date_to)
            except ValueError as exc:
                raise ValueError("Pilot dates must use YYYY-MM-DD") from exc
            if end < start or (end - start).days > 31:
                raise ValueError("Pilot range must be between 1 and 32 inclusive calendar days")
            end_exclusive = end + timedelta(days=1)
            record = WindowsTokenStore(settings.client_id).load()
            if record is None:
                raise RuntimeError("No stored access token; run bqe auth --login first")
            if record.expired:
                raise RuntimeError("Stored access token is expired; run bqe auth --login again")
            where = (
                f"date>='{start.isoformat()}T00:00:00' AND "
                f"date<'{end_exclusive.isoformat()}T00:00:00'"
            )
            time_fields = [
                "id", "date", "projectId", "resourceId", "activityId", "actualHours",
                "clientHours", "billable", "billRate", "costRate", "billStatus", "invoiceId",
                "isWrittenOff", "lastUpdated",
            ]
            expense_fields = [
                "id", "date", "projectId", "resourceId", "expenseId", "billable", "billStatus",
                "chargeAmount", "costRate", "invoiceId", "isWrittenOff", "lastUpdated",
            ]
            print(LIVE_BANNER)
            with BQEClient(record.endpoint, record.access_token, utc_offset=settings.utc_offset) as client:
                time_rows = client.get_time_entries(
                    fields=time_fields, where=where, order_by="date asc", page_size=1000
                )
                expense_rows = client.get_expense_entries(
                    fields=expense_fields, where=where, order_by="date asc", page_size=1000
                )
            context = f"approved live pilot {start.isoformat()} through {end.isoformat()} America/New_York"
            with Warehouse(args.output_db) as warehouse:
                warehouse.store_raw("time_entries", time_rows, context=context)
                warehouse.store_raw("expense_entries", expense_rows, context=context)
                warehouse.normalize("time_entries", time_rows)
                warehouse.normalize("expense_entries", expense_rows)
                summary = warehouse.connection.execute(
                    "SELECT COUNT(*), COALESCE(SUM(actual_hours),0), "
                    "COALESCE(SUM(CASE WHEN billable=1 THEN actual_hours ELSE 0 END),0) "
                    "FROM time_entries WHERE date>=? AND date<?",
                    (f"{start.isoformat()}T00:00:00", f"{end_exclusive.isoformat()}T00:00:00"),
                ).fetchone()
                expense_summary = warehouse.connection.execute(
                    "SELECT COUNT(*), COALESCE(SUM(charge_amount),0) FROM expense_entries "
                    "WHERE date>=? AND date<?",
                    (f"{start.isoformat()}T00:00:00", f"{end_exclusive.isoformat()}T00:00:00"),
                ).fetchone()
            print(
                f"Pilot cached in {args.output_db}: time entries={summary[0]}, "
                f"actual hours={summary[1]:.2f}, billable hours={summary[2]:.2f}; "
                f"expense entries={expense_summary[0]}, charge amount={expense_summary[1]:.2f}."
            )
            print("No names, memos, descriptions, custom fields, attachments, or unrelated records were requested.")
            return 0
    except (RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
