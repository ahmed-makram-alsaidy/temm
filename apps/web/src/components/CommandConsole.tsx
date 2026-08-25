import React, { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, Clock3, Command, History, Play, ShieldCheck, TerminalSquare } from 'lucide-react';
import type { CommandRun, TerminalExecResult, Workspace } from '../services/api';
import { api } from '../services/api';
import { useLanguage } from '../i18n/LanguageContext';
import { StateNotice } from './StateNotice';

export const CommandConsole: React.FC<{ onOpenWorkspaces: () => void }> = ({ onOpenWorkspaces }) => {
  const { isArabic } = useLanguage();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState('');
  const [shell, setShell] = useState<'powershell' | 'cmd'>('powershell');
  const [command, setCommand] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<TerminalExecResult | null>(null);
  const [history, setHistory] = useState<CommandRun[]>([]);
  const [error, setError] = useState('');

  const loadHistory = (id?: string) => api.listCommandHistory(id).then(setHistory).catch(console.error);
  useEffect(() => {
    api.listWorkspaces().then((items) => {
      setWorkspaces(items);
      const selected = items.find((item) => item.is_default) || items[0];
      if (selected) { setWorkspaceId(selected.id); setShell(selected.allowed_shells[0] || 'powershell'); loadHistory(selected.id); }
    }).catch(console.error);
  }, []);

  const selectedWorkspace = workspaces.find((item) => item.id === workspaceId);
  const execute = async () => {
    if (!workspaceId || !command.trim() || !confirmed) return;
    setRunning(true); setError(''); setResult(null);
    try {
      const approval = await api.requestApproval({ action_type: 'command', scope_type: 'workspace', scope_id: workspaceId, summary: `Run ${shell} command`, details: { command: command.trim(), shell } });
      await api.decideApproval(approval.id, true, 'Confirmed in Command Console.');
      const next = await api.runTerminal(command.trim(), shell, workspaceId, approval.id);
      setResult(next); setConfirmed(false); await loadHistory(workspaceId);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Command failed.'); }
    finally { setRunning(false); }
  };

  const presets = [
    { label: isArabic ? 'عرض الملفات' : 'List files', command: 'Get-ChildItem -Force' },
    { label: 'Git status', command: 'git status --short' },
    { label: isArabic ? 'إصدار Node' : 'Node version', command: 'node --version' },
  ];

  return (
    <div className="product-page console-page">
      <div className="product-page-head"><div><div className="eyebrow"><Command size={13} /> Workspace executor</div><h1>{isArabic ? 'وحدة الأوامر' : 'Command console'}</h1><p>{isArabic ? 'نفّذ PowerShell أو CMD داخل مجلد مشروع معتمد، مع تأكيد وسجل لكل أمر.' : 'Run PowerShell or CMD inside an approved project folder, with explicit confirmation and an audit trail.'}</p></div></div>

      {!workspaces.length ? (
        <section className="surface-card workspace-empty"><ShieldCheck size={24} /><h2>{isArabic ? 'يلزم إضافة Workspace أولًا' : 'A workspace is required'}</h2><p>{isArabic ? 'لن يعمل الـConsole على مستوى الجهاز بالكامل.' : 'The console will not run against the whole computer.'}</p><button type="button" className="btn-primary" onClick={onOpenWorkspaces}>{isArabic ? 'إضافة مساحة عمل' : 'Add workspace'}</button></section>
      ) : (
        <div className="console-layout">
          <div className="console-main">
            <section className="surface-card console-composer">
              <div className="console-context"><label><span>{isArabic ? 'مساحة العمل' : 'Workspace'}</span><select value={workspaceId} onChange={(event) => { const id = event.target.value; setWorkspaceId(id); const next = workspaces.find((item) => item.id === id); if (next) setShell(next.allowed_shells[0] || 'powershell'); loadHistory(id); }}>{workspaces.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label><span>Shell</span><select value={shell} onChange={(event) => setShell(event.target.value as typeof shell)}>{selectedWorkspace?.allowed_shells.map((item) => <option key={item} value={item}>{item}</option>)}</select></label><div className="console-path"><span>{isArabic ? 'نطاق التنفيذ' : 'Execution boundary'}</span><code>{selectedWorkspace?.path}</code></div></div>
              <div className="console-presets">{presets.map((preset) => <button type="button" key={preset.command} onClick={() => { setCommand(preset.command); setConfirmed(false); }}>{preset.label}</button>)}</div>
              <textarea dir="ltr" value={command} onChange={(event) => { setCommand(event.target.value); setConfirmed(false); }} placeholder="Get-ChildItem -Force" rows={6} />
              <label className="command-confirm"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /><span>{isArabic ? `أؤكد تشغيل هذا الأمر داخل ${selectedWorkspace?.name || 'Workspace'} فقط.` : `I confirm this command may run inside ${selectedWorkspace?.name || 'this workspace'} only.`}</span></label>
              {error && <StateNotice state="error" title="Command failed" detail={error} />}
              <div className="console-action"><span><ShieldCheck size={13} /> {selectedWorkspace?.permission_profile}</span><button type="button" className="btn-primary" onClick={execute} disabled={running || !command.trim() || !confirmed}><Play size={14} /> {running ? (isArabic ? 'جارٍ التنفيذ…' : 'Running…') : (isArabic ? 'تشغيل الأمر' : 'Run command')}</button></div>
            </section>

            {result && <section className={`surface-card command-result ${result.success ? 'success' : 'failed'}`}><div className="command-result-head"><div>{result.success ? <CheckCircle2 size={17} /> : <AlertTriangle size={17} />}<strong>{result.success ? (isArabic ? 'اكتمل الأمر' : 'Command completed') : (isArabic ? 'فشل الأمر' : 'Command failed')}</strong></div><span><Clock3 size={12} /> {result.duration_ms}ms · exit {result.exit_code}</span></div><pre>{result.stdout || result.stderr || (isArabic ? 'اكتمل دون مخرجات.' : 'Completed without output.')}</pre></section>}
          </div>

          <aside className="surface-card command-history"><div className="panel-heading"><div><h2><History size={14} /> {isArabic ? 'سجل الأوامر' : 'Command history'}</h2><p>{isArabic ? 'داخل مساحة العمل الحالية' : 'For the current workspace'}</p></div></div>{!history.length ? <div className="mini-empty"><TerminalSquare size={20} /><span>{isArabic ? 'لا توجد أوامر بعد' : 'No commands yet'}</span></div> : history.map((item) => <button type="button" key={item.id} onClick={() => { setCommand(item.command); setConfirmed(false); }}><span className={`status-dot ${item.status === 'completed' ? 'status-online' : ''}`} /><div><code>{item.command}</code><small>{new Date(item.created_at).toLocaleString()} · exit {item.exit_code ?? '—'}</small></div></button>)}</aside>
        </div>
      )}
    </div>
  );
};

