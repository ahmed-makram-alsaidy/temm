import { useEffect, useReducer, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import {
  AcceptanceGate,
  ClosedCell,
  EvidencePackage,
  ExecutionConnector,
  ExecutionNode,
  MicroSpine,
  StatusPrimitive,
} from './visual-primitives';
import type {
  AttentionState,
  AttemptView,
  LifecycleStation,
  ProjectRecord,
  ProjectWorkspaceModel,
  WorkTask,
  WorkspaceActionKind,
} from './project-workspace-model';
import { deriveMotionPlan, emptyTaskMotionPlan } from './project-workspace-motion';
import type { ProjectMotionEvent, TaskMotionPlan } from './project-workspace-motion';
import './project-workspace.css';

interface ProjectWorkspaceProps {
  model: ProjectWorkspaceModel;
  projects?: ProjectRecord[];
  answers?: Record<string, string>;
  primarySuppressed?: boolean;
  onAnswer?: (questionId: string, value: string) => void;
  onAction: (kind: WorkspaceActionKind) => void;
  onNewProject?: () => void;
  onSelectProject?: (projectId: string) => void;
  initialSheetTaskId?: string | null;
}

const lifecycleLabels: Record<LifecycleStation, { en: string; ar: string }> = {
  goal: { en: 'Goal', ar: 'الهدف' },
  blueprint: { en: 'Blueprint', ar: 'الفهم' },
  requirements: { en: 'Requirements', ar: 'المتطلبات' },
  execution: { en: 'Execution', ar: 'التنفيذ' },
  evidence: { en: 'Evidence', ar: 'الأدلة' },
  deliverable: { en: 'Deliverable', ar: 'التسليم' },
};

const actionLabels: Record<WorkspaceActionKind, { en: string; ar: string }> = {
  'understand-goal': { en: 'Understand this goal', ar: 'افهم هذا الهدف' },
  'save-clarifications': { en: 'Continue with answers', ar: 'تابع بالإجابات' },
  'approve-blueprint': { en: 'Approve blueprint', ar: 'اعتمد المخطط' },
  'approve-requirements': { en: 'Approve requirements', ar: 'اعتمد المتطلبات' },
  'compile-plan': { en: 'Compile plan', ar: 'حوّل المتطلبات إلى خطة' },
  'connect-workspace': { en: 'Connect project folder', ar: 'اربط مجلد المشروع' },
  'open-tools': { en: 'Open capability setup', ar: 'افتح إعداد القدرة' },
  'start-execution': { en: 'Start execution', ar: 'ابدأ التنفيذ' },
  'continue-execution': { en: 'Continue execution', ar: 'تابع التنفيذ' },
  'review-blocker': { en: 'Review blocker evidence', ar: 'راجع دليل العائق' },
  'package-deliverable': { en: 'Package deliverable', ar: 'جهّز حزمة التسليم' },
  'download-deliverable': { en: 'Download deliverable', ar: 'نزّل حزمة التسليم' },
};

const taskStateLabels: Record<string, { en: string; ar: string }> = {
  neutral: { en: 'Retired', ar: 'متوقف' },
  planned: { en: 'Planned', ar: 'مخطط' },
  ready: { en: 'Ready', ar: 'جاهز' },
  running: { en: 'Running', ar: 'قيد التنفيذ' },
  attention: { en: 'Needs attention', ar: 'يحتاج انتباهًا' },
  blocked: { en: 'Blocked', ar: 'متوقف بسبب عائق' },
  retrying: { en: 'Retrying', ar: 'إعادة محاولة' },
  verifying: { en: 'Checking evidence', ar: 'فحص الأدلة' },
  rejected: { en: 'Not accepted', ar: 'غير مقبول' },
  accepted: { en: 'Accepted · measured', ar: 'مقبول · مُقاس' },
  complete: { en: 'Complete', ar: 'مكتمل' },
};

const attemptLabels: Record<AttemptView['outcome'], { en: string; ar: string }> = {
  running: { en: 'in progress', ar: 'قيد التنفيذ' },
  accepted: { en: 'accepted', ar: 'مقبولة' },
  rejected: { en: 'not accepted', ar: 'غير مقبولة' },
  'no-effect': { en: 'no measured effect', ar: 'بلا أثر مُقاس' },
  effect: { en: 'measured effect', ar: 'أثر مُقاس' },
  stopped: { en: 'stopped before acceptance', ar: 'توقفت قبل القبول' },
};

function abbreviated(value: string | null | undefined): string {
  if (!value) return '';
  return value.length > 7 ? value.slice(0, 7) : value;
}

// V5 motion gate: TEMM's explicit preference wins, then the media query.
// The CSS layer enforces the same law independently; this only stops the
// controller from emitting transitions nothing should play.
function motionAllowed(): boolean {
  if (document.documentElement.getAttribute('data-reduce-motion') === 'true') return false;
  return !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
}

// Presentation-level motion controller. It diffs the previous authoritative
// V4 snapshot against the current one to decide WHICH transition occurred;
// the V4 model remains the only authority on what is true. Historical states
// settle on initial load; a hidden tab absorbs its missed transitions on
// return instead of replaying them.
function useWorkspaceMotion(model: ProjectWorkspaceModel): { tasks: Record<string, TaskMotionPlan>; projectEvents: ProjectMotionEvent[] } {
  const previousRef = useRef<ProjectWorkspaceModel | null>(null);
  const modelRef = useRef(model);
  modelRef.current = model;
  const [, reconcileAfterAbsorb] = useReducer((count: number) => count + 1, 0);
  const cacheRef = useRef<{ model: ProjectWorkspaceModel; plan: { tasks: Record<string, TaskMotionPlan>; projectEvents: ProjectMotionEvent[] } } | null>(null);
  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState !== 'visible') return;
      // The hidden tab observed nothing, so nothing may replay: absorb the
      // missed diffs into the baseline and settle the current attributes.
      previousRef.current = modelRef.current;
      cacheRef.current = null;
      reconcileAfterAbsorb();
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  }, []);
  // Cached per model identity: unrelated re-renders (hover, disclosure) must
  // never interrupt or replay an arrival animation that is still playing.
  if (!cacheRef.current || cacheRef.current.model !== model) {
    cacheRef.current = { model, plan: deriveMotionPlan(previousRef.current, model, { allowMotion: motionAllowed() }) };
  }
  useEffect(() => { previousRef.current = model; }, [model]);
  return cacheRef.current.plan;
}

function formatDuration(durationMs: number | null, isArabic: boolean): string | null {
  if (durationMs === null) return null;
  if (durationMs < 1000) return `${durationMs} ms`;
  const seconds = Math.round(durationMs / 100) / 10;
  return isArabic ? `${seconds} ث` : `${seconds}s`;
}

function readableEnum(value: string): string {
  return value.replace(/[_-]+/g, ' ').replace(/^./, (letter) => letter.toUpperCase());
}

