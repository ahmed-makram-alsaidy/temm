import { systemOverviewModel } from '../components/system-overview-model.ts';
import type { AnalyticsSummary, FleetOverview, TaskRun } from '../services/api.ts';

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

const overview = (counts: Partial<FleetOverview['fleet_counts']>): FleetOverview => ({
  fleet_counts: {
    models_total: 0, models_online: 0, models_unavailable: 0, agents_ready: 0,
    execution_ready: false, models_registered: 0, providers_count: 0, ...counts,
  },
} as FleetOverview);

const month = (financials: Record<string, unknown>): AnalyticsSummary => ({
  usage_by_provenance: {},
  runs: { total: 0, fallback_runs: 0, statuses: {} },
  financials,
} as unknown as AnalyticsSummary);

const run = { id: 'run-1', prompt: 'p' } as TaskRun;

test('readiness tone is operational: neutral when a route exists, attention when setup is incomplete', () => {
  const ready = systemOverviewModel({ overview: overview({ models_online: 2 }), monthAnalytics: null, analyticsError: false, workspaceCount: 0, recentRuns: [] });
  equal(ready.ready, true);
  equal(ready.tone, 'neutral');
  const notReady = systemOverviewModel({ overview: overview({}), monthAnalytics: null, analyticsError: false, workspaceCount: 0, recentRuns: [] });
  equal(notReady.ready, false);
  equal(notReady.tone, 'attention');
});

test('attention items come only from known truth — never a fabricated health score', () => {
  const view = systemOverviewModel({ overview: overview({ models_unavailable: 3 }), monthAnalytics: null, analyticsError: true, workspaceCount: 0, recentRuns: [] });
  equal(view.alerts.length, 3);
  const keys = view.alerts.map((alert) => alert.key).sort();
  equal(JSON.stringify(keys), JSON.stringify(['analytics', 'models', 'workspace']));
  const serialized = JSON.stringify(view);
  truthy(!/health[_ ]?score|productivity|quality[_ ]?score/i.test(serialized), 'no invented scores');
  for (const alert of view.alerts) equal(alert.tone, 'attention');
});

test('canonical values pass through verbatim — nothing derived beyond summation', () => {
  const monthAnalytics = month({ estimated_avoided_cost: '12.34' });
  const view = systemOverviewModel({ overview: overview({ models_online: 4, models_registered: 9, agents_ready: 2, providers_count: 3 }), monthAnalytics, analyticsError: false, workspaceCount: 1, recentRuns: [run] });
  equal(view.usage.avoidedCost, 12.34);
  equal(view.fleet.modelsOnline, 4);
  equal(view.fleet.modelsRegistered, 9);
  equal(view.fleet.agentsReady, 2);
  equal(view.fleet.providers, 3);
  equal(view.recentRuns[0]?.id, 'run-1');
});

test('the overview stays secondary: it exposes no task-launch surface', () => {
  const view = systemOverviewModel({ overview: null, monthAnalytics: null, analyticsError: false, workspaceCount: 2, recentRuns: [] });
  const serialized = JSON.stringify(view);
  truthy(!/launch|composer|prompt-input|quick-?prompts/i.test(serialized), 'no task composer concept in the model');
});

console.log(`V10 SYSTEM OVERVIEW CONTRACT PASSED (${passed} tests)`);
