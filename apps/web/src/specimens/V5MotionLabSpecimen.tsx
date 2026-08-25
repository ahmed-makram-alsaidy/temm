import { useEffect, useRef, useState } from 'react';
import { deriveProjectWorkspaceModel } from '../components/project-workspace-model';
import type { PlanTaskRecord, RunDetailRecord, WorkspaceModelInput } from '../components/project-workspace-model';
import { ProjectWorkspace } from '../components/ProjectWorkspace';
import './v5-lab.css';

export type V5ScenarioId =
  | 'ready-running'
  | 'transit'
  | 'no-effect'
  | 'rejected'
  | 'accepted'
  | 'retry-chain'
  | 'concurrent'
  | 'waiting'
  | 'blocked'
  | 'gate-rejected'
  | 'convergence';

interface V5Scenario {
  id: V5ScenarioId;
  label: string;
  rtl?: boolean;
  steps: WorkspaceModelInput[];
}

const acceptance = [{
  criterion_id: 'criterion-output',
  statement: 'The required workspace effect is measured and accepted.',
  evaluator: { type: 'changed_files_subset' },
}];

function task(overrides: Partial<PlanTaskRecord> & { id: string; state: PlanTaskRecord['state'] }): PlanTaskRecord {
  return {
    title: `Execution task ${overrides.id.slice(-1)}`,
    description: 'Dependency-ordered work with independently measured effect and acceptance.',
    dependency_ids: [],
    requirement_ids: ['requirement-1'],
    acceptance,
    ...overrides,
  };
}

function liveRunDetails(runId: string, attempts: RunDetailRecord['attempts'], status = 'running'): RunDetailRecord {
  return {
    run: {
      id: runId, status, routing_mode: 'balanced', selected_agent_id: 'coder',
      selected_model_id: 'model-route-a', current_attempt_id: attempts?.at(-1)?.id,
      duration_ms: status === 'running' ? 0 : 9000, latency_provenance: 'measured',
      started_at: '2026-08-24T10:00:00Z', completed_at: status === 'running' ? null : '2026-08-24T10:00:09Z',
    },
    attempts,
    artifacts: [],
  };
}

function input(overrides: Partial<WorkspaceModelInput>): WorkspaceModelInput {
  return {
    project: { id: 'project-v5-lab', name: 'Execution motion lab', purpose: 'Run, attempt, effect, acceptance, rejoin.' },
    stage: 'running',
    blueprint: { id: 'blueprint-v5', revision: 1, status: 'approved' },
    requirements: [{ id: 'requirement-1', title: 'Causal transit', status: 'approved', acceptance }],
    plan: { tasks: [], orchestrations: [{ state: 'running' }], needs: [] },
    completion: { ready: false, evidence: { tasks: [] } },
    deliverables: [],
    readiness: { ready: true, workspace: { id: 'workspace-v5', name: 'Lab workspace' }, blockers: [] },
    runDetails: {},
    isArabic: false,
    ...overrides,
  };
}

const acceptedEvidence = (taskId: string) => ({
  task_id: taskId,
  done: true,
  criteria: [{
    id: 'criterion-output',
    description: acceptance[0]!.statement,
    status: 'passed',
    source: 'measured',
    evidence: { path: 'src/output.ts' },
  }],
});

const attemptRunning = (id: string, number: number): NonNullable<RunDetailRecord['attempts']>[number] =>
  ({ id, attempt_number: number, status: 'running', executor_type: 'coding', agent_id: 'coder', model_id: 'model-route-a', started_at: '2026-08-24T10:00:00Z' });
const attemptNoEffect = (id: string, number: number): NonNullable<RunDetailRecord['attempts']>[number] =>
  ({ id, attempt_number: number, status: 'failed', executor_type: 'coding', model_id: 'model-route-a', receipt: { no_effect: true, duration_ms: 4200 } });