function readableRunTerm(value: string, kind: 'route' | 'executor', isArabic: boolean): string {
  if (!isArabic) return readableEnum(value);
  const routes: Record<string, string> = { balanced: 'متوازن', economy: 'اقتصادي', quality: 'عالي الجودة', fast: 'سريع', custom: 'مخصص' };
  const executors: Record<string, string> = { coding: 'برمجي', research: 'بحثي', reasoning: 'استدلالي', general: 'عام' };
  return (kind === 'route' ? routes : executors)[value] ?? readableEnum(value);
}

function attemptFacts(attempt: AttemptView, isArabic: boolean): string {
  const facts: string[] = [];
  if (attempt.effect === 'observed') {
    const count = attempt.effectPaths.length;
    facts.push(count > 0
      ? (isArabic ? `${count} مسارات متأثرة` : `${count} affected ${count === 1 ? 'path' : 'paths'}`)
      : (isArabic ? 'سُجّل أثر في مساحة العمل' : 'workspace effect recorded'));
  } else if (attempt.effect === 'none') {
    facts.push(isArabic ? 'سُجّل بلا أثر' : 'no effect recorded');
  } else {
    facts.push(isArabic ? 'لم يُبلّغ عن الأثر' : 'effect not reported');
  }
  if (attempt.gateState === 'accepted') facts.push(isArabic ? 'اجتاز القبول المُقاس' : 'measured acceptance passed');
  if (attempt.gateState === 'rejected') facts.push(isArabic ? 'رفضه القبول المُقاس' : 'measured acceptance rejected');
  if (attempt.gateState === 'evaluating') facts.push(isArabic ? 'قياس القبول غير حاسم' : 'acceptance measurement is unresolved');
  return facts.join(' · ');
}

function projectState(model: ProjectWorkspaceModel) {
  if (model.attention) return 'attention' as const;
  if (model.delivery.ready) return 'complete' as const;
  if (model.evidence.verified) return 'complete' as const;
  if (model.work.currentTask) return model.work.currentTask.state;
  if (model.work.tasks.length) return 'ready' as const;
  if (model.stage === 'clarify') return 'attention' as const;
  return 'planned' as const;
}

function stateSentence(model: ProjectWorkspaceModel, isArabic: boolean): string {
  const total = model.work.tasks.length;
  const current = model.work.currentTask;
  if (model.delivery.ready) {
    return isArabic
      ? `تم التحقق من ${model.work.completedCount} مهمة، وحزمة ${model.delivery.ready.name} جاهزة للتنزيل.`
      : `${model.work.completedCount} tasks verified. ${model.delivery.ready.name} is ready to download.`;
  }
  if (model.evidence.verified) {
    return isArabic
      ? `تم التحقق من ${model.work.completedCount} مهمة بالأدلة المقبولة. العمل جاهز للتجهيز.`
      : `${model.work.completedCount} tasks verified by accepted evidence. The work is ready to package.`;
  }
  if (model.attention) {
    return isArabic ? 'توقف مسار المشروع عند عائق يحتاج إجراءً.' : 'The project path has stopped at an actionable blocker.';
  }
  if (current) {
    const label = taskStateLabels[current.state]?.[isArabic ? 'ar' : 'en'] ?? current.state;
    if (model.work.activeCount > 1) {
      return isArabic
        ? `${model.work.completedCount} من ${total} مهام مقبولة. ${model.work.activeCount} مهام نشطة الآن.`
        : `${model.work.completedCount} of ${total} tasks accepted. ${model.work.activeCount} tasks are active now.`;
    }
    return isArabic
      ? `${model.work.completedCount} من ${total} مهام مقبولة. حالة العمل الحالي: ${label}.`
      : `${model.work.completedCount} of ${total} tasks accepted. Current work: ${current.title} · ${label}.`;
  }
  if (total) {
    return isArabic
      ? `الخطة تضم ${total} مهام مرتبة حسب الاعتماد، ولم يبدأ تنفيذ نشط بعد.`
      : `The plan contains ${total} dependency-ordered tasks. No task is actively running.`;
  }
  if (model.stage === 'clarify') return isArabic ? 'يحتاج TEMM إلى إجابات محددة قبل اعتماد الفهم.' : 'TEMM needs specific answers before the understanding can be approved.';
  if (model.understanding.blueprintStatus) return isArabic ? 'حوّل TEMM الهدف إلى مخطط ومتطلبات قابلة للمراجعة.' : 'TEMM translated the goal into a reviewable blueprint and requirements.';
  return isArabic ? 'سُجّل الهدف كما كتبه صاحبه، ولم يبدأ الفهم بعد.' : 'The owner’s goal is recorded verbatim. Understanding has not started.';
}

function AttemptStrip({ attempts, isArabic, motion }: { attempts: AttemptView[]; isArabic: boolean; motion: TaskMotionPlan }) {
  if (!attempts.length) return null;
  const visible = attempts.slice(-3);
  const earlier = attempts.slice(0, -3);
  const arrived = new Set(motion.arrivedAttemptIds);
  const settled = new Set(motion.settledAttemptIds);
  const renderAttempts = (items: AttemptView[]) => (
    <ol className="temm-v3-attempt-list">
      {items.map((attempt) => {
        const duration = formatDuration(attempt.durationMs, isArabic);
        return (
          <li
            key={attempt.id}
            data-outcome={attempt.outcome}
            data-effect={attempt.effect}
            data-gate={attempt.gateState ?? 'none'}
            data-active={attempt.active ? 'true' : 'false'}
            data-arrived={arrived.has(attempt.id) ? 'true' : undefined}
            data-settled={settled.has(attempt.id) ? 'true' : undefined}
          >
            <span className="temm-v3-attempt-index" dir="ltr">A{attempt.number}</span>
            <span className="temm-v3-attempt-geometry" aria-hidden="true"><i /><b /></span>
            <span className="temm-v3-attempt-result">
              {attemptLabels[attempt.outcome][isArabic ? 'ar' : 'en']}
              {duration && <code dir="ltr">{duration}</code>}
              <small>{attemptFacts(attempt, isArabic)}</small>
            </span>
          </li>
        );
      })}
    </ol>
  );
  return (
    <div className="temm-v3-attempts" aria-label={isArabic ? 'سجل المحاولات' : 'Attempt history'}>
      {renderAttempts(visible)}
      {earlier.length > 0 && (
        <details className="temm-v3-earlier-attempts">
          <summary>{isArabic ? `${earlier.length}+ محاولات أقدم` : `+${earlier.length} earlier attempts`}</summary>
          {renderAttempts(earlier)}
        </details>
      )}
    </div>
  );
}

