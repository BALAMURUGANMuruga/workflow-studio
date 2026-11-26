import { Component } from '@angular/core';

@Component({
  selector: 'app-workflow-chat',
  template: '<iframe src="/?view=embedded-chat" title="Workflow Studio chat" allowfullscreen></iframe>',
  styles: `
    :host { display: block; width: 100%; height: 100%; min-height: 0; }
    iframe { display: block; width: 100%; height: 100%; border: 0; border-radius: 12px; }
  `,
})
export class WorkflowChatComponent {}
