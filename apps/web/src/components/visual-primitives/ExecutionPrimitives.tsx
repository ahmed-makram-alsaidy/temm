import type { CSSProperties, ReactNode } from 'react';
import type {
  ClosedCellSize,
  ClosedCellState,
  ConnectorTreatment,
  CriterionState,
  Direction,
  ExecutionNodeType,
  ExecutionState,
  FailureKind,
  GateState,
  StationScale,
} from './execution-types';
import './execution-primitives.css';
import './execution-motion.css';

const CELL = {
  spine: 'M12 0 L12 24',
  open: 'M12 4 L19 11 L19 15 L14.5 19.5 M12 4 L5 11 L5 15 L9.5 19.5',
  upper: 'M12 4 L19 11 L19 15 M12 4 L5 11 L5 15',
  lower: 'M19 15 L12 22 L5 15',
  gate: 'M5 15 L19 15',
} as const;

// Grid-unit weights validated at their rendered sizes. They follow the
// approved 0.85 + 16/size curve, then receive the optical corrections from V1.
const CELL_WEIGHTS: Record<ClosedCellSize, number> = {
  16: 1.85,
  24: 1.52,
  40: 1.25,
  64: 1.1,
  96: 1.02,
  128: 0.98,
};

// Fixed SVG construction spaces. Consumers resize the SVG; viewBox scaling
// keeps these semantic points aligned instead of recomputing pixel geometry.
const GATE_LAYOUT = {
  width: 140,
  minHeight: 76,
  gateLead: 86,
  effectLead: 60,
  segmentWidth: 12,
  segmentHeight: 14,
  segmentGap: 5,
  frameInset: 7,
} as const;
const CONNECTOR_LAYOUT = { width: 148, height: 46, axisY: 23 } as const;
const FAILURE_LAYOUT = { width: 220, height: 84, axisY: 42 } as const;
const ATTEMPT_LAYOUT = {
  full: { width: 600, height: 220, start: 116, noEffect: 338, gate: 448, spine: 564, rows: [50, 112, 174] },
  compact: { width: 340, height: 206, start: 70, noEffect: 196, gate: 248, spine: 316, rows: [48, 105, 162] },
} as const;
const MICRO_SPINE_LAYOUT = { width: 124, height: 64, axisY: 32, effect: 46, gate: 86, spine: 116 } as const;

const STATE_LABELS: Record<ExecutionState, string> = {
  neutral: 'Neutral',
  planned: 'Planned',
  ready: 'Ready',
  running: 'Running',
  attention: 'Needs attention',
  blocked: 'Blocked',
  retrying: 'Retrying',
  verifying: 'Verifying',
  rejected: 'Not accepted',
  accepted: 'Accepted - measured',
  complete: 'Complete',
};

const NODE_LABELS: Record<ExecutionNodeType, string> = {
  task: 'Task',
  run: 'Run',
  attempt: 'Attempt',
  effect: 'Effect',
  gate: 'Gate',
  evidence: 'Evidence',
  convergence: 'Verified output',
};

const xFromLead = (lead: number, width: number, direction: Direction) =>
  direction === 'rtl' ? width - lead : lead;

const line = (start: number, end: number, y: number, width: number, direction: Direction) =>
  `M${xFromLead(start, width, direction)} ${y} L${xFromLead(end, width, direction)} ${y}`;

interface GraphicProps {
  label?: string;
  decorative?: boolean;
  className?: string;
}

interface ClosedCellProps extends GraphicProps {
  size?: ClosedCellSize;
  state: ClosedCellState;
  animate?: boolean;
}

export function ClosedCell({
  size = 24,
  state,
  animate = false,
  label,
  decorative = false,
  className = '',
}: ClosedCellProps) {
  const weight = CELL_WEIGHTS[size];
  const closed = state === 'closed';
  const style = { '--temm-cell-weight': weight } as CSSProperties;

  return (
    <svg
      className={`temm-closed-cell ${className}`.trim()}
      data-state={state}
      data-animate={animate ? 'true' : 'false'}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      style={style}
      role={decorative ? undefined : 'img'}
      aria-hidden={decorative || undefined}
      aria-label={decorative ? undefined : label ?? `${closed ? 'Closed' : 'Open'} verification cell`}
      focusable="false"
    >
      <path className="temm-cell__spine" d={CELL.spine} />
      {closed ? (
        <>
          <path className="temm-cell__body" d={CELL.upper} />
          <path className="temm-cell__body temm-cell__lower" d={CELL.lower} />
          {size >= 20 && <path className="temm-cell__gate" d={CELL.gate} />}
        </>
      ) : (
        <path className="temm-cell__body" d={CELL.open} />
      )}
    </svg>
  );
}

