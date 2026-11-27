
import { Component } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { finalize } from 'rxjs';
import { AuthService } from '../../services/auth.service';
import { ForgotPasswordComponent } from '../forgot-password/forgot-password.component';
import { RegisterComponent } from '../register/register.component';
import { operationsAvailable } from '../../operations-availability';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [
    FormsModule,
    ForgotPasswordComponent,
    RegisterComponent
  ],
  templateUrl: './login.component.html',
  styleUrl: './login.component.scss'
})
export class LoginComponent {
  readonly operationsAvailable = operationsAvailable;
  username = '';
  password = '';
  showPassword = false;
  rememberMe = true;
  operationsAccount = false;
  errorMessage = '';
  loading = false;

  showForgotPassword = false;
  showRegister = false;

  constructor(
    private readonly authService: AuthService,
    private readonly router: Router,
    private readonly route: ActivatedRoute,
  ) {
    this.operationsAccount = this.operationsAvailable && !this.embeddedChat && route.snapshot.queryParamMap.get('account') === 'operations';
    if (router.currentNavigation()?.extras.state?.['expired']) {
      this.errorMessage = 'Your session has expired. Please sign in again.';
    }
  }

  get embeddedChat(): boolean {
    return this.route.snapshot.queryParamMap.get('view') === 'embedded-chat';
  }

  // Submit credentials using the selected account type and select the corresponding destination.
  login(): void {
    this.errorMessage = '';

    const username = this.username.trim();

    if (!username || !this.password) {
      this.errorMessage = 'Enter your username and password.';
      return;
    }

    this.loading = true;

    const operationsAccount = this.operationsAvailable && !this.embeddedChat && this.operationsAccount;
    const request = operationsAccount
      ? this.authService.login({ username, password: this.password })
      : this.authService.loginWorkflow(username, this.password, this.rememberMe);

    request
    .pipe(finalize(() => {
      this.loading = false;
    }))
    .subscribe({
      next: () => {
        if (operationsAccount) {
          window.location.assign('/operations/');
          return;
        }
        void this.router.navigate(['/'], { queryParams: this.embeddedChat ? { view: 'embedded-chat' } : {} });
      },
      error: (error) => {
        if (error.status === 401) {
          this.errorMessage = 'Invalid username or password.';
        } else if (!operationsAccount && error.status === 503 && typeof error.error?.detail === 'string') {
          this.errorMessage = error.error.detail;
        } else if (error.status === 0) {
          this.errorMessage =
            'Cannot connect to the server. Check that the backend is running.';
        } else {
          this.errorMessage = 'Login failed. Please try again.';
        }
      }
    });
  }

  // Open the password recovery panel.
  openForgotPassword(): void {
    this.showRegister = false;
    this.showForgotPassword = true;
  }

  // Open the registration panel.
  openRegister(): void {
    this.showForgotPassword = false;
    this.showRegister = true;
  }

  closePopup(): void {
    this.showForgotPassword = false;
    this.showRegister = false;
  }

  // Return to sign-in and populate the newly registered username.
  onRegistered(username: string): void {
    this.closePopup();
    this.operationsAccount = true;
    this.username = username;
    this.password = '';
  }
}
