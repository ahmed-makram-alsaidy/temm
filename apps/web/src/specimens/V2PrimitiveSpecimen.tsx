import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import {
  AcceptanceGate,
  AttemptHistory,
  ClosedCell,
  EvidencePackage,
  ExecutionConnector,
  ExecutionNode,
  ExecutionStation,
  FailureGeometry,
  StatusPrimitive,
  EXECUTION_STATES,
} from '../components/visual-primitives';
import type {
  ClosedCellSize,
  ConnectorTreatment,
  ExecutionNodeType,
  ExecutionState,
  FailureKind,
  GateState,
} from '../components/visual-primitives';
import './v2-primitive-specimen.css';

const params = new URLSearchParams(window.location.search);

const STATE_DETAILS: Record<ExecutionState, string> = {
  neutral: 'plain capsule / solid hairline / on spine',
  planned: 'dashed outline / branch not at gate',
  ready: 'tip cap / solid branch / short of gate',
  running: 'route glyph / live segment / in transit',
  attention: 'leading bite / hatch / interrupted branch',
  blocked: 'hatch / arrest / gap before any gate',
  retrying: 'parallel offset / retained ghost / live route',
  verifying: 'segmented gate / cross-axis emphasis',
  rejected: 'filled effect / closed gate / struck segment',
  accepted: 'open gate / continuous through-line',
  complete: 'on spine / filled object / weight step',
};

const CONNECTOR_COPY: Record<ConnectorTreatment, string> = {
  planned: 'dashed hairline; nothing measured yet',
  ready: 'solid hairline with a terminal cap',
  running: 'live segment and capability route glyph',
  retry: 'retired lane retained beside the live lane',
  blocked: 'travel arrests; the dependency gap remains',
  effect: 'a measured effect square exists on the line',
  rejected: 'effect arrived flush at a closed, struck gate',
  accepted: 'full-weight line passes the gate and rejoins',
};

const FAILURE_COPY: Record<FailureKind, { title: string; detail: string }> = {
  blocked: {
    title: 'Blocked',
    detail: 'Short run. Arrested before travel. No effect socket and no gate.',
  },
  'no-effect': {
    title: 'No Effect',
    detail: 'The lane ran to an explicitly empty effect socket. No gate can be built.',
  },
  rejected: {
    title: 'Rejected',
    detail: 'A filled effect reached evaluation, stayed flush, and the closed gate was struck.',
  },
};

const CELL_SIZES: ClosedCellSize[] = [16, 24, 40, 64];
const NODE_TYPES: ExecutionNodeType[] = ['task', 'run', 'attempt', 'effect', 'gate', 'evidence', 'convergence'];
const CONNECTORS: ConnectorTreatment[] = ['planned', 'ready', 'running', 'retry', 'blocked', 'effect', 'rejected', 'accepted'];
const GATE_STATES: GateState[] = ['dormant', 'evaluating', 'rejected', 'accepted'];
const FAILURES: FailureKind[] = ['blocked', 'no-effect', 'rejected'];

function Section({
  id,
  index,
  title,
  note,
  focus,
  children,
}: {
  id: string;
  index: string;
  title: string;
  note?: string;
  focus: string;
  children: ReactNode;
}) {
  return (
    <section className="v2-section" data-section={id} hidden={Boolean(focus && focus !== id)}>
      <header className="v2-section__header">
        <span>{index}</span>
        <h2>{title}</h2>
      </header>
      {note && <p className="v2-section__note">{note}</p>}
      {children}
    </section>
  );
}

