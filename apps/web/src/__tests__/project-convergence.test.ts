import { deriveMotionPlan, settleMotionPlan } from '../components/project-workspace-motion.ts';
import { deriveProjectWorkspaceModel } from '../components/project-workspace-model.ts';
import type { RunDetailRecord, WorkspaceModelInput } from '../components/project-workspace-model.ts';

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

const acceptance = [{ criterion_id: 'criterion-output', statement: 'The output is measured and accepted.' }];

function acceptedRun(taskId: string, runId: string): [string, RunDetailRecord] {
  return [runId, {
    run: { id: runId, status: 'completed', routing_mode: 'balanced', duration_ms: 9000, latency_provenance: 'measured' },
    attempts: [{ id: `${runId}-attempt-1`, attempt_number: 1, status: 'completed', receipt: { workspace_diff: [{ path: `src/${taskId}.ts` }], acceptance: [{ criterion_id: 'criterion-output', status: 'passed', evidence: { observed: true } }] } }],
    artifacts: [{ id: `artifact-${runId}`, path: `src/${taskId}.ts`, sha256: 'a1b2c3d4e5f6a7b8' }],
  }];
}

function verifiedInput(overrides: Partial<WorkspaceModelInput> = {}): WorkspaceModelInput {
  const tasks = [
    { id: 'task-1', title: 'First proven task', state: 'completed', current_run_id: 'run-1', acceptance },
    { id: 'task-2', title: 'Second proven task', state: 'completed', current_run_id: 'run-2', acceptance },
  ];
  const input: WorkspaceModelInput = {
    project: { id: 'project-v7', name: 'Convergence', purpose: 'Resolve complexity into one verified line.' },
    stage: 'complete',
    blueprint: { id: 'blueprint-v7', revision: 1, status: 'approved' },
    requirements: [{ id: 'requirement-v7', title: 'Verified outcome', status: 'completed' }],
    plan: { tasks, orchestrations: [{ state: 'complete' }], needs: [] },
    completion: {
      ready: true,
      evidence: { tasks: tasks.map((task) => ({ task_id: task.id, done: true, criteria: [{ id: 'criterion-output', status: 'passed', source: 'measured', evidence: { observed: true } }] })) },
    },
    deliverables: [],
    readiness: { ready: true, blockers: [] },
    runDetails: Object.fromEntries([acceptedRun('task-1', 'run-1'), acceptedRun('task-2', 'run-2')]),
    ...overrides,
  };
  return { ...input, runDetails: input.runDetails as WorkspaceModelInput['runDetails'] };
}

function model(overrides: Partial<WorkspaceModelInput> = {}) {
  return deriveProjectWorkspaceModel(verifiedInput(overrides));
}

test('the convergence event fires on the observed verification transition', () => {
  const before = model({ completion: { ready: false, evidence: { tasks: [] } } });
  const after = model();
  const plan = deriveMotionPlan(before, after);
  truthy(plan.projectEvents.includes('project-verified'));
  // The tasks' acceptance genuinely arrived with the reconciliation, so the
  // rows settle into accepted geometry while the chain plays over them.
  truthy(plan.tasks['task-1']?.events.includes('task-accepted'));
  truthy(plan.tasks['task-1']?.events.includes('gate-accepted'));
});

test('an already-verified project never replays the convergence on load', () => {
  const plan = deriveMotionPlan(null, model());
  equal(plan.projectEvents.length, 0, 'the seal is already closed; nothing replays');
  equal(plan.tasks['task-1']?.events.length, 0);
  // Even with every receipt already in hand — accepted tasks, artifacts,
  // checksums, a ready package — a fresh mount renders the resting Closed Cell
  // immediately instead of replaying history.
  const packaged = model({
    deliverables: [{ id: 'package-1', name: 'convergence', version: '0.1.0', readiness: 'ready', checksum: 'a1b2c3d4e5f6a7b8a1b2c3d4e5f6a7b8a1b2c3d4e5f6a7b8a1b2c3d4e5f6a7b8', download_path: '/download' }],
  });
  const replay = deriveMotionPlan(null, packaged);
  equal(replay.projectEvents.length, 0, 'a fully-evidenced historical state still never replays');
  equal(replay.tasks['task-2']?.events.length, 0);
});

test('reduced motion never emits the convergence event', () => {
  const before = model({ completion: { ready: false, evidence: { tasks: [] } } });
  const after = model();
  const plan = deriveMotionPlan(before, after, { allowMotion: false });
  equal(plan.projectEvents.length, 0, 'the resting composition renders immediately');
});

