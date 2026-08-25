import {
  DEFAULT_SURFACE,
  PRIMARY_NAV,
  SYSTEM_NAV,
  initialSurface,
  surfaceIsActive,
  systemStatusTone,
} from '../components/shell-navigation.ts';

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

test('the flagship Projects surface is the default launch', () => {
  equal(DEFAULT_SURFACE, 'projects');
  equal(initialSurface(null), 'projects');
  equal(initialSurface(''), 'projects');
});

test('a remembered surface still wins over the default', () => {
  equal(initialSurface('runs'), 'runs');
  equal(initialSurface('settings'), 'settings');
  equal(initialSurface('fleet'), 'fleet');
});

test('navigation groups cover exactly the real product surfaces — nothing invented', () => {
  const ids = [...PRIMARY_NAV, ...SYSTEM_NAV].map((item) => item.id).sort();
  equal(
    JSON.stringify(ids),
    JSON.stringify(['automation', 'console', 'dashboard', 'fleet', 'insights', 'model_lab', 'projects', 'runs', 'workspaces']),
    'the nav model must match App.tsx routes one-to-one',
  );
  equal(PRIMARY_NAV[0]?.id, 'projects', 'Projects leads the primary group');
});

test('active location follows the real surface, including the nested run view', () => {
  truthy(surfaceIsActive('projects', 'projects'));
  truthy(surfaceIsActive('runs', 'runs'));
  truthy(surfaceIsActive('runs', 'run'), 'an open run detail keeps Runs as the current location');
  truthy(!surfaceIsActive('projects', 'run'));
  truthy(!surfaceIsActive('runs', 'projects'));
  truthy(!surfaceIsActive('fleet', 'model_lab'));
});

test('system status tone is operational — never acceptance green', () => {
  equal(systemStatusTone(true), 'neutral');
  equal(systemStatusTone(false), 'attention');
});

test('every navigation item carries both languages', () => {
  for (const item of [...PRIMARY_NAV, ...SYSTEM_NAV]) {
    truthy(item.en.trim() && item.ar.trim(), `missing label on ${item.id}`);
  }
});

console.log(`V9 SHELL NAVIGATION CONTRACT PASSED (${passed} tests)`);
