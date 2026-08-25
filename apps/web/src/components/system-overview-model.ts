import type { AnalyticsSummary, FleetOverview, TaskRun } from '../services/api';

// V10 System Overview presentation model (the surface V9 demoted from
// "Home"). The page answers two questions, in order: is TEMM able to work,
// and what needs attention. Everything here classifies ALREADY-AUTHORITATIVE
// data; no health score, no productivity score, no invented urgency.

export type ReadinessTone = 'neutral' | 'attention';

export interface OverviewAlert {
  key: string;
  text: string;
  textAr: string;
  tone: Extract<ReadinessTone, 'attention'>;
}

export interface SystemOverviewModel {
  ready: boolean;
  readyLabel: string;
  readyLabelAr: string;
  tone: ReadinessTone;
  alerts: OverviewAlert[];
  recentRuns: TaskRun[];
  usage: { monthTokens: number | null; estimatedTokens: number; avoidedCost: number | null };
  fleet: { modelsOnline: number; modelsRegistered: number; agentsReady: number; providers: number };
}

export function systemOverviewModel({
  overview,
  monthAnalytics,
  analyticsError,
  workspaceCount,
  recentRuns,
}: {
  overview: FleetOverview | null;
  monthAnalytics: AnalyticsSummary | null;
  analyticsError: boolean;
  workspaceCount: number;
  recentRuns: TaskRun[];
}): SystemOverviewModel {
  const fleetCounts = overview?.fleet_counts;
  const modelsOnline = fleetCounts?.models_online || 0;
  const agentsReady = fleetCounts?.agents_ready || 0;
  const hasExecutableRoute = modelsOnline > 0 || (agentsReady > 0 && workspaceCount > 0);

  const alerts: OverviewAlert[] = [];
  if (workspaceCount === 0) {
    alerts.push({ key: 'workspace', tone: 'attention', text: 'No approved workspace for file-based tasks', textAr: 'لا توجد مساحة عمل معتمدة لمهام الملفات' });
  }
  if (analyticsError) {
    alerts.push({ key: 'analytics', tone: 'attention', text: 'Operational metrics are unavailable', textAr: 'تعذر تحميل المقاييس التشغيلية' });
  }
  if ((fleetCounts?.models_unavailable || 0) > 0) {
    alerts.push({ key: 'models', tone: 'attention', text: `${fleetCounts?.models_unavailable} models currently unavailable`, textAr: `${fleetCounts?.models_unavailable} موديل غير متاح حاليًا` });
  }

  const monthTokens = monthAnalytics
    ? Object.values(monthAnalytics.usage_by_provenance).reduce((total, value) => total + value.input_tokens + value.output_tokens + value.cached_tokens + value.reasoning_tokens, 0)
    : null;

  return {
    ready: hasExecutableRoute,
    readyLabel: hasExecutableRoute ? 'Execution route ready' : 'Setup incomplete',
    readyLabelAr: hasExecutableRoute ? 'يوجد مسار تنفيذ جاهز' : 'الإعداد غير مكتمل',
    tone: hasExecutableRoute ? 'neutral' : 'attention',
    alerts,
    recentRuns,
    usage: {
      monthTokens,
      estimatedTokens: monthAnalytics
        ? Object.entries(monthAnalytics.usage_by_provenance).filter(([source]) => source === 'estimated').reduce((total, [, value]) => total + value.input_tokens + value.output_tokens + value.cached_tokens + value.reasoning_tokens, 0)
        : 0,
      avoidedCost: monthAnalytics ? Number(monthAnalytics.financials.estimated_avoided_cost) : null,
    },
    fleet: {
      modelsOnline,
      modelsRegistered: fleetCounts?.models_registered || 0,
      agentsReady,
      providers: fleetCounts?.providers_count || 0,
    },
  };
}
