import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { bootstrapApplication } from '@angular/platform-browser';
import { provideRouter } from '@angular/router';
import { AppComponent } from './app/app.component';
import { routes } from './app/app.routes';
import { portalAuthInterceptor } from './app/services/portal-auth.interceptor';
import { floorplanActivityInterceptor } from './app/services/floorplan-activity.service';

bootstrapApplication(AppComponent, {
  providers: [provideRouter(routes), provideHttpClient(withInterceptors([portalAuthInterceptor, floorplanActivityInterceptor]))],
}).catch(console.error);
