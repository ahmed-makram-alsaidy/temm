import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource-variable/manrope';
import '@fontsource-variable/alexandria';
import '@fontsource/jetbrains-mono';
import './styles/tokens.css';
import './styles/theme.css';
import { V8SupportSpecimen } from './specimens/V8SupportSpecimen';

const params = new URLSearchParams(window.location.search);
const surface = params.get('surface') ?? 'runs';

document.documentElement.dataset.theme = params.get('theme') === 'light' ? 'light' : 'dark';
const rtl = ['1', 'true'].includes(params.get('rtl') ?? '');
// The product language provider reads this key; pin it so the specimen
// direction is deterministic for capture runs (fresh profile = empty store).
window.localStorage.setItem('ai_fleet_lang', rtl ? 'ar' : 'en');
document.documentElement.dir = rtl ? 'rtl' : 'ltr';
document.documentElement.lang = rtl ? 'ar' : 'en';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <V8SupportSpecimen surface={surface} />
  </StrictMode>,
);
