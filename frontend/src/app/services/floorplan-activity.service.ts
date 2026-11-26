import { HttpErrorResponse, HttpInterceptorFn, HttpResponse } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { finalize, tap } from 'rxjs';

type Path = 'workflow' | 'docs' | 'xml' | 'designer' | 'test' | 'chat';
type Outcome = 'Running' | 'Completed' | 'Failed' | 'Needs input' | 'Cancelled';

interface Activity {
  id: number;
  path: Path;
  label: string;
  startedAt: number;
  outcome: Outcome;
  elapsedMs?: number;
  httpStatus?: number;
  steps?: { id: string; status: string }[];
}

@Injectable({ providedIn: 'root' })
export class FloorplanActivityService {
  private readonly entries = signal<Activity[]>([]);
  readonly activity = this.entries.asReadonly();
  private nextId = 0;

  start(path: Path, label: string): number {
    const id = ++this.nextId;
    const entry: Activity = { id, path, label, outcome: 'Running', startedAt: Date.now() };
    this.entries.update(entries => [entry, ...entries].slice(0, 30));
    return id;
  }

  finish(id: number, update: Partial<Activity>): void {
    this.entries.update(entries => entries.map(entry =>
      entry.id === id ? { ...entry, ...update } : entry
    ));
  }
}

function operation(url: string): { path: Path; label: string } | undefined {
  if (url === '/api/chat') return { path: 'chat', label: 'Chat request' };
  if (url.startsWith('/api/execute/')) return { path: 'workflow', label: 'Run workflow' };
  if (url === '/api/studio/generate') return { path: 'designer', label: 'Generate YAML' };
  if (url === '/api/studio/generated-flows' || url === '/api/studio/file') return { path: 'designer', label: 'Save definition' };
  if (url === '/api/studio/designer/validate') return { path: 'designer', label: 'Validate definition' };
  if (url.startsWith('/api/order-automation/')) {
    const label = url.endsWith('/run') ? 'Run browser test' :
      url.endsWith('/stop') ? 'Finish recording' :
        url.endsWith('/recordings') ? 'Start recording' :
          url.endsWith('/preview') ? 'Preview scenario' : 'Save script';
    return { path: 'test', label };
  }
  return undefined;
}

export const floorplanActivityInterceptor: HttpInterceptorFn = (request, next) => {
  const tracked = request.method === 'POST' ? operation(request.url) : undefined;
  if (!tracked) return next(request);

  const activity = inject(FloorplanActivityService);
  const id = activity.start(tracked.path, tracked.label);
  const start = performance.now();
  let settled = false;
  const finish = (update: Partial<Activity>) => {
    settled = true;
    activity.finish(id, { ...update, elapsedMs: Math.round(performance.now() - start) });
  };

  return next(request).pipe(
    tap({
      next: event => {
        if (!(event instanceof HttpResponse)) return;
        const body = event.body as {
          extraction?: unknown; sources?: unknown[]; flow?: string; needsInput?: boolean;
          success?: boolean; status?: string; steps?: { id?: string; status?: string }[];
        } | null;
        let path = tracked.path;
        let label = tracked.label;
        if (path === 'chat') {
          if (body?.extraction) { path = 'xml'; label = 'Extract XML values'; }
          else if (Array.isArray(body?.sources)) { path = 'docs'; label = 'Ask Docs'; }
          else if (body?.flow) { path = 'workflow'; label = 'Workflow from chat'; }
        }
        const failed = body?.success === false ||
          (typeof body?.status === 'string' && body.status.toLowerCase() === 'failed');
        const outcome = body?.needsInput ? 'Needs input' : failed ? 'Failed' : 'Completed';
        const steps = (path === 'workflow' || request.url.endsWith('/run')) && Array.isArray(body?.steps)
          ? body.steps.slice(0, 50).flatMap((step, index) => typeof step?.status === 'string'
            ? [{ id: step.id ?? `Step ${index + 1}`, status: step.status }] : [])
          : undefined;
        finish({ path, label, outcome, httpStatus: event.status, steps });
      },
      error: error => finish({ outcome: 'Failed', httpStatus: error instanceof HttpErrorResponse ? error.status : undefined }),
    }),
    finalize(() => { if (!settled) finish({ outcome: 'Cancelled' }); }),
  );
};
