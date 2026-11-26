// Host the workflow designer in the assistant workspace.
import { Component, inject } from '@angular/core';
import { Router } from '@angular/router';
import { WorkflowDesignerComponent } from './workflow-designer.component';

@Component({
  selector: 'app-workflow-generator',
  imports: [WorkflowDesignerComponent],
  styles: [':host { display: block; height: 100%; min-height: 0; }'],
  template: '<app-workflow-designer (saved)="openStudio($event)" (dismissed)="cancel()" />',
})
export class WorkflowGeneratorComponent {
  private readonly router = inject(Router);

  openStudio(path: string): void {
    void this.router.navigate(['/home/aichat'], { queryParams: { workflowFile: path } });
  }

  cancel(): void {
    void this.router.navigate(['/home/aichat']);
  }
}