interface EvidencePackageProps extends GraphicProps {
  size?: 40 | 64;
  verifiedCount: 0 | 1 | 2 | 3;
}

export function EvidencePackage({
  size = 40,
  verifiedCount,
  label,
  decorative = false,
  className = '',
}: EvidencePackageProps) {
  const weight = 0.85 + 16 / size;
  const style = { '--temm-cell-weight': weight } as CSSProperties;
  const height = Math.round((size * 60) / 24);

  return (
    <svg
      className={`temm-evidence-package ${className}`.trim()}
      data-verified-count={verifiedCount}
      width={size}
      height={height}
      viewBox="0 0 24 60"
      style={style}
      role={decorative ? undefined : 'img'}
      aria-hidden={decorative || undefined}
      aria-label={decorative ? undefined : label ?? `${verifiedCount} of 3 evidence cells verified`}
      focusable="false"
    >
      <path className="temm-cell__spine" d="M12 0 L12 60" />
      {[0, 18, 36].map((offset, index) => {
        const closed = index < verifiedCount;
        return (
          <g key={offset} data-state={closed ? 'closed' : 'open'} transform={`translate(0 ${offset})`}>
            {closed ? (
              <>
                <path className="temm-cell__body" d={`${CELL.upper} ${CELL.lower}`} />
                <path className="temm-cell__gate" d={CELL.gate} />
              </>
            ) : (
              <path className="temm-cell__body" d={CELL.open} />
            )}
          </g>
        );
      })}
    </svg>
  );
}

const criteriaForState = (state: GateState): CriterionState[] => {
  if (state === 'evaluating') return ['pass', 'testing', 'pending'];
  if (state === 'rejected') return ['pass', 'fail', 'pending'];
  if (state === 'accepted') return ['pass', 'pass', 'pass'];
  return [];
};

interface AcceptanceGateProps extends GraphicProps {
  state: GateState;
  criteria?: CriterionState[];
  direction?: Direction;
  animate?: boolean;
}

export function AcceptanceGate({
  state,
  criteria = criteriaForState(state),
  direction = 'ltr',
  animate = false,
  label,
  decorative = false,
  className = '',
}: AcceptanceGateProps) {
  const width = GATE_LAYOUT.width;
  const innerHeight = criteria.length
    ? criteria.length * GATE_LAYOUT.segmentHeight + (criteria.length - 1) * GATE_LAYOUT.segmentGap
    : 0;
  const height = Math.max(GATE_LAYOUT.minHeight, innerHeight + GATE_LAYOUT.frameInset * 2 + 10);
  const branchY = height / 2;
  const gateLead = GATE_LAYOUT.gateLead;
  const gateX = xFromLead(gateLead, width, direction);
  const effectX = xFromLead(GATE_LAYOUT.effectLead, width, direction);
  const segmentStart = (height - innerHeight) / 2;
  const accepted = state === 'accepted';
  const measured = state !== 'dormant';

  return (
    <svg
      className={`temm-gate temm-directional ${className}`.trim()}
      data-state={state}
      data-animate={animate ? 'true' : 'false'}
      data-direction={direction}
      viewBox={`0 0 ${width} ${height}`}
      role={decorative ? undefined : 'img'}
      aria-hidden={decorative || undefined}
      aria-label={decorative ? undefined : label ?? `Acceptance gate: ${state}`}
      focusable="false"
    >
      <path
        className="temm-gate__branch"
        d={line(8, measured ? gateLead - 8 : 62, branchY, width, direction)}
      />
      {!measured && (
        <path
          className="temm-gate__dormant-cap"
          d={`M${xFromLead(62, width, direction)} ${branchY - 7} V${branchY + 7}`}
        />
      )}
      {measured && (
        <>
          <rect className="temm-gate__effect" x={effectX - 5} y={branchY - 5} width="10" height="10" />
          <path className="temm-gate__frame" d={`M${gateX - 10} ${GATE_LAYOUT.frameInset} V${height - GATE_LAYOUT.frameInset} M${gateX + 10} ${GATE_LAYOUT.frameInset} V${height - GATE_LAYOUT.frameInset}`} />
          {criteria.map((criterion, index) => {
            const y = segmentStart + index * (GATE_LAYOUT.segmentHeight + GATE_LAYOUT.segmentGap);
            return (
            <g key={`${criterion}-${index}`}>
              <rect
                className="temm-gate__segment"
                data-result={criterion}
                x={gateX - GATE_LAYOUT.segmentWidth / 2}
                y={y}
                width={GATE_LAYOUT.segmentWidth}
                height={GATE_LAYOUT.segmentHeight}
              />
              {criterion === 'fail' && (
                <path
                  className="temm-gate__strike"
                  d={`M${gateX - 5} ${y + GATE_LAYOUT.segmentHeight - 1} L${gateX + 5} ${y + 1}`}
                />
              )}
            </g>
            );
          })}
          {accepted && (
            <path
              className="temm-gate__through"
              d={line(gateLead - 8, 132, branchY, width, direction)}
            />
          )}
        </>
      )}
    </svg>
  );
}

