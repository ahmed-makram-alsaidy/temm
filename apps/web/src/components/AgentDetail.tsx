import React, { useCallback, useEffect, useState } from 'react';
import { Check, KeyRound, RefreshCw, Save, Trash2, X } from 'lucide-react';
import type { Agent } from '../services/api';
import { api } from '../services/api';
import { StateNotice } from './StateNotice';
import { useDialogFocus } from '../accessibility';

interface AgentDetailProps {
  agent: Agent;
  onClose: () => void;
  onChanged: () => Promise<void>;
  isArabic: boolean;
}

export const AgentDetail: React.FC<AgentDetailProps> = ({ agent, onClose, onChanged, isArabic }) => {
  const [current, setCurrent] = useState(agent);
  const [name, setName] = useState(agent.name);
  const [description, setDescription] = useState(agent.description || '');
  const [executable, setExecutable] = useState(agent.detected_path || agent.cli_command);
  const [versionArgs, setVersionArgs] = useState(agent.version_probe_args.join('\n'));
  const [invocationArgs, setInvocationArgs] = useState(agent.invocation_args.join('\n'));
  const [secretReference, setSecretReference] = useState('AGENT_API_KEY');
  const [secretValue, setSecretValue] = useState('');
  const [secrets, setSecrets] = useState<Array<{ reference: string; configured: boolean }>>([]);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const manual = current.discovery_source === 'manual';
  const { dialogRef, closeRef } = useDialogFocus(onClose);

  const loadSecrets = useCallback(async () => setSecrets(await api.listAgentSecrets(current.id)), [current.id]);
  useEffect(() => { loadSecrets().catch(() => setSecrets([])); }, [loadSecrets]);

  const run = async (action: string, callback: () => Promise<void>) => {
    setBusy(action); setError('');
    try { await callback(); await onChanged(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Action failed.'); }
    finally { setBusy(''); }
  };

  const save = () => run('save', async () => {
    const updated = await api.updateAgent(current.id, {
      expected_revision: current.revision,
      name: name.trim(),
      description,
      executable: executable.trim(),
      version_probe_args: versionArgs.split(/\r?\n/).map((item) => item.trim()).filter(Boolean),
      invocation_args: invocationArgs.split(/\r?\n/).map((item) => item.trim()).filter(Boolean),
    });
    setCurrent(updated);
  });

  const toggle = () => run('toggle', async () => {
    const updated = await api.updateAgent(current.id, { expected_revision: current.revision, user_enabled: !current.user_enabled });
    setCurrent(updated);
  });

  const rescan = () => run('rescan', async () => {
    await api.rescanAgent(current.id);
    const next = (await api.listAgents()).find((item) => item.id === current.id);
    if (next) setCurrent(next);
  });

  const checkAuth = () => run('auth', async () => {
    await api.checkAgentAuth(current.id);
    const next = (await api.listAgents()).find((item) => item.id === current.id);
    if (next) setCurrent(next);
  });

  const saveSecret = () => run('secret', async () => {
    await api.setAgentSecret(current.id, secretReference, secretValue);
    setSecretValue('');
    await loadSecrets();
    const next = (await api.listAgents()).find((item) => item.id === current.id);
    if (next) setCurrent(next);
  });

  const removeSecret = (reference: string) => run(`secret-${reference}`, async () => {
    await api.deleteAgentSecret(current.id, reference);
    await loadSecrets();
    const next = (await api.listAgents()).find((item) => item.id === current.id);
    if (next) setCurrent(next);
  });

  const remove = () => {
    if (!window.confirm(isArabic ? `إزالة ${current.name}؟` : `Remove ${current.name}?`)) return;
    run('remove', async () => { await api.deleteAgent(current.id); onClose(); });
  };

  return <div className="agent-detail-backdrop" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) onClose(); }}>
    <section ref={dialogRef} tabIndex={-1} className="agent-detail surface-card" role="dialog" aria-modal="true" aria-labelledby="agent-detail-title">
      <header><div><span className={`status-badge discovery-${current.discovery_state}`}>{current.discovery_state}</span><h2 id="agent-detail-title">{current.name}</h2><p>{current.tool_kind} · {current.discovery_source} · revision {current.revision}</p></div><button ref={closeRef} type="button" aria-label="Close" onClick={onClose}><X size={17} /></button></header>
      {error && <StateNotice state="error" title="Agent update failed" detail={error} />}
      <div className="agent-detail-grid">
        <section><h3>{isArabic ? 'الحالة والأدلة' : 'State & evidence'}</h3><dl><div><dt>Lifecycle</dt><dd>{current.lifecycle_status} · {current.user_enabled ? 'enabled' : 'disabled'}</dd></div><div><dt>Version</dt><dd>{current.version || 'Unverified'}</dd></div><div><dt>Executable</dt><dd><code>{current.detected_path || 'Not available'}</code></dd></div><div><dt>Last checked</dt><dd>{current.last_checked_at ? new Date(current.last_checked_at).toLocaleString() : 'Never'}</dd></div><div><dt>Auth</dt><dd>{current.auth_state} · {current.auth_method}</dd></div></dl><div className="agent-detail-actions"><button type="button" className="btn-secondary" onClick={toggle} disabled={!!busy}>{current.user_enabled ? 'Disable' : 'Enable'}</button><button type="button" className="btn-secondary" onClick={rescan} disabled={!!busy}><RefreshCw size={13} /> Rescan</button>{current.auth_state !== 'not_required' && <button type="button" className="btn-secondary" onClick={checkAuth} disabled={!!busy}><Check size={13} /> Check auth</button>}</div></section>
        <section><h3>{isArabic ? 'القدرات' : 'Capabilities'}</h3><div className="asset-tags">{current.capabilities.length ? current.capabilities.map((item) => <span key={item}>{item}</span>) : <span>None declared</span>}</div><pre className="agent-evidence-json">{JSON.stringify(current.discovery_evidence, null, 2)}</pre></section>
      </div>
      {manual && <section className="agent-edit-section"><h3>{isArabic ? 'إعداد الوكيل اليدوي' : 'Manual Agent configuration'}</h3><div className="wizard-grid"><label><span>Name</span><input className="input-text" value={name} onChange={(event) => setName(event.target.value)} /></label><label><span>Executable</span><input className="input-text font-mono" value={executable} onChange={(event) => setExecutable(event.target.value)} /></label><label><span>Description</span><textarea className="input-text" value={description} onChange={(event) => setDescription(event.target.value)} rows={3} /></label><label><span>Version arguments</span><textarea className="input-text font-mono" value={versionArgs} onChange={(event) => setVersionArgs(event.target.value)} rows={3} /></label><label><span>Invocation arguments</span><textarea className="input-text font-mono" value={invocationArgs} onChange={(event) => setInvocationArgs(event.target.value)} rows={3} /></label></div><button type="button" className="btn-primary" onClick={save} disabled={!!busy || !name.trim() || !executable.trim()}><Save size={14} /> Save & verify</button></section>}
      {current.auth_state !== 'not_required' && <section className="agent-secret-section"><h3><KeyRound size={14} /> {isArabic ? 'مراجع الأسرار' : 'Secret references'}</h3><p>{isArabic ? 'القيمة تُكتب فقط ولا تُعرض مرة أخرى.' : 'Values are write-only and are never returned.'}</p><div className="agent-secret-form"><input className="input-text font-mono" value={secretReference} onChange={(event) => setSecretReference(event.target.value.toUpperCase())} aria-label="Secret reference" /><input className="input-text" type="password" value={secretValue} onChange={(event) => setSecretValue(event.target.value)} aria-label="Secret value" autoComplete="new-password" /><button type="button" className="btn-secondary" onClick={saveSecret} disabled={!!busy || !secretReference || !secretValue}>Save</button></div><div className="agent-secret-list">{secrets.map((item) => <div key={item.reference}><span>{item.reference}</span><strong>{item.configured ? 'Configured' : 'Missing'}</strong><button type="button" onClick={() => removeSecret(item.reference)} disabled={!!busy}>Remove</button></div>)}</div></section>}
      <footer>{manual && current.lifecycle_status !== 'retired' && <button type="button" className="btn-danger" onClick={remove} disabled={!!busy}><Trash2 size={13} /> Remove Agent</button>}<span>{busy ? 'Working…' : 'Changes are persisted locally.'}</span></footer>
    </section>
  </div>;
};
