import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from order_automation.browser import OrderPage

FIXTURE_URL = "http://order-automation.test/orders"
FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "orders.html"


def test_order_details(page, order_scenario, pytestconfig):
    url = pytestconfig.getoption("order_url")
    if url:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None:
            raise pytest.UsageError("--order-url requires an HTTP or HTTPS URL without embedded credentials.")
    else:
        url = FIXTURE_URL

        def serve_fixture(route):
            if route.request.url == FIXTURE_URL:
                route.fulfill(path=FIXTURE_PATH, content_type="text/html; charset=utf-8")
            else:
                route.abort()

        page.route("**/*", serve_fixture)

    selectors = json.loads(Path(pytestconfig.getoption("order_selectors")).read_text(encoding="utf-8"))
    OrderPage(page, url, selectors).validate(order_scenario)
