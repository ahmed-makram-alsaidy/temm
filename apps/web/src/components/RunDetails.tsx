import React, { useEffect, useState } from 'react';
import type { TaskRun } from '../services/api';
import { api } from '../services/api';
import {
  artifactRows,
  attemptLines,
  measuredFactRows,
  runOutcomeLabel,
  runOutcomeSentence,
  technicalReceiptLines,
} from './supporting-screens-model';
import type { RawRunDetails } from './supporting-screens-model';
import './supporting-screens.css';

export const RunDetails: React.FC<{ run: TaskRun; isArabic: boolean; details?: RawRunDetails | null }> = ({ run, isArabic, details: injectedDetails }) => {
  const [fetched, setFetched] = useState<RawRunDetails | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    if (injectedDetails !== undefined) { setFetched(injectedDetails ?? null); setError(''); return; }
    setFetched(null); setError('');
    api.getRunDetails(run.id).then(setFetched).catch((reason) => setError(reason instanceof Error ? reason.message : 'Could not load run details.'));
    // Injected receipts (verification harness only) never refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [injectedDetails, run.id]);
  if (error) return <section className="surface-card failed-run-card"><AlertTriangleMark /><div><h2>{isArabic ? 'تعذر تحميل تفاصيل التشغيل' : 'Could not load run details'}</h2><p>{error}</p></div></section>;
  if (injectedDetails === undefined && !fetched) return <section className="surface-card run-detail-loading">{isArabic ? 'جارٍ تحميل الأدلة…' : 'Loading run evidence…'}</section>;
  const details = injectedDetails !== undefined ? injectedDetails : fetched;
  const attempts = attemptLines(details);
  const facts = measuredFactRows(run, details);
  const artifacts = artifactRows(details);
  const output = (details?.output ?? []).map((item) => item.content).join('');
  const truncated = (details?.output ?? []).some((item) => item.truncated);
  const events = (details?.events ?? []).slice(-30);
  return (
    <section className="temm-v8-narrative" aria-label={isArabic ? 'قصة التشغيل' : 'The run story'}>
      <header className="temm-v8-narrative-head" data-needs-attention={run.status === 'completed' ? undefined : 'true'}>
        <p className="temm-v8-kicker">{isArabic ? 'ما طُلب' : 'What was asked'}</p>
        <h2 dir="auto">{run.prompt || (isArabic ? 'لا يوجد وصف مسجّل لهذه المهمة.' : 'No recorded description exists for this task.')}</h2>
        <p className="temm-v8-narrative-verdict" data-outcome={run.status === 'completed' ? 'completed' : 'stopped'}>
          <strong>{runOutcomeLabel(run.status, isArabic)}</strong> · {runOutcomeSentence(run.status, isArabic)}
        </p>
      </header>

      <section className="temm-v8-chapter" aria-labelledby="temm-v8-execution-title">
        <h3 id="temm-v8-execution-title">{isArabic ? 'كيف نُفِّذت' : 'How it executed'}</h3>
        {attempts.length ? (
          <ul className="temm-v8-attempts">
            {attempts.map((attempt) => (
              <li key={`${attempt.number}-${attempt.headline}`}>
                <strong dir="auto">{attempt.headline}</strong>
                <span>{isArabic ? 'الحالة' : 'Status'}: {attempt.status}</span>
                <code dir="ltr" className="temm-v8-token">{attempt.detail}</code>
              </li>
            ))}
          </ul>
        ) : (
          <p className="temm-v8-absent">{isArabic ? 'لم تُسجَّل محاولات لهذا التشغيل.' : 'No attempts were recorded for this run.'}</p>
        )}
      </section>

      <section className="temm-v8-chapter" aria-labelledby="temm-v8-output-title">
        <h3 id="temm-v8-output-title">{isArabic ? 'ما أنتجته' : 'What it produced'}</h3>
        {output
          ? <pre className="temm-v8-output" dir="auto">{output}{truncated && '\n\n[truncated]'}</pre>
          : <p className="temm-v8-absent">{isArabic ? 'لا يوجد ناتج نصي محفوظ.' : 'No persisted text output.'}</p>}
        {truncated && <p className="temm-v8-note">{isArabic ? 'قلّص حد الاحتفاظ جزءًا من الناتج.' : 'Part of the output was shortened by retention limits.'}</p>}
      </section>

      <section className="temm-v8-chapter" aria-labelledby="temm-v8-facts-title">
        <h3 id="temm-v8-facts-title">{isArabic ? 'حقائق مقيسة' : 'Measured facts'}</h3>
        <dl className="temm-v8-facts">
          {facts.map((fact) => (
            <div key={fact.label}>
              <dt>{isArabic ? fact.labelAr : fact.label}{fact.note && <small> · {fact.note}</small>}</dt>
              <dd>{fact.text}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="temm-v8-chapter" aria-labelledby="temm-v8-artifacts-title">
        <h3 id="temm-v8-artifacts-title">{isArabic ? 'الأثر على القرص' : 'The effect on disk'}</h3>
        {artifacts.length ? (
          <ul className="temm-v8-artifacts">
            {artifacts.map((artifact) => (
              <li key={artifact.path}>
                <code dir="ltr" className="temm-v8-artifact-path">{artifact.path}</code>
                {artifact.chip && <code dir="ltr" className="temm-v8-chip" title={artifact.fullHash ?? undefined}>{artifact.chip}</code>}
                <span>{artifact.type ?? ''}{artifact.sizeBytes != null ? ` · ${artifact.sizeBytes.toLocaleString()} bytes` : ''}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="temm-v8-absent">{isArabic ? 'لم يُسجَّل أي ملف ناتج.' : 'No artifacts were registered.'}</p>
        )}
      </section>

      <details className="temm-v8-receipt-details">
        <summary>{isArabic ? 'الإيصال التقني الكامل' : 'Full technical receipt'}</summary>
        <dl className="temm-v8-receipt-grid">
          {technicalReceiptLines(run, details).map((line) => (
            <div key={line.term}><dt>{line.term}</dt><dd><code dir="ltr">{line.value}</code></dd></div>
          ))}
        </dl>
        <h4>{isArabic ? 'أحداث السجل' : 'Event log'}</h4>
        {events.length ? (
          <ul className="temm-v8-events">
            {events.map((event) => (
              <li key={event.event_id}>
                <code dir="ltr">{event.event_type}</code>
                <span>#{event.sequence ?? '—'} · {event.timestamp ? new Date(event.timestamp).toLocaleString() : '—'}</span>
              </li>
            ))}
          </ul>
        ) : <p className="temm-v8-absent">{isArabic ? 'لا أحداث مسجّلة.' : 'No events recorded.'}</p>}
      </details>
    </section>
  );
};

function AlertTriangleMark() {
  return <span aria-hidden="true" className="temm-v8-error-mark">!</span>;
}