function RunSummary({ task, isArabic }: { task: WorkTask; isArabic: boolean }) {
  if (!task.run) return null;
  const duration = formatDuration(task.run.durationMs, isArabic);
  const activeAttempt = task.attempts.find((attempt) => attempt.active);
  const route = [
    task.run.routingMode ? (isArabic ? `مسار ${readableRunTerm(task.run.routingMode, 'route', true)}` : `${readableRunTerm(task.run.routingMode, 'route', false)} route`) : null,
    task.run.executorType ? (isArabic ? `منفذ ${readableRunTerm(task.run.executorType, 'executor', true)}` : `${readableRunTerm(task.run.executorType, 'executor', false)} executor`) : null,
  ].filter(Boolean).join(' · ');
  return (
    <div className="temm-v4-run-summary" data-live={task.active ? 'true' : 'false'}>
      <strong>
        {task.active ? (isArabic ? 'تشغيل نشط' : 'Active run') : (isArabic ? 'تشغيل مسجل' : 'Recorded run')}
        {activeAttempt && (isArabic ? ` · المحاولة ${activeAttempt.number} من ${task.attempts.length}` : ` · attempt ${activeAttempt.number} of ${task.attempts.length}`)}
      </strong>
      {(route || duration) && (
        <span>
          {route}
          {route && duration ? ' · ' : ''}
          {duration && (task.run.durationMeasured
            ? (isArabic ? `${duration} مُقاس` : `${duration} measured`)
            : (isArabic ? `${duration} مسجل` : `${duration} recorded`))}
        </span>
      )}
    </div>
  );
}

function TechnicalReceipt({ task, isArabic }: { task: WorkTask; isArabic: boolean }) {
  if (!task.runId) return null;
  return (
    <details className="temm-v3-technical-receipt">
      <summary>{isArabic ? 'الإيصال التقني' : 'Technical receipt'}</summary>
      <div className="temm-v3-receipt-body" dir="ltr">
        <p>run <code>{task.runId}</code></p>
        {task.run && <p>status {task.run.status} · route {task.run.routingMode ?? 'unknown'}</p>}
        <p dir={isArabic ? 'rtl' : 'ltr'}>{isArabic ? 'نطاق السجل: التشغيل الحالي فقط' : 'history scope: current run only'}</p>
        {task.run && (task.run.agentId || task.run.modelId) && <p>agent {task.run.agentId ?? 'unknown'} · model {task.run.modelId ?? 'unknown'}</p>}
        {task.technical.attempts.map((attempt) => (
          <p key={attempt.id}>
            attempt {attempt.attempt_number} · {attempt.executor_type ?? 'executor'} · {attempt.model_id ?? 'model unknown'} · {attempt.status ?? 'unknown'}
          </p>
        ))}
        {(task.technical.artifacts?.length ?? 0) > 0 && (
          <ul>
            {task.technical.artifacts?.map((artifact, index) => (
              <li key={artifact.id ?? `${artifact.path}-${index}`}>{artifact.path ?? 'measured artifact'}</li>
            ))}
          </ul>
        )}
        {task.technical.output && <pre>{task.technical.output}</pre>}
      </div>
    </details>
  );
}

