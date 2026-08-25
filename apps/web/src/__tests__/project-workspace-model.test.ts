import {
  deriveProjectWorkspaceModel,
  directionFor,
  selectTaskScale,
} from '../components/project-workspace-model.ts';
import type {
  BlueprintRecord,
  RequirementRecord,
  WorkspaceModelInput,
} from '../components/project-workspace-model.ts';

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

const blueprint: BlueprintRecord = {
  id: 'blueprint-1',
  revision: 1,
  status: 'approved',
  content: {
    goal: 'Ship an evidence-backed project workspace.',
    requirements: [{
      proposal_id: 'proposal-1',
      title: 'Expose execution truth',
      acceptance: [{ criterion_id: 'criterion-1', statement: 'The measured workspace state is visible.' }],
    }],
  },
};

const requirements: RequirementRecord[] = [{
  id: 'requirement-1',
  title: 'Expose execution truth',
  status: 'approved',
  acceptance: [{ criterion_id: 'criterion-1', statement: 'The measured workspace state is visible.' }],
}];

function base(overrides: Partial<WorkspaceModelInput> = {}): WorkspaceModelInput {
  return {
    project: { id: 'project-1', name: 'Workspace', purpose: 'Ship an evidence-backed project workspace.' },
    stage: 'goal',
    blueprint: null,
    requirements: [],
    plan: { tasks: [], orchestrations: [] },
    completion: { ready: false, evidence: { tasks: [] } },
    deliverables: [],
    readiness: { ready: false, blockers: [] },
    runDetails: {},
    busy: '',
    error: '',
    isArabic: false,
    ...overrides,
  };
}

test('freezes task-scale boundaries', () => {
  equal(selectTaskScale(0), 'lattice');
  equal(selectTaskScale(24), 'lattice');
  equal(selectTaskScale(25), 'grouped');
  equal(selectTaskScale(80), 'grouped');
  equal(selectTaskScale(81), 'ledger');
});

test('selects logical direction from language', () => {
  equal(directionFor(false), 'ltr');
  equal(directionFor(true), 'rtl');
});

test('keeps an unprocessed goal at the first lifecycle station', () => {
  const model = deriveProjectWorkspaceModel(base());
  equal(model.currentStation, 'goal');
  equal(model.lifecycle[0]?.status, 'current');
  equal(model.action?.kind, 'understand-goal');
});

test('orders dependencies before dependents and computes depth', () => {
  const model = deriveProjectWorkspaceModel(base({
    stage: 'running',
    blueprint,
    requirements,
    plan: {
      orchestrations: [{ state: 'running' }],
      tasks: [
        { id: 'child', title: 'Dependent task', state: 'planned', dependency_ids: ['root'], requirement_ids: ['requirement-1'] },
        { id: 'root', title: 'Foundation task', state: 'completed', dependency_ids: [], requirement_ids: ['requirement-1'] },
      ],
    },
    completion: {
      ready: false,
      evidence: { tasks: [{ task_id: 'root', done: true, criteria: [{ id: 'criterion-1', status: 'passed', source: 'measured', evidence: { observed: true } }] }] },
    },
    readiness: { ready: true, blockers: [] },
  }));
  equal(model.work.tasks[0]?.id, 'root');
  equal(model.work.tasks[1]?.id, 'child');
  equal(model.work.tasks[1]?.depth, 1);
  equal(model.work.tasks[0]?.state, 'accepted');
});

test('does not infer acceptance from a completed task state', () => {
  const model = deriveProjectWorkspaceModel(base({
    stage: 'running',
    blueprint,
    requirements,
    plan: { orchestrations: [{ state: 'running' }], tasks: [{ id: 'task-1', title: 'Unmeasured task', state: 'completed', requirement_ids: ['requirement-1'] }] },
    readiness: { ready: true, blockers: [] },
  }));
  equal(model.work.tasks[0]?.accepted, false);
  equal(model.work.tasks[0]?.state, 'verifying');
  equal(model.evidence.acceptedCount, 0);
});

