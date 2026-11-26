// Manage chat and workflow state in Angular. Send user messages to the backend and render replies and execution results.
import { CommonModule } from '@angular/common';
import { Component, Injectable, OnDestroy, OnInit, computed, inject, output } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { WorkflowApiService } from '../../services/workflow-api.service';
import { AuthService } from '../../services/auth.service';
import { WorkflowDesignerComponent } from '../workflow-generator/workflow-designer.component';


interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
  time: Date;
  result?: any;
  uiDefinition?: any;
  needsInput?: boolean;
  flow?: string;
  inputName?: string;
  traceWorkflows?: { id: string; name: string }[];
  openTraceGenerator?: boolean;
}

interface Conversation {
  id: number;
  title: string;
  messages: ChatMessage[];
  time: Date;
}

@Injectable()
export class AssistantHistory {
  conversations: Conversation[] = [];
  nextId = 0;
  timeZone = 'Asia/Kolkata';
}

type StepTarget = string | { gotoStep?: string };
interface StudioStep {
  id: string;
  name?: string;
  type: string;
  action?: string;
  toolName?: string;
  gotoStep?: string;
  onSuccess?: StepTarget;
  onError?: StepTarget;
  onTrue?: StepTarget;
  onFalse?: StepTarget;
  onFailure?: StepTarget;
}
interface StudioFlow {
  id: string;
  name?: string;
  description?: string;
  version?: string;
  steps: StudioStep[];
}

@Component({
  selector: 'app-workflow-studio',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, WorkflowDesignerComponent],
  templateUrl: './workflow-studio.component.html',
  styleUrl: './workflow-studio.component.css',
  host: { '[class.embedded-chat]': 'embeddedChat()' },
})
export class WorkflowStudioComponent implements OnInit, OnDestroy {
  readonly Math = Math;
  private readonly route = inject(ActivatedRoute);
  private readonly queryParams = toSignal(this.route.queryParamMap, { requireSync: true });
  readonly embeddedChat = computed(() => this.queryParams().get('view') === 'embedded-chat');
  readonly sessionExpired = output<void>();
  private api=inject(WorkflowApiService);
  private auth=inject(AuthService);
  private readonly history = inject(AssistantHistory);
  private activeConversationId = this.history.nextId++;
  historyQuery = '';
  selectedConversationId = this.activeConversationId;
  studioQuery = '';
  studioView: 'canvas' | 'source' = 'canvas';
  studioFlow: StudioFlow | null = null;
  selectedStep: StudioStep | null = null;
  get isMaster(){return this.auth.isWorkflowMaster;}
  definitions:any[]=[]; ui:any=null; inputs:Record<string,any>={}; result:any=null;
  selected=''; loading=false; error=''; searchText=''; pageIndex=0; pageSize=10;
  sortKey=''; sortAsc=true; currentTab='run'; yamlView='ui';
  messages:ChatMessage[]=[]; messageDraft=''; showSettings=false;
  railOpen = typeof matchMedia === 'function' && matchMedia('(min-width: 901px)').matches;
  copyFeedback: { message: ChatMessage; label: string } | null = null;

  async copyReply(message: ChatMessage): Promise<void> {
    try {
      await navigator.clipboard.writeText(message.text);
      this.copyFeedback = { message, label: 'Copied' };
    } catch {
      this.copyFeedback = { message, label: 'Copy failed' };
    }
  }
  studioFiles:any[]=[]; studioPath=''; studioContent=''; studioType='yaml'; studioBusy=false; studioNotice=''; newFilePath=''; showNewFile=false;
  addingFlow = false;

