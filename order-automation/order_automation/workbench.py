# Accept a scenario over stdin, produce a Playwright code preview, and optionally return pytest results and an HTML report.
"""Bridge the local scenario runner to the Automation Testing workbench."""

from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

from .instructions import Scenario, load_model, parse_scenarios

ROOT = Path(__file__).resolve().parents[1]


def preview_code(scenarios: list[Scenario], selectors: dict) -> str:
    fields = selectors["fields"]
    lines = ["import os", "", "from playwright.sync_api import expect", ""]
    for number, scenario in enumerate(scenarios, 1):
        lines.extend([
            "", f"def test_order_{number}(page):",
            '    page.goto(os.environ["ORDER_TEST_URL"], wait_until="domcontentloaded")',
            f"    page.locator({selectors['search_input']!r}).fill({scenario.order_number!r})",
            f"    page.locator({selectors['search_button']!r}).click()",
            f"    expect(page.locator({fields['order_number']!r})).to_be_visible()",
            f"    expect(page.locator({fields['order_number']!r})).to_have_text({scenario.order_number!r})",
        ])
        lines.extend(f"    expect(page.locator({fields[check.field]!r})).to_have_text({check.expected!r})"
                     for check in scenario.checks)
    # The preview exposes the same Playwright steps for use outside the demo runner.
    return "\n".join(lines) + "\n"


def _run(text: str, scenarios: list[Scenario]) -> dict:
    with TemporaryDirectory(prefix="order-workbench-") as directory:
        root = Path(directory)
        scenario, report, junit = (root / name for name in ("scenario.txt", "report.html", "results.xml"))
        scenario.write_text(text, encoding="utf-8")
        command = [
            sys.executable, "-m", "pytest", "-c", "pytest.ini", "tests",
            "--scenario", str(scenario), "--html", str(report), "--junitxml", str(junit),
            "--output", str(root / "screenshots"), "--tb=short", "-q", "-p", "no:cacheprovider",
        ]
        channel = os.getenv("ORDER_AUTOMATION_BROWSER_CHANNEL", "msedge" if os.name == "nt" else "")
        if channel:
            command.extend(["--browser-channel", channel])
        run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=85)
        if run.returncode not in (0, 1) or not junit.is_file() or not report.is_file():
            raise ValueError("The browser run did not finish. Check the installed Playwright browser and runner dependencies.")
        if report.stat().st_size > 5_000_000:
            raise ValueError("The HTML report exceeded 5 MB. Run fewer scenarios at a time.")
        cases = ElementTree.parse(junit).getroot().findall(".//testcase")
        outcomes = []
        for case in cases:
            failure = case.find("failure")
            if failure is None:
                failure = case.find("error")
            pytest_name = case.get("name", "")
            name = next((item.title for item in scenarios if pytest_name.startswith(f"test_order_details[{item.title}-")), pytest_name)
            outcomes.append({
                "name": name,
                "status": "failed" if failure is not None else "passed",
                "detail": failure.get("message", "") if failure is not None else "",
            })
        return {"status": "passed" if run.returncode == 0 else "failed", "outcomes": outcomes,
                "report": report.read_text(encoding="utf-8")}


def main() -> None:
    try:
        request = json.load(sys.stdin)
        text = request["scenario"]
        scenarios = parse_scenarios(text, load_model(ROOT / "field-training.json"))
        if len(scenarios) > 5 or sum(len(item.checks) for item in scenarios) > 30:
            raise ValueError("Run up to five scenarios and 30 checks at a time.")
        selectors = json.loads((ROOT / "selectors.json").read_text(encoding="utf-8"))
        response = {"scenarios": [asdict(item) for item in scenarios], "code": preview_code(scenarios, selectors)}
        if request.get("run"):
            response.update(_run(text, scenarios))
    except subprocess.TimeoutExpired:
        response = {"error": "The browser run timed out."}
    except (KeyError, ValueError, OSError, ElementTree.ParseError) as exc:
        response = {"error": str(exc)}
    print(json.dumps(response, ensure_ascii=True))


if __name__ == "__main__":
    main()