// V6 — the acceptance + evidence experience. One sheet per task: intent,
// measured effect, the acceptance contract criterion by criterion with its
// measured evidence, the spatial attempt history, and — behind exactly one
// control — the technical receipt. The micro spine in the header is drawn
// only when criteria were measured; an unmeasured proof stays text.
function AcceptanceSheet({ task, isArabic, onClose }: { task: WorkTask; isArabic: boolean; onClose: () => void }) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);
  const effect = task.sheet.effect;
  const effectLabel = {
    observed: isArabic ? 'الأثر المُقاس' : 'Measured effect',
    none: isArabic ? 'بلا أثر مُقاس' : 'No measured effect',
    unknown: isArabic ? 'لم يُبلّغ عن أثر' : 'Effect not reported',
  }[effect.kind];
  return (
    <div className="temm-v3-sheet-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="temm-v3-sheet temm-v6-acceptance" role="dialog" aria-modal="true" aria-labelledby="temm-v6-acceptance-title" dir={isArabic ? 'rtl' : 'ltr'} data-state={task.state}>
        <header className="temm-v6-acceptance-head">
          <div>
            <p className="temm-v3-kicker">{isArabic ? 'القبول والأدلة' : 'Acceptance and evidence'}</p>
            <h2 id="temm-v6-acceptance-title" dir="auto">{task.title}</h2>
          </div>
          <button type="button" className="temm-v3-utility" onClick={onClose} aria-label={isArabic ? 'إغلاق' : 'Close'}>✕</button>
        </header>
        <div className="temm-v6-acceptance-receipt">
          <StatusPrimitive state={task.state} label={taskStateLabels[task.state]?.[isArabic ? 'ar' : 'en'] ?? task.state} />
          {task.sheet.microSpine && (
            <MicroSpine
              state={task.sheet.microSpine.gateState}
              criteria={task.sheet.microSpine.criteria}
              direction={isArabic ? 'rtl' : 'ltr'}
              label={isArabic ? 'إيصال التحقق لهذه المهمة' : 'This task’s verification receipt'}
            />
          )}
        </div>
        {task.description && <p className="temm-v6-acceptance-intent" dir="auto">{task.description}</p>}

        <section className="temm-v6-acceptance-section" aria-labelledby="temm-v6-effect-title">
          <h3 id="temm-v6-effect-title">{effectLabel}</h3>
          {effect.kind === 'observed' && (
            <>
              <ul className="temm-v6-effect-paths">
                {effect.paths.map((path) => <li key={path}><code dir="ltr">{path}</code></li>)}
              </ul>
              {effect.sourceAttemptNumber !== null && (
                <p className="temm-v6-section-note">
                  {isArabic ? `قِيس على المحاولة ${effect.sourceAttemptNumber}.` : `Measured on attempt ${effect.sourceAttemptNumber}.`}
                </p>
              )}
            </>
          )}
          {effect.kind === 'none' && (
            <p className="temm-v6-section-note" dir="auto">
              {isArabic
                ? 'لم يسجّل التنفيذ أي أثر في مساحة العمل، لذا لا يمكن أن يصل إلى بوابة القبول.'
                : 'Execution recorded no workspace effect, so nothing could reach the acceptance gate.'}
            </p>
          )}
          {effect.kind === 'unknown' && (
            <p className="temm-v6-section-note" dir="auto">
              {isArabic ? 'لم يبلغ أي محاولة عن أثر مُقاس بعد.' : 'No attempt has reported a measured effect yet.'}
            </p>
          )}
          {task.sheet.artifacts.length > 0 && (
            <ul className="temm-v6-artifacts">
              {task.sheet.artifacts.map((artifact) => (
                <li key={artifact.path}>
                  <code dir="ltr">{artifact.path}</code>
                  {artifact.checksum && (
                    <button type="button" className="temm-v3-checksum" title={isArabic ? 'انسخ بصمة SHA-256 الكاملة' : 'Copy full SHA-256 checksum'} onClick={() => navigator.clipboard?.writeText(artifact.checksum ?? '')}>
                      <code dir="ltr">sha256 {abbreviated(artifact.checksum)}</code>
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="temm-v6-acceptance-section" aria-labelledby="temm-v6-gate-title">
          <h3 id="temm-v6-gate-title">{isArabic ? 'عقد القبول' : 'The acceptance contract'}</h3>
          {task.gateState ? (
            <>
              <AcceptanceGate
                state={task.gateState}
                criteria={task.gateCriteria.map((criterion) => criterion.state)}
                direction={isArabic ? 'rtl' : 'ltr'}
                label={isArabic ? 'بوابة القبول المُقاسة لهذه المهمة' : 'This task’s measured acceptance gate'}
                className="temm-v6-gate-full"
              />
              <ul className="temm-v6-criteria">
                {task.gateCriteria.map((criterion) => (
                  <li key={criterion.id} data-state={criterion.state}>
                    <span className="temm-v6-criterion-statement" dir="auto">{criterion.description}</span>
                    <strong>{isArabic
                      ? { pass: 'مُقبل', fail: 'مرفوض', testing: 'قيد القياس', pending: 'غير مُقاس' }[criterion.state]
                      : { pass: 'passed', fail: 'failed', testing: 'measuring', pending: 'unmeasured' }[criterion.state]}
                    </strong>
                    {criterion.evidence && <code dir="ltr" className="temm-v6-criterion-evidence">{criterion.evidence}</code>}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="temm-v6-section-note" dir="auto">
              {isArabic
                ? 'لم تُقَس أي شروط قبول لهذه المهمة بعد، فلا تُرسم بوابة.'
                : 'No acceptance criteria have been measured for this task yet, so no gate is drawn.'}
            </p>
          )}
        </section>

        <section className="temm-v6-acceptance-section" aria-labelledby="temm-v6-attempts-title">
          <h3 id="temm-v6-attempts-title">{isArabic ? 'سجل المحاولات' : 'Attempt history'}</h3>
          <AttemptStrip attempts={task.attempts} isArabic={isArabic} motion={emptyTaskMotionPlan()} />
          {!task.attempts.length && (
            <p className="temm-v6-section-note" dir="auto">
              {isArabic ? 'لا توجد محاولات مسجّلة ضمن التشغيل الحالي.' : 'No attempts are recorded within the current run.'}
            </p>
          )}
        </section>

        <TechnicalReceipt task={task} isArabic={isArabic} />
      </section>
    </div>
  );
}

function TaskCopy({ task, isArabic, traced, hasRelations, onTrace, motion, onOpenSheet }: {
  task: WorkTask;
  isArabic: boolean;
  traced: boolean;
  hasRelations: boolean;
  onTrace: () => void;
  motion: TaskMotionPlan;
  onOpenSheet: () => void;
}) {
  const stateLabel = taskStateLabels[task.state]?.[isArabic ? 'ar' : 'en'] ?? task.state;
  return (
    <div className="temm-v3-task-copy">
      <div className="temm-v3-task-heading">
        <h3 dir="auto">{task.title}</h3>
        <span data-state={task.state}>{stateLabel}</span>
      </div>
      {task.description && <p dir="auto">{task.description}</p>}
      {task.blockedReason && <p className="temm-v3-task-stop" data-stop-kind={task.stopKind ?? 'none'} dir="auto">{task.blockedReason}</p>}
      <RunSummary task={task} isArabic={isArabic} />
      {hasRelations && (
        <button type="button" className="temm-v4-trace" aria-pressed={traced} onClick={onTrace}>
          {traced
            ? (isArabic ? 'أوقف تتبع الاعتماد' : 'Clear dependency trace')
            : (isArabic ? 'تتبّع روابط المهمة' : 'Trace task links')}
        </button>
      )}
      <AttemptStrip attempts={task.attempts} isArabic={isArabic} motion={motion} />
      <button
        type="button"
        className="temm-v6-acceptance-trigger"
        data-state={task.state}
        onClick={onOpenSheet}
      >
        {task.gateState
          ? (isArabic ? 'اعرض القبول والأدلة' : 'View acceptance and evidence')
          : (isArabic ? 'اعرض تفاصيل المهمة' : 'View task details')}
      </button>
    </div>
  );
}

type TaskTraceState = 'none' | 'focus' | 'related' | 'dim';

function traceState(task: WorkTask, tracedTaskId: string | null, tasks: WorkTask[]): TaskTraceState {
  if (!tracedTaskId) return 'none';
  if (task.id === tracedTaskId) return 'focus';
  const traced = tasks.find((item) => item.id === tracedTaskId);
  if (!traced) return 'none';
  if (traced.dependencyIds.includes(task.id) || task.dependencyIds.includes(traced.id)) return 'related';
  return 'dim';
}

function hasTaskRelations(task: WorkTask, tasks: WorkTask[]): boolean {
  return task.dependencyIds.length > 0 || tasks.some((item) => item.dependencyIds.includes(task.id));
}

function LatticeTask({ task, model, trace, traced, motion, onHover, onLeave, onTrace, onOpenSheet }: {
  task: WorkTask;
  model: ProjectWorkspaceModel;
  trace: TaskTraceState;
  traced: boolean;
  motion: TaskMotionPlan;
  onHover: () => void;
  onLeave: () => void;
  onTrace: () => void;
  onOpenSheet: () => void;
}) {
  const style = { '--v3-depth': Math.min(task.depth, 5) } as CSSProperties;
  return (
    <article
      id={`temm-v3-task-${task.id}`}
      className="temm-v3-lattice-task"
      data-current={task.current ? 'true' : 'false'}
      data-active={task.active ? 'true' : 'false'}
      data-state={task.state}
      data-trace={trace}
      data-motion={motion.events.length ? motion.events.join(' ') : undefined}
      data-v3-task-review={task.id}
      style={style}
      onMouseEnter={onHover}
      onMouseLeave={onLeave}
    >
      <div className="temm-v3-dependency-rail" aria-hidden="true"><i /></div>
      <div className="temm-v3-branch">
        <ExecutionNode type="task" state={task.state} caption={task.title} className="temm-v3-task-node" />
        <ExecutionConnector
          treatment={task.connector}
          direction={model.direction}
          transit={motion.transit}
          decorative
          className="temm-v3-task-connector"
        />
        {task.gateState && (
          <AcceptanceGate
            state={task.gateState}
            criteria={task.gateCriteria.map((criterion) => criterion.state)}
            direction={model.direction}
            animate={motion.events.some((event) => event.startsWith('gate-'))}
            label={`${task.title}: measured acceptance`}
            className="temm-v3-task-gate"
          />
        )}
      </div>
      <TaskCopy
        task={task}
        isArabic={model.direction === 'rtl'}
        traced={traced}
        hasRelations={hasTaskRelations(task, model.work.tasks)}
        onTrace={onTrace}
        motion={motion}
        onOpenSheet={onOpenSheet}
      />
    </article>
  );
}

function TaskLedger({ model, tasks = model.work.tasks, tracedTaskId, motionPlans, onHover, onLeave, onTrace, onOpenSheet }: {
  model: ProjectWorkspaceModel;
  tasks?: WorkTask[];
  tracedTaskId: string | null;
  motionPlans: Record<string, TaskMotionPlan>;
  onHover: (taskId: string) => void;
  onLeave: () => void;
  onTrace: (taskId: string) => void;
  onOpenSheet: (taskId: string) => void;
}) {
  const isArabic = model.direction === 'rtl';
  const attentionTasks = tasks.filter((task) => task.state === 'rejected');
  const ordered = [...attentionTasks, ...tasks.filter((task) => task.state !== 'rejected')];
  return (
    <div className="temm-v3-task-ledger" data-scale={model.work.scale}>
      {attentionTasks.length > 0 && <p className="temm-v3-ledger-hoist">{isArabic ? 'يحتاج قرارك أولًا' : 'Needs your decision first'}</p>}
      {ordered.map((task) => {
        const motion = motionPlans[task.id] ?? emptyTaskMotionPlan();
        return (
          <article
            id={`temm-v3-ledger-${task.id}`}
            className="temm-v3-ledger-row"
            data-current={task.current ? 'true' : 'false'}
            data-active={task.active ? 'true' : 'false'}
            data-state={task.state}
            data-trace={traceState(task, tracedTaskId, model.work.tasks)}
            data-motion={motion.events.length ? motion.events.join(' ') : undefined}
            data-v3-task-review={task.id}
            key={task.id}
            onMouseEnter={() => onHover(task.id)}
            onMouseLeave={onLeave}
          >
            <div className="temm-v3-ledger-depth" aria-label={isArabic ? `عمق الاعتماد ${task.depth}` : `Dependency depth ${task.depth}`}>
              {Array.from({ length: Math.min(task.depth + 1, 4) }, (_, index) => <i key={index} />)}
            </div>
            <TaskCopy
              task={task}
              isArabic={isArabic}
              traced={tracedTaskId === task.id}
              hasRelations={hasTaskRelations(task, model.work.tasks)}
              onTrace={() => onTrace(task.id)}
              motion={motion}
              onOpenSheet={() => onOpenSheet(task.id)}
            />
            <ExecutionConnector
              treatment={task.connector}
              direction={model.direction}
              transit={motion.transit}
              decorative
              className="temm-v3-ledger-geometry"
            />
          </article>
        );
      })}
    </div>
  );
}

function WorkRegion({ model, motionPlans, converging, onOpenSheet }: {
  model: ProjectWorkspaceModel;
  motionPlans: Record<string, TaskMotionPlan>;
  converging: boolean;
  onOpenSheet: (taskId: string) => void;
}) {
  const isArabic = model.direction === 'rtl';
  const [hoveredTaskId, setHoveredTaskId] = useState<string | null>(null);
  const [latchedTaskId, setLatchedTaskId] = useState<string | null>(null);
  useEffect(() => {
    setHoveredTaskId(null);
    setLatchedTaskId(null);
  }, [model.project.id]);
  const tracedTaskId = hoveredTaskId ?? latchedTaskId;
  const toggleTrace = (taskId: string) => setLatchedTaskId((current) => current === taskId ? null : taskId);
  const revealTask = (taskId: string) => {
    setLatchedTaskId(taskId);
    window.setTimeout(() => {
      const target = [...document.querySelectorAll<HTMLElement>('[data-v3-task-review]')]
        .find((element) => element.dataset.v3TaskReview === taskId && element.offsetParent !== null);
      target?.scrollIntoView({ block: 'center' });
    }, 0);
  };
  const ledgerProps = {
    tracedTaskId,
    motionPlans,
    onHover: setHoveredTaskId,
    onLeave: () => setHoveredTaskId(null),
    onTrace: toggleTrace,
    onOpenSheet,
  };
  const activeIndex = model.work.activeCount > 0 ? (
    <nav className="temm-v4-active-index" aria-label={isArabic ? 'المهام النشطة الآن' : 'Tasks active now'}>
      <strong>{isArabic ? 'نشط الآن' : 'Active now'}</strong>
      <div>
        {model.work.activeTasks.map((task) => {
          const attempt = task.attempts.find((item) => item.active);
          return (
            <button type="button" key={task.id} onClick={() => revealTask(task.id)}>
              <span>{task.title}</span>
              <small>
                {taskStateLabels[task.state]?.[isArabic ? 'ar' : 'en'] ?? task.state}
                {attempt && (isArabic ? ` · المحاولة ${attempt.number}` : ` · attempt ${attempt.number}`)}
              </small>
            </button>
          );
        })}
      </div>
    </nav>
  ) : null;
  if (!model.work.tasks.length) {
    return <p className="temm-v3-absent">{isArabic ? 'لا توجد خطة مهام مجمّعة بعد.' : 'No compiled task plan exists yet.'}</p>;
  }
  if (model.evidence.verified && converging && model.work.scale === 'lattice') {
    // The convergence chain's transient lattice (freeze §15.2, steps 2–4):
    // gates resolve, evidence departs toward the spine, branches retire.
    // It exists only while the chain plays; the resting state is the
    // collapsed record below.
    return (
      <>
        {activeIndex}
        <div className="temm-v3-lattice-view" data-converging="true">
          {model.work.tasks.map((task) => (
            <LatticeTask
              key={task.id}
              task={task}
              model={model}
              trace={traceState(task, tracedTaskId, model.work.tasks)}
              traced={tracedTaskId === task.id}
              motion={motionPlans[task.id] ?? emptyTaskMotionPlan()}
              onHover={() => setHoveredTaskId(task.id)}
              onLeave={() => setHoveredTaskId(null)}
              onTrace={() => toggleTrace(task.id)}
              onOpenSheet={() => onOpenSheet(task.id)}
            />
          ))}
        </div>
      </>
    );
  }
  if (model.evidence.verified) {
    return (
      <>
        {activeIndex}
        <details className="temm-v3-retired-work">
          <summary>
            {isArabic
              ? `${model.work.completedCount} مهام مثبتة · اعرض سجل التنفيذ`
              : `${model.work.completedCount} tasks proven · Show execution history`}
          </summary>
          <TaskLedger model={model} {...ledgerProps} />
        </details>
      </>
    );
  }
  if (model.work.scale === 'grouped') {
    return (
      <>
        {activeIndex}
        <div className="temm-v3-grouped-work">
          {model.work.groups.map((group) => {
            const acceptedCount = group.tasks.filter((task) => task.accepted).length;
            const activeCount = group.tasks.filter((task) => task.active).length;
            return (
              <section key={group.id} data-current={group.current ? 'true' : 'false'} data-state={group.state}>
                <ExecutionConnector treatment={group.state === 'accepted' ? 'accepted' : group.state === 'blocked' || group.state === 'rejected' ? 'blocked' : group.current ? 'running' : 'planned'} direction={model.direction} decorative />
                <div>
                  <h3>{group.label}</h3>
                  <p>
                    {isArabic ? `${group.tasks.length} مهام` : `${group.tasks.length} tasks`}
                    {acceptedCount > 0 && (isArabic ? ` · ${acceptedCount} مقبولة` : ` · ${acceptedCount} accepted`)}
                    {activeCount > 0 && (isArabic ? ` · ${activeCount} نشطة` : ` · ${activeCount} active`)}
                    {' · '}{taskStateLabels[group.state]?.[isArabic ? 'ar' : 'en'] ?? group.state}
                  </p>
                </div>
                {group.current && <TaskLedger model={model} tasks={group.tasks} {...ledgerProps} />}
              </section>
            );
          })}
        </div>
      </>
    );
  }
  if (model.work.scale === 'ledger') return <>{activeIndex}<TaskLedger model={model} {...ledgerProps} /></>;
  return (
    <>
      {activeIndex}
      <div className="temm-v3-lattice-view">
        {model.work.tasks.map((task) => (
          <LatticeTask
            key={task.id}
            task={task}
            model={model}
            trace={traceState(task, tracedTaskId, model.work.tasks)}
            traced={tracedTaskId === task.id}
            motion={motionPlans[task.id] ?? emptyTaskMotionPlan()}
            onHover={() => setHoveredTaskId(task.id)}
            onLeave={() => setHoveredTaskId(null)}
            onTrace={() => toggleTrace(task.id)}
            onOpenSheet={() => onOpenSheet(task.id)}
          />
        ))}
      </div>
      <div className="temm-v3-mobile-ledger"><TaskLedger model={model} {...ledgerProps} /></div>
    </>
  );
}

function PrimaryAction({ model, location, suppressed, onAction }: {
  model: ProjectWorkspaceModel;
  location: 'outcome' | 'attention' | 'delivery';
  suppressed: boolean;
  onAction: (kind: WorkspaceActionKind) => void;
}) {
  const action = model.action;
  if (!action || suppressed) return null;
  const isAttention = Boolean(model.attention);
  const isDelivery = action.kind === 'download-deliverable' || action.kind === 'package-deliverable';
  if ((location === 'attention') !== isAttention) return null;
  if (!isAttention && (location === 'delivery') !== isDelivery) return null;
  if (action.kind === 'download-deliverable' && model.delivery.ready) {
    const href = model.delivery.ready.download_path
      || `/api/projects/${model.project.id}/deliverables/${model.delivery.ready.id}/download`;
    return <a data-v3-primary="true" className="temm-v3-primary" href={href} download>{actionLabels[action.kind][model.direction === 'rtl' ? 'ar' : 'en']}</a>;
  }
  return (
    <button data-v3-primary="true" type="button" className="temm-v3-primary" onClick={() => onAction(action.kind)}>
      {actionLabels[action.kind][model.direction === 'rtl' ? 'ar' : 'en']}
    </button>
  );
}

export function ProjectWorkspace({
  model,
  projects = [],
  answers = {},
  primarySuppressed = false,
  onAnswer,
  onAction,
  onNewProject,
  onSelectProject,
  initialSheetTaskId = null,
}: ProjectWorkspaceProps) {
  const isArabic = model.direction === 'rtl';
  const [sheetTaskId, setSheetTaskId] = useState<string | null>(initialSheetTaskId);
  const sheetProjectRef = useRef(model.project.id);
  const { tasks: motionPlans, projectEvents } = useWorkspaceMotion(model);
  const [converging, setConverging] = useState(false);
  const evidenceRef = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    // Reset only when the project actually changes — not on mount, which
    // would immediately close a sheet the owner (or a QA harness) opened.
    if (sheetProjectRef.current === model.project.id) return;
    sheetProjectRef.current = model.project.id;
    setSheetTaskId(null);
  }, [model.project.id]);
  useEffect(() => {
    if (!projectEvents.includes('project-verified')) return;
    // The convergence chain fires once per observed verification. It is a
    // transient state: when it ends, the resting composition — identical to
    // the chain's final frame — remains. Reduced motion never emits the
    // event, so the resting composition renders immediately, and an
    // already-verified project never replays (initial load settles).
    setConverging(true);
    const timer = window.setTimeout(() => setConverging(false), 2100);
    return () => window.clearTimeout(timer);
  }, [projectEvents]);

  const triggerAction = (kind: WorkspaceActionKind) => {
    if (kind === 'review-blocker') {
      // The blocker's evidence is the point: the acceptance sheet for the
      // stopped task is the review.
      const taskId = model.attention?.taskId ?? model.work.currentTask?.id ?? null;
      if (taskId) setSheetTaskId(taskId);
      return;
    }
    onAction(kind);
  };

  const state = projectState(model);
  const statusLabel = taskStateLabels[state]?.[isArabic ? 'ar' : 'en'] ?? state;
  const acceptedRequirementCount = model.understanding.approvedCount;
  const understandingMeta = model.understanding.settled
    ? (isArabic ? `${acceptedRequirementCount} متطلبات معتمدة` : `${acceptedRequirementCount} requirements approved`)
    : (isArabic ? `${model.understanding.requirements.length} متطلبات للمراجعة` : `${model.understanding.requirements.length} requirements to review`);

  return (
    <div className="temm-v3-workspace" dir={model.direction} data-attention={model.attention ? 'true' : 'false'} data-reviewing={sheetTaskId ? 'true' : 'false'} data-verified={model.evidence.verified ? 'true' : 'false'} data-convergence={converging ? 'true' : undefined}>
      <aside className="temm-v3-macro" aria-label={isArabic ? 'مراحل دورة المشروع' : 'Project lifecycle'}>
        {model.lifecycle.map((item, index) => (
          <div className="temm-v3-macro-station" data-status={item.status} key={item.station}>
            <span className="temm-v3-macro-node" aria-hidden="true" />
            <span>{lifecycleLabels[item.station][isArabic ? 'ar' : 'en']}</span>
            {index < model.lifecycle.length - 1 && <i className="temm-v3-macro-link" aria-hidden="true" />}
          </div>
        ))}
      </aside>

      <div className="temm-v3-story">
        <header className="temm-v3-outcome">
          <div className="temm-v3-project-tools">
            <label>
              <span>{isArabic ? 'المشروع' : 'Project'}</span>
              <select value={model.project.id} onChange={(event) => onSelectProject?.(event.target.value)} aria-label={isArabic ? 'اختر مشروعًا' : 'Choose project'}>
                {(projects.length ? projects : [model.project]).map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}
              </select>
            </label>
            {onNewProject && <button type="button" className="temm-v3-utility" onClick={onNewProject}>{isArabic ? 'مشروع جديد' : 'New project'}</button>}
          </div>
          <div className="temm-v3-goal-block">
            <p className="temm-v3-kicker">{isArabic ? 'النتيجة المطلوبة' : 'Outcome'}</p>
            <h1 dir="auto">{model.project.purpose}</h1>
            <p className="temm-v3-project-name" dir="auto">{model.project.name}</p>
          </div>
          <div className="temm-v3-now">
            <StatusPrimitive state={state} label={statusLabel} />
            <p>{stateSentence(model, isArabic)}</p>
          </div>
          <div className="temm-v3-dot-rail" aria-label={isArabic ? 'تقدم دورة المشروع' : 'Lifecycle progress'}>
            {model.lifecycle.map((item) => <i data-status={item.status} key={item.station} title={lifecycleLabels[item.station][isArabic ? 'ar' : 'en']} />)}
          </div>
          <div className="temm-v3-outcome-action"><PrimaryAction model={model} location="outcome" suppressed={primarySuppressed} onAction={triggerAction} /></div>
          {model.waiting && (
            <div className="temm-v3-waiting" role="status">
              <i aria-hidden="true" />
              <p>{isArabic ? actionWaitingArabic(model.waiting.reason) : model.waiting.reason}<small>{model.waiting.noEstimate && (isArabic ? 'لا يظهر تقدير زمني لأنه لم يُقَس.' : 'No estimate is shown because none has been measured.')}</small></p>
            </div>
          )}
        </header>

        {model.error && !model.attention && (
          <div className="temm-v3-error" role="alert">
            <strong>{isArabic ? 'تعذر إكمال إجراء المشروع' : 'Project action could not complete'}</strong>
            <p>{model.error}</p>
          </div>
        )}

        {model.attention && (
          <section className="temm-v3-attention" aria-labelledby="temm-v3-attention-title">
            <StatusPrimitive state="attention" label={isArabic ? 'توقف يحتاج إجراءً' : 'Actionable stop'} />
            <div>
              <h2 id="temm-v3-attention-title">{isArabic ? attentionTitleArabic(model.attention.kind) : model.attention.title}</h2>
              <p>{isArabic ? attentionDetailArabic(model.attention.kind) : model.attention.detail}</p>
              {model.attention.remainingCount > 0 && <small>{isArabic ? `${model.attention.remainingCount} عوائق أخرى محفوظة في السجل.` : `${model.attention.remainingCount} more blockers remain in the record.`}</small>}
            </div>
            <PrimaryAction model={model} location="attention" suppressed={primarySuppressed} onAction={triggerAction} />
            {(model.readiness?.blockers?.length ?? 0) > 0 && (
              <details className="temm-v3-attention-receipt">
                <summary>{isArabic ? 'تفاصيل الجاهزية التقنية' : 'Technical readiness details'}</summary>
                <ul dir="ltr">{model.readiness?.blockers?.map((blocker, index) => <li key={`${blocker.code}-${index}`}><code>{blocker.code}</code> {blocker.detail}</li>)}</ul>
              </details>
            )}
          </section>
        )}

        <details className="temm-v3-station temm-v3-understood" open={!model.understanding.settled}>
          <summary className="temm-v3-station-heading">
            <span>{isArabic ? 'ما فهمه TEMM' : 'Understood'}</span><i /><small>{understandingMeta}</small><b aria-hidden="true">{isArabic ? '‹' : '›'}</b>
          </summary>
          <div className="temm-v3-understood-body">
            {model.stage === 'clarify' && model.understanding.questions.length > 0 && (
              <section className="temm-v3-clarifications">
                <h2>{isArabic ? 'أسئلة لازمة لتعريف العمل' : 'Questions required to define the work'}</h2>
                {model.understanding.questions.map((question) => (
                  <label key={question.question_id}>
                    <span>{question.text}{question.required ? ' *' : ''}</span>
                    <textarea data-project-question={question.question_id} rows={2} value={answers[question.question_id] ?? ''} onChange={(event) => onAnswer?.(question.question_id, event.target.value)} />
                  </label>
                ))}
              </section>
            )}
            <div className="temm-v3-requirements">
              {model.understanding.requirements.map((requirement) => (
                <article key={requirement.id} data-status={requirement.status}>
                  <span className="temm-v3-requirement-node" aria-hidden="true" />
                  <div>
                    <h3 dir="auto">{requirement.title}</h3>
                    {requirement.description && <p dir="auto">{requirement.description}</p>}
                    {requirement.acceptance.length > 0 && <p className="temm-v3-contract" dir="auto">{requirement.acceptance[0]}</p>}
                    {requirement.acceptance.length > 1 && <details><summary>{isArabic ? `${requirement.acceptance.length} شروط قبول` : `${requirement.acceptance.length} acceptance criteria`}</summary><ul>{requirement.acceptance.map((criterion, index) => <li key={index}>{criterion}</li>)}</ul></details>}
                  </div>
                </article>
              ))}
              {!model.understanding.requirements.length && <p className="temm-v3-absent">{isArabic ? 'لم يُنشأ مخطط بعد.' : 'No blueprint has been created yet.'}</p>}
            </div>
          </div>
        </details>

        <section className="temm-v3-station temm-v3-work" aria-labelledby="temm-v3-work-title">
          <header className="temm-v3-station-heading">
            <span id="temm-v3-work-title">{isArabic ? 'العمل' : 'Work'}</span><i />
            <small>
              {isArabic ? `${model.work.completedCount} من ${model.work.tasks.length} مقبولة` : `${model.work.completedCount} of ${model.work.tasks.length} accepted`}
              {model.work.activeCount > 0 && (isArabic ? ` · ${model.work.activeCount} نشطة` : ` · ${model.work.activeCount} active`)}
            </small>
          </header>
          <WorkRegion model={model} motionPlans={motionPlans} converging={converging} onOpenSheet={setSheetTaskId} />
        </section>

        <details ref={evidenceRef} className="temm-v3-station temm-v3-evidence" open={model.evidence.verified && !model.delivery.ready}>
          <summary className="temm-v3-station-heading">
            <span>{isArabic ? 'الأدلة' : 'Evidence'}</span><i />
            <small>{model.evidence.items.length
              ? (isArabic ? `${model.evidence.acceptedCount} مهام مقبولة · ${model.evidence.measuredCriteriaCount} قياسات` : `${model.evidence.acceptedCount} accepted · ${model.evidence.measuredCriteriaCount} measured criteria`)
              : (isArabic ? 'لا توجد أدلة قبول مُقاسة بعد' : 'No measured acceptance evidence yet')}</small>
            <b aria-hidden="true">›</b>
          </summary>
          <div className="temm-v3-evidence-body">
            {model.evidence.verified && !model.delivery.ready && (
              <div className="temm-v3-verification-anchor">
                <ClosedCell state="closed" size={64} label={isArabic ? 'اكتمل التحقق بالأدلة المقبولة' : 'Verification established by accepted evidence'} />
                <div><h2>{isArabic ? 'اكتمل التحقق' : 'Verification established'}</h2><p>{isArabic ? 'أصبحت الأدلة المقبولة هي مرساة المشروع.' : 'Accepted measurements now anchor the project outcome.'}</p></div>
              </div>
            )}
            {model.evidence.items.map((item) => (
              <article key={item.taskId} data-accepted={item.accepted ? 'true' : 'false'}>
                <button type="button" className="temm-v6-evidence-open" onClick={() => setSheetTaskId(item.taskId)} aria-label={isArabic ? `اعرض أدلة ${item.title}` : `Show the evidence for ${item.title}`}>
                  {item.microSpine ? (
                    <MicroSpine
                      state={item.microSpine.gateState}
                      criteria={item.microSpine.criteria}
                      direction={model.direction}
                      label={`${item.title}: ${isArabic ? 'إيصال التحقق' : 'verification receipt'}`}
                    />
                  ) : (
                    <span className="temm-v4-evidence-note">{isArabic ? 'لا قياس للمحاولة النشطة' : 'Active attempt not measured'}</span>
                  )}
                </button>
                <div>
                  <h3>{item.title}</h3>
                  {item.effect.kind === 'observed' && (
                    <p className="temm-v6-evidence-effect">
                      {isArabic
                        ? `${item.effect.paths.length} مسارات متأثرة${item.effect.sourceAttemptNumber !== null ? ` · المحاولة ${item.effect.sourceAttemptNumber}` : ''}`
                        : `${item.effect.paths.length} affected ${item.effect.paths.length === 1 ? 'path' : 'paths'}${item.effect.sourceAttemptNumber !== null ? ` · attempt ${item.effect.sourceAttemptNumber}` : ''}`}
                    </p>
                  )}
                  {item.effect.kind === 'none' && (
                    <p className="temm-v6-evidence-effect">{isArabic ? 'سُجّل بلا أثر' : 'no effect recorded'}</p>
                  )}
                  {item.active && !item.microSpine && (
                    <p className="temm-v4-evidence-context">{isArabic ? 'القياس أدناه من أحدث محاولة قاست القبول، وليس حكمًا على المحاولة النشطة.' : 'The measurement below belongs to the latest attempt that reached acceptance, not the active attempt.'}</p>
                  )}
                  <ul>{item.criteria.map((criterion) => <li key={criterion.id} data-state={criterion.state}>{criterion.description}</li>)}</ul>
                </div>
              </article>
            ))}
          </div>
        </details>

        <section className="temm-v3-station temm-v3-delivery" aria-labelledby="temm-v3-delivery-title">
          <header className="temm-v3-station-heading"><span id="temm-v3-delivery-title">{isArabic ? 'التسليم' : 'Deliverable'}</span><i /></header>
          {model.evidence.verified ? (
            <div className="temm-v7-resting">
              <div className="temm-v7-seal">
                <ClosedCell
                  state="closed"
                  size={128}
                  animate={converging}
                  label={isArabic ? 'ختم التحقق: أُغلق بالأدلة المقبولة' : 'The verification seal: closed by accepted evidence'}
                />
                {model.delivery.ready && (
                  <EvidencePackage
                    size={40}
                    verifiedCount={Math.min(3, model.work.completedCount) as 0 | 1 | 2 | 3}
                    label={isArabic ? 'علامة التحقق على الحزمة' : 'Package verification mark'}
                  />
                )}
              </div>
              <div className="temm-v7-resting-copy">
                <h2 className="temm-v7-name" dir="auto">
                  {model.delivery.ready ? model.delivery.ready.name : (isArabic ? 'العمل موثّق' : 'The work is verified')}
                  {model.delivery.ready && <span className="temm-v7-version">{model.delivery.ready.version}</span>}
                </h2>
                <p className="temm-v7-receipt">
                  {model.delivery.ready?.checksum && (
                    <button type="button" className="temm-v3-checksum" title={isArabic ? 'انسخ بصمة SHA-256 الكاملة' : 'Copy full SHA-256 checksum'} onClick={() => navigator.clipboard?.writeText(model.delivery.ready?.checksum ?? '')}>
                      <code dir="ltr">sha256 {abbreviated(model.delivery.ready.checksum)}</code>
                    </button>
                  )}
                  <span>{isArabic
                    ? `${model.work.completedCount} مهام مثبتة بالأدلة`
                    : `${model.work.completedCount} tasks verified`}</span>
                </p>
                {!model.delivery.ready && (
                  <p className="temm-v7-packaging-note" dir="auto">
                    {isArabic
                      ? 'التحقق والتجهيز مطالبتان منفصلتان: التحقق أُقِس، ولا توجد حزمة بعد، لذلك لا يظهر تنزيل بعد.'
                      : 'Verification and packaging are separate claims: verification is measured; no package exists yet, so there is nothing to download.'}
                  </p>
                )}
                <PrimaryAction model={model} location="delivery" suppressed={primarySuppressed} onAction={triggerAction} />
                <button
                  type="button"
                  className="temm-v7-what-verified"
                  onClick={() => {
                    if (!evidenceRef.current) return;
                    evidenceRef.current.open = true;
                    evidenceRef.current.scrollIntoView({ block: 'start', behavior: motionAllowed() ? 'smooth' : 'auto' });
                  }}
                >
                  {isArabic ? 'ما الذي تم التحقق منه' : 'What was verified'}
                  <b aria-hidden="true">{isArabic ? '‹' : '›'}</b>
                </button>
              </div>
            </div>
          ) : (
            <p className="temm-v3-delivery-dormant">{isArabic ? 'يصبح التسليم متاحًا فقط بعد إثبات العمل بأدلة قبول مُقاسة.' : 'Available only after measured acceptance evidence establishes completion.'}</p>
          )}
          {model.delivery.blocked.length > 0 && (
            <details className="temm-v3-blocked-packages"><summary>{isArabic ? 'محاولات تجهيز سابقة' : 'Previous package records'}</summary><ul>{model.delivery.blocked.map((item) => <li key={item.id}>{item.name} {item.version} · {isArabic ? 'غير جاهزة' : 'not ready'}</li>)}</ul></details>
          )}
        </section>
      </div>

      {sheetTaskId && (() => {
        const sheetTask = model.work.tasks.find((task) => task.id === sheetTaskId)
          ?? null;
        return sheetTask
          ? <AcceptanceSheet task={sheetTask} isArabic={isArabic} onClose={() => setSheetTaskId(null)} />
          : null;
      })()}
    </div>
  );
}

function attentionTitleArabic(kind: AttentionState['kind']): string {
  if (kind === 'workspace') return 'مجلد المشروع مطلوب';
  if (kind === 'capability') return 'قدرة تنفيذ مطلوبة';
  if (kind === 'need') return 'قرار مشروع مطلوب';
  if (kind === 'rejected') return 'لم يُقبل العمل المقاس';
  return 'يحتاج تنفيذ المشروع إلى انتباه';
}

function attentionDetailArabic(kind: NonNullable<ProjectWorkspaceModel['attention']>['kind']): string {
  if (kind === 'workspace') return 'اربط مجلدًا معتمدًا ليبقى التنفيذ داخل حد أذونات واضح.';
  if (kind === 'capability') return 'لا توجد قدرة متصلة تستطيع متابعة العمل وفق دليل الجاهزية الحالي.';
  if (kind === 'need') return 'راجع القرار المطلوب قبل أن يتابع مسار المشروع.';
  if (kind === 'rejected') return 'وصل العمل إلى بوابة القبول، وقيس، ولم يحقق أحد الشروط.';
  return 'توقف المسار عند خطأ مسجل. راجع الدليل قبل المتابعة.';
}

function actionWaitingArabic(reason: string): string {
  if (reason.includes('blueprint')) return 'في انتظار بناء مخطط المشروع.';
  if (reason.includes('answers')) return 'في انتظار حفظ الإجابات المؤكدة.';
  if (reason.includes('contracts')) return 'في انتظار تسجيل العقود المعتمدة.';
  if (reason.includes('requirements')) return 'في انتظار تحويل المتطلبات المعتمدة إلى عمل.';
  if (reason.includes('executor')) return 'في انتظار أن يبلّغ المنفذ عن تغييرات مُقاسة.';
  if (reason.includes('packaged')) return 'في انتظار تجهيز الملفات الموثقة.';
  return 'في انتظار تسجيل حد مجلد المشروع.';
}