  openAddedFlow(path: string): void {
    this.addingFlow = false;
    this.studioPath = '';
    this.refreshStudioFiles(path);
    this.api.definitions().subscribe({ next: definitions => { this.definitions = definitions; } });
  }
  ngOnInit(){
    this.bootstrapApp();
    const workflowFile = this.route.snapshot.queryParamMap.get('workflowFile');
    if (this.isMaster && workflowFile) {
      this.currentTab = 'designer';
      this.refreshStudioFiles(workflowFile);
    }
  }
  ngOnDestroy(){this.archiveConversation();}
  // Load workflow definitions and open the first available workflow form.
  bootstrapApp(){this.api.definitions().subscribe({next:d=>{this.definitions=d;if(d.length)this.loadUi(d[0].id);},error:e=>this.fail(e)});}
  // Archive the current conversation, then load the requested form. Ignore a response if the user selected another workflow in the meantime.
  loadUi(id:string){this.archiveConversation();this.activeConversationId=this.history.nextId++;this.selected=id;this.result=null;this.error='';this.messages=[];this.api.ui(id).subscribe({next:u=>{if(this.selected===id){this.ui=u;this.initializeInputs(u);}},error:e=>{if(this.selected===id)this.fail(e);}});}
  execute(){this.submitWorkflow();}
  sendMessage(text=this.messageDraft){
    // Trim composer text and reject empty or overlapping submissions.
    const prompt=text.trim();
    if(!prompt||this.loading)return;
    this.messageDraft='';
    this.error='';
    // Keep the recent conversation and any pending workflow input for a follow-up.
    const history=this.messages.slice(-12).map(m=>({
      role:m.role,
      content:m.text,
      needsInput:m.needsInput,
      flow:m.flow,
      inputName:m.inputName
    }));
    // Show the user's message immediately while the HTTP request is running.
    this.messages.push({role:'user',text:prompt,time:new Date()});
    this.loading=true;this.result=null;
    this.api.chat(prompt,history).subscribe({
      next:r=>{
        this.loading=false;this.error='';this.pageIndex=0;
        // Adopt the form returned for a newly selected workflow.
        const resultUi=r.ui||this.ui;
        if(resultUi&&resultUi.flow!==this.ui?.flow){this.ui=resultUi;this.selected=resultUi.flow;this.initializeInputs(resultUi);}
        // Render execution results with the result view. Clarifications and explanations use chat.
        const showResult=!r.needsInput&&r.kind!=='explanation';
        this.result=showResult?r:null;
        this.messages.push({
          role:'assistant',
          text:r.assistantMessage||r.message||'The request could not be completed.',
          time:new Date(),
          result:showResult?r:undefined,
          uiDefinition:showResult?this.resultUi(resultUi,r):resultUi,
          needsInput:r.needsInput===true,
          flow:r.flow,
          inputName:r.inputName,
          traceWorkflows:r.traceWorkflows,
          openTraceGenerator:r.openTraceGenerator
        });
      },
      error:e=>{
        this.loading=false;if(this.fail(e))return;
        this.messages.push({role:'assistant',text:this.error,time:new Date()});
      }
    });
  }
  clearChat(){
    this.archiveConversation();
    this.activeConversationId = this.history.nextId++;
    this.messages=[];
    this.result=null;
    this.error='';
    this.searchText='';
    this.pageIndex=0;
    this.showSettings=false;
    this.initializeInputs(this.ui);
  }
  private conversation(): Conversation | null {
    if (!this.messages.length) return null;
    const prompt = this.messages.find(message => message.role === 'user');
    return {
      id: this.activeConversationId,
      title: prompt?.text.split('\n')[0].slice(0, 80) || 'Workflow session',
      messages: [...this.messages],
      time: this.messages[this.messages.length - 1].time,
    };
  }

  private archiveConversation(): void {
    const current = this.conversation();
    if (current) this.history.conversations = [current, ...this.history.conversations.filter(entry => entry.id !== current.id)];
  }

  get matchingConversations(): Conversation[] {
    const current = this.conversation();
    const entries = current ? [current, ...this.history.conversations] : this.history.conversations;
    const query = this.historyQuery.trim().toLowerCase();
    return entries.filter(entry => entry.messages.some(message => message.text.toLowerCase().includes(query)));
  }

  get selectedConversation(): Conversation | undefined {
    const entries = this.matchingConversations;
    return entries.find(entry => entry.id === this.selectedConversationId) ?? entries[0];
  }

