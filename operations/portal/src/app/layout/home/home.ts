
import { Component, OnInit } from '@angular/core';
import {
  Router,
  RouterOutlet,
  NavigationEnd
} from '@angular/router';
import { filter } from 'rxjs/operators';

import { SideNavigationComponent } from '../side-navigation/side-navigation';
import { AuthService } from '../../services/auth.service';

@Component({
  selector: 'app-home',
  standalone: true,
  imports: [
    RouterOutlet,
    SideNavigationComponent
  ],
  templateUrl: './home.html',
  styleUrl: './home.scss'
})
export class HomeComponent implements OnInit {

  isDarkMode = this.readSavedTheme();
  pageTitle = 'Exception Management';

  constructor(
    private readonly authService: AuthService,
    private readonly router: Router
  ) {}

  ngOnInit(): void {
    this.router.events
      .pipe(
        filter(
          (event): event is NavigationEnd =>
            event instanceof NavigationEnd
        )
      )
      .subscribe(event => {
        this.updatePageTitle(event.urlAfterRedirects);
      });

    this.updatePageTitle(this.router.url);
  }

  private readSavedTheme(): boolean {
    try {
      return localStorage.getItem('ganalimura-theme') === 'dark';
    } catch {
      return false;
    }
  }

  toggleTheme(): void {
    this.isDarkMode = !this.isDarkMode;

    try {
      localStorage.setItem(
        'ganalimura-theme',
        this.isDarkMode ? 'dark' : 'light'
      );
    } catch {
      // Theme remains available for this session.
    }
  }

  updatePageTitle(url: string): void {
    if (url.includes('/exception')) {
      this.pageTitle = 'Exception Management';
    } else if (url.includes('/api')) {
      this.pageTitle = 'API Document';
    } else if (url.includes('/orders')) {
      this.pageTitle = 'Order Management';
    } else if (url.includes('/automation')) {
      this.pageTitle = 'Automation Testing';
    } else if (url.includes('/users')) {
      this.pageTitle = 'User Management';
    }
     else if (url.includes('/aichat')) {
      this.pageTitle = 'Ai-Chat';
    } else {
      this.pageTitle = 'Exception Management';
    }
  }

  

  logout(): void {
    this.authService.logout();
    void this.router.navigate(['/login']);
  }
}
