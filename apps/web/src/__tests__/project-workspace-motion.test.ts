import { deriveMotionPlan, settleMotionPlan, TRANSIT_CONCURRENCY_LIMIT } from '../components/project-workspace-motion.ts';
import { deriveProjectWorkspaceModel } from '../components/project-workspace-model.ts';
import type { WorkspaceModelInput } from '../components/project-workspace-model.ts';

let passed = 0;

function test(name: string, run: () => void): void {
  run();
  passed += 1;
  console.log(`ok ${passed} - ${name}`);
}

function equal<T>(actual: T, expected: T, message = 'values differ'): void {
  if (actual !== expected) throw new Error(`${message}: expected ${String(expected)}, received ${String(actual)}`);
}

function truthy(value: unknown, message = 'expected truthy'): asserts value {
  if (!value) throw new Error(message);
}

function base(overrides: Partial<WorkspaceModelInput> = {}): WorkspaceModelInput {
  return {
    project: { id: 'project-v5', name: 'Execution motion', purpose: 'Animate only measured truth.' },
    stage: 'running',
    blueprint: { id: 'blueprint-v5', revision: 1, status: 'approved' },
    requirements: [{ id: 'requirement-v5', title: 'Causal transit', status: 'approved' }],
    plan: { tasks: [], orchestrations: [{ state: 'running' }] },
    completion: { ready: false, evidence: { tasks: [] } },
    deliverables: [],
    readiness: { ready: true, blockers: [] },
    runDetails: {},
    ...overrides,
  };
}

function model(overrides: Partial<WorkspaceModelInput> = {}) {
  return deriveProjectWorkspaceModel(base(overrides));
}

const liveRun = {
  run: { id: 'run-1', status: 'running', current_attempt_id: 'attempt-1' },
  attempts: [{ id: 'attempt-1', attempt_number: 1, status: 'running' }],
};

test('initial historical load settles without replaying events', () => {
  const plan = deriveMotionPlan(null, model({
    plan: { tasks: [{ id: 'task-1', title: 'Done', state: 'completed', current_run_id: 'run-1' }], orchestrations: [{ state: 'running' }] },
    runDetails: { 'task-1': { attempts: [{ id: 'attempt-1', attempt_number: 1, status: 'completed', receipt: { workspace_diff: [{ path: 'src/a.ts' }], acceptance: [{ criterion_id: 'criterion-1', status: 'passed', evidence: { observed: true } }] } }] } },
    completion: { ready: false, evidence: { tasks: [{ task_id: 'task-1', done: true, criteria: [{ id: 'criterion-1', status: 'passed', source: 'measured', evidence: { observed: true } }] }] } },
  }));
  truthy(plan.live, 'active truth may still transit on load');
  equal(plan.tasks['task-1']?.events.length, 0, 'accepted history must not animate');
  equal(plan.tasks['task-1']?.transit, false, 'a settled run must not transit');
});

test('an active run transits on initial load while history stays settled', () => {
  const plan = deriveMotionPlan(null, model({
    plan: { tasks: [{ id: 'task-1', title: 'Live', state: 'running', current_run_id: 'run-1' }], orchestrations: [{ state: 'running' }] },
    runDetails: { 'task-1': liveRun },
  }));
  equal(plan.tasks['task-1']?.transit, true);
  equal(plan.tasks['task-1']?.events.length, 0);
});

test('diffs a running start as task activation', () => {
  const before = model({ plan: { tasks: [{ id: 'task-1', title: 'Next', state: 'ready' }], orchestrations: [{ state: 'running' }] } });
  const after = model({
    plan: { tasks: [{ id: 'task-1', title: 'Next', state: 'running', current_run_id: 'run-1' }], orchestrations: [{ state: 'running' }] },
    runDetails: { 'task-1': liveRun },
  });
  const plan = deriveMotionPlan(before, after);
  truthy(plan.tasks['task-1']?.events.includes('task-activated'));
  equal(plan.tasks['task-1']?.transit, true);
});

test('diffs a new attempt without animating prior attempts', () => {
  const before = model({
    plan: { tasks: [{ id: 'task-1', title: 'Retry', state: 'running', current_run_id: 'run-1' }], orchestrations: [{ state: 'running' }] },
    runDetails: { 'task-1': liveRun },
  });
  const after = model({
    plan: { tasks: [{ id: 'task-1', title: 'Retry', state: 'running', current_run_id: 'run-1' }], orchestrations: [{ state: 'running' }] },
    runDetails: { 'task-1': {
      run: { id: 'run-1', status: 'running', current_attempt_id: 'attempt-2' },
      attempts: [
        { id: 'attempt-1', attempt_number: 1, status: 'failed', receipt: { no_effect: true } },
        { id: 'attempt-2', attempt_number: 2, status: 'running' },
      ],
    } },
  });
  const plan = deriveMotionPlan(before, after);
  truthy(plan.tasks['task-1']?.events.includes('attempt-added'));
  equal(plan.tasks['task-1']?.arrivedAttemptIds.length, 1);
  equal(plan.tasks['task-1']?.arrivedAttemptIds[0], 'attempt-2');
  truthy(plan.tasks['task-1']?.events.includes('attempt-ended'));
  equal(plan.tasks['task-1']?.settledAttemptIds[0], 'attempt-1');
  equal(after.work.tasks[0]?.attempts.length, 2, 'prior attempts stay in history');
});

