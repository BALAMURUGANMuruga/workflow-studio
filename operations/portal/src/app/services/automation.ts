
import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, from } from 'rxjs';

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

interface RecorderResponse {
  ok: boolean;
  error?: string;
  test?: {
    name?: string;
    startUrl?: string;
    steps?: AutomationStep[];
  };
}

@Injectable({
  providedIn: 'root'
})
export class AutomationService {
  private http = inject(HttpClient);

  private readonly apiUrl = '/operations-api/api/tests';

  // Replace this with the ID shown on chrome://extensions.
  private readonly extensionId = 'ehjiknaeahcnnjfpcdhaoolaplndmmnm';

  getTestCases(): Observable<any[]> {
    return this.http.get<any[]>(this.apiUrl);
  }

  getTestCase(id: string): Observable<any> {
    return this.http.get<any>(
      `${this.apiUrl}/${encodeURIComponent(id)}`
    );
  }

  saveTestCase(test: any): Observable<any> {
    return this.http.post<any>(this.apiUrl, test);
  }

  runTest(id: string): Observable<any> {
    return this.http.post<any>(
      `${this.apiUrl}/${encodeURIComponent(id)}/run`,
      {}
    );
  }

  startRecording(targetUrl: string): Observable<RecorderResponse> {
    return from(this.sendRecorderMessage({
      type: 'START',
      targetUrl
    }));
  }

 stopRecording(): Observable<AutomationStep[]> {
  return new Observable<AutomationStep[]>(subscriber => {
    this.sendRecorderMessage({ type: 'STOP' })
      .then((response: RecorderResponse) => {
        if (!response.ok) {
          subscriber.error(
            new Error(response.error || 'Could not stop recording.')
          );
          return;
        }

        subscriber.next(response.test?.steps ?? []);
        subscriber.complete();
      })
      .catch(error => subscriber.error(error));
  });
}

  private sendRecorderMessage(
    message: Record<string, unknown>
  ): Promise<RecorderResponse> {
    return new Promise((resolve, reject) => {
if (!this.extensionId) {
  reject(new Error('Chrome Extension ID is missing.'));
  return;
}

      const chromeApi = (
        window as Window & {
          chrome?: {
            runtime?: {
              sendMessage?: (
                extensionId: string,
                message: unknown,
                callback: (response?: RecorderResponse) => void
              ) => void;
              lastError?: { message?: string };
            };
          };
        }
      ).chrome;

      // Web pages do not normally expose chrome.runtime.
      // Use the browser extension messaging API only when available.
      const runtime = chromeApi?.runtime;

      if (!runtime?.sendMessage) {
        reject(new Error(
          'Chrome Extension messaging is unavailable in this browser context.'
        ));
        return;
      }

      runtime.sendMessage(
        this.extensionId,
        message,
        response => {
          const error = runtime.lastError;

          if (error) {
            reject(new Error(error.message || 'Extension messaging failed.'));
            return;
          }

          if (!response?.ok) {
            reject(new Error(response?.error || 'Extension request failed.'));
            return;
          }

          resolve(response);
        }
      );
    });
  }
}
