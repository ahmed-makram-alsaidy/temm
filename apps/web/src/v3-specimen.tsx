import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource-variable/manrope';
import '@fontsource-variable/alexandria';
import '@fontsource/jetbrains-mono';
import './styles/tokens.css';
import { V3WorkspaceSpecimen } from './specimens/V3WorkspaceSpecimen';
import type { V3SpecimenState } from './specimens/V3WorkspaceSpecimen';

const params = new URLSearchParams(window.location.search);
const requestedState = params.get('state');
const states: V3SpecimenState[] = ['ready', 'live', 'attention', 'verified', 'empty'];
const state = states.find((item) => item === requestedState) ?? 'ready';
const requestedTheme = params.get('theme');
const theme = requestedTheme === 'light' || requestedTheme === 'chalk' ? 'light' : 'dark';
const rtl = ['1', 'true'].includes(params.get('rtl') ?? '');
const grey = ['1', 'true'].includes(params.get('grey') ?? '');

document.documentElement.dataset.theme = theme;
document.documentElement.dir = rtl ? 'rtl' : 'ltr';
document.documentElement.lang = rtl ? 'ar' : 'en';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <V3WorkspaceSpecimen state={state} theme={theme} rtl={rtl} grey={grey} />
  </StrictMode>,
);