test('diffs a no-effect terminal without inventing a gate', () => {
  const before = model({
    plan: { tasks: [{ id: 'task-1', title: 'Empty', state: 'running', current_run_id: 'run-1' }], orchestrations: [{ state: 'running' }] },
    runDetails: { 'task-1': liveRun },
  });
  const after = model({
    plan: { tasks: [{ id: 'task-1', title: 'Empty', state: 'running', current_run_id: 'run-1' }], orchestrations: [{ state: 'running' }] },
    runDetails: { 'task-1': { run: { id: 'run-1', status: 'running' }, attempts: [{ id: 'attempt-1', attempt_number: 1, status: 'failed', receipt: { no_effect: true } }] } },
  });
  const plan = deriveMotionPlan(before, after);
  truthy(plan.tasks['task-1']?.events.includes('attempt-ended'));
  equal(plan.tasks['task-1']?.events.includes('gate-rejected'), false, 'no-effect never reaches the gate');
  equal(plan.tasks['task-1']?.events.includes('gate-accepted'), false);
});

test('diffs a rejection at the gate', () => {
  const rejected = {
    run: { id: 'run-1', status: 'running' },
    attempts: [{ id: 'attempt-1', attempt_number: 1, status: 'failed', receipt: { workspace_diff: [{ path: 'src/a.ts' }], acceptance: [{ criterion_id: 'criterion-1', status: 'failed', evidence: { observed: false } }] } }],
  };
  const before = model({
    plan: { tasks: [{ id: 'task-1', title: 'Refused', state: 'running', current_run_id: 'run-1' }], orchestrations: [{ state: 'running' }] },
    runDetails: { 'task-1': liveRun },
  });
  const after = model({
    plan: { tasks: [{ id: 'task-1', title: 'Refused', state: 'running', current_run_id: 'run-1' }], orchestrations: [{ state: 'running' }] },
    runDetails: { 'task-1': rejected },
  });
  const plan = deriveMotionPlan(before, after);
  truthy(plan.tasks['task-1']?.events.includes('gate-rejected'));
  truthy(plan.tasks['task-1']?.events.includes('attempt-ended'));
});

test('diffs measured acceptance as the only path to task-accepted', () => {
  const acceptedDetails = {
    run: { id: 'run-1', status: 'completed' },
    attempts: [{ id: 'attempt-1', attempt_number: 1, status: 'completed', receipt: { workspace_diff: [{ path: 'src/a.ts' }], acceptance: [{ criterion_id: 'criterion-1', status: 'passed', evidence: { observed: true } }] } }],
  };
  const before = model({
    plan: { tasks: [{ id: 'task-1', title: 'Proven', state: 'running', current_run_id: 'run-1' }], orchestrations: [{ state: 'running' }] },
    runDetails: { 'task-1': liveRun },
  });
  const after = model({
    plan: { tasks: [{ id: 'task-1', title: 'Proven', state: 'completed', current_run_id: 'run-1' }], orchestrations: [{ state: 'running' }] },
    runDetails: { 'task-1': acceptedDetails },
    completion: { ready: false, evidence: { tasks: [{ task_id: 'task-1', done: true, criteria: [{ id: 'criterion-1', status: 'passed', source: 'measured', evidence: { observed: true } }] }] } },
  });
  const plan = deriveMotionPlan(before, after);
  truthy(plan.tasks['task-1']?.events.includes('gate-accepted'));
  truthy(plan.tasks['task-1']?.events.includes('task-accepted'));
  equal(plan.tasks['task-1']?.transit, false, 'transit stops the moment the run is terminal');
});

test('an executor stop without measured criteria earns no gate event', () => {
  const before = model({
    plan: { tasks: [{ id: 'task-1', title: 'Died', state: 'running', current_run_id: 'run-1' }], orchestrations: [{ state: 'running' }] },
    runDetails: { 'task-1': liveRun },
  });
  const after = model({
    plan: { tasks: [{ id: 'task-1', title: 'Died', state: 'failed', current_run_id: 'run-1' }], orchestrations: [{ state: 'running' }] },
    runDetails: { 'task-1': { run: { id: 'run-1', status: 'failed' }, attempts: [{ id: 'attempt-1', attempt_number: 1, status: 'failed', receipt: {} }] } },
  });
  const plan = deriveMotionPlan(before, after);
  equal(plan.tasks['task-1']?.events.includes('gate-rejected'), false);
  equal(plan.tasks['task-1']?.events.includes('gate-accepted'), false);
  equal(plan.tasks['task-1']?.transit, false);
});

