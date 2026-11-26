// Send plain-English scenarios or recorded steps to FastAPI. Return plans, browser recordings, and replay results.

import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, map } from 'rxjs';
import { AuthService } from './auth.service';

export interface OrderScenarioPlan {
  scenarios: {
    title: string;
    order_number: string;
    checks: { field: string; expected: string; instruction: string }[];
  }[];
  code: string;
}

export interface OrderScenarioRun extends OrderScenarioPlan {
  status: 'passed' | 'failed';
  outcomes: { name: string; status: 'passed' | 'failed'; detail: string }[];
  report: string;
}

export interface AutomationStep {
  action: string;
  selector?: string;
  locator?: string;
  value?: string;
  inputValue?: string;
  expected?: string;
  expectedResult?: string;
  url?: string;
  name?: string;
  metadata?: Record<string, unknown>;
  status?: string;
  recordedAt?: string;
  pageUrl?: string;
}

@Injectable({
  providedIn: 'root'
})
export class AutomationService {
  private http = inject(HttpClient);
  private auth = inject(AuthService);

  private readonly apiUrl = '/api/order-automation/scripts';

  // Send plain-English instructions and receive a plan with source code.
  previewOrderScenario(scenario: string): Observable<OrderScenarioPlan> {
    return this.http.post<OrderScenarioPlan>('/api/order-automation/preview', { scenario }, { headers: this.auth.workflowHeaders() });
  }

  // Run the scenario and receive outcome details and an HTML report.
  runOrderScenario(scenario: string): Observable<OrderScenarioRun> {
    return this.http.post<OrderScenarioRun>('/api/order-automation/run', { scenario }, { headers: this.auth.workflowHeaders() });
  }

  getTestCases(): Observable<any[]> {
    return this.http.get<any[]>(this.apiUrl, { headers: this.auth.workflowHeaders() });
  }

  getTestCase(id: string): Observable<any> {
    return this.http.get<any>(
      `${this.apiUrl}/${encodeURIComponent(id)}`, { headers: this.auth.workflowHeaders() }
    );
  }

  // Persist the recorded script and return the saved definition.
  saveTestCase(test: any): Observable<any> {
    return this.http.post<any>(this.apiUrl, test, { headers: this.auth.workflowHeaders() });
  }

  // Pass an optional password in the replay request body for this run.
  runTest(id: string, password = ''): Observable<any> {
    return this.http.post<any>(
      `${this.apiUrl}/${encodeURIComponent(id)}/run`,
      password ? { password } : {}, { headers: this.auth.workflowHeaders() }
    );
  }

  // Send the application URL and return the recording session ID.
  startRecording(url: string): Observable<{ id: string }> {
    return this.http.post<{ id: string }>('/api/order-automation/recordings', { url }, { headers: this.auth.workflowHeaders() });
  }

  // Stop by session ID and unwrap the captured step list from the HTTP response.
  stopRecording(id: string): Observable<AutomationStep[]> {
    return this.http.post<{ steps: AutomationStep[] }>(
      '/api/order-automation/recordings/' + encodeURIComponent(id) + '/stop', {}, { headers: this.auth.workflowHeaders() }
    ).pipe(map(result => result.steps));
  }
}
