import { Component, input, output } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';

@Component({
  selector: 'app-side-navigation',
  standalone: true,
  imports: [RouterLink, RouterLinkActive],
  templateUrl: './side-navigation.html',
  styleUrl: './side-navigation.scss'
})
export class SideNavigationComponent {
  isDarkMode = input(false);
  themeToggle = output<void>();

  isProfileMenuOpen = false;

  toggleProfileMenu(): void {
    this.isProfileMenuOpen = !this.isProfileMenuOpen;
  }

  closeProfileMenu(): void {
    this.isProfileMenuOpen = false;
  }

  toggleTheme(): void {
    this.themeToggle.emit();
  }
}
