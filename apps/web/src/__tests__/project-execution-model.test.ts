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

function truthy(value: unknown, message: string): asserts value {
  if (!value) throw new Error(message);
}

function base(overrides: Partial<WorkspaceModelInput> = {}): WorkspaceModelInput {
  return {
    project: { id: 'project-v4', name: 'Execution map', purpose: 'Map execution truth.' },
    stage: 'running',
    blueprint: { id: 'blueprint-v4', revision: 1, status: 'approved' },
    requirements: [{ id: 'requirement-v4', title: 'Execution truth', status: 'approved' }],
    plan: { tasks: [], orchestrations: [{ state: 'running' }] },
    completion: { ready: false, evidence: { tasks: [] } },
    deliverables: [],
    readiness: { ready: true, blockers: [] },
    runDetails: {},
    ...overrides,
  };
}

test('keeps an older rejection off the live retry gate', () => {
  const model = deriveProjectWorkspaceModel(base({
    plan: { tasks: [{ id: 'task-1', title: 'Retry', state: 'running', current_run_id: 'run-1' }], orchestrations: [{ state: 'running' }] },
    runDetails: { 'task-1': {
      run: { id: 'run-1', status: 'running', current_attempt_id: 'attempt-2' },
      attempts: [
        { id: 'attempt-1', attempt_number: 1, status: 'failed', receipt: { acceptance: [{ status: 'failed', evidence: { observed: false } }] } },
        { id: 'attempt-2', attempt_number: 2, status: 'running' },
      ],
    } },
  }));
  const task = model.work.tasks[0]!;
  equal(task.state, 'retrying');
  equal(task.gateState, null);
  equal(task.attempts[0]?.gateState, 'rejected');
  equal(task.attempts[1]?.active, true);
  equal(model.evidence.items[0]?.gateState, null);
});

test('separates measured effects from acceptance verdicts', () => {
  const model = deriveProjectWorkspaceModel(base({
    plan: { tasks: [{ id: 'task-1', title: 'Effects', state: 'failed', current_run_id: 'run-1' }] },
    runDetails: { 'task-1': { attempts: [
      { id: 'attempt-1', attempt_number: 1, status: 'failed', receipt: { workspace_diff: [{ path: 'src/a.ts' }] } },
      { id: 'attempt-2', attempt_number: 2, status: 'failed', receipt: { no_effect: true } },
      { id: 'attempt-3', attempt_number: 3, status: 'failed', receipt: { no_effect: true, acceptance: [{ status: 'failed', evidence: { observed: false } }] } },
    ] } },
  }));
  const attempts = model.work.tasks[0]!.attempts;
  equal(attempts[0]?.effect, 'observed');
  equal(attempts[0]?.outcome, 'effect');
  equal(attempts[1]?.effect, 'none');
  equal(attempts[1]?.outcome, 'no-effect');
  equal(attempts[2]?.gateState, 'rejected');
  equal(attempts[2]?.outcome, 'rejected');
});

test('maps the current run envelope and measured span', () => {
  const model = deriveProjectWorkspaceModel(base({
    plan: { tasks: [{ id: 'task-1', title: 'Envelope', state: 'running', current_run_id: 'run-1' }] },
    runDetails: { 'task-1': {
      run: {
        id: 'run-1', status: 'running', routing_mode: 'balanced', selected_agent_id: 'agent-1',
        selected_model_id: 'model-1', current_attempt_id: 'attempt-1', duration_ms: 8420,
        latency_provenance: 'measured', started_at: '2026-08-24T10:00:00Z',
      },
      attempts: [{ id: 'attempt-1', attempt_number: 1, status: 'running', executor_type: 'coding', agent_id: 'agent-1', model_id: 'model-1' }],
    } },
  }));
  const run = model.work.tasks[0]!.run!;
  equal(run.routingMode, 'balanced');
  equal(run.executorType, 'coding');
  equal(run.agentId, 'agent-1');
  equal(run.modelId, 'model-1');
  equal(run.durationMs, 8420);
  equal(run.durationMeasured, true);
  equal(run.historyScope, 'current-run-only');
});

