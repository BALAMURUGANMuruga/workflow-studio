// Host shared assistant navigation and the active workspace view.
import { Component, DestroyRef, OnInit, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, NavigationEnd, Router, RouterLink, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../services/auth.service';
import { AssistantHistory, WorkflowStudioComponent } from '../../features/workflow-studio/workflow-studio.component';
import { SideNavigationComponent } from '../side-navigation/side-navigation.component';

@Component({
  selector: 'app-home',
  imports: [RouterOutlet, RouterLink, SideNavigationComponent, FormsModule],
  providers: [AssistantHistory],
  templateUrl: './home.component.html',
  styleUrl: './home.component.scss',
})
export class HomeComponent implements OnInit {
  private readonly auth = inject(AuthService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly systemTheme = window.matchMedia('(prefers-color-scheme: dark)');
  private readonly history = inject(AssistantHistory);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly navigationEnd = this.router.events.pipe(
    filter(event => event instanceof NavigationEnd),
    takeUntilDestroyed(),
  );
  pageTitle = 'Ganalimura AI Assistant';
  assistant: WorkflowStudioComponent | null = null;
  panel: 'profile' | 'settings' | null = null;
  openTabs = ['run'];
  showTabMenu = false;
  notice = '';
  private readonly profileDefaults = {
    name: this.auth.workflowUser?.displayName || this.auth.workflowUser?.username || '',
    email: '', phone: '', department: '',
  };
  private readonly preferenceDefaults = {
    theme: 'light', density: 'standard', timeZone: 'Asia/Kolkata',
  };
  private readonly accountKey = `ganalimura-preferences:${this.auth.workflowUser?.username ?? ''}`;
  profile = this.readPreferences('profile', this.profileDefaults);
  profileDraft = { ...this.profile };
  preferences = this.readPreferences('settings', { ...this.preferenceDefaults, theme: this.readSavedTheme() });
  get isDarkMode() {
    return this.preferences.theme === 'system' ? this.systemDark : this.preferences.theme === 'dark';
  }
  private systemDark = this.systemTheme.matches;
  preferenceDraft = { ...this.preferences };
  editingProfile = false;
  get tabs() {
    return [
      { id: 'run', label: 'Chat', icon: '☏' },
      ...(this.isMaster ? [{ id: 'designer', label: 'Workflow Studio', icon: '⌘' }] : []),
      { id: 'exception', label: 'Exception', icon: '△' },
      { id: 'workflow-generator', label: 'Workflow YAML Create AI', icon: '⌘' },
      { id: 'history', label: 'History', icon: '◷' },
      { id: 'settings', label: 'Settings', icon: '⚙' },
      { id: 'profile', label: 'Profile', icon: '♙' },
      { id: 'about', label: 'About', icon: 'ⓘ' },
    ];
  }
  get activeTab() {
    if (this.panel) return this.panel;
    const route = this.route.firstChild?.snapshot.routeConfig?.path;
    return route === 'aichat' ? this.assistant?.currentTab ?? 'run' : route ?? '';
  }
  get displayUser() {
    const user = this.currentUser;
    return user ? { ...user, displayName: this.profile.name || user.username } : null;
  }

  get embeddedChat() { return this.route.snapshot.queryParamMap.get('view') === 'embedded-chat'; }
  get currentUser() { return this.auth.workflowUser; }
  get isMaster() { return this.auth.isWorkflowMaster; }

  // Initialize the assistant shell and track navigation for the page header.
  ngOnInit(): void {
    const updateSystemTheme = (event: MediaQueryListEvent) => { this.systemDark = event.matches; };
    this.systemTheme.addEventListener('change', updateSystemTheme);
    this.destroyRef.onDestroy(() => this.systemTheme.removeEventListener('change', updateSystemTheme));
    this.history.timeZone = this.preferences.timeZone;
    this.updatePageTitle();
    this.navigationEnd.subscribe(() => {
      this.panel = null;
      this.updatePageTitle();
    });
  }

  private updatePageTitle(): void {
    this.pageTitle = this.route.firstChild?.snapshot.title ?? 'Ganalimura AI Assistant';
    const tab = this.activeTab;
    if (['exception', 'workflow-generator'].includes(tab) && !this.openTabs.includes(tab)) this.openTabs.push(tab);
  }

  // Connect the active routed component to the shell when it enters the router outlet.
  onPageActivated(page: unknown, outlet: RouterOutlet): void {
    if (page instanceof WorkflowStudioComponent) {
      page.sessionExpired.subscribe(() => this.logout(true));
      queueMicrotask(() => {
        if (outlet.isActivated && outlet.component === page) {
          this.assistant = page;
          if (page.currentTab === 'designer' && !this.openTabs.includes('designer')) this.openTabs.push('designer');
        }
      });
    }
  }

  // Select a workspace tab and navigate or switch views as needed.
  async selectAssistantTab(tab: string): Promise<void> {
    this.showTabMenu = false;
    if (!this.openTabs.includes(tab)) this.openTabs.push(tab);
    this.notice = '';
    if (tab === 'profile' || tab === 'settings') {
      if (this.panel !== tab) {
        this.profileDraft = { ...this.profile };
        this.preferenceDraft = { ...this.preferences };
        this.editingProfile = false;
      }
      this.panel = tab;
      return;
    }
    this.panel = null;
    if (tab === 'exception' || tab === 'workflow-generator') {
      await this.router.navigate([tab], { relativeTo: this.route, queryParamsHandling: 'preserve' });
      return;
    }
    if (this.route.firstChild?.snapshot.routeConfig?.path !== 'aichat') {
      await this.router.navigate(['aichat'], { relativeTo: this.route, queryParamsHandling: 'preserve' });
    }
    this.assistant?.setTab(tab);
  }

  closeTab(tab: string): void {
    this.openTabs = this.openTabs.filter(open => open !== tab);
    if (this.activeTab === tab) void this.selectAssistantTab(this.openTabs.at(-1) ?? 'run');
  }

  // Open the chat workspace and reset the active conversation.
  async newChat(): Promise<void> {
    if (this.embeddedChat) {
      this.assistant?.setTab('run');
      this.assistant?.clearChat();
      return;
    }
    await this.selectAssistantTab('run');
    if (!this.assistant?.loading) this.assistant?.clearChat();
  }

  async openWorkflowOptions(): Promise<void> {
    await this.selectAssistantTab('run');
    this.assistant?.openWorkflowOptions();
  }

  focusSection(id: string): void {
    document.getElementById(id)?.focus();
  }

  // Apply the edited profile details.
  saveProfile(): void {
    this.profile = { ...this.profileDraft, name: this.profileDraft.name.trim() || this.profileDefaults.name };
    this.profileDraft = { ...this.profile };
    this.editingProfile = false;
    this.savePreferences('profile', this.profile);
  }

  discardProfile(): void {
    this.profileDraft = { ...this.profile };
    this.editingProfile = false;
    this.notice = '';
  }

  resetPreferences(): void {
    this.preferenceDraft = { ...this.preferenceDefaults };
    this.notice = '';
  }

  // Apply the current application preferences.
  saveSettings(): void {
    this.preferences = { ...this.preferenceDraft };
    this.history.timeZone = this.preferences.timeZone;
    this.savePreferences('settings', this.preferences);
  }

  private readPreferences<T extends object>(section: string, defaults: T): T {
    try {
      return { ...defaults, ...JSON.parse(localStorage.getItem(`${this.accountKey}:${section}`) ?? '{}') };
    } catch {
      return defaults;
    }
  }

  // Persist one preference section in browser storage.
  private savePreferences(section: string, value: object): void {
    try {
      localStorage.setItem(`${this.accountKey}:${section}`, JSON.stringify(value));
      this.notice = 'Changes saved on this device.';
    } catch {
      this.notice = 'Changes applied for this session. Browser storage is unavailable.';
    }
  }

  // Switch the current theme and remember it in the browser.
  toggleTheme(): void {
    this.preferences = { ...this.preferences, theme: this.isDarkMode ? 'light' : 'dark' };
    this.preferenceDraft.theme = this.preferences.theme;
    this.savePreferences('settings', this.preferences);
  }

  private readSavedTheme(): string {
    try {
      const theme = localStorage.getItem('ganalimura-theme');
      return theme === 'dark' || theme === 'light' ? theme : this.preferenceDefaults.theme;
    } catch {
      return this.preferenceDefaults.theme;
    }
  }

  // Enter or exit browser fullscreen mode.
  toggleFullscreen(): void {
    if (document.fullscreenElement) {
      void document.exitFullscreen().catch(console.error);
    } else {
      void document.documentElement.requestFullscreen().catch(console.error);
    }
  }

  // Clear the assistant session and return to sign-in.
  logout(expired = false): void {
    this.auth.logoutWorkflow();
    if (!expired) this.auth.logout();
    void this.router.navigate(['/login'], {
      queryParams: this.route.snapshot.queryParams,
      state: { expired },
    });
  }
}
