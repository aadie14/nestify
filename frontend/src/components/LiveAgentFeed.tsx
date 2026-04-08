import React from 'react';
import { Brain, Shield, DollarSign, Server, Wrench } from 'lucide-react';
import { ProgressMessage } from '../hooks/useWebSocket';

type Props = {
  messages: ProgressMessage[];
};

const ROW_HEIGHT = 92;
const MAX_VISIBLE_ROWS = 50;

function getAgentStyle(agent?: string) {
  const normalized = String(agent || '').toLowerCase();
  if (normalized.includes('security')) return { icon: <Shield size={14} />, color: 'var(--brand-primary)', label: 'Security Agent' };
  if (normalized.includes('cost')) return { icon: <DollarSign size={14} />, color: 'var(--brand-primary)', label: 'Cost Agent' };
  if (normalized.includes('deploy') || normalized.includes('platform')) return { icon: <Server size={14} />, color: 'var(--brand-primary)', label: 'Architect Agent' };
  if (normalized.includes('fix') || normalized.includes('heal')) return { icon: <Wrench size={14} />, color: 'var(--brand-primary)', label: 'Self-Healing Agent' };
  return { icon: <Brain size={14} />, color: 'var(--brand-primary)', label: 'Code Agent' };
}

function formatTimestamp(value?: string) {
  if (!value) return '';
  const numeric = Number(value);
  const date = Number.isFinite(numeric) ? new Date(numeric * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleTimeString();
}

type FeedRowProps = {
  message: ProgressMessage;
  index: number;
};

const FeedRow = React.memo(function FeedRow({ message, index }: FeedRowProps) {
  const style = getAgentStyle(message.agent);
  const content = message.user_message || message.message || message.decision || 'Working on this step.';

  const getStatusLabel = (value?: string) => {
    const normalized = String(value || '').toLowerCase();
    if (normalized === 'complete') return 'Completed';
    if (normalized === 'error') return 'Error';
    if (normalized === 'active') return 'In Progress';
    return 'Update';
  };

  return (
    <article key={`${message.timestamp || index}-${index}`} className="agent-feed-item fade-in" style={{ borderLeftColor: style.color }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: style.color }}>
          {style.icon}
          <strong>{style.label}</strong>
        </div>
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          <span className="status-pill">{getStatusLabel(message.status)}</span>
          <span className="tiny">{formatTimestamp(message.timestamp)}</span>
        </div>
      </div>
      <p style={{ margin: '6px 0 0 0' }}>{content}</p>
    </article>
  );
});

export default function LiveAgentFeed({ messages }: Props) {
  const listRef = React.useRef<HTMLDivElement | null>(null);
  const feed = React.useMemo(() => messages.slice(-240), [messages]);
  const [windowStart, setWindowStart] = React.useState(0);

  const handleScroll = React.useCallback(() => {
    if (!listRef.current) return;
    const top = listRef.current.scrollTop;
    const next = Math.max(0, Math.floor(top / ROW_HEIGHT) - 4);
    setWindowStart((prev) => (prev === next ? prev : next));
  }, []);

  const windowEnd = Math.min(feed.length, windowStart + MAX_VISIBLE_ROWS);
  const visibleRows = feed.slice(windowStart, windowEnd);
  const topSpacer = windowStart * ROW_HEIGHT;
  const bottomSpacer = Math.max(0, (feed.length - windowEnd) * ROW_HEIGHT);
  const hasReasoning = feed.some((item) => String(item.type || '').toLowerCase() === 'argument' || Boolean(item.thought));

  React.useEffect(() => {
    if (!listRef.current) return;
    const el = listRef.current;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 140;
    if (nearBottom) {
      el.scrollTop = el.scrollHeight;
      setWindowStart(Math.max(0, feed.length - MAX_VISIBLE_ROWS));
    }
  }, [feed.length]);

  return (
    <section className="card" style={{ display: 'grid', gap: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
        <h3 style={{ margin: 0 }}>Live Agent Feed</h3>
        <div className="tiny">{feed.length} updates</div>
      </div>
      <div ref={listRef} className="agent-feed-list" onScroll={handleScroll}>
        {feed.length === 0 ? (
          <div className="tiny">
            Connecting to agent stream. I will surface reasoning, confidence, and decisions as soon as analysis begins.
          </div>
        ) : null}
        {feed.length > 0 && !hasReasoning ? (
          <div className="tiny">Receiving execution events. Reasoned decision traces will appear as the meta-agent evaluates options.</div>
        ) : null}
        {topSpacer > 0 ? <div style={{ height: topSpacer }} /> : null}
        {visibleRows.map((message, idx) => (
          <FeedRow key={`${message.timestamp || windowStart + idx}-${windowStart + idx}`} message={message} index={windowStart + idx} />
        ))}
        {bottomSpacer > 0 ? <div style={{ height: bottomSpacer }} /> : null}
      </div>
    </section>
  );
}