test('preserves multiple active tasks while selecting one dominant task', () => {
  const model = deriveProjectWorkspaceModel(base({
    plan: { tasks: [
      { id: 'task-1', title: 'First', state: 'running', current_run_id: 'run-1' },
      { id: 'task-2', title: 'Second', state: 'running', current_run_id: 'run-2' },
    ], orchestrations: [{ state: 'running' }] },
    runDetails: {
      'task-1': { run: { id: 'run-1', status: 'running' }, attempts: [{ id: 'attempt-1', attempt_number: 1, status: 'running' }] },
      'task-2': { run: { id: 'run-2', status: 'running' }, attempts: [{ id: 'attempt-2', attempt_number: 1, status: 'running' }] },
    },
  }));
  equal(model.work.activeCount, 2);
  equal(model.work.activeTasks.length, 2);
  equal(model.work.tasks.filter((task) => task.current).length, 1);
});

test('distinguishes dependency waiting from an executor stop', () => {
  const model = deriveProjectWorkspaceModel(base({
    plan: { tasks: [
      { id: 'root', title: 'Foundation', state: 'planned' },
      { id: 'child', title: 'Dependent work', state: 'planned', dependency_ids: ['root'] },
      { id: 'failed', title: 'Executor stopped', state: 'failed' },
    ], orchestrations: [{ state: 'running' }] },
  }));
  const child = model.work.tasks.find((task) => task.id === 'child')!;
  const failed = model.work.tasks.find((task) => task.id === 'failed')!;
  equal(child.state, 'planned');
  equal(child.stopKind, 'dependency');
  equal(child.waitingOn[0], 'Foundation');
  equal(failed.state, 'blocked');
  equal(failed.stopKind, 'executor');
});

test('keeps unstarted work planned and promotes only dispatcher-ready work', () => {
  const idle = deriveProjectWorkspaceModel(base({
    plan: { tasks: [{ id: 'task-1', title: 'Quiet', state: 'planned' }], orchestrations: [{ state: 'planned' }] },
  }));
  equal(idle.work.tasks[0]?.state, 'planned');

  const approved = deriveProjectWorkspaceModel(base({
    plan: {
      tasks: [
        { id: 'task-1', title: 'Next up', state: 'planned' },
        { id: 'task-2', title: 'Explicitly ready', state: 'ready' },
        { id: 'child', title: 'Dependent', state: 'planned', dependency_ids: ['task-1'] },
      ],
      orchestrations: [{ state: 'approved' }],
    },
  }));
  equal(approved.work.tasks.find((task) => task.id === 'task-1')?.state, 'ready');
  equal(approved.work.tasks.find((task) => task.id === 'task-2')?.state, 'ready');
  const child = approved.work.tasks.find((task) => task.id === 'child')!;
  // A dependent must never look ready while its dependency is authoritatively incomplete.
  equal(child.state, 'planned');
  equal(child.stopKind, 'dependency');
});

test('maps a first live attempt to running before any retry exists', () => {
  const model = deriveProjectWorkspaceModel(base({
    plan: { tasks: [{ id: 'task-1', title: 'Live', state: 'running', current_run_id: 'run-1' }], orchestrations: [{ state: 'running' }] },
    runDetails: { 'task-1': {
      run: { id: 'run-1', status: 'running', current_attempt_id: 'attempt-1' },
      attempts: [{ id: 'attempt-1', attempt_number: 1, status: 'running' }],
    } },
  }));
  const task = model.work.tasks[0]!;
  equal(task.state, 'running');
  equal(task.connector, 'running');
  equal(task.attempts[0]?.outcome, 'running');
  equal(task.attempts[0]?.active, true);
});

test('never maps a stopped executor onto no effect', () => {
  const model = deriveProjectWorkspaceModel(base({
    plan: { tasks: [{ id: 'task-1', title: 'Died early', state: 'failed', current_run_id: 'run-1' }] },
    runDetails: { 'task-1': {
      run: { id: 'run-1', status: 'failed' },
      attempts: [{ id: 'attempt-1', attempt_number: 1, status: 'failed', receipt: {} }],
    } },
  }));
  const task = model.work.tasks[0]!;
  equal(task.state, 'blocked');
  equal(task.stopKind, 'executor');
  equal(task.accepted, false);
  equal(task.gateState, null);
  equal(task.attempts[0]?.effect, 'unknown');
  equal(task.attempts[0]?.outcome, 'stopped');
});

