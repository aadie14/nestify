import React from 'react';
import { AnimatePresence, motion } from 'framer-motion';

export type DebateStreamEvent = {
  agent: string;
  role?: string;
  message: string;
  reason?: string;
  result?: string;
  type: 'thinking' | 'fix' | 'action' | 'retry' | 'success' | 'failure';
  confidence?: number;
  cycle?: number;
};

type Props = {
  events: DebateStreamEvent[];
  loadingHint?: string;
  headline?: string;
  compact?: boolean;
};

function roleColor(role: string): string {
  const normalized = role.toLowerCase();
  if (normalized.includes('meta')) return '#b48cff';
  if (normalized.includes('security')) return '#26c6c4';
  if (normalized.includes('fix') || normalized.includes('code')) return '#43c97a';
  if (normalized.includes('simulation')) return '#eab308';
  if (normalized.includes('deploy') || normalized.includes('platform')) return '#60a5fa';
  return '#9aa7b8';
}

function normalizeMessage(event: DebateStreamEvent): string {
  const base = shortMessage(event.message)
    .replace(/^Reasoning:\s*/i, '')
    .replace(/^Pattern detected:\s*/i, '')
    .replace(/^I\s+will\s+/i, '')
    .replace(/^Retry\s+failed\.?\s*Retry\s+failed\.?/i, 'Retry failed.')
    .replace(/^\p{Emoji_Presentation}+\s*/u, '')
    .replace(/^\w[\w\s-]{1,24}:\s*/i, '')
    .replace(/\p{Extended_Pictographic}/gu, '');
  if (event.type !== 'fix') return base;
  if (base.startsWith('[+]') || base.startsWith('[~]')) return base;
  const lower = base.toLowerCase();
  if (/(added|created|set|injected)\b/.test(lower)) return `[+] ${base}`;
  return `[~] ${base}`;
}

function shortMessage(raw: string): string {
  const line = raw.replace(/\s+/g, ' ').trim();
  if (line.length <= 86) return line;
  return `${line.slice(0, 83)}...`;
}

function shortReason(raw?: string): string {
  const line = String(raw || '').replace(/\s+/g, ' ').trim();
  if (!line) return '';
  if (line.length <= 120) return line;
  return `${line.slice(0, 117)}...`;
}

function normalizeKey(event: DebateStreamEvent): string {
  const cycle = Number.isFinite(Number(event.cycle)) ? Number(event.cycle) : -1;
  const role = displayRoleLabel(event).toLowerCase();
  return `${cycle}|${role}|${event.type}|${normalizeMessage(event).toLowerCase()}|${shortReason(event.reason || event.result).toLowerCase()}`;
}

function collapseEvents(events: DebateStreamEvent[]): DebateStreamEvent[] {
  const result: DebateStreamEvent[] = [];
  const seen = new Set<string>();
  let retryCount = 0;
  let retryAgent = 'Deploy Agent';
  let retryReason = '';

  const flushRetry = () => {
    if (retryCount <= 0) return;
    if (retryCount === 1) {
      const collapsed: DebateStreamEvent = {
        agent: 'deploy_agent',
        role: retryAgent,
        message: 'Retry failed. Switching strategy.',
        reason: shortReason(retryReason) || undefined,
        type: 'retry',
      };
      const key = normalizeKey(collapsed);
      if (!seen.has(key)) {
        result.push(collapsed);
        seen.add(key);
      }
    } else {
      const collapsed: DebateStreamEvent = {
        agent: 'deploy_agent',
        role: retryAgent,
        message: `${retryCount} retries failed. Applying new approach.`,
        reason: shortReason(retryReason) || undefined,
        type: 'retry',
      };
      const key = normalizeKey(collapsed);
      if (!seen.has(key)) {
        result.push(collapsed);
        seen.add(key);
      }
    }
    retryCount = 0;
    retryReason = '';
  };

  for (const item of events) {
    const lowerMessage = String(item.message || '').toLowerCase();
    const lowerReason = String(item.reason || '').toLowerCase();
    if (item.type === 'thinking') continue;
    if (lowerMessage.includes('reasoning:') || lowerReason.includes('reasoning:')) continue;

    const current: DebateStreamEvent = {
      ...item,
      message: normalizeMessage(item),
      reason: shortReason(item.reason || '' ) || undefined,
      result: undefined,
    };

    if (current.type === 'retry') {
      retryCount += 1;
      retryAgent = String(current.role || current.agent || 'Deploy Agent');
      retryReason = String(current.reason || retryReason || 'Previous attempt failed');
      continue;
    }

    flushRetry();

    const prev = result[result.length - 1];
    if (prev) {
      const prevKey = normalizeKey(prev);
      const curKey = normalizeKey(current);
      if (prevKey === curKey) {
        continue;
      }
      if (prev.type === 'failure' && current.type === 'failure' && normalizeMessage(prev).toLowerCase() === normalizeMessage(current).toLowerCase()) {
        continue;
      }
    }

    const currentKey = normalizeKey(current);
    if (seen.has(currentKey)) continue;

    if (Number.isFinite(Number(current.cycle))) {
      const cycleRole = `${Number(current.cycle)}|${displayRoleLabel(current).toLowerCase()}`;
      const existingIndex = result.findIndex((entry) => `${Number(entry.cycle)}|${displayRoleLabel(entry).toLowerCase()}` === cycleRole);
      if (existingIndex >= 0) {
        result[existingIndex] = current;
        continue;
      }
    }

    result.push(current);
    seen.add(currentKey);
  }

  flushRetry();
  return result.slice(-7);
}

