import React, { useEffect, useRef, useState } from 'react';
import { FitAddon } from '@xterm/addon-fit';
import { Terminal } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';

export type TerminalConnectionState = 'connecting' | 'connected' | 'reconnecting' | 'disconnected' | 'completed' | 'failed' | 'cancelled';

interface LiveTerminalProps {
  socket: WebSocket | null;
  state: TerminalConnectionState;
  interactive: boolean;
  events: any[];
  onInput: (data: string) => void;
  onResize: (columns: number, rows: number) => void;
  onCancel?: () => void;
  cancelling?: boolean;
  isArabic?: boolean;
}

const terminalText = (event: any) => event.type === 'terminal' || event.type === 'output'
  ? event.text || ''
  : event.type === 'log'
    ? event.text || ''
    : event.message
      ? `\r\n[${String(event.type).toUpperCase()}] ${event.message}\r\n`
      : '';

export const LiveTerminal: React.FC<LiveTerminalProps> = ({
  socket,
  state,
  interactive,
  events,
  onInput,
  onResize,
  onCancel,
  cancelling = false,
  isArabic = false,
}) => {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const terminalRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const writtenRef = useRef(0);
  const onInputRef = useRef(onInput);
  const onResizeRef = useRef(onResize);
  const [ready, setReady] = useState(false);

  useEffect(() => { onInputRef.current = onInput; }, [onInput]);
  useEffect(() => { onResizeRef.current = onResize; }, [onResize]);

  useEffect(() => {
    if (!containerRef.current) return;
    const terminal = new Terminal({
      convertEol: false,
      cursorBlink: interactive,
      disableStdin: !interactive,
      fontFamily: 'Consolas, "Cascadia Mono", monospace',
      fontSize: 12,
      lineHeight: 1.35,
      scrollback: 5000,
      theme: {
        background: '#0d110f',
        foreground: '#d5e2db',
        cursor: '#78d5a8',
        selectionBackground: '#365347',
        black: '#18201c',
        red: '#ff8299',
        green: '#78d5a8',
        yellow: '#e7cb7b',
        blue: '#8da8ff',
        magenta: '#c39cf4',
        cyan: '#72cbd0',
        white: '#d5e2db',
      },
    });
    const fit = new FitAddon();
    terminal.loadAddon(fit);
    terminal.open(containerRef.current);
    fit.fit();
    terminalRef.current = terminal;
    fitRef.current = fit;
    const inputDisposable = terminal.onData((data) => onInputRef.current(data));
    const resizeObserver = new ResizeObserver(() => {
      fit.fit();
      onResizeRef.current(terminal.cols, terminal.rows);
    });
    resizeObserver.observe(containerRef.current);
    setReady(true);
    return () => {
      resizeObserver.disconnect();
      inputDisposable.dispose();
      terminal.dispose();
      terminalRef.current = null;
      fitRef.current = null;
      writtenRef.current = 0;
    };
  }, [interactive]);

  useEffect(() => {
    if (!ready || !terminalRef.current) return;
    for (const event of events.slice(writtenRef.current)) {
      const text = terminalText(event);
      if (text) terminalRef.current.write(text);
    }
    writtenRef.current = events.length;
  }, [events, ready]);

  useEffect(() => {
    if (state === 'connected' && interactive) terminalRef.current?.focus();
  }, [interactive, state]);

  const labels: Record<TerminalConnectionState, string> = {
    connecting: isArabic ? 'جارٍ الاتصال' : 'Connecting',
    connected: isArabic ? 'متصل' : 'Connected',
    reconnecting: isArabic ? 'إعادة الاتصال' : 'Reconnecting',
    disconnected: isArabic ? 'غير متصل' : 'Disconnected',
    completed: isArabic ? 'اكتمل' : 'Completed',
    failed: isArabic ? 'فشل' : 'Failed',
    cancelled: isArabic ? 'أُلغي' : 'Cancelled',
  };

  return (
    <section className="surface-card live-terminal-card" aria-label={isArabic ? 'طرفية التنفيذ الحية' : 'Live execution terminal'}>
      <div className="live-terminal-head">
        <div><span className={`terminal-connection ${state}`} /><strong>{isArabic ? 'الطرفية الحية' : 'Live terminal'}</strong><span>{labels[state]}</span></div>
        <div><span>{interactive ? (isArabic ? 'تفاعلية · PTY' : 'Interactive · PTY') : (isArabic ? 'قراءة فقط' : 'Read only')}</span>{onCancel && state === 'connected' && <button type="button" onClick={onCancel} disabled={cancelling}>{cancelling ? (isArabic ? 'جارٍ الإيقاف…' : 'Stopping…') : (isArabic ? 'إيقاف' : 'Cancel')}</button>}</div>
      </div>
      {!events.length && state !== 'connected' && <div className="terminal-empty">{isArabic ? 'في انتظار اتصال التنفيذ…' : 'Waiting for the execution stream…'}</div>}
      <div className="xterm-host" ref={containerRef} />
      <div className="terminal-footer"><span>{interactive ? (isArabic ? 'اكتب مباشرة داخل الطرفية' : 'Type directly in the terminal') : (isArabic ? 'الناتج الحي محفوظ مع إيصال التشغيل' : 'Live output is retained with the run receipt')}</span><span>{socket?.readyState === WebSocket.OPEN ? 'WebSocket open' : 'WebSocket offline'}</span></div>
    </section>
  );
};
