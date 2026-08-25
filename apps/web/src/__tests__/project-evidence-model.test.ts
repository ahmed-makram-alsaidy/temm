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
    project: { id: 'project-v6', name: 'Acceptance evidence', purpose: 'Prove acceptance, criterion by criterion.' },
    stage: 'running',
    blueprint: { id: 'blueprint-v6', revision: 1, status: 'approved' },
    requirements: [{ id: 'requirement-v6', title: 'Measured acceptance', status: 'approved' }],
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

test('the sheet effect comes from the latest attempt with an authoritative fact', () => {
  const task = model({
    plan: { tasks: [{ id: 'task-1', title: 'Effects', state: 'failed', current_run_id: 'run-1' }] },
    runDetails: { 'task-1': { attempts: [
      { id: 'attempt-1', attempt_number: 1, status: 'failed', receipt: { workspace_diff: [{ path: 'src/old.ts' }] } },
      { id: 'attempt-2', attempt_number: 2, status: 'failed', receipt: { no_effect: true } },
      { id: 'attempt-3', attempt_number: 3, status: 'failed', receipt: { workspace_diff: [{ path: 'src/new.ts' }, { path: 'src/also-new.ts' }] } },
    ] } },
  }).work.tasks[0]!;
  equal(task.sheet.effect.kind, 'observed');
  equal(task.sheet.effect.paths[0], 'src/new.ts');
  equal(task.sheet.effect.paths.length, 2);
  equal(task.sheet.effect.sourceAttemptNumber, 3);
});

test('a no-effect receipt is the sheet effect when it is the latest fact', () => {
  const task = model({
    plan: { tasks: [{ id: 'task-1', title: 'Empty', state: 'failed', current_run_id: 'run-1' }] },
    runDetails: { 'task-1': { attempts: [
      { id: 'attempt-1', attempt_number: 1, status: 'failed', receipt: { workspace_diff: [{ path: 'src/old.ts' }] } },
      { id: 'attempt-2', attempt_number: 2, status: 'completed', receipt: { no_effect: true } },
    ] } },
  }).work.tasks[0]!;
  equal(task.sheet.effect.kind, 'none');
  equal(task.sheet.effect.paths.length, 0);
  equal(task.sheet.effect.sourceAttemptNumber, 2);
});

test('an unreported effect stays unknown and fabricates nothing', () => {
  const task = model({
    plan: { tasks: [{ id: 'task-1', title: 'Quiet', state: 'failed', current_run_id: 'run-1' }] },
    runDetails: { 'task-1': { attempts: [{ id: 'attempt-1', attempt_number: 1, status: 'failed', receipt: {} }] } },
  }).work.tasks[0]!;
  equal(task.sheet.effect.kind, 'unknown');
  equal(task.sheet.effect.sourceAttemptNumber, null);
  equal(task.sheet.microSpine, null, 'no measured criteria, no micro spine');
});

test('measured artifacts surface with their checksums for the receipt chips', () => {
  const task = model({
    plan: { tasks: [{ id: 'task-1', title: 'Packaged', state: 'completed', current_run_id: 'run-1' }] },
    runDetails: { 'task-1': {
      attempts: [{ id: 'attempt-1', attempt_number: 1, status: 'completed', receipt: { workspace_diff: [{ path: 'dist/app.js' }] } }],
      artifacts: [
        { id: 'artifact-1', path: 'dist/app.js', sha256: 'a1b2c3d4e5f6a7b8a1b2c3d4e5f6a7b8a1b2c3d4e5f6a7b8a1b2c3d4e5f6a7b8' },
        { id: 'artifact-2', path: 'dist/notes.txt' },
      ],
    } },
  }).work.tasks[0]!;
  equal(task.sheet.artifacts.length, 2);
  equal(task.sheet.artifacts[0]?.checksum, 'a1b2c3d4e5f6a7b8a1b2c3d4e5f6a7b8a1b2c3d4e5f6a7b8a1b2c3d4e5f6a7b8');
  equal(task.sheet.artifacts[1]?.checksum, null);
});

test('criterion evidence summaries surface only what the payload carries', () => {
  const task = model({
    plan: { tasks: [{ id: 'task-1', title: 'Contract', state: 'failed', current_run_id: 'run-1' }] },
    runDetails: { 'task-1': { attempts: [{
      id: 'attempt-1', attempt_number: 1, status: 'failed',
      receipt: { acceptance: [
        { criterion_id: 'criterion-1', status: 'passed', evidence: { path: 'src/output.ts' } },
        { criterion_id: 'criterion-2', status: 'failed', evidence: { reason: 'contract mismatch' } },
        { criterion_id: 'criterion-3', status: 'passed', evidence: 'suite: 12 passed' },
        { criterion_id: 'criterion-4', status: 'pending' },
      ] },
    }] } },
  }).work.tasks[0]!;
  const criteria = task.gateCriteria;
  equal(criteria.length, 4);
  equal(criteria[0]?.evidence, 'path src/output.ts');
  equal(criteria[1]?.evidence, 'reason contract mismatch');
  equal(criteria[2]?.evidence, 'suite: 12 passed');
  equal(criteria[3]?.evidence, null);
  equal(task.gateState, 'rejected');
});

