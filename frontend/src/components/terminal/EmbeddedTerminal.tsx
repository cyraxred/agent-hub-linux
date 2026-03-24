import { SessionId } from '@/types/session';
import { useSessionsStore } from '@/store/sessions';
import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { WebglAddon } from '@xterm/addon-webgl';
import { api } from '@/api/client';
import '@xterm/xterm/css/xterm.css';

interface EmbeddedTerminalProps {
  sessionId: SessionId;
  projectPath: string;
}

export const EmbeddedTerminal: React.FC<EmbeddedTerminalProps> = ({
  sessionId,
  projectPath,
}) => {
  const terminalRef = useRef<HTMLDivElement>(null);
  const xtermRef = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const webglAddonRef = useRef<WebglAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const terminalKeyRef = useRef<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sessionUpdate = useSessionsStore((s) => s.sessionUpdates[sessionId]);
  // Block only when SessionManager explicitly says not connectable.
  // No sessionUpdate yet = allow (backend will 409 if needed).
  const cannotConnect = sessionUpdate ? !sessionUpdate.is_connectable : false;

  const handleKill = useCallback(() => {
    const key = terminalKeyRef.current;
    if (key) {
      api.terminal.kill(key).catch(() => {});
      terminalKeyRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!terminalRef.current || cannotConnect) return;

    const terminal = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'SF Mono', Menlo, monospace",
      theme: {
        background: '#0d1117',
        foreground: '#c9d1d9',
        cursor: '#58a6ff',
        cursorAccent: '#0d1117',
        selectionBackground: '#264f78',
        selectionForeground: '#ffffff',
        black: '#484f58',
        red: '#ff7b72',
        green: '#3fb950',
        yellow: '#d29922',
        blue: '#58a6ff',
        magenta: '#bc8cff',
        cyan: '#39c5cf',
        white: '#b1bac4',
        brightBlack: '#6e7681',
        brightRed: '#ffa198',
        brightGreen: '#56d364',
        brightYellow: '#e3b341',
        brightBlue: '#79c0ff',
        brightMagenta: '#d2a8ff',
        brightCyan: '#56d4dd',
        brightWhite: '#f0f6fc',
      },
      scrollback: 10000,
      allowProposedApi: true,
    });

    const fitAddon = new FitAddon();
    terminal.loadAddon(fitAddon);
    fitAddonRef.current = fitAddon;

    terminal.open(terminalRef.current);

    // Try WebGL addon for performance
    try {
      const webglAddon = new WebglAddon();
      terminal.loadAddon(webglAddon);
      webglAddonRef.current = webglAddon;
      webglAddon.onContextLoss(() => {
        webglAddon.dispose();
        webglAddonRef.current = null;
      });
    } catch {
      // WebGL not available, fallback to canvas
    }

    fitAddon.fit();

    xtermRef.current = terminal;

    // Launch the terminal via REST API, then connect via dedicated WebSocket
    api.terminal
      .launch({
        project_path: projectPath,
        session_id: SessionId.rawId(sessionId),
        resume: true,
      })
      .then((resp) => {
        if (!xtermRef.current) return; // component unmounted
        terminalKeyRef.current = resp.key;

        // Open a dedicated WebSocket to /ws/terminal/{key}
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/terminal/${encodeURIComponent(resp.key)}`;
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
          // Fit and report initial size
          try {
            fitAddon.fit();
          } catch {
            // ignore
          }
          // Send initial resize as JSON
          ws.send(JSON.stringify({
            type: 'resize',
            rows: terminal.rows,
            cols: terminal.cols,
          }));
        };

        ws.onmessage = (event: MessageEvent) => {
          // The dedicated terminal WS sends raw text frames (PTY output)
          if (xtermRef.current && typeof event.data === 'string') {
            xtermRef.current.write(event.data);
          }
        };

        ws.onclose = () => {
          if (xtermRef.current) {
            terminal.writeln('');
            terminal.writeln('\x1b[90m--- Terminal disconnected ---\x1b[0m');
          }
        };

        ws.onerror = () => {
          if (xtermRef.current) {
            terminal.writeln('\x1b[31mWebSocket connection error\x1b[0m');
          }
        };

        // Forward user keystrokes to the dedicated WS
        terminal.onData((data) => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(data);
          }
        });
      })
      .catch((err) => {
        console.error('[Terminal] Failed to launch:', err);
        setError((err as Error).message ?? 'Failed to launch terminal');
        if (xtermRef.current) {
          terminal.writeln(`\x1b[31mFailed to launch terminal: ${(err as Error).message}\x1b[0m`);
        }
      });

    // Handle resize
    const resizeObserver = new ResizeObserver(() => {
      requestAnimationFrame(() => {
        try {
          fitAddon.fit();
          const ws = wsRef.current;
          if (ws && ws.readyState === WebSocket.OPEN && xtermRef.current) {
            ws.send(JSON.stringify({
              type: 'resize',
              rows: xtermRef.current.rows,
              cols: xtermRef.current.cols,
            }));
          }
        } catch {
          // Ignore fit errors during resize
        }
      });
    });

    if (terminalRef.current) {
      resizeObserver.observe(terminalRef.current);
    }

    // Cleanup on unmount: disconnect UI only, keep backend process alive
    return () => {
      resizeObserver.disconnect();

      // Close the dedicated terminal WS (does NOT kill the backend process)
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }

      webglAddonRef.current?.dispose();
      fitAddon.dispose();
      terminal.dispose();
      xtermRef.current = null;
      fitAddonRef.current = null;
      webglAddonRef.current = null;
    };
  }, [sessionId, projectPath, cannotConnect]);

  if (cannotConnect) {
    return (
      <div className="embedded-terminal">
        <div className="terminal-toolbar">
          <div className="terminal-toolbar-left">
            <span className="terminal-label">Terminal</span>
          </div>
        </div>
        <div style={{ padding: 'var(--space-lg)', color: 'var(--accent-orange)' }}>
          Cannot connect to this session — it has a running process
          (category: {sessionUpdate?.process_category ?? 'unknown'})
          that cannot be attached to. Wait for it to finish or use tmux.
        </div>
      </div>
    );
  }

  return (
    <div className="embedded-terminal">
      <div className="terminal-toolbar">
        <div className="terminal-toolbar-left">
          <span className="terminal-label">Terminal</span>
          <span className="terminal-session-id">{SessionId.rawId(sessionId).slice(0, 8)}</span>
        </div>
        <div className="terminal-toolbar-right">
          <button
            className="terminal-btn"
            onClick={() => {
              xtermRef.current?.clear();
            }}
            title="Clear terminal"
          >
            Clear
          </button>
          <button
            className="terminal-btn"
            onClick={() => {
              fitAddonRef.current?.fit();
              const ws = wsRef.current;
              if (ws && ws.readyState === WebSocket.OPEN && xtermRef.current) {
                ws.send(JSON.stringify({
                  type: 'resize',
                  rows: xtermRef.current.rows,
                  cols: xtermRef.current.cols,
                }));
              }
            }}
            title="Fit terminal"
          >
            Fit
          </button>
          <button
            className="terminal-btn terminal-btn-danger"
            onClick={handleKill}
            title="Kill terminal process"
          >
            Kill
          </button>
        </div>
      </div>
      <div className="terminal-container" ref={terminalRef} />
    </div>
  );
};