test('claims no effect only from the authoritative receipt flag', () => {
  const model = deriveProjectWorkspaceModel(base({
    plan: { tasks: [{ id: 'task-1', title: 'Empty diff', state: 'failed', current_run_id: 'run-1' }] },
    runDetails: { 'task-1': { attempts: [
      { id: 'attempt-1', attempt_number: 1, status: 'completed', receipt: { workspace_diff: [] } },
      { id: 'attempt-2', attempt_number: 2, status: 'completed', receipt: { workspace_diff: [], no_effect: true } },
    ] } },
  }));
  const attempts = model.work.tasks[0]!.attempts;
  equal(attempts[0]?.effect, 'unknown');
  equal(attempts[0]?.outcome, 'stopped');
  equal(attempts[1]?.effect, 'none');
  equal(attempts[1]?.outcome, 'no-effect');
});

test('keeps an executor that finished short of acceptance out of accepted', () => {
  const model = deriveProjectWorkspaceModel(base({
    plan: { tasks: [{ id: 'task-1', title: 'Wrote but unmeasured', state: 'blocked', current_run_id: 'run-1' }] },
    runDetails: { 'task-1': { attempts: [{
      id: 'attempt-1',
      attempt_number: 1,
      status: 'completed',
      receipt: { workspace_diff: [{ path: 'src/a.ts' }], acceptance: [{ criterion_id: 'criterion-1', status: 'pending' }] },
    }] } },
  }));
  const task = model.work.tasks[0]!;
  equal(task.state, 'blocked');
  equal(task.stopKind, 'executor');
  equal(task.accepted, false);
  equal(task.gateState, 'evaluating');
  equal(task.attempts[0]?.effect, 'observed');
  equal(task.attempts[0]?.outcome, 'effect');
});

test('separates an accepted task from a complete project', () => {
  const model = deriveProjectWorkspaceModel(base({
    plan: { tasks: [
      { id: 'done', title: 'Measured work', state: 'completed' },
      { id: 'next', title: 'Remaining work', state: 'planned' },
    ], orchestrations: [{ state: 'running' }] },
    completion: {
      ready: false,
      evidence: { tasks: [{ task_id: 'done', done: true, criteria: [{ id: 'criterion-1', status: 'passed', source: 'measured', evidence: { observed: true } }] }] },
    },
  }));
  const done = model.work.tasks.find((task) => task.id === 'done')!;
  equal(done.accepted, true);
  equal(model.evidence.acceptedCount, 1);
  equal(model.evidence.verified, false);
  equal(model.delivery.canPackage, false);
  equal(model.action?.kind, 'continue-execution');
  equal(model.lifecycle.find((item) => item.station === 'deliverable')?.status, 'future');
});

test('preserves every attempt in order instead of collapsing history', () => {
  const receipts = [
    { receipt: { no_effect: true } },
    { receipt: { acceptance: [{ criterion_id: 'criterion-1', status: 'failed', evidence: { observed: false } }] } },
    { receipt: { workspace_diff: [{ path: 'src/a.ts' }] } },
    { receipt: { acceptance: [{ criterion_id: 'criterion-1', status: 'passed', evidence: { observed: true } }] } },
    {},
  ];
  const model = deriveProjectWorkspaceModel(base({
    plan: { tasks: [{ id: 'task-1', title: 'Long history', state: 'running', current_run_id: 'run-1' }], orchestrations: [{ state: 'running' }] },
    runDetails: { 'task-1': { attempts: receipts.map((item, index) => ({
      id: `attempt-${index + 1}`,
      attempt_number: index + 1,
      status: index === 4 ? 'running' : 'failed',
      ...item,
    })) } },
  }));
  const attempts = model.work.tasks[0]!.attempts;
  equal(attempts.length, 5);
  attempts.forEach((attempt, index) => equal(attempt.number, index + 1));
  equal(attempts[0]?.outcome, 'no-effect');
  equal(attempts[1]?.outcome, 'rejected');
  equal(attempts[2]?.outcome, 'effect');
  equal(attempts[3]?.outcome, 'accepted');
  equal(attempts[4]?.outcome, 'running');
});

