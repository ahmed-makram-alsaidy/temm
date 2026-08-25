import { deriveProjectWorkspaceModel } from '../components/project-workspace-model.ts';
import type { WorkspaceModelInput } from '../components/project-workspace-model.ts';
import {
  artifactRows,
  attemptLines,
  checksumChip,
  humanDuration,
  measuredFactRows,
  money,
  needsAttention,
  projectLabel,
  runOutcomeKind,
  runOutcomeLabel,
  runOutcomeSentence,
  technicalReceiptLines,
} from '../components/supporting-screens-model.ts';
import type { RawRunDetails } from '../components/supporting-screens-model.ts';
import type { TaskRun } from '../services/api.ts';

let passed = 0;

function test(name: string, run: () => void): void {
  run();
  passed += 1;
  console.log(`ok ${passed} - ${name}`);
}

function equal<T>(actual: T, expected: T, message = 'values differ'): void {
  if (actual !== expected) throw new Error(`${message}: expected ${String(expected)}, received ${String(actual)}`);
}

function deepEqual(actual: unknown, expected: unknown, message: string): void {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error(`${message}: ${JSON.stringify(actual)} !== ${JSON.stringify(expected)}`);
}

function truthy(value: unknown, message = 'expected truthy'): asserts value {
  if (!value) throw new Error(message);
}

// ---- Fixtures ----------------------------------------------------------

const acceptance = [{ criterion_id: 'criterion-output', statement: 'The report file exists and cites three sources.' }];

function workspaceInput(overrides: Partial<WorkspaceModelInput> = {}): WorkspaceModelInput {
  return {
    project: { id: 'project-v8', name: 'Support screens', purpose: 'Every guiding screen speaks the same language.' },
    stage: 'blueprint',
    blueprint: {
      id: 'blueprint-v8', revision: 3, status: 'proposed',
      content: {
        goal: 'Produce a sourced market report.',
        questions: [{ question_id: 'question-scope', text: 'Which market?', required: true }],
        requirements: [
          { proposal_id: 'proposal-1', title: 'Sourced market report', description: 'A written report the owner can forward.', acceptance: acceptance },
          { proposal_id: 'proposal-2', title: 'Human summary', acceptance: [] },
        ],
      },
    },
    requirements: [],
    plan: null,
    completion: null,
    deliverables: [],
    readiness: null,
    runDetails: {},
    ...overrides,
  };
}

function taskRun(overrides: Partial<TaskRun> & Pick<TaskRun, 'id' | 'prompt' | 'status'>): TaskRun {
  return {
    task_type: 'coding',
    routing_mode: 'balanced',
    input_tokens: 1000,
    output_tokens: 2000,
    cached_tokens: 0,
    actual_cost: 0.00412,
    reference_cost: 0.0118,
    saved_amount: 0.00768,
    saving_percentage: 65.1,
    duration_ms: 42000,
    quality_eval_score: 87.4,
    token_provenance: 'provider_reported',
    cost_provenance: 'measured',
    quality_provenance: 'measured',
    latency_provenance: 'measured',
    measurement_metadata: {},
    financials: {},
    route_explanation: '',
    fallback_chain: ['fallback-a', 'fallback-b'],
    log_output: '',
    result_output: '',
    created_at: '2026-08-25T09:24:00Z',
    status_reason: null,
    ...overrides,
  };
}

const fullReceipt: RawRunDetails = {
  attempts: [
    { id: 'run-x-attempt-1', attempt_number: 1, status: 'failed', executor_type: 'cli', agent_id: 'codex-cli' },
    { id: 'run-x-attempt-2', attempt_number: 2, status: 'completed', executor_type: 'cli', agent_id: 'qwen-coder-cli' },
  ],
  output: [{ content: 'Guard added.' }, { content: ' Second line.', truncated: true }],
  artifacts: [
    { id: 'a-1', path: 'core/dispatcher.py', sha256: 'c7d8e9f0a1b2c3d4e5f6a7b8', artifact_type: 'patch', metadata: { size_bytes: 2148 } },
    { id: 'a-2', path: 'README.md', sha256: null },
  ],
  usage: { usage: { input_tokens: 1840, output_tokens: 2210, cached_tokens: 512 }, provenance: { input_tokens: 'provider_reported', output_tokens: 'measured' } },
  latency: { latency: { duration_ms: 42100, ttft_ms: 640 }, provenance: { duration_ms: 'measured', ttft_ms: 'measured' } },
  events: [{ event_id: 'e-1', event_type: 'run.completed', sequence: 4, timestamp: '2026-08-25T09:24:43Z' }],
};

