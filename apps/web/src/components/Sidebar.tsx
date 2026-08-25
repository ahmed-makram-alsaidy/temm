import React from 'react';
import {
  Activity,
  Boxes,
  ChartNoAxesCombined,
  ChevronRight,
  Command,
  FlaskConical,
  FolderKanban,
  History,
  LayoutDashboard,
  Plus,
  Settings,
  SquareTerminal,
  Workflow,
  X,
} from 'lucide-react';
import { useLanguage } from '../i18n/LanguageContext';
import { PRIMARY_NAV, SYSTEM_NAV, surfaceIsActive, systemStatusTone } from './shell-navigation';
import type { NavItem } from './shell-navigation';

interface SidebarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  onNewTask: () => void;
  isOpen?: boolean;
  onClose?: () => void;
  fleetCounts?: { models_online: number; agents_ready: number; execution_ready: boolean };
}

const NAV_ICONS: Record<Exclude<NavItem['id'], 'settings'>, React.ComponentType<{ size?: number; className?: string }>> = {
  projects: FolderKanban,
  runs: History,
  workspaces: FolderKanban,
  console: SquareTerminal,
  fleet: Boxes,
  automation: Workflow,
  insights: ChartNoAxesCombined,
  model_lab: FlaskConical,
  dashboard: LayoutDashboard,
};

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  setActiveTab,
  onNewTask,
  isOpen = false,
  onClose,
  fleetCounts,
}) => {
  const { isArabic } = useLanguage();

  return (
    <aside className={`sidebar ${isOpen ? 'open' : ''}`}>
      <div className="sidebar-brand">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true"><Command size={20} strokeWidth={2.4} /></div>
          <div>
            <div className="brand-name">TEMM</div>
            <div className="brand-subtitle">{isArabic ? 'طبقة القرار والتنفيذ' : 'Decision & execution layer'}</div>
          </div>
        </div>
        <button type="button" className="mobile-close" onClick={onClose} aria-label="Close navigation"><X size={19} /></button>
      </div>

      <div className="sidebar-action">
        <button type="button" className="new-task-button" onClick={onNewTask}>
          <Plus size={15} />
          <span>{isArabic ? 'مشروع جديد' : 'New project'}</span>
        </button>
      </div>

      <nav className="nav-scroll" aria-label={isArabic ? 'التنقل الرئيسي' : 'Primary navigation'}>
        <div className="nav-list" data-group="primary">
          {[...PRIMARY_NAV].map((item) => (
            <NavButton key={item.id} item={item} activeTab={activeTab} setActiveTab={setActiveTab} isArabic={isArabic} />
          ))}
        </div>
        <div className="nav-label">{isArabic ? 'النظام' : 'System'}</div>
        <div className="nav-list" data-group="system">
          {SYSTEM_NAV.map((item) => (
            <NavButton key={item.id} item={item} activeTab={activeTab} setActiveTab={setActiveTab} isArabic={isArabic} />
          ))}
        </div>
      </nav>

      <div className="sidebar-footer">
        <button
          type="button"
          data-route="settings"
          className={`nav-item ${activeTab === 'settings' ? 'active' : ''}`}
          onClick={() => setActiveTab('settings')}
          aria-current={activeTab === 'settings' ? 'page' : undefined}
        >
          <Settings size={17} className="nav-icon" />
          <span className="nav-text">{isArabic ? 'الإعدادات' : 'Settings'}</span>
        </button>
        <div className="sidebar-status" data-tone={systemStatusTone(fleetCounts?.execution_ready === true)}>
          <div className="status-line">
            <span className="status-title">{isArabic ? 'التنفيذ' : 'Execution'}</span>
            <span className="status-value">
              {fleetCounts?.execution_ready === true
                ? (isArabic ? 'جاهز' : 'Ready')
                : (isArabic ? 'يحتاج إعدادًا' : 'Setup needed')}
            </span>
          </div>
          <div className="status-meta"><Activity size={12} /> {fleetCounts?.models_online || 0} {isArabic ? 'موديل' : 'models'} · {fleetCounts?.agents_ready || 0} {isArabic ? 'وكيل' : 'agents'}</div>
        </div>
      </div>
    </aside>
  );
};

function NavButton({ item, activeTab, setActiveTab, isArabic }: { item: NavItem; activeTab: string; setActiveTab: (tab: string) => void; isArabic: boolean }) {
  const Icon = NAV_ICONS[item.id];
  const isActive = surfaceIsActive(item.id, activeTab);
  return (
    <button
      type="button"
      data-route={item.id}
      className={`nav-item ${isActive ? 'active' : ''}`}
      onClick={() => setActiveTab(item.id)}
      aria-current={isActive ? 'page' : undefined}
    >
      <Icon size={17} className="nav-icon" />
      <span className="nav-text">{isArabic ? item.ar : item.en}</span>
      {isActive && <ChevronRight size={13} className="nav-chevron" aria-hidden="true" />}
    </button>
  );
}