  restoreConversation(entry: Conversation): void {
    if (entry.id !== this.activeConversationId) {
      this.archiveConversation();
      this.history.conversations = this.history.conversations.filter(item => item.id !== entry.id);
      this.activeConversationId = entry.id;
      this.messages = [...entry.messages];
      this.result = null;
      this.error = '';
      this.messageDraft = '';
      this.showSettings = false;
    }
    this.setTab('run');
  }
  // Send structured form values to the workflow endpoint and display its execution response.
  private submitWorkflow(){
    this.loading=true;this.error='';this.result=null;
    this.api.execute(this.selected,this.inputs).subscribe({
      next:r=>{
        this.result=r;this.loading=false;this.pageIndex=0;
        this.messages.push({
          role:'assistant',
          text:r.message||'The workflow could not be completed.',
          time:new Date(),
          result:r,
          uiDefinition:this.resultUi(this.ui,r)
        });
      },
      error:e=>{
        this.loading=false;if(this.fail(e))return;
        this.messages.push({role:'assistant',text:this.error,time:new Date()});
      }
    });
  }
  // Reset the value map from form defaults. Checkboxes without a default start as false.
  private initializeInputs(ui:any){this.inputs={};for(const c of ui?.components||[])if(c.type==='form')for(const f of c.fields||[])this.inputs[f.name]=f.default??(f.type==='checkbox'?false:'');}
  // Build presentation metadata for the execution result.
  private resultUi(ui:any,result:any){
    const components=(ui?.components??[]).map((component:any)=>
      component.type==='data-table'&&!component.features
        ? {...component,features:ui?.tableFeatures}
        : component
    );
    const configuredSources=new Set(components.map((component:any)=>component.source));
    const label=(key:string)=>key.replace(/([a-z0-9])([A-Z])/g,'$1 $2').replace(/[_-]/g,' ').replace(/^./,char=>char.toUpperCase());
    const fields=(keys:string[])=>keys.map(key=>({key,label:label(key)}));
    const isRecord=(value:any)=>value!==null&&typeof value==='object'&&!Array.isArray(value);
    const values=isRecord(result.data)?result.data:{data:result.data};
    const source=isRecord(result.data)?'result.data':'result';
    const scalars:string[]=[];
    for(const [key,value] of Object.entries(values)){
      if(configuredSources.has(`${source}.${key}`))continue;
      if(Array.isArray(value)&&value.every(isRecord)){
        const keys=[...new Set(value.flatMap(row=>Object.keys(row)))];
        components.push({id:key,type:'data-table',title:label(key),source:`${source}.${key}`,
          columns:fields(keys.length?keys:['value']),features:ui?.tableFeatures});
      }else if(isRecord(value)){
        components.push({id:key,type:'object-view',title:label(key),source:`${source}.${key}`,fields:fields(Object.keys(value as object))});
      }else if(result.data!=null){
        scalars.push(key);
      }
    }
    if(scalars.length){
      components.push({id:'workflow-result',type:'object-view',title:'Result',source,
        fields:fields(scalars)});
    }
    return {...ui,components};
  }
  setTab(tab:string){
    this.currentTab=tab;
    if(tab==='designer' && !this.studioFiles.length && !this.studioBusy)this.refreshStudioFiles();
    if(tab==='history') this.selectedConversationId=this.activeConversationId;
  }
  get filteredStudioFiles() {
    const query = this.studioQuery.trim().toLowerCase();
    return this.studioFiles.filter(file => file.path.toLowerCase().includes(query));
  }
  // Refresh the definition browser using the current selection or requested path.
  refreshStudioFiles(requestedPath?: string){
    this.studioBusy=true;
    this.api.studioFiles().subscribe({
      next:files=>{
        const visibleFiles = files.filter((file: {path: string}) =>
          /\.xml$/i.test(file.path) || /^(?:workflows|flows)\/.+\.ya?ml$/i.test(file.path));
        this.studioFiles=visibleFiles;
        this.studioBusy=false;
        if(!this.studioPath&&visibleFiles.length){
          const preferred=visibleFiles.find((file: {path: string}) => file.path === requestedPath)
            ?? visibleFiles.find((file: {path: string}) => /\.ya?ml$/i.test(file.path));
          this.openStudioFile((preferred ?? visibleFiles[0]).path);
        }
      },
      error:e=>{this.studioBusy=false;if(!this.fail(e))this.studioNotice=this.error;}
    });
  }
  openStudioFile(path:string){
    this.studioPath=path;
    this.studioContent='';
    this.studioFlow=null;
    this.selectedStep=null;
    this.studioNotice='';
    this.studioBusy=true;
    this.api.studioRead(path).subscribe({
      next:file=>{
        if(this.studioPath!==path)return;
        this.studioContent=file.content;
        this.studioType=file.type;
        this.studioFlow=file.flow ?? null;
        this.studioView=this.studioFlow?'canvas':'source';
        this.studioBusy=false;
      },
      error:e=>{
        if(this.studioPath!==path)return;
        this.studioPath='';
        this.studioBusy=false;
        if(!this.fail(e))this.studioNotice=this.error;
      }
    });
  }
  // Send the edited source to the backend and refresh the file list after a successful save.
  saveStudioFile(){if(!this.studioPath)return;this.studioBusy=true;this.studioNotice='';this.api.studioWrite(this.studioPath,this.studioContent).subscribe({next:file=>{this.studioBusy=false;this.studioContent=file.content??this.studioContent;this.studioFlow=file.flow??null;this.selectedStep=null;if(!this.studioFlow)this.studioView='source';this.studioNotice='Saved successfully';this.refreshStudioFiles();},error:e=>{if(e?.status===401){this.fail(e);return;}this.studioBusy=false;this.studioNotice=e?.error?.detail||e?.error||'Save failed';}});}