// ---- 1. Blueprint review preserves canonical blueprint data ------------

test('the understood station presents the blueprint verbatim — nothing rewritten', () => {
  const model = deriveProjectWorkspaceModel(workspaceInput());
  const source = workspaceInput().blueprint?.content?.requirements ?? [];
  equal(model.understanding.requirements.length, source.length);
  deepEqual(
    model.understanding.requirements.map((requirement) => requirement.title),
    source.map((requirement) => requirement.title),
    'requirement titles pass through unchanged',
  );
  equal(model.understanding.requirements[0]?.acceptance[0], 'The report file exists and cites three sources.');
});

// ---- 2. Requirements never gain fabricated measured evidence -----------

test('requirements carry statements only — no invented measurement fields', () => {
  const model = deriveProjectWorkspaceModel(workspaceInput({ requirements: [], stage: 'approval' }));
  for (const requirement of model.understanding.requirements) {
    const keys = Object.keys(requirement);
    for (const forbidden of ['criteria', 'gateState', 'microSpine', 'measured', 'evidence']) {
      truthy(!keys.includes(forbidden), `requirement must not fabricate ${forbidden}`);
    }
  }
  // A requirement with no typed acceptance is presented as such: no gate
  // language anywhere in its projection.
  truthy(model.understanding.requirements.every((requirement) => !('gateState' in requirement)));
});

// ---- 3. Runs preserve exact run truth -----------------------------------

test('run history labels classify status only; every value stays verbatim', () => {
  const completed = taskRun({ id: 'run-c', prompt: 'Ship it.', status: 'completed' });
  equal(runOutcomeKind(completed.status), 'completed');
  equal(needsAttention(completed.status), false);
  const failed = taskRun({ id: 'run-f', prompt: 'Migrate.', status: 'failed' });
  equal(runOutcomeKind(failed.status), 'stopped');
  equal(needsAttention(failed.status), true);
  equal(runOutcomeKind('mystery_state'), 'unknown');
  // No fabricated acceptance language: completion of a TASK RUN is not
  // acceptance. The sentence may say "completed", never "accepted"/"verified".
  for (const status of ['completed', 'failed', 'running']) {
    const sentence = `${runOutcomeSentence(status, false)} ${runOutcomeLabel(status, false)}`.toLowerCase();
    truthy(!sentence.includes('accepted') && !sentence.includes('verified'), `outcome language must not claim acceptance: ${status}`);
  }
});

// ---- 4. Measured facts are exact projections ---------------------------

test('measured facts project record values exactly, dash when absent', () => {
  const run = taskRun({ id: 'run-x', prompt: 'p', status: 'completed' });
  const facts = measuredFactRows(run, fullReceipt);
  const bylabel = new Map(facts.map((fact) => [fact.label, fact]));
  equal(bylabel.get('Duration')?.raw, 42100, 'duration comes from the receipt latency');
  deepEqual(bylabel.get('Tokens')?.raw, [1840, 2210], 'tokens come from receipt usage');
  equal(bylabel.get('Actual cost')?.text, '$0.00412');
  equal(bylabel.get('Quality')?.text, '87%');
  const bare = taskRun({ id: 'run-bare', prompt: 'p', status: 'completed', actual_cost: null, reference_cost: null, saved_amount: null, quality_eval_score: null });
  const absent = new Map(measuredFactRows(bare, null).map((fact) => [fact.label, fact]));
  equal(absent.get('Actual cost')?.text, '—');
  equal(absent.get('Quality'), undefined, 'absent quality is omitted, not invented');
  equal(humanDuration(null), '—');
  equal(money(null), '—');
  equal(money(0), '$0.00');
});

// ---- 5. Artifacts: chip plus full hash availability --------------------

