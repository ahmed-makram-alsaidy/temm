import type { TaskRun } from '../services/api';
import { LanguageProvider } from '../i18n/LanguageContext';
import { RunDetails } from '../components/RunDetails';
import { Runs } from '../components/Runs';
import type { RawRunDetails } from '../components/supporting-screens-model';

// V8 verification aid: the REAL Runs and RunDetails components rendered with
// fixed receipts so capture harnesses can prove hierarchy, RTL, and mobile
// recomposition without a backend. The product routes render these same
// components with live data (see App.tsx); nothing here ships to users.

function run(overrides: Partial<TaskRun> & Pick<TaskRun, 'id' | 'prompt' | 'status'>): TaskRun {
  return {
    task_type: 'coding',
    routing_mode: 'balanced',
    input_tokens: 1840,
    output_tokens: 2210,
    cached_tokens: 0,
    actual_cost: 0.00412,
    reference_cost: 0.0118,
    saved_amount: 0.00768,
    saving_percentage: 65.1,
    duration_ms: 4200,
    quality_eval_score: null,
    token_provenance: 'provider_reported',
    cost_provenance: 'measured',
    quality_provenance: 'unknown',
    latency_provenance: 'measured',
    measurement_metadata: {},
    financials: {},
    route_explanation: '',
    fallback_chain: [],
    log_output: '',
    result_output: '',
    created_at: '2026-08-25T09:24:00Z',
    ...overrides,
  };
}

const history: TaskRun[] = [
  run({ id: 'run-301', prompt: 'Add a retry guard to the dispatch loop so one failed pass cannot strand finished tasks.', status: 'completed', duration_ms: 42100, created_at: '2026-08-25T09:24:00Z', project_id: 'project-dispatch', selected_model_id: 'qwen3-coder', result_output: 'The retry guard is in place; three bounded passes now follow every dispatch.' }),
  run({ id: 'run-302', prompt: 'Draft the clinic intake questionnaire in Arabic and English.', status: 'running', duration_ms: 0, actual_cost: null, saved_amount: null, created_at: '2026-08-25T10:02:00Z', task_type: 'writing', selected_model_id: null, selected_agent_id: 'claude-cli' }),
  run({ id: 'run-303', prompt: 'Migrate the staging database to the new schema revision.', status: 'failed', status_reason: 'executor_exit_1', duration_ms: 18700, created_at: '2026-08-25T08:41:00Z', task_type: 'migration', selected_agent_id: 'codex-cli' }),
  run({ id: 'run-304', prompt: 'Summarise yesterday\u2019s fleet spend against the weekly allowance.', status: 'cancelled', duration_ms: 3200, actual_cost: 0.0009, saved_amount: null, created_at: '2026-08-24T18:15:00Z', task_type: 'analysis', cost_provenance: 'estimated' }),
];

const completedReceipt: RawRunDetails = {
  attempts: [
    { id: 'run-301-attempt-1', attempt_number: 1, status: 'failed', executor_type: 'cli', agent_id: 'codex-cli' },
    { id: 'run-301-attempt-2', attempt_number: 2, status: 'completed', executor_type: 'cli', agent_id: 'qwen-coder-cli' },
  ],
  output: [{ content: 'The retry guard is in place; three bounded passes now follow every dispatch.' }],
  artifacts: [
    { id: 'artifact-1', path: 'core/ai_fleet/dispatcher.py', sha256: 'c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8', artifact_type: 'patch', metadata: { size_bytes: 2148 } },
  ],
  usage: { usage: { input_tokens: 1840, output_tokens: 2210, cached_tokens: 512 }, provenance: { input_tokens: 'provider_reported', output_tokens: 'provider_reported' } },
  latency: { latency: { duration_ms: 42100, ttft_ms: 640 }, provenance: { duration_ms: 'measured', ttft_ms: 'measured' } },
  events: [
    { event_id: 'e-1', event_type: 'attempt.started', sequence: 1, timestamp: '2026-08-25T09:24:01Z' },
    { event_id: 'e-2', event_type: 'attempt.failed', sequence: 2, timestamp: '2026-08-25T09:24:31Z' },
    { event_id: 'e-3', event_type: 'attempt.started', sequence: 3, timestamp: '2026-08-25T09:25:02Z' },
    { event_id: 'e-4', event_type: 'run.completed', sequence: 4, timestamp: '2026-08-25T09:24:43Z' },
  ],
};

const failedReceipt: RawRunDetails = {
  attempts: [
    { id: 'run-303-attempt-1', attempt_number: 1, status: 'failed', executor_type: 'cli', agent_id: 'codex-cli' },
  ],
  output: [],
  artifacts: [],
  usage: { usage: { input_tokens: 900, output_tokens: 0 }, provenance: { input_tokens: 'estimated', output_tokens: 'estimated' } },
  latency: { latency: { duration_ms: 18700 }, provenance: {} },
  events: [{ event_id: 'e-9', event_type: 'run.failed', sequence: 1, timestamp: '2026-08-25T08:41:19Z' }],
};

export function V8SupportSpecimen({ surface }: { surface: string }) {
  const grey = ['1', 'true'].includes(new URLSearchParams(window.location.search).get('grey') ?? '');
  const isArabic = document.documentElement.dir === 'rtl';
  const state = new URLSearchParams(window.location.search).get('state') ?? 'completed';
  // Runs reads the product language context; the entry script pins
  // localStorage to the requested direction so the provider matches it.
  return (
    <LanguageProvider>
      {surface === 'run-details' ? <DetailsSurface grey={grey} isArabic={isArabic} state={state} /> : <RunsSurface grey={grey} />}
    </LanguageProvider>
  );
}

function DetailsSurface({ grey, isArabic, state }: { grey: boolean; isArabic: boolean; state: string }) {
  const runRow = state === 'failed' ? history[2]! : history[0]!;
  return (
    <main style={{ filter: grey ? 'grayscale(1)' : undefined, maxWidth: 980, margin: '0 auto', padding: 'var(--sp-6)' }}>
      <RunDetails run={runRow} isArabic={isArabic} details={state === 'failed' ? failedReceipt : completedReceipt} />
    </main>
  );
}

function RunsSurface({ grey }: { grey: boolean }) {
  return (
    <main style={{ filter: grey ? 'grayscale(1)' : undefined }}>
      <Runs onOpenRun={() => undefined} onNewTask={() => undefined} runs={history} loading={false} />
    </main>
  );
}
