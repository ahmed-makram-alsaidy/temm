import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Bot, Clock3, Cpu, FolderKanban, Globe2, Menu, Moon, RefreshCw, ScanSearch, Search, Sun } from 'lucide-react';
import type { Agent, FleetOverview, Model, TaskRun } from '../services/api';
import { api } from '../services/api';
import { useLanguage } from '../i18n/LanguageContext';
import { useTheme } from '../theme/ThemeContext';

interface HeaderProps {
  activeTab: string;
  overview?: FleetOverview | null;
  onRefresh: () => void;
  isScanning: boolean;
  onScanComputer: () => void;
  onMenuToggle: () => void;
  onNavigate: (tab: string) => void;
  onOpenRun: (run: TaskRun) => void;
}

export const Header: React.FC<HeaderProps> = ({ activeTab, onRefresh, isScanning, onScanComputer, onMenuToggle, onNavigate, onOpenRun }) => {
  const { setLanguage, isArabic } = useLanguage();
  const { theme, toggleTheme } = useTheme();
  const [query, setQuery] = useState('');
  const [searchOpen, setSearchOpen] = useState(false);
  const [projects, setProjects] = useState<any[]>([]);
  const [projectResults, setProjectResults] = useState<any[]>([]);
  const [runs, setRuns] = useState<TaskRun[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const searchInput = useRef<HTMLInputElement>(null);
  const pageNames: Record<string, [string, string]> = {
    dashboard: ['نظرة النظام', 'System overview'], projects: ['المشروعات', 'Projects'], run: ['تشغيل مهمة', 'Task run'], runs: ['عمليات التشغيل', 'Runs'],
    workspaces: ['مساحات العمل', 'Workspaces'], console: ['وحدة الأوامر', 'Command console'],
    fleet: ['الأدوات', 'Tools'], automation: ['المهارات وسير العمل', 'Skills & workflows'], insights: ['التحليلات', 'Insights'], model_lab: ['مختبر الموديلات', 'Model lab'], settings: ['الإعدادات', 'Settings'],
  };
  const pageName = pageNames[activeTab] || pageNames.dashboard;

  useLayoutEffect(() => {
    if (searchOpen) (searchInput.current || document.querySelector<HTMLInputElement>('.header-search input'))?.focus({ preventScroll: true });
  }, [searchOpen]);

  useEffect(() => {
    if (!searchOpen || projects.length || runs.length || models.length || agents.length) return;
    Promise.all([api.listProjects(), api.getTaskHistory(), api.listModels(), api.listAgents()]).then(([projectData, runData, modelData, agentData]) => { setProjects(projectData); setRuns(runData); setModels(modelData); setAgents(agentData); }).catch(console.error);
  }, [searchOpen, projects.length, runs.length, models.length, agents.length]);

  useEffect(() => {
    if (query.trim().length < 2) { setProjectResults([]); return; }
    const timer = window.setTimeout(() => { api.globalSearch(query.trim()).then((payload) => setProjectResults(payload.results || [])).catch(() => setProjectResults([])); }, 180);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if (event.key === '/' && !(event.target instanceof HTMLInputElement) && !(event.target instanceof HTMLTextAreaElement) && !(event.target instanceof HTMLSelectElement)) {
        event.preventDefault();
        event.stopPropagation();
        setSearchOpen(true);
        searchInput.current?.focus();
        window.setTimeout(() => searchInput.current?.focus(), 0);
      }
      if (event.key === 'Escape') closeSearch();
    };
    window.addEventListener('keydown', handleShortcut, true);
    return () => window.removeEventListener('keydown', handleShortcut, true);
  });

  const results = useMemo(() => {
    const value = query.trim().toLowerCase();
    if (!value) return { projects: [] as any[], runs: [] as TaskRun[], models: [] as Model[], agents: [] as Agent[] };
    return {
      projects: projects.filter((item) => `${item.name} ${item.slug} ${item.purpose} ${item.project_type}`.toLowerCase().includes(value)).slice(0, 4),
      runs: runs.filter((item) => `${item.prompt} ${item.task_type} ${item.selected_model_id}`.toLowerCase().includes(value)).slice(0, 4),
      models: models.filter((item) => `${item.name} ${item.provider} ${item.category}`.toLowerCase().includes(value)).slice(0, 3),
      agents: agents.filter((item) => `${item.name} ${item.description}`.toLowerCase().includes(value)).slice(0, 3),
    };
  }, [query, projects, runs, models, agents]);
  const hasResults = projectResults.length + results.projects.length + results.runs.length + results.models.length + results.agents.length > 0;
  const closeSearch = () => { setSearchOpen(false); setQuery(''); };

  return (
    <header className="topbar">
      <div className="topbar-leading">
        <button type="button" className="menu-toggle" onClick={onMenuToggle} aria-label="Open navigation"><Menu size={18} /></button>
        <div className="page-context"><div className="page-kicker">TEMM</div><div className="page-name">{isArabic ? pageName[0] : pageName[1]}</div></div>
      </div>

      <div className="global-search-wrap">
        <div className={`header-search ${searchOpen ? 'active' : ''}`}><Search size={15} color="var(--text-muted)" /><input ref={searchInput} type="search" aria-label="Search" value={query} onFocus={() => setSearchOpen(true)} onChange={(event) => setQuery(event.target.value)} placeholder={isArabic ? 'ابحث في المشروعات أو التشغيلات…' : 'Search projects or runs…'} /><kbd>/</kbd></div>
        {searchOpen && query.trim() && (
          <div className="search-popover">
            {projectResults.length > 0 && <section><span className="search-group-label">{isArabic ? 'سجل المشروع' : 'Project records'}</span>{projectResults.slice(0, 8).map((item) => <button type="button" key={`${item.type}:${item.id}`} onClick={() => { closeSearch(); onNavigate(item.type === 'run' ? 'runs' : item.type === 'agent' ? 'fleet' : 'projects'); }}><span className="search-result-icon"><FolderKanban size={14} /></span><span><strong>{item.title}</strong><small>{item.type} · {item.detail}</small></span></button>)}</section>}
            {results.projects.length > 0 && <section><span className="search-group-label">{isArabic ? 'المشروعات' : 'Projects'}</span>{results.projects.map((item) => <button type="button" key={item.id} onClick={() => { closeSearch(); onNavigate('projects'); }}><span className="search-result-icon"><FolderKanban size={14} /></span><span><strong>{item.name}</strong><small>{item.project_type} · {item.lifecycle_status}</small></span></button>)}</section>}
            {results.runs.length > 0 && <section><span className="search-group-label">{isArabic ? 'عمليات التشغيل' : 'Runs'}</span>{results.runs.map((item) => <button type="button" key={item.id} onClick={() => { closeSearch(); onOpenRun(item); }}><span className="search-result-icon"><Clock3 size={14} /></span><span><strong>{item.prompt}</strong><small>{item.selected_model_id} · {item.task_type}</small></span></button>)}</section>}
            {results.models.length > 0 && <section><span className="search-group-label">{isArabic ? 'الموديلات' : 'Models'}</span>{results.models.map((item) => <button type="button" key={item.id} onClick={() => { closeSearch(); onNavigate('fleet'); }}><span className="search-result-icon"><Cpu size={14} /></span><span><strong>{item.name}</strong><small>{item.provider} · {item.category}</small></span></button>)}</section>}
            {results.agents.length > 0 && <section><span className="search-group-label">{isArabic ? 'الوكلاء' : 'Agents'}</span>{results.agents.map((item) => <button type="button" key={item.id} onClick={() => { closeSearch(); onNavigate('fleet'); }}><span className="search-result-icon"><Bot size={14} /></span><span><strong>{item.name}</strong><small>{item.status} · {item.version || item.cli_command}</small></span></button>)}</section>}
            {!hasResults && <div className="search-empty">{isArabic ? 'لا توجد نتائج مطابقة.' : 'No matching results.'}</div>}
          </div>
        )}
      </div>

      <div className="topbar-actions">
        <button type="button" className="icon-action" onClick={toggleTheme} title={theme === 'light' ? 'Use dark mode' : 'Use light mode'}>{theme === 'light' ? <Moon size={15} /> : <Sun size={15} />}</button>
        <button type="button" className="language-action" onClick={() => setLanguage(isArabic ? 'en' : 'ar')}><Globe2 size={15} /><span>{isArabic ? 'EN' : 'العربية'}</span></button>
        <button type="button" className="icon-action" onClick={onScanComputer} disabled={isScanning} title={isArabic ? 'اكتشاف أدوات AI على الجهاز' : 'Discover AI tools'}><ScanSearch size={16} className={isScanning ? 'spin' : ''} /></button>
        <button type="button" className="icon-action" onClick={onRefresh} title={isArabic ? 'تحديث' : 'Refresh'}><RefreshCw size={15} /></button>
      </div>
      {searchOpen && <button type="button" className="search-dismiss" aria-label="Close search" onClick={closeSearch} />}
    </header>
  );
};
