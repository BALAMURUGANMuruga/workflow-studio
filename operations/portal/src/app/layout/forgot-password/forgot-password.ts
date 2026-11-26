import { Component } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { finalize } from 'rxjs';
import { AuthService } from '../../services/auth.service';

@Component({
  selector: 'app-forgot-password',
  standalone: true,
  imports: [FormsModule, RouterLink],
  templateUrl: './forgot-password.html',
  styleUrl: '../auth-pages.scss'
})
export class ForgotPassword {
  email = '';
  otp = '';
  newPassword = '';
  confirmPassword = '';

  otpRequested = false;
  loading = false;
  errorMessage = '';
  successMessage = '';

  constructor(private readonly auth: AuthService) {}

  requestOtp(): void {
    this.errorMessage = '';
    this.successMessage = '';
    this.loading = true;

    this.auth.requestPasswordOtp(this.email.trim())
      .pipe(finalize(() => this.loading = false))
      .subscribe({
        next: response => {
          this.otpRequested = true;
          this.successMessage =
            response.message ||
            'If this email is registered, a reset code will be sent.';
        },
        error: () => {
          this.errorMessage =
            'Could not request a reset code. Please try again later.';
        }
      });
  }

  resetPassword(): void {
    this.errorMessage = '';
    this.successMessage = '';

    if (!/^\d{6}$/.test(this.otp)) {
      this.errorMessage = 'Enter the six-digit code from your email.';
      return;
    }

    if (this.newPassword.length < 12) {
      this.errorMessage =
        'Use a password with at least 12 characters.';
      return;
    }

    if (this.newPassword !== this.confirmPassword) {
      this.errorMessage = 'Passwords do not match.';
      return;
    }

    this.loading = true;

    this.auth.resetPassword({
      email: this.email.trim(),
      otp: this.otp,
      newPassword: this.newPassword
    })
      .pipe(finalize(() => this.loading = false))
      .subscribe({
        next: response => {
          this.successMessage =
            response.message || 'Password reset successfully. You can sign in now.';

          this.otpRequested = false;
          this.otp = '';
          this.newPassword = '';
          this.confirmPassword = '';
        },
       error: error => {
  console.error('Forgot password failed:', {
    status: error.status,
    message: error.message,
    response: error.error
  });

  this.errorMessage =
    error?.error?.detail ||
    error?.error?.message ||
    `Could not request reset code (HTTP ${error.status}).`;
}
      });
  }

  requestAnotherCode(): void {
    this.otpRequested = false;
    this.otp = '';
    this.newPassword = '';
    this.confirmPassword = '';
    this.errorMessage = '';
    this.successMessage = '';
  }
}