interface ConnectorProps extends GraphicProps {
  treatment: ConnectorTreatment;
  direction?: Direction;
  transit?: boolean;
}

export function ExecutionConnector({
  treatment,
  direction = 'ltr',
  transit = false,
  label,
  decorative = false,
  className = '',
}: ConnectorProps) {
  const width = CONNECTOR_LAYOUT.width;
  const y = CONNECTOR_LAYOUT.axisY;
  const x = (lead: number) => xFromLead(lead, width, direction);
  let geometry: ReactNode;

  if (treatment === 'planned') {
    geometry = <path className="temm-connector__main" d={line(8, 132, y, width, direction)} />;
  } else if (treatment === 'ready') {
    geometry = (
      <>
        <path className="temm-connector__main" d={line(8, 128, y, width, direction)} />
        <path className="temm-connector__cap" d={`M${x(128)} 16 V30`} />
      </>
    );
  } else if (treatment === 'running') {
    geometry = (
      <>
        <path className="temm-connector__main" d={line(8, 132, y, width, direction)} />
        <path className="temm-connector__active" d={line(86, 118, y, width, direction)} />
        <path className="temm-connector__route" d={`M${x(124)} 15 L${x(132)} 23 L${x(124)} 31`} />
      </>
    );
  } else if (treatment === 'retry') {
    geometry = (
      <>
        <path className="temm-connector__ghost" d={line(8, 104, 15, width, direction)} />
        <path className="temm-connector__main" d={line(8, 132, 31, width, direction)} />
        <path className="temm-connector__tick" d={`M${x(34)} 10 V20 M${x(50)} 26 V36`} />
        <path className="temm-connector__route" d={`M${x(124)} 23 L${x(132)} 31 L${x(124)} 39`} />
      </>
    );
  } else if (treatment === 'blocked') {
    geometry = (
      <>
        <path className="temm-connector__main" d={line(8, 88, y, width, direction)} />
        <path className="temm-connector__dependency" d={line(106, 134, y, width, direction)} />
      </>
    );
  } else if (treatment === 'effect') {
    geometry = (
      <>
        <path className="temm-connector__main" d={line(8, 132, y, width, direction)} />
        <rect className="temm-connector__effect" x={x(92) - 5} y="18" width="10" height="10" />
      </>
    );
  } else if (treatment === 'rejected') {
    geometry = (
      <>
        <path className="temm-connector__main" d={line(8, 112, y, width, direction)} />
        <rect className="temm-connector__effect" x={x(92) - 5} y="18" width="10" height="10" />
        <path className="temm-connector__closed-gate" d={`M${x(112)} 8 V38`} />
        <path className="temm-connector__strike" d={`M${x(106)} 34 L${x(118)} 12`} />
      </>
    );
  } else {
    geometry = (
      <>
        <path
          className="temm-connector__main"
          d={`M${x(8)} ${y} L${x(112)} ${y} L${x(124)} 11 L${x(140)} 11`}
        />
        <path className="temm-connector__spine" d={`M${x(140)} 4 V42`} />
        <path className="temm-connector__open-gate" d={`M${x(112)} 7 V16 M${x(112)} 30 V39`} />
      </>
    );
  }

  // Sustained transit travels the live branch toward the gate. It exists only
  // while the run is genuinely active: the path unmounts with the state, so
  // the motion stops the moment authoritative truth stops.
  const transitLead: { from: number; to: number; y: number } | null =
    transit && treatment === 'running' ? { from: 8, to: 132, y } :
    transit && treatment === 'retry' ? { from: 8, to: 132, y: 31 } :
    null;

  return (
    <svg
      className={`temm-connector temm-directional ${className}`.trim()}
      data-treatment={treatment}
      data-direction={direction}
      data-transit={transitLead ? 'true' : undefined}
      viewBox={`0 0 ${width} ${CONNECTOR_LAYOUT.height}`}
      role={decorative ? undefined : 'img'}
      aria-hidden={decorative || undefined}
      aria-label={decorative ? undefined : label ?? `${treatment} connector`}
      focusable="false"
    >
      {geometry}
      {transitLead && (
        <path
          className="temm-connector__transit"
          pathLength={100}
          d={line(transitLead.from, transitLead.to, transitLead.y, width, direction)}
        />
      )}
    </svg>
  );
}

