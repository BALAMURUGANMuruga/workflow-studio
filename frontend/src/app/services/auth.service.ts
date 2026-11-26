// Manage browser authentication state and add credentials to assistant API requests.
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, tap } from 'rxjs';

export interface LoginResponse { token: string; username?: string; }
export interface MessageResponse { message: string; }
export interface AuthUser {
  token: string;
  username: string;
  role: string;
  displayName: string;
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly apiUrl = '/operations-api/api/auth';
  private readonly tokenKey = 'authToken';
  private readonly workflowKey = 'workflow_studio_auth';
  private workflowSession = this.readWorkflowSession();
  constructor(private readonly http: HttpClient) {}

  get workflowUser(): AuthUser | null { return this.workflowSession; }
  get isWorkflowMaster(): boolean { return this.workflowSession?.role === 'master'; }

  // Authenticate against the workflow backend and retain the session according to the remember-me option.
  loginWorkflow(username: string, password: string, rememberMe: boolean): Observable<AuthUser> {
    return this.http.post<AuthUser>('/api/auth/login', { username, password }).pipe(
      tap(user => {
        if (!user?.token || !user.username) throw new Error('Incomplete assistant session.');
        localStorage.removeItem(this.workflowKey);
        sessionStorage.removeItem(this.workflowKey);
        (rememberMe ? localStorage : sessionStorage).setItem(this.workflowKey, JSON.stringify(user));
        this.workflowSession = user;
      }),
    );
  }

  // Remove the workflow session from browser storage.
  logoutWorkflow(): void {
    localStorage.removeItem(this.workflowKey);
    sessionStorage.removeItem(this.workflowKey);
    this.workflowSession = null;
    this.http.post('/api/auth/logout', {}).subscribe({ error: () => {} });
  }

  // Prepare workflow authorization headers for authenticated HTTP requests.
  workflowHeaders(): Record<string, string> {
    const token = this.workflowSession?.token;
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  // Read the saved workflow session and deserialize its user data.
  private readWorkflowSession(): AuthUser | null {
    try {
      const stored = sessionStorage.getItem(this.workflowKey) ?? localStorage.getItem(this.workflowKey);
      const user = stored ? JSON.parse(stored) : null;
      return user?.token && user?.username ? user : null;
    } catch {
      return null;
    }
  }

  // Authenticate a portal account and process the returned session token.
  login(credentials: { username: string; password: string }): Observable<LoginResponse> {
    return this.http.post<LoginResponse>(`${this.apiUrl}/login`, credentials).pipe(
      tap(response => {
        if (!response?.token) throw new Error('Login response did not contain token.');
        sessionStorage.setItem(this.tokenKey, response.token);
      })
    );
  }

  // Send new portal account details to the registration endpoint.
  register(data: { username: string; email: string; password: string }): Observable<MessageResponse> {
    return this.http.post<MessageResponse>(`${this.apiUrl}/register`, data);
  }
 requestPasswordOtp(email: string): Observable<MessageResponse> {
  return this.http.post<MessageResponse>(
    `${this.apiUrl}/forgot-password`,
    { email }
  );
}

resetPassword(data: {
  email: string;
  otp: string;
  newPassword: string;
}): Observable<MessageResponse> {
  return this.http.post<MessageResponse>(
    `${this.apiUrl}/reset-password`,
    data
  );
}
 
  logout(): void { sessionStorage.removeItem(this.tokenKey); }
  isLoggedIn(): boolean { return !!sessionStorage.getItem(this.tokenKey); }
  getToken(): string | null { return sessionStorage.getItem(this.tokenKey); }
}
