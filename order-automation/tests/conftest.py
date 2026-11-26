from base64 import b64encode
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
import pytest
from pytest_html import extras

from order_automation.instructions import load_model, read_scenarios

ROOT = Path(__file__).resolve().parents[1]


def pytest_addoption(parser):
    group = parser.getgroup("order automation")
    group.addoption("--scenario", action="append", default=[], help="Plain-English scenario file. Repeat to run more than one.")
    group.addoption("--order-url", help="Order lookup page URL. Defaults to the bundled fixture.")
    group.addoption("--order-selectors", default=str(ROOT / "selectors.json"), help="JSON selector profile.")
    group.addoption("--order-storage-state", help="Playwright storage state for an authenticated test account.")


def pytest_generate_tests(metafunc):
    if "order_scenario" not in metafunc.fixturenames:
        return
    files = metafunc.config.getoption("scenario") or [ROOT / "scenarios" / "demo.txt"]
    model = load_model(ROOT / "field-training.json")
    scenarios = []
    for file in files:
        try:
            scenarios.extend(read_scenarios(Path(file), model))
        except (OSError, ValueError) as exc:
            raise pytest.UsageError(str(exc)) from exc
    metafunc.parametrize("order_scenario", scenarios, ids=[scenario.title for scenario in scenarios])


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args, pytestconfig):
    state = pytestconfig.getoption("order_storage_state")
    if state:
        if not pytestconfig.getoption("order_url"):
            raise pytest.UsageError("--order-storage-state requires --order-url.")
        path = Path(state).resolve()
        if not path.is_file():
            raise pytest.UsageError(f"Storage state file does not exist: {path}")
        return {**browser_context_args, "storage_state": str(path)}
    return browser_context_args


def pytest_html_report_title(report):
    report.title = "Order Automation Test Report"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or "order_scenario" not in item.funcargs:
        return
    scenario = item.funcargs["order_scenario"]
    plan = {
        "order": scenario.order_number,
        "checks": [{"field": check.field, "expected": check.expected, "instruction": check.instruction}
                   for check in scenario.checks],
    }
    report.extras = [*getattr(report, "extras", []), extras.json(plan, name="Test instructions")]
    if report.failed:
        try:
            screenshot = item.funcargs["page"].screenshot(timeout=3_000)
        except PlaywrightError:
            return
        report.extras.append(extras.png(b64encode(screenshot).decode("ascii"), name="Failure screenshot"))
