// V9 shell navigation model. The SINGLE description of the product's
// navigation hierarchy, derived from the routes App.tsx actually renders.
// No second routing truth lives anywhere: App owns `activeTab`; this module
// only describes groups, nesting, and honest system-status tone.

export type ShellSurface =
  | 'projects' | 'runs' | 'run'
  | 'workspaces' | 'console' | 'fleet' | 'automation' | 'insights' | 'model_lab'
  | 'settings' | 'dashboard';

// Surfaces that appear as navigable items (settings renders in the footer;
// the run detail view nests inside Runs).
export type NavRoute = Exclude<ShellSurface, 'run' | 'settings'>;

// The surface the product opens on when nothing is remembered (V6 decision:
// the flagship Project Workspace is home).
export const DEFAULT_SURFACE: ShellSurface = 'projects';

export function initialSurface(remembered: string | null): ShellSurface {
  return (remembered as ShellSurface) || DEFAULT_SURFACE;
}

export interface NavItem {
  id: NavRoute;
  en: string;
  ar: string;
}

// Primary work surfaces: where outcomes live and where execution history is
// read. Everything else — including the operator dashboard — is system
// tooling. Settings is a footer utility.
export const PRIMARY_NAV: [NavItem, NavItem] = [
  { id: 'projects', en: 'Projects', ar: 'المشروعات' },
  { id: 'runs', en: 'Runs', ar: 'عمليات التشغيل' },
];

export const SYSTEM_NAV: NavItem[] = [
  { id: 'workspaces', en: 'Workspaces', ar: 'مساحات العمل' },
  { id: 'console', en: 'Command console', ar: 'وحدة الأوامر' },
  { id: 'fleet', en: 'Tools', ar: 'الأدوات' },
  { id: 'automation', en: 'Skills & workflows', ar: 'المهارات وسير العمل' },
  { id: 'insights', en: 'Insights', ar: 'التحليلات' },
  { id: 'model_lab', en: 'Model lab', ar: 'مختبر الموديلات' },
  { id: 'dashboard', en: 'System overview', ar: 'نظرة النظام' },
];

// A run's detail view is not a separate destination: it lives inside Runs.
// The shell must keep marking Runs as the current location while it is open.
export function surfaceIsActive(item: NavItem['id'], activeTab: string): boolean {
  if (item === 'runs' && activeTab === 'run') return true;
  return item === activeTab;
}

// System status in the sidebar footer is execution READINESS, not acceptance:
// ready is neutral ink; needing setup is attention clay. There is no earned
// green and no animation anywhere in the shell.
export type SystemStatusTone = 'neutral' | 'attention';

export function systemStatusTone(executionReady: boolean): SystemStatusTone {
  return executionReady ? 'neutral' : 'attention';
}