  stepLinks(step: StudioStep, following?: StudioStep) {
    if (step.type === 'end' || step.type === 'return') return [];
    const target = (value?: StepTarget) => typeof value === 'string' ? value : value?.gotoStep;
    const success = step.gotoStep || target(step.onSuccess) || following?.id;
    const links = step.type === 'condition'
      ? [
        { label: 'Yes', id: target(step.onTrue ?? step.onSuccess) || success },
        { label: 'No', id: target(step.onFalse ?? step.onFailure) || target(step.onError) || success },
      ]
      : [{ label: 'Next', id: success }, { label: 'Error', id: target(step.onError) }];
    return links.filter(link => !!link.id);
  }

  selectStep(id?: string): void {
    this.selectedStep = this.studioFlow?.steps.find(step => step.id === id) ?? null;
    if (this.selectedStep) document.getElementById('flow-step-' + id)?.scrollIntoView({ block: 'nearest' });
  }

  // Run the selected workflow from the studio.
  runStudioFlow(): void {
    const id = this.studioFlow?.id;
    if (id && this.definitions.some(definition => definition.id === id)) this.openWorkflowOptions(id);
  }

  get canRunStudioFlow(): boolean {
    return !!this.studioFlow && this.definitions.some(definition => definition.id === this.studioFlow?.id);
  }
  createStudioFile(){
    const path=this.newFilePath.trim().replace(/\\/g,'/');if(!path)return;
    const parts=path.split('/');
    const file=parts[parts.length-1];
    const name=file==='flow.yaml'?parts[parts.length-2]:file.replace(/\.(yaml|yml)$/,'');
    const slug=(name||'new-workflow').toLowerCase().replace(/[^a-z0-9-]/g,'-').replace(/-+/g,'-').replace(/^-|-$/g,'')||'new-workflow';
    let content='';
    if(path.startsWith('workflows/')&&/\.ya?ml$/.test(path)) content=`id: ${slug}\nname: ${slug}\nversion: "1.0"\ndescription: New workflow\ntrigger:\n  type: ui\n  ui: common-ui\n  event: execute\ninputs: []\nsteps:\n  - id: finish\n    type: end\n`;
    else if(path.endsWith('.xml')) content='<?xml version="1.0" encoding="UTF-8"?>\n<Root/>\n';
    else content=`id: ${slug}\nversion: "1.0"\n`;
    this.studioBusy=true;this.api.studioWrite(path,content,true).subscribe({next:()=>{this.newFilePath='';this.showNewFile=false;this.refreshStudioFiles();this.openStudioFile(path);},error:e=>{if(e?.status===401){this.fail(e);return;}this.studioBusy=false;this.studioNotice=e?.error?.detail||e?.error||'Create failed';}});
  }
  fileIcon(file:any){return file.type==='xml'?'XML':'YAML';}

