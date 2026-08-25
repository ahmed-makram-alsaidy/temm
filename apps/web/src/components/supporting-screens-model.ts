import type { TaskRun } from '../services/api';

// The raw run-receipt payload exactly as `/runs/{id}/details` returns it.
// Deliberately local to these supporting screens: the V4/V6 workspace
// adapter owns TASK truth; this file only re-presents RUN receipts.
export interface RawRunDetails {
  run?: Record<string, unknown>;
  attempts?: Array<{
    id: string;
    attempt_number: number;
    status?: string | null;
    executor_type?: string | null;
    agent_id?: string | null;
    model_id?: string | null;
    provider_instance_id?: string | null;
  }>;
  events?: Array<{ event_id: string; event_type: string; sequence?: number; timestamp?: string }>;
  output?: Array<{ content?: string; truncated?: boolean }>;
  artifacts?: Array<{
    id?: string;
    path?: string;
    sha256?: string | null;
    artifact_type?: string | null;
    metadata?: { size_bytes?: number } | null;
  }>;
  usage?: {
    usage?: { input_tokens?: number | null; output_tokens?: number | null; cached_tokens?: number | null };
    provenance?: { input_tokens?: string; output_tokens?: string };
  };
  latency?: {
    latency?: { duration_ms?: number | null; ttft_ms?: number | null };
    provenance?: { duration_ms?: string; ttft_ms?: string };
  };
}

// V8 supporting screens presentation helpers. These functions translate
// ALREADY-AUTHORITATIVE run records into human sentences and stable row
// shapes. They classify status strings that the backend already produced;
// they never compute acceptance, completion, or quality, and never invent a
// value the record does not carry (absent facts render as an explicit dash).

export type RunOutcomeKind = 'completed' | 'stopped' | 'running' | 'unknown';

export function runOutcomeKind(status: string): RunOutcomeKind {
  if (status === 'completed') return 'completed';
  if (['failed', 'cancelled', 'timed_out', 'canceled'].includes(status)) return 'stopped';
  if (['running', 'queued', 'starting', 'pending'].includes(status)) return 'running';
  return 'unknown';
}

export function runOutcomeSentence(status: string, isArabic: boolean): string {
  const kind = runOutcomeKind(status);
  if (kind === 'completed') return isArabic ? 'أنتجت نتيجة مسجّلة.' : 'Produced a recorded result.';
  if (kind === 'stopped') {
    if (status === 'cancelled' || status === 'canceled') return isArabic ? 'أُوقفت قبل الاكتمال، وحُفظ إيصال الإيقاف.' : 'Stopped before it could finish; the cancellation was receipted.';
    if (status === 'timed_out') return isArabic ? 'انتهت مهلتها قبل إنتاج نتيجة صالحة.' : 'Ran out of time before producing a valid result.';
    return isArabic ? 'توقفت دون نتيجة صالحة وتحتاج مراجعة.' : 'Ended without a valid result and needs review.';
  }
  if (kind === 'running') return isArabic ? 'قيد التنفيذ الآن.' : 'Executing now.';
  return isArabic ? `حالة غير معروفة: ${status}.` : `Unrecognised state: ${status}.`;
}

export function runOutcomeLabel(status: string, isArabic: boolean): string {
  const kind = runOutcomeKind(status);
  if (kind === 'completed') return isArabic ? 'مكتملة' : 'Completed';
  if (kind === 'stopped') return status === 'cancelled' || status === 'canceled' ? (isArabic ? 'أُوقفت' : 'Stopped') : (isArabic ? 'فشلت' : 'Failed');
  if (kind === 'running') return isArabic ? 'قيد التنفيذ' : 'Running';
  return status;
}

export function needsAttention(status: string): boolean {
  return runOutcomeKind(status) === 'stopped';
}

// The owning project's human name, resolved from a list the client already
// holds (one listProjects call, never per-row). Unknown or standalone runs
// resolve to null: no name is ever invented.
export function projectLabel(projectId: string | null | undefined, projects: Array<{ id: string; name: string }>): string | null {
  if (!projectId) return null;
  return projects.find((project) => project.id === projectId)?.name ?? null;
}

export function humanDuration(ms: number | null | undefined, isArabic = false): string {
  if (ms == null) return '—';
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return isArabic ? `${ms}ms` : `${ms}ms`;
}

export function checksumChip(sha256: string | null | undefined): string | null {
  if (!sha256) return null;
  return sha256.slice(0, 7);
}

export function money(amount: number | string | null | undefined): string {
  if (amount == null || amount === '') return '—';
  if (typeof amount === 'string') return amount;
  const decimals = amount === 0 ? 2 : amount < 0.01 ? 5 : amount < 1 ? 4 : 2;
  return `$${amount.toFixed(decimals)}`;
}

export interface AttemptLine {
  number: number;
  headline: string;
  detail: string;
  status: string;
}

