
import { CommonModule } from '@angular/common';
import { Component } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { finalize } from 'rxjs';
import { AuthService } from '../../services/auth.service';
import { ForgotPassword } from '../forgot-password/forgot-password';
import { Register } from '../register/register';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    
    ForgotPassword,
    Register
  ],
  templateUrl: './login.html',
  styleUrl: './login.scss'
})
export class Login {
  username = '';
  password = '';
  showPassword = false;
  rememberMe = false;
  errorMessage = '';
  loading = false;

  showForgotPassword = false;
  showRegister = false;

  constructor(
    private readonly authService: AuthService,
    private readonly router: Router
  ) {}

  login(): void {
    this.errorMessage = '';

    const username = this.username.trim();

    if (!username || !this.password) {
      this.errorMessage = 'Enter your username and password.';
      return;
    }

    this.loading = true;

    this.authService.login({
      username,
      password: this.password
    })
    .pipe(finalize(() => {
      this.loading = false;
    }))
    .subscribe({
      next: () => {
        void this.router.navigate(['/home']);
      },
      error: (error) => {
        if (error.status === 401) {
          this.errorMessage = 'Invalid username or password.';
        } else if (error.status === 0) {
          this.errorMessage =
            'Cannot connect to the server. Check that the backend is running.';
        } else {
          this.errorMessage = 'Login failed. Please try again.';
        }
      }
    });
  }

  openForgotPassword(): void {
    this.showRegister = false;
    this.showForgotPassword = true;
  }

  openRegister(): void {
    this.showForgotPassword = false;
    this.showRegister = true;
  }

  closePopup(): void {
    this.showForgotPassword = false;
    this.showRegister = false;
  }
}
