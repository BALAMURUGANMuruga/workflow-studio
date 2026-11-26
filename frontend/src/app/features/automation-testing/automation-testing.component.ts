// Manage editable recordings and show the results returned by the Playwright replay service.

import { CommonModule } from '@angular/common';
import { Component, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AutomationService } from '../../services/automation.service';
import { OrderAutomationWorkbenchComponent } from './order-automation-workbench.component';

export interface TestStep {
  action: string;
  selector: string;
  value?: string;
  expected?: string;
  url?: string;
  name?: string;
  metadata?: Record<string, unknown>;
  status?: string;
}

export interface TestCase {
  id: string;
  name: string;
  startUrl: string;
  steps: TestStep[];
  status?: string;
  updatedOn?: string;
  description?: string;
}

@Component({
  selector: 'app-automation-testing',
  standalone: true,
  imports: [CommonModule, FormsModule, OrderAutomationWorkbenchComponent],
  templateUrl: './automation-testing.component.html',
  styleUrl: './automation-testing.component.scss'
})
export class AutomationTestingComponent {
  private automationService = inject(AutomationService);

  loading = false;
  showReplayPassword = false;
  recording = false;
  recordingBusy = false;
  private recordingId = '';
  errorMessage = '';
  searchText = '';
  workspace: 'order' | 'recorded' = 'order';
  private openedRecorder = false;

  targetUrl = 'https://localhost:6443/icc/';

  testCases: TestCase[] = [
    {
      id: 'sample-1',
      name: 'Sign in to the order management application',
      startUrl: this.targetUrl,
      status: 'Draft',
      updatedOn: '14 Oct 2026',
      description: 'Sign in to the order management application and verify the dashboard.',
      steps: [
        {
          action: 'navigate',
          selector: '',
          url: this.targetUrl,
          expected: 'Login page should load',
          status: 'Pending'
        },
        {
          action: 'fill',
          selector: '#username',
          value: '',
          expected: 'Username entered',
          status: 'Pending'
        },
        {
          action: 'click',
          selector: 'button[type="submit"]',
          expected: 'Dashboard should appear',
          status: 'Pending'
        }
      ]
    },
    {
      id: 'sample-2',
      name: 'Search Order',
      startUrl: this.targetUrl,
      status: 'Draft',
      updatedOn: '13 Oct 2026',
      description: 'Search for an order.',
      steps: []
    },
    {
      id: 'sample-3',
      name: 'Create Order',
      startUrl: this.targetUrl,
      status: 'Draft',
      updatedOn: '12 Oct 2026',
      description: 'Create and validate an order.',
      steps: []
    },
    {
      id: 'sample-4',
      name: 'Cancel Order',
      startUrl: this.targetUrl,
      status: 'Draft',
      updatedOn: '11 Oct 2026',
      description: 'Cancel an existing order.',
      steps: []
    }
  ];

  selectedTest: TestCase | null = this.testCases[0];

  selectWorkspace(workspace: 'order' | 'recorded'): void {
    this.workspace = workspace;
    if (workspace === 'recorded' && !this.openedRecorder) {
      this.openedRecorder = true;
      this.loadTestCases();
    }
  }

  get filteredTests(): TestCase[] {
    const term = this.searchText.trim().toLowerCase();

    return this.testCases.filter(test =>
      test.name.toLowerCase().includes(term)
    );
  }

  // Load persisted recording definitions into the test list.
  loadTestCases(): void {
    this.automationService.getTestCases().subscribe({
      next: (cases: TestCase[]) => {
        if (!cases.length) return;
        this.testCases = cases;

        if (this.selectedTest) {
          this.selectedTest =
            cases.find(test => test.id === this.selectedTest?.id) ??
            cases[0] ??
            null;
        } else {
          this.selectedTest = cases[0] ?? null;
        }
      },
      error: (error: unknown) => {
        console.error('Loading test cases failed:', error);
      }
    });
  }

  selectTest(test: TestCase): void {
    this.showReplayPassword = false;
    this.selectedTest = test;
    this.errorMessage = '';
  }

  createTest(): void {
    const name = prompt('Enter a test case name:');

    if (!name?.trim()) {
      return;
    }

    const test: TestCase = {
      id: '',
      name: name.trim(),
      startUrl: this.targetUrl,
      steps: [],
      status: 'Draft',
      updatedOn: new Date().toLocaleDateString('en-GB'),
      description: ''
    };

    this.showReplayPassword = false;
    this.selectedTest = test;
    this.errorMessage = '';
  }

  addStep(): void {
    if (!this.selectedTest) {
      return;
    }

    this.selectedTest.steps.push({
      action: 'click',
      selector: '',
      value: '',
      expected: '',
      status: 'Pending'
    });
  }

  removeStep(index: number): void {
    this.selectedTest?.steps.splice(index, 1);
  }

