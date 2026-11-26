# Integrated Workflow Studio and Operations Portal

Open `http://127.0.0.1:4200/operations/` for the Ganalimura shell. **Chat** opens the Workflow Studio conversation in the portal's main panel, including workflow actions, settings, and results. The standalone studio is also available at `http://127.0.0.1:4200/`. The studio and portal use their existing sign-ins. If you have already signed into the studio on that browser origin, the embedded chat reuses that session.

| Module | Responsibility | Local port |
| --- | --- | --- |
| `../frontend` | Workflow Studio and development gateway | 4200 |
| `../backend` | Workflow runtime and local AI | 8000 |
| `portal` | Operations Portal screens and bundled API reference | 4300 |
| `portal-service` | Portal users, sign-in, and exception support | 9002 |
| `workflow-service` | Portal chat bridge and the imported shipment workflow API | 8081 |
| `reprocess-service` | Standalone exception reprocessing service | 9003 |

The embedded chat uses the same local AI and workflow API as the standalone studio. The imported Java chat bridge remains available for clients that use the portal's read-only document API. The standalone reprocessing and shipment workflow APIs are available on loopback at their own ports.

## Run locally

1. Install Python dependencies from `backend/requirements.txt`, and run `npm ci` in `frontend/` and `operations/portal/`. Put JDK 21 or later and Maven on `PATH`, or set `WORKFLOW_JAVA_HOME` to the JDK installation.
2. Configure the studio with `backend/.env`. For Java, set the following environment variables in the PowerShell session that starts the suite. Use development databases and test Interop credentials.

   - `PORTAL_DB_URL`, `PORTAL_DB_USERNAME`, `PORTAL_DB_PASSWORD` for portal PostgreSQL
   - `WORKFLOW_DB_URL`, `WORKFLOW_DB_USERNAME`, `WORKFLOW_DB_PASSWORD` for workflow-service PostgreSQL
   - `APP_JWT_SECRET` for portal sign-in and optionally `BOOTSTRAP_USERNAME` and `BOOTSTRAP_PASSWORD` for the initial portal account
   - `SPRING_MAIL_HOST`, `SPRING_MAIL_USERNAME`, `SPRING_MAIL_PASSWORD`, `APP_MAIL_FROM` for password recovery
   - `OMS_INTEROP_URL`, `OMS_INTEROP_USER`, `OMS_INTEROP_PASSWORD` for the imported Java Interop clients

3. Run `./scripts/start-integrated.ps1` from the repository root. It starts the six services and writes their logs to `.integrated-logs/`. Stop any running instances on the same ports first.

If `/operations/` displays the standalone Workflow Studio sidebar, port 4200 is likely serving an older Studio dev server. The launcher reuses verified Studio and portal processes and reports ports occupied by other processes. To start just the portal shell and embedded chat, pass `-ChatOnly`. User management and exceptions require the Java services.

The launcher generates an ephemeral shared bridge token. For separate manual processes, provide the same `WORKFLOW_BRIDGE_TOKEN` to FastAPI and `workflow-service`.

The copied Java API reference lives in `portal/public/javadocs/`. It is generated content ignored by version control. In a fresh checkout, copy that directory from the source portal if the API Doc page is needed. The copied Automation Testing page still expects its original `/api/tests` backend, which was absent from the supplied projects.
