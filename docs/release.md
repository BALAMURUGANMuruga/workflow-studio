# Workflow Studio release steps

## GitHub and Render

Create an empty private GitHub repository. From this project root, initialize Git if this is a fresh workspace. Review the staged file list for credentials, local data, and generated artifacts before committing.

```powershell
git init -b main
git add .
git diff --cached --name-only
git commit -m "Prepare Workflow Studio for Render"
git remote add origin https://github.com/OWNER/REPOSITORY.git
git push -u origin main
```

For an existing checkout, use its existing branch and remote. In Render, choose **New → Blueprint**, connect the repository, and review the two paid service plans before applying. Enter `WORKFLOW_ADMIN_USERNAME` and a unique password of 16–128 characters for `WORKFLOW_ADMIN_PASSWORD`. Render creates the token signing secret. Configured-auth mode accepts only the configured account. The demo accounts remain available for local development when that mode is disabled.

Open the web service's Render URL and verify `/api/health`, sign-in, chat, and **Floorplan → Live activity**. To enable Sterling calls, add `INTEROP_URL`, `INTEROP_USER`, and `INTEROP_PASSWORD` in the private backend's environment and verify network reachability from Render.

The Blueprint deploys the core Angular and FastAPI services. Render's ephemeral filesystem does not preserve workflow edits across deploys. The Java portal services, Playwright runner, and durable workflow storage require separate provisioning. See [Render Blueprints](https://render.com/docs/infrastructure-as-code).

The root Compose file starts the Angular/Nginx workspace and Python/FastAPI backend. The integrated suite also uses the standalone Operations Portal and three Java services. Browser automation requires the separate Python/Playwright runner.

## 1. Verify the core release on a private machine

From the repository root in PowerShell, create `backend/.env` from `backend/.env.example` if it is missing:

```powershell
if (-not (Test-Path backend/.env)) { Copy-Item backend/.env.example backend/.env }
```

Set `WORKFLOW_AUTH_SECRET` to a new private random secret. To test Sterling calls, configure `INTEROP_URL`, `INTEROP_USER`, and `INTEROP_PASSWORD` for a test environment and keep `WORKFLOW_MOCK_MODE=false`. The Sterling URL must be reachable from the backend container. Its loopback address refers to the container itself.

```powershell
docker compose config --quiet
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://localhost:4200/api/health
```

Open `http://localhost:4200` on the test machine. Sign in, send a chat message, open **Floorplan → Live activity**, and confirm that the request appears. Floorplan activity is per browser tab.

## 2. Prepare the production configuration

- Replace the hardcoded demo accounts in `backend/app/auth/users.py` with production authentication before allowing external traffic. Set production secrets through the deployment environment.
- Expose the workspace through HTTPS and keep backend and database ports private. The repository Compose file publishes ports 4200 and 8000, so restrict them to the deployment network or adjust the port mappings.
- If live users must save workflows, provide a writable, backed-up definitions directory. The current Compose mount is read-only. Retain workflow packs, document model artifacts, and the local intent model cache as needed across releases.
- If recorded tests and browser automation are required, package `order-automation` with the backend, install its Python dependencies and a supported Playwright browser, set `ORDER_AUTOMATION_ROOT`, and configure `ORDER_RECORDING_ORIGINS`. The recorder opens a headed browser on the machine running the backend. Plan an interactive browser host for recording and persistent storage for saved scripts.

## 3. Bring up the integrated services if used

Use the [integrated suite inventory and environment settings](../operations/README.md) to provision the three Java services, the Operations Portal, and their PostgreSQL databases. Build the Java services with Maven and serve the built Angular portal at `/operations/`.

Mirror the route mappings in [the development proxy](../frontend/proxy.conf.js) in the production HTTPS gateway. Route `/api/` to FastAPI, `/operations-api/` to the portal service with WebSocket support, and `/operations-workflows/api/ai/chat` to the Java workflow service. Keep the reprocessing service private and expose only the routes needed by your deployment. Configure the same `WORKFLOW_BRIDGE_TOKEN` on the Java chat bridge and FastAPI when using that bridge.

## 4. Verify and cut over

Validate sign-in, chat, a local document answer, XML extraction, and Floorplan activity on staging. If enabled, also validate saving and reopening a draft, a controlled Sterling test workflow, exception streaming, and Playwright replay. Back up the definition directory, script storage, and Java databases and retain the previous image tags before switching traffic. Check the health endpoint and gateway logs after cutover.