export function V2PrimitiveSpecimen() {
  const [theme, setTheme] = useState<'dark' | 'light'>(() => params.get('theme') === 'light' ? 'light' : 'dark');
  const [greyscale, setGreyscale] = useState(() => params.get('grey') === '1');
  const [rtl, setRtl] = useState(() => params.get('rtl') === '1');
  const [reduced, setReduced] = useState(() => params.get('reduced') === '1');
  const [motionClosed, setMotionClosed] = useState(() => params.get('motion') === 'closed');
  const compact = params.get('compact') === '1';
  const focus = params.get('focus') ?? (compact ? 'compact' : '');

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = theme;
    root.dataset.reduceMotion = reduced ? 'true' : 'false';
    root.dataset.compact = compact ? 'true' : 'false';
    root.dir = rtl ? 'rtl' : 'ltr';
    root.lang = rtl ? 'ar' : 'en';
    return () => {
      delete root.dataset.compact;
    };
  }, [compact, reduced, rtl, theme]);

  return (
    <div className="v2-shell" data-greyscale={greyscale ? 'true' : 'false'}>
      <header className="v2-masthead">
        <div>
          <p className="v2-kicker">V2 · Production primitive proof</p>
          <h1>Closed Cell + Core Execution Primitives</h1>
          <p>Task → run → attempt → effect → gate → evidence → verified convergence.</p>
        </div>
        {!focus && (
          <div className="v2-controls" aria-label="Specimen controls">
            <button type="button" aria-pressed={theme === 'dark'} onClick={() => setTheme((value) => value === 'dark' ? 'light' : 'dark')}>
              {theme === 'dark' ? 'Graphite' : 'Chalk'}
            </button>
            <button type="button" aria-pressed={greyscale} onClick={() => setGreyscale((value) => !value)}>Greyscale</button>
            <button type="button" aria-pressed={rtl} onClick={() => setRtl((value) => !value)}>RTL · ع</button>
            <button type="button" aria-pressed={reduced} onClick={() => setReduced((value) => !value)}>Reduced motion</button>
          </div>
        )}
      </header>

      <main>
        <Section
          id="cell"
          index="A"
          title="Closed Cell · open and verified"
          note="The open form keeps the complete silhouette but leaves the bottom vertex unjoined. At 16px the gate rule is deliberately dropped; the spine and cell survive."
          focus={focus}
        >
          <div className="cell-sheet">
            {CELL_SIZES.map((size) => (
              <article className="cell-size" key={size}>
                <header><strong>{size}px</strong><span>{size < 20 ? 'detail dropped' : 'gate retained'}</span></header>
                <div className="cell-pair">
                  <figure><div className="mark-field"><ClosedCell size={size} state="open" /></div><figcaption>Open</figcaption></figure>
                  <figure><div className="mark-field"><ClosedCell size={size} state="closed" /></div><figcaption>Closed</figcaption></figure>
                </div>
              </article>
            ))}
          </div>
          <div className="cell-transition">
            <div>
              <p className="v2-label">Primitive-level transition</p>
              <strong>{motionClosed ? 'Measured acceptance closed the cell' : 'Work is still out'}</strong>
              <small>One user-triggered state change. No idle loop. Reduced motion renders the same final geometry immediately.</small>
            </div>
            <ClosedCell key={motionClosed ? 'closed' : 'open'} size={64} state={motionClosed ? 'closed' : 'open'} animate={motionClosed} />
            <button type="button" onClick={() => setMotionClosed((value) => !value)}>{motionClosed ? 'Reopen proof' : 'Apply measured acceptance'}</button>
          </div>
        </Section>

        <Section
          id="package"
          index="B"
          title="Three-cell evidence package"
          note="Three accepted evidence units share one uninterrupted spine. Green is local to closed, measured cells; dormant cells remain open ink."
          focus={focus}
        >
          <div className="package-grid">
            <figure><EvidencePackage size={40} verifiedCount={0} /><figcaption><strong>Dormant</strong><span>0 / 3 verified</span></figcaption></figure>
            <figure><EvidencePackage size={40} verifiedCount={2} /><figcaption><strong>Partial</strong><span>2 / 3 verified</span></figcaption></figure>
            <figure><EvidencePackage size={40} verifiedCount={3} /><figcaption><strong>Verified package</strong><span>3 / 3 measured</span></figcaption></figure>
          </div>
        </Section>

        <Section
          id="nodes"
          index="C"
          title="Seven semantic node types"
          note="Runs and attempts are intentionally lengths and offsets of line, not rounded database objects."
          focus={focus}
        >
          <div className="node-grid">
            {NODE_TYPES.map((type) => <ExecutionNode key={type} type={type} state={type === 'run' ? 'running' : type === 'gate' ? 'accepted' : type === 'convergence' ? 'complete' : 'ready'} />)}
          </div>
        </Section>

        <Section
          id="connectors"
          index="D"
          title="Connector grammar · causality without curves"
          note="Only orthogonal and 45-degree construction. Running is shown as a static active segment in V2; sustained transit remains V5."
          focus={focus}
        >
          <div className="connector-grid">
            {CONNECTORS.map((treatment) => (
              <article key={treatment}>
                <ExecutionConnector treatment={treatment} direction={rtl ? 'rtl' : 'ltr'} />
                <div><strong>{treatment}</strong><span>{CONNECTOR_COPY[treatment]}</span></div>
              </article>
            ))}
          </div>
        </Section>

        <Section
          id="attempt"
          index="E"
          title="Attempt history · recovery stays spatial"
          note="Attempt 1 remains visible after Attempt 3 succeeds. Extent is monotonic: no effect, measured rejection, accepted rejoin."
          focus={focus}
        >
          <div className="attempt-proof"><AttemptHistory direction={rtl ? 'rtl' : 'ltr'} /></div>
          <div className="comparison-answer"><strong>History retained</strong><span>Success adds a load-bearing lane; it does not erase the two failed facts.</span></div>
        </Section>

        <Section
          id="failures"
          index="F"
          title="Blocked vs No Effect vs Rejected"
          note="Three facts, three terminal geometries. The comparison remains legible when all hue is removed."
          focus={focus}
        >
          <div className="failure-grid">
            {FAILURES.map((kind) => (
              <article key={kind}>
                <FailureGeometry kind={kind} direction={rtl ? 'rtl' : 'ltr'} />
                <h3>{FAILURE_COPY[kind].title}</h3>
                <p>{FAILURE_COPY[kind].detail}</p>
              </article>
            ))}
          </div>
          <div className="failure-law">
            <span><b>Blocked</b> never produced a socket</span>
            <span><b>No Effect</b> produced an empty socket</span>
            <span><b>Rejected</b> produced an effect and a struck gate</span>
          </div>
        </Section>

        <Section
          id="status"
          index="G"
          title="Eleven semantic status primitives"
          note="Every status keeps a text label and differs through structural channels. Accepted is through a gate; Complete is merged onto a stepped spine."
          focus={focus}
        >
          <div className="status-grid">
            {EXECUTION_STATES.map((state) => <StatusPrimitive key={state} state={state} detail={STATE_DETAILS[state]} />)}
          </div>
        </Section>

        <Section
          id="gates"
          index="H"
          title="Acceptance gate · never speculative"
          note="Dormant deliberately draws no gate at all. Evaluation begins only after an effect and measured criteria exist."
          focus={focus}
        >
          <div className="gate-grid">
            {GATE_STATES.map((state) => (
              <figure key={state}>
                <AcceptanceGate state={state} direction={rtl ? 'rtl' : 'ltr'} />
                <figcaption><strong>{state}</strong><span>{state === 'dormant' ? 'boundary absent until measured' : state === 'evaluating' ? 'effect present · criteria resolving' : state === 'rejected' ? 'flush arrest · failed segment struck' : 'open · continuous through-line'}</span></figcaption>
              </figure>
            ))}
          </div>
        </Section>

        <Section
          id="stations"
          index="I"
          title="Containment primitives · one scale inside the next"
          note="This is an API proof, not the Project Workspace. The station structures provide containment and spacing without composing or duplicating a semantic spine."
          focus={focus}
        >
          <div className="station-proof">
            <ExecutionStation scale="macro" label="Lifecycle station">
              <p>Macro owns lifecycle position and contains the work station.</p>
              <ExecutionStation scale="meso" label="Work station">
                <StatusPrimitive state="verifying" detail="one task at the measured boundary" />
                <ExecutionStation scale="micro" label="Verification receipt">
                  <AcceptanceGate state="accepted" decorative />
                </ExecutionStation>
              </ExecutionStation>
            </ExecutionStation>
          </div>
        </Section>

        <Section
          id="rtl"
          index="J"
          title="RTL Arabic chain · causality preserved"
          note="The branch is rebuilt from the leading edge; it is never CSS-mirrored. The seal remains identical and Arabic labels stay horizontal."
          focus={focus}
        >
          <div className="rtl-proof" dir="rtl" lang="ar">
            <div className="rtl-proof__labels">
              <strong>مهمة</strong><strong>تشغيل</strong><strong>محاولة</strong><strong>أثر</strong><strong>بوابة</strong><strong>تحقق</strong>
            </div>
            <ExecutionConnector treatment="accepted" direction="rtl" label="مسار سببي من المهمة إلى التحقق" />
            <p>تتحرك السببية نحو بوابة القبول من اليمين إلى اليسار، بينما يبقى ترتيب التحقق واضحًا ولا تنعكس العلامة.</p>
            <div className="rtl-proof__receipt"><ClosedCell size={24} state="closed" /><span>تم القياس والقبول · <bdi dir="ltr">3/3 criteria</bdi></span></div>
          </div>
        </Section>

        <Section
          id="compact"
          index="K"
          title="Compact execution fragment"
          note="A distinct compact composition, not a desktop graph scaled down. Attempt history remains spatial and labels remain at the type floor."
          focus={focus}
        >
          <div className="compact-proof">
            <div className="compact-proof__head"><StatusPrimitive state="retrying" detail="attempt 3 at acceptance" /><ClosedCell size={24} state="open" /></div>
            <AttemptHistory compact direction={rtl ? 'rtl' : 'ltr'} />
            <div className="compact-proof__cells">
              <ClosedCell size={16} state="open" /><span>Open · 16px</span>
              <ClosedCell size={16} state="closed" /><span>Closed · 16px</span>
            </div>
          </div>
        </Section>
      </main>

      {!focus && (
        <footer className="v2-footer">
          <strong>Truth check</strong>
          <span>Green appears only on accepted gates, measured evidence, closed cells, and verified convergence.</span>
          <span>No execution travel animation is implemented in this slice.</span>
        </footer>
      )}
    </div>
  );
}
