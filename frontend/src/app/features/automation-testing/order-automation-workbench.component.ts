// Accept plain-English order scenarios and display generated test code, results, and HTML reports.
import { Component, DestroyRef, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { AutomationService, OrderScenarioPlan, OrderScenarioRun } from '../../services/automation.service';

const SAMPLE = `# Confirm the released order
Open order TEST-1001
Verify order status is Released
Check customer name equals Sample Customer
Confirm order total is "$125.50"
Verify number of items is 2

# Confirm the held order
Find order TEST-1002
Verify status is Held
Confirm buyer is Test Buyer
Verify grand total is "$42.00"`;

@Component({
  selector: 'app-order-automation-workbench',
  imports: [FormsModule],
  templateUrl: './order-automation-workbench.component.html',
  styleUrl: './order-automation-workbench.component.scss',
})
export class OrderAutomationWorkbenchComponent {
  private readonly service = inject(AutomationService);
  private readonly destroyRef = inject(DestroyRef);
  readonly views = [
    { id: 'plan', label: 'Test plan' }, { id: 'code', label: 'Python code' }, { id: 'report', label: 'Run report' },
  ] as const;
  scenario = SAMPLE;
  plan: OrderScenarioPlan | null = null;
  run: OrderScenarioRun | null = null;
  view: 'plan' | 'code' | 'report' = 'plan';
  busy: 'preview' | 'run' | null = null;
  error = '';
  feedback = '';

  get checks(): number { return this.plan?.scenarios.reduce((count, scenario) => count + scenario.checks.length, 0) ?? 0; }
  get passed(): number { return this.run?.outcomes.filter(outcome => outcome.status === 'passed').length ?? 0; }
  get failed(): number { return this.run?.outcomes.filter(outcome => outcome.status === 'failed').length ?? 0; }

  edit(value: string): void {
    this.scenario = value;
    this.plan = null;
    this.run = null;
    this.error = '';
    this.feedback = '';
  }

  loadSample(): void { this.edit(SAMPLE); }

  // Send the scenario text to the backend for a structured plan and generated code.
  preview(): void {
    if (this.busy || !this.scenario.trim()) return;
    this.busy = 'preview';
    this.error = '';
    this.feedback = '';
    this.service.previewOrderScenario(this.scenario).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: plan => { this.plan = plan; this.view = 'plan'; this.busy = null; },
      error: error => this.fail(error),
    });
  }

  // Execute the scenario and show the returned results and HTML report.
  runTests(): void {
    if (this.busy || !this.scenario.trim()) return;
    this.busy = 'run';
    this.error = '';
    this.feedback = '';
    this.run = null;
    this.view = 'report';
    this.service.runOrderScenario(this.scenario).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: result => { this.plan = result; this.run = result; this.busy = null; },
      error: error => this.fail(error),
    });
  }

  // Copy the generated Playwright code to the clipboard.
  async copyCode(): Promise<void> {
    if (!this.plan) return;
    try {
      await navigator.clipboard.writeText(this.plan.code);
      this.feedback = 'Python code copied.';
    } catch {
      this.feedback = 'Clipboard unavailable. Use Download Python.';
    }
  }

  download(code = false): void {
    const content = code ? this.plan?.code : this.run?.report;
    if (!content) return;
    const href = URL.createObjectURL(new Blob([content], { type: 'application/octet-stream' }));
    const link = document.createElement('a');
    link.href = href;
    link.download = code ? 'test_order_details.py' : 'order-tests.html';
    link.click();
    setTimeout(() => URL.revokeObjectURL(href), 1000);
  }

  private fail(error: { error?: { detail?: unknown } }): void {
    this.busy = null;
    this.error = typeof error.error?.detail === 'string' ? error.error.detail : 'The order automation runner is unavailable.';
  }
}
