// Edit the workflow graph and YAML. Send drafts to backend services for validation and persistence.
import { Component, DestroyRef, OnInit, inject, output } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../services/auth.service';
import { NgTemplateOutlet } from '@angular/common';
import { WorkflowApiService, DesignerWorkflow, DesignerStep, DesignerInput, DesignerXmlTemplate } from '../../services/workflow-api.service';
import { Port, portLabels, stepPorts, transitionId, workflowGraph } from './workflow-graph';
import { ResultField, apiResultFields, resultFieldId } from './workflow-result-fields';
import { ApiXmlPropertiesComponent, ApiXmlSettings } from './api-xml-properties.component';

@Component({
  selector: 'app-workflow-designer',
  imports: [FormsModule, NgTemplateOutlet, ApiXmlPropertiesComponent],
  templateUrl: './workflow-designer.component.html',
  styleUrl: './workflow-designer.component.scss',
})
export class WorkflowDesignerComponent implements OnInit {
  private readonly api = inject(WorkflowApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly auth = inject(AuthService);
  readonly dismissed = output<void>();
  readonly saved = output<string>();
  readonly stepLabels: Record<string, string> = {
    action: 'Run Action', api: 'Call API', condition: 'Decision', display: 'Show Result',
    end: 'End Workflow', flow: 'Run Subflow', return: 'Return Result', set: 'Set Values', transform: 'Transform Data',
    'show-message': 'Show Message', 'check-text': 'Check Text',
    'prompt-transform': 'Prompt Transform',
  };
  readonly stepIcons: Record<string, string> = {
    action: '⚡', api: '⇄', condition: '⑂', display: '▣', end: '■',
    flow: '⌘', return: '↩', set: '≡', transform: '⟳',
    'show-message': '☏', 'check-text': '✓',
    'prompt-transform': '✦',
  };
  readonly stepUsage: Record<string, string> = {
    action: 'Run a registered action with the arguments under Additional properties. Save its output to reuse it later.',
    api: 'Call a Sterling API or service using request XML. Save the response for later steps.',
    condition: 'Compare two values or test a condition. Connect Yes and No to the steps that should run for each outcome.',
    display: 'Show selected fields in the workflow result and continue to the next step.',
    end: 'Stop the workflow and return its accumulated result.',
    flow: 'Run a saved workflow as one step. Map its inputs and save its output for later steps.',
    return: 'Choose the final response fields and finish the workflow.',
    set: 'Store named values for later steps. Use literal values or expressions such as ${inputs.orderNo}.',
    transform: 'Reshape existing data into named values. Use Save As to keep the result together.',
    'show-message': 'Show text or a saved workflow output in the assistant reply.',
    'check-text': 'Check for non-empty text, save the boolean result, and route through Yes or No.',
    'prompt-transform': 'Rename the root of XML or JSON, or extract a JSON field from an earlier result.',
  };
  readonly fieldTypes = [
    { type: 'string', label: 'Text Input', icon: 'Aa' }, { type: 'textarea', label: 'Text Area', icon: '¶' },
    { type: 'select', label: 'Dropdown', icon: '▾' }, { type: 'boolean', label: 'Checkbox', icon: '✓' },
    { type: 'number', label: 'Number', icon: '#' }, { type: 'date', label: 'Date Picker', icon: '▦' },
  ];
  workflow: DesignerWorkflow | null = null;
  actions: string[] = [];
  stepTypes: string[] = [];
  index = -1;
  inputIndex = -1;
  dragging = -1;
  query = '';
  details = '';
  private readonly invalidDetails = new Map<DesignerStep | DesignerInput, string>();
  error = '';
  status = '';
  busy = false;
  preview = '';
  view: 'properties' | 'yaml' = 'properties';
  canvasView: 'canvas' | 'yaml' | 'preview' = 'canvas';
  showTemplates = false;
  templates: { id: string; name: string }[] = [];
  xmlTemplates: DesignerXmlTemplate[] = [];
  xmlTemplatesLoading = false;
  xmlTemplatesError = '';
  promptOpen = false;
  aiPrompt = '';
  aiXml = '';
  aiDraft = '';
  aiDraftCode = '';
  aiDraftPreview = '';
  aiPreviewTab: 'yaml' | 'result' | 'code' = 'yaml';
  aiError = '';
  displaySource = '';
  displayLabel = '';
  selectedDisplayFields: string[] = [];
  private resultFieldCache: { key: string; fields: ResultField[] } = { key: '', fields: [] };
  readonly displayFieldId = resultFieldId;
  messageText = '';
  messageMode: 'text' | 'output' = 'text';
  messageSource = '';
  textPath = '';
  decisionSource = '';
  decisionField = '';
  decisionPath = '';
  decisionOperator = 'equals';
  decisionValue = '';
  decisionValueType: 'text' | 'number' | 'boolean' | 'reference' = 'text';
  readonly decisionOperators = [
    {id: 'equals', label: 'Equals'}, {id: 'notEquals', label: 'Does not equal'},
    {id: 'contains', label: 'Contains'}, {id: 'greaterThan', label: 'Greater than'},
    {id: 'empty', label: 'Is empty'}, {id: 'notEmpty', label: 'Is not empty'},
    {id: 'truthy', label: 'Is truthy'},
  ];
  transformSource = '';
  transformPrompt = '';
  transformOutput = '';
  reshapeOutput = '';
  connection: { source: DesignerStep; port: Port } | null = null;
  readonly portLabels = portLabels;
  readonly ports = stepPorts;
  readonly targetId = transitionId;
  private layout = workflowGraph([]);
  private layoutKey = '';

  get steps() { return this.workflow?.steps ?? []; }
  get selected(): DesignerStep | undefined { return this.steps[this.index]; }
  get selectedInput(): DesignerInput | undefined { return this.workflow?.inputs[this.inputIndex]; }
  get canSave(): boolean { return this.auth.isWorkflowMaster; }
  get detailsInvalid(): boolean {
    return !!(this.selected || this.selectedInput) && this.parseDetails() === null;
  }
  get hasUnfinishedDetails(): boolean {
    return this.detailsInvalid || this.invalidDetails.size > 0;
  }
  get dataSources(): string[] {
    const inputs = this.workflow?.inputs.map(field => 'inputs.' + field.name) ?? [];
    const outputs = this.steps.filter(step => step !== this.selected).flatMap(step => {
      const name = step['saveAs'] ?? step['output'];
      if (typeof name !== 'string' || !name) return [];
      const path = 'variables.' + name;
      if (step.type !== 'api' || step['action']) return [path];
      const mapping = step['responseMapping'] as { strategy?: string } | undefined;
      if (step['responseFormat'] === 'xml') return [path + '.xml', path];
      if (mapping?.strategy === 'field') return step['responseFormat'] === 'json' ? [path] : [path + '.raw.xml', path];
      return [path + '.response', path];
    });
    return [...new Set([...outputs, ...inputs])];
  }
  get outputFields(): ResultField[] {
    const key = JSON.stringify([this.xmlTemplates.length, this.steps.filter(step => step.type === 'api').map(step => [
      step['saveAs'], step['output'], step['responseFormat'], step['responseMapping'], step['xml_templates'], step['action'],
    ])]);
    if (key !== this.resultFieldCache.key) {
      this.resultFieldCache = { key, fields: apiResultFields(this.steps, this.xmlTemplates) };
    }
    return this.resultFieldCache.fields;
  }
  get displayDataPaths(): string[] {
    return [...new Set([...this.outputFields.map(field => field.dataPath), ...this.dataSources])];
  }
  get displayAttributes(): ResultField[] {
    return this.outputFields.filter(field => field.dataPath === this.displaySource);
  }
  get decisionAttributes(): ResultField[] {
    return this.outputFields.filter(field => field.dataPath === this.decisionSource);
  }
  get decisionNeedsValue(): boolean {
    return !['empty', 'notEmpty', 'truthy'].includes(this.decisionOperator);
  }

  get displayMappings(): { key: string; expression: string }[] {
    const step = this.selected;
    if (!step || (!step['displayFields'] && step.type !== 'return' && step.type !== 'transform')) return [];
    const fields = this.resultMappings(step);
    const mappings = fields && typeof fields === 'object' && !Array.isArray(fields)
      ? Object.entries(fields).map(([key, expression]) => ({
        key, expression: typeof expression === 'string' ? expression : JSON.stringify(expression),
      })) : [];
    const xml = Object.entries((step['xmlFields'] ?? {}) as Record<string, { source: string; path: string }>)
      .map(([key, field]) => ({ key, expression: `${field.source} → ${field.path}` }));
    return [...mappings, ...xml];
  }

  private resultMappings(step?: DesignerStep): Record<string, unknown> {
    const fields = step?.type === 'transform' && !step['displayFields'] ? step['values'] || step['with'] : step?.['with'];
    return fields && typeof fields === 'object' && !Array.isArray(fields) ? fields as Record<string, unknown> : {};
  }
  get graph() {
    const key = JSON.stringify(this.steps.map(step => [step.id, step.type, step['gotoStep'], step['onSuccess'],
      step['onTrue'], step['onFalse'], step['onFailure'], step['onError']]));
    if (this.layoutKey !== key || this.layout.nodes.some((node, index) => node.step !== this.steps[index])) {
      this.layout = workflowGraph(this.steps);
      this.layoutKey = key;
    }
    return this.layout;
  }
  get filteredTypes() {
    return [...this.stepTypes, ...(this.stepTypes.includes('display') ? ['show-message'] : []),
      ...(this.stepTypes.includes('condition') ? ['check-text'] : []),
      ...(this.stepTypes.includes('action') ? ['prompt-transform'] : [])]
      .filter(type => this.stepLabels[type]?.toLowerCase().includes(this.query.trim().toLowerCase()));
  }

  paletteType(step: DesignerStep): string {
    if (step.type === 'display' && step['presentation'] === 'message') return 'show-message';
    if (step.type === 'condition' && (step['condition'] as { operator?: string } | undefined)?.operator === 'hasText') return 'check-text';
    if (step.type === 'action' && step['action'] === 'transform_with_prompt') return 'prompt-transform';
    return step.type;
  }

  nodeTarget(step: DesignerStep): string {
    const service = (step['interop'] as { serviceName?: unknown } | undefined)?.serviceName;
    const target = service || step['toolName'] || step['flow'] || step['flowId'];
    return typeof target === 'string' ? target : '';
  }

  nodeTitle(step: DesignerStep): string {
    if (step.type === 'api' && (!step.name?.trim() || step.name === this.stepLabels['api'])) {
      return this.nodeTarget(step) || this.stepLabels['api'];
    }
    return step.name?.trim() || step.id;
  }

  nodeSubtitle(step: DesignerStep): string {
    const target = this.nodeTarget(step);
    return target && target !== this.nodeTitle(step) ? target : this.stepLabels[this.paletteType(step)] || step.type;
  }

  get workflowPrompt(): string {
    const ai = this.workflow?.['ai'] as { prompt?: unknown } | undefined;
    return typeof ai?.prompt === 'string' ? ai.prompt : '';
  }

  setWorkflowPrompt(prompt: string): void {
    if (!this.workflow) return;
    const ai = { ...(this.workflow['ai'] as Record<string, unknown> | undefined) };
    if (prompt.trim()) ai['prompt'] = prompt;
    else delete ai['prompt'];
    if (Object.keys(ai).length) this.workflow['ai'] = ai;
    else delete this.workflow['ai'];
  }
  ngOnInit(): void {
    this.load("id: new-workflow\nname: New Workflow\nversion: '1.0'\ntrigger:\n  type: ui\n  ui: common-ui\n  event: execute\ninputs: []\nsteps:\n- id: end\n  name: End Workflow\n  type: end\n");
    this.loadTemplates();
  }

  renameWorkflow(name: string): void {
    if (!this.workflow) return;
    const slug = (value: string) => value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 100).replace(/-$/, '');
    if (this.workflow.id === (slug(this.workflow.name || '') || 'new-workflow')) {
      this.workflow.id = slug(name) || 'new-workflow';
    }
    this.workflow.name = name;
  }

