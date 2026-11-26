// Apply portal authentication to the HTTP requests handled by this interceptor.
import { HttpInterceptorFn } from '@angular/common/http';
import { inject, PLATFORM_ID } from '@angular/core';
import { isPlatformBrowser } from '@angular/common';
import { AuthService } from './auth.service';

export const portalAuthInterceptor: HttpInterceptorFn = (request, next) => {
  if ((!request.url.startsWith('/operations-api/') && !request.url.startsWith('/operations-workflows/'))
      || !isPlatformBrowser(inject(PLATFORM_ID))) {
    return next(request);
  }
  const token = inject(AuthService).getToken();
  return next(token ? request.clone({ setHeaders: { Authorization: `Bearer ${token}` } }) : request);
};
