# Workflow Studio

A YAML-driven workflow studio with a locally trained model and retrieval. The bundled example workflows integrate with IBM Sterling.

**Version 3.1** — Cleaned and restructured for real-world development.

## Architecture

The studio uses one shared UI YAML and discovers workflows from their Flow YAML files.

| Definition | Location | Responsibility |
|------------|----------|----------------|
| **UI** | `backend/app/definitions/ui/common-ui.yaml` | Shared layout, status panel, and table controls |
| **Flow** | `backend/app/definitions/flows/` or `.../workflows/<id>/flow.yaml` | Inputs, configuration, variables, registered actions, execution order, error handling |

Supporting assets:

- `definitions/schemas/` — YAML schema contracts
- `definitions/templates/` — Shared XML input/output template catalogs
- Interop API names are enabled by `toolName` values declared in core Flow YAML
- `definitions/workflows/<flow-id>/` — Workflow folders with the flow and any supporting XML templates

The selected flow supplies the title and input fields. Returned records and lists populate result cards and tables.
UI YAML contains **no** Python code or credentials.  
Flow YAML contains **no** HTML or Angular templates.

Chat (`POST /api/chat`) uses a small Transformer token tagger initialized and trained from scratch on synthetic examples derived from AI-enabled workflow YAML. BM25 retrieval selects the relevant workflow metadata. No hosted model or Ollama is used. This is a workflow-specific prototype, not a general-purpose LLM; extraction quality is limited by the synthetic training set.

## Project Structure

```text
backend/
  app/
    main.py                                # FastAPI entry point
    workflow_actions.py                    # Registered actions and Sterling Interop
    api/
      assistant_ai_routes.py               # HTTP endpoints for the local assistant
      studio_api_router.py                 # Composes the studio API
      studio_file_routes.py                # Definition editor and packs
      workflow_chat_routes.py
      workflow_definition_routes.py
      workflow_execution_routes.py
    auth/
      authentication_routes.py
      tokens.py
      users.py
    core/config.py
    definitions/
      schemas/
      templates/
      ui/common-ui.yaml
      workflows/
    assistant_ai/
      workflow_intent_service.py
      workflow_model_training.py
      workflow_retrieval.py
      workflow_token_tagger.py
    runtime/
      chat_service.py
      expression_resolver.py
      workflow_definition_repository.py
      workflow_executor.py
      workflow_explainer.py
      workflow_ui.py
      workflow_validation.py
  tests/
frontend/
  src/
    app/
      authentication.service.ts
      workflow-api.service.ts
      workflow-studio.component.html
      workflow-studio.component.ts
    main.ts
    styles.css
scripts/
docs/
```


## Authentication

For the combined Workflow Studio and Ganalimura setup, follow [Running the integrated suite](operations/README.md).

Login is required for the UI.

| Username | Password | Role | Access |
|----------|----------|------|--------|
| `customer` | `customer123` | customer | Chat + run workflows |
| `master` / `admin` | `master123` / `admin123` | master | Full access including Workflow Studio |

Tokens are HMAC-signed (stdlib, no JWT library). Set `WORKFLOW_AUTH_SECRET` in production.

## Quick Start (Local)

### Prerequisites

- Python 3.11+
- Node.js 20+
- PyTorch (installed from `backend/requirements.txt`)
- (Optional) Docker & Docker Compose