test('the micro spine exists exactly when criteria were measured', () => {
  const unmeasured = model({
    plan: { tasks: [{ id: 'task-1', title: 'Verifying', state: 'completed' }] },
  }).work.tasks[0]!;
  equal(unmeasured.sheet.microSpine, null, 'an unmeasured proof is a claim, not geometry');

  const measured = model({
    plan: { tasks: [{ id: 'task-1', title: 'Proven', state: 'completed', current_run_id: 'run-1' }] },
    runDetails: { 'task-1': { attempts: [{ id: 'attempt-1', attempt_number: 1, status: 'completed', receipt: { workspace_diff: [{ path: 'src/a.ts' }], acceptance: [{ criterion_id: 'criterion-1', status: 'passed', evidence: { observed: true } }] } }] } },
    completion: { ready: false, evidence: { tasks: [{ task_id: 'task-1', done: true, criteria: [{ id: 'criterion-1', status: 'passed', source: 'measured', evidence: { observed: true } }] }] } },
  }).work.tasks[0]!;
  truthy(measured.sheet.microSpine);
  equal(measured.sheet.microSpine?.gateState, 'accepted');
  equal(measured.sheet.microSpine?.criteria.length, 1);

  // An attempt receipt alone never promotes the verdict: without the measured
  // completion assessment the receipt stays "evaluating", never accepted.
  const uncredited = model({
    plan: { tasks: [{ id: 'task-2', title: 'Uncredited', state: 'completed', current_run_id: 'run-2' }] },
    runDetails: { 'task-2': { attempts: [{ id: 'attempt-2', attempt_number: 1, status: 'completed', receipt: { workspace_diff: [{ path: 'src/b.ts' }], acceptance: [{ criterion_id: 'criterion-2', status: 'passed', evidence: { observed: true } }] } }] } },
  }).work.tasks[0]!;
  equal(uncredited.sheet.microSpine?.gateState, 'evaluating');
});

test('a live retry keeps its own unmeasured gate off the micro spine', () => {
  const task = model({
    plan: { tasks: [{ id: 'task-1', title: 'Retry', state: 'running', current_run_id: 'run-1' }], orchestrations: [{ state: 'running' }] },
    runDetails: { 'task-1': { run: { id: 'run-1', status: 'running', current_attempt_id: 'attempt-2' }, attempts: [
      { id: 'attempt-1', attempt_number: 1, status: 'failed', receipt: { acceptance: [{ criterion_id: 'criterion-1', status: 'failed', evidence: { observed: false } }] } },
      { id: 'attempt-2', attempt_number: 2, status: 'running' },
    ] } },
  }).work.tasks[0]!;
  equal(task.sheet.microSpine, null, 'the live attempt owns no verdict yet');
  equal(task.attempts[0]?.gateState, 'rejected', 'the older rejection stays in history');
});

test('evidence items carry the micro spine and effect for the stack', () => {
  const result = model({
    plan: {
      tasks: [
        { id: 'task-1', title: 'Proven', state: 'completed', current_run_id: 'run-1' },
        { id: 'task-2', title: 'Unmeasured', state: 'completed' },
      ],
      orchestrations: [{ state: 'running' }],
    },
    runDetails: { 'task-1': { attempts: [{ id: 'attempt-1', attempt_number: 1, status: 'completed', receipt: { workspace_diff: [{ path: 'src/a.ts' }], acceptance: [{ criterion_id: 'criterion-1', status: 'passed', evidence: { path: 'src/a.ts' } }] } }] } },
    completion: { ready: false, evidence: { tasks: [{ task_id: 'task-1', done: true, criteria: [{ id: 'criterion-1', status: 'passed', source: 'measured', evidence: { path: 'src/a.ts' } }] }] } },
  });
  equal(result.evidence.items.length, 1, 'unmeasured work stays out of the evidence stack');
  const item = result.evidence.items[0]!;
  equal(item.taskId, 'task-1');
  truthy(item.microSpine);
  equal(item.microSpine?.gateState, 'accepted');
  equal(item.effect.kind, 'observed');
  equal(item.effect.paths[0], 'src/a.ts');
});

test('an accepted task and a complete project remain separate claims in the sheet data', () => {
  const result = model({
    plan: { tasks: [
      { id: 'task-1', title: 'Proven', state: 'completed', current_run_id: 'run-1' },
      { id: 'task-2', title: 'Remaining', state: 'planned' },
    ], orchestrations: [{ state: 'running' }] },
    runDetails: { 'task-1': { attempts: [{ id: 'attempt-1', attempt_number: 1, status: 'completed', receipt: { workspace_diff: [{ path: 'src/a.ts' }], acceptance: [{ criterion_id: 'criterion-1', status: 'passed', evidence: { observed: true } }] } }] } },
    completion: { ready: false, evidence: { tasks: [{ task_id: 'task-1', done: true, criteria: [{ id: 'criterion-1', status: 'passed', source: 'measured', evidence: { observed: true } }] }] } },
  });
  equal(result.work.tasks[0]?.sheet.microSpine?.gateState, 'accepted');
  equal(result.evidence.verified, false);
  equal(result.delivery.canPackage, false);
});

console.log(`V6 EVIDENCE MODEL CONTRACT PASSED (${passed} tests)`);