  // Build the script payload from the selected test and send it to the backend.
  saveTest(): void {
    if (!this.selectedTest) {
      return;
    }

    if (!this.selectedTest.name.trim()) {
      this.errorMessage = 'Test name is required.';
      return;
    }

    this.errorMessage = '';

    const payload = {
      id: this.selectedTest.id?.startsWith('sample-') ? undefined : this.selectedTest.id || undefined,
      name: this.selectedTest.name,
      description: this.selectedTest.description,
      startUrl: this.selectedTest.startUrl || this.targetUrl,
      steps: this.selectedTest.steps.map(step => ({
        action: step.action,
        selector: step.selector || '',
        value: step.value || '',
        expected: step.expected || '',
        url: step.url || '',
        name: step.name || '',
        metadata: step.metadata
      }))
    };

    this.automationService.saveTestCase(payload).subscribe({
      next: (saved: TestCase) => {
        this.selectedTest = {
          ...saved,
          status: 'Draft',
          updatedOn: new Date().toLocaleDateString('en-GB'),
          description: this.selectedTest?.description || ''
        };

        const index = this.testCases.findIndex(
          test => test.id === saved.id
        );

        if (index >= 0) {
          this.testCases[index] = this.selectedTest;
          this.testCases = [...this.testCases];
        } else {
          this.testCases = [...this.testCases, this.selectedTest];
        }

        alert('Test case saved successfully.');
      },
      error: error => {
        console.error('Saving test case failed:', error);
        this.errorMessage =
          typeof error.error?.detail === 'string' ? error.error.detail : 'Could not save the recorded test.';
      }
    });
  }

  // Start a Playwright recording session for the selected application URL.
  recordTest(): void {
    if (this.recording || this.recordingBusy) return;
    const url = this.targetUrl.trim();
    if (!url) { this.errorMessage = 'Enter a recording URL.'; return; }
    this.showReplayPassword = false;
    this.errorMessage = '';
    this.recordingBusy = true;
    this.automationService.startRecording(url).subscribe({
      next: result => {
        this.recordingId = result.id;
        this.recording = true;
        this.recordingBusy = false;
        this.selectedTest ??= { id: '', name: 'Recorded browser test', startUrl: url, steps: [] };
        this.selectedTest.startUrl = url;
        this.selectedTest.status = 'Recording';
      },
      error: error => {
        this.recordingBusy = false;
        this.errorMessage = error.error?.detail || 'Could not start the Playwright recorder.';
      },
    });
  }

  // Stop the session and import its captured actions into the editor.
  stopRecording(): void {
    if (!this.recordingId || this.recordingBusy) return;
    this.recordingBusy = true;
    this.errorMessage = '';
    this.automationService.stopRecording(this.recordingId).subscribe({
      next: steps => {
        this.finishRecording();
        if (!this.selectedTest) return;
        this.selectedTest.steps = steps.map(step => ({
          action: step.action,
          selector: step.selector || step.locator || '',
          value: step.value || step.inputValue || '',
          expected: step.expected || step.expectedResult || '',
          url: step.url || '',
          name: step.name || '',
          metadata: step.metadata,
          status: step.status || 'Pending'
        }));
      },
      error: error => {
        this.finishRecording();
        this.errorMessage = error.error?.detail || 'Could not retrieve recorded steps.';
      },
    });
  }

  private finishRecording(): void {
    this.recording = false;
    this.recordingBusy = false;
    this.recordingId = '';
    if (this.selectedTest) this.selectedTest.status = 'Draft';
  }

  private normalizeAction(action: string): string {
    const actions: Record<string, string> = {
      'Open URL': 'navigate',
      navigate: 'navigate',
      Click: 'click',
      click: 'click',
      Type: 'fill',
      Fill: 'fill',
      fill: 'fill',
      type: 'fill',
      Select: 'select',
      select: 'select',
      'Verify Text': 'assertText',
      assertText: 'assertText',
      'Verify Visible': 'assertVisible',
      assertVisible: 'assertVisible',
      Screenshot: 'screenshot',
      screenshot: 'screenshot'
    };

    return actions[action] || action;
  }

  // Require a saved script and collect a per-run password when needed before requesting replay.
  runTest(password?: string): void {
    if (!this.selectedTest) {
      return;
    }

    if (
      !this.selectedTest.id ||
      this.selectedTest.id.startsWith('sample-')
    ) {
      this.errorMessage = 'Save this test case before running it.';
      return;
    }

    if (password === undefined && this.selectedTest.steps.some(
      step => step.action === 'fill' && step.metadata?.['environment']
    )) {
      this.errorMessage = '';
      this.showReplayPassword = true;
      return;
    }

    this.showReplayPassword = false;
    this.loading = true;
    this.errorMessage = '';

    const test = this.selectedTest;
    this.automationService.runTest(test.id, password).subscribe({
      next: (result: any) => {
        test.status = result.status;
        if (this.selectedTest === test) this.errorMessage = result.detail || '';
        test.updatedOn =
          new Date().toLocaleDateString('en-GB');

        if (Array.isArray(result.steps)) {
          test.steps = test.steps.map(
            (step, index) => {
              const resultStep = result.steps[index];

              return {
                ...step,
                status: resultStep?.status || 'Pending'
              };
            }
          );
        }

        this.testCases = this.testCases.map(item =>
          item.id === test.id ? test : item
        );

        this.loading = false;
      },
      error: error => {
        console.error('Running test failed:', error);
        this.loading = false;
        this.errorMessage =
          typeof error.error?.detail === 'string' ? error.error.detail :
            'Execution failed. Verify the saved test and Playwright setup.';
      }
    });
  }

  trackByIndex(index: number): number {
    return index;
  }
}
