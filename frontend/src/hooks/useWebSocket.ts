import { useEffect, useMemo, useRef, useState } from 'react';

export type ProgressMessage = {
  type?: string;
  user_message?: string;
  state?: string;
  message?: string;
  details?: Record<string, unknown>;
  timestamp?: string;
  phase?: string;
  agent?: string;
  status?: 'pending' | 'active' | 'complete' | 'error';
  thought?: string;
  decision?: string;
  confidence?: number;
  evidence?: string[];
  data?: Record<string, unknown>;
  reason?: string;
  result?: string;
  cycle?: number;
};

export function useWebSocket(projectId: number | null) {
  const [messages, setMessages] = useState<ProgressMessage[]>([]);
  const [connected, setConnected] = useState(false);
  const queueRef = useRef<ProgressMessage[]>([]);
  const flushTimerRef = useRef<number | null>(null);

  const flushQueue = () => {
    if (!queueRef.current.length) return;
    const chunk = queueRef.current;
    queueRef.current = [];
    setMessages((prev) => [...prev, ...chunk].slice(-240));
  };

  useEffect(() => {
    if (!projectId) return;

    setMessages([]);
    queueRef.current = [];

    flushTimerRef.current = window.setInterval(() => {
      flushQueue();
    }, 500);

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

    ws.onopen = () => {
      setConnected(true);
      ws.send(JSON.stringify({ type: 'subscribe', projectId }));
    };

    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === 'agent_reasoning' || payload.type === 'argument') {
          const reasoning: ProgressMessage = {
            type: 'argument',
            timestamp: payload.timestamp || new Date().toISOString(),
            cycle: Number(payload.cycle || payload?.data?.cycle || 0) || undefined,
            phase: 'reasoning',
            agent: payload.agent,
            status: 'active',
            user_message: payload.user_message || payload.decision,
            message: payload.user_message || payload.decision || 'Agent reasoning update',
            thought: payload.thought,
            decision: payload.decision,
            confidence: Number(payload.confidence || 0),
            evidence: Array.isArray(payload.evidence) ? payload.evidence : [],
            data: payload.data && typeof payload.data === 'object' ? payload.data : {},
            details: {
              evidence: Array.isArray(payload.evidence) ? payload.evidence : [],
              data: payload.data,
            },
          };
          queueRef.current.push(reasoning);
          return;
        }

        const messageText = String(payload.message || 'Progress update');
        const stateText = String(payload.phase || 'pending').toLowerCase();
        const status: ProgressMessage['status'] =
          messageText.toLowerCase().includes('error') || stateText.includes('fail')
            ? 'error'
            : messageText.toLowerCase().includes('complete') || messageText.toLowerCase().includes('success')
              ? 'complete'
              : stateText.includes('deploy') || stateText.includes('analy') || stateText.includes('scan')
                ? 'active'
                : 'pending';

        const normalized: ProgressMessage = {
          type: 'progress',
          cycle: Number(payload.cycle || payload?.data?.cycle || 0) || undefined,
          state: payload.phase,
          message: messageText,
          details: {
            agent: payload.agent,
            data: payload.data,
          },
          reason: typeof payload?.data?.reason === 'string' ? payload.data.reason : undefined,
          result: typeof payload?.data?.result === 'string' ? payload.data.result : undefined,
          timestamp: payload.timestamp || new Date().toISOString(),
          phase: payload.phase,
          agent: payload.agent,
          status,
          data: payload.data && typeof payload.data === 'object' ? payload.data : undefined,
        };
        queueRef.current.push(normalized);
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);

    return () => {
      if (flushTimerRef.current) {
        window.clearInterval(flushTimerRef.current);
        flushTimerRef.current = null;
      }
      flushQueue();
      queueRef.current = [];
      ws.close();
    };
  }, [projectId]);

  const status = useMemo(() => (connected ? 'connected' : 'disconnected'), [connected]);

  return { messages, status };
}