test('the same snapshot twice never replays a transition', () => {
  const snapshot = model({
    plan: { tasks: [{ id: 'task-1', title: 'Steady', state: 'running', current_run_id: 'run-1' }], orchestrations: [{ state: 'running' }] },
    runDetails: { 'task-1': liveRun },
  });
  const plan = deriveMotionPlan(snapshot, snapshot);
  equal(plan.tasks['task-1']?.events.length, 0);
  equal(plan.tasks['task-1']?.transit, true, 'state-based transit is stable, not an event');
});

test('reduced motion settles immediately and suppresses transit', () => {
  const snapshot = model({
    plan: { tasks: [{ id: 'task-1', title: 'Live', state: 'running', current_run_id: 'run-1' }], orchestrations: [{ state: 'running' }] },
    runDetails: { 'task-1': liveRun },
  });
  const settled = settleMotionPlan(snapshot, { allowMotion: false });
  equal(settled.live, true);
  equal(settled.tasks['task-1']?.transit, false);
  equal(settled.tasks['task-1']?.events.length, 0);
});

test('hidden-tab reconciliation absorbs missed transitions without replay', () => {
  // The tab was hidden while `before` became `after`; on return the controller
  // settles into `after` directly instead of replaying the missed transition.
  const after = model({
    plan: { tasks: [{ id: 'task-1', title: 'Proven', state: 'completed', current_run_id: 'run-1' }], orchestrations: [{ state: 'running' }] },
    runDetails: { 'task-1': { run: { id: 'run-1', status: 'completed' }, attempts: [{ id: 'attempt-1', attempt_number: 1, status: 'completed', receipt: { workspace_diff: [{ path: 'src/a.ts' }], acceptance: [{ criterion_id: 'criterion-1', status: 'passed', evidence: { observed: true } }] } }] } },
    completion: { ready: false, evidence: { tasks: [{ task_id: 'task-1', done: true, criteria: [{ id: 'criterion-1', status: 'passed', source: 'measured', evidence: { observed: true } }] }] } },
  });
  const reconciled = settleMotionPlan(after);
  equal(reconciled.tasks['task-1']?.events.length, 0, 'stale transitions must not queue or replay');
});

test('caps prominent transit at three concurrent active tasks', () => {
  equal(TRANSIT_CONCURRENCY_LIMIT, 3);
  const tasks = Array.from({ length: 5 }, (_, index) => ({
    id: `task-${index + 1}`,
    title: `Task ${index + 1}`,
    description: '',
    rawState: 'running',
    state: index < 2 ? 'retrying' as const : 'running' as const,
    connector: 'running' as const,
    gateState: null,
    gateCriteria: [],
    criteria: [],
    attempts: [],
    dependencyIds: [],
    dependencyTitles: [],
    requirementIds: [],
    groupLabel: 'Work',
    depth: 0,
    current: index === 0,
    active: true,
    accepted: false,
    stopKind: null,
    waitingOn: [],
    blockedReason: null,
    runId: `run-${index + 1}`,
    run: null,
    technical: { attempts: [], artifacts: [], output: '' },
  }));
  const snapshot = model({
    plan: { tasks: tasks.map((task) => ({ id: task.id, title: task.title, state: 'running', current_run_id: task.runId })), orchestrations: [{ state: 'running' }] },
    runDetails: Object.fromEntries(tasks.map((task) => [task.id, liveRun])),
  });
  const moving = snapshot.work.tasks.filter((task) => deriveMotionPlan(null, snapshot).tasks[task.id]?.transit);
  equal(moving.length, 3, 'at most three connectors carry transit');
  equal(moving[0]?.id, snapshot.work.currentTask?.id, 'the dominant active task keeps the lead');
});

test('a task absent from the previous snapshot settles instead of animating', () => {
  const after = model({
    plan: { tasks: [{ id: 'task-new', title: 'Appeared', state: 'running', current_run_id: 'run-1' }], orchestrations: [{ state: 'running' }] },
    runDetails: { 'task-new': liveRun },
  });
  const before = model({ plan: { tasks: [], orchestrations: [{ state: 'running' }] } });
  const plan = deriveMotionPlan(before, after);
  equal(plan.tasks['task-new']?.events.length, 0);
  equal(plan.tasks['task-1' as string]?.events, undefined);
});

test('missing run data fabricates no transitions', () => {
  const before = model({ plan: { tasks: [{ id: 'task-1', title: 'Quiet', state: 'planned' }], orchestrations: [{ state: 'running' }] } });
  const after = model({ plan: { tasks: [{ id: 'task-1', title: 'Quiet', state: 'planned' }], orchestrations: [{ state: 'running' }] } });
  const plan = deriveMotionPlan(before, after);
  equal(plan.tasks['task-1']?.events.length, 0);
  equal(plan.tasks['task-1']?.transit, false);
});

console.log(`V5 MOTION CONTROLLER CONTRACT PASSED (${passed} tests)`);
