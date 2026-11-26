# End-to-end code walkthrough

## Chat and authentication

1. [Angular workspace](../frontend/src/app/features/workflow-studio/workflow-studio.component.ts) reads the composer text, keeps up to 12 earlier turns, appends the user bubble, and calls `WorkflowApiService.chat`.
2. [Angular HTTP service](../frontend/src/app/services/workflow-api.service.ts) uses HttpClient and RxJS to send `{message, history}` to `POST /api/chat`. The [authentication service](../frontend/src/app/services/auth.service.ts) supplies the authorization headers.
3. [FastAPI chat route](../backend/app/api/workflow_chat_routes.py) validates the JSON with Pydantic and resolves the caller using [signed bearer tokens](../backend/app/auth/tokens.py). It passes the message, history, and master-role flag to the chat runtime. Configuration, provider, and input errors map to HTTP 503, 502, and 422 respectively.
4. [Chat runtime](../backend/app/runtime/chat_service.py) handles greetings, trace guidance, document questions, inline XML extraction, and workflow selection. It checks the selected workflow and extracted values. A missing required value produces a clarification and can include a workflow form.
5. [Workflow executor](../backend/app/runtime/workflow_executor.py) loads the selected YAML, runs its steps, and returns data, a message, variables, and step timings. The Angular workspace renders that response as a chat bubble and, for an execution, a result view.

## Workflow data and XML

| Source | Input | Output |
| --- | --- | --- |
| [Create order YAML](../backend/app/definitions/workflows/create-order.yaml) | Order number and optional batch input | Mapped order details or execution error |
| [Expression resolver](../backend/app/runtime/expression_resolver.py) | YAML value and execution context | Resolved value, such as a number, object, or XML string |
| [Workflow actions](../backend/app/workflow_actions.py) | Action arguments or Sterling API parameters and XML | Action value or integration response |
| [Prompt transformation](../backend/app/runtime/prompt_transform.py) | XML or JSON value and a supported instruction | XML with a renamed root or selected JSON data |
| [Shared XML templates](../backend/app/definitions/templates/input-templates.xml) | Template ID and runtime values | Request XML for Sterling |

A standalone reference such as `${variables.api_1_response.xml}` returns the stored value. The [example workflow](../backend/app/definitions/workflows/new-workflow.yaml) passes that XML to a Python transformation, saves the result, and uses it as the next API request body. PyYAML loads workflow definitions. Python regular expressions and lxml implement the supported XML transformation commands.

## AI, document retrieval, and workflow design

- [Workflow retrieval](../backend/app/assistant_ai/workflow_retrieval.py) uses BM25 to rank workflow metadata. [Local workflow selection](../backend/app/assistant_ai/workflow_intent_service.py) coordinates the selection and extraction of inputs. The workflow runtime validates values before executing a step.
- [Document service](../backend/app/assistant_ai/document_assistant/document_service.py) receives the question and history. [Document retrieval](../backend/app/assistant_ai/document_assistant/document_retrieval.py) ranks relevant local text chunks. The [PyTorch generation model](../backend/app/assistant_ai/document_assistant/generation_model.py) implements local text generation.
- [Workflow draft generation](../backend/app/runtime/workflow_generator.py) builds YAML and preview data from a description, template, or sample XML. The [Angular designer](../frontend/src/app/features/workflow-generator/workflow-designer.component.ts) uses the [studio routes](../backend/app/api/workflow_generator_routes.py) for validation, XML templates, and saving.

## Browser automation

The [Angular automation service](../frontend/src/app/services/automation.service.ts) calls the [FastAPI automation routes](../backend/app/api/order_automation_routes.py). The [Python workbench](../order-automation/order_automation/workbench.py) builds a code preview from a plain-English scenario and can invoke pytest for an HTML report. The [recorder](../order-automation/order_automation/recorder.py) captures browser actions as editable steps. [Replay](../order-automation/order_automation/replay.py) uses Playwright to execute the saved steps and return a status for each.
