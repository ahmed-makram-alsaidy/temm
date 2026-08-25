import React, { useEffect, useMemo, useState } from 'react';
import { ChevronDown, Plus, Search } from 'lucide-react';
import type { TaskRun } from '../services/api';
import { api } from '../services/api';
import { useLanguage } from '../i18n/LanguageContext';
import { StateNotice } from './StateNotice';
import {
  humanDuration,
  money,
  needsAttention,
  projectLabel,
  runOutcomeKind,
  runOutcomeLabel,
  runOutcomeSentence,
} from './supporting-screens-model';
import './supporting-screens.css';

interface RunsProps { onOpenRun: (run: TaskRun) => void; onNewTask: () => void; runs?: TaskRun[]; loading?: boolean; projects?: Array<{ id: string; name: string }> }

export const Runs: React.FC<RunsProps> = ({ onOpenRun, onNewTask, runs: injectedRuns, loading: injectedLoading, projects: injectedProjects }) => {
  const { isArabic } = useLanguage();
  const [fetchedRuns, setFetchedRuns] = useState<TaskRun[]>([]);
  const [fetchedProjects, setFetchedProjects] = useState<Array<{ id: string; name: string }>>([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(injectedLoading ?? true);
  const [selected, setSelected] = useState<string[]>([]);
  const [comparison, setComparison] = useState<any>(null);
  const [comparisonError, setComparisonError] = useState('');

  useEffect(() => {
    if (injectedRuns) { setFetchedRuns(injectedRuns); setLoading(injectedLoading ?? false); return; }
    // Two list reads total for the whole screen — never one per row.
    Promise.all([api.listRuns(), api.listProjects()])
      .then(([runRows, projectRows]) => { setFetchedRuns(runRows); setFetchedProjects(projectRows); })
      .catch(console.error)
      .finally(() => setLoading(false));
    // Injected history (verification harness only) never refetches.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [injectedRuns]);

  const runs = injectedRuns ?? fetchedRuns;
  const projects = injectedProjects ?? fetchedProjects;
  const visibleRuns = useMemo(() => runs.filter((run) => [run.prompt, run.selected_model_id, run.task_type].join(' ').toLowerCase().includes(query.toLowerCase())), [runs, query]);

  return (
    <div className="product-page runs-page">
      <div className="product-page-head">
        <div><h1>{isArabic ? 'عمليات التشغيل' : 'Runs'}</h1><p>{isArabic ? 'ماذا حدث، وماذا أنتجت، وهل تحتاج إلى تدخلك.' : 'What happened, what it produced, and whether it needs you.'}</p></div>
        <button type="button" className="btn-primary" onClick={onNewTask}><Plus size={14} /> {isArabic ? 'مهمة جديدة' : 'New task'}</button>
      </div>

      <section className="surface-card runs-surface">
        <div className="runs-toolbar">
          <div className="runs-search"><Search size={15} /><input aria-label={isArabic ? 'بحث في التشغيلات' : 'Search runs'} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={isArabic ? 'ابحث في التشغيلات…' : 'Search runs…'} /></div>
          <span>{visibleRuns.length} {isArabic ? 'تشغيل' : 'runs'}</span>
          <button type="button" className="btn-secondary" disabled={selected.length < 2 || selected.length > 10} onClick={() => { setComparisonError(''); api.compareRuns(selected).then(setComparison).catch((reason) => setComparisonError(reason instanceof Error ? reason.message : 'Comparison failed.')); }}>{isArabic ? 'مقارنة' : 'Compare'} ({selected.length})</button>
        </div>

        {loading && <p className="temm-v8-resting-note">{isArabic ? 'جارٍ تحميل سجل التشغيلات…' : 'Loading the run history…'}</p>}

        {!loading && !!visibleRuns.length && (
          <ul className="temm-v8-history" aria-label={isArabic ? 'سجل التشغيلات' : 'Run history'}>
            {visibleRuns.map((run) => {
              const kind = runOutcomeKind(run.status);
              return (
                <li className="temm-v8-run-row" data-outcome={kind} key={run.id}>
                  <input
                    type="checkbox"
                    className="temm-v8-run-select"
                    checked={selected.includes(run.id)}
                    aria-label={`${isArabic ? 'اختيار' : 'Select'} ${run.prompt}`}
                    onChange={(event) => setSelected((current) => event.target.checked ? [...current, run.id] : current.filter((id) => id !== run.id))}
                  />
                  <button type="button" className="temm-v8-run-main" onClick={() => onOpenRun(run)}>
                    <i className="temm-v8-run-mark" aria-hidden="true" data-outcome={kind} />
                    <span className="temm-v8-run-story">
                      <span className="temm-v8-run-prompt" dir="auto">{run.prompt}</span>
                      <span className="temm-v8-run-sentence" data-needs-attention={needsAttention(run.status) ? 'true' : undefined}>
                        <strong>{runOutcomeLabel(run.status, isArabic)}</strong>
                        {' · '}{runOutcomeSentence(run.status, isArabic)}
                        {' · '}{new Date(run.created_at).toLocaleString(isArabic ? 'ar-EG' : 'en-US', { dateStyle: 'medium', timeStyle: 'short' })}
                        {' · '}{humanDuration(run.duration_ms, isArabic)}
                        {projectLabel(run.project_id, projects) && ' · '}
                        {projectLabel(run.project_id, projects) && <span className="temm-v8-run-project" dir="auto">{projectLabel(run.project_id, projects)}</span>}
                      </span>
                    </span>
                    <ChevronDown size={14} aria-hidden="true" className="temm-v8-open-hint" />
                  </button>
                  <details className="temm-v8-run-receipt">
                    <summary>{isArabic ? 'الإيصال التقني' : 'Technical receipt'}</summary>
                    <dl className="temm-v8-receipt-grid" dir={isArabic ? 'rtl' : 'ltr'}>
                      <div><dt>{isArabic ? 'المهمة' : 'Task type'}</dt><dd><code dir="ltr">{run.task_type}</code></dd></div>
                      <div><dt>{isArabic ? 'المسار' : 'Route'}</dt><dd><code dir="ltr">{run.routing_mode}</code></dd></div>
                      <div><dt>{isArabic ? 'المنفّذ' : 'Executor'}</dt><dd><code dir="ltr">{run.selected_agent_id || run.selected_model_id || '—'}</code></dd></div>
                      <div><dt>Run ID</dt><dd><code dir="ltr">{run.id}</code></dd></div>
                      <div><dt>{isArabic ? 'الرموز' : 'Tokens'}</dt><dd>{run.input_tokens.toLocaleString()} in · {run.output_tokens.toLocaleString()} out<small> · {run.token_provenance}</small></dd></div>
                      <div><dt>{isArabic ? 'التكلفة الفعلية' : 'Actual cost'}</dt><dd>{money(run.financials?.actual_cost?.amount ?? run.actual_cost)}<small> · {run.cost_provenance}</small></dd></div>
                      <div><dt>{isArabic ? 'القيمة المرجعية' : 'Reference value'}</dt><dd>{money(run.financials?.reference_cost?.amount ?? run.reference_cost)}</dd></div>
                      <div><dt>{isArabic ? 'التكلفة المتجنَّبة تقديريًا' : 'Estimated avoided cost'}</dt><dd>{money(run.saved_amount)}</dd></div>
                      {run.quality_eval_score != null && <div><dt>{isArabic ? 'الجودة' : 'Quality'}</dt><dd>{Math.round(run.quality_eval_score)}%<small> · {run.quality_provenance}</small></dd></div>}
                      {run.route_explanation && <div className="temm-v8-receipt-wide"><dt>{isArabic ? 'قرار التوجيه' : 'Routing decision'}</dt><dd dir="auto">{run.route_explanation}</dd></div>}
                    </dl>
                  </details>
                </li>
              );
            })}
          </ul>
        )}

        {comparisonError && <div className="run-compare-error">{comparisonError}</div>}
        {comparison && <section className="run-comparison-panel"><div className="panel-heading"><div><h2>{isArabic ? 'مقارنة الأدلة' : 'Evidence comparison'}</h2><p>{isArabic ? 'تُقارن القيم المتجانسة فقط.' : 'Only commensurable evidence is compared.'}</p></div><button type="button" className="text-button" onClick={() => setComparison(null)}>{isArabic ? 'إغلاق' : 'Close'}</button></div>{Object.entries(comparison.metrics).map(([name, metric]: [string, any]) => <div className="run-comparison-row" key={name}><div><strong>{name.replaceAll('_', ' ')}</strong><small>{metric.comparable ? metric.values[0]?.provenance : metric.reason}</small></div>{metric.values.map((item: any) => <span key={item.run_id}>{item.value ?? '—'}{item.currency ? ` ${item.currency}` : ''}</span>)}</div>)}</section>}
        {!loading && !visibleRuns.length && <StateNotice state="empty" title={isArabic ? 'لا توجد تشغيلات بعد' : 'No runs yet'} detail={isArabic ? 'شغّل أول مهمة وسيظهر سجلها هنا.' : 'Run your first task and its record will appear here.'} action={<button type="button" className="btn-secondary" onClick={onNewTask}>{isArabic ? 'ابدأ الآن' : 'Start now'}</button>} />}
      </section>
    </div>
  );
};
