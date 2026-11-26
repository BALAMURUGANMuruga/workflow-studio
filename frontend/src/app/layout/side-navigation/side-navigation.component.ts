import { Component, input, output } from '@angular/core';
import type { AuthUser } from '../../services/auth.service';
import { RouterLink, RouterLinkActive } from '@angular/router';

@Component({
  selector: 'app-side-navigation',
  standalone: true,
  imports: [RouterLink, RouterLinkActive],
  host: { class: 'sidebar' },
  templateUrl: './side-navigation.component.html',
  styleUrl: './side-navigation.component.scss'
})
export class SideNavigationComponent {
  isDarkMode = input(false);
  readonly currentTab = input.required<string>();
  readonly isMaster = input.required<boolean>();
  readonly currentUser = input.required<AuthUser | null>();
  readonly tabChange = output<string>();
  readonly signOut = output<void>();
  readonly fullscreenToggle = output<void>();
  themeToggle = output<void>();

  isProfileMenuOpen = false;

  // Open or close the profile actions without changing the current workspace.
  toggleProfileMenu(): void {
    this.isProfileMenuOpen = !this.isProfileMenuOpen;
  }

  closeProfileMenu(): void {
    this.isProfileMenuOpen = false;
  }

  // Notify the parent shell that the theme toggle was selected.
  toggleTheme(): void {
    this.themeToggle.emit();
  }
}