  toggleSettings(){this.showSettings=!this.showSettings;this.currentTab='run';}
  openWorkflowOptions(workflowId = this.selected): void {
    this.currentTab = 'run';
    this.showSettings = true;
    if (workflowId && workflowId !== this.selected) this.loadUi(workflowId);
  }
  sendOnEnter(event:Event){if(event instanceof KeyboardEvent&&!event.shiftKey){event.preventDefault();this.sendMessage();}}
  // Handle API errors, including an expired assistant session.
  fail(e:any):boolean{
    if(e?.status===401){
      this.studioBusy=false;
      this.sessionExpired.emit();
      return true;
    }
    this.error=e?.error?.detail||e?.message||'Unable to complete request';
    return false;
  }
  resolve(source:string,resultValue:any=this.result):any{if(!source)return null;let path=source.replace(/^\$\{|\}$/g,'').split('.');let current:any={result:resultValue,inputs:this.inputs};for(const p of path)current=current?.[p];return current;}
  visible(c:any,resultValue:any=this.result):boolean{if(!c.visibleWhen)return true;if(c.visibleWhen==='result.success')return !!resultValue?.success;if(c.visibleWhen==='result.batch')return !!resultValue?.batch;if(c.visibleWhen==='result.single')return !!resultValue?.success&&!resultValue?.batch;return true;}
  // Resolve dropdown choices, including those filtered by another input.
  getOptions(f:any):any[]{
    const options = f.options;
    return options?.dependsOn ? options.byType?.[this.inputs[options.dependsOn]] ?? [] : options?.items ?? [];
  }
  // Update the selected field and dependent controls.
  updateSelection(field: {name: string}, value: string): void {
    this.inputs[field.name] = value;
    for (const component of this.ui?.components ?? []) {
      for (const dependent of component.fields ?? []) {
        if (dependent.options?.dependsOn === field.name &&
            !this.getOptions(dependent).some(option => option.value === this.inputs[dependent.name])) {
          this.inputs[dependent.name] = '';
        }
      }
    }
  }
  // Read result rows and apply text filtering and sorting before pagination.
  getRows(c:any,resultValue:any=this.result):any[]{let rows=this.resolve(c.source,resultValue);if(!Array.isArray(rows))return [];if(this.searchText){const q=this.searchText.toLowerCase();rows=rows.filter(r=>Object.values(r).some(v=>String(v??'').toLowerCase().includes(q)));}if(this.sortKey)rows=[...rows].sort((a,b)=>String(a[this.sortKey]??'').localeCompare(String(b[this.sortKey]??''),undefined,{numeric:true})*(this.sortAsc?1:-1));return rows;}
  badgeClass(f:any,value:any):string{const colors=f?.colors||{};const key=String(value??'').toLowerCase();const match=Object.keys(colors).find(k=>k.toLowerCase()===key);const color=match?colors[match]:(colors['default']||'grey');return 'badge-'+color;}
  formatCell(value:any):string{if(value==null)return '—';if(Array.isArray(value))return value.map(item=>typeof item==='object'&&item!==null?Object.entries(item).map(([key,itemValue])=>`${key}: ${String(itemValue??'—')}`).join(', '):String(item)).join('; ');if(typeof value==='object')return Object.entries(value).map(([key,item])=>`${key}: ${String(item??'—')}`).join(', ');return String(value);}
  // Return the slice of result rows for the current page.
  pageRows(c:any,resultValue:any=this.result):any[]{let rows=this.getRows(c,resultValue);let size=c.features?.pagination?.pageSize||this.pageSize;return rows.slice(this.pageIndex*size,(this.pageIndex+1)*size);}
  totalPages(c:any,resultValue:any=this.result):number{return Math.max(1,Math.ceil(this.getRows(c,resultValue).length/(c.features?.pagination?.pageSize||this.pageSize)));}
  sort(key:string){if(this.sortKey===key)this.sortAsc=!this.sortAsc;else{this.sortKey=key;this.sortAsc=true;}}
  useSuggestion(text:string){this.sendMessage(text);}
  formatTime(time:Date):string{return time.toLocaleTimeString([],{hour:'numeric',minute:'2-digit',timeZone:this.history.timeZone});}
  formatDate(time:Date):string{return time.toLocaleDateString([],{month:'short',day:'numeric',timeZone:this.history.timeZone});}
  track(index:number,item:any){return item.id||item.name||item.key||index;}
}
