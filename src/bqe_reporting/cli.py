from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

import httpx

from .analysis import analyze, management_brief
from .auth import OAuthPKCE, TokenRecord, WindowsTokenStore
from .client import BQEClient
from .config import Settings
from .mock import sync_mock
from .planning import write_planning_context
from .storage import Warehouse
from .sync import DEFAULT_RESOURCES, RESOURCE_SPECS, SyncEngine


MOCK_BANNER = "*** MOCK MODE — SYNTHETIC DATA; NO BQE CONNECTION ***"
LIVE_BANNER = "*** LIVE MODE — READ-ONLY BQE CORE ACCESS ***"


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="bqe",
        description="BQE CORE read-only ingestion and AI planning data connector",
    )
    root.add_argument("--db", type=Path, help="SQLite path (defaults to BQE_DB_PATH)")
    sub = root.add_subparsers(dest="command", required=True)

    auth = sub.add_parser("auth", help="manage Native App PKCE authorization")
    auth_actions = auth.add_mutually_exclusive_group()
    auth_actions.add_argument("--show-url", action="store_true")
    auth_actions.add_argument("--login", action="store_true")
    auth_actions.add_argument("--clear", action="store_true")

    sync = sub.add_parser("sync", help="ingest mock fixtures or authorized BQE data")
    sync.add_argument("--live", action="store_true", help="use the approved live connection")
    sync.add_argument(
        "--resources",
        nargs="+",
        choices=tuple(RESOURCE_SPECS),
        default=list(DEFAULT_RESOURCES),
    )
    sync.add_argument("--from", dest="date_from", help="inclusive YYYY-MM-DD")
    sync.add_argument("--to", dest="date_to", help="inclusive YYYY-MM-DD")
    sync.add_argument(
        "--full",
        action="store_true",
        help="explicitly allow a full history read for resources without checkpoints",
    )
    sync.add_argument("--strict", action="store_true", help="stop when a resource is unavailable")
    sync.add_argument("--page-size", type=int)

    sub.add_parser("status", help="show local coverage and recent sync state")
    sub.add_parser("validate", help="run local warehouse integrity checks")

    analyze_cmd = sub.add_parser("analyze", help="generate CSV summaries")
    analyze_cmd.add_argument("--output", type=Path, default=Path("exports/analysis"))

    brief = sub.add_parser("brief", help="generate a Markdown planning brief")
    brief.add_argument(
        "--output", type=Path, default=Path("exports/planning/management_brief.md")
    )

    context = sub.add_parser(
        "export-context", help="generate traceable JSON and Markdown for AI-assisted planning"
    )
    context.add_argument("--output", type=Path, default=Path("exports/planning"))

    sub.add_parser("inspect-schema", help="print the local analytical schema")

    test = sub.add_parser(
        "test-connection", help="make one limited five-row project capability request"
    )
    test.add_argument("--live", action="store_true", required=True)

    access = sub.add_parser(
        "test-access", help="probe approved resources without displaying or storing records"
    )
    access.add_argument("--live", action="store_true", required=True)
    access.add_argument(
        "resources",
        nargs="+",
        choices=tuple(spec.endpoint for spec in RESOURCE_SPECS.values()),
    )
    return root


def _token(settings: Settings) -> TokenRecord:
    settings.require_live()
    assert settings.client_id
    record = WindowsTokenStore(settings.client_id).load()
    if record is None:
        raise RuntimeError("No stored access token; run bqe auth --login first")
    if record.expired:
        raise RuntimeError("Stored access token is expired; run bqe auth --login again")
    if "readwrite:core" in record.scope.split():
        raise RuntimeError("Stored token includes forbidden readwrite:core scope")
    return record


def _mode(settings: Settings) -> str:
    return "authorized BQE CORE read-only warehouse" if settings.live else "synthetic mock warehouse"


def _auth(args: argparse.Namespace, settings: Settings) -> int:
    print(LIVE_BANNER if settings.live else MOCK_BANNER)
    print(
        f"Application type: Native App\nRedirect URI: {settings.redirect_uri}\n"
        f"Scopes: {' '.join(settings.scopes)}"
    )
    if not settings.client_id:
        raise RuntimeError("BQE_CLIENT_ID is not configured locally")
    store = WindowsTokenStore(settings.client_id)
    if args.clear:
        store.clear()
        print("Stored BQE access token removed from Windows Credential Manager.")
        return 0
    if args.login:
        print("Opening BQE consent. Confirm that the screen requests read:core only.")
        record = OAuthPKCE(settings).login()
        print(f"Authorization succeeded. Token expires at {record.expires_at}.")
        return 0
    if args.show_url:
        pending = OAuthPKCE(settings).prepare()
        print(f"Authorization URL (contains no secret):\n{pending.authorization_url}")
        return 0
    record = store.load()
    if record is None:
        print("Authorization status: no stored token.")
    else:
        state = "expired" if record.expired else "available"
        print(f"Authorization status: access token is {state}; expires at {record.expires_at}.")
    return 0


