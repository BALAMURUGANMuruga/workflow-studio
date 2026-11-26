import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, tap } from 'rxjs';

export interface LoginResponse { token: string; username?: string; }
export interface MessageResponse { message: string; }

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly apiUrl = '/operations-api/api/auth';
  private readonly tokenKey = 'authToken';
  constructor(private readonly http: HttpClient) {}

  login(credentials: { username: string; password: string }): Observable<LoginResponse> {
    return this.http.post<LoginResponse>(`${this.apiUrl}/login`, credentials).pipe(
      tap(response => {
        if (!response?.token) throw new Error('Login response did not contain token.');
        sessionStorage.setItem(this.tokenKey, response.token);
      })
    );
  }

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