const attemptRejected = (id: string, number: number): NonNullable<RunDetailRecord['attempts']>[number] =>
  ({ id, attempt_number: number, status: 'failed', executor_type: 'coding', model_id: 'model-route-b', receipt: { workspace_diff: [{ path: 'src/output.ts' }], acceptance: [{ criterion_id: 'criterion-output', description: acceptance[0]!.statement, status: 'failed', evidence: { reason: 'contract mismatch' } }], duration_ms: 6800 } });
const attemptEvaluating = (id: string, number: number): NonNullable<RunDetailRecord['attempts']>[number] =>
  ({ id, attempt_number: number, status: 'completed', executor_type: 'coding', agent_id: 'coder', model_id: 'model-route-c', receipt: { workspace_diff: [{ path: 'src/output.ts' }], acceptance: [{ criterion_id: 'criterion-output', description: acceptance[0]!.statement, status: 'passed', evidence: { path: 'src/output.ts' } }, { criterion_id: 'criterion-tests', description: 'The workspace test suite passes.', status: 'pending' }], duration_ms: 8100 } });
const attemptAccepted = (id: string, number: number): NonNullable<RunDetailRecord['attempts']>[number] =>
  ({ id, attempt_number: number, status: 'completed', executor_type: 'coding', agent_id: 'coder', model_id: 'model-route-c', receipt: { workspace_diff: [{ path: 'src/output.ts' }], acceptance: [
    { criterion_id: 'criterion-output', description: acceptance[0]!.statement, status: 'passed', evidence: { path: 'src/output.ts' } },
    { criterion_id: 'criterion-tests', description: 'The workspace test suite passes.', status: 'passed', evidence: { suite: 'workspace', passed: 12 } },
  ], duration_ms: 8100 } });

const chainTasks = (state: PlanTaskRecord['state'], currentRunId: string | null): PlanTaskRecord[] => [
  task({ id: 'task-1', title: 'Set up the workspace', state: 'completed', current_run_id: 'run-settle' }),
  task({ id: 'task-2', title: 'Produce the measured output', state, current_run_id: currentRunId }),
  task({ id: 'task-3', title: 'Follow-on work', state: currentRunId ? 'planned' : 'ready', dependency_ids: ['task-2'] }),
];

const settledDetails = liveRunDetails('run-settle', [attemptAccepted('settle-attempt-1', 1)], 'completed');

// The §32 proof chain: ready -> active -> transit -> attempt -> no-effect ->
// rejection -> retry -> effect -> gate evaluation -> acceptance -> rejoin.
const retryChain: WorkspaceModelInput[] = [
  input({
    plan: { tasks: chainTasks('ready', null), orchestrations: [{ state: 'running' }], needs: [] },
    completion: { ready: false, evidence: { tasks: [acceptedEvidence('task-1')] } }, runDetails: { 'task-1': settledDetails },
  }),
  input({
    plan: { tasks: chainTasks('running', 'run-live'), orchestrations: [{ state: 'running' }], needs: [] },
    completion: { ready: false, evidence: { tasks: [acceptedEvidence('task-1')] } }, runDetails: { 'task-1': settledDetails, 'task-2': liveRunDetails('run-live', [attemptRunning('live-attempt-1', 1)]) },
  }),
  input({
    plan: { tasks: chainTasks('running', 'run-live'), orchestrations: [{ state: 'running' }], needs: [] },
    completion: { ready: false, evidence: { tasks: [acceptedEvidence('task-1')] } }, runDetails: {
      'task-1': settledDetails,
      'task-2': liveRunDetails('run-live', [attemptNoEffect('live-attempt-1', 1), attemptRunning('live-attempt-2', 2)]),
    },
  }),
  input({
    plan: { tasks: chainTasks('running', 'run-live'), orchestrations: [{ state: 'running' }], needs: [] },
    completion: { ready: false, evidence: { tasks: [acceptedEvidence('task-1')] } }, runDetails: {
      'task-1': settledDetails,
      'task-2': liveRunDetails('run-live', [attemptNoEffect('live-attempt-1', 1), attemptRejected('live-attempt-2', 2), attemptRunning('live-attempt-3', 3)]),
    },
  }),
  input({
    plan: { tasks: chainTasks('running', 'run-live'), orchestrations: [{ state: 'running' }], needs: [] },
    completion: { ready: false, evidence: { tasks: [acceptedEvidence('task-1')] } }, runDetails: {
      'task-1': settledDetails,
      'task-2': liveRunDetails('run-live', [attemptNoEffect('live-attempt-1', 1), attemptRejected('live-attempt-2', 2), attemptEvaluating('live-attempt-3', 3)], 'running'),
    },
  }),
  input({
    plan: { tasks: chainTasks('completed', 'run-live'), orchestrations: [{ state: 'running' }], needs: [] },
    completion: { ready: false, evidence: { tasks: [acceptedEvidence('task-1'), acceptedEvidence('task-2')] } },
    runDetails: {
      'task-1': settledDetails,
      'task-2': liveRunDetails('run-live', [attemptNoEffect('live-attempt-1', 1), attemptRejected('live-attempt-2', 2), attemptAccepted('live-attempt-3', 3)], 'completed'),
    },
  }),
];

