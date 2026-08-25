import React, { lazy, Suspense, useEffect, useState } from 'react';
import { Sidebar } from './components/Sidebar';
import { Header } from './components/Header';
import { Dashboard } from './components/Dashboard';
import { Runs } from './components/Runs';
import { Onboarding } from './components/Onboarding';
const RunWorkspace = lazy(() => import('./components/RunWorkspace').then((module) => ({ default: module.RunWorkspace })));
const FleetManager = lazy(() => import('./components/FleetManager').then((module) => ({ default: module.FleetManager })));
const Insights = lazy(() => import('./components/Insights').then((module) => ({ default: module.Insights })));
const ModelLab = lazy(() => import('./components/ModelLab').then((module) => ({ default: module.ModelLab })));
const SettingsVault = lazy(() => import('./components/SettingsVault').then((module) => ({ default: module.SettingsVault })));
const Workspaces = lazy(() => import('./components/Workspaces').then((module) => ({ default: module.Workspaces })));
const CommandConsole = lazy(() => import('./components/CommandConsole').then((module) => ({ default: module.CommandConsole })));
const AutomationCenter = lazy(() => import('./components/AutomationCenter').then((module) => ({ default: module.AutomationCenter })));
const Projects = lazy(() => import('./components/Projects').then((module) => ({ default: module.Projects })));
import type { FleetOverview, TaskRun } from './services/api';
import { api } from './services/api';
import './styles/theme.css';
import './components/shell.css';
import './components/inner-surfaces.css';

export const App: React.FC = () => {
  // The flagship Project Workspace is the product's home surface (V1-V6).
  // Every legacy surface remains reachable from the sidebar; a remembered
  // surface still wins.
  const [activeTab, setActiveTab] = useState(() => localStorage.getItem('temm_active_surface') || 'projects');
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [overview, setOverview] = useState<FleetOverview | null>(null);
  const [isScanning, setIsScanning] = useState(false);
  const [launchedPrompt, setLaunchedPrompt] = useState('');
  const [launchedMode, setLaunchedMode] = useState('balanced');
  const [selectedRun, setSelectedRun] = useState<TaskRun | null>(null);
  const [runKey, setRunKey] = useState(0);
  // The legacy setup wizard no longer owns first launch: it covered the
  // flagship workspace entirely, and the workspace's own readiness blockers
  // surface the same setup needs when execution actually requires them. The
  // wizard remains available as a deliberate action from Settings → Restart
  // setup, and completing it still lands on Home.
  const [showOnboarding, setShowOnboarding] = useState(false);

  const loadOverview = async () => {
    try {
      setOverview(await api.getOverview());
    } catch (error) {
      console.error('Failed to load fleet overview', error);
    }
  };

  useEffect(() => {
    try {
      const preferences = JSON.parse(localStorage.getItem('ai_fleet_preferences') || '{}');
      document.documentElement.dataset.compactNav = preferences.compactNav ? 'true' : 'false';
      document.documentElement.dataset.reduceMotion = preferences.reduceMotion ? 'true' : 'false';
    } catch { /* Keep product defaults when preferences are malformed. */ }
    loadOverview();
    const interval = window.setInterval(loadOverview, 10000);
    return () => window.clearInterval(interval);
  }, []);

  const handleScanComputer = async () => {
    try {
      setIsScanning(true);
      await api.triggerScan();
      await loadOverview();
    } catch (error) {
      console.error(error);
    } finally {
      setIsScanning(false);
    }
  };

  const handleLaunchTask = (prompt: string, mode: string) => {
    setSelectedRun(null);
    setLaunchedPrompt(prompt);
    setLaunchedMode(mode);
    setRunKey((value) => value + 1);
    setActiveTab('run');
  };

  const handleNewTask = () => {
    let defaultMode = 'balanced';
    try { defaultMode = JSON.parse(localStorage.getItem('ai_fleet_preferences') || '{}').defaultRoutingMode || 'balanced'; } catch { /* use balanced */ }
    handleLaunchTask('', defaultMode);
  };

  const handleOpenRun = (run: TaskRun) => {
    setSelectedRun(run);
    setLaunchedPrompt('');
    setRunKey((value) => value + 1);
    setActiveTab('run');
  };

  const handleNavigate = (tab: string) => {
    localStorage.setItem('temm_active_surface', tab);
    setActiveTab(tab);
    setIsSidebarOpen(false);
  };

  return (
    <div className="app-container">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <Sidebar
        activeTab={activeTab}
        setActiveTab={handleNavigate}
        onNewTask={handleNewTask}
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        fleetCounts={overview?.fleet_counts ? {
          models_online: overview.fleet_counts.models_online,
          agents_ready: overview.fleet_counts.agents_ready,
          execution_ready: overview.fleet_counts.execution_ready === true,
        } : undefined}
      />

      <button
        type="button"
        className={`sidebar-overlay ${isSidebarOpen ? 'open' : ''}`}
        onClick={() => setIsSidebarOpen(false)}
        aria-label="Close navigation"
      />

      <main id="main-content" className="main-content" tabIndex={-1}>
        <Header
          activeTab={activeTab}
          overview={overview}
          onRefresh={loadOverview}
          isScanning={isScanning}
          onScanComputer={handleScanComputer}
          onMenuToggle={() => setIsSidebarOpen(true)}
          onNavigate={handleNavigate}
          onOpenRun={handleOpenRun}
        />

        <div className="page-stage">
          <Suspense fallback={<div className="large-empty" role="status">Loading workspace…</div>}>
          {activeTab === 'dashboard' && (
            <Dashboard overview={overview} onNavigate={handleNavigate} onLaunchTask={handleLaunchTask} />
          )}
          {activeTab === 'run' && (
            <RunWorkspace
              key={runKey}
              initialPrompt={launchedPrompt}
              initialMode={launchedMode}
              existingRun={selectedRun}
              onRunComplete={loadOverview}
              onOpenRuns={() => handleNavigate('runs')}
              onNavigate={handleNavigate}
            />
          )}
          {activeTab === 'projects' && <Projects onNavigate={handleNavigate} />}
          {activeTab === 'runs' && <Runs onOpenRun={handleOpenRun} onNewTask={handleNewTask} />}
          {activeTab === 'workspaces' && <Workspaces onOpenConsole={() => handleNavigate('console')} />}
          {activeTab === 'console' && <CommandConsole onOpenWorkspaces={() => handleNavigate('workspaces')} />}
          {activeTab === 'fleet' && <FleetManager />}
          {activeTab === 'automation' && <AutomationCenter onLaunchTask={handleLaunchTask} />}
          {activeTab === 'insights' && <Insights overview={overview} />}
          {activeTab === 'model_lab' && <ModelLab onOpenConnections={() => { localStorage.setItem('ai_fleet_settings_tab', 'connections'); handleNavigate('settings'); }} />}
          {activeTab === 'settings' && <SettingsVault onRestartSetup={() => setShowOnboarding(true)} />}
          </Suspense>
        </div>
      </main>
      {showOnboarding && (
        <Onboarding
          onComplete={() => { setShowOnboarding(false); handleNavigate('dashboard'); }}
          onOpenSettings={() => { setShowOnboarding(false); handleNavigate('settings'); }}
          onOpenWorkspaces={() => { setShowOnboarding(false); handleNavigate('workspaces'); }}
        />
      )}
    </div>
  );
};

export default App;
