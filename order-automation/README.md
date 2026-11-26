# AI-Powered Order Automation Testing

Write order lookups and assertions in plain English. A local field classifier learns recognized field names from `field-training.json`. Pytest runs each scenario with Playwright and creates a standalone HTML report with the interpreted checks and failure screenshots.

## Run in VS Code

Open this folder in VS Code, create a virtual environment, and select `.venv\Scripts\python.exe` with **Python: Select Interpreter**.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m pytest
```

The bundled browser fixture contains two sample orders and is served through Playwright request interception. Open `reports/order-tests.html` after the run.

In Workflow Studio, open **Automation Testing → Order automation** to preview a test plan, download its generated Python, or run the same demo fixture and download the HTML report. The backend can locate an installed runner via `ORDER_AUTOMATION_ROOT`. The workbench defaults to Edge on Windows and Playwright Chromium elsewhere. Set `ORDER_AUTOMATION_BROWSER_CHANNEL` on the server to select a different installed browser channel.

**Recorded scripts → Record** opens a Playwright window on the machine running the backend. Perform the browser actions, then use **Stop Recording** to import them. The recorder skips password and sensitive autofill fields. For other test sites, set server variable `ORDER_RECORDING_ORIGINS` to the comma-separated origins the recorder can load, including any sign-in origin it needs.

## Write a scenario

Put each test under its own heading. Start it with an order lookup, then add one or more field checks.

```text
# Check a released order
Open order TEST-1001
Verify order status is Released
Check customer name equals Sample Customer
Confirm order total is "$125.50"
Verify number of items is 2
```

```powershell
.\.venv\Scripts\python.exe -m pytest -c pytest.ini tests --scenario scenarios/demo.txt
```

Supported checks cover order number, status, customer, total, and item count. Add labeled phrases to `field-training.json` to teach the classifier more ways to name these fields. The runner loads the training phrases on each run. Unrecognized instructions or ambiguous field names fail during test collection with the source line.

## Run against your order page

Copy `selectors.json` and update the search controls and order detail selectors for your test application. Supply an authenticated Playwright storage state if the page requires a login. Keep that file out of source control.

```powershell
.\.venv\Scripts\python.exe -m pytest -c pytest.ini tests --scenario scenarios/my-orders.txt --order-url http://localhost:4200/orders --order-selectors selectors.local.json --order-storage-state storage-state.json
```

Use `--headed` to watch the test. You can use an installed Edge browser with `--browser-channel msedge`. Reports and screenshots can contain order data.