interface FailureGeometryProps extends GraphicProps {
  kind: FailureKind;
  direction?: Direction;
}

interface MicroSpineProps extends GraphicProps {
  state: GateState;
  criteria: CriterionState[];
  direction?: Direction;
}

// The verification receipt at reading size (freeze §3.3): one branch segment,
// the measured effect, one gate, its criterion segments — one task's proof in
// isolation. Rendered only for measured criteria; the caller owns that law.
export function MicroSpine({
  state,
  criteria,
  direction = 'ltr',
  label,
  decorative = false,
  className = '',
}: MicroSpineProps) {
  const { width, height, axisY, effect, gate, spine } = MICRO_SPINE_LAYOUT;
  const x = (lead: number) => xFromLead(lead, width, direction);
  const accepted = state === 'accepted';
  const rejected = state === 'rejected';
  const segmentCount = Math.max(1, Math.min(criteria.length || 1, 6));
  const slotSpan = 24;
  const firstSegment = gate - slotSpan / 2;
  const step = slotSpan / (segmentCount - 1 || 1);
  const branchEnd = accepted ? spine : rejected ? gate : gate - 6;

  return (
    <svg
      className={`temm-micro-spine temm-directional ${className}`.trim()}
      data-state={state}
      data-direction={direction}
      viewBox={`0 0 ${width} ${height}`}
      role={decorative ? undefined : 'img'}
      aria-hidden={decorative || undefined}
      aria-label={decorative ? undefined : label ?? `Verification receipt: ${state}, ${criteria.length} measured criteria`}
      focusable="false"
    >
      <path className="temm-micro-spine__branch" d={line(6, branchEnd, axisY, width, direction)} />
      <rect
        className="temm-micro-spine__effect"
        x={x(effect) - 5}
        y={axisY - 5}
        width="10"
        height="10"
      />
      {accepted ? (
        <path
          className="temm-micro-spine__open-gate"
          d={`M${x(gate)} ${axisY - 12} V${axisY - 4} M${x(gate)} ${axisY + 4} V${axisY + 12}`}
        />
      ) : (
        <path
          className="temm-micro-spine__jamb"
          d={`M${x(gate)} ${axisY - 13} V${axisY + 13}`}
        />
      )}
      {criteria.slice(0, 6).map((criterion, index) => {
        const cx = x(firstSegment + (segmentCount > 1 ? index * step : slotSpan / 2));
        return (
          <g key={`${criterion}-${index}`}>
            <path
              className="temm-micro-spine__segment"
              data-result={criterion}
              d={`M${cx} ${axisY - 6} V${axisY + 6}`}
            />
            {criterion === 'fail' && (
              <path
                className="temm-micro-spine__strike"
                d={`M${cx - 4} ${axisY + 5} L${cx + 4} ${axisY - 5}`}
              />
            )}
          </g>
        );
      })}
      {accepted && (
        <>
          <path className="temm-micro-spine__through" d={line(gate, spine - 4, axisY, width, direction)} />
          <path className="temm-micro-spine__rejoin" d={`M${x(spine)} ${axisY - 18} V${axisY + 18}`} />
        </>
      )}
    </svg>
  );
}export function FailureGeometry({
  kind,
  direction = 'ltr',
  label,
  decorative = false,
  className = '',
}: FailureGeometryProps) {
  const width = FAILURE_LAYOUT.width;
  const y = FAILURE_LAYOUT.axisY;
  const x = (lead: number) => xFromLead(lead, width, direction);

  return (
    <svg
      className={`temm-failure temm-directional ${className}`.trim()}
      data-kind={kind}
      data-direction={direction}
      viewBox={`0 0 ${width} ${FAILURE_LAYOUT.height}`}
      role={decorative ? undefined : 'img'}
      aria-hidden={decorative || undefined}
      aria-label={decorative ? undefined : label ?? `${kind} execution outcome`}
      focusable="false"
    >
      <rect className="temm-failure__task" x={x(22) - 12} y="31" width="24" height="22" rx="11" />
      {kind === 'blocked' && (
        <>
          <path className="temm-failure__line" d={line(34, 112, y, width, direction)} />
          <path className="temm-failure__dependency" d={line(136, 190, y, width, direction)} />
        </>
      )}
      {kind === 'no-effect' && (
        <>
          <path className="temm-failure__line" d={line(34, 164, y, width, direction)} />
          <rect className="temm-failure__empty-effect" x={x(176) - 8} y="34" width="16" height="16" />
          <path className="temm-failure__vacancy" d={line(184, 198, y, width, direction)} />
        </>
      )}
      {kind === 'rejected' && (
        <>
          <path className="temm-failure__line" d={line(34, 182, y, width, direction)} />
          <rect className="temm-failure__effect" x={x(160) - 7} y="35" width="14" height="14" />
          <path className="temm-failure__gate" d={`M${x(182)} 17 V67`} />
          <path className="temm-failure__strike" d={`M${x(174)} 58 L${x(190)} 26`} />
        </>
      )}
    </svg>
  );
}

