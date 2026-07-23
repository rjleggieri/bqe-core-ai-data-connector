from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import logging
import random
import time
from typing import Any

import httpx


LOG = logging.getLogger(__name__)


class ReadOnlyViolation(RuntimeError):
    pass


class BQEClient:
    """Resilient GET-only client for BQE CORE business-data endpoints."""

    def __init__(
        self,
        base_url: str,
        access_token: str,
        *,
        utc_offset: str = "-04:00",
        timeout: float = 30.0,
        max_retries: int = 4,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self._client = httpx.Client(
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "X-UTC-Offset": utc_offset,
                "User-Agent": "bqe-core-ai-data-connector/1.0 (read-only)",
            },
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "BQEClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @staticmethod
    def build_params(
        *,
        fields: str | list[str] | None = None,
        where: str | None = None,
        order_by: str | None = None,
        page: int | tuple[int, int] | str | None = None,
        expand: str | list[str] | None = None,
    ) -> dict[str, str]:
        params: dict[str, str] = {}
        if fields:
            params["fields"] = ",".join(fields) if isinstance(fields, list) else fields
        if where:
            params["where"] = where
        if order_by:
            params["orderBy"] = order_by
        if page is not None:
            params["page"] = (
                f"{page[0]},{page[1]}" if isinstance(page, tuple) else str(page)
            )
        if expand:
            params["expand"] = ",".join(expand) if isinstance(expand, list) else expand
        return params

    def request(self, method: str, resource: str, **kwargs: Any) -> httpx.Response:
        if method.upper() != "GET":
            raise ReadOnlyViolation(
                f"Blocked {method.upper()} {resource}: business-data access is GET-only"
            )
        url = f"{self.base_url}/{resource.lstrip('/')}"
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.request("GET", url, **kwargs)
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt >= self.max_retries:
                    raise
                self._sleep(attempt)
                continue
            if response.status_code == 429 and attempt < self.max_retries:
                delay = self._retry_after(response.headers.get("Retry-After"))
                LOG.warning("BQE rate limit reached; retrying in %.1f seconds", delay)
                time.sleep(delay)
                continue
            if response.status_code >= 500 and attempt < self.max_retries:
                self._sleep(attempt)
                continue
            response.raise_for_status()
            return response
        raise AssertionError("unreachable")

    @staticmethod
    def _retry_after(value: str | None) -> float:
        if not value:
            return 1.0
        try:
            return min(max(float(value), 0.0), 60.0)
        except ValueError:
            try:
                parsed = parsedate_to_datetime(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return min(max((parsed - datetime.now(timezone.utc)).total_seconds(), 0.0), 60.0)
            except (TypeError, ValueError, OverflowError):
                return 1.0

    @staticmethod
    def _sleep(attempt: int) -> None:
        delay = min(2**attempt, 8) + random.uniform(0, 0.25)
        time.sleep(delay)

    def get(self, resource: str, **query: Any) -> list[dict[str, Any]]:
        response = self.request("GET", resource, params=self.build_params(**query))
        if response.status_code == 204 or not response.content:
            return []
        payload = response.json()
        if not isinstance(payload, list):
            raise TypeError(f"Expected a list from {resource}, got {type(payload).__name__}")
        return payload

    def iter_pages(
        self, resource: str, *, page_size: int | None = None, **query: Any
    ) -> Iterator[list[dict[str, Any]]]:
        expanded = bool(query.get("expand"))
        size = page_size or (100 if expanded else 1000)
        maximum = 100 if expanded else 1000
        if not 1 <= size <= maximum:
            raise ValueError(f"page_size must be 1..{maximum} for this query")
        number = 1
        while True:
            rows = self.get(resource, page=(number, size), **query)
            if not rows:
                break
            yield rows
            if len(rows) < size:
                break
            number += 1

    def get_all(self, resource: str, **query: Any) -> list[dict[str, Any]]:
        return [row for page in self.iter_pages(resource, **query) for row in page]

    def get_projects(self, **query: Any) -> list[dict[str, Any]]:
        return self.get_all("project", **query)

    def get_clients(self, **query: Any) -> list[dict[str, Any]]:
        return self.get_all("client", **query)

    def get_time_entries(self, **query: Any) -> list[dict[str, Any]]:
        return self.get_all("timeentry", **query)

    def get_invoices(self, **query: Any) -> list[dict[str, Any]]:
        return self.get_all("invoice", **query)

    def get_payments(self, **query: Any) -> list[dict[str, Any]]:
        return self.get_all("payment", **query)

    def get_employees(self, **query: Any) -> list[dict[str, Any]]:
        return self.get_all("employee", **query)

    def get_expense_entries(self, **query: Any) -> list[dict[str, Any]]:
        return self.get_all("expenseentry", **query)

    def get_activities(self, **query: Any) -> list[dict[str, Any]]:
        return self.get_all("activity", **query)

    def get_allocations(self, **query: Any) -> list[dict[str, Any]]:
        return self.get_all("allocation", **query)

    def get_custom_fields(self, **query: Any) -> list[dict[str, Any]]:
        return self.get_all("customfield", **query)

    def get_custom_field_values(self, **query: Any) -> list[dict[str, Any]]:
        return self.get_all("customfieldvalue", **query)