  // Parse YAML through the backend and initialize the editable designer model.
  load(source: string): void {
    this.busy = true;
    this.error = '';
    this.api.parseDesigner(source).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: result => {
        this.workflow = result.workflow;
        this.resultFieldCache = { key: '', fields: [] };
        this.invalidDetails.clear();
        this.actions = result.actions;
        this.stepTypes = result.stepTypes;
        this.index = -1;
        this.inputIndex = -1;
        this.preview = source;
        this.canvasView = 'canvas';
        this.connection = null;
        this.status = '';
        this.busy = false;
      },
      error: error => this.fail(error),
    });
  }

  openTemplates(): void {
    this.showTemplates = true;
    if (!this.templates.length) this.loadTemplates();
  }

  private loadTemplates(): void {
    this.api.definitions().pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: templates => { this.templates = templates; },
      error: () => {},
    });
  }

  useTemplate(id: string, name: string): void {
    this.busy = true;
    this.api.generateWorkflow(name, '', id).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: draft => { this.showTemplates = false; this.load(draft.yaml); },
      error: error => this.fail(error),
    });
  }

  promptForDraft(): void {
    if (!this.aiPrompt.trim() || this.busy) return;
    this.aiError = '';
    this.aiDraft = '';
    this.aiPreviewTab = 'yaml';
    this.busy = true;
    this.api.generateWorkflow(this.aiPrompt, this.aiXml, '').pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: draft => {
        this.aiDraft = draft.yaml;
        this.aiDraftCode = draft.code;
        this.aiDraftPreview = JSON.stringify(draft.preview, null, 2);
        this.busy = false;
      },
      error: error => {
        this.busy = false;
        this.aiError = typeof error.error?.detail === 'string' ? error.error.detail : 'Could not generate a draft.';
      },
    });
  }

  // Request a workflow draft from the description and load the returned YAML.
  loadPromptDraft(): void {
    if (!this.aiDraft || this.busy) return;
    this.load(this.aiDraft);
    this.promptOpen = false;
  }

  fieldOptions(field: DesignerInput): { label: string }[] {
    const options = field['options'] as { items?: { label: string }[] } | undefined;
    return Array.isArray(options?.items) ? options.items : [];
  }

  async importFile(event: Event): Promise<void> {
    const picker = event.target as HTMLInputElement;
    const file = picker.files?.[0];
    picker.value = '';
    if (!file) return;
    if (file.size > 250_000) { this.error = 'Choose a YAML file smaller than 250 KB.'; return; }
    try { this.load(await file.text()); } catch { this.error = 'The file could not be read.'; }
  }

  // Parse the selected step's additional properties as JSON.
  private parseDetails(): Record<string, unknown> | null {
    try {
      const value: unknown = JSON.parse(this.details);
      return value && !Array.isArray(value) && typeof value === 'object' ? value as Record<string, unknown> : null;
    } catch {
      return null;
    }
  }

  // Apply edited properties to the selected item before continuing.
  private commitDetails(allowUnfinished = false): boolean {
    const current = this.selected ?? this.selectedInput;
    if (!current) return true;
    const extras = this.parseDetails();
    if (!extras) {
      this.invalidDetails.set(current, this.details);
      if (!allowUnfinished) this.error = 'Additional properties must contain a valid JSON object.';
      return allowUnfinished;
    }
    this.invalidDetails.delete(current);
    const explicit = this.selected ? ['id', 'name', 'type'] : ['name', 'label', 'type', 'required'];
    const properties = Object.fromEntries(explicit.filter(key => key in current).map(key => [key, current[key]]));
    for (const key of Object.keys(current)) delete current[key];
    for (const [key, value] of Object.entries({ ...extras, ...properties })) {
      Object.defineProperty(current, key, { value, writable: true, enumerable: true, configurable: true });
    }
    return true;
  }

  discardInvalidDetails(): void {
    const current = this.selected ?? this.selectedInput;
    if (current) this.invalidDetails.delete(current);
    this.syncSelectedDetails();
    this.error = '';
  }

  // Update the current selection and load its editable properties.
  select(step: number, field = -1): void {
    this.commitDetails(true);
    this.index = step;
    this.inputIndex = field;
    this.syncSelectedDetails();
    const source = this.selected?.['source'];
    const label = this.selected?.['displayAs'];
    this.displaySource = typeof source === 'string' ? source.replace(/^\$\{([^{}]+)\}$/, '$1') : '';
    this.displayLabel = typeof label === 'string' ? label : 'displayedResult';
    this.selectedDisplayFields = [];
    this.messageText = typeof source === 'string' ? source : '';
    const messagePath = /^\$\{((?:variables|inputs|steps)(?:\.[@\w-]+)+)\}$/.exec(this.messageText);
    this.messageMode = messagePath ? 'output' : 'text';
    this.messageSource = messagePath?.[1] ?? '';
    const condition = this.selected?.['condition'] as { field?: string; left?: string } | undefined;
    this.textPath = typeof condition?.field === 'string' ? condition.field
      : typeof condition?.left === 'string' ? condition.left.replace(/^\$\{([^{}]+)\}$/, '$1') : '';
    const transform = this.selected?.['with'] as { data?: unknown; prompt?: unknown } | undefined;
    this.transformSource = typeof transform?.data === 'string' ? transform.data.replace(/^\$\{([^{}]+)\}$/, '$1') : '';
    this.transformPrompt = typeof transform?.prompt === 'string' ? transform.prompt : '';
    const saveAs = this.selected?.['saveAs'];
    this.transformOutput = typeof saveAs === 'string' ? saveAs : 'transformedResult';
    this.view = 'properties';
    this.error = '';
    if (this.selected?.type === 'condition') this.loadDecision(this.selected);
    this.reshapeOutput = typeof saveAs === 'string' ? saveAs : '';
    if (this.selected && ['api', 'display', 'return', 'condition', 'transform'].includes(this.selected.type)) this.loadXmlTemplates();
  }

  private loadDecision(step: DesignerStep): void {
    const condition = (step['condition'] || step['equals'] || {}) as Record<string, unknown>;
    const xml = condition['xmlField'] as { source?: string; path?: string } | undefined;
    const left = condition['left'] ?? condition['field'] ?? condition['path'];
    const unwrap = (value: string) => value.replace(/^\$\{([^{}]+)\}$/, '$1');
    this.decisionPath = xml?.source ? unwrap(xml.source) : typeof left === 'string' ? unwrap(left) : '';
    const field = this.outputFields.find(item => item.source === this.decisionPath && item.xmlPath === xml?.path);
    this.decisionSource = field?.dataPath ?? (xml?.source ? this.decisionPath : '');
    this.decisionField = field ? resultFieldId(field) : xml?.path ? `${this.decisionPath}|${xml.path}` : '';
    const operator = condition['operator'] ?? ('left' in condition ? 'equals' : 'notEmpty');
    this.decisionOperator = operator === '==' ? 'equals' : operator === '!=' ? 'notEquals'
      : operator === 'isEmpty' ? 'empty' : operator === 'not_empty' ? 'notEmpty'
      : this.decisionOperators.some(item => item.id === operator) ? String(operator) : 'equals';
    const value = condition['right'] ?? condition['value'];
    this.decisionValueType = typeof value === 'number' ? 'number' : typeof value === 'boolean' ? 'boolean'
      : typeof value === 'string' && /^\$\{[^{}]+\}$/.test(value) ? 'reference' : 'text';
    this.decisionValue = value == null ? '' : unwrap(String(value));
  }

  // Change the data source used to populate the decision field picker.
  chooseDecisionSource(path: string): void {
    this.decisionSource = path;
    this.decisionPath = path;
    this.decisionField = '';
  }

  chooseDecisionField(id: string): void {
    this.decisionField = id;
    this.decisionPath = this.decisionAttributes.find(field => resultFieldId(field) === id)?.source ?? this.decisionSource;
  }

  // Write the selected comparison into the step definition.
  applyDecision(step: DesignerStep): void {
    const dataPath = /^(?:variables|inputs|steps)(?:\.[@#:\w-]+)+$/;
    const path = this.decisionPath.trim();
    if (!dataPath.test(path)) {
      this.error = 'Choose an attribute or enter a workflow data path.';
      return;
    }
    if (this.decisionAttributes.length && !this.decisionField && path === this.decisionSource) {
      this.error = 'Choose an attribute from the selected data source.';
      return;
    }
    let right: string | number | boolean = this.decisionValue;
    if (this.decisionNeedsValue && this.decisionValueType === 'number') {
      right = Number(this.decisionValue);
      if (!this.decisionValue.trim() || !Number.isFinite(right)) {
        this.error = 'Enter a valid comparison number.';
        return;
      }
    } else if (this.decisionNeedsValue && this.decisionValueType === 'boolean') {
      right = this.decisionValue === 'true';
    } else if (this.decisionNeedsValue && this.decisionValueType === 'reference') {
      const reference = this.decisionValue.trim().replace(/^\$\{([^{}]+)\}$/, '$1');
      if (!dataPath.test(reference)) { this.error = 'Enter a valid comparison data path.'; return; }
      right = '${' + reference + '}';
    }
    if (!this.commitDetails()) return;
    const field = this.decisionAttributes.find(item => resultFieldId(item) === this.decisionField);
    const source = '${' + path + '}';
    const xmlPath = field?.xmlPath ?? (this.decisionField.startsWith(path + '|') ? this.decisionField.split('|')[1] : '');
    step['condition'] = {
      operator: this.decisionOperator,
      ...(xmlPath ? { xmlField: { source, path: xmlPath } } : { left: source }),
      ...(this.decisionNeedsValue ? { right } : {}),
    };
    this.syncSelectedDetails();
    this.error = '';
    this.status = 'Decision condition configured.';
  }

  // Write the prompt text, source value, and result variable into the step.
  applyPromptTransform(step: DesignerStep): void {
    const path = this.transformSource.trim().replace(/^\$\{([^{}]+)\}$/, '$1');
    const output = this.transformOutput.trim();
    if (!/^(?:variables|inputs|steps)(?:\.[@\w-]+)+$/.test(path) || !this.transformPrompt.trim() || !/^[A-Za-z_][\w-]*$/.test(output)) {
      this.error = 'Enter a data path, prompt, and output variable name.';
      return;
    }
    if (!this.commitDetails()) return;
    step['with'] = { data: '${' + path + '}', prompt: this.transformPrompt.trim() };
    step['saveAs'] = output;
    this.syncSelectedDetails();
    this.error = '';
    this.status = 'Prompt transformation configured.';
  }

  // Apply the message settings to the selected display step.
  applyMessage(step: DesignerStep): void {
    const path = this.messageSource.trim().replace(/^\$\{([^{}]+)\}$/, '$1');
    if (this.messageMode === 'output' && !/^(?:variables|inputs|steps)(?:\.[@\w-]+)+$/.test(path)) {
      this.error = 'Choose a workflow output or enter a path such as variables.transformedResult.';
      return;
    }
    const source = this.messageMode === 'output' ? '${' + path + '}' : this.messageText;
    if (!source.trim() || !this.commitDetails()) return;
    step['source'] = source;
    step['presentation'] = 'message';
    delete step['with'];
    this.syncSelectedDetails();
    this.error = '';
    this.status = 'Message configured.';
  }

  applyTextCheck(step: DesignerStep): void {
    const source = this.textPath.trim();
    if (!/^(?:variables|inputs|steps)(?:\.[\w-]+)+$/.test(source)) {
      this.error = 'Enter a text path such as inputs.userText.';
      return;
    }
    if (!this.commitDetails()) return;
    step['condition'] = { field: source, operator: 'hasText' };
    step['saveAs'] ||= 'isValid';
    this.syncSelectedDetails();
    this.error = '';
    this.status = 'Text check configured.';
  }

  chooseDisplayPath(path: string): void {
    this.displaySource = path;
    const step = this.selected;
    const mappings = Object.values(this.resultMappings(step));
    const xml = Object.values((step?.['xmlFields'] ?? {}) as Record<string, { source: string; path: string }>);
    this.selectedDisplayFields = this.displayAttributes.filter(field => {
      const expression = '${' + field.source + '}';
      return field.xmlPath ? xml.some(item => item.source === expression && item.path === field.xmlPath)
        : mappings.includes(expression);
    }).map(resultFieldId);
  }

  toggleDisplayField(id: string, selected: boolean): void {
    this.selectedDisplayFields = selected
      ? [...new Set([...this.selectedDisplayFields, id])]
      : this.selectedDisplayFields.filter(field => field !== id);
  }

  // Turn the selected output fields into display or return mappings.
  applyDisplaySettings(step: DesignerStep): void {
    let source = this.displaySource.trim();
    const label = this.displayLabel.trim();
    source = source.replace(/^\$\{([^{}]+)\}$/, '$1');
    if (!/^(?:variables|inputs|steps)(?:\.[@#:\w-]+)+$/.test(source)
        || (!this.displayAttributes.length && !/^[a-zA-Z_][\w-]*$/.test(label))) {
      this.error = 'Choose a data path such as variables.api_response and enter a result key.';
      return;
    }
    const output = this.reshapeOutput.trim();
    if (step.type === 'transform' && output && !/^[A-Za-z_][\w-]*$/.test(output)) {
      this.error = 'Enter a valid output variable name.';
      return;
    }
    if (!this.commitDetails()) return;
    const expression = '${' + source + '}';
    const available = this.displayAttributes;
    const namedResult = step.type === 'return' || step.type === 'transform' || !!step['displayFields'];
    if (available.length) {
      const mappings = { ...(namedResult ? this.resultMappings(step) : {}) };
      const xml = { ...(namedResult ? step['xmlFields'] as Record<string, { source: string; path: string }> : {}) };
      const matchingKeys = new Map<string, string>();
      for (const field of available) {
        const fieldExpression = '${' + field.source + '}';
        const existingKey = field.xmlPath
          ? Object.keys(xml).find(key => xml[key].source === fieldExpression && xml[key].path === field.xmlPath)
          : Object.keys(mappings).find(key => mappings[key] === fieldExpression);
        if (existingKey) {
          matchingKeys.set(resultFieldId(field), existingKey);
          delete mappings[existingKey];
          delete xml[existingKey];
        }
      }
      for (const field of available.filter(item => this.selectedDisplayFields.includes(resultFieldId(item)))) {
        const existingKey = matchingKeys.get(resultFieldId(field));
        let key = existingKey ?? field.key;
        let suffix = 2;
        while (Object.hasOwn(mappings, key) || Object.hasOwn(xml, key)) key = `${field.key}${suffix++}`;
        const fieldExpression = '${' + field.source + '}';
        if (field.xmlPath) Object.defineProperty(xml, key, { value: { source: fieldExpression, path: field.xmlPath }, enumerable: true, writable: true, configurable: true });
        else Object.defineProperty(mappings, key, { value: fieldExpression, enumerable: true, writable: true, configurable: true });
      }
      step['displayFields'] = true;
      step['with'] = mappings;
      if (Object.keys(xml).length) step['xmlFields'] = xml;
      else delete step['xmlFields'];
      delete step['source'];
      delete step['displayAs'];
    } else if (namedResult) {
      const mappings = { ...this.resultMappings(step) };
      Object.defineProperty(mappings, label, { value: expression, enumerable: true, writable: true, configurable: true });
      if (step['xmlFields']) delete (step['xmlFields'] as Record<string, unknown>)[label];
      step['with'] = mappings;
      step['displayFields'] = true;
    } else {
      step['source'] = expression;
      step['displayAs'] = label;
      delete step['with'];
    }
    if (step.type === 'transform') {
      delete step['values'];
      if (output) step['saveAs'] = output;
      else delete step['saveAs'];
    }
    this.syncSelectedDetails();
    this.error = '';
    this.status = step.type === 'transform' ? 'Transform fields configured.'
      : step.type === 'return' ? 'Return fields configured.' : 'Result display configured.';
  }

  removeDisplayMapping(step: DesignerStep, key: string): void {
    if (!this.commitDetails()) return;
    delete this.resultMappings(step)[key];
    if (step['xmlFields']) delete (step['xmlFields'] as Record<string, unknown>)[key];
    this.syncSelectedDetails();
  }

  private loadXmlTemplates(): void {
    if (this.xmlTemplates.length || this.xmlTemplatesLoading) return;
    this.xmlTemplatesLoading = true;
    this.xmlTemplatesError = '';
    this.api.designerXmlTemplates().pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: templates => { this.xmlTemplates = templates; this.resultFieldCache = { key: '', fields: [] }; this.xmlTemplatesLoading = false; },
      error: () => { this.xmlTemplatesError = 'The XML template list could not be loaded.'; this.xmlTemplatesLoading = false; },
    });
  }

  // Copy the API or Flow settings and XML template references into the selected step.
  applyApiSettings(step: DesignerStep, settings: ApiXmlSettings): void {
    if (!this.commitDetails()) return;
    if (settings.toolName) step['toolName'] = settings.toolName;
    else delete step['toolName'];
    if (settings.interop) step['interop'] = settings.interop;
    else delete step['interop'];
    step['saveAs'] = settings.saveAs;
    step['xml_templates'] = settings.xml_templates;
    if (settings.parameters && Object.keys(settings.parameters).length) {
      step['parameters'] = { ...(step['parameters'] as Record<string, unknown> | undefined), ...settings.parameters };
    }
    if (settings.responseFormat) step['responseFormat'] = settings.responseFormat;
    else delete step['responseFormat'];
    this.syncSelectedDetails();
    this.status = '';
  }

  rememberXmlTemplate(template: DesignerXmlTemplate): void {
    this.xmlTemplates.push(template);
  }

  private uniqueName(base: string, existing: string[]): string {
    let sequence = 1;
    while (existing.includes(`${base}${sequence}`)) sequence++;
    return `${base}${sequence}`;
  }

  // Create and insert a configured node of the requested palette type.
  addStep(type: string, position?: number): void {
    const runtimeType = type === 'show-message' ? 'display' : type === 'check-text' ? 'condition'
      : type === 'prompt-transform' ? 'action' : type;
    if (!this.workflow || this.busy || !this.stepTypes.includes(runtimeType)) return;
    this.commitDetails(true);
    const id = this.uniqueName(`${type}-`, this.steps.map(step => step.id));
    const finalStep = this.steps.findIndex(step => step.type === 'end' || step.type === 'return');
    const index = position ?? (finalStep === -1 ? this.steps.length : finalStep);
    const parameters: Record<string, unknown> = {
      action: { action: this.actions[0] ?? '', with: {} },
      api: { toolName: '', xml_templates: { request: { file: '', id: '' } }, parameters: {}, responseFormat: 'json' },
      condition: { condition: { left: '', operator: 'equals', right: '' } },
      flow: { flow: '', inputs: {} }, set: { with: {} }, transform: { with: {} },
      display: { with: {} }, return: { with: {} },
      'show-message': { presentation: 'message', source: 'Thank you for your response.' },
      'check-text': { condition: { field: 'inputs.userText', operator: 'hasText' }, saveAs: 'isValid' },
      'prompt-transform': { action: 'transform_with_prompt', with: { data: '', prompt: '' }, saveAs: 'transformedResult' },
    }[type] ?? {};
    this.steps.splice(index, 0, { id, name: this.stepLabels[type], type: runtimeType, ...parameters });
    this.index = -1;
    this.inputIndex = -1;
    this.select(index);
  }

  // Add a workflow input control and its initial settings.
  addField(type: string, label: string): void {
    if (!this.workflow || this.busy) return;
    this.commitDetails(true);
    const name = this.uniqueName('field', this.workflow.inputs.map(field => field.name));
    const options = type === 'select' ? { options: { items: [{ label: 'Option 1', value: 'option-1' }] } } : {};
    const index = this.workflow.inputs.push({ name, label, type, required: false, ...options }) - 1;
    this.index = -1;
    this.inputIndex = -1;
    this.select(-1, index);
  }

  startDrag(event: DragEvent, index: number): void {
    this.dragging = index;
    event.dataTransfer?.setData('application/x-workflow-step', String(index));
  }

  dragPalette(event: DragEvent, type: string): void {
    this.dragging = -1;
    event.dataTransfer?.setData('application/x-workflow-type', type);
  }

  // Handle a palette or canvas drop at the requested step position.
  drop(event: DragEvent, at: number): void {
    event.preventDefault();
    if (this.connection && event.dataTransfer?.getData('application/x-workflow-connection')) {
      if (this.steps[at]) this.connectTo(this.steps[at]);
      return;
    }
    const type = event.dataTransfer?.getData('application/x-workflow-type');
    if (type) this.addStep(type, at);
    else if (this.dragging !== -1) this.moveStep(this.dragging, Math.min(at, this.steps.length - 1));
    this.dragging = -1;
  }

  moveStep(from: number, to: number): void {
    if (from === to || to < 0 || to >= this.steps.length || this.busy) return;
    this.commitDetails(true);
    const [step] = this.steps.splice(from, 1);
    this.steps.splice(to, 0, step);
    this.index = -1;
    this.inputIndex = -1;
    this.select(to);
  }

  removeSelection(): void {
    if (this.busy) return;
    if (this.index >= 0) {
      this.removeStep(this.index);
      return;
    }
    const current = this.selectedInput;
    if (current) {
      this.invalidDetails.delete(current);
      this.workflow?.inputs.splice(this.inputIndex, 1);
    }
    this.index = -1;
    this.inputIndex = -1;
    this.connection = null;
    this.select(-1);
  }

  // Delete the selected workflow step and update associated designer state.
  removeStep(index: number): void {
    const step = this.steps[index];
    if (this.busy || !step) return;
    if (this.selected !== step) this.commitDetails(true);
    this.invalidDetails.delete(step);
    this.steps.splice(index, 1);
    for (const remaining of this.steps) {
      for (const key of ['gotoStep', 'onSuccess', 'onFailure', 'onTrue', 'onFalse', 'onError']) {
        const connection = remaining[key];
        if (transitionId(connection) !== step.id) continue;
        if (connection && typeof connection === 'object') {
          const metadata = { ...connection as Record<string, unknown> };
          delete metadata['gotoStep'];
          if (Object.keys(metadata).length) {
            remaining[key] = metadata;
            continue;
          }
        }
        delete remaining[key];
      }
    }
    this.index = -1;
    this.inputIndex = -1;
    this.connection = null;
    this.dragging = -1;
    this.select(Math.min(index, this.steps.length - 1));
    this.status = `Removed ${step.name || step.id}.`;
  }

  startConnection(source: DesignerStep, port: Port, event?: DragEvent): void {
    if (this.busy || !this.commitDetails()) return;
    this.connection = { source, port };
    event?.dataTransfer?.setData('application/x-workflow-connection', port);
  }

  chooseNode(index: number): void {
    if (this.connection) this.connectTo(this.steps[index]);
    else this.select(index);
  }

  connectTo(target: DesignerStep): void {
    if (!this.connection || !target.id) return;
    if (this.setConnection(this.connection.source, this.connection.port, target.id)) this.connection = null;
  }

  // Store a destination step for the selected output port.
  setConnection(source: DesignerStep, port: Port, target: string): boolean {
    if (!this.commitDetails()) return false;
    const previous = source[port];
    const metadata = previous && typeof previous === 'object' ? { ...previous as Record<string, unknown> } : {};
    delete metadata['gotoStep'];
    if (target) source[port] = port === 'onError' || (port !== 'gotoStep' && Object.keys(metadata).length)
      ? { ...metadata, gotoStep: target } : target;
    else if (Object.keys(metadata).length) source[port] = metadata;
    else delete source[port];
    if (!target) {
      const fallback = port === 'onFalse' ? 'onFailure' : port === 'onError' ? '' : 'onSuccess';
      if (fallback) {
        const handler = source[fallback];
        if (handler && typeof handler === 'object') {
          const remaining = { ...handler as Record<string, unknown> };
          delete remaining['gotoStep'];
          if (Object.keys(remaining).length) source[fallback] = remaining;
          else delete source[fallback];
        } else {
          delete source[fallback];
        }
      }
    }
    this.syncSelectedDetails();
    this.status = '';
    return true;
  }

  updateSubflow(step: DesignerStep, id: string): void {
    if (!this.commitDetails()) return;
    step['flow'] = id;
    delete step['flowId'];
    this.syncSelectedDetails();
    this.status = '';
  }

  private syncSelectedDetails(): void {
    const current = this.selected ?? this.selectedInput;
    const unfinished = current ? this.invalidDetails.get(current) : undefined;
    if (unfinished !== undefined) { this.details = unfinished; return; }
    const explicit = this.selected ? ['id', 'name', 'type'] : ['name', 'label', 'type', 'required'];
    this.details = JSON.stringify(Object.fromEntries(Object.entries(current ?? {}).filter(([key]) => !explicit.includes(key))), null, 2);
  }

  // Send the current model to the backend and use the returned YAML for preview, saving, or export.
  validate(mode: 'preview' | 'yaml' | 'apply' | 'export' = 'preview'): void {
    if (!this.workflow || this.busy || !this.commitDetails()) return;
    const pending = this.invalidDetails.keys().next().value;
    if (pending) {
      this.select(this.steps.indexOf(pending as DesignerStep), this.workflow.inputs.indexOf(pending as DesignerInput));
      this.error = 'Fix or discard the highlighted JSON edit before validating or saving.';
      return;
    }
    this.busy = true;
    this.error = '';
    this.status = '';
    this.api.validateDesigner(this.workflow).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: result => {
        this.busy = false;
        this.preview = result.yaml;
        this.status = 'Workflow is valid.';
        if (mode === 'apply' && this.canSave) this.save(result.yaml);
        else if (mode === 'export') this.download(result.yaml);
        else if (mode === 'yaml') this.canvasView = 'yaml';
        else this.view = 'yaml';
      },
      error: error => this.fail(error),
    });
  }

  private save(yaml: string): void {
    this.busy = true;
    this.api.createFlow(yaml).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: result => { this.busy = false; this.saved.emit(result.path); },
      error: error => this.fail(error),
    });
  }

  private download(yaml: string): void {
    const url = URL.createObjectURL(new Blob([yaml], { type: 'application/yaml' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `${this.workflow?.id || 'workflow'}.yaml`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  private fail(error: { error?: { detail?: unknown } }): void {
    this.busy = false;
    this.error = typeof error.error?.detail === 'string' ? error.error.detail : 'The workflow could not be processed.';
  }
}