### 1. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with Interop URL and credentials
```

Start:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Or from root:

```bash
make backend-install
make backend
```

Endpoints:

| URL | Description |
|-----|-------------|
| http://127.0.0.1:8000/api/health | Health check |
| http://127.0.0.1:8000/api/config/status | Config status |
| http://127.0.0.1:8000/api/local-ai/health | Local AI status |
| http://127.0.0.1:8000/docs | OpenAPI / Swagger |

The tiny model is trained locally from workflow YAML on the first chat request and cached under `backend/.local_ai_models/`. `LOCAL_AI_TRAIN_EPOCHS` controls the CPU training run (default: 30). For useful general-purpose language understanding, a real domain corpus and substantially more compute are required; the bundled synthetic data is only a workflow prototype.

The custom AI lives in `backend/app/assistant_ai/`. Add model architecture and inference in `workflow_token_tagger.py` or a new module, training data and training code in `workflow_model_training.py`, and retrieval in `workflow_retrieval.py`. `workflow_intent_service.py` connects retrieval, model loading, and input extraction. It returns the selected workflow and inputs to the studio, where workflow execution is handled.

`prompt_intent_model.py` fits a lightweight local classifier from workflow examples, allowed commands, and Markdown headings in the document corpus. Workflow YAML changes refresh the examples automatically. Restart the backend after editing document headings. The classifier suggests an intent, and chat still checks the workflow's allowed commands before executing.

The imported document assistant lives in `backend/app/assistant_ai/document_assistant/`. In Studio chat, try **Ask docs: What is an OrderReleaseKey?** The assistant loads the bundled checkpoint locally and builds a hybrid keyword and embedding index from `documents/` on its first use. It can quote retrieved passages when generation is unreliable and lists source filenames in its answer. The bundled documents are examples, so check their guidance against your integration.

To train a separate checkpoint on the project's actual workflow definitions, run this from `backend/`:

```powershell
python -m app.assistant_ai.document_assistant.generation_model app/definitions/workflows trained-document-model
```

Evaluate the new model before replacing the matching `model.pt` and `tokenizer.json` in `document_assistant/artifacts/`. Restart the backend after replacing those files or editing `documents/` to rebuild the in-memory index.

### 2. Frontend

```bash
cd frontend
npm install
npm start
```

Or:

```bash
make frontend-install
make frontend
```

Open http://127.0.0.1:4200

The Angular dev server proxies `/api` to the backend via `proxy.conf.js`.

### 3. Docker (full stack)

```bash
cp backend/.env.example backend/.env
# edit credentials
make docker-up
```

- Frontend: http://localhost:4200  
- Backend:  http://localhost:8000

## Environment Variables

See `backend/.env.example`:

```env
INTEROP_URL=
INTEROP_USER=
INTEROP_PASSWORD=
WORKFLOW_MOCK_MODE=false
LOCAL_AI_TRAIN_EPOCHS=30

WORKFLOW_PACKS_DIR=          # default: backend/packs
```

Never put secrets in YAML or Angular source.

## Adding a New Workflow

Create a self-contained folder:

```text
backend/app/definitions/workflows/<flow-id>/
  flow.yaml          # id: <flow-id>
  templates/
    input.xml
    output.xml
```

Reference templates from an `api` step:

```yaml
xml_templates:
  request:  {file: workflows/<flow-id>/templates/input,  id: getorderdetailsinput}
  response: {file: workflows/<flow-id>/templates/output, id: getorderdetailsresponse}
```

Declare the Interop API name as `toolName` in a core Flow YAML. Pack workflows can use only API names declared by core Flows.  
Set `ai.enabled: true` and provide examples so the chat can discover the flow.

See `backend/app/definitions/workflows/get-order-details.yaml` for a workflow with generated input fields and single and batch results.

## Updating Flows via Packs (JAR)

A pack is a zip file placed in `backend/packs/`. It mirrors the `definitions/` layout:

```text
orders-pack-1.1.jar
  workflows/order-details-v2/flow.yaml
  workflows/order-hold-list/{flow,ui}.yaml
  workflows/order-hold-list/templates/*.xml
```

- Packs are hot-reloaded when added/replaced/removed.
- `GET /api/packs` lists loaded packs.
- Later jars override earlier ones.
- Only `.yaml/.yml/.xml` entries are read (zip-slip safe).
- `schemas/` inside a jar are ignored for security; pack flows can only call API names declared by core Flows.
- New step capabilities still require a Python action registered in `workflow_actions.py`.

## Security Notes

- YAML is loaded with `yaml.safe_load` only.
- Runtime operations go through the registered `ACTIONS` map and API names declared by core Flow YAML.
- Chat model training and inference run inside the backend; they do not call a hosted AI service.

## Development

See [GitHub and Render deployment](docs/release.md#github-and-render) for the hosted release.

```bash
make clean         # Remove caches
```

## Order automation testing

The [Python order testing framework](order-automation/README.md) runs plain-English order checks through Playwright and produces Pytest HTML reports.

## License

Proprietary / Internal use — adjust as needed.