const SCENARIOS: V5Scenario[] = [
  {
    id: 'ready-running',
    label: 'A · Ready to running',
    steps: [
      input({ plan: { tasks: chainTasks('ready', null), orchestrations: [{ state: 'running' }], needs: [] }, completion: { ready: false, evidence: { tasks: [acceptedEvidence('task-1')] } }, runDetails: { 'task-1': settledDetails } }),
      input({
        plan: { tasks: chainTasks('running', 'run-live'), orchestrations: [{ state: 'running' }], needs: [] },
        completion: { ready: false, evidence: { tasks: [acceptedEvidence('task-1')] } }, runDetails: { 'task-1': settledDetails, 'task-2': liveRunDetails('run-live', [attemptRunning('live-attempt-1', 1)]) },
      }),
    ],
  },
  {
    id: 'transit',
    label: 'B · Sustained transit',
    steps: [
      input({
        plan: { tasks: chainTasks('running', 'run-live'), orchestrations: [{ state: 'running' }], needs: [] },
        completion: { ready: false, evidence: { tasks: [acceptedEvidence('task-1')] } }, runDetails: { 'task-1': settledDetails, 'task-2': liveRunDetails('run-live', [attemptRunning('live-attempt-1', 1)]) },
      }),
      input({
        plan: { tasks: chainTasks('running', 'run-live'), orchestrations: [{ state: 'running' }], needs: [] },
        completion: { ready: false, evidence: { tasks: [acceptedEvidence('task-1')] } }, runDetails: { 'task-1': settledDetails, 'task-2': liveRunDetails('run-live', [attemptRunning('live-attempt-1', 1)]) },
      }),
    ],
  },
  {
    id: 'no-effect',
    label: 'C · No effect terminal',
    steps: [
      input({
        plan: { tasks: chainTasks('running', 'run-live'), orchestrations: [{ state: 'running' }], needs: [] },
        completion: { ready: false, evidence: { tasks: [acceptedEvidence('task-1')] } }, runDetails: { 'task-1': settledDetails, 'task-2': liveRunDetails('run-live', [attemptRunning('live-attempt-1', 1)]) },
      }),
      input({
        plan: { tasks: chainTasks('running', 'run-live'), orchestrations: [{ state: 'running' }], needs: [] },
        completion: { ready: false, evidence: { tasks: [acceptedEvidence('task-1')] } }, runDetails: { 'task-1': settledDetails, 'task-2': liveRunDetails('run-live', [attemptNoEffect('live-attempt-1', 1), attemptRunning('live-attempt-2', 2)]) },
      }),
    ],
  },
  {
    id: 'rejected',
    label: 'D · Rejected at the gate',
    steps: [
      input({
        plan: { tasks: chainTasks('running', 'run-live'), orchestrations: [{ state: 'running' }], needs: [] },
        completion: { ready: false, evidence: { tasks: [acceptedEvidence('task-1')] } }, runDetails: { 'task-1': settledDetails, 'task-2': liveRunDetails('run-live', [attemptRunning('live-attempt-1', 1)]) },
      }),
      input({
        plan: { tasks: chainTasks('running', 'run-live'), orchestrations: [{ state: 'running' }], needs: [] },
        completion: { ready: false, evidence: { tasks: [acceptedEvidence('task-1')] } }, runDetails: { 'task-1': settledDetails, 'task-2': liveRunDetails('run-live', [attemptRejected('live-attempt-1', 1), attemptRunning('live-attempt-2', 2)]) },
      }),
    ],
  },
  {
    id: 'accepted',
    label: 'E · Effect, gate, acceptance',
    steps: [
      input({
        plan: { tasks: chainTasks('running', 'run-live'), orchestrations: [{ state: 'running' }], needs: [] },
        completion: { ready: false, evidence: { tasks: [acceptedEvidence('task-1')] } }, runDetails: { 'task-1': settledDetails, 'task-2': liveRunDetails('run-live', [attemptRunning('live-attempt-1', 1)]) },
      }),
      input({
        plan: { tasks: chainTasks('running', 'run-live'), orchestrations: [{ state: 'running' }], needs: [] },
        completion: { ready: false, evidence: { tasks: [acceptedEvidence('task-1')] } }, runDetails: { 'task-1': settledDetails, 'task-2': liveRunDetails('run-live', [attemptEvaluating('live-attempt-1', 1)]) },
      }),
      input({
        plan: { tasks: chainTasks('completed', 'run-live'), orchestrations: [{ state: 'running' }], needs: [] },
        completion: { ready: false, evidence: { tasks: [acceptedEvidence('task-1'), acceptedEvidence('task-2')] } },
        runDetails: { 'task-1': settledDetails, 'task-2': liveRunDetails('run-live', [attemptAccepted('live-attempt-1', 1)], 'completed') },
      }),
    ],
  },
  { id: 'retry-chain', label: 'F · Full causal chain', steps: retryChain },
  {
    id: 'concurrent',
    label: 'G · Five active, three transits',
    steps: [
      input({
        plan: {
          tasks: Array.from({ length: 5 }, (_, index) => task({ id: `task-${index + 1}`, title: `Parallel task ${index + 1}`, state: 'ready' })),
          orchestrations: [{ state: 'running' }], needs: [],
        },
      }),
      input({
        plan: {
          tasks: Array.from({ length: 5 }, (_, index) => task({ id: `task-${index + 1}`, title: `Parallel task ${index + 1}`, state: 'running', current_run_id: `run-${index + 1}` })),
          orchestrations: [{ state: 'running' }], needs: [],
        },
        runDetails: Object.fromEntries(Array.from({ length: 5 }, (_, index) => [`task-${index + 1}`, liveRunDetails(`run-${index + 1}`, [attemptRunning(`run-${index + 1}-attempt-1`, 1)])])),
      }),
    ],
  },
  {
    id: 'waiting',
    label: 'J · Waiting stays still',
    steps: [
      input({ busy: 'start', plan: { tasks: chainTasks('running', 'run-live'), orchestrations: [{ state: 'running' }], needs: [] }, completion: { ready: false, evidence: { tasks: [acceptedEvidence('task-1')] } }, runDetails: { 'task-1': settledDetails, 'task-2': liveRunDetails('run-live', [attemptRunning('live-attempt-1', 1)]) } }),
      input({ busy: 'start', plan: { tasks: chainTasks('running', 'run-live'), orchestrations: [{ state: 'running' }], needs: [] }, completion: { ready: false, evidence: { tasks: [acceptedEvidence('task-1')] } }, runDetails: { 'task-1': settledDetails, 'task-2': liveRunDetails('run-live', [attemptRunning('live-attempt-1', 1)]) } }),
    ],
  },
  {
    id: 'blocked',
    label: 'K · Blocked stays still',
    steps: [
      input({
        stage: 'attention',
        plan: { tasks: chainTasks('failed', 'run-live'), orchestrations: [{ state: 'running' }], needs: [] },
        completion: { ready: false, evidence: { tasks: [acceptedEvidence('task-1')] } }, runDetails: { 'task-1': settledDetails, 'task-2': { run: { id: 'run-live', status: 'failed' }, attempts: [{ id: 'live-attempt-1', attempt_number: 1, status: 'failed', receipt: {} }] } },
      }),
      input({
        stage: 'attention',
        plan: { tasks: chainTasks('failed', 'run-live'), orchestrations: [{ state: 'running' }], needs: [] },
        completion: { ready: false, evidence: { tasks: [acceptedEvidence('task-1')] } }, runDetails: { 'task-1': settledDetails, 'task-2': { run: { id: 'run-live', status: 'failed' }, attempts: [{ id: 'live-attempt-1', attempt_number: 1, status: 'failed', receipt: {} }] } },
      }),
    ],
  },
  {
    id: 'gate-rejected',
    label: 'L · Rejected at rest',
    steps: [
      input({
        stage: 'attention',
        plan: { tasks: chainTasks('running', 'run-live'), orchestrations: [{ state: 'running' }], needs: [] },
        completion: { ready: false, evidence: { tasks: [acceptedEvidence('task-1')] } }, runDetails: { 'task-1': settledDetails, 'task-2': liveRunDetails('run-live', [attemptRunning('live-attempt-1', 1)]) },
      }),
      input({
        stage: 'attention',
        plan: { tasks: chainTasks('failed', 'run-live'), orchestrations: [{ state: 'running' }], needs: [] },
        completion: { ready: false, evidence: { tasks: [acceptedEvidence('task-1')] } },
        runDetails: {
          'task-1': settledDetails,
          'task-2': {
            ...liveRunDetails('run-live', [attemptRejected('live-attempt-1', 1)], 'failed'),
            artifacts: [{ id: 'artifact-task-2', attempt_id: 'live-attempt-1', path: 'src/output.ts', sha256: 'b4c5d6e7f8a9b0c1b4c5d6e7f8a9b0c1b4c5d6e7f8a9b0c1b4c5d6e7f8a9b0c1' }],
          },
        },
      }),
    ],
  },
  {
    id: 'convergence',
    label: 'M · Deliverable convergence',
    steps: [
      // The instant before reconciliation: every task is accepted, completion
      // is not yet evidence-based. No celebration is possible here.
      input({
        plan: {
          tasks: [
            task({ id: 'task-1', title: 'Set up the workspace', state: 'completed', current_run_id: 'run-settle' }),
            task({ id: 'task-2', title: 'Produce the measured output', state: 'completed', current_run_id: 'run-live' }),
            task({ id: 'task-3', title: 'Verify the follow-on work', state: 'completed', current_run_id: 'run-3', dependency_ids: ['task-2'] }),
          ],
          orchestrations: [{ state: 'complete' }], needs: [],
        },
        completion: { ready: false, evidence: { tasks: [acceptedEvidence('task-1')] } },
        runDetails: {
          'task-1': settledDetails,
          'task-2': liveRunDetails('run-live', [attemptAccepted('live-attempt-1', 1)], 'completed'),
          'task-3': liveRunDetails('run-3', [attemptAccepted('run-3-attempt-1', 1)], 'completed'),
        },
      }),
      // Reconciliation credits the requirements: completion becomes
      // evidence-based and the one-time convergence chain fires.
      input({
        stage: 'complete',
        plan: {
          tasks: [
            task({ id: 'task-1', title: 'Set up the workspace', state: 'completed', current_run_id: 'run-settle' }),
            task({ id: 'task-2', title: 'Produce the measured output', state: 'completed', current_run_id: 'run-live' }),
            task({ id: 'task-3', title: 'Verify the follow-on work', state: 'completed', current_run_id: 'run-3', dependency_ids: ['task-2'] }),
          ],
          orchestrations: [{ state: 'complete' }], needs: [],
        },
        completion: {
          ready: true,
          evidence: { tasks: [acceptedEvidence('task-1'), acceptedEvidence('task-2'), acceptedEvidence('task-3')] },
        },
        deliverables: [{ id: 'package-v7', name: 'convergence', version: '0.1.0', readiness: 'ready', checksum: 'c7d8e9f0a1b2c3d4c7d8e9f0a1b2c3d4c7d8e9f0a1b2c3d4c7d8e9f0a1b2c3d4', download_path: '/download' }],
        runDetails: {
          'task-1': settledDetails,
          'task-2': liveRunDetails('run-live', [attemptAccepted('live-attempt-1', 1)], 'completed'),
          'task-3': liveRunDetails('run-3', [attemptAccepted('run-3-attempt-1', 1)], 'completed'),
        },
      }),
    ],
  },
];