function displayAgentName(event: DebateStreamEvent): string {
  const direct = String(event.role || '').trim();
  if (direct) return direct.replace(/(\p{Extended_Pictographic}).*(\p{Extended_Pictographic})/gu, '$1 ').trim();
  const normalized = String(event.agent || '').trim();
  if (!normalized) return 'Specialist Agent';
  return normalized
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (ch) => ch.toUpperCase());
}

function displayRoleLabel(event: DebateStreamEvent): string {
  const raw = `${displayAgentName(event)} ${event.agent}`.toLowerCase();
  if (raw.includes('meta')) return '🧠 Meta-Agent';
  if (raw.includes('security')) return '🛡 Security';
  if (raw.includes('simulation')) return '🧪 Simulation';
  if (raw.includes('fix')) return '🛠 Fix Agent';
  if (raw.includes('deploy') || raw.includes('platform') || raw.includes('architect')) return '🚀 Deploy';
  return '🤖 Specialist';
}

export default function AIDebateStream({ events, loadingHint, headline, compact = false }: Props) {
  const streamRef = React.useRef<HTMLDivElement | null>(null);
  const stickToBottomRef = React.useRef(true);
  const scrollRafRef = React.useRef<number | null>(null);
  const [loadingIndex, setLoadingIndex] = React.useState(0);
  const normalizedEvents = React.useMemo(() => collapseEvents(events), [events]);
  const visibleEvents = React.useMemo(() => normalizedEvents.slice(-7), [normalizedEvents]);

  const loadingLines = React.useMemo(
    () => [
      'Analyzing dependencies...',
      'Evaluating deployment strategy...',
      'Validating provider readiness...',
    ],
    [],
  );

  const queueScrollToBottom = React.useCallback((behavior: ScrollBehavior = 'smooth') => {
    const node = streamRef.current;
    if (!node || !stickToBottomRef.current) return;
    if (scrollRafRef.current != null) {
      window.cancelAnimationFrame(scrollRafRef.current);
    }
    scrollRafRef.current = window.requestAnimationFrame(() => {
      node.scrollTo({ top: node.scrollHeight, behavior });
      scrollRafRef.current = null;
    });
  }, []);

  React.useEffect(() => {
    const node = streamRef.current;
    if (!node) return;

    const onScroll = () => {
      const distance = node.scrollHeight - node.scrollTop - node.clientHeight;
      stickToBottomRef.current = distance < 56;
    };

    onScroll();
    node.addEventListener('scroll', onScroll, { passive: true });
    return () => {
      node.removeEventListener('scroll', onScroll);
      if (scrollRafRef.current != null) {
        window.cancelAnimationFrame(scrollRafRef.current);
      }
    };
  }, []);

  React.useEffect(() => {
    queueScrollToBottom('smooth');
  }, [normalizedEvents.length, queueScrollToBottom]);

  React.useEffect(() => {
    if (visibleEvents.length > 0) return;
    const timer = window.setInterval(() => {
      setLoadingIndex((prev) => (prev + 1) % loadingLines.length);
    }, 1800);
    return () => window.clearInterval(timer);
  }, [visibleEvents.length, loadingLines.length]);

  return (
    <section className="ai-debate-stream-chat" ref={streamRef}>
        <div className="ai-stream-headline">{headline || 'AI Conversation Stream'}</div>
        {visibleEvents.length === 0 ? (
          <div className="ai-debate-loading-inline">
            <div className="ai-debate-loading-line">{loadingLines[loadingIndex]}</div>
            <div className="tiny">{loadingHint || 'Starting multi-agent discussion. First reasoning updates will appear shortly.'}</div>
          </div>
        ) : null}

        <AnimatePresence initial={false}>
          {visibleEvents.map((event, index) => {
            const displayName = displayAgentName(event);
            const roleLabel = displayRoleLabel(event);
            const color = roleColor(`${displayName} ${event.agent}`);
            const isMeta = `${displayName} ${event.agent}`.toLowerCase().includes('meta');
            const relativeIndex = Math.max(0, index - Math.max(0, visibleEvents.length - 8));

            return (
              <motion.article
                key={`${index}-${event.agent}-${event.message}`}
                className={`ai-debate-msg type-${event.type} ${isMeta ? 'meta' : ''} ${index === visibleEvents.length - 1 ? 'active' : ''}`}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.25, delay: Math.min(relativeIndex * 0.045, 0.22), ease: [0.22, 1, 0.36, 1] }}
                layout="position"
              >
                <div className="ai-debate-content">
                  <p className="ai-debate-text">
                    <span className="ai-feed-agent" style={{ color }}>{roleLabel}:</span>{' '}
                    <span className="ai-feed-msg">{normalizeMessage(event)}</span>
                  </p>
                </div>
              </motion.article>
            );
          })}
        </AnimatePresence>
    </section>
  );
}
