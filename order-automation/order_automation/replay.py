# Run saved steps in Playwright and return per-step statuses. Resolve any test password only for the current run.
"""Replay a saved browser script and return per-step outcomes."""

import json
import os
import sys
from urllib.parse import urlsplit

from playwright.sync_api import Error, expect, sync_playwright


def _allowed(url, origins):
    target = urlsplit(url)
    return f"{target.scheme}://{target.netloc}".lower() in origins


def _run_step(page, step, start_url, origins, password=None):
    action = step["action"]
    if action == "navigate":
        url = step["url"] or start_url
        if not _allowed(url, origins):
            raise ValueError("Navigation is outside the configured recording origins.")
        page.goto(url, wait_until="domcontentloaded")
        return
    if action == "screenshot":
        page.screenshot()
        return
    if not step["selector"]:
        raise ValueError("Enter a selector for this step.")
    target = page.locator(step["selector"])
    if action == "click":
        target.click()
    elif action == "fill":
        value = step["value"]
        if step.get("metadata"):
            value = password or os.getenv("ORDER_TEST_PASSWORD")
            if not value:
                raise ValueError("Enter the test account password to replay this step.")
        target.fill(value)
    elif action == "select":
        target.select_option(step["value"])
    elif action == "assertText":
        expect(target).to_contain_text(step["expected"])
    elif action == "assertTextExact":
        expect(target).to_have_text(step["expected"])
    elif action == "assertVisible":
        expect(target).to_be_visible()


def _click_failure(page, selector, error, previous_step=None):
    # Inspect the locator without exposing the browser's raw error or page content.
    prefix = f"Could not click {selector}."
    try:
        target = page.locator(selector)
        count = target.count()
        if count == 0:
            path = urlsplit(page.url).path or "/"
            if (previous_step and previous_step["action"] == "click"
                    and path.rstrip("/").rsplit("/", 1)[-1].lower() in {"login", "signin", "sign-in"}
                    and page.locator('input[type="password"]:visible').count()):
                return (f"{prefix} The browser is still on {path} after the previous click. "
                        "Check that the script fills the username and that the test account can sign in.")
            return f"{prefix} No element matched on {path}. Check that the previous step opened the expected page."
        if count > 1:
            return f"{prefix} {count} elements matched. Use a selector that identifies one element."
        if not target.is_visible():
            return f"{prefix} The element was hidden."
        if not target.is_enabled(timeout=300):
            return f"{prefix} The element was disabled."
    except (Error, ValueError):
        return f"{prefix} The selector could not be inspected. Check its syntax and whether the page is still open."
    if "intercepts pointer events" in str(error):
        return f"{prefix} Another element blocked the click. Check for an open dialog or overlay."
    return f"{prefix} The click timed out. Check whether the element was ready and stable."


def replay(script, origins, password=None):
    start_url, steps = script["startUrl"], script["steps"]
    with sync_playwright() as playwright:
        channel = os.getenv("ORDER_AUTOMATION_BROWSER_CHANNEL", "msedge" if os.name == "nt" else "")
        with playwright.chromium.launch(**({"channel": channel} if channel else {})) as browser:
            with browser.new_context(
                ignore_https_errors=urlsplit(start_url).hostname in {"localhost", "127.0.0.1", "::1"},
                service_workers="block",
            ) as context:
                context.route("**/*", lambda route: route.continue_() if _allowed(route.request.url, origins) else route.abort())
                page = context.new_page()
                page.set_default_timeout(5000)
                outcomes = []
                for index, step in enumerate(steps, 1):
                    try:
                        if index == 1 and step["action"] != "navigate":
                            _run_step(page, {"action": "navigate", "url": start_url}, start_url, origins)
                        _run_step(page, step, start_url, origins, password)
                    except (Error, ValueError, AssertionError) as exc:
                        outcomes.append({"status": "FAILED"})
                        if isinstance(exc, ValueError):
                            detail = str(exc)
                        elif step["action"] == "click":
                            detail = _click_failure(page, step["selector"], exc, steps[index - 2] if index > 1 else None)
                        else:
                            detail = f"Could not complete {step['action']}. Check the target and expected result."
                        return {"status": "FAILED", "steps": outcomes, "detail": f"Step {index}. {detail}"}
                    outcomes.append({"status": "PASSED"})
                return {"status": "PASSED", "steps": outcomes}


if __name__ == "__main__":
    payload = json.load(sys.stdin)
    print(json.dumps(replay(payload["script"], set(payload["origins"]), payload.get("password"))))
