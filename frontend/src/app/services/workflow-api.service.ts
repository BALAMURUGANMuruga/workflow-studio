// Use Angular HttpClient to send workflow and chat requests and return backend responses to the UI.
import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable } from 'rxjs';
import { AuthService } from './auth.service';

export interface WorkflowDraft {
  id: string;
  yaml: string;
  code: string;
  preview: Record<string, unknown>;
}

export interface DesignerStep extends Record<string, unknown> { id: string; name?: string; type: string; }
export interface DesignerInput extends Record<string, unknown> { name: string; label?: string; type: string; required?: boolean; }
export interface DesignerWorkflow extends Record<string, unknown> {
  id: string; name?: string; version: string; steps: DesignerStep[]; inputs: DesignerInput[];
}

export interface DesignerXmlTemplate {
  file: string;
  id: string;
  name?: string;
  kind: 'request' | 'response';
  xml: string;
}

@Injectable({ providedIn: 'root' })
export class WorkflowApiService {
  private http = inject(HttpClient);
  private auth = inject(AuthService);

  // Convert current session headers to the immutable Angular HttpHeaders format.
  private headers(): HttpHeaders {
    return new HttpHeaders(this.auth.workflowHeaders());
  }

  definitions(): Observable<any[]> {
    return this.http.get<any[]>('/api/definitions', { headers: this.headers() });
  }

  ui(id: string): Observable<any> {
    return this.http.get<any>(`/api/ui/${encodeURIComponent(id)}`, { headers: this.headers() });
  }

  flow(id: string): Observable<any> {
    return this.http.get<any>(`/api/flows/${encodeURIComponent(id)}`, { headers: this.headers() });
  }

  execute(uiId: string, inputs: Record<string, any>): Observable<any> {
    // Submit structured form values to the selected workflow UI endpoint.
    return this.http.post<any>(
      `/api/execute/${encodeURIComponent(uiId)}`,
      { inputs },
      { headers: this.headers() }
    );
  }

  chat(
    message: string,
    history: {
      role: string;
      content: string;
      needsInput?: boolean;
      flow?: string;
      inputName?: string;
    }[] = []
  ): Observable<any> {
    // Send the current prompt and prior turns to FastAPI as JSON.
    return this.http.post<any>(
      '/api/chat',
      { message, history },
      { headers: this.headers() }
    );
  }

  studioFiles(): Observable<any[]> {
    return this.http.get<any[]>('/api/studio/files', { headers: this.headers() });
  }

  // Pass a relative definition path as a query parameter and receive the file contents.
  studioRead(path: string): Observable<any> {
    return this.http.get<any>('/api/studio/file', {
      params: { path },
      headers: this.headers(),
    });
  }

  // Send source text, its path, and the creation mode to the backend.
  studioWrite(path: string, content: string, createOnly = false): Observable<any> {
    return this.http.post<any>(
      '/api/studio/file',
      { path, content, createOnly },
      { headers: this.headers() }
    );
  }

  packs(): Observable<any[]> {
    return this.http.get<any[]>('/api/packs', { headers: this.headers() });
  }

  // Send the description, sample XML, and template selection and return the typed draft.
  generateWorkflow(request: string, xml: string, templateId: string): Observable<WorkflowDraft> {
    return this.http.post<WorkflowDraft>('/api/studio/generate', { request, xml, templateId }, { headers: this.headers() });
  }

  createFlow(yaml: string): Observable<{ saved: boolean; id: string; path: string; yaml: string }> {
    return this.http.post<{ saved: boolean; id: string; path: string; yaml: string }>('/api/studio/generated-flows', { yaml }, { headers: this.headers() });
  }

  // Parse imported YAML and receive the workflow model and supported editor choices.
  parseDesigner(yaml: string): Observable<{ workflow: DesignerWorkflow; actions: string[]; stepTypes: string[] }> {
    return this.http.post<{ workflow: DesignerWorkflow; actions: string[]; stepTypes: string[] }>(
      '/api/studio/designer/parse', { yaml }, { headers: this.headers() });
  }

  // Validate the edited model and return normalized YAML.
  validateDesigner(workflow: DesignerWorkflow): Observable<{ yaml: string }> {
    return this.http.post<{ yaml: string }>('/api/studio/designer/validate', { workflow }, { headers: this.headers() });
  }

  designerXmlTemplates(): Observable<DesignerXmlTemplate[]> {
    return this.http.get<DesignerXmlTemplate[]>('/api/studio/designer/xml-templates', { headers: this.headers() });
  }

  // Send the template payload and return the assigned catalog reference.
  saveDesignerXmlTemplate(template: Omit<DesignerXmlTemplate, 'file'>): Observable<DesignerXmlTemplate> {
    return this.http.post<DesignerXmlTemplate>('/api/studio/designer/xml-templates', template, { headers: this.headers() });
  }

  designerXmlPreview(xml: string): Observable<{ value: unknown }> {
    return this.http.post<{ value: unknown }>('/api/studio/designer/xml-preview', { xml }, { headers: this.headers() });
  }

  health(): Observable<any> {
    return this.http.get<any>('/api/health');
  }
}
