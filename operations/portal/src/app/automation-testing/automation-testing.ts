
import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AutomationService } from '../services/automation';
import { AutomationStep } from '../services/automation';
import { Observable, from, map } from 'rxjs';

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
  imports: [CommonModule, FormsModule],
  templateUrl: './automation-testing.html',
  styleUrl: './automation-testing.scss'
})
export class AutomationTestingComponent implements OnInit {
  private automationService = inject(AutomationService);

  loading = false;
  recording = false;
  errorMessage = '';
  searchText = '';

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

  ngOnInit(): void {
    this.loadTestCases();
  }

  get filteredTests(): TestCase[] {
    const term = this.searchText.trim().toLowerCase();

    return this.testCases.filter(test =>
      test.name.toLowerCase().includes(term)
    );
  }

  loadTestCases(): void {
    this.automationService.getTestCases().subscribe({
      next: (cases: TestCase[]) => {
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
      id: this.selectedTest.id || undefined,
      name: this.selectedTest.name,
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
      error: (error: unknown) => {
        console.error('Saving test case failed:', error);
        this.errorMessage =
          'Cannot save test case. Check the Spring Boot backend.';
      }
    });
  }

  recordTest(): void {
    if (this.recording || !this.selectedTest) {
      return;
    }

    this.errorMessage = '';

    this.automationService.startRecording(this.targetUrl).subscribe({
      next: () => {
        this.recording = true;

        if (this.selectedTest) {
          this.selectedTest.startUrl = this.targetUrl;
          this.selectedTest.status = 'Recording';
        }
      },
    error: (error: unknown) => {
  console.error('Starting recording failed:', error);

  this.errorMessage =
    error instanceof Error
      ? error.message
      : 'Failed to connect to Chrome extension.';
}
    });
  }

stopRecording(): void {
  this.automationService.stopRecording().subscribe({
    next: (steps: AutomationStep[]) => {
      this.recording = false;

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

      this.selectedTest.status = 'Draft';
    },
    error: (error: unknown) => {
      console.error('Stop recording failed:', error);
      this.recording = false;
      this.errorMessage = 'Could not retrieve recorded steps.';
    }
  });
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

  runTest(): void {
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

    this.loading = true;
    this.errorMessage = '';

    this.automationService.runTest(this.selectedTest.id).subscribe({
      next: (result: any) => {
        if (!this.selectedTest) {
          this.loading = false;
          return;
        }

        this.selectedTest.status = result.status;
        this.selectedTest.updatedOn =
          new Date().toLocaleDateString('en-GB');

        if (Array.isArray(result.steps)) {
          this.selectedTest.steps = this.selectedTest.steps.map(
            (step, index) => {
              const resultStep = result.steps[index];

              return {
                ...step,
                status: resultStep?.status || step.status
              };
            }
          );
        }

        this.testCases = this.testCases.map(test =>
          test.id === this.selectedTest!.id
            ? this.selectedTest!
            : test
        );

        this.loading = false;
      },
      error: (error: unknown) => {
        console.error('Running test failed:', error);
        this.loading = false;
        this.errorMessage =
          'Execution failed. Verify the saved test and Playwright setup.';
      }
    });
  }

  trackByIndex(index: number): number {
    return index;
  }
}
