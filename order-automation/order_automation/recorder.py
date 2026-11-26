# Launch a local Playwright browser and capture user events as editable steps. Password steps use a reference instead of a stored value.
"""Capture editable Playwright steps from a local headed browser session."""

import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

from playwright.sync_api import Error, sync_playwright

CAPTURE = r"""
(() => {
  const passwordFields = new WeakSet();
  const recordedValues = new WeakMap();
  function selector(el) {
    const tag = el.tagName.toLowerCase();
    for (const name of ["data-testid", "name", "aria-label", "title", "autocomplete", "placeholder", "id", "type"]) {
      const value = el.getAttribute(name);
      if (!value) continue;
      if (name === "id" && /^(cds|icon-btn|mat|ng|react|radix)[-_:].*\d$/i.test(value)) continue;
      const rule = (name === "id" || name === "data-testid" ? '' : tag) + '[' + name + '="' + CSS.escape(value) + '"]';
      if (document.querySelectorAll(rule).length === 1) return rule;
    }
    const text = (el.textContent || '').trim().replace(/\s+/g, ' ');
    if (text && text.length <= 100 && Array.from(document.querySelectorAll(tag)).filter(
      item => (item.textContent || '').trim().replace(/\s+/g, ' ') === text).length === 1) {
      return tag + ':text-is(' + JSON.stringify(text) + ')';
    }
    return '';
  }
  function record(action, el, value, environment) {
    const target = selector(el);
    if (!target) return;
    if (action === 'fill' && !environment) recordedValues.set(el, value);
    window.recordWorkflowStep({action, selector: target, ...(value === undefined ? {} : {value}),
      ...(environment ? {metadata: {environment}} : {})}).catch(() => {});
  }
  document.addEventListener('click', event => {
    if (!event.isTrusted) return;
    const el = event.target instanceof Element && event.target.closest('button,a,input,[role="button"],[role="link"]');
    if (!el || /(?:show|hide|reveal|toggle).*password|password.*visibility/i.test(
        [el.getAttribute('aria-label'), el.title, el.textContent].join(' '))) return;
    if (el.type === 'submit' || /^(?:log\s*in|sign\s*in)$/i.test(el.textContent.trim())) {
      const form = el.form || el.closest('form');
      const scope = form || document;
      if (scope.querySelector('input[type="password"]')) {
        const candidates = [...scope.querySelectorAll('input')].filter(input =>
          ['text', 'email'].includes(input.type) && !passwordFields.has(input) &&
          /user\s*name|user\s*id|login|email/i.test(
            [input.name, input.id, input.autocomplete, input.placeholder, input.getAttribute('aria-label'),
              ...Array.from(input.labels || [], label => label.textContent)].join(' ')));
        if (candidates.length === 1) {
          const input = candidates[0];
          if (input.value && input.value !== recordedValues.get(input)) record('fill', input, input.value);
        }
      }
    }
    if (!(el instanceof HTMLInputElement && !['button','submit','reset','checkbox','radio'].includes(el.type)))
      record('click', el);
  }, true);
  function captureValue(event) {
    const el = event.target;
    if (!event.isTrusted || (el instanceof HTMLInputElement && el.type === 'file')) return;
    if (el instanceof HTMLSelectElement) record('select', el, el.value);
    else if (el instanceof HTMLInputElement &&
        (el.type === 'password' || passwordFields.has(el) ||
          /password/i.test([el.name, el.id, el.autocomplete].join(' ')))) {
      passwordFields.add(el);
      if (el.value) record('fill', el, undefined, 'ORDER_TEST_PASSWORD');
    }
    else if ((el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement)
      && !['password','hidden','file','checkbox','radio','submit','button','reset'].includes(el.type)
      && !/password|one-time-code|cc-|secret|token/i.test([el.name, el.id, el.autocomplete].join(' '))) record('fill', el, el.value);
  }
  document.addEventListener('change', captureValue, true);
  document.addEventListener('focusin', event => {
    if (event.target instanceof HTMLInputElement && event.target.type === 'password')
      passwordFields.add(event.target);
  }, true);
  document.addEventListener('input', event => {
    if (!(event.target instanceof HTMLSelectElement)) captureValue(event);
  }, true);
})();
"""


def main() -> None:
    session = Path(sys.argv[1])
    config = json.loads((session / "config.json").read_text(encoding="utf-8"))
    url, origins = config["url"], set(config["origins"])
    steps = [{"action": "navigate", "url": url, "selector": ""}]
    ready = session / "ready"
    try:
        with sync_playwright() as playwright:
            channel = os.getenv("ORDER_AUTOMATION_BROWSER_CHANNEL", "msedge" if os.name == "nt" else "")
            browser = playwright.chromium.launch(headless=False, **({"channel": channel} if channel else {}))
            with browser.new_context(
                ignore_https_errors=urlsplit(url).hostname in {"localhost", "127.0.0.1", "::1"},
                service_workers="block",
            ) as context:
                def route_request(route):
                    target = urlsplit(route.request.url)
                    if f"{target.scheme}://{target.netloc}".lower() in origins:
                        route.continue_()
                    else:
                        route.abort()

                def record(source, step):
                    if not isinstance(step, dict):
                        return
                    action, selector = step.get("action"), step.get("selector")
                    if action not in ("click", "fill", "select") or not isinstance(selector, str) or len(selector) > 1500:
                        return
                    clean = {"action": action, "selector": selector}
                    if action != "click":
                        if action == "fill" and step.get("metadata") == {"environment": "ORDER_TEST_PASSWORD"}:
                            clean["metadata"] = step["metadata"]
                        else:
                            value = step.get("value")
                            if not isinstance(value, str) or len(value) > 10_000:
                                return
                            clean["value"] = value
                    if action == "fill" and steps[-1].get("action") == action and steps[-1].get("selector") == selector:
                        steps[-1] = clean
                    elif len(steps) < 250:
                        steps.append(clean)

                context.route("**/*", route_request)
                context.expose_binding("recordWorkflowStep", record)
                context.add_init_script(CAPTURE)
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=15_000)
                ready.touch()
                deadline = time.monotonic() + 900
                while browser.is_connected() and not page.is_closed() and not (session / "stop").exists():
                    if time.monotonic() >= deadline:
                        break
                    page.wait_for_timeout(200)
    except Error as exc:
        if not ready.exists():
            (session / "error.txt").write_text(str(exc).splitlines()[0], encoding="utf-8")
    finally:
        (session / "steps.json").write_text(json.dumps(steps, ensure_ascii=True), encoding="utf-8")


if __name__ == "__main__":
    main()
