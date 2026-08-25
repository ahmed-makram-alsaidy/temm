import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource-variable/manrope';
import '@fontsource-variable/alexandria';
import '@fontsource/jetbrains-mono';
import './styles/tokens.css';
import { V2PrimitiveSpecimen } from './specimens/V2PrimitiveSpecimen';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <V2PrimitiveSpecimen />
  </StrictMode>,
);
