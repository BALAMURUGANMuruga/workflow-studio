# Use Playwright and selectors to search orders and inspect the resulting browser page.
from playwright.sync_api import Page, expect

from .instructions import Scenario


class OrderPage:
    def __init__(self, page: Page, url: str, selectors: dict):
        self.page = page
        self.url = url
        self.selectors = selectors

    def validate(self, scenario: Scenario) -> None:
        fields = self.selectors["fields"]
        required = {"order_number", *(check.field for check in scenario.checks)}
        missing = required - fields.keys()
        if missing:
            raise ValueError(f"Missing selectors for: {', '.join(sorted(missing))}")
        self.page.goto(self.url, wait_until="domcontentloaded")
        self.page.locator(self.selectors["search_input"]).fill(scenario.order_number)
        self.page.locator(self.selectors["search_button"]).click()
        order_number = self.page.locator(fields["order_number"])
        expect(order_number).to_be_visible(timeout=10_000)
        expect(order_number).to_have_text(scenario.order_number, timeout=10_000)
        for check in scenario.checks:
            expect(self.page.locator(fields[check.field]), check.instruction).to_have_text(
                check.expected, timeout=10_000
            )
