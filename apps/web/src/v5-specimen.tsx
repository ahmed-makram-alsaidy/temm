import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource-variable/manrope';
import '@fontsource-variable/alexandria';
import '@fontsource/jetbrains-mono';
import './styles/tokens.css';
import { SCENARIOS, V5MotionLab } from './specimens/V5MotionLabSpecimen';

const params = new URLSearchParams(window.location.search);
const requested = params.get('scenario') ?? 'retry-chain';
const scenario = SCENARIOS.find((item) => item.id === requested) ?? SCENARIOS[5]!;
const requestedStep = Number(params.get('step'));
const play = ['1', 'true'].includes(params.get('play') ?? '');
const step = play && Number.isFinite(requestedStep)
  ? Math.max(0, Math.min(requestedStep, scenario.steps.length - 1))
  : scenario.steps.length - 1;
const grey = ['1', 'true'].includes(params.get('grey') ?? '');
const rtl = ['1', 'true'].includes(params.get('rtl') ?? '') || scenario.rtl === true;
const reduced = ['1', 'true'].includes(params.get('reduced') ?? '');
// Dev-only QA affordance: open a task's acceptance sheet deterministically.
const sheetTaskId = ['1', 'true'].includes(params.get('sheet') ?? '') ? 'task-2' : null;

document.documentElement.dataset.theme = 'dark';
document.documentElement.dir = rtl ? 'rtl' : 'ltr';
document.documentElement.lang = rtl ? 'ar' : 'en';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <V5MotionLab scenario={scenario} targetStep={step} grey={grey} reduced={reduced} rtl={rtl} sheetTaskId={sheetTaskId} />
  </StrictMode>,
);
