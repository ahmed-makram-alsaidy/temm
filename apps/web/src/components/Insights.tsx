import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CircleDollarSign, Gauge, ReceiptText, ShieldCheck, Sparkles } from 'lucide-react';
import type { AnalyticsSummary, FleetOverview } from '../services/api';
import { api } from '../services/api';
import { useLanguage } from '../i18n/LanguageContext';
import { StateNotice } from './StateNotice';

interface InsightsProps { overview: FleetOverview | null }

export const Insights: React.FC<InsightsProps> = () => {
  const { isArabic } = useLanguage();
  const [tab, setTab] = useState('overview');
  const [analytics, setAnalytics] = useState<AnalyticsSummary | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const now = new Date();
    const start = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1));
    api.getAnalytics(start, now).then(setAnalytics).catch((reason) => setError(reason instanceof Error ? reason.message : 'Analytics unavailable.'));
  }, []);
  const usage = useMemo(() => {
    const result = { input: 0, output: 0, cached: 0, reasoning: 0, estimated: 0 };
    if (!analytics) return result;
    Object.entries(analytics.usage_by_provenance).forEach(([source, value]) => {
      result.input += value.input_tokens; result.output += value.output_tokens; result.cached += value.cached_tokens; result.reasoning += value.reasoning_tokens;
      if (source === 'estimated') result.estimated += value.input_tokens + value.output_tokens + value.cached_tokens + value.reasoning_tokens;
    });
    return result;
  }, [analytics]);
  const tabs = [['overview', isArabic ? 'نظرة عامة' : 'Overview'], ['cost', isArabic ? 'التكلفة' : 'Cost'], ['savings', isArabic ? 'القيمة' : 'Value'], ['tokens', 'Tokens'], ['quotas', isArabic ? 'الحصص' : 'Quotas'], ['subscriptions', isArabic ? 'الاشتراكات' : 'Subscriptions']];
  const reportedSpend = analytics ? Number(analytics.financials.provider_reported_actual_cost) : null;
  const estimatedSpend = analytics ? Number(analytics.financials.estimated_actual_cost) : null;
  const avoided = analytics ? Number(analytics.financials.estimated_avoided_cost) : null;
  const equivalent = analytics ? Number(analytics.financials.equivalent_api_value) : null;

  return <div className="product-page insights-page">
    <div className="product-page-head"><div><h1>{isArabic ? 'التحليلات' : 'Insights'}</h1><p>{isArabic ? 'بيانات تشغيلية حقيقية مع فصل القياس والتقدير والمجهول.' : 'Operational evidence with reported, estimated, and unknown values kept separate.'}</p></div></div>
    <div className="tab-strip">{tabs.map(([id, label]) => <button key={id} type="button" className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>{label}</button>)}</div>
    {error && <section className="surface-card insight-disclaimer"><AlertTriangle size={15} /><span>{error}</span></section>}
    {(tab === 'overview' || tab === 'cost' || tab === 'savings') && <section className="insight-metrics">
      <Metric icon={<ReceiptText size={15} />} label={isArabic ? 'إنفاق أبلغ عنه المزود' : 'Provider-reported spend'} value={reportedSpend == null ? '—' : `$${reportedSpend.toFixed(2)}`} detail={isArabic ? 'هذا الشهر' : 'this month'} />
      <Metric icon={<Gauge size={15} />} label={isArabic ? 'تكلفة محسوبة تقديريًا' : 'Formula-estimated cost'} value={estimatedSpend == null ? '—' : `$${estimatedSpend.toFixed(2)}`} detail={`${analytics?.financials.unknown_actual_cost_runs || 0} ${isArabic ? 'تشغيل بتكلفة مجهولة' : 'runs with unknown cost'}`} />
      <Metric icon={<CircleDollarSign size={15} />} label={isArabic ? 'تكلفة متجنبة تقديريًا' : 'Estimated avoided cost'} value={avoided == null ? '—' : `$${avoided.toFixed(2)}`} detail={isArabic ? 'فرق خط الأساس' : 'baseline equivalent difference'} />
      <Metric icon={<Sparkles size={15} />} label={isArabic ? 'قيمة API مكافئة' : 'Equivalent API value'} value={equivalent == null ? '—' : `$${equivalent.toFixed(2)}`} detail={isArabic ? 'فئة منفصلة تقديرية' : 'separate estimated category'} />
    </section>}
    {tab === 'overview' && <div className="insight-grid"><section className="surface-card insight-panel"><div className="panel-heading"><div><h2>{isArabic ? 'سلامة الأدلة' : 'Evidence health'}</h2><p>{isArabic ? 'حدود البيانات الحالية' : 'Current data boundaries'}</p></div><ShieldCheck size={18} /></div><div className="usage-stack"><div><span>Runs</span><strong>{analytics?.runs.total ?? '—'}</strong></div><div><span>Fallback runs</span><strong>{analytics?.runs.fallback_runs ?? '—'}</strong></div><div><span>Unknown cost</span><strong>{analytics?.financials.unknown_actual_cost_runs ?? '—'}</strong></div><div><span>Unknown usage observations</span><strong>{analytics?.unknown_usage_observations ?? '—'}</strong></div></div></section><section className="surface-card insight-panel"><div className="panel-heading"><div><h2>{isArabic ? 'الاستخدام هذا الشهر' : 'Usage this month'}</h2><p>{usage.estimated ? `${usage.estimated.toLocaleString()} estimated tokens` : 'Reported or measured observations'}</p></div></div><div className="usage-stack"><div><span>Input</span><strong>{usage.input.toLocaleString()}</strong></div><div><span>Output</span><strong>{usage.output.toLocaleString()}</strong></div><div><span>Cached</span><strong>{usage.cached.toLocaleString()}</strong></div><div><span>Reasoning</span><strong>{usage.reasoning.toLocaleString()}</strong></div></div></section></div>}
    {tab === 'cost' && <Breakdown title={isArabic ? 'تفاصيل التكلفة' : 'Cost by evidence'} rows={[[isArabic ? 'أبلغ عنه المزود' : 'Provider reported', reportedSpend], [isArabic ? 'محسوب تقديريًا' : 'Formula estimated', estimatedSpend]]} />}
    {tab === 'savings' && <Breakdown title={isArabic ? 'فئات القيمة' : 'Value taxonomy'} rows={[[isArabic ? 'توفير مباشر مثبت' : 'Direct saving', analytics ? Number(analytics.financials.direct_saving) : null], [isArabic ? 'تكلفة متجنبة تقديريًا' : 'Estimated avoided cost', avoided], [isArabic ? 'قيمة API مكافئة' : 'Equivalent API value', equivalent]]} />}
    {tab === 'tokens' && <Breakdown title={isArabic ? 'استخدام التوكنز' : 'Token usage'} rows={[[isArabic ? 'إدخال' : 'Input', usage.input], [isArabic ? 'إخراج' : 'Output', usage.output], [isArabic ? 'مخزنة مؤقتًا' : 'Cached', usage.cached], [isArabic ? 'استدلال' : 'Reasoning', usage.reasoning]]} currency={false} />}
    {(tab === 'quotas' || tab === 'subscriptions') && <section className="surface-card subscription-panel"><StateNotice state="unknown" title={isArabic ? 'لا توجد بيانات موثقة للعرض' : 'No verified data available'} detail={isArabic ? 'لن نعرض حصة أو اشتراكًا حتى يصل من موفر أو إعداد موثق.' : 'Quota or subscription values appear only after verified provider or user configuration.'} /></section>}
  </div>;
};

const Metric: React.FC<{ icon: React.ReactNode; label: string; value: string; detail: string }> = ({ icon, label, value, detail }) => <article className="surface-card insight-metric"><span>{icon}{label}</span><strong>{value}</strong><small>{detail}</small></article>;
const Breakdown: React.FC<{ title: string; rows: Array<[string, number | null]>; currency?: boolean }> = ({ title, rows, currency = true }) => <section className="surface-card breakdown-panel"><div className="panel-heading"><div><h2>{title}</h2></div></div><div>{rows.map(([label, value]) => <div className="breakdown-line" key={label}><span>{label}</span><strong>{value == null ? '—' : currency ? `$${value.toFixed(2)}` : value.toLocaleString()}</strong></div>)}</div></section>;
