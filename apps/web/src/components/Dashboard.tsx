import React, { useEffect, useState } from 'react';
import { ArrowUpRight, CheckCircle2, CircleDollarSign, Cpu } from 'lucide-react';
import type { AnalyticsSummary, FleetOverview, TaskRun } from '../services/api';
import { api } from '../services/api';
import { useLanguage } from '../i18n/LanguageContext';
import { StateNotice } from './StateNotice';
import { systemOverviewModel } from './system-overview-model';

interface DashboardProps {
  overview: FleetOverview | null;
  onNavigate: (tab: string) => void;
  onLaunchTask: (prompt: string, mode: string) => void;
}

const compact = (value = 0) => new Intl.NumberFormat('en', { notation: value >= 1000 ? 'compact' : 'standard', maximumFractionDigits: 1 }).format(value);

// System overview (V10): a secondary operator surface. It answers "is TEMM
// able to work, and what needs attention" — it does not compete with the
// Projects flagship and carries no task composer.
export const Dashboard: React.FC<DashboardProps> = ({ overview, onNavigate }) => {
  const { isArabic } = useLanguage();
  const [recentRuns, setRecentRuns] = useState<TaskRun[]>([]);
  const [workspaceCount, setWorkspaceCount] = useState(0);
  const [monthAnalytics, setMonthAnalytics] = useState<AnalyticsSummary | null>(null);
  const [analyticsError, setAnalyticsError] = useState(false);

  useEffect(() => {
    const now = new Date();
    const monthStart = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1));
    Promise.all([api.listRuns(), api.listWorkspaces(), api.getAnalytics(monthStart, now)])
      .then(([runs, workspaces, month]) => { setRecentRuns(runs); setWorkspaceCount(workspaces.length); setMonthAnalytics(month); })
      .catch(() => setAnalyticsError(true));
  }, []);

  const view = systemOverviewModel({ overview, monthAnalytics, analyticsError, workspaceCount, recentRuns });

  return (
    <div className="dashboard-page home-page">
      <section className="home-welcome">
        <div>
          <h1>{isArabic ? 'نظرة النظام' : 'System overview'}</h1>
          <p>{isArabic ? 'هل يستطيع TEMM العمل الآن، وما الذي يحتاج انتباهك.ابدأ العمل من المشروعات.' : 'Whether TEMM can work right now, and what needs your attention. Start real work from Projects.'}</p>
        </div>
        <span className="system-ready" data-tone={view.tone}>● {isArabic ? view.readyLabelAr : view.readyLabel}</span>
      </section>

      <div className="home-lower-grid">
        <article className="surface-card attention-panel">
          <div className="panel-heading"><div><h2>{isArabic ? 'ما يحتاج انتباهك' : 'What needs attention'}</h2><p>{isArabic ? 'عوائق معروفة أمام التنفيذ' : 'Known blockers in front of execution'}</p></div></div>
          {view.alerts.length ? (
            <div className="alert-list">{view.alerts.map((alert) => <div key={alert.key}><span className="alert-mark" aria-hidden="true" /><span dir="auto">{isArabic ? alert.textAr : alert.text}</span></div>)}</div>
          ) : (
            <div className="all-clear"><CheckCircle2 size={20} /><strong>{isArabic ? 'لا شيء يحتاج انتباهك' : 'Nothing needs you'}</strong><span>{isArabic ? 'لا توجد عوائق معروفة أمام التنفيذ.' : 'No known blockers in front of execution.'}</span></div>
          )}
          <div className="status-actions">
            <button type="button" className="btn-secondary" onClick={() => onNavigate('fleet')}>{isArabic ? 'إدارة الأدوات' : 'Manage tools'}</button>
            {workspaceCount === 0 && <button type="button" className="btn-secondary" onClick={() => onNavigate('workspaces')}>{isArabic ? 'إضافة مساحة عمل' : 'Add workspace'}</button>}
          </div>
        </article>

        <article className="surface-card recent-panel">
          <div className="panel-heading"><div><h2>{isArabic ? 'آخر عمليات التشغيل' : 'Recent runs'}</h2><p>{isArabic ? 'آخر القرارات والنتائج المحفوظة' : 'Latest saved decisions and outcomes'}</p></div><button type="button" className="text-button" onClick={() => onNavigate('runs')}>{isArabic ? 'عرض الكل' : 'View all'} <ArrowUpRight size={12} /></button></div>
          <div className="recent-list">{view.recentRuns.slice(0, 5).map((run) => <button type="button" key={run.id} onClick={() => onNavigate('runs')}><span className="recent-copy"><strong dir="auto">{run.prompt}</strong><small><code dir="ltr">{run.selected_model_id || run.task_type}</code></small></span><span className="recent-cost">{run.actual_cost == null ? '—' : `$${run.actual_cost.toFixed(4)}`}</span></button>)}{!view.recentRuns.length && <StateNotice state="empty" title={isArabic ? 'لا توجد تشغيلات حديثة' : 'No recent runs'} detail={isArabic ? 'أول مهمة ستظهر هنا.' : 'Your first run will appear here.'} />}</div>
        </article>
      </div>

      <section className="home-metrics" aria-label={isArabic ? 'استخدام هذا الشهر' : 'This month in numbers'}>
        <article><span><Cpu size={14} /> Tokens</span><strong>{view.usage.monthTokens == null ? '—' : compact(view.usage.monthTokens)}</strong><small>{view.usage.estimatedTokens ? `${compact(view.usage.estimatedTokens)} ${isArabic ? 'تقديري' : 'estimated'}` : (isArabic ? 'مبلغ عنه أو مقاس' : 'reported or measured')}</small></article>
        <article><span><CircleDollarSign size={14} /> {isArabic ? 'تكلفة متجنبة' : 'Estimated avoided'}</span><strong>{view.usage.avoidedCost == null ? '—' : `$${view.usage.avoidedCost.toFixed(2)}`}</strong><small>{isArabic ? 'هذا الشهر · تقدير خط أساس' : 'this month · baseline estimate'}</small></article>
        <article><span>{isArabic ? 'الأدوات' : 'Fleet'}</span><strong>{view.fleet.modelsOnline}</strong><small>{view.fleet.modelsRegistered} {isArabic ? 'موديل مسجل' : 'registered models'} · {view.fleet.agentsReady} {isArabic ? 'وكيل جاهز' : 'ready agents'}</small></article>
      </section>
    </div>
  );
};
