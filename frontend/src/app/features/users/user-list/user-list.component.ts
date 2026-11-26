import { Component, inject, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { UserService } from '../../../services/user.service';

interface ConnectionConfig {
  id: string;
  label: string;
  name: string;
  password: string;
  url: string;
  isEditing: boolean;
}

@Component({
  selector: 'app-user-list',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './user-list.component.html',
  styleUrl: './user-list.component.scss'
})
export class UserListComponent implements OnInit {

  private userService = inject(UserService);

  connections: ConnectionConfig[] = [
    {
      id: 'ApiId',
      label: 'API',
      name: '',
      password: '',
      url: '',
      isEditing: true
    },
    {
      id: 'ccId',
      label: 'Call Center',
      name: '',
      password: '',
      url: '',
      isEditing: true
    },
    {
      id: 'ohId',
      label: 'Order Hub',
      name: '',
      password: '',
      url: '',
      isEditing: true
    }
  ];

  successMessage = '';

  ngOnInit(): void {
    this.loadConfiguration();
  }

  // Load the current connection configuration into the page.
  loadConfiguration(): void {

    this.connections.forEach(config => {

      this.userService.getUserById(config.id).subscribe({

        next: (data) => {

          config.name = data.name || '';
          config.url = data.url || '';

          // Never display the existing password
          config.password = '';

          // Data already exists, so show Edit
          config.isEditing = false;
        },

        error: (error) => {

          console.error(
            `Failed to load ${config.id}`,
            error
          );

        }

      });

    });

  }

  private originalValues = new Map<string, {
  name: string;
  url: string;
}>();

  // Submit the edited connection configuration.
  save(config: ConnectionConfig): void {

    const request = {
      name: config.name,
      password: config.password,
      url: config.url
    };

    this.userService.updateUser(
      config.id,
      request
    ).subscribe({

      next: () => {

        config.isEditing = false;

        // Don't keep password in browser memory
        config.password = '';

        this.showSuccess(
          `${config.label} updated successfully`
        );

      },

      error: (error) => {

        console.error(
          `Failed to update ${config.id}`,
          error
        );

      }

    });

  }

  // Populate the editor with a selected configuration.
  edit(config: ConnectionConfig): void {

  this.originalValues.set(config.id, {
    name: config.name,
    url: config.url
  });

  config.password = '';
  config.isEditing = true;
  this.successMessage = '';
}

cancel(config: ConnectionConfig): void {

  const original = this.originalValues.get(config.id);

  if (original) {
    config.name = original.name;
    config.url = original.url;
  }

  config.password = '';
  config.isEditing = false;

  this.originalValues.delete(config.id);
}

  showSuccess(message: string): void {

    this.successMessage = message;

    setTimeout(() => {
      this.successMessage = '';
    }, 3000);

  }

}