test('artifact chips abbreviate to seven characters with the full hash retained', () => {
  const rows = artifactRows(fullReceipt);
  equal(rows.length, 2);
  equal(rows[0]?.chip, 'c7d8e9f');
  equal(rows[0]?.fullHash, 'c7d8e9f0a1b2c3d4e5f6a7b8');
  equal(rows[1]?.chip, null, 'no hash means no chip — never a fake signature');
  equal(checksumChip(undefined), null);
});

// ---- 6. L3 technical receipt remains complete ---------------------------

test('the technical receipt keeps every L3 field the records carried', () => {
  const run = taskRun({ id: 'run-x', prompt: 'p', status: 'completed' });
  const lines = technicalReceiptLines(run, fullReceipt);
  const byterm = new Map(lines.map((line) => [line.term, line.value]));
  equal(byterm.get('Run ID'), 'run-x');
  equal(byterm.get('Token source'), 'provider_reported / measured');
  equal(byterm.get('TTFT'), '640 ms · measured');
  equal(byterm.get('Fallback chain'), 'fallback-a → fallback-b');
  const attempts = attemptLines(fullReceipt);
  equal(attempts.length, 2);
  equal(attempts[1]?.detail, 'qwen-coder-cli', 'executor identity passes through verbatim');
  // Every original artifact hash survives somewhere in the projection.
  const serialized = JSON.stringify({ lines, attempts, artifacts: artifactRows(fullReceipt) });
  truthy(serialized.includes('c7d8e9f0a1b2c3d4e5f6a7b8'), 'full hash still reachable in L3');
});

// ---- 7. Flagship workspace still works through the same model ----------

test('flagship derivation is untouched: verified work reaches the deliverable station', () => {
  const input = workspaceInput({
    stage: 'complete',
    blueprint: { id: 'blueprint-v8', revision: 1, status: 'approved' },
    plan: { tasks: [{ id: 'task-1', title: 'T', state: 'completed' }], orchestrations: [{ state: 'complete' }], needs: [] },
    completion: { ready: true, evidence: { tasks: [{ task_id: 'task-1', done: true, criteria: [{ id: 'c1', status: 'passed', source: 'measured', evidence: { observed: true } }] }] } },
  });
  const model = deriveProjectWorkspaceModel(input);
  equal(model.evidence.verified, true);
  equal(model.currentStation, 'deliverable');
});

// ---- 8. Outcome classification covers the real status vocabulary -------

test('every backend run status maps to exactly one honest outcome kind', () => {
  deepEqual(
    ['completed', 'failed', 'cancelled', 'timed_out', 'running', 'queued', 'pending', 'who-knows'].map((status) => runOutcomeKind(status)),
    ['completed', 'stopped', 'stopped', 'stopped', 'running', 'running', 'running', 'unknown'],
    'status vocabulary maps to honest kinds',
  );
});

// ---- 9. Execution completion is never acceptance semantics --------------

test('a completed run is operational completion — never accepted or verified', () => {
  // The RunOutcomeKind union has no 'accepted'/'verified' members at the type
  // level: acceptance semantics are unrepresentable for run outcomes.
  equal(runOutcomeKind('completed'), 'completed');
  equal(needsAttention('completed'), false);
  // The whole completed presentation vocabulary stays operational.
  for (const text of [runOutcomeLabel('completed', false), runOutcomeLabel('completed', true), runOutcomeSentence('completed', false), runOutcomeSentence('completed', true)]) {
    truthy(!/accept|verif|proven|gate/i.test(text), `completion language must stay operational: ${text}`);
  }
});

// ---- 10. Owning project context resolves at L1 or stays absent ----------

test('project context at L1 resolves from the existing project list — or stays absent', () => {
  const projects = [{ id: 'project-1', name: 'Clinic website' }];
  equal(projectLabel('project-1', projects), 'Clinic website');
  equal(projectLabel('project-unknown', projects), null, 'an unknown id never becomes an invented name');
  equal(projectLabel(null, projects), null, 'a standalone run shows no project claim');
  equal(projectLabel(undefined, []), null);
});

console.log(`V8 SUPPORTING SCREENS CONTRACT PASSED (${passed} tests)`);