test('a hidden tab absorbs the verification without replaying the chain', () => {
  const after = model();
  const reconciled = settleMotionPlan(after);
  equal(reconciled.projectEvents.length, 0);
});

test('the same snapshot twice never refires the convergence', () => {
  const snapshot = model();
  const plan = deriveMotionPlan(snapshot, snapshot);
  equal(plan.projectEvents.length, 0);
});

test('canonical completion alone drives the chain — nothing else has to change', () => {
  // The two snapshots differ ONLY in the canonical completion verdict: same
  // tasks, same acceptance, same evidence, same artifacts, same checksums.
  const before = model({ completion: { ready: false, evidence: { tasks: verifiedInput().completion?.evidence?.tasks ?? [] } } });
  const after = model();
  const plan = deriveMotionPlan(before, after);
  equal(plan.projectEvents.length, 1, 'exactly one convergence event for exactly one canonical flip');
  equal(plan.projectEvents[0], 'project-verified');
  equal(plan.tasks['task-1']?.events.length, 0, 'no task-level change was required to trigger the chain');
  equal(plan.tasks['task-2']?.events.length, 0);
  // The resting Closed Cell conditions hold after the flip.
  truthy(after.evidence.verified);
  equal(after.currentStation, 'deliverable');
});

test('unverified work can never converge, whatever the task states claim', () => {
  // The strongest possible false-negative fixture: every visible task is
  // accepted with measured criteria, artifacts and checksums exist, even a
  // ready-looking package record exists — yet canonical completion says NO.
  const fullyAccepted = model({
    completion: { ready: false, evidence: { tasks: verifiedInput().completion?.evidence?.tasks ?? [] } },
    deliverables: [{ id: 'package-early', name: 'convergence', version: '0.0.1', readiness: 'ready', checksum: 'a1b2c3d4e5f6a7b8a1b2c3d4e5f6a7b8a1b2c3d4e5f6a7b8a1b2c3d4e5f6a7b8', download_path: '/download' }],
  });
  truthy(model().work.tasks.every((task) => task.accepted), 'fixture premise: every visible task is accepted');
  truthy(fullyAccepted.work.tasks.every((task) => task.sheet.artifacts.every((artifact) => artifact.checksum)), 'fixture premise: checksums exist');
  equal(fullyAccepted.evidence.verified, false, 'accepted tasks never imply completion');
  equal(fullyAccepted.delivery.verifiedWork, false);
  equal(fullyAccepted.delivery.ready, null, 'a ready-looking package cannot close an incomplete project');
  equal(fullyAccepted.currentStation, 'execution', 'the workspace stays in the incomplete composition');
  equal(fullyAccepted.lifecycle[5]?.status, 'future', 'the deliverable station has not been reached');
  truthy(fullyAccepted.action?.kind !== 'download-deliverable' && fullyAccepted.action?.kind !== 'package-deliverable');

  const before = model({ completion: { ready: false, evidence: { tasks: [] } } });
  const plan = deriveMotionPlan(before, fullyAccepted);
  equal(plan.projectEvents.length, 0, 'a partial project gets the Attention station, not a celebration');
});

test('the resting receipt is fed by measured facts only', () => {
  const packaged = model({
    deliverables: [{ id: 'package-1', name: 'convergence', version: '0.1.0', readiness: 'ready', checksum: 'a1b2c3d4e5f6a7b8a1b2c3d4e5f6a7b8a1b2c3d4e5f6a7b8a1b2c3d4e5f6a7b8', download_path: '/download' }],
  });
  truthy(packaged.delivery.ready);
  equal(packaged.delivery.ready?.version, '0.1.0');
  equal(packaged.delivery.ready?.checksum?.length, 64);
  equal(packaged.work.completedCount, 2, 'the receipt counts only accepted tasks');
  equal(packaged.action?.kind, 'download-deliverable');

  const unpackaged = model();
  equal(unpackaged.evidence.verified, true);
  equal(unpackaged.delivery.ready, null, 'the seal closes on verified work with no package');
  equal(unpackaged.delivery.canPackage, true);
  equal(unpackaged.action?.kind, 'package-deliverable');
});

test('verification and packaging stay separate claims in the resting model', () => {
  const unpackaged = model();
  equal(unpackaged.delivery.verifiedWork, true);
  equal(unpackaged.evidence.acceptedCount, 2);
  equal(unpackaged.evidence.items.every((item) => item.microSpine !== null), true, 'every proven task carries its receipt');
});

console.log(`V7 CONVERGENCE CONTRACT PASSED (${passed} tests)`);
