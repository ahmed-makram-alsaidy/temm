import type {
  ConnectorTreatment,
  CriterionState,
  Direction,
  ExecutionState,
  GateState,
} from './visual-primitives';

export const TASK_SCALE_THRESHOLDS = {
  latticeMax: 24,
  groupedMax: 80,
} as const;

export type ProjectStage =
  | 'goal'
  | 'clarify'
  | 'blueprint'
  | 'approval'
  | 'ready'
  | 'running'
  | 'attention'
  | 'verifying'
  | 'complete';

export type LifecycleStation =
  | 'goal'
  | 'blueprint'
  | 'requirements'
  | 'execution'
  | 'evidence'
  | 'deliverable';

export type LifecycleStatus = 'complete' | 'current' | 'future' | 'blocked' | 'verified';
export type TaskScale = 'lattice' | 'grouped' | 'ledger';
export type WorkspaceActionKind =
  | 'understand-goal'
  | 'save-clarifications'
  | 'approve-blueprint'
  | 'approve-requirements'
  | 'compile-plan'
  | 'connect-workspace'
  | 'open-tools'
  | 'start-execution'
  | 'continue-execution'
  | 'review-blocker'
  | 'package-deliverable'
  | 'download-deliverable';

export interface ProjectRecord {
  id: string;
  name: string;
  purpose: string;
  slug?: string;
}

export interface BlueprintQuestion {
  question_id: string;
  text: string;
  required?: boolean;
}

export interface AcceptanceContract {
  criterion_id?: string;
  statement?: string;
  description?: string;
  evaluator?: Record<string, unknown>;
}

export interface BlueprintRequirement {
  proposal_id?: string;
  title: string;
  description?: string;
  acceptance?: AcceptanceContract[];
}

export interface BlueprintRecord {
  id: string;
  revision: number;
  status: string;
  content?: {
    goal?: string;
    questions?: BlueprintQuestion[];
    requirements?: BlueprintRequirement[];
  };
}

export interface RequirementRecord {
  id: string;
  title: string;
  description?: string;
  status: string;
  acceptance?: AcceptanceContract[];
}

export interface PlanTaskRecord {
  id: string;
  title: string;
  description?: string;
  state: string;
  dependency_ids?: string[];
  requirement_ids?: string[];
  acceptance?: AcceptanceContract[];
  current_run_id?: string | null;
}

export interface PlanRecord {
  tasks?: PlanTaskRecord[];
  orchestrations?: Array<{ state?: string }>;
  needs?: Array<{
    id?: string;
    title?: string;
    description?: string;
    need_type?: string;
    impact?: string;
    state?: string;
  }>;
}

export interface AttemptRecord {
  id: string;
  attempt_number: number;
  status?: string;
  outcome?: string | null;
  error_code?: string | null;
  executor_type?: string;
  started_at?: string | null;
  completed_at?: string | null;
  agent_id?: string | null;
  model_id?: string | null;
  provider_instance_id?: string | null;
  receipt?: {
    acceptance?: Array<{
      criterion_id?: string;
      description?: string;
      status?: string;
      evidence?: unknown;
    }>;
    no_effect?: boolean;
    workspace_diff?: Array<{ path?: string }>;
    duration_ms?: number;
    [key: string]: unknown;
  };
}

