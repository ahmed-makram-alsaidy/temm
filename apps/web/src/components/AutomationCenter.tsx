import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowDown, Blocks, CheckCircle2, FileInput, GitBranch, Play, RefreshCw, ShieldCheck, Sparkles, Workflow } from 'lucide-react';
import { api } from '../services/api';
import { useLanguage } from '../i18n/LanguageContext';
import { StateNotice } from './StateNotice';

type AutomationTab = 'skills' | 'workflows';

export const AutomationCenter: React.FC<{ onLaunchTask: (prompt: string, mode: string) => void }> = ({ onLaunchTask }) => {
  const { isArabic } = useLanguage();
  const [tab, setTab] = useState<AutomationTab>('skills');
  const [skills, setSkills] = useState<any[]>([]);
  const [workflows, setWorkflows] = useState<any[]>([]);
  const [folderPath, setFolderPath] = useState('');
  const [importing, setImporting] = useState(false);
  const [importMessage, setImportMessage] = useState('');
  const [selectedSkillId, setSelectedSkillId] = useState('');
  const [taskInput, setTaskInput] = useState('');
  const [preparing, setPreparing] = useState(false);
  const [error, setError] = useState('');
  const [builderVersion, setBuilderVersion] = useState(1);
  const [builderNodeId, setBuilderNodeId] = useState('');
  const [builderNodeType, setBuilderNodeType] = useState('task');
  const [builderNodes, setBuilderNodes] = useState<Array<{ id: string; type: string }>>([]);
  const [builderMessage, setBuilderMessage] = useState('');
  const [liveRunId, setLiveRunId] = useState('');
  const [liveEvidence, setLiveEvidence] = useState<any>(null);
  const [liveState, setLiveState] = useState<'idle' | 'connecting' | 'connected' | 'reconnecting' | 'error'>('idle');

  const load = useCallback(async () => {
    const [skillData, workflowData] = await Promise.all([api.listSkills(), api.listWorkflows()]);
    setSkills(skillData); setWorkflows(workflowData);
    setSelectedSkillId((current) => current || skillData[0]?.id || '');
  }, []);
  useEffect(() => { load().catch(console.error); }, [load]);

  const selectedSkill = useMemo(() => skills.find((item) => item.id === selectedSkillId), [skills, selectedSkillId]);

  const importFolder = async () => {
    if (!folderPath.trim()) return;
    setImporting(true); setImportMessage(''); setError('');
    try {
      const result = await api.importSkillsFolder(folderPath.trim());
      setImportMessage(isArabic ? `تم استيراد ${result.imported_count} مهارة جديدة.` : `Imported ${result.imported_count} new skills.`);
      await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Import failed.'); }
    finally { setImporting(false); }
  };

  const prepareSkill = async () => {
    if (!selectedSkill || !taskInput.trim()) return;
    setPreparing(true); setError('');
    try {
      const result = await api.runSkill(selectedSkill.id, taskInput.trim());
      if (!result.formatted_prompt) {
        setError(isArabic ? 'هذه المهارة Script وتحتاج Workspace قبل التنفيذ. تشغيل Scripts المباشر غير مفعّل من هذه الشاشة.' : 'This is a script skill and needs a workspace. Direct script execution is not enabled from this screen.');
        return;
      }
      onLaunchTask(result.formatted_prompt, 'balanced');
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not prepare skill.'); }
    finally { setPreparing(false); }
  };

  const addBuilderNode = () => {
    const id = builderNodeId.trim();
    if (!id || builderNodes.some((node) => node.id === id)) { setBuilderMessage('Node id is required and must be unique.'); return; }
    setBuilderNodes((current) => [...current, { id, type: builderNodeType }]); setBuilderNodeId(''); setBuilderMessage('');
  };
  const connectLiveRun = async (reconnecting = false) => {
    if (!liveRunId.trim()) return;
    setLiveState(reconnecting ? 'reconnecting' : 'connecting');
    try {
      const [run, details] = await Promise.all([api.getRun(liveRunId.trim()), api.getRunDetails(liveRunId.trim())]);
      setLiveEvidence({ run, ...details }); setLiveState('connected');
    } catch { setLiveState('error'); }
  };
  const validateBuilder = () => {
    if (builderNodes.length < 2) { setBuilderMessage('Add at least two nodes before test mode.'); return; }
    setBuilderMessage(`Version ${builderVersion} is a valid sequential DAG in test mode. No execution was started.`);
  };

  return (
    <div className="product-page automation-page">
      <div className="product-page-head"><div><div className="eyebrow"><Blocks size={13} /> Capability layer</div><h1>{isArabic ? 'المهارات وسير العمل' : 'Skills & workflows'}</h1><p>{isArabic ? 'حوّل الخبرة المتكررة إلى مهارات قابلة لإعادة الاستخدام، وراجع قوالب الـMulti-agent قبل تشغيلها.' : 'Turn repeatable expertise into reusable skills, and inspect multi-agent workflow templates before they run.'}</p></div><button type="button" className="btn-secondary" onClick={() => load()}><RefreshCw size={14} /> {isArabic ? 'تحديث' : 'Refresh'}</button></div>
      <div className="tab-strip automation-tabs"><button type="button" className={tab === 'skills' ? 'active' : ''} onClick={() => setTab('skills')}><Sparkles size={14} /> {isArabic ? 'Delegate Skills' : 'Delegate skills'} <span>{skills.length}</span></button><button type="button" className={tab === 'workflows' ? 'active' : ''} onClick={() => setTab('workflows')}><Workflow size={14} /> {isArabic ? 'قوالب Workflows' : 'Workflow templates'} <span>{workflows.length}</span></button></div>

      {tab === 'skills' && <div className="automation-layout">
        <div className="automation-main">
          <section className="surface-card skill-launcher"><div className="panel-heading"><div><h2>{isArabic ? 'استخدم مهارة في مهمة جديدة' : 'Use a skill in a new task'}</h2><p>{isArabic ? 'المهارة تصف القدرات المطلوبة، والـRouter يختار المنفّذ الجاهز لاحقًا.' : 'The skill describes required capabilities; the router chooses a ready executor next.'}</p></div></div><label><span>{isArabic ? 'المهارة' : 'Skill'}</span><select className="input-text" value={selectedSkillId} onChange={(event) => setSelectedSkillId(event.target.value)}>{skills.map((skill) => <option value={skill.id} key={skill.id}>{skill.name} · {skill.adapter_type}</option>)}</select></label><label><span>{isArabic ? 'مدخل المهمة' : 'Task input'}</span><textarea value={taskInput} onChange={(event) => setTaskInput(event.target.value)} rows={5} placeholder={isArabic ? 'مثال: راجع نظام المصادقة في المشروع…' : 'e.g. Review the authentication system…'} /></label>{selectedSkill && <div className="skill-requirements"><span>{isArabic ? 'القدرات المطلوبة' : 'Required capabilities'}</span>{selectedSkill.required_capabilities.map((item: string) => <code key={item}>{item}</code>)}</div>}{error && <StateNotice state="error" title="Automation operation failed" detail={error} />}<button type="button" className="btn-primary" onClick={prepareSkill} disabled={preparing || !taskInput.trim()}><Play size={14} /> {preparing ? (isArabic ? 'جارٍ التحضير…' : 'Preparing…') : (isArabic ? 'تحضير المهمة' : 'Prepare task')}</button></section>
          <div className="skill-grid">{skills.map((skill) => <article className="surface-card skill-card" key={skill.id}><div className="skill-card-head"><span><Sparkles size={15} /></span><span className="status-badge">{skill.adapter_type}</span></div><h3>{skill.name}</h3><p>{skill.description}</p><div>{skill.required_capabilities.map((item: string) => <code key={item}>{item}</code>)}</div><button type="button" onClick={() => { setSelectedSkillId(skill.id); window.scrollTo({ top: 0, behavior: 'smooth' }); }}>{isArabic ? 'استخدام المهارة' : 'Use skill'}</button></article>)}</div>
        </div>
        <aside className="surface-card skill-importer"><FileInput size={20} /><h2>{isArabic ? 'استيراد مجلد Skills' : 'Import skills folder'}</h2><p>{isArabic ? 'نفحص ملفات ps1 وpy وmd وsh ونضيف تعريفاتها إلى السجل.' : 'Scan ps1, py, md, and sh files and add their definitions to the registry.'}</p><label><span>{isArabic ? 'المسار الكامل' : 'Absolute folder path'}</span><input className="input-text font-mono" dir="ltr" value={folderPath} onChange={(event) => setFolderPath(event.target.value)} placeholder="D:\\skills" /></label><button type="button" className="btn-secondary" onClick={importFolder} disabled={importing || !folderPath.trim()}>{importing ? (isArabic ? 'جارٍ الفحص…' : 'Scanning…') : (isArabic ? 'فحص واستيراد' : 'Scan and import')}</button>{importMessage && <div className="scan-result"><CheckCircle2 size={14} /> {importMessage}</div>}<small><ShieldCheck size={12} /> {isArabic ? 'الاستيراد يسجل المهارات فقط؛ تشغيل Script يحتاج Workspace.' : 'Import registers skills only; script execution still requires a workspace.'}</small></aside>
      </div>}

      {tab === 'workflows' && <>
        <section className="surface-card workflow-notice"><ShieldCheck size={17} /><div><strong>{isArabic ? 'القوالب ظاهرة، والتنفيذ المصطنع متوقف' : 'Templates are visible; simulated execution is disabled'}</strong><span>{isArabic ? 'لن نسجل Workflow كمكتمل قبل توصيل كل Node بمنفّذ حقيقي، وإضافة أحداث وسجل مستقل له.' : 'A workflow will not be marked complete until every node has a real executor, events, and an audit log.'}</span></div></section>
        <section className="surface-card workflow-builder"><div className="panel-heading"><div><h2>Live workflow evidence</h2><p>Connect a canonical run. No node state is synthesized.</p></div><span className={`status-badge ${liveState}`}>{liveState}</span></div><div className="brain-editor"><input aria-label="Canonical run id" value={liveRunId} onChange={(event) => setLiveRunId(event.target.value)} placeholder="run-id" /><button type="button" className="btn-secondary" onClick={() => void connectLiveRun(liveEvidence ? true : false)}>{liveEvidence ? 'Reconnect' : 'Connect'}</button></div>{liveEvidence && <div className="run-evidence-grid"><section><h3>Run</h3><p>{liveEvidence.run.status} · {liveEvidence.run.selected_agent_id || liveEvidence.run.selected_model_id || 'unknown executor'}</p><small>Cost: {liveEvidence.run.actual_cost ?? 'unknown'} · {liveEvidence.run.cost_provenance}</small></section><section><h3>Attempts</h3>{liveEvidence.attempts.map((attempt: any) => <div className="run-evidence-row" key={attempt.id}><strong>#{attempt.attempt_number} · {attempt.executor_type}</strong><span className={`status-badge ${attempt.status}`}>{attempt.status}</span></div>)}</section><section><h3>Evidence events</h3><p>{liveEvidence.events.length} persisted events</p><small>{liveEvidence.events.slice(-3).map((event: any) => event.event_type).join(' · ') || 'No workflow-specific events'}</small></section><section><h3>Output</h3><pre className="run-output-evidence">{liveEvidence.output.map((item: any) => item.content).join('') || 'No persisted output.'}</pre></section></div>}</section>
        <section className="surface-card workflow-builder"><div className="panel-heading"><div><h2>Workflow builder</h2><p>Keyboard-accessible sequential DAG editor · version {builderVersion}</p></div><button type="button" className="btn-secondary" onClick={() => { setBuilderVersion((value) => value + 1); setBuilderMessage('Created a new draft version.'); }}>New version</button></div><div className="brain-editor"><input aria-label="Node id" value={builderNodeId} onChange={(event) => setBuilderNodeId(event.target.value)} placeholder="node-id" /><select aria-label="Node type" value={builderNodeType} onChange={(event) => setBuilderNodeType(event.target.value)}>{['task', 'classify', 'router', 'agent', 'judge', 'critic', 'gate', 'approval', 'output'].map((type) => <option key={type}>{type}</option>)}</select><button type="button" className="btn-primary" onClick={addBuilderNode}>Add node</button></div><ol className="workflow-builder-list">{builderNodes.map((node, index) => <li key={node.id}><span><strong>{node.id}</strong> · {node.type}</span><button type="button" aria-label={`Remove ${node.id}`} onClick={() => setBuilderNodes((current) => current.filter((item) => item.id !== node.id))}>Remove</button>{index < builderNodes.length - 1 && <small>output → next input</small>}</li>)}</ol><button type="button" className="btn-secondary" onClick={validateBuilder}>Validate in test mode</button>{builderMessage && <div className="scan-result" role="status">{builderMessage}</div>}</section>
        <div className="workflow-grid">{workflows.map((workflow) => <article className="surface-card workflow-card" key={workflow.id}><div className="workflow-card-head"><span><GitBranch size={16} /></span><span className="status-badge">Template</span></div><h2>{workflow.name}</h2><p>{workflow.description}</p><div className="workflow-nodes">{workflow.nodes.map((node: any, index: number) => <React.Fragment key={node.id}><div><strong>{node.title || node.type}</strong><small>{node.type} · {node.model || 'router'}</small></div>{index < workflow.nodes.length - 1 && <ArrowDown size={13} />}</React.Fragment>)}</div><div className="workflow-card-footer"><span>{workflow.nodes.length} nodes · {workflow.edges.length} edges</span><button type="button" disabled>{isArabic ? 'يحتاج منفّذين' : 'Executors required'}</button></div></article>)}</div>
      </>}
    </div>
  );
};
