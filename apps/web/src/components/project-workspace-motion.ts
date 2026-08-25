import type { GateState } from './visual-primitives';
import type { ProjectWorkspaceModel, WorkTask } from './project-workspace-model';

export const TRANSIT_CONCURRENCY_LIMIT = 3;

export type TaskMotionEvent =
  | 'task-activated'
  | 'attempt-added'
  | 'attempt-ended'
  | 'gate-evaluating'
  | 'gate-accepted'
  | 'gate-rejected'
  | 'task-accepted';

// V7 — the deliverable convergence moment. The only project-level event:
// completion became evidence-based (freeze §15). It fires on the observed
// transition alone — never on initial load, re-render, or navigation return.
export type ProjectMotionEvent = 'project-verified';

export interface TaskMotionPlan {
  transit: boolean;
  events: TaskMotionEvent[];
  arrivedAttemptIds: string[];
  settledAttemptIds: string[];
}

export interface WorkspaceMotionOptions {
  allowMotion?: boolean;
}

export interface WorkspaceMotionPlan {
  live: boolean;
  projectEvents: ProjectMotionEvent[];
  tasks: Record<string, TaskMotionPlan>;
}

const EMPTY_PLAN: TaskMotionPlan = { transit: false, events: [], arrivedAttemptIds: [], settledAttemptIds: [] };

export function emptyTaskMotionPlan(): TaskMotionPlan {
  return EMPTY_PLAN;
}

// Sustained transit is a STATE of genuinely active work, capped for calm:
// the dominant task keeps the lead and at most TRANSIT_CONCURRENCY_LIMIT
// connectors carry the travelling illumination. Every active task keeps its
// truthful active treatment whether or not it moves.
export function assignTransit(tasks: WorkTask[]): Record<string, boolean> {
  const assignment: Record<string, boolean> = {};
  let granted = 0;
  for (const task of tasks) {
    if (!task.active) continue;
    assignment[task.id] = granted < TRANSIT_CONCURRENCY_LIMIT;
    if (granted < TRANSIT_CONCURRENCY_LIMIT) granted += 1;
  }
  return assignment;
}

function gateEvent(before: GateState | null, after: GateState | null): TaskMotionEvent | null {
  if (before === after) return null;
  if (after === 'accepted') return 'gate-accepted';
  if (after === 'rejected') return 'gate-rejected';
  if (after === 'evaluating') return 'gate-evaluating';
  return null;
}

// Presentation-level diff between two authoritative V4 snapshots. It decides
// WHICH visual transition occurred; it never decides what is true. With no
// previous snapshot (initial load, remount) every historical state settles and
// only currently active truth (transit) may animate.
export function deriveMotionPlan(
  previous: ProjectWorkspaceModel | null,
  next: ProjectWorkspaceModel | null,
  options: WorkspaceMotionOptions = {},
): WorkspaceMotionPlan {
  if (!next) return { live: false, projectEvents: [], tasks: {} };
  const transit = options.allowMotion === false ? {} : assignTransit(next.work.tasks);
  if (!previous) {
    // Initial load settles all history: an already-verified project renders
    // its resting composition directly and never replays the convergence.
    const tasks: Record<string, TaskMotionPlan> = {};
    for (const task of next.work.tasks) {
      tasks[task.id] = { ...EMPTY_PLAN, transit: Boolean(transit[task.id]) };
    }
    return { live: true, projectEvents: [], tasks };
  }
  const projectEvents: ProjectMotionEvent[] = [];
  if (options.allowMotion !== false && !previous.evidence.verified && next.evidence.verified) {
    projectEvents.push('project-verified');
  }
  const previousById = new Map(previous.work.tasks.map((task) => [task.id, task]));
  const tasks: Record<string, TaskMotionPlan> = {};
  for (const task of next.work.tasks) {
    const before = previousById.get(task.id);
    if (!before) {
      // A task that was absent from the previous snapshot has no observable
      // transition; it settles into its current truthful geometry.
      tasks[task.id] = { ...EMPTY_PLAN, transit: Boolean(transit[task.id]) };
      continue;
    }
    const events: TaskMotionEvent[] = [];
    if (!before.active && task.active) events.push('task-activated');
    const beforeAttemptIds = new Set(before.attempts.map((attempt) => attempt.id));
    const arrivedAttemptIds = task.attempts
      .filter((attempt) => !beforeAttemptIds.has(attempt.id))
      .map((attempt) => attempt.id);
    if (arrivedAttemptIds.length) events.push('attempt-added');
    const beforeAttemptById = new Map(before.attempts.map((attempt) => [attempt.id, attempt]));
    const settledAttemptIds = task.attempts
      .filter((attempt) => beforeAttemptById.get(attempt.id)?.active === true && attempt.active === false)
      .map((attempt) => attempt.id);
    if (settledAttemptIds.length) events.push('attempt-ended');
    const gate = gateEvent(before.gateState, task.gateState);
    if (gate) events.push(gate);
    if (!before.accepted && task.accepted) events.push('task-accepted');
    tasks[task.id] = {
      transit: Boolean(transit[task.id]),
      events,
      arrivedAttemptIds,
      settledAttemptIds,
    };
  }
  return { live: true, projectEvents, tasks };
}

// Hidden-tab reconciliation (freeze §28): the tab observed nothing, so nothing
// may replay. The current authoritative snapshot becomes the baseline; sustained
// transit survives because it is a state, not an event.
export function settleMotionPlan(model: ProjectWorkspaceModel | null, options: WorkspaceMotionOptions = {}): WorkspaceMotionPlan {
  return deriveMotionPlan(model, model, options);
}
