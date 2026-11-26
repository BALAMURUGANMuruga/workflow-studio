
import { Routes } from '@angular/router';

import { HomeComponent } from './layout/home/home';
import { Login } from './layout/login/login';
import { UserList } from './features/users/user-list/user-list';
import { Apidoc } from './features/apidocs/apidoc/apidoc';
import { AutomationTestingComponent } from './automation-testing/automation-testing';
import { ExceptionAssist } from './features/exception-assist/exception-assist';
import { Register } from './layout/register/register';
import { ForgotPassword } from './layout/forgot-password/forgot-password';
import { WorkflowChatComponent } from './features/workflow-chat/workflow-chat.component';

export const routes: Routes = [
  {
    path: 'login',
    component: Login
  },
 
  { path: 'register', component: Register },
  { path: 'forgot-password', component: ForgotPassword },
  {
    path: 'home',
    component: HomeComponent,
    children: [
      { path: 'aichat', component: WorkflowChatComponent },
      { path: 'exception', component: ExceptionAssist },
      { path: 'apidoc', component: Apidoc },
      { path: 'users', component: UserList },
      { path: 'automation', component: AutomationTestingComponent },
      { path: '', redirectTo: 'aichat', pathMatch: 'full' }
    ]
  },

  // { path: '', redirectTo: 'login', pathMatch: 'full' },
  //  { path: '**', redirectTo: 'login' }
  { path: '', redirectTo: 'home', pathMatch: 'full' },
   { path: '**', redirectTo: 'home' }
];
