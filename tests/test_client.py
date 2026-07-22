from __future__ import annotations

import httpx
import pytest

from bqe_reporting.client import BQEClient, ReadOnlyViolation


def test_query_parameter_construction() -> None:
    params = BQEClient.build_params(
        fields=["id", "name"],
        where="lastUpdated>'2026-01-01T00:00:00'",
        order_by="lastUpdated asc",
        page=(2, 100),
        expand=["customFields", "invoiceDetails"],
    )
    assert params == {
        "fields": "id,name",
        "where": "lastUpdated>'2026-01-01T00:00:00'",
        "orderBy": "lastUpdated asc",
        "page": "2,100",
        "expand": "customFields,invoiceDetails",
    }


def test_pagination_stops_on_short_page() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["page"]
        calls.append(page)
        payload = [{"id": "1"}, {"id": "2"}] if page == "1,2" else [{"id": "3"}]
        return httpx.Response(200, json=payload)

    with BQEClient("https://example.test/api", "synthetic", transport=httpx.MockTransport(handler)) as client:
        rows = client.get_all("project", page_size=2)
    assert [row["id"] for row in rows] == ["1", "2", "3"]
    assert calls == ["1,2", "2,2"]


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_write_methods_are_blocked_before_network(method: str) -> None:
    def fail_if_called(_: httpx.Request) -> httpx.Response:
        raise AssertionError("network should not be reached")

    with BQEClient("https://example.test/api", "synthetic", transport=httpx.MockTransport(fail_if_called)) as client:
        with pytest.raises(ReadOnlyViolation):
            client.request(method, "invoice")


def test_expand_caps_page_size() -> None:
    with BQEClient("https://example.test/api", "synthetic") as client:
        with pytest.raises(ValueError):
            list(client.iter_pages("invoice", page_size=101, expand="invoiceDetails"))