test('selects current work by execution authority order', () => {
  const rejectedAttempt = { id: 'attempt-r', attempt_number: 1, status: 'failed', receipt: { acceptance: [{ criterion_id: 'criterion-1', status: 'failed', evidence: { observed: false } }] } };
  const pool = [
    { id: 'task-verifying', title: 'Verifying', state: 'completed' },
    { id: 'task-rejected', title: 'Rejected', state: 'failed', current_run_id: 'run-1' },
    { id: 'task-ready', title: 'Ready', state: 'ready' },
    { id: 'task-blocked', title: 'Blocked', state: 'blocked' },
  ];
  // The authority ladder is fixed: verifying outranks a rejection, which outranks
  // ready work, which outranks a blocked stop. Active execution outranks them all.
  const expectations = ['task-verifying', 'task-rejected', 'task-ready', 'task-blocked'];
  for (let cut = 0; cut < expectations.length; cut += 1) {
    const remaining = pool.slice(cut);
    const model = deriveProjectWorkspaceModel(base({
      plan: { tasks: remaining.map((task) => ({ ...task })), orchestrations: [{ state: 'running' }] },
      runDetails: remaining.some((task) => task.id === 'task-rejected')
        ? { 'task-rejected': { attempts: [rejectedAttempt] } }
        : {},
    }));
    equal(model.work.currentTask?.id, expectations[cut]!);
  }

  const active = deriveProjectWorkspaceModel(base({
    plan: { tasks: [
      { id: 'task-verifying', title: 'Verifying', state: 'completed' },
      { id: 'task-live', title: 'Live', state: 'running', current_run_id: 'run-live' },
    ], orchestrations: [{ state: 'running' }] },
    runDetails: { 'task-live': { run: { id: 'run-live', status: 'running' }, attempts: [{ id: 'attempt-1', attempt_number: 1, status: 'running' }] } },
  }));
  equal(active.work.currentTask?.id, 'task-live');
});

test('carries full execution truth into ledger scale for mobile parity', () => {
  const tasks = Array.from({ length: 120 }, (_, index) => ({
    id: `task-${index + 1}`,
    title: `Task ${index + 1}`,
    state: index === 119 ? 'running' : 'planned',
    current_run_id: index === 119 ? 'run-live' : undefined,
  }));
  const model = deriveProjectWorkspaceModel(base({
    plan: { tasks, orchestrations: [{ state: 'running' }] },
    runDetails: { 'task-120': {
      run: { id: 'run-live', status: 'running' },
      attempts: [
        { id: 'attempt-1', attempt_number: 1, status: 'failed', receipt: { no_effect: true } },
        { id: 'attempt-2', attempt_number: 2, status: 'running' },
      ],
    } },
  }));
  equal(model.work.scale, 'ledger');
  const live = model.work.tasks.find((task) => task.id === 'task-120')!;
  equal(live.state, 'retrying');
  equal(live.runId, 'run-live');
  equal(live.attempts.length, 2);
  equal(live.attempts[0]?.outcome, 'no-effect');
  equal(live.gateState, null);
  equal(model.work.currentTask?.id, 'task-120');
  // Unmeasured work never enters the evidence station, even when it is the current task.
  equal(model.evidence.items.some((item) => item.taskId === 'task-120'), false);
});

test('exposes no run or attempt truth where none was reported', () => {
  const unlinked = deriveProjectWorkspaceModel(base({
    plan: { tasks: [{ id: 'task-1', title: 'Never dispatched', state: 'planned' }], orchestrations: [{ state: 'approved' }] },
  }));
  const quiet = unlinked.work.tasks[0]!;
  equal(quiet.runId, null);
  equal(quiet.run, null);
  equal(quiet.attempts.length, 0);

  const linkedButUnreported = deriveProjectWorkspaceModel(base({
    plan: { tasks: [{ id: 'task-2', title: 'Run id only', state: 'running', current_run_id: 'run-9' }], orchestrations: [{ state: 'running' }] },
    runDetails: { 'task-2': {} },
  }));
  const sparse = linkedButUnreported.work.tasks[0]!;
  equal(sparse.runId, 'run-9');
  equal(sparse.attempts.length, 0);
  equal(sparse.run?.status, 'unknown');
});

test('never fabricates verification or measured progress', () => {
  const idle = deriveProjectWorkspaceModel(base({
    plan: { tasks: [{ id: 'task-1', title: 'Planned', state: 'planned' }], orchestrations: [{ state: 'approved' }] },
  }));
  equal(idle.waiting, null);
  equal(idle.evidence.verified, false);

  const running = deriveProjectWorkspaceModel(base({
    busy: 'start',
    plan: { tasks: [{ id: 'task-1', title: 'Running', state: 'running', current_run_id: 'run-1' }], orchestrations: [{ state: 'running' }] },
    runDetails: { 'task-1': { run: { id: 'run-1', status: 'running' }, attempts: [{ id: 'attempt-1', attempt_number: 1, status: 'running' }] } },
  }));
  truthy(running.waiting, 'an active run should name what it waits for');
  equal(running.waiting.noEstimate, true);
  equal(running.evidence.verified, false);
});

console.log(`V4 EXECUTION MODEL CONTRACT PASSED (${passed} tests)`);
