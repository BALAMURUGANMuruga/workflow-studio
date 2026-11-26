import { Component, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FloorplanActivityService } from '../../services/floorplan-activity.service';

@Component({
  selector: 'app-floorplan',
  imports: [DatePipe],
  templateUrl: './floorplan.component.html',
  styleUrl: './floorplan.component.scss',
})
export class FloorplanComponent {
  readonly activity = inject(FloorplanActivityService).activity;
  readonly selectedActivity = signal<number | null>(null);
  readonly paths = [
    {
      key: 'workflow',
      label: 'Run a workflow',
      steps: [
        { title: 'Chat or Workflow Studio', detail: 'Send a message or submit a workflow form.' },
        { title: 'FastAPI', detail: 'Authenticate the session and validate the request.' },
        { title: 'Python workflow executor', detail: 'Resolve inputs, load YAML and XML templates, and call Sterling when configured.' },
        { title: 'Workflow results', detail: 'Show the returned data, messages, and step timings.' },
      ],
    },
    {
      key: 'docs',
      label: 'Ask Docs',
      steps: [
        { title: 'Chat', detail: 'Send a question about the local documentation.' },
        { title: 'Chat service', detail: 'Route the question to the document assistant.' },
        { title: 'Document retrieval', detail: 'Rank local document passages and use them to answer the question.' },
        { title: 'Chat reply', detail: 'Show the answer and available source references.' },
      ],
    },
    {
      key: 'xml',
      label: 'Extract XML values',
      steps: [
        { title: 'Chat', detail: 'Paste XML and name the field to extract.' },
        { title: 'Chat service', detail: 'Separate the XML sample from the extraction request.' },
        { title: 'XPath evaluator', detail: 'Find the field path and evaluate it with lxml.' },
        { title: 'Extraction results', detail: 'Show the XPath, match count, and values.' },
      ],
    },
    {
      key: 'designer',
      label: 'Design a workflow',
      steps: [
        { title: 'YAML Designer', detail: 'Describe a draft workflow or assemble steps on the canvas.' },
        { title: 'Studio API', detail: 'Generate or validate the definition.' },
        { title: 'Workflow definitions', detail: 'Save the YAML and reference shared XML templates by ID.' },
        { title: 'Workflow Studio', detail: 'Open the saved workflow to inspect or run it.' },
      ],
    },
    {
      key: 'test',
      label: 'Run a browser test',
      steps: [
        { title: 'Automation Testing', detail: 'Write a scenario or select a saved recording.' },
        { title: 'Automation API', detail: 'Send the scenario or script to the Python runner.' },
        { title: 'Playwright', detail: 'Run the browser steps and evaluate the configured checks.' },
        { title: 'Test results', detail: 'Show step statuses for recordings or an HTML report for scenarios.' },
      ],
    },
  ];

  selectedPath = this.paths[0];

  inspectActivity(id: number, path: string): void {
    const opening = this.selectedActivity() !== id;
    this.selectedActivity.set(opening ? id : null);
    if (opening) this.selectedPath = this.paths.find(item => item.key === path) ?? this.selectedPath;
  }
}