interface AttemptHistoryProps extends GraphicProps {
  direction?: Direction;
  compact?: boolean;
}

export function AttemptHistory({
  direction = 'ltr',
  compact = false,
  label,
  decorative = false,
  className = '',
}: AttemptHistoryProps) {
  const layout = compact ? ATTEMPT_LAYOUT.compact : ATTEMPT_LAYOUT.full;
  const { width, height, start, noEffect, gate, spine, rows } = layout;
  const x = (lead: number) => xFromLead(lead, width, direction);
  const textX = x(8);
  const textAnchor = direction === 'rtl' ? 'end' : 'start';

  return (
    <svg
      className={`temm-attempt-history temm-directional ${className}`.trim()}
      data-compact={compact ? 'true' : 'false'}
      data-direction={direction}
      viewBox={`0 0 ${width} ${height}`}
      role={decorative ? undefined : 'img'}
      aria-hidden={decorative || undefined}
      aria-label={decorative ? undefined : label ?? 'Three retained attempts: no effect, rejected, then accepted'}
      focusable="false"
    >
      <text className="temm-attempt-history__label" x={textX} y={rows[0] - 17} textAnchor={textAnchor}>Attempt 1 - no effect</text>
      <path className="temm-attempt-history__ghost" d={line(start, noEffect - 12, rows[0], width, direction)} />
      <rect className="temm-attempt-history__empty" x={x(noEffect) - 8} y={rows[0] - 8} width="16" height="16" />
      <path className="temm-attempt-history__vacancy" d={line(noEffect + 10, noEffect + 34, rows[0], width, direction)} />

      <text className="temm-attempt-history__label" x={textX} y={rows[1] - 17} textAnchor={textAnchor}>Attempt 2 - rejected</text>
      <path className="temm-attempt-history__ghost" d={line(start, gate - 8, rows[1], width, direction)} />
      <rect className="temm-attempt-history__effect" x={x(gate - 28) - 7} y={rows[1] - 7} width="14" height="14" />
      <path className="temm-attempt-history__gate" d={`M${x(gate)} ${rows[1] - 23} V${rows[1] + 23}`} />
      <path className="temm-attempt-history__strike" d={`M${x(gate - 8)} ${rows[1] + 16} L${x(gate + 8)} ${rows[1] - 16}`} />

      <text className="temm-attempt-history__label" x={textX} y={rows[2] - 17} textAnchor={textAnchor}>Attempt 3 - accepted</text>
      <path
        className="temm-attempt-history__accepted"
        d={`M${x(start)} ${rows[2]} L${x(gate)} ${rows[2]} L${x(gate + 18)} ${rows[2]} L${x(spine - 16)} ${rows[2]} L${x(spine)} ${rows[2] + 16}`}
      />
      <rect className="temm-attempt-history__effect" data-accepted="true" x={x(gate - 28) - 7} y={rows[2] - 7} width="14" height="14" />
      <path className="temm-attempt-history__open-gate" d={`M${x(gate)} ${rows[2] - 24} V${rows[2] - 8} M${x(gate)} ${rows[2] + 8} V${rows[2] + 24}`} />
      <path className="temm-attempt-history__spine" d={`M${x(spine)} ${rows[2] - 10} V${height - 5}`} />
      {[0, 1, 2].map((index) => (
        <path
          key={index}
          className="temm-attempt-history__tick"
          d={`M${x(start + 18 + index * 12)} ${rows[index] - 5} V${rows[index] + 5}`}
        />
      ))}
    </svg>
  );
}

