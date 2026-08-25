import React, { useEffect, useRef, useState } from 'react';
import {
  ArrowLeft,
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleDollarSign,
  Clock3,
  Copy,
  Cpu,
  FileText,
  FlaskConical,
  History,
  KeyRound,
  Play,
  Plug,
  RotateCcw,
  Route,
  Square,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
  FolderKanban,
} from 'lucide-react';
import type { Agent, RouteRecommendation, TaskPreflight, TaskRun, Workspace } from '../services/api';
import { api } from '../services/api';
import { useLanguage } from '../i18n/LanguageContext';
import { LiveTerminal, type TerminalConnectionState } from './LiveTerminal';
import { RunDetails } from './RunDetails';
import { StateNotice } from './StateNotice';

type RunPhase = 'idle' | 'analyzing' | 'blocked' | 'ready' | 'running' | 'complete' | 'error';

interface RunWorkspaceProps {
  initialPrompt?: string;
  initialMode?: string;
  existingRun?: TaskRun | null;
  onRunComplete?: () => void;
  onOpenRuns: () => void;
  onNavigate: (tab: string) => void;
}

const money = (value?: number | null) => value == null ? '—' : `$${value.toFixed(value < 0.01 ? 5 : 2)}`;
const duration = (value = 0) => value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${value}ms`;

export const RunWorkspace: React.FC<RunWorkspaceProps> = ({
  initialPrompt = '',
  initialMode = 'balanced',
  existingRun,
  onRunComplete,
  onOpenRuns,
  onNavigate,
}) => {
  const { isArabic } = useLanguage();
  const [prompt, setPrompt] = useState(initialPrompt);
  const [mode, setMode] = useState(initialMode);
  const [phase, setPhase] = useState<RunPhase>(existingRun ? 'complete' : 'idle');
  const [recommendation, setRecommendation] = useState<RouteRecommendation | null>(null);
  const [preflight, setPreflight] = useState<TaskPreflight | null>(null);
  const [run, setRun] = useState<TaskRun | null>(existingRun || null);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState('');
  const [agentId, setAgentId] = useState('auto');
  const [resolvedAgent, setResolvedAgent] = useState<Agent | null>(null);
  const [savedTemplate, setSavedTemplate] = useState(false);
  const [liveEvents, setLiveEvents] = useState<any[]>([]);
  const [activeTaskId, setActiveTaskId] = useState('');
  const [cancelling, setCancelling] = useState(false);
  const [interactive, setInteractive] = useState(false);
  const [terminalState, setTerminalState] = useState<TerminalConnectionState>('disconnected');
  const [terminalSocket, setTerminalSocket] = useState<WebSocket | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const taskRunningRef = useRef(false);
  const eventKeysRef = useRef(new Set<string>());

  useEffect(() => () => {
    taskRunningRef.current = false;
    socketRef.current?.close();
    if (reconnectTimerRef.current !== null) window.clearTimeout(reconnectTimerRef.current);
  }, []);

  useEffect(() => {
    Promise.all([api.listAgents(), api.listWorkspaces()]).then(([agentData, workspaceData]) => {
      setAgents(agentData);
      setWorkspaces(workspaceData);
      const defaultWorkspace = workspaceData.find((item) => item.is_default) || workspaceData[0];
      if (defaultWorkspace) setWorkspaceId(defaultWorkspace.id);
    }).catch(console.error);
  }, []);

  const analyze = async () => {
    if (!prompt.trim()) return;
    setError('');
    setPhase('analyzing');
    try {
      const next = await api.preflightTask({
        prompt: prompt.trim(),
        routing_mode: mode,
        agent_id: agentId === 'auto' ? undefined : agentId,
        workspace_id: workspaceId || undefined,
        interactive,
      });
      if (!next?.recommendation) throw new Error('No preflight returned');
      setAgents(next.installed_tools);
      setWorkspaces(next.workspaces);
      setResolvedAgent(next.selected_agent);
      setRecommendation(next.recommendation);
      setPreflight(next);
      setPhase(next.can_execute ? 'ready' : 'blocked');
    } catch (reason) {
      console.error(reason);
      setError(isArabic ? 'تعذر تحليل المهمة. تأكد أن الخادم يعمل ثم حاول مرة أخرى.' : 'Could not analyze this task. Check the server and try again.');
      setPhase('error');
    }
  };

  useEffect(() => {
    if (initialPrompt.trim() && !existingRun) analyze();
    // Initial analysis should only run once for each workspace instance.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const appendTerminalEvent = (event: any) => {
    const key = `${event.timestamp || ''}:${event.type || ''}:${event.text || event.message || ''}`;
    if (event.type !== 'connected' && eventKeysRef.current.has(key)) return;
    if (event.type !== 'connected') eventKeysRef.current.add(key);
    setLiveEvents((current) => [...current, event].slice(-500));
    if (event.type === 'done') setTerminalState('completed');
    else if (event.type === 'cancelled') setTerminalState('cancelled');
    else if (['failed', 'error', 'timed_out'].includes(event.type)) setTerminalState('failed');
    else if (event.type === 'connected') setTerminalState('connected');
  };

  const connectTerminal = (taskId: string) => {
    socketRef.current?.close();
    setTerminalState(reconnectAttemptsRef.current ? 'reconnecting' : 'connecting');
    const socket = api.openTaskStream(taskId, appendTerminalEvent);
    socketRef.current = socket;
    setTerminalSocket(socket);
    socket.onopen = () => {
      reconnectAttemptsRef.current = 0;
      setTerminalState('connected');
    };
    socket.onclose = () => {
      if (socketRef.current === socket) {
        socketRef.current = null;
        setTerminalSocket(null);
      }
      if (!taskRunningRef.current || reconnectAttemptsRef.current >= 5) {
        if (taskRunningRef.current) setTerminalState('disconnected');
        return;
      }
      reconnectAttemptsRef.current += 1;
      setTerminalState('reconnecting');
      reconnectTimerRef.current = window.setTimeout(() => connectTerminal(taskId), Math.min(5000, 500 * (2 ** reconnectAttemptsRef.current)));
    };
  };

  const sendTerminal = (message: Record<string, unknown>) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) socketRef.current.send(JSON.stringify(message));
  };

  const execute = async () => {
    if (!prompt.trim() || !preflight?.can_execute) return;
    setError('');
    setPhase('running');
    setLiveEvents([]);
    eventKeysRef.current.clear();
    taskRunningRef.current = true;
    reconnectAttemptsRef.current = 0;
    try {
      const taskId = `task-${crypto.randomUUID().slice(0, 8)}`;
      setActiveTaskId(taskId);
      connectTerminal(taskId);
      const completed = await api.runTask({
        task_id: taskId,
        prompt: prompt.trim(),
        routing_mode: mode,
        model_id: preflight.execution_method === 'provider_api' ? preflight.selected_model?.id : undefined,
        agent_id: preflight.execution_method === 'cli' ? preflight.selected_agent?.id : undefined,
        workspace_id: preflight.selected_workspace?.id,
        interactive,
        terminal_columns: 120,
        terminal_rows: 30,
      });
      taskRunningRef.current = false;
      socketRef.current?.close();
      socketRef.current = null;
      setTerminalSocket(null);
      setActiveTaskId('');
      if (!completed?.id) throw new Error('No run returned');
      setRun(completed);
      setTerminalState(completed.status === 'completed' ? 'completed' : completed.status === 'cancelled' ? 'cancelled' : 'failed');
      if (completed.status !== 'completed') {
        setError(isArabic ? 'فشل المنفّذ الحقيقي في إكمال المهمة. راجع السجل التقني ثم أعد المحاولة.' : 'The real executor could not complete the task. Review the technical log and try again.');
        setPhase('error');
        return;
      }
      setPhase('complete');
      onRunComplete?.();
    } catch (reason) {
      console.error(reason);
      setError(isArabic ? 'تعذر تنفيذ المهمة. راجع الاتصال أو مفاتيح المزود من الإعدادات.' : 'Execution failed. Check the provider connection or API keys in Settings.');
      setPhase('error');
    } finally {
      taskRunningRef.current = false;
      socketRef.current?.close();
      socketRef.current = null;
      setTerminalSocket(null);
      if (reconnectTimerRef.current !== null) window.clearTimeout(reconnectTimerRef.current);
      setActiveTaskId('');
      setCancelling(false);
    }
  };

  const cancelExecution = async () => {
    if (!activeTaskId || preflight?.execution_method !== 'cli') return;
    setCancelling(true);
    try {
      if (socketRef.current?.readyState === WebSocket.OPEN) sendTerminal({ type: 'cancel' });
      else await api.cancelTask(activeTaskId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Cancellation failed.');
      setCancelling(false);
    }
  };

  const copyResult = async () => {
    if (!run?.result_output) return;
    await navigator.clipboard.writeText(run.result_output);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  const runAgain = () => {
    if (!run) return;
    setPrompt(run.prompt);
    setRun(null);
    setRecommendation(null);
    setPreflight(null);
    setPhase('idle');
    setTerminalState('disconnected');
    setLiveEvents([]);
    setError('');
  };

  const saveAsTemplate = () => {
    if (!run) return;
    const existing = JSON.parse(localStorage.getItem('ai_fleet_task_templates') || '[]');
    localStorage.setItem('ai_fleet_task_templates', JSON.stringify([{ id: `template-${Date.now()}`, prompt: run.prompt, mode: run.routing_mode, createdAt: new Date().toISOString() }, ...existing]));
    setSavedTemplate(true);
    window.setTimeout(() => setSavedTemplate(false), 1800);
  };

  const selectedModel = (run?.selected_agent_id && agents.find((item) => item.id === run.selected_agent_id)?.name)
    || run?.selected_model_id
    || preflight?.selected_agent?.name
    || preflight?.selected_model?.name
    || recommendation?.selected_model.name
    || '—';
  const actualCost = run?.actual_cost ?? (preflight?.execution_method === 'cli' ? 0 : recommendation?.estimated_cost);
  const referenceCost = run?.reference_cost ?? recommendation?.reference_baseline_cost;
  const saved = run?.saved_amount ?? recommendation?.estimated_saved;
  const routeBlocked = !!preflight && !preflight.can_execute;
  const blockerText = (code: string, title: string, fallback: string) => {
    if (!isArabic) return fallback;
    if (code === 'provider_key_missing') return `اربط بيانات ${title} من الاتصالات قبل تشغيل هذا المسار.`;
    if (code === 'agent_needs_auth') return `${title} مثبت على الجهاز، لكنه يحتاج تسجيل الدخول أولًا.`;
    if (code === 'agent_unavailable') return `${title} غير مثبت أو غير جاهز للتنفيذ.`;
    if (code === 'local_runtime_offline') return 'خدمة Ollama المحلية غير مشغلة حاليًا.';
    if (code === 'local_model_missing') return 'خدمة Ollama تعمل، لكن لا يوجد موديل محلي مثبت.';
    if (code === 'workspace_required') return 'اختر مجلد مشروع معتمدًا وحدد صلاحياته قبل السماح لأي Agent بقراءة الملفات أو تعديلها.';
    return 'هذا المسار غير جاهز للتنفيذ الحقيقي حتى الآن.';
  };

  return (
    <div className="product-page run-page">
      <div className="product-page-head compact">
        <div>
          <button type="button" className="back-link" onClick={onOpenRuns}><ArrowLeft size={13} /> {isArabic ? 'عمليات التشغيل' : 'All runs'}</button>
          <h1>{run?.status === 'completed' ? (isArabic ? 'نتيجة المهمة' : 'Task result') : (isArabic ? 'تشغيل مهمة' : 'Run a task')}</h1>
          <p>{isArabic ? 'قرار واضح قبل التنفيذ وإيصال كامل بعده.' : 'A clear decision before execution and a complete receipt after it.'}</p>
        </div>
        <span className={`run-state ${phase}`}><span className="status-dot" />{
          phase === 'complete' ? (isArabic ? 'مكتملة' : 'Completed') :
          phase === 'running' ? (isArabic ? 'قيد التنفيذ' : 'Running') :
          phase === 'analyzing' ? (isArabic ? 'جارٍ التحليل' : 'Analyzing') :
          phase === 'ready' ? (isArabic ? 'جاهزة للتنفيذ' : 'Ready to run') :
          phase === 'blocked' ? (isArabic ? 'تحتاج إعدادًا' : 'Setup required') :
          phase === 'error' ? (isArabic ? 'تحتاج انتباه' : 'Needs attention') :
          (isArabic ? 'مسودة' : 'Draft')
        }</span>
      </div>

      <div className="run-layout">
        <div className="run-main-column">
          {!run && (
            <section className="surface-card task-brief-card">
              <div className="section-label"><FileText size={14} /> {isArabic ? 'المهمة' : 'Task brief'}</div>
              <textarea
                className="run-prompt-input"
                value={prompt}
                onChange={(event) => { setPrompt(event.target.value); setPreflight(null); if (phase !== 'idle') setPhase('idle'); }}
                placeholder={isArabic ? 'اكتب النتيجة التي تريد الوصول إليها، واترك اختيار الأداة للنظام…' : 'Describe the outcome you need and let the system choose the tool…'}
                rows={5}
                disabled={phase === 'running'}
              />
              <div className="task-brief-footer">
                <label className="inline-field">
                  <span>{isArabic ? 'الأولوية' : 'Priority'}</span>
                  <select value={mode} onChange={(event) => { setMode(event.target.value); setPreflight(null); setPhase('idle'); }} disabled={phase === 'running'}>
                    <option value="balanced">{isArabic ? 'متوازن' : 'Balanced'}</option>
                    <option value="economy">{isArabic ? 'أقل تكلفة' : 'Lower cost'}</option>
                    <option value="quality">{isArabic ? 'أعلى جودة' : 'Best quality'}</option>
                    <option value="fast">{isArabic ? 'أسرع نتيجة' : 'Fastest'}</option>
                  </select>
                </label>
                <label className="inline-field">
                  <span>{isArabic ? 'مساحة العمل' : 'Workspace'}</span>
                  <select value={workspaceId} onChange={(event) => { setWorkspaceId(event.target.value); setPreflight(null); setPhase('idle'); }} disabled={phase === 'running'}>
                    <option value="">{isArabic ? 'بدون مساحة عمل' : 'No workspace'}</option>
                    {workspaces.map((workspace) => <option value={workspace.id} key={workspace.id}>{workspace.name} · {workspace.permission_profile}</option>)}
                  </select>
                </label>
                <label className="inline-field">
                  <span>{isArabic ? 'منفّذ المهمة' : 'Execution agent'}</span>
                  <select value={agentId} onChange={(event) => { setAgentId(event.target.value); setPreflight(null); setPhase('idle'); }} disabled={phase === 'running'}>
                    <option value="auto">{isArabic ? 'اختيار تلقائي' : 'Auto select'}</option>
                    {agents.map((item) => <option value={item.id} key={item.id}>{item.name} · {item.status === 'ready' ? (isArabic ? 'جاهز' : 'ready') : (isArabic ? 'يحتاج ربطًا' : 'needs setup')}</option>)}
                  </select>
                </label>
                <label className="interactive-toggle"><input type="checkbox" checked={interactive} onChange={(event) => { setInteractive(event.target.checked); setPreflight(null); setPhase('idle'); }} disabled={phase === 'running'} /><span><strong>{isArabic ? 'طرفية تفاعلية' : 'Interactive terminal'}</strong><small>{isArabic ? 'PTY حقيقي للإدخال وتغيير الحجم' : 'Real PTY input and resize'}</small></span></label>
                {phase !== 'ready' && phase !== 'running' && (
                  <button type="button" className="btn-primary" onClick={analyze} disabled={!prompt.trim()}><Sparkles size={14} /> {isArabic ? 'تحليل المهمة' : 'Analyze task'}</button>
                )}
              </div>
            </section>
          )}

          {(phase === 'analyzing' || phase === 'running') && (
            <section className="surface-card progress-card">
              <div className="progress-mark"><span className="progress-spinner" /></div>
              <div>
                <h2>{phase === 'analyzing' ? (isArabic ? 'نحلّل المهمة ونقارن الأدوات' : 'Analyzing the task and comparing tools') : (isArabic ? 'المهمة قيد التنفيذ' : 'Your task is running')}</h2>
                <p>{phase === 'analyzing' ? (isArabic ? 'نوازن الجودة والتكلفة والسرعة والتوافر.' : 'Balancing quality, cost, speed, and availability.') : (isArabic ? 'يمكنك ترك هذه الشاشة، وسنحفظ النتيجة في عمليات التشغيل.' : 'You can leave this screen; the result will be saved in Runs.')}</p>
                {phase === 'running' && preflight?.execution_method === 'cli' && activeTaskId && <button type="button" className="btn-secondary" onClick={cancelExecution} disabled={cancelling}><Square size={13} fill="currentColor" /> {cancelling ? (isArabic ? 'جارٍ الإيقاف…' : 'Stopping…') : (isArabic ? 'إيقاف المهمة' : 'Stop task')}</button>}
              </div>
            </section>
          )}

          {preflight && phase === 'blocked' && (
            <section className="surface-card execution-gate-card">
              <div className="execution-gate-head">
                <span className="gate-icon"><AlertTriangle size={18} /></span>
                <div>
                  <div className="section-label">{isArabic ? 'فحص الجاهزية' : 'Execution preflight'}</div>
                  <h2>{isArabic ? 'لا يوجد مسار تنفيذ متصل حتى الآن' : 'No connected execution route yet'}</h2>
                  <p>{isArabic ? 'لن نبدأ المهمة ولن نسجلها كمكتملة قبل ربط مزود أو تسجيل الدخول إلى أداة محلية.' : 'The task will not start or be marked complete until a provider or local CLI is genuinely ready.'}</p>
                </div>
              </div>

              <div className="gate-blockers">
                {preflight.blockers.map((blocker, index) => (
                  <div className="gate-blocker" key={`${blocker.code}-${blocker.title}-${index}`}>
                    {blocker.code.includes('auth') ? <TerminalSquare size={16} /> : <KeyRound size={16} />}
                    <div><strong>{blocker.title}</strong><span>{blockerText(blocker.code, blocker.title, blocker.detail)}</span>{blocker.setup_command && <code>{blocker.setup_command}</code>}</div>
                  </div>
                ))}
              </div>

              {!!preflight.installed_tools.length && (
                <div className="discovered-tool-list">
                  <span>{isArabic ? 'الأدوات المكتشفة على الجهاز' : 'Tools found on this computer'}</span>
                  {preflight.installed_tools.map((tool) => (
                    <div key={tool.id}>
                      <TerminalSquare size={14} />
                      <div><strong>{tool.name}</strong><small>{tool.version || tool.detected_path}</small></div>
                      <span className={`tool-readiness ${tool.status === 'ready' ? 'ready' : 'setup'}`}>{tool.status === 'ready' ? (isArabic ? 'مسجّل وجاهز' : 'Signed in & ready') : (isArabic ? 'يحتاج تسجيل دخول' : 'Sign-in required')}</span>
                    </div>
                  ))}
                </div>
              )}

              <div className="gate-actions">
                {preflight.blockers.some((item) => item.code === 'workspace_required') && <button type="button" className="btn-primary" onClick={() => onNavigate('workspaces')}><FolderKanban size={15} /> {isArabic ? 'إضافة مساحة عمل' : 'Add workspace'}</button>}
                <button type="button" className="btn-primary" onClick={() => { localStorage.setItem('ai_fleet_settings_tab', 'connections'); onNavigate('settings'); }}><Plug size={15} /> {isArabic ? 'ربط مزود API' : 'Connect provider'}</button>
                <button type="button" className="btn-secondary" onClick={() => onNavigate('fleet')}><TerminalSquare size={15} /> {isArabic ? 'إدارة أدوات الجهاز' : 'Manage local tools'}</button>
                <button type="button" className="btn-secondary" onClick={analyze}>{isArabic ? 'إعادة الفحص' : 'Scan again'}</button>
              </div>
            </section>
          )}

          {recommendation && !run && (phase === 'ready' || phase === 'running') && (
            <section className="surface-card decision-card">
              <div className="decision-head">
                <div>
                  <div className="section-label"><Route size={14} /> {isArabic ? 'قرار التوجيه' : 'Routing decision'}</div>
                  <h2>{preflight?.selected_agent?.name || preflight?.selected_model?.name || recommendation.selected_model.name}</h2>
                  <p>{preflight?.execution_method === 'cli' ? (isArabic ? 'أداة محلية موثقة · مسجّل الدخول' : 'Verified local CLI · signed in') : `${preflight?.selected_model?.provider || recommendation.selected_model.provider} · ${recommendation.task_analysis.category}`}</p>
                </div>
                <div className="confidence-score"><strong>{preflight?.can_execute ? <Check size={19} /> : Math.round(recommendation.score)}</strong><span>{isArabic ? 'موثّق' : 'verified'}</span></div>
              </div>
              <div className="decision-facts">
                <div><span>{isArabic ? 'التكلفة المتوقعة' : 'Estimated cost'}</span><strong>{money(preflight?.execution_method === 'cli' ? 0 : recommendation.estimated_cost)}</strong></div>
                <div><span>{isArabic ? 'مقارنة بالمرجع' : 'Baseline cost'}</span><strong>{money(recommendation.reference_baseline_cost)}</strong></div>
                <div><span>{isArabic ? 'توفير متوقع' : 'Estimated avoided cost'}</span><strong className="positive">{money(recommendation.estimated_saved)}</strong></div>
              </div>
              {resolvedAgent && <div className="agent-decision"><span>{isArabic ? 'منفّذ المهمة' : 'Execution agent'}</span><div><strong>{resolvedAgent.name}</strong><small>{resolvedAgent.capabilities.slice(0, 3).join(' · ')} · {resolvedAgent.permission_profile}</small></div><span className="status-badge completed">{isArabic ? 'مثبت ومسجّل' : 'Installed & signed in'}</span></div>}
              <details className="why-details">
                <summary>{isArabic ? 'لماذا اختار النظام هذا المسار؟' : 'Why did the system choose this route?'} <ChevronDown size={14} /></summary>
                {preflight?.execution_method === 'cli' ? (
                  <>
                    <p>{isArabic ? 'الأداة مثبتة على الجهاز، واجتازت فحص تسجيل الدخول، وتطابق قدراتها نوع المهمة.' : 'The CLI is installed, signed in, and its capabilities match this task.'}</p>
                    <ul><li>{isArabic ? 'لن يتم استخدام موديل سحابي غير متصل.' : 'No disconnected cloud model will be used.'}</li><li>{isArabic ? 'سيعمل المنفّذ داخل مساحة العمل بصلاحيات كتابة محدودة.' : 'The executor will use workspace-scoped write permissions.'}</li></ul>
                  </>
                ) : (
                  <>
                    <p>{recommendation.explanation}</p>
                    <ul>{recommendation.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
                    {!!recommendation.fallback_chain.length && <div className="fallback-line"><span>{isArabic ? 'المسار الاحتياطي' : 'Fallback'}</span>{recommendation.fallback_chain.join(' → ')}</div>}
                  </>
                )}
              </details>
              {phase === 'ready' && (
                <div className="decision-action"><button type="button" className="btn-primary run-now-button" onClick={execute}><Play size={15} fill="currentColor" /> {isArabic ? 'تشغيل المهمة' : 'Run task'}</button></div>
              )}
            </section>
          )}

          {phase === 'running' && (
            <section className="surface-card run-timeline">
              <div className="section-label"><History size={14} /> {isArabic ? 'خط التنفيذ' : 'Execution timeline'}</div>
              <div className="timeline-steps">
                {[
                  [isArabic ? 'تحليل المهمة' : 'Task analyzed', isArabic ? 'تحديد النوع والتعقيد والمتطلبات' : 'Category, complexity, and requirements'],
                  [isArabic ? 'اختيار المسار' : 'Route selected', `${run?.selected_agent_id || run?.selected_model_id || preflight?.selected_agent?.name || preflight?.selected_model?.name || '—'}`],
                  [isArabic ? 'التنفيذ' : 'Execution', run ? (run.status === 'completed' ? (isArabic ? 'اكتمل بنجاح' : 'Completed successfully') : (isArabic ? 'فشل التنفيذ الحقيقي' : 'Real execution failed')) : (isArabic ? 'جارٍ معالجة المهمة…' : 'Processing the task…')],
                  [isArabic ? 'حفظ الإيصال' : 'Receipt saved', run ? (isArabic ? 'الإيصال محفوظ في السجل' : 'The receipt is saved in the run history') : (isArabic ? 'في انتظار النتيجة' : 'Waiting for result')],
                ].map(([title, note], index) => {
                  const done = (run?.status === 'completed') || (!run && index < 2);
                  const active = !run && index === 2;
                  return <div className={`${done ? 'done' : ''} ${active ? 'active' : ''}`} key={title}><span>{done ? <Check size={12} /> : index + 1}</span><div><strong>{title}</strong><small>{note}</small></div></div>;
                })}
              </div>
            </section>
          )}

           {(phase === 'running' || liveEvents.length > 0) && <LiveTerminal socket={terminalSocket} state={terminalState} interactive={interactive && preflight?.execution_method === 'cli'} events={liveEvents} onInput={(data) => sendTerminal({ type: 'stdin', data })} onResize={(columns, rows) => sendTerminal({ type: 'resize', columns, rows })} onCancel={phase === 'running' && preflight?.execution_method === 'cli' ? cancelExecution : undefined} cancelling={cancelling} isArabic={isArabic} />}

          {/* The causal story leads for every terminal run: intent →
              execution → outcome → evidence. Completed runs then get their
              result actions; failed runs get the failure card. */}
          {run && <RunDetails run={run} isArabic={isArabic} />}

          {run?.status === 'completed' && (
            <>
              <section className="surface-card result-card">
                <div className="result-head">
                  <div>
                    <div className="section-label"><CheckCircle2 size={14} /> {isArabic ? 'النتيجة' : 'Result'}</div>
                    <h2>{isArabic ? 'تم إنجاز المهمة' : 'Task completed'}</h2>
                  </div>
                  <div className="result-actions"><button type="button" className="btn-secondary" onClick={runAgain}><RotateCcw size={14} /> {isArabic ? 'تشغيل مرة أخرى' : 'Run again'}</button><button type="button" className="btn-secondary" onClick={copyResult}>{copied ? <Check size={14} /> : <Copy size={14} />}{copied ? (isArabic ? 'تم النسخ' : 'Copied') : (isArabic ? 'نسخ' : 'Copy')}</button></div>
                </div>
                <div className="result-output">{run.result_output || (isArabic ? 'انتهى التنفيذ دون نص ناتج. راجع التفاصيل التقنية.' : 'Execution completed without text output. Check technical details.')}</div>
              </section>

              <section className="post-run-actions">
                <button type="button" className="surface-card" onClick={() => onNavigate('model_lab')}><FlaskConical size={17} /><span><strong>{isArabic ? 'قارن النتيجة' : 'Compare result'}</strong><small>{isArabic ? 'اختبر نفس المهمة في Model Lab' : 'Test the same task in Model Lab'}</small></span></button>
                <button type="button" className="surface-card" onClick={saveAsTemplate}><Sparkles size={17} /><span><strong>{savedTemplate ? (isArabic ? 'تم الحفظ' : 'Saved') : (isArabic ? 'حفظ كقالب' : 'Save as template')}</strong><small>{isArabic ? 'استخدم نفس الإعدادات لاحقًا' : 'Reuse these settings later'}</small></span></button>
                <button type="button" className="surface-card" onClick={onOpenRuns}><History size={17} /><span><strong>{isArabic ? 'فتح السجل' : 'Open history'}</strong><small>{isArabic ? 'راجع كل عمليات التشغيل' : 'Review every run'}</small></span></button>
              </section>

              <details className="surface-card technical-card">
                <summary><span><Cpu size={14} /> {isArabic ? 'التفاصيل التقنية والسجل' : 'Technical details & log'}</span><ChevronDown size={14} /></summary>
                <div className="technical-grid">
                  <div><span>Run ID</span><code>{run.id}</code></div>
                  <div><span>{isArabic ? 'الموديل' : 'Model'}</span><code>{run.selected_model_id}</code></div>
                  <div><span>{isArabic ? 'نوع المهمة' : 'Task type'}</span><code>{run.task_type}</code></div>
                  <div><span>{isArabic ? 'المسار' : 'Route'}</span><code>{run.routing_mode}</code></div>
                  <div><span>{isArabic ? 'مساحة العمل' : 'Workspace'}</span><code>{run.workspace_id || '—'}</code></div>
                </div>
                <pre className="run-log">{run.log_output || 'No log output.'}</pre>
              </details>
            </>
          )}

          {run && run.status !== 'completed' && (
            <section className="surface-card failed-run-card">
              <AlertTriangle size={20} />
              <div><div className="section-label">{run.status === 'cancelled' ? (isArabic ? 'تم إيقاف التنفيذ' : 'Execution cancelled') : run.status === 'timed_out' ? (isArabic ? 'انتهت مهلة التنفيذ' : 'Execution timed out') : (isArabic ? 'فشل التنفيذ' : 'Execution failed')}</div><h2>{isArabic ? 'لم تُسجّل المهمة كمكتملة' : 'This task was not marked complete'}</h2><p>{run.status === 'cancelled' ? (isArabic ? 'تم إيقاف العملية المحلية وعملياتها الفرعية، وحُفظ إيصال الإلغاء.' : 'The local process and its child processes were stopped, and a cancellation receipt was saved.') : (isArabic ? 'لم يصل أي ناتج صالح من المنفّذ الحقيقي. راجع السجل التقني وأصلح الاتصال ثم أعد المحاولة.' : 'No valid output was returned by the real executor. Review the log, fix the connection, and retry.')}</p><pre className="run-log">{run.log_output}</pre></div>
            </section>
          )}

          {phase === 'error' && <StateNotice state="error" title="Run failed" detail={error} />}
        </div>

        <aside className="run-receipt surface-card">
          <div className="receipt-head"><div><span>{isArabic ? 'إيصال التشغيل' : 'Run receipt'}</span><strong>{routeBlocked ? (isArabic ? 'في انتظار الربط' : 'Awaiting setup') : run ? (isArabic ? 'نهائي' : 'Final') : (isArabic ? 'تقديري' : 'Estimate')}</strong></div><CircleDollarSign size={18} /></div>
          <div className="receipt-model"><span>{isArabic ? 'المسار المختار' : 'Selected route'}</span><strong>{routeBlocked ? (isArabic ? 'لا يوجد مسار جاهز' : 'No ready route') : selectedModel}</strong></div>
          <div className="receipt-lines">
            <div><span>{isArabic ? 'التكلفة الفعلية' : 'Actual cost'}{run ? ` · ${run.cost_provenance}` : ''}</span><strong>{routeBlocked || run?.cost_provenance === 'unknown' ? '—' : money(actualCost)}</strong></div>
            <div><span>{isArabic ? 'القيمة المرجعية' : 'Reference cost'}</span><strong>{routeBlocked ? '—' : money(referenceCost)}</strong></div>
            <div className="receipt-saving"><span>{isArabic ? 'تكلفة متجنبة تقديريًا' : 'Estimated avoided cost'}</span><strong>{routeBlocked ? '—' : money(saved)}</strong></div>
          </div>
          {run && (
            <div className="receipt-meta">
              <div><Clock3 size={13} /><span>{isArabic ? 'المدة' : 'Duration'}</span><strong>{duration(run.duration_ms)}</strong></div>
              <div><Cpu size={13} /><span>Tokens · {run.token_provenance}</span><strong>{(run.input_tokens + run.output_tokens).toLocaleString()}</strong></div>
              <div><ShieldCheck size={13} /><span>{isArabic ? 'الجودة' : 'Quality'} · {run.quality_provenance}</span><strong>{run.quality_eval_score == null ? '—' : `${Math.round(run.quality_eval_score)}%`}</strong></div>
            </div>
          )}
          <p className="receipt-note">{isArabic ? 'التوفير والقيمة المرجعية تقديرات مقارنة بالموديل المرجعي المحدد في الإعدادات، وليست رصيدًا نقديًا.' : 'Savings and reference value are estimates against the baseline model configured in Settings, not cash balance.'}</p>
        </aside>
      </div>
    </div>
  );
};
