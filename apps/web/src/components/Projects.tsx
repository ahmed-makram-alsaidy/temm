import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../services/api';
import { useLanguage } from '../i18n/LanguageContext';
import { deriveProjectWorkspaceModel } from './project-workspace-model';
import type { ProjectStage, RunDetailRecord, WorkspaceActionKind } from './project-workspace-model';
import { ProjectWorkspace } from './ProjectWorkspace';

const slugify = (value: string) => value.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 120) || `project-${Date.now()}`;

export const Projects: React.FC<{ onNavigate?: (tab: string) => void }> = ({ onNavigate }) => {
  const { isArabic } = useLanguage();
  const [projects, setProjects] = useState<any[]>([]);
  const [selected, setSelected] = useState<any>(null);
  const [blueprints, setBlueprints] = useState<any[]>([]);
  const [requirements, setRequirements] = useState<any>(null);
  const [plan, setPlan] = useState<any>(null);
  const [completion, setCompletion] = useState<any>(null);
  const [deliverables, setDeliverables] = useState<any[]>([]);
  const [workspaces, setWorkspaces] = useState<any[]>([]);
  const [projectWorkspaces, setProjectWorkspaces] = useState<any[]>([]);
  const [readiness, setReadiness] = useState<any>(null);
  const [runDetails, setRunDetails] = useState<Record<string, RunDetailRecord>>({});
  const [showWorkspaceSetup, setShowWorkspaceSetup] = useState(false);
  const [workspaceChoice, setWorkspaceChoice] = useState('');
  const [workspaceForm, setWorkspaceForm] = useState({ name: '', path: '' });
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: '', purpose: '' });
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [stage, setStage] = useState<ProjectStage>('goal');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  const activeBlueprint = useMemo(() => blueprints[0] || null, [blueprints]);
  // Which project the visible surface belongs to. Reloads are 9 concurrent reads, so a
  // slower reload for a project the owner has already left could land last and repaint
  // this project's card with another project's connected folder, readiness and task
  // states. That is not a cosmetic mix-up: "Ready to execute" and a primary folder from
  // a different project is an unsafe basis for dispatch.
  const visibleProjectRef = useRef<string>('');
  const reloadProject = useCallback(async (project = selected) => {
    if (!project) return;
    visibleProjectRef.current = project.id;
    const [nextBlueprints, nextBrain, nextRequirements, nextPlan, nextCompletion, nextDeliverables, nextWorkspaces, nextProjectWorkspaces, nextReadiness] = await Promise.all([
      api.listBlueprints(project.id), api.listProjectBrain(project.id), api.getProjectRequirements(project.id), api.getProjectPlan(project.id), api.getProjectCompletion(project.id), api.listProjectDeliverables(project.id), api.listWorkspaces(), api.listProjectWorkspaces(project.id), api.getProjectExecutionReadiness(project.id),
    ]);
    if (visibleProjectRef.current !== project.id) return;
    setBlueprints(nextBlueprints); setRequirements(nextRequirements); setPlan(nextPlan); setCompletion(nextCompletion); setDeliverables(nextDeliverables); setWorkspaces(nextWorkspaces); setProjectWorkspaces(nextProjectWorkspaces); setReadiness(nextReadiness);
    const details = await Promise.all((nextPlan.tasks || []).filter((task: any) => task.current_run_id).map(async (task: any): Promise<[string, RunDetailRecord]> => {
      const [run, runDetail] = await Promise.all([api.getRun(task.current_run_id), api.getRunDetails(task.current_run_id)]);
      return [task.id, { ...runDetail, run }];
    }));
    if (visibleProjectRef.current !== project.id) return;
    setRunDetails(Object.fromEntries(details));
    const orchestration = nextPlan.orchestrations?.[0];
    const tasks = nextPlan.tasks || [];
    if (nextCompletion.ready) setStage('complete');
    else if (orchestration?.state === 'running' && !nextProjectWorkspaces.length && tasks.every((task: any) => task.state === 'planned')) setStage('attention');
    else if (tasks.some((task: any) => ['running'].includes(task.state)) || orchestration?.state === 'running') setStage('running');
    else if (tasks.some((task: any) => ['failed', 'blocked'].includes(task.state)) || nextPlan.needs?.some((need: any) => need.impact === 'blocking' && need.state !== 'resolved')) setStage('attention');
    else if (nextBlueprints[0]?.status === 'approved' && nextRequirements?.requirements?.some((item: any) => item.status === 'draft')) setStage('approval');
    else if (nextBlueprints[0]?.status === 'approved' && nextRequirements?.requirements?.length && nextRequirements.requirements.every((item: any) => ['approved', 'completed', 'waived'].includes(item.status))) setStage('ready');
    else if (nextBlueprints[0]?.status === 'proposed') {
      const confirmedFacts = new Set(nextBrain.filter((fact: any) => fact.truth_state === 'confirmed').map((fact: any) => fact.fact_key));
      const missing = nextBlueprints[0].content?.questions?.some((question: any) => question.required && !confirmedFacts.has(question.question_id));
      setStage(missing ? 'clarify' : 'approval');
    }
    else if (nextBlueprints[0]) setStage('blueprint');
    else setStage('goal');
  }, [selected]);

  const loadProjects = useCallback(async () => {
    const items = await api.listProjects(); setProjects(items);
    if (!selected && items[0]) {
      const remembered = localStorage.getItem('temm_active_project_id');
      const project = items.find((item) => item.id === remembered) || items[0];
      setSelected(project); await reloadProject(project);
    }
  }, [selected, reloadProject]);
  useEffect(() => { void loadProjects().catch((reason) => setError(String(reason))); }, [loadProjects]);

  const createProject = async () => {
    if (!form.name.trim() || !form.purpose.trim()) return;
    setBusy('create'); setError('');
    try {
      const project = await api.createProject({ name: form.name.trim(), purpose: form.purpose.trim(), slug: slugify(form.name), project_type: 'software' });
      localStorage.setItem('temm_active_project_id', project.id); setProjects((current) => [...current, project]); setSelected(project); setShowCreate(false); setForm({ name: '', purpose: '' }); setStage('goal'); await reloadProject(project);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Project creation failed.'); } finally { setBusy(''); }
  };

  const generateBlueprint = async () => {
    if (!selected) return;
    setBusy('blueprint'); setError('');
    try { await api.createBlueprintFromGoal(selected.id, selected.purpose); await reloadProject(); } catch (reason) { setError(reason instanceof Error ? reason.message : 'Blueprint generation failed.'); } finally { setBusy(''); }
  };

  const saveClarifications = async () => {
    if (!selected || !activeBlueprint) return;
    setBusy('clarify'); setError('');
    try {
      const visibleAnswers = [...document.querySelectorAll<HTMLTextAreaElement>('[data-project-question]')].map((field) => [field.dataset.projectQuestion || '', field.value] as const);
      const submittedAnswers = visibleAnswers.length ? visibleAnswers : Object.entries(answers);
      await Promise.all(submittedAnswers.filter(([factKey, value]) => factKey && value.trim()).map(([factKey, value]) => api.mergeProjectBrainFact(selected.id, { section: 'purpose', fact_key: factKey, value, truth_state: 'confirmed', provenance: 'owner_declared', source_type: 'user', source_id: 'local_owner', confidence: 1 })));
      await reloadProject();
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Clarifications could not be saved.'); } finally { setBusy(''); }
  };

  const approve = async () => {
    if (!activeBlueprint) return;
    setBusy('approve'); setError('');
    try {
      if (activeBlueprint.status === 'proposed') await api.approveBlueprint(activeBlueprint.id, activeBlueprint.revision);
      else {
        for (const item of (requirements?.requirements || []).filter((item: any) => item.status === 'draft')) {
          await api.updateProjectRequirement(item.id, item.revision, { truth_state: 'confirmed' });
          await api.approveProjectRequirement(item.id);
        }
      }
      await reloadProject();
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Approval failed.'); } finally { setBusy(''); }
  };

  const compilePlan = async () => {
    if (!selected || !activeBlueprint) return;
    setBusy('plan'); setError('');
    try { await api.compileProjectPlan(selected.id, activeBlueprint.id); await reloadProject(); } catch (reason) { setError(reason instanceof Error ? reason.message : 'Project plan compilation failed.'); } finally { setBusy(''); }
  };

  const startExecution = async () => {
    if (!selected || !activeBlueprint) return;
    setBusy('start'); setError('');
    try {
      let nextPlan = await api.getProjectPlan(selected.id);
      if (!nextPlan.tasks?.length) { await api.compileProjectPlan(selected.id, activeBlueprint.id); nextPlan = await api.getProjectPlan(selected.id); }
      let orchestration = nextPlan.orchestrations?.[0];
      if (!orchestration) orchestration = await api.createOrchestration(selected.id);
      for (const action of ['analyze', 'plan', 'approve', 'start']) {
        if (action === 'analyze' && orchestration.state !== 'new') continue;
        if (action === 'plan' && !['analyzed'].includes(orchestration.state)) continue;
        if (action === 'approve' && !['planned'].includes(orchestration.state)) continue;
        if (action === 'start' && !['approved'].includes(orchestration.state)) continue;
        orchestration = await api.commandOrchestration(orchestration.id, action);
      }
      const currentReadiness = await api.getProjectExecutionReadiness(selected.id); setReadiness(currentReadiness);
      const workspace = currentReadiness.workspace;
      if (!workspace) { setStage('attention'); setShowWorkspaceSetup(true); setError('Connect project folder so TEMM can execute the planned work inside an approved boundary.'); return; }
      if (!currentReadiness.ready) { setStage('attention'); setError(`Execution blocked — action required. ${readinessMessage(currentReadiness)}.`); return; }
      await api.dispatchOrchestration(orchestration.id, workspace.id); setStage('running');
      // One dispatch is one pass over the ready queue, and reconciliation - which credits
      // a requirement whose acceptance contract has been measured satisfied, and is
      // therefore what turns proven work into project completion - only runs when that
      // queue is empty. A single pass left a finished task with an uncredited requirement
      // and no affordance to continue, so the project sat on "Running" for ever with the
      // work already done and the deliverable unreachable. Passes are bounded and stop as
      // soon as the dispatcher reports it moved nothing further.
      for (let pass = 0; pass < 6; pass += 1) {
        const result = await api.dispatchOrchestration(orchestration.id, workspace.id);
        if (result?.status !== 'running' || !(result?.dispatched?.length > 0)) break;
      }
      await reloadProject();
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Project execution could not start.'); setStage('attention'); await reloadProject().catch(() => undefined); } finally { setBusy(''); }
  };

  const capabilityLabel = (value: any) => {
    const first = (value?.required_capabilities || [])[0];
    if (!first) return 'Execution capability';
    return ({ coding: 'Coding capability', research: 'Research capability', reasoning: 'Reasoning capability', general: 'General assistant capability' } as Record<string, string>)[first] || `${first.replace(/_/g, ' ')} capability`;
  };

  const readinessMessage = (value: any) => {
    const blockers = value?.blockers || [];
    const codes = new Set(blockers.map((item: any) => item.code));
    if (codes.has('workspace_required') || codes.has('permission_incompatible')) return 'Connect project folder';
    if (codes.has('capability_signin_required')) return `${capabilityLabel(value)} required`;
    if (codes.has('capability_unavailable')) return `${capabilityLabel(value)} required`;
    if (codes.has('host_capacity_unavailable')) return 'Execution blocked — action required';
    if ([...codes].some((code) => String(code).includes('auth'))) return `${capabilityLabel(value)} required`;
    if ([...codes].some((code) => String(code).includes('quota') || String(code).includes('allowance'))) return 'Execution account is out of available usage';
    if ([...codes].some((code) => String(code).includes('provider'))) return `${capabilityLabel(value)} required`;
    return blockers.length ? 'Execution blocked — action required' : 'Checking readiness…';
  };

  const connectWorkspace = async () => {
    if (!selected) return;
    setBusy('workspace'); setError('');
    try {
      let workspaceId = workspaceChoice;
      // A folder the owner already approved is not an error. Before this, typing a path
      // that was already an approved workspace failed with "already registered" and left
      // the project with no folder at all, even though the approval it needed existed.
      const normalize = (value: string) => value.trim().replace(/\//g, '\\').replace(/\\+$/, '').toLowerCase();
      if (!workspaceId && workspaceForm.path.trim()) {
        const existing = workspaces.find((item) => normalize(item.path || '') === normalize(workspaceForm.path));
        if (existing) workspaceId = existing.id;
      }
      if (!workspaceId && workspaceForm.name.trim() && workspaceForm.path.trim()) {
        const workspace = await api.createWorkspace({ name: workspaceForm.name.trim(), path: workspaceForm.path.trim(), permission_profile: 'developer', allowed_shells: ['powershell'], is_default: !workspaces.length });
        workspaceId = workspace.id;
      }
      if (!workspaceId) throw new Error('Choose an approved workspace or provide an existing local folder.');
      await api.bindProjectWorkspace(selected.id, workspaceId, 'primary');
      setShowWorkspaceSetup(false); setWorkspaceChoice(''); setWorkspaceForm({ name: '', path: '' }); await reloadProject();
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not connect the project folder.'); } finally { setBusy(''); }
  };

  // The files this project actually produced, taken from the acceptance contracts that
  // were measured and passed. Before this the deliverable action always asked to package
  // "." and every attempt failed with "Path must be an existing file", so a verified
  // project could never reach a downloadable package. Only clauses that assert a file's
  // content or presence contribute: a scope clause such as `changed_files_subset` lists
  // what a run was *allowed* to touch, which is not evidence that those files exist.
  const deliverablePaths = () => {
    const paths = new Set<string>();
    const walk = (evaluator: any) => {
      if (!evaluator || typeof evaluator !== 'object') return;
      const kind = String(evaluator.type || '');
      if (typeof evaluator.path === 'string' && evaluator.path.trim() && kind !== 'changed_files_subset') paths.add(evaluator.path);
      if (Array.isArray(evaluator.paths) && kind.includes('exist')) evaluator.paths.forEach((item: any) => { if (typeof item === 'string' && item.trim()) paths.add(item); });
      ['all', 'any', 'clauses', 'criteria'].forEach((key) => { if (Array.isArray(evaluator[key])) evaluator[key].forEach(walk); });
    };
    (plan?.tasks || []).filter((task: any) => task.state === 'completed').forEach((task: any) => (task.acceptance || []).forEach((item: any) => walk(item.evaluator)));
    return [...paths];
  };

  const packageDeliverable = async () => {
    const workspace = projectWorkspaces.find((item) => item.role === 'primary')?.workspace;
    if (!selected || !workspace) { setError('Connect project folder before packaging.'); return; }
    const paths = deliverablePaths();
    if (!paths.length) { setError('No acceptance-measured file has been produced yet, so there is nothing to package.'); return; }
    setBusy('package'); setError('');
    try { await api.packageProjectDeliverable(selected.id, { workspace_id: workspace.id, name: selected.slug, version: `0.1.${deliverables.length}`, relative_paths: paths }); await reloadProject(); } catch (reason) { setError(reason instanceof Error ? reason.message : 'Deliverable packaging failed.'); } finally { setBusy(''); }
  };

  const selectProject = (projectId: string) => {
    const project = projects.find((item) => item.id === projectId);
    if (!project || project.id === selected?.id) return;
    localStorage.setItem('temm_active_project_id', project.id);
    visibleProjectRef.current = project.id;
    setSelected(project);
    setBlueprints([]); setRequirements(null); setPlan(null); setCompletion(null); setDeliverables([]); setProjectWorkspaces([]); setReadiness(null); setRunDetails({}); setStage('goal'); setError('');
    void reloadProject(project).catch((reason) => setError(reason instanceof Error ? reason.message : 'Project data could not be loaded.'));
  };

  const handleWorkspaceAction = (kind: WorkspaceActionKind) => {
    switch (kind) {
      case 'understand-goal': void generateBlueprint(); break;
      case 'save-clarifications': void saveClarifications(); break;
      case 'approve-blueprint':
      case 'approve-requirements': void approve(); break;
      case 'compile-plan': void compilePlan(); break;
      case 'connect-workspace': setShowWorkspaceSetup(true); break;
      case 'open-tools': onNavigate?.('fleet'); break;
      case 'start-execution':
      case 'continue-execution': void startExecution(); break;
      case 'package-deliverable': void packageDeliverable(); break;
      case 'review-blocker':
      case 'download-deliverable': break;
    }
  };

  const workspaceModel = selected ? deriveProjectWorkspaceModel({
    project: selected,
    stage,
    blueprint: activeBlueprint,
    requirements: requirements?.requirements ?? [],
    plan,
    completion,
    deliverables,
    readiness,
    runDetails,
    busy,
    error,
    isArabic,
  }) : null;

  return <div className="projects-page temm-v3-projects-page">
    {workspaceModel ? (
      <ProjectWorkspace
        model={workspaceModel}
        projects={projects}
        answers={answers}
        primarySuppressed={showCreate || showWorkspaceSetup}
        onAnswer={(questionId, value) => setAnswers((current) => ({ ...current, [questionId]: value }))}
        onAction={handleWorkspaceAction}
        onNewProject={() => setShowCreate(true)}
        onSelectProject={selectProject}
      />
    ) : (
      <section className="temm-v3-empty">
        <div>
          <p className="temm-v3-kicker">{isArabic ? 'مساحة عمل النتيجة' : 'Outcome workspace'}</p>
          <h1>{isArabic ? 'ابدأ بنتيجة مشروع' : 'Start with a project outcome'}</h1>
          <p>{isArabic ? 'يجمع المشروع هدفك ومخططه وأدلة التنفيذ وحزمة التسليم.' : 'A project keeps your goal, blueprint, execution evidence, and deliverable together.'}</p>
          <button type="button" className="temm-v3-primary" onClick={() => setShowCreate(true)}>{isArabic ? 'أنشئ مشروعًا' : 'Create project'}</button>
        </div>
      </section>
    )}

    {showCreate && (
      <div className="temm-v3-sheet-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setShowCreate(false); }}>
        <section className="temm-v3-sheet" role="dialog" aria-modal="true" aria-labelledby="temm-v3-create-title" dir={isArabic ? 'rtl' : 'ltr'}>
          <h2 id="temm-v3-create-title">{isArabic ? 'ابدأ بالنتيجة' : 'Start with the outcome'}</h2>
          <p>{isArabic ? 'صف ما تريد إنجازه. يمكن إعداد الأدوات عندما يحتاجها التنفيذ.' : 'Describe what you want accomplished. Technical setup can follow when execution needs it.'}</p>
          <label><span>{isArabic ? 'اسم المشروع' : 'Project name'}</span><input autoFocus aria-label="Project name" placeholder="e.g. Clinic website" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
          <label><span>{isArabic ? 'ما النتيجة التي تريد من TEMM إنجازها؟' : 'What do you want TEMM to accomplish?'}</span><textarea aria-label="Project goal" rows={5} placeholder="Describe the finished result in your own words…" value={form.purpose} onChange={(event) => setForm({ ...form, purpose: event.target.value })} /></label>
          <div className="temm-v3-sheet-actions"><button type="button" className="temm-v3-sheet-secondary" onClick={() => setShowCreate(false)}>{isArabic ? 'إلغاء' : 'Cancel'}</button><button type="button" className="temm-v3-primary" disabled={busy === 'create' || !form.name.trim() || !form.purpose.trim()} onClick={() => void createProject()}>{busy === 'create' ? (isArabic ? 'جارٍ الإنشاء…' : 'Creating…') : (isArabic ? 'أنشئ المشروع' : 'Create project')}</button></div>
        </section>
      </div>
    )}

    {showWorkspaceSetup && (
      <div className="temm-v3-sheet-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setShowWorkspaceSetup(false); }}>
        <section className="temm-v3-sheet" role="dialog" aria-modal="true" aria-labelledby="temm-v3-workspace-title" dir={isArabic ? 'rtl' : 'ltr'}>
          <h2 id="temm-v3-workspace-title">{isArabic ? 'اربط مجلد المشروع' : 'Connect project folder'}</h2>
          <p>{isArabic ? 'اختر مجلدًا معتمدًا أو سجّل مجلدًا محليًا موجودًا ليبقى التنفيذ داخل حد واضح.' : 'Choose an approved folder or register an existing local folder so execution stays inside an explicit boundary.'}</p>
          <p className="temm-v3-sheet-note">{isArabic ? 'وعد الحد: لا يقرأ TEMM ولا يكتب إلا داخل هذا المجلد.' : 'The boundary is a promise: TEMM can only read and write inside this folder.'}</p>
          {workspaces.length > 0 && <label><span>{isArabic ? 'مجلد معتمد' : 'Approved folder'}</span><select value={workspaceChoice} onChange={(event) => setWorkspaceChoice(event.target.value)}><option value="">{isArabic ? 'اختر مجلدًا' : 'Choose a folder'}</option>{workspaces.map((workspace) => <option value={workspace.id} key={workspace.id}>{workspace.name} · {workspace.path}</option>)}</select></label>}
          <label><span>{isArabic ? 'اسم المجلد الجديد' : 'New folder name'}</span><input value={workspaceForm.name} onChange={(event) => setWorkspaceForm({ ...workspaceForm, name: event.target.value })} placeholder="Project workspace" /></label>
          <label><span>{isArabic ? 'المسار المحلي الموجود' : 'Existing local path'}</span><input dir="ltr" value={workspaceForm.path} onChange={(event) => setWorkspaceForm({ ...workspaceForm, path: event.target.value })} placeholder="D:\\projects\\example" /></label>
          {error && <small className="temm-v3-sheet-note" role="alert">{error}</small>}
          <div className="temm-v3-sheet-actions"><button type="button" className="temm-v3-sheet-secondary" onClick={() => setShowWorkspaceSetup(false)}>{isArabic ? 'إلغاء' : 'Cancel'}</button><button type="button" className="temm-v3-primary" disabled={busy === 'workspace' || (!workspaceChoice && !workspaceForm.path.trim())} onClick={() => void connectWorkspace()}>{busy === 'workspace' ? (isArabic ? 'جارٍ الربط…' : 'Connecting…') : (isArabic ? 'اربط المجلد' : 'Connect folder')}</button></div>
        </section>
      </div>
    )}
  </div>;
}