function StatusGlyph({ state }: { state: ExecutionState }) {
  return (
    <svg className="temm-status__glyph" data-state={state} viewBox="0 0 72 34" aria-hidden="true" focusable="false">
      {state === 'neutral' && <rect className="sg-capsule" x="10" y="9" width="32" height="16" rx="8" />}
      {state === 'planned' && <><rect className="sg-capsule" x="8" y="5" width="28" height="14" rx="7" /><path className="sg-line" d="M36 12 H64" /></>}
      {state === 'ready' && <><rect className="sg-capsule" x="8" y="10" width="28" height="14" rx="7" /><path className="sg-line" d="M36 17 H62" /><path className="sg-cap" d="M62 11 V23" /></>}
      {state === 'running' && <><rect className="sg-capsule" x="6" y="10" width="28" height="14" rx="7" /><path className="sg-line" d="M34 17 H64" /><path className="sg-live" d="M43 17 H58" /><path className="sg-route" d="M57 10 L64 17 L57 24" /></>}
      {state === 'attention' && <><rect className="sg-capsule" x="8" y="8" width="30" height="18" rx="9" /><path className="sg-bite-cut" d="M7 11 L13 17 L7 23 Z" /><path className="sg-hatch" d="M15 9 L10 14 M22 9 L11 20 M29 9 L15 23" /><path className="sg-line" d="M38 17 H50 M58 17 H66" /></>}
      {state === 'blocked' && <><rect className="sg-capsule" x="6" y="10" width="28" height="14" rx="7" /><path className="sg-hatch" d="M13 11 L8 16 M21 11 L10 22 M29 11 L20 23" /><path className="sg-line" d="M34 17 H50" /><path className="sg-ghost" d="M59 17 H68" /></>}
      {state === 'retrying' && <><rect className="sg-capsule" x="5" y="10" width="26" height="14" rx="7" /><path className="sg-ghost" d="M31 12 H57" /><path className="sg-line" d="M31 22 H66" /><path className="sg-route" d="M59 16 L66 22 L59 28" /></>}
      {state === 'verifying' && <><rect className="sg-capsule" x="4" y="10" width="24" height="14" rx="7" /><path className="sg-line" d="M28 17 H42" /><rect className="sg-segment" x="44" y="3" width="8" height="8" /><rect className="sg-segment" data-active="true" x="44" y="13" width="8" height="8" /><rect className="sg-segment" x="44" y="23" width="8" height="8" /></>}
      {state === 'rejected' && <><path className="sg-line" d="M6 17 H48" /><rect className="sg-effect" x="32" y="12" width="10" height="10" /><path className="sg-gate" d="M49 3 V31" /><path className="sg-strike" d="M43 27 L55 7" /></>}
      {state === 'accepted' && <><path className="sg-line" d="M5 17 H67" /><rect className="sg-effect" x="27" y="12" width="10" height="10" /><path className="sg-open-gate" d="M47 3 V11 M47 23 V31" /></>}
      {state === 'complete' && <><path className="sg-spine sg-spine--thin" d="M36 1 V12" /><rect className="sg-complete" x="23" y="10" width="26" height="14" rx="7" /><path className="sg-spine sg-spine--thick" d="M36 24 V33" /></>}
    </svg>
  );
}