const STEP_INTERVAL_MS = 900;

interface V5MotionLabProps {
  scenario: V5Scenario;
  targetStep: number;
  grey: boolean;
  reduced: boolean;
  rtl: boolean;
  sheetTaskId?: string | null;
}

export function V5MotionLab({ scenario, targetStep, grey, reduced, rtl, sheetTaskId = null }: V5MotionLabProps) {
  const [step, setStep] = useState(0);
  const [run, setRun] = useState(0);
  const timer = useRef<number | null>(null);
  useEffect(() => {
    setStep(0);
    setRun((current) => current + 1);
  }, [scenario, targetStep, reduced, rtl]);
  useEffect(() => {
    if (reduced) {
      // Reduced motion never stages a journey: settle directly into the final
      // authoritative geometry.
      setStep(targetStep);
      return;
    }
    if (step >= targetStep) return;
    timer.current = window.setTimeout(() => setStep((current) => Math.min(current + 1, targetStep)), STEP_INTERVAL_MS);
    return () => { if (timer.current) window.clearTimeout(timer.current); };
  }, [step, targetStep, reduced, run]);
  useEffect(() => {
    if (reduced) document.documentElement.dataset.reduceMotion = 'true';
    else delete document.documentElement.dataset.reduceMotion;
    return () => { delete document.documentElement.dataset.reduceMotion; };
  }, [reduced]);
  // Direction is a property of the model, not of the page: the same override
  // that flips the document dir must reach deriveProjectWorkspaceModel so the
  // causal geometry itself resolves right-to-left.
  const model = deriveProjectWorkspaceModel({
    ...scenario.steps[Math.min(step, scenario.steps.length - 1)]!,
    isArabic: rtl,
  });
  const last = Math.min(step, scenario.steps.length - 1);
  return (
    <main className="temm-v5-lab" data-specimen-theme="dark" data-v5-scenario={scenario.id} data-v5-step={last} style={grey ? { filter: 'grayscale(1)' } : undefined}>
      <nav className="temm-v5-lab-rail" aria-label="Motion lab controls">
        <div className="temm-v5-lab-scenarios">
          {SCENARIOS.map((item) => (
            <a key={item.id} href={`?scenario=${item.id}&step=${item.steps.length - 1}&play=1`} data-active={item.id === scenario.id ? 'true' : undefined} onClick={(event) => {
              event.preventDefault();
              window.history.replaceState(null, '', `?scenario=${item.id}&step=${item.steps.length - 1}&play=1`);
              window.dispatchEvent(new PopStateEvent('popstate'));
            }}>{item.label}</a>
          ))}
        </div>
        <div className="temm-v5-lab-controls">
          <button type="button" onClick={() => setStep((current) => Math.min(current + 1, scenario.steps.length - 1))} disabled={step >= scenario.steps.length - 1}>Step</button>
          <button type="button" onClick={() => { setStep(0); setRun((current) => current + 1); }}>Replay</button>
          <output data-v5-step-label dir="ltr">{last + 1} / {scenario.steps.length}</output>
        </div>
      </nav>
      <div className="temm-v5-lab-stage" key={`${scenario.id}-${run}-${reduced ? 'reduced' : 'motion'}`}>
        <ProjectWorkspace model={model} projects={[model.project]} onAction={() => undefined} initialSheetTaskId={sheetTaskId} />
      </div>
    </main>
  );
}

export { SCENARIOS };