def _sync(args: argparse.Namespace, settings: Settings, db_path: Path) -> int:
    if not args.live:
        print(MOCK_BANNER)
        with Warehouse(db_path) as warehouse:
            counts = sync_mock(warehouse)
        print("Loaded: " + ", ".join(f"{name}={count}" for name, count in counts.items()))
        return 0

    record = _token(settings)
    print(LIVE_BANNER)
    with Warehouse(db_path) as warehouse:
        with BQEClient(
            record.endpoint,
            record.access_token,
            utc_offset=settings.utc_offset,
        ) as client:
            results = SyncEngine(client, warehouse).sync(
                args.resources,
                date_from=args.date_from,
                date_to=args.date_to,
                full=args.full,
                strict=args.strict,
                page_size=args.page_size,
            )
    for result in results:
        detail = f"; {result.error}" if result.error else ""
        print(
            f"{result.resource}: {result.status}; pages={result.pages}; "
            f"rows={result.rows}; checkpoint={result.watermark_after or 'none'}{detail}"
        )
    unavailable = [result for result in results if result.status != "complete"]
    print("No record values were written to logs. BQE CORE was not modified.")
    return 3 if unavailable and args.strict else 0


def _status(db_path: Path) -> int:
    with Warehouse(db_path) as warehouse:
        counts = warehouse.row_counts()
        checkpoints = warehouse.connection.execute(
            "SELECT resource,high_watermark,synced_at FROM sync_state ORDER BY resource"
        ).fetchall()
        runs = warehouse.connection.execute(
            "SELECT started_at,finished_at,status,requested_resources_json,error "
            "FROM sync_runs ORDER BY started_at DESC LIMIT 5"
        ).fetchall()
    print("Local coverage:")
    for name, count in counts.items():
        print(f"  {name}: {count}")
    print("Checkpoints:")
    for row in checkpoints:
        print(f"  {row['resource']}: {row['high_watermark'] or 'none'}")
    if runs:
        print("Recent sync runs:")
        for row in runs:
            resources = ", ".join(json.loads(row["requested_resources_json"]))
            print(f"  {row['started_at']} — {row['status']} ({resources})")
    return 0


def _validate(db_path: Path) -> int:
    with Warehouse(db_path) as warehouse:
        checks = warehouse.validate()
    for check in checks:
        print(f"{check['severity'].upper()}: {check['check']} — {check['message']}")
    return 4 if any(check["severity"] == "error" for check in checks) else 0


def _probe(args: argparse.Namespace, settings: Settings) -> int:
    record = _token(settings)
    resources = ["project"] if args.command == "test-connection" else args.resources
    failures = 0
    print(LIVE_BANNER)
    with BQEClient(
        record.endpoint, record.access_token, utc_offset=settings.utc_offset
    ) as client:
        for resource in dict.fromkeys(resources):
            try:
                response = client.request(
                    "GET",
                    resource,
                    params=client.build_params(
                        fields="id,lastUpdated",
                        order_by="lastUpdated desc",
                        page=(1, 5),
                    ),
                )
                rows = [] if response.status_code == 204 else response.json()
                if not isinstance(rows, list):
                    raise RuntimeError(f"Unexpected {resource} response shape")
                print(
                    f"{resource}: HTTP {response.status_code}; rows={len(rows)}; "
                    f"rate-limit-remaining="
                    f"{response.headers.get('X-Rate-Limit-Remaining', 'not supplied')}"
                )
            except httpx.HTTPStatusError as exc:
                failures += 1
                print(
                    f"{resource}: HTTP {exc.response.status_code}; unavailable for this user",
                    file=sys.stderr,
                )
    print("No response records were displayed or stored.")
    return 3 if failures else 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        settings = Settings.from_env()
        logging.basicConfig(level=settings.log_level, format="%(levelname)s %(message)s")
        db_path = args.db or settings.db_path
        if args.command == "auth":
            return _auth(args, settings)
        if args.command == "sync":
            return _sync(args, settings, db_path)
        if args.command == "status":
            return _status(db_path)
        if args.command == "validate":
            return _validate(db_path)
        if args.command == "analyze":
            with Warehouse(db_path) as warehouse:
                paths = analyze(warehouse.connection, args.output)
            print("Generated: " + ", ".join(str(path) for path in paths.values()))
            return 0
        if args.command == "brief":
            with Warehouse(db_path) as warehouse:
                text = management_brief(warehouse.connection, _mode(settings))
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
            print(f"Generated: {args.output}")
            return 0
        if args.command == "export-context":
            with Warehouse(db_path) as warehouse:
                paths = write_planning_context(
                    warehouse, args.output, data_mode=_mode(settings)
                )
            print("Generated: " + ", ".join(str(path) for path in paths.values()))
            return 0
        if args.command == "inspect-schema":
            with Warehouse(db_path) as warehouse:
                rows = warehouse.connection.execute(
                    "SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
            for name, sql in rows:
                print(f"\n-- {name}\n{sql};")
            return 0
        if args.command in {"test-connection", "test-access"}:
            return _probe(args, settings)
    except (RuntimeError, ValueError, httpx.HTTPError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