test('preserves spatial attempt outcomes from the current run', () => {
  const model = deriveProjectWorkspaceModel(base({
    stage: 'running',
    blueprint,
    requirements,
    plan: {
      orchestrations: [{ state: 'running' }],
      tasks: [{ id: 'task-1', title: 'Retry task', state: 'running', current_run_id: 'run-1', acceptance: [{ criterion_id: 'criterion-1', statement: 'Output is valid.' }] }],
    },
    readiness: { ready: true, blockers: [] },
    runDetails: {
      'task-1': { attempts: [
        { id: 'attempt-1', attempt_number: 1, status: 'completed', receipt: { no_effect: true } },
        { id: 'attempt-2', attempt_number: 2, status: 'completed', receipt: { acceptance: [{ criterion_id: 'criterion-1', status: 'failed', evidence: { observed: false } }] } },
        { id: 'attempt-3', attempt_number: 3, status: 'running' },
      ] },
    },
  }));
  equal(model.work.currentTask?.state, 'retrying');
  equal(model.work.currentTask?.attempts[0]?.outcome, 'no-effect');
  equal(model.work.currentTask?.attempts[1]?.outcome, 'rejected');
  equal(model.work.currentTask?.attempts[2]?.outcome, 'running');
});

test('preempts execution with a resolvable workspace blocker', () => {
  const model = deriveProjectWorkspaceModel(base({
    stage: 'ready',
    blueprint,
    requirements,
    plan: { orchestrations: [{ state: 'approved' }], tasks: [{ id: 'task-1', title: 'Planned task', state: 'planned' }] },
    readiness: { ready: false, blockers: [{ code: 'workspace_required', title: 'Project folder required', detail: 'Connect an approved folder.' }] },
  }));
  equal(model.attention?.kind, 'workspace');
  equal(model.action?.kind, 'connect-workspace');
  equal(model.lifecycle.find((item) => item.station === 'execution')?.status, 'blocked');
});

test('does not fabricate a resolver for an open project need', () => {
  const model = deriveProjectWorkspaceModel(base({
    stage: 'attention',
    blueprint,
    requirements,
    plan: {
      tasks: [{ id: 'task-1', title: 'Planned task', state: 'planned' }],
      needs: [{ id: 'need-1', title: 'Owner decision', description: 'Choose the source of truth.', need_type: 'information', impact: 'blocking', state: 'open' }],
    },
    readiness: { ready: true, blockers: [] },
  }));
  equal(model.attention?.kind, 'need');
  equal(model.attention?.action, null);
  equal(model.action, null);
});

test('hoists a stopped task and exposes its measured review locally', () => {
  const model = deriveProjectWorkspaceModel(base({
    stage: 'attention',
    blueprint,
    requirements,
    plan: { tasks: [{ id: 'task-1', title: 'Rejected output', state: 'failed', current_run_id: 'run-1' }] },
    readiness: { ready: true, blockers: [] },
    runDetails: { 'task-1': { attempts: [{ id: 'attempt-1', attempt_number: 1, status: 'completed', receipt: { acceptance: [{ status: 'failed', evidence: { reason: 'mismatch' } }] } }] } },
  }));
  equal(model.attention?.taskId, 'task-1');
  equal(model.action?.kind, 'review-blocker');
  equal(model.work.currentTask?.state, 'rejected');
});

test('keeps download dormant until completion and a ready package both exist', () => {
  const verified = base({
    stage: 'complete',
    blueprint,
    requirements,
    completion: { ready: true, evidence: { tasks: [] } },
    deliverables: [{ id: 'package-1', name: 'workspace', version: '1.0.0', readiness: 'draft' }],
  });
  const packageModel = deriveProjectWorkspaceModel(verified);
  equal(packageModel.delivery.ready, null);
  equal(packageModel.delivery.canPackage, true);
  equal(packageModel.action?.kind, 'package-deliverable');

  const downloadModel = deriveProjectWorkspaceModel({
    ...verified,
    deliverables: [{ id: 'package-2', name: 'workspace', version: '1.0.0', readiness: 'ready', checksum: 'abc123def456', download_path: '/download' }],
  });
  truthy(downloadModel.delivery.ready, 'ready persisted package should be exposed');
  equal(downloadModel.action?.kind, 'download-deliverable');
  equal(downloadModel.lifecycle.at(-1)?.status, 'verified');
});

test('separates plan compilation from execution start', () => {
  const model = deriveProjectWorkspaceModel(base({
    stage: 'ready',
    blueprint,
    requirements,
    plan: { tasks: [], orchestrations: [] },
    readiness: { ready: true, blockers: [] },
  }));
  equal(model.action?.kind, 'compile-plan');
});

console.log(`V3 MODEL CONTRACT PASSED (${passed} tests)`);
