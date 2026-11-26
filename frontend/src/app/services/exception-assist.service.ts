
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { webSocket, WebSocketSubject } from 'rxjs/webSocket';
import { AuthService } from './auth.service';

export interface ExceptionCode {
  code: string;
  description: string;
}

export interface ExceptionMessage {
  message: string;
  inputXml?: string;
  errorXml?: string;
}

@Injectable({
  providedIn: 'root'
})
export class ExceptionAssistService {

  private readonly baseUrl = '/operations-api';
  private get wsUrl(): string {
    const url = new URL('/operations-api/ws', window.location.origin);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    return url.href;
  }

  private socket?: WebSocketSubject<unknown>;

  constructor(private http: HttpClient, private auth: AuthService) {}

  // Fetch the codes displayed in the exception picker.
  getExceptionCodes(): Observable<ExceptionCode[]> {
    return this.http.get<ExceptionCode[]>(
      `${this.baseUrl}/oms/exception-codes`
    );
  }

  // Expose WebSocket messages as an RxJS observable for the exception page.
  startStream(code: string): Observable<ExceptionMessage> {
    this.closeSocket();

    this.socket = webSocket<unknown>({
      url: this.wsUrl,
      protocol: ['workflow-portal', this.auth.getToken() || 'missing-token'],
      openObserver: {
        next: () => {
          this.socket?.next(code);
        }
      },
      deserializer: event => JSON.parse(event.data)
    });

    return this.socket.asObservable() as Observable<ExceptionMessage>;
  }

  // Send a pause or resume command to the exception backend.
  control(action: 'pause' | 'resume'): Observable<unknown> {
    return this.http.post(`${this.baseUrl}/oms/control`, { action });
  }

  stopStream(): void {
    this.closeSocket();
  }

  // Close the existing WebSocket connection.
  private closeSocket(): void {
    if (this.socket) {
      this.socket.complete();
      this.socket = undefined;
    }
  }
}
