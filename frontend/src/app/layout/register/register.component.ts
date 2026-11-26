
import { Component, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { finalize } from 'rxjs';
import { AuthService } from '../../services/auth.service';

@Component({
  selector: 'app-register',
  standalone: true,
  imports: [FormsModule, RouterLink],
  templateUrl: './register.component.html',
  styleUrl: '../auth-pages.scss'
})
export class RegisterComponent {
  readonly inDialog = input(false);
  readonly registered = output<string>();
  username = '';
  email = '';
  password = '';
  confirmPassword = '';

  errorMessage = '';
  successMessage = '';
  loading = false;

  constructor(
    private readonly auth: AuthService,
    private readonly router: Router
  ) {}

  // Validate registration fields and send the new account request.
  submit(): void {
    this.errorMessage = '';
    this.successMessage = '';

    if (this.password.length < 8) {
      this.errorMessage =
        'Use a password with at least 8 characters.';
      return;
    }

    if (this.password !== this.confirmPassword) {
      this.errorMessage = 'Passwords do not match.';
      return;
    }

    this.loading = true;

    this.auth.register({
      username: this.username.trim(),
      email: this.email.trim(),
      password: this.password
    })
    .pipe(finalize(() => this.loading = false))
    .subscribe({
      next: response => {
        this.successMessage =
          response.message || 'Account created. Please sign in.';

        if (this.inDialog()) {
          this.registered.emit(this.username.trim());
        } else {
          void this.router.navigate(['/login'], { queryParams: { account: 'operations' } });
        }
      },
     error: error => {
  console.error('Registration failed:', {
    status: error.status,
    message: error.message,
    response: error.error
  });

  this.errorMessage =
    error?.error?.detail ||
    error?.error?.message ||
    error?.message ||
    'Could not create account. Check the browser console.';
}
    });
  }
}
