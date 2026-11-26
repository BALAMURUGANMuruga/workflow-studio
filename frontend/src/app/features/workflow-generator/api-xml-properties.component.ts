// Edit API call settings, resolve request and response template IDs, and show XML for the selected step.
import { Component, DestroyRef, effect, inject, input, output } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { NgTemplateOutlet } from '@angular/common';
import { forkJoin } from 'rxjs';
import { DesignerStep, DesignerXmlTemplate, WorkflowApiService } from '../../services/workflow-api.service';
import { AuthService } from '../../services/auth.service';

type XmlKind = 'request' | 'response';
type XmlSpec = { file?: string; id?: string; xml?: string; source?: string };
type TemplateMode = 'new' | 'existing' | 'workflow';
export interface ApiXmlSettings {
  toolName: string;
  interop?: { type: 'flow'; serviceName: string };
  responseFormat?: 'json' | 'xml';
  xml_templates: { request: XmlSpec; response?: XmlSpec };
  parameters?: Record<string, unknown>;
  saveAs: string;
}

@Component({
  selector: 'app-api-xml-properties',
  imports: [FormsModule, NgTemplateOutlet],
  templateUrl: './api-xml-properties.component.html',
  styleUrl: './api-xml-properties.component.scss',
})
export class ApiXmlPropertiesComponent {
  private readonly api = inject(WorkflowApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly auth = inject(AuthService);
  readonly step = input.required<DesignerStep>();
  readonly templates = input<DesignerXmlTemplate[]>([]);
  readonly disabled = input(false);
  readonly dataSources = input<string[]>([]);
  readonly confirmed = output<ApiXmlSettings>();
  apiName = '';
  callType: 'api' | 'flow' = 'api';
  serviceName = '';
  outputName = '';
  format: '' | 'json' | 'xml' = '';
  requestXml = '';
  requestPath = '';
  responseXml = '';
  requestKey = '';
  responseKey = '';
  requestReference: XmlSpec = {};
  responseReference: XmlSpec = {};
  parameterValues: Record<string, unknown> = {};
  preview = '';
  error = '';
  feedback = '';
  working = false;
  sourceMode: Record<XmlKind, TemplateMode> = { request: 'new', response: 'new' };
  templateDrafts = { request: { id: '', name: '' }, response: { id: '', name: '' } };
  private addedTemplates: DesignerXmlTemplate[] = [];
  readonly templateSaved = output<DesignerXmlTemplate>();
  private requestSequence = 0;

  constructor() {
    effect(() => {
      const step = this.step();
      const catalog = this.templates();
      this.requestSequence++;
      this.working = false;
      this.error = '';
      this.preview = '';
      this.feedback = '';
      this.apiName = typeof step['toolName'] === 'string' ? step['toolName'] : '';
      const invocation = step['interop'] as ApiXmlSettings['interop'];
      this.callType = invocation?.type === 'flow' ? 'flow' : 'api';
      this.serviceName = invocation?.serviceName ?? '';
      const output = step['saveAs'] ?? step['output'];
      this.outputName = typeof output === 'string' && output ? output
        : (String(step.id ?? '').replace(/[^a-zA-Z0-9_]/g, '_') || 'api') + '_response';
      this.format = step['responseFormat'] === 'json' || step['responseFormat'] === 'xml' ? step['responseFormat'] : '';
      const specs = step['xml_templates'] as ApiXmlSettings['xml_templates'] | undefined;
      const request = specs?.request ?? {};
      const response = specs?.response ?? {};
      this.requestReference = request.id && !request.file ? { ...request, file: 'input-templates' } : request;
      this.responseReference = response.id && !response.file ? { ...response, file: 'output-templates' } : response;
      this.parameterValues = { ...(step['parameters'] as Record<string, unknown> | undefined) };
      this.requestXml = this.xmlFor(this.requestReference, 'request', catalog);
      this.requestPath = this.requestReference.source?.replace(/^\$\{([^{}]+)\}$/, '$1') ?? '';
      this.responseXml = this.xmlFor(this.responseReference, 'response', catalog);
      this.requestKey = this.requestReference.xml ? '' : this.key(this.requestReference);
      this.responseKey = this.responseReference.xml ? '' : this.key(this.responseReference);
      this.sourceMode = { request: this.requestPath ? 'workflow' : this.requestKey ? 'existing' : 'new', response: this.responseKey ? 'existing' : 'new' };
      this.templateDrafts = { request: { id: '', name: '' }, response: { id: '', name: '' } };
    });
  }

  // Resolve XML from an inline specification or a shared catalog template.
  private xmlFor(spec: XmlSpec, kind: XmlKind, catalog: DesignerXmlTemplate[]): string {
    return spec.xml ?? catalog.find(item => item.kind === kind && item.file === spec.file
      && (!spec.id || item.id === spec.id))?.xml ?? '';
  }

  key(spec: XmlSpec): string { return spec.file ? `${spec.file}:${spec.id ?? ''}` : ''; }
  options(kind: XmlKind) {
    return [...new Map([...this.templates(), ...this.addedTemplates].filter(template => template.kind === kind)
      .map(template => [this.key(template), template])).values()];
  }
  get canSaveTemplates(): boolean { return this.auth.isWorkflowMaster; }
  get hasCallName(): boolean { return !!(this.callType === 'flow' ? this.serviceName.trim() : this.apiName.trim()); }
  get parameterNames(): string[] {
    return [...new Set(Array.from(this.requestXml.matchAll(/\{\{([A-Za-z][A-Za-z0-9_]*)\}\}/g), match => match[1]))];
  }

  // Load the selected template into its request or response editor.
  useTemplate(kind: XmlKind, key: string): void {
    const template = this.options(kind).find(item => this.key(item) === key);
    if (kind === 'request') {
      this.requestKey = key;
      this.requestReference = template ? { file: template.file, id: template.id } : {};
      this.requestXml = template?.xml ?? '';
    } else {
      this.responseKey = key;
      this.responseReference = template ? { file: template.file, id: template.id } : {};
      this.responseXml = template?.xml ?? '';
    }
    this.clearFeedback();
  }

  clearFeedback(): void { this.preview = ''; this.feedback = ''; this.error = ''; }

  // Switch between the new and existing template editing modes.
  setTemplateMode(kind: XmlKind, mode: TemplateMode): void {
    this.sourceMode[kind] = mode;
    if (mode === 'new') {
      if (kind === 'request') { this.requestKey = ''; this.requestReference = {}; }
      else { this.responseKey = ''; this.responseReference = {}; }
    }
    this.clearFeedback();
  }

  // Save one template through the backend and update the editor with the returned reference.
  saveTemplate(kind: XmlKind): void {
    if (this.working || !this.canSaveTemplates) return;
    const id = this.templateDrafts[kind].id.trim();
    const name = this.templateDrafts[kind].name.trim();
    const xml = kind === 'request' ? this.requestXml : this.responseXml;
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(id) || !name || !xml.trim()) {
      this.error = 'Enter a lowercase kebab-case ID, a name, and XML.';
      return;
    }
    this.working = true;
    this.clearFeedback();
    const sequence = ++this.requestSequence;
    this.api.saveDesignerXmlTemplate({ id, name, kind, xml }).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: record => {
        if (sequence !== this.requestSequence) return;
        this.addedTemplates = [...this.addedTemplates, record];
        if (record.kind === 'request') {
          this.requestReference = { file: record.file, id: record.id };
          this.requestKey = this.key(record);
        } else {
          this.responseReference = { file: record.file, id: record.id };
          this.responseKey = this.key(record);
        }
        this.sourceMode[kind] = 'existing';
        this.working = false;
        this.feedback = `Template ${record.name} saved.`;
        this.templateSaved.emit(record);
      },
      error: error => {
        if (sequence !== this.requestSequence) return;
        this.working = false;
        this.error = typeof error.error?.detail === 'string' ? error.error.detail : 'The XML template could not be saved.';
      },
    });
  }

  // Send edited XML to the parser and display its JSON representation.
  previewJson(xml: string): void {
    const sequence = ++this.requestSequence;
    this.working = true;
    this.clearFeedback();
    this.api.designerXmlPreview(xml).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: result => {
        if (sequence !== this.requestSequence) return;
        this.preview = JSON.stringify(result.value, null, 2);
        this.working = false;
      },
      error: error => {
        if (sequence !== this.requestSequence) return;
        this.error = typeof error.error?.detail === 'string' ? error.error.detail : 'XML could not be converted.';
        this.working = false;
      },
    });
  }

  // Validate the form and emit the API settings to the parent designer.
  confirm(): void {
    const name = this.callType === 'api' ? this.apiName.trim() : '';
    if (!this.hasCallName || this.working) return;
    const serviceName = this.serviceName.trim();
    if (this.sourceMode.request === 'existing' && !this.requestKey) {
      this.error = 'Select an existing request template or switch to New template.';
      return;
    }
    if (this.sourceMode.response === 'existing' && !this.responseKey) {
      this.error = 'Select an existing response template or switch to New template.';
      return;
    }
    const saveAs = this.outputName.trim();
    if (!saveAs || (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(saveAs) && saveAs !== this.step()['saveAs'] && saveAs !== this.step()['output'])) {
      this.error = 'Enter a response variable name using letters, digits, or underscores.';
      return;
    }
    const requestPath = this.requestPath.trim().replace(/^\$\{([^{}]+)\}$/, '$1');
    if (this.sourceMode.request === 'workflow' && !/^(?:inputs|variables|steps)(?:\.[@\w-]+)+$/.test(requestPath)) {
      this.error = 'Choose a previous XML output or enter a path such as variables.api_response.xml.';
      return;
    }
    const request: XmlSpec = this.sourceMode.request === 'workflow'
      ? { source: '${' + requestPath + '}' }
      : this.xmlSpec(this.requestXml, this.requestReference, 'request');
    if (!request.xml && !request.file && !request.id && !request.source) {
      this.error = 'Provide request XML or select a request template.';
      return;
    }
    const response = this.xmlSpec(this.responseXml, this.responseReference, 'response');
    const parameters = request.source ? {} : Object.fromEntries(this.parameterNames.map(key => [key, this.parameterValues[key] ?? '']));
    const publish = () => {
      this.error = '';
      this.working = false;
      this.confirmed.emit({ toolName: name, interop: this.callType === 'flow' ? { type: 'flow', serviceName } : undefined,
        responseFormat: this.format || undefined, parameters, saveAs,
        xml_templates: { request, ...(response.file || response.id || response.xml ? { response } : {}) } });
      this.feedback = 'API settings added to the draft.';
    };
    const previews = [request.xml, response.xml].filter((xml): xml is string => !!xml);
    if (!previews.length) { publish(); return; }
    this.working = true;
    const sequence = ++this.requestSequence;
    forkJoin(previews.map(xml => this.api.designerXmlPreview(xml))).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: () => { if (sequence === this.requestSequence) publish(); },
      error: error => {
        if (sequence !== this.requestSequence) return;
        this.working = false;
        this.error = typeof error.error?.detail === 'string' ? error.error.detail : 'Check the request and response XML.';
      },
    });
  }

  // Build the workflow's XML specification from the editor and catalog state.
  private xmlSpec(xml: string, reference: XmlSpec, kind: XmlKind): XmlSpec {
    if (reference.file && xml === this.xmlFor(reference, kind, this.options(kind))) {
      const catalog = kind === 'request' ? 'input-templates' : 'output-templates';
      return reference.file === catalog && reference.id ? { id: reference.id } : reference;
    }
    return xml.trim() ? { xml } : {};
  }
}
