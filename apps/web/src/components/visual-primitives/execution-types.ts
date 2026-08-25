export const EXECUTION_STATES = [
  'neutral',
  'planned',
  'ready',
  'running',
  'attention',
  'blocked',
  'retrying',
  'verifying',
  'rejected',
  'accepted',
  'complete',
] as const;

export type ExecutionState = (typeof EXECUTION_STATES)[number];
export type ClosedCellState = 'open' | 'closed';
export type ClosedCellSize = 16 | 24 | 40 | 64 | 96 | 128;
export type Direction = 'ltr' | 'rtl';
export type GateState = 'dormant' | 'evaluating' | 'rejected' | 'accepted';
export type CriterionState = 'pending' | 'testing' | 'pass' | 'fail';
export type ConnectorTreatment =
  | 'planned'
  | 'ready'
  | 'running'
  | 'retry'
  | 'blocked'
  | 'effect'
  | 'rejected'
  | 'accepted';
export type ExecutionNodeType =
  | 'task'
  | 'run'
  | 'attempt'
  | 'effect'
  | 'gate'
  | 'evidence'
  | 'convergence';
export type FailureKind = 'blocked' | 'no-effect' | 'rejected';
export type StationScale = 'macro' | 'meso' | 'micro';