interface StatusPrimitiveProps {
  state: ExecutionState;
  label?: string;
  detail?: string;
  className?: string;
}

export function StatusPrimitive({
  state,
  label = STATE_LABELS[state],
  detail,
  className = '',
}: StatusPrimitiveProps) {
  return (
    <span className={`temm-status ${className}`.trim()} data-state={state}>
      <StatusGlyph state={state} />
      <span className="temm-status__copy">
        <strong>{label}</strong>
        {detail && <small>{detail}</small>}
      </span>
    </span>
  );
}

interface ExecutionNodeProps extends GraphicProps {
  type: ExecutionNodeType;
  state?: ExecutionState;
  caption?: string;
}

export function ExecutionNode({
  type,
  state = type === 'convergence' ? 'complete' : 'neutral',
  caption = NODE_LABELS[type],
  className = '',
}: ExecutionNodeProps) {
  let graphic: ReactNode;

  if (type === 'gate') {
    const gateState: GateState = state === 'verifying'
      ? 'evaluating'
      : state === 'rejected'
        ? 'rejected'
        : state === 'accepted' || state === 'complete'
          ? 'accepted'
          : 'dormant';
    graphic = <AcceptanceGate state={gateState} decorative />;
  } else if (type === 'convergence') {
    const cellState: ClosedCellState = state === 'accepted' || state === 'complete' ? 'closed' : 'open';
    graphic = <ClosedCell size={40} state={cellState} decorative />;
  } else {
    graphic = (
      <svg className="temm-node__graphic" data-type={type} data-state={state} viewBox="0 0 112 64" aria-hidden="true" focusable="false">
        {type === 'task' && <><path className="ng-line" d="M8 32 H27 M85 32 H104" /><rect className="ng-task" x="27" y="20" width="58" height="24" rx="12" /></>}
        {type === 'run' && <><path className="ng-run" d="M8 32 H104" /><path className="ng-tick" d="M32 26 V38 M80 26 V38" /></>}
        {type === 'attempt' && <><path className="ng-ghost" d="M8 23 H78" /><path className="ng-run" d="M8 41 H104" /><path className="ng-tick" d="M28 17 V29 M44 35 V47" /></>}
        {type === 'effect' && <><path className="ng-line" d="M8 32 H104" /><rect className="ng-effect" x="49" y="25" width="14" height="14" /></>}
        {type === 'evidence' && <><path className="ng-line" d="M8 32 H104" /><rect className="ng-effect" data-evidence="true" x="25" y="25" width="14" height="14" /><path className="ng-measure" d="M52 21 H92 M52 32 H84 M52 43 H74" /></>}
      </svg>
    );
  }

  return (
    <figure className={`temm-node ${className}`.trim()} data-type={type} data-state={state}>
      <div className="temm-node__stage" role="img" aria-label={`${caption}: ${state}`}>{graphic}</div>
      <figcaption>{caption}</figcaption>
    </figure>
  );
}

interface StationPrimitiveProps {
  scale: StationScale;
  label: string;
  children: ReactNode;
  className?: string;
}

export function ExecutionStation({ scale, label, children, className = '' }: StationPrimitiveProps) {
  return (
    <section className={`temm-station temm-station--${scale} ${className}`.trim()} data-scale={scale}>
      <header className="temm-station__header">
        <span>{scale}</span>
        <strong>{label}</strong>
      </header>
      <div className="temm-station__body">{children}</div>
    </section>
  );
}