export function attemptLines(details: RawRunDetails | null | undefined): AttemptLine[] {
  return (details?.attempts ?? []).map((attempt) => ({
    number: attempt.attempt_number,
    headline: `#${attempt.attempt_number}${attempt.executor_type ? ` · ${attempt.executor_type}` : ''}`,
    detail: attempt.agent_id || attempt.model_id || attempt.provider_instance_id || 'unknown executor',
    status: attempt.status ?? 'unknown',
  }));
}

export interface MeasuredFactRow<T = unknown> {
  label: string;
  labelAr: string;
  raw: T;
  text: string;
  note?: string;
}

export function measuredFactRows(run: TaskRun, details: RawRunDetails | null | undefined): MeasuredFactRow[] {
  const usage = details?.usage?.usage ?? {};
  const inputTokens = typeof usage.input_tokens === 'number' ? usage.input_tokens : run.input_tokens;
  const outputTokens = typeof usage.output_tokens === 'number' ? usage.output_tokens : run.output_tokens;
  const cached = typeof usage.cached_tokens === 'number' ? usage.cached_tokens : run.cached_tokens;
  const financialActual = run.financials?.actual_cost?.amount != null
    ? `${run.financials.actual_cost.amount}${run.financials.actual_cost.currency ? ` ${run.financials.actual_cost.currency}` : ''}`
    : run.actual_cost;
  const financialReference = run.financials?.reference_cost?.amount != null
    ? `${run.financials.reference_cost.amount}${run.financials.reference_cost.currency ? ` ${run.financials.reference_cost.currency}` : ''}`
    : run.reference_cost;
  const durationMs = details?.latency?.latency?.duration_ms ?? run.duration_ms;
  const rows: MeasuredFactRow[] = [
    { label: 'Duration', labelAr: 'المدة', raw: durationMs, text: humanDuration(durationMs), note: run.latency_provenance },
    { label: 'Tokens', labelAr: 'الرموز', raw: [inputTokens, outputTokens], text: `${inputTokens.toLocaleString()} in · ${outputTokens.toLocaleString()} out${cached ? ` · ${cached.toLocaleString()} cached` : ''}`, note: run.token_provenance },
    { label: 'Actual cost', labelAr: 'التكلفة الفعلية', raw: financialActual, text: money(financialActual), note: run.cost_provenance },
    { label: 'Reference value', labelAr: 'القيمة المرجعية', raw: financialReference, text: money(financialReference) },
    { label: 'Avoided cost', labelAr: 'التكلفة المتجنَّبة', raw: run.saved_amount, text: money(run.saved_amount) },
  ];
  if (run.quality_eval_score != null) {
    rows.push({ label: 'Quality', labelAr: 'الجودة', raw: run.quality_eval_score, text: `${Math.round(run.quality_eval_score)}%`, note: run.quality_provenance });
  }
  return rows;
}

export interface ArtifactRow {
  path: string;
  type: string | null;
  chip: string | null;
  fullHash: string | null;
  sizeBytes: number | null;
}

export function artifactRows(details: RawRunDetails | null | undefined): ArtifactRow[] {
  return (details?.artifacts ?? [])
    .filter((artifact) => Boolean(artifact.path))
    .map((artifact) => ({
      path: artifact.path!,
      type: artifact.artifact_type ?? null,
      chip: checksumChip(artifact.sha256 ?? null),
      fullHash: artifact.sha256 ?? null,
      sizeBytes: artifact.metadata?.size_bytes ?? null,
    }));
}

export interface ReceiptLine {
  term: string;
  value: string;
}

// Level 3 technical receipt. Every field below already exists on the record;
// nothing is derived, rounded beyond display, or omitted.
export function technicalReceiptLines(run: TaskRun, details: RawRunDetails | null | undefined): ReceiptLine[] {
  const usageProvenance = details?.usage?.provenance ?? {};
  const latency = details?.latency?.latency ?? {};
  const latencyProvenance = details?.latency?.provenance ?? {};
  const lines: ReceiptLine[] = [
    { term: 'Run ID', value: run.id },
    { term: 'Route', value: run.routing_mode },
    { term: 'Task type', value: run.task_type },
    { term: 'Model', value: run.selected_model_id || '—' },
    { term: 'Agent', value: run.selected_agent_id || '—' },
    { term: 'Workspace', value: run.workspace_id || '—' },
    { term: 'Token source', value: `${String(usageProvenance.input_tokens ?? run.token_provenance)} / ${String(usageProvenance.output_tokens ?? run.token_provenance)}` },
    { term: 'TTFT', value: `${latency.ttft_ms ?? '—'} ms · ${latencyProvenance.ttft_ms ?? run.latency_provenance}` },
    { term: 'Value category', value: run.financials?.value?.category || 'unknown' },
  ];
  if (run.status_reason) lines.push({ term: 'Status reason', value: run.status_reason });
  if (run.fallback_chain?.length) lines.push({ term: 'Fallback chain', value: run.fallback_chain.join(' → ') });
  return lines;
}
