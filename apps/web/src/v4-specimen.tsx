import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource-variable/manrope';
import '@fontsource-variable/alexandria';
import '@fontsource/jetbrains-mono';
import './styles/tokens.css';
import { V4WorkGraphSpecimen } from './specimens/V4WorkGraphSpecimen';

const params = new URLSearchParams(window.location.search);
const requestedCount = Number(params.get('count'));
const counts = [1, 6, 24, 40, 120] as const;
const taskCount = counts.find((count) => count === requestedCount) ?? 6;
const requestedTheme = params.get('theme');
const theme = requestedTheme === 'light' || requestedTheme === 'chalk' ? 'light' : 'dark';
const rtl = ['1', 'true'].includes(params.get('rtl') ?? '');
const grey = ['1', 'true'].includes(params.get('grey') ?? '');
// Dev-only QA affordance: open a task's acceptance sheet deterministically.
// The production workspace is always user-driven.
const requestedSheet = Number(params.get('sheet'));
const sheetTaskId = Number.isFinite(requestedSheet) && requestedSheet > 0
  ? `task-${String(requestedSheet).padStart(3, '0')}`
  : null;

document.documentElement.dataset.theme = theme;
document.documentElement.dir = rtl ? 'rtl' : 'ltr';
document.documentElement.lang = rtl ? 'ar' : 'en';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <V4WorkGraphSpecimen taskCount={taskCount} theme={theme} rtl={rtl} grey={grey} sheetTaskId={sheetTaskId} />
  </StrictMode>,
);
