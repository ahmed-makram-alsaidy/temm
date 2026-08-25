import React from 'react';
import { AlertTriangle, CheckCircle2, CircleHelp, Clock3, WifiOff } from 'lucide-react';

export type TruthState = 'loading' | 'empty' | 'degraded' | 'error' | 'offline' | 'stale' | 'unknown' | 'approval';

const icons = { loading: Clock3, empty: CircleHelp, degraded: AlertTriangle, error: AlertTriangle, offline: WifiOff, stale: Clock3, unknown: CircleHelp, approval: CheckCircle2 };

export const StateNotice: React.FC<{ state: TruthState; title: string; detail: string; action?: React.ReactNode }> = ({ state, title, detail, action }) => {
  const Icon = icons[state];
  const role = state === 'error' || state === 'offline' ? 'alert' : 'status';
  return <div className={`state-notice state-${state}`} role={role} aria-live={role === 'alert' ? 'assertive' : 'polite'}><Icon size={18} /><div><strong>{title}</strong><span>{detail}</span>{action}</div></div>;
};