export interface RunRecord {
  id: string;
  task_type?: string;
  selected_model_id?: string | null;
  selected_agent_id?: string | null;
  current_attempt_id?: string | null;
  routing_mode?: string;
  status?: string;
  status_reason?: string | null;
  duration_ms?: number;
  latency_provenance?: string;
  route_explanation?: string;
  fallback_chain?: string[];
  created_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface RunDetailRecord {
  run?: RunRecord;
  attempts?: AttemptRecord[];
  artifacts?: Array<{ id?: string; attempt_id?: string | null; path?: string; sha256?: string | null }>;
  output?: Array<{ content?: string }>;
  latency?: {
    latency?: { duration_ms?: number };
    provenance?: { duration_ms?: string };
  };
}

export interface CompletionCriterion {
  id?: string;
  description?: string;
  status?: string;
  source?: string;
  evidence?: unknown;
  waiver?: unknown;
}

export interface CompletionTaskEvidence {
  task_id: string;
  done?: boolean;
  task_state?: string;
  criteria?: CompletionCriterion[];
  blockers?: string[];
}

export interface CompletionRecord {
  ready?: boolean;
  statement?: string;
  blockers?: Record<string, unknown[]>;
  evidence?: {
    requirements?: number;
    tasks?: CompletionTaskEvidence[];
    assets?: unknown[];
  };
}

export interface ReadinessRecord {
  ready?: boolean;
  workspace?: { id?: string; name?: string } | null;
  blockers?: Array<{ code?: string; title?: string; detail?: string }>;
  required_capabilities?: string[];
  [key: string]: unknown;
}

export interface DeliverableRecord {
  id: string;
  name: string;
  version: string;
  readiness: string;
  checksum?: string;
  download_path?: string;
  relative_path?: string;
  created_at?: string;
}

export interface WorkspaceModelInput {
  project: ProjectRecord;
  stage: ProjectStage;
  blueprint: BlueprintRecord | null;
  requirements: RequirementRecord[];
  plan: PlanRecord | null;
  completion: CompletionRecord | null;
  deliverables: DeliverableRecord[];
  readiness: ReadinessRecord | null;
  runDetails: Record<string, RunDetailRecord>;
  busy?: string;
  error?: string;
  isArabic?: boolean;
}

export interface CriterionView {
  id: string;
  description: string;
  state: CriterionState;
  measured: boolean;
  evidence: string | null;
}

export type AttemptOutcome = 'running' | 'accepted' | 'rejected' | 'no-effect' | 'effect' | 'stopped';
export type AttemptEffect = 'observed' | 'none' | 'unknown';
export type TaskStopKind = 'dependency' | 'executor' | 'acceptance' | null;

export interface AttemptView {
  id: string;
  number: number;
  outcome: AttemptOutcome;
  effect: AttemptEffect;
  effectPaths: string[];
  gateState: GateState | null;
  criteria: CriterionView[];
  active: boolean;
  durationMs: number | null;
  technicalLabel: string;
}

// The task's measured effect, taken from the latest attempt that carries an
// authoritative effect fact. `unknown` means no attempt reported either a
// workspace diff or the no-effect receipt; nothing may be inferred.
export interface TaskEffectView {
  kind: AttemptEffect;
  paths: string[];
  sourceAttemptNumber: number | null;
}

export interface TaskArtifactView {
  path: string;
  checksum: string | null;
}

// The verification receipt at reading size (freeze §3.3). Present only when
// measured criteria exist — a gate is never drawn speculatively.
export interface MicroSpineView {
  gateState: GateState;
  criteria: CriterionState[];
}

export interface TaskSheetView {
  effect: TaskEffectView;
  artifacts: TaskArtifactView[];
  microSpine: MicroSpineView | null;
}

export interface RunView {
  id: string;
  status: string;
  routingMode: string | null;
  executorType: string | null;
  agentId: string | null;
  modelId: string | null;
  currentAttemptId: string | null;
  startedAt: string | null;
  completedAt: string | null;
  durationMs: number | null;
  durationMeasured: boolean;
  historyScope: 'current-run-only';
}

export interface TaskExecutionPresentation {
  state: ExecutionState;
  connector: ConnectorTreatment;
  gateState: GateState | null;
  gateCriteria: CriterionView[];
  criteria: CriterionView[];
  attempts: AttemptView[];
  active: boolean;
  accepted: boolean;
  stopKind: TaskStopKind;
  waitingOn: string[];
  blockedReason: string | null;
  runId: string | null;
  run: RunView | null;
  sheet: TaskSheetView;
  technical: WorkTask['technical'];
}

export interface WorkTask {
  id: string;
  title: string;
  description: string;
  rawState: string;
  state: ExecutionState;
  connector: ConnectorTreatment;
  gateState: GateState | null;
  gateCriteria: CriterionView[];
  criteria: CriterionView[];
  attempts: AttemptView[];
  dependencyIds: string[];
  dependencyTitles: string[];
  requirementIds: string[];
  groupLabel: string;
  depth: number;
  current: boolean;
  active: boolean;
  accepted: boolean;
  stopKind: TaskStopKind;
  waitingOn: string[];
  blockedReason: string | null;
  runId: string | null;
  run: RunView | null;
  sheet: TaskSheetView;
  technical: {
    attempts: AttemptRecord[];
    artifacts: RunDetailRecord['artifacts'];
    output: string;
  };
}

export interface WorkGroup {
  id: string;
  label: string;
  tasks: WorkTask[];
  state: ExecutionState;
  current: boolean;
}

export interface AttentionState {
  kind: 'workspace' | 'capability' | 'need' | 'rejected' | 'error';
  title: string;
  detail: string;
  action: WorkspaceActionKind | null;
  taskId?: string;
  remainingCount: number;
}

export interface WorkspaceAction {
  kind: WorkspaceActionKind;
}

export interface EvidenceItem {
  taskId: string;
  title: string;
  accepted: boolean;
  active: boolean;
  gateState: GateState | null;
  gateCriteria: CriterionView[];
  criteria: CriterionView[];
  microSpine: MicroSpineView | null;
  effect: TaskEffectView;
}

export interface ProjectWorkspaceModel {
  project: ProjectRecord;
  stage: ProjectStage;
  direction: Direction;
  currentStation: LifecycleStation;
  lifecycle: Array<{ station: LifecycleStation; status: LifecycleStatus }>;
  understanding: {
    settled: boolean;
    blueprintStatus: string | null;
    questions: BlueprintQuestion[];
    requirements: Array<{ id: string; title: string; description: string; status: string; acceptance: string[] }>;
    approvedCount: number;
  };
  work: {
    scale: TaskScale;
    tasks: WorkTask[];
    groups: WorkGroup[];
    currentTask: WorkTask | null;
    activeTasks: WorkTask[];
    activeCount: number;
    completedCount: number;
    blockedCount: number;
  };
  attention: AttentionState | null;
  action: WorkspaceAction | null;
  waiting: { reason: string; noEstimate: boolean } | null;
  evidence: {
    items: EvidenceItem[];
    acceptedCount: number;
    measuredCriteriaCount: number;
    verified: boolean;
  };
  delivery: {
    verifiedWork: boolean;
    ready: DeliverableRecord | null;
    blocked: DeliverableRecord[];
    canPackage: boolean;
  };
  readiness: ReadinessRecord | null;
  error: string | null;
}

export function directionFor(isArabic: boolean): Direction {
  return isArabic ? 'rtl' : 'ltr';
}

export function selectTaskScale(taskCount: number): TaskScale {
  if (taskCount <= TASK_SCALE_THRESHOLDS.latticeMax) return 'lattice';
  if (taskCount <= TASK_SCALE_THRESHOLDS.groupedMax) return 'grouped';
  return 'ledger';
}

function hasValue(value: unknown): boolean {
  if (Array.isArray(value)) return value.length > 0;
  if (value && typeof value === 'object') return Object.keys(value).length > 0;
  return value !== null && value !== undefined && value !== '';
}

function criterionState(status: string | undefined): CriterionState {
  if (status === 'passed' || status === 'waived' || status === 'pass') return 'pass';
  if (status === 'failed' || status === 'fail' || status === 'unsatisfied') return 'fail';
  if (status === 'testing' || status === 'evaluating') return 'testing';
  return 'pending';
}

// A short human summary of one measured criterion's evidence. Only what the
// payload actually carries may surface: a path stays a path, a reason stays a
// reason, and anything unrecognised stays "measured" — never invented detail.
function evidenceSummary(evidence: unknown): string | null {
  if (evidence === null || evidence === undefined) return null;
  if (typeof evidence === 'string') return evidence.trim() ? evidence.trim() : null;
  if (typeof evidence === 'number' || typeof evidence === 'boolean') return `measured: ${String(evidence)}`;
  if (Array.isArray(evidence)) return evidence.length ? `measured: ${evidence.length} recorded` : null;
  if (typeof evidence === 'object') {
    const record = evidence as Record<string, unknown>;
    const parts: string[] = [];
    for (const key of ['path', 'reason', 'suite', 'passed', 'failed', 'observed', 'exit_code']) {
      const value = record[key];
      if (value === undefined || value === null || value === '') continue;
      parts.push(`${key.replace(/_/g, ' ')} ${String(value)}`);
    }
    if (parts.length) return parts.join(' · ');
    if (Object.keys(record).length) return 'measured';
  }
  return null;
}

function criterionIsMeasured(criterion: CompletionCriterion): boolean {
  return criterion.source === 'measured'
    || criterion.source === 'recorded'
    || hasValue(criterion.evidence)
    || (criterion.status === 'waived' && hasValue(criterion.waiver));
}

function attemptCriteria(task: PlanTaskRecord, attempt: AttemptRecord | undefined): CriterionView[] {
  const measured = attempt?.receipt?.acceptance ?? [];
  const contracts = new Map((task.acceptance ?? []).map((item, index) => [
    item.criterion_id ?? `criterion-${index + 1}`,
    item.statement ?? item.description ?? `Acceptance criterion ${index + 1}`,
  ]));
  return measured.map((item, index) => ({
    id: item.criterion_id ?? `attempt-criterion-${index + 1}`,
    description: item.description ?? contracts.get(item.criterion_id ?? '') ?? `Acceptance criterion ${index + 1}`,
    state: criterionState(item.status),
    measured: true,
    evidence: evidenceSummary(item.evidence),
  }));
}

function normalizedCriteria(task: PlanTaskRecord, assessment: CompletionTaskEvidence | undefined, attempts: AttemptRecord[]): CriterionView[] {
  const assessed = (assessment?.criteria ?? [])
    .filter(criterionIsMeasured)
    .map((criterion, index) => ({
      id: criterion.id ?? `criterion-${index + 1}`,
      description: criterion.description ?? `Acceptance criterion ${index + 1}`,
      state: criterionState(criterion.status),
      measured: true,
      evidence: evidenceSummary(criterion.evidence),
    }));
  if (assessed.length) return assessed;
  for (let index = attempts.length - 1; index >= 0; index -= 1) {
    const criteria = attemptCriteria(task, attempts[index]);
    if (criteria.length) return criteria;
  }
  return [];
}

// The task's measured effect comes from the latest attempt that reported an
// authoritative effect fact — a non-empty workspace diff or the no-effect
// receipt. Anything else stays unknown.
function taskEffect(attempts: AttemptRecord[]): TaskEffectView {
  for (let index = attempts.length - 1; index >= 0; index -= 1) {
    const attempt = attempts[index]!;
    const diff = attempt.receipt?.workspace_diff ?? [];
    if (diff.length > 0) {
      return {
        kind: 'observed',
        paths: diff.map((item) => item.path).filter((path): path is string => Boolean(path)),
        sourceAttemptNumber: attempt.attempt_number,
      };
    }
    if (attempt.receipt?.no_effect === true) {
      return { kind: 'none', paths: [], sourceAttemptNumber: attempt.attempt_number };
    }
  }
  return { kind: 'unknown', paths: [], sourceAttemptNumber: null };
}

function taskArtifacts(details: RunDetailRecord): TaskArtifactView[] {
  return (details.artifacts ?? [])
    .filter((artifact) => Boolean(artifact.path))
    .map((artifact) => ({ path: artifact.path!, checksum: artifact.sha256 ?? null }));
}

function attemptEffect(attempt: AttemptRecord): AttemptEffect {
  if ((attempt.receipt?.workspace_diff ?? []).length > 0) return 'observed';
  if (attempt.receipt?.no_effect === true) return 'none';
  return 'unknown';
}

function attemptGateState(criteria: CriterionView[], attempt: AttemptRecord): GateState | null {
  if (!criteria.length) return null;
  if (criteria.some((criterion) => criterion.state === 'fail')) return 'rejected';
  const measurements = attempt.receipt?.acceptance ?? [];
  if (criteria.every((criterion) => criterion.state === 'pass' && criterion.measured)
    && measurements.every((measurement) => hasValue(measurement.evidence))) return 'accepted';
  return 'evaluating';
}

function attemptOutcome(attempt: AttemptRecord, effect: AttemptEffect, gateState: GateState | null): AttemptOutcome {
  if (attempt.status === 'running' || attempt.status === 'starting') return 'running';
  if (gateState === 'rejected') return 'rejected';
  if (gateState === 'accepted') return 'accepted';
  if (effect === 'none') return 'no-effect';
  if (effect === 'observed') return 'effect';
  return 'stopped';
}

function elapsedMilliseconds(startedAt: string | null | undefined, completedAt: string | null | undefined): number | null {
  if (!startedAt || !completedAt) return null;
  const started = Date.parse(startedAt);
  const completed = Date.parse(completedAt);
  if (!Number.isFinite(started) || !Number.isFinite(completed) || completed < started) return null;
  return completed - started;
}

function deriveRunView(task: PlanTaskRecord, details: RunDetailRecord, attempts: AttemptRecord[]): RunView | null {
  const runId = task.current_run_id ?? details.run?.id ?? null;
  if (!runId) return null;
  const run = details.run;
  const selectedAttempt = attempts.find((attempt) => attempt.id === run?.current_attempt_id)
    ?? attempts.at(-1);
  const recordedDuration = typeof run?.duration_ms === 'number' && run.duration_ms > 0
    ? run.duration_ms
    : null;
  const timestampDuration = elapsedMilliseconds(run?.started_at, run?.completed_at);
  const aggregateDuration = typeof details.latency?.latency?.duration_ms === 'number'
    && details.latency.latency.duration_ms > 0
    ? details.latency.latency.duration_ms
    : null;
  const durationMs = recordedDuration
    ?? aggregateDuration
    ?? timestampDuration;
  const durationMeasured = recordedDuration !== null
    ? run?.latency_provenance === 'measured'
    : aggregateDuration !== null
      ? details.latency?.provenance?.duration_ms === 'measured'
      : false;
  return {
    id: runId,
    status: run?.status ?? selectedAttempt?.status ?? 'unknown',
    routingMode: run?.routing_mode ?? null,
    executorType: selectedAttempt?.executor_type ?? null,
    agentId: selectedAttempt?.agent_id ?? run?.selected_agent_id ?? null,
    modelId: selectedAttempt?.model_id ?? run?.selected_model_id ?? null,
    currentAttemptId: run?.current_attempt_id ?? selectedAttempt?.id ?? null,
    startedAt: run?.started_at ?? selectedAttempt?.started_at ?? null,
    completedAt: run?.completed_at ?? selectedAttempt?.completed_at ?? null,
    durationMs,
    durationMeasured,
    historyScope: 'current-run-only',
  };
}

function orderTasks(tasks: PlanTaskRecord[]): PlanTaskRecord[] {
  const byId = new Map(tasks.map((task) => [task.id, task]));
  const visiting = new Set<string>();
  const visited = new Set<string>();
  const ordered: PlanTaskRecord[] = [];
  const visit = (task: PlanTaskRecord) => {
    if (visited.has(task.id)) return;
    if (visiting.has(task.id)) return;
    visiting.add(task.id);
    for (const dependencyId of task.dependency_ids ?? []) {
      const dependency = byId.get(dependencyId);
      if (dependency) visit(dependency);
    }
    visiting.delete(task.id);
    visited.add(task.id);
    ordered.push(task);
  };
  tasks.forEach(visit);
  return ordered;
}

function taskDepth(taskId: string, byId: Map<string, PlanTaskRecord>, memo: Map<string, number>, active = new Set<string>()): number {
  const cached = memo.get(taskId);
  if (cached !== undefined) return cached;
  if (active.has(taskId)) return 0;
  active.add(taskId);
  const task = byId.get(taskId);
  const dependencies = (task?.dependency_ids ?? []).filter((id) => byId.has(id));
  const depth = dependencies.length
    ? Math.max(...dependencies.map((id) => taskDepth(id, byId, memo, new Set(active)))) + 1
    : 0;
  memo.set(taskId, depth);
  return depth;
}

function visualState(
  task: PlanTaskRecord,
  gateCriteria: CriterionView[],
  active: boolean,
  attemptCount: number,
  accepted: boolean,
  dependenciesComplete: boolean,
  orchestrationState: string,
): ExecutionState {
  if (accepted) return 'accepted';
  if (active) return attemptCount > 1 ? 'retrying' : 'running';
  if (gateCriteria.some((criterion) => criterion.state === 'fail')) return 'rejected';
  if (task.state === 'completed') return 'verifying';
  if (task.state === 'blocked' || task.state === 'failed') return 'blocked';
  if (task.state === 'ready') return 'ready';
  if (task.state === 'cancelled') return 'neutral';
  if (task.state === 'planned' && dependenciesComplete && ['approved', 'running'].includes(orchestrationState)) return 'ready';
  return 'planned';
}

function connectorFor(state: ExecutionState): ConnectorTreatment {
  if (state === 'accepted' || state === 'complete') return 'accepted';
  if (state === 'rejected') return 'rejected';
  if (state === 'blocked' || state === 'attention') return 'blocked';
  if (state === 'retrying') return 'retry';
  if (state === 'running' || state === 'verifying') return 'running';
  if (state === 'ready') return 'ready';
  return 'planned';
}

function groupState(tasks: WorkTask[]): ExecutionState {
  const priority: ExecutionState[] = ['rejected', 'running', 'retrying', 'verifying', 'blocked', 'ready', 'planned', 'accepted', 'neutral'];
  return priority.find((state) => tasks.some((task) => task.state === state)) ?? 'neutral';
}

export function deriveTaskExecutionPresentation({
  task,
  details,
  assessment,
  dependenciesComplete,
  dependencyTitles,
  orchestrationState,
}: {
  task: PlanTaskRecord;
  details: RunDetailRecord;
  assessment?: CompletionTaskEvidence;
  dependenciesComplete: boolean;
  dependencyTitles: string[];
  orchestrationState: string;
}): TaskExecutionPresentation {
  const rawAttempts = [...(details.attempts ?? [])].sort((a, b) => a.attempt_number - b.attempt_number);
  const run = deriveRunView(task, details, rawAttempts);
  const activeAttempt = rawAttempts.find((attempt) =>
    attempt.id === details.run?.current_attempt_id
    && ['running', 'starting'].includes(attempt.status ?? ''),
  ) ?? [...rawAttempts].reverse().find((attempt) => ['running', 'starting'].includes(attempt.status ?? ''));
  const active = task.state === 'running'
    || ['created', 'running', 'cancellation_requested'].includes(details.run?.status ?? '')
    || Boolean(activeAttempt);
  const criteria = normalizedCriteria(task, assessment, rawAttempts);
  const accepted = assessment?.done === true
    && criteria.length > 0
    && criteria.every((criterion) => criterion.state === 'pass');
  let latestMeasuredCriteria: CriterionView[] = [];
  for (let index = rawAttempts.length - 1; index >= 0; index -= 1) {
    latestMeasuredCriteria = attemptCriteria(task, rawAttempts[index]);
    if (latestMeasuredCriteria.length) break;
  }
  // A live retry owns only its own gate. The previous attempt remains in history,
  // but its rejection must not be painted as the active attempt's verdict.
  const gateCriteria = activeAttempt
    ? attemptCriteria(task, activeAttempt)
    : latestMeasuredCriteria.length ? latestMeasuredCriteria : criteria;
  const state = visualState(task, gateCriteria, active, rawAttempts.length, accepted, dependenciesComplete, orchestrationState);
  const waitingOn = dependenciesComplete ? [] : dependencyTitles;
  const stopKind: TaskStopKind = state === 'rejected'
    ? 'acceptance'
    : state === 'blocked'
      ? task.state === 'failed' ? 'executor' : waitingOn.length ? 'dependency' : 'executor'
      : state === 'planned' && waitingOn.length ? 'dependency' : null;
  const blockedReason = stopKind === 'acceptance'
    ? `Unmet acceptance criterion: ${gateCriteria.find((criterion) => criterion.state === 'fail')?.description ?? 'Measured acceptance was not established.'}`
    : stopKind === 'dependency'
      ? `Waiting for ${waitingOn.join(', ')}.`
      : stopKind === 'executor'
        ? 'Execution stopped before acceptance was established.'
        : null;
  const attempts = rawAttempts.map<AttemptView>((attempt) => {
    const attemptCriteriaView = attemptCriteria(task, attempt);
    const effect = attemptEffect(attempt);
    const gateState = attemptGateState(attemptCriteriaView, attempt);
    return {
      id: attempt.id,
      number: attempt.attempt_number,
      outcome: attemptOutcome(attempt, effect, gateState),
      effect,
      effectPaths: (attempt.receipt?.workspace_diff ?? []).map((item) => item.path).filter((path): path is string => Boolean(path)),
      gateState,
      criteria: attemptCriteriaView,
      active: attempt.id === activeAttempt?.id,
      durationMs: typeof attempt.receipt?.duration_ms === 'number'
        ? attempt.receipt.duration_ms
        : elapsedMilliseconds(attempt.started_at, attempt.completed_at),
      technicalLabel: [attempt.executor_type, attempt.model_id, attempt.status].filter(Boolean).join(' · '),
    };
  });
  return {
    state,
    connector: connectorFor(state),
    gateState: gateCriteria.length
      ? accepted ? 'accepted' : gateCriteria.some((criterion) => criterion.state === 'fail') ? 'rejected' : 'evaluating'
      : null,
    gateCriteria,
    criteria,
    attempts,
    active,
    accepted,
    stopKind,
    waitingOn,
    blockedReason,
    runId: task.current_run_id ?? details.run?.id ?? null,
    run,
    sheet: {
      effect: taskEffect(rawAttempts),
      artifacts: taskArtifacts(details),
      // The micro spine exists only where criteria were measured. An unmeasured
      // proof is a claim, and claims stay text (freeze §3.3).
      microSpine: gateCriteria.length
        ? {
          gateState: accepted ? 'accepted' : gateCriteria.some((criterion) => criterion.state === 'fail') ? 'rejected' : 'evaluating',
          criteria: gateCriteria.map((criterion) => criterion.state),
        }
        : null,
    },
    technical: {
      attempts: rawAttempts,
      artifacts: details.artifacts ?? [],
      output: (details.output ?? []).map((item) => item.content ?? '').join(''),
    },
  };
}

function buildWork(input: WorkspaceModelInput, requirementNames: Map<string, string>) {
  const sourceTasks = orderTasks(input.plan?.tasks ?? []);
  const byId = new Map(sourceTasks.map((task) => [task.id, task]));
  const depthMemo = new Map<string, number>();
  const evidenceByTask = new Map((input.completion?.evidence?.tasks ?? []).map((item) => [item.task_id, item]));
  const orchestrationState = input.plan?.orchestrations?.[0]?.state ?? '';

  const tasks = sourceTasks.map<WorkTask>((task) => {
    const details = input.runDetails[task.id] ?? {};
    const assessment = evidenceByTask.get(task.id);
    const dependencyIds = task.dependency_ids ?? [];
    const dependenciesComplete = dependencyIds.every((id) => byId.get(id)?.state === 'completed');
    const dependencyTitles = dependencyIds.map((id) => byId.get(id)?.title).filter((title): title is string => Boolean(title));
    const requirementIds = task.requirement_ids ?? [];
    const groupLabel = requirementNames.get(requirementIds[0] ?? '') ?? 'Supporting work';
    const execution = deriveTaskExecutionPresentation({
      task,
      details,
      assessment,
      dependenciesComplete,
      dependencyTitles,
      orchestrationState,
    });
    return {
      id: task.id,
      title: task.title,
      description: task.description ?? '',
      rawState: task.state,
      ...execution,
      dependencyIds,
      dependencyTitles,
      requirementIds,
      groupLabel,
      depth: taskDepth(task.id, byId, depthMemo),
      current: false,
    };
  });

  const activeTasks = tasks.filter((task) => task.active);
  const currentTask = activeTasks[0]
    ?? tasks.find((task) => task.state === 'verifying')
    ?? tasks.find((task) => task.state === 'rejected')
    ?? tasks.find((task) => task.state === 'ready')
    ?? tasks.find((task) => task.state === 'blocked')
    ?? null;
  if (currentTask) currentTask.current = true;

  const groupsByLabel = new Map<string, WorkTask[]>();
  tasks.forEach((task) => groupsByLabel.set(task.groupLabel, [...(groupsByLabel.get(task.groupLabel) ?? []), task]));
  const groups = [...groupsByLabel.entries()].map<WorkGroup>(([label, groupTasks], index) => ({
    id: `group-${index + 1}`,
    label,
    tasks: groupTasks,
    state: groupState(groupTasks),
    current: groupTasks.some((task) => task.current || task.active),
  }));

  return {
    scale: selectTaskScale(tasks.length),
    tasks,
    groups,
    currentTask,
    activeTasks,
    activeCount: activeTasks.length,
    completedCount: tasks.filter((task) => task.accepted).length,
    blockedCount: tasks.filter((task) => ['blocked', 'rejected'].includes(task.state)).length,
  };
}

function readinessAction(blockerCode: string): WorkspaceActionKind {
  if (blockerCode === 'workspace_required' || blockerCode === 'permission_incompatible') return 'connect-workspace';
  return 'open-tools';
}

function buildAttention(input: WorkspaceModelInput, tasks: WorkTask[]): AttentionState | null {
  if (input.completion?.ready) return null;
  const readinessBlockers = input.readiness?.blockers ?? [];
  if (tasks.length && readinessBlockers.length) {
    const blocker = readinessBlockers[0];
    return {
      kind: blocker.code === 'workspace_required' || blocker.code === 'permission_incompatible' ? 'workspace' : 'capability',
      title: blocker.title ?? 'Execution cannot continue',
      detail: blocker.detail ?? 'Project execution needs setup before work can continue.',
      action: readinessAction(blocker.code ?? ''),
      remainingCount: Math.max(0, readinessBlockers.length - 1),
    };
  }

  const humanNeeds = (input.plan?.needs ?? []).filter((need) =>
    need.impact === 'blocking'
    && ['open', 'in_progress'].includes(need.state ?? '')
    && ['approval', 'information'].includes(need.need_type ?? ''),
  );
  if (humanNeeds.length) {
    const need = humanNeeds[0];
    return {
      kind: 'need',
      title: need.title ?? 'A project decision is required',
      detail: need.description ?? 'Review the blocking project decision before work continues.',
      action: null,
      remainingCount: humanNeeds.length - 1,
    };
  }

  const rejected = tasks.find((task) => task.state === 'rejected');
  const blocked = tasks.find((task) => task.state === 'blocked');
  const live = tasks.some((task) => ['running', 'retrying', 'verifying'].includes(task.state));
  const stoppedTask = rejected ?? blocked;
  if (stoppedTask && !live) {
    return {
      kind: 'rejected',
      title: stoppedTask.title,
      detail: stoppedTask.blockedReason ?? 'Execution stopped before acceptance was established.',
      action: 'review-blocker',
      taskId: stoppedTask.id,
      remainingCount: Math.max(0, tasks.filter((task) => ['blocked', 'rejected'].includes(task.state)).length - 1),
    };
  }

  if (input.error && input.stage === 'attention') {
    return {
      kind: 'error',
      title: 'Project execution needs attention',
      detail: input.error,
      action: null,
      remainingCount: 0,
    };
  }
  return null;
}

function buildWaiting(input: WorkspaceModelInput, tasks: WorkTask[]) {
  if (input.busy === 'blueprint') return { reason: 'Waiting for TEMM to build the project blueprint.', noEstimate: true };
  if (input.busy === 'clarify') return { reason: 'Waiting for the confirmed answers to be stored.', noEstimate: true };
  if (input.busy === 'approve') return { reason: 'Waiting for the approved contracts to be recorded.', noEstimate: true };
  if (input.busy === 'plan') return { reason: 'Waiting for the approved requirements to compile into work.', noEstimate: true };
  if (input.busy === 'start') return { reason: 'Waiting for the executor to report measured work.', noEstimate: true };
  if (input.busy === 'package') return { reason: 'Waiting for the verified files to be packaged.', noEstimate: true };
  if (input.busy === 'workspace') return { reason: 'Waiting for the project folder boundary to be recorded.', noEstimate: true };
  if (tasks.some((task) => ['running', 'retrying'].includes(task.state))) {
    return { reason: 'Waiting for the executor to report measured changes.', noEstimate: true };
  }
  return null;
}

function currentStation(input: WorkspaceModelInput, readyDeliverable: DeliverableRecord | null): LifecycleStation {
  if (input.completion?.ready) return 'deliverable';
  if (input.stage === 'verifying') return 'evidence';
  if ((input.plan?.tasks ?? []).length || ['ready', 'running', 'attention'].includes(input.stage)) return 'execution';
  if (input.blueprint?.status === 'approved') return 'requirements';
  if (input.blueprint) return 'blueprint';
  if (readyDeliverable) return 'deliverable';
  return 'goal';
}

function buildAction(input: WorkspaceModelInput, attention: AttentionState | null, work: ProjectWorkspaceModel['work'], readyDeliverable: DeliverableRecord | null): WorkspaceAction | null {
  if (input.busy) return null;
  if (attention) return attention.action ? { kind: attention.action } : null;
  if (input.completion?.ready) return { kind: readyDeliverable ? 'download-deliverable' : 'package-deliverable' };
  if (!input.blueprint) return { kind: 'understand-goal' };
  if (input.stage === 'clarify') return { kind: 'save-clarifications' };
  if (input.blueprint.status !== 'approved') return { kind: 'approve-blueprint' };
  if (input.requirements.some((requirement) => requirement.status === 'draft')) return { kind: 'approve-requirements' };
  if (!work.tasks.length) return { kind: 'compile-plan' };
  if (work.currentTask && ['running', 'retrying'].includes(work.currentTask.state)) return null;
  const orchestration = input.plan?.orchestrations?.[0]?.state;
  if (orchestration === 'running') return { kind: 'continue-execution' };
  return { kind: 'start-execution' };
}

export function deriveProjectWorkspaceModel(input: WorkspaceModelInput): ProjectWorkspaceModel {
  const requirementNames = new Map(input.requirements.map((requirement) => [requirement.id, requirement.title]));
  const work = buildWork(input, requirementNames);
  const readyDeliverable = input.completion?.ready
    ? input.deliverables.find((deliverable) => deliverable.readiness === 'ready') ?? null
    : null;
  const attention = buildAttention(input, work.tasks);
  const station = currentStation(input, readyDeliverable);
  const order: LifecycleStation[] = ['goal', 'blueprint', 'requirements', 'execution', 'evidence', 'deliverable'];
  const currentIndex = order.indexOf(station);
  const lifecycle = order.map((item, index) => ({
    station: item,
    status: (
      item === 'deliverable' && readyDeliverable ? 'verified'
        : index < currentIndex ? 'complete'
          : index === currentIndex && attention && item === 'execution' ? 'blocked'
            : index === currentIndex ? 'current'
              : 'future'
    ) as LifecycleStatus,
  }));
  const blueprintRequirements = input.blueprint?.content?.requirements ?? [];
  const requirementSource = input.requirements.length
    ? input.requirements.map((requirement) => ({
      id: requirement.id,
      title: requirement.title,
      description: requirement.description ?? '',
      status: requirement.status,
      acceptance: (requirement.acceptance ?? []).map((item, index) => item.statement ?? item.description ?? `Acceptance criterion ${index + 1}`),
    }))
    : blueprintRequirements.map((requirement, index) => ({
      id: requirement.proposal_id ?? `proposal-${index + 1}`,
      title: requirement.title,
      description: requirement.description ?? '',
      status: input.blueprint?.status ?? 'proposed',
      acceptance: (requirement.acceptance ?? []).map((item, criterionIndex) => item.statement ?? item.description ?? `Acceptance criterion ${criterionIndex + 1}`),
    }));
  const understandingSettled = input.blueprint?.status === 'approved'
    && input.requirements.length > 0
    && input.requirements.every((requirement) => ['approved', 'completed', 'waived'].includes(requirement.status));
  const evidenceItems = work.tasks
    .filter((task) => task.criteria.length > 0)
    .map<EvidenceItem>((task) => ({
      taskId: task.id,
      title: task.title,
      accepted: task.accepted,
      active: task.active,
      gateState: task.gateState,
      gateCriteria: task.gateCriteria,
      criteria: task.criteria,
      microSpine: task.sheet.microSpine,
      effect: task.sheet.effect,
    }));

  return {
    project: input.project,
    stage: input.stage,
    direction: directionFor(Boolean(input.isArabic)),
    currentStation: station,
    lifecycle,
    understanding: {
      settled: understandingSettled,
      blueprintStatus: input.blueprint?.status ?? null,
      questions: input.blueprint?.content?.questions ?? [],
      requirements: requirementSource,
      approvedCount: input.requirements.filter((requirement) => ['approved', 'completed', 'waived'].includes(requirement.status)).length,
    },
    work,
    attention,
    action: buildAction(input, attention, work, readyDeliverable),
    waiting: buildWaiting(input, work.tasks),
    evidence: {
      items: evidenceItems,
      acceptedCount: evidenceItems.filter((item) => item.accepted).length,
      measuredCriteriaCount: evidenceItems.reduce((count, item) => count + item.criteria.length, 0),
      verified: input.completion?.ready === true,
    },
    delivery: {
      verifiedWork: input.completion?.ready === true,
      ready: readyDeliverable,
      blocked: input.deliverables.filter((deliverable) => deliverable.readiness !== 'ready'),
      canPackage: input.completion?.ready === true && !readyDeliverable,
    },
    readiness: input.readiness,
    error: input.error?.trim() || null,
  };
}
