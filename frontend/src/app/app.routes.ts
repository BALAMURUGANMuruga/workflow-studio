// Redirect the default path to chat and protect assistant routes with a workflow session check.
// Define Angular navigation and require an assistant session before opening the workspace.
import { inject } from '@angular/core';
import { CanActivateFn, Router, Routes } from '@angular/router';
import { LoginComponent } from './layout/login/login.component';
import { RegisterComponent } from './layout/register/register.component';
import { ForgotPasswordComponent } from './layout/forgot-password/forgot-password.component';
import { HomeComponent } from './layout/home/home.component';
import { AuthService } from './services/auth.service';
import { WorkflowStudioComponent } from './features/workflow-studio/workflow-studio.component';

const requireAssistantSession: CanActivateFn = (route) =>
  !!inject(AuthService).workflowUser ||
  inject(Router).createUrlTree(['/login'], { queryParams: route.queryParams });

export const routes: Routes = [
  {
    path: '',
    pathMatch: 'full',
    redirectTo: ({ queryParams }) => inject(Router).createUrlTree(['/home/aichat'], { queryParams }),
  },
  {
    path: 'home',
    component: HomeComponent,
    canActivate: [requireAssistantSession],
    children: [
      {
        path: '',
        pathMatch: 'full',
        redirectTo: ({ queryParams }) => inject(Router).createUrlTree(['/home/aichat'], { queryParams }),
      },
      { path: 'aichat', component: WorkflowStudioComponent, title: 'Ganalimura AI Assistant' },
      { path: 'workflow-generator', title: 'Workflow YAML Create AI', loadComponent: () => import('./features/workflow-generator/workflow-generator.component').then(module => module.WorkflowGeneratorComponent) },
      { path: 'exception', title: 'Exception Management', loadComponent: () => import('./features/exception-assist/exception-assist.component').then(module => module.ExceptionAssistComponent) },
      { path: 'automation', title: 'Automation Testing', loadComponent: () => import('./features/automation-testing/automation-testing.component').then(module => module.AutomationTestingComponent) },
      { path: 'floorplan', title: 'Floorplan', loadComponent: () => import('./features/floorplan/floorplan.component').then(module => module.FloorplanComponent) },
      { path: 'users', title: 'User Management', loadComponent: () => import('./features/users/user-list/user-list.component').then(module => module.UserListComponent) },
    ],
  },
  { path: 'login', component: LoginComponent },
  { path: 'register', component: RegisterComponent },
  { path: 'forgot-password', component: ForgotPasswordComponent },
  { path: '**', redirectTo: '' },
];
