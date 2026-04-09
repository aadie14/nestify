import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import Badge from './ui/Badge';

export type FeedItem = {
  agent?: string;
  type?: string;
  title?: string;
  severity?: string;
  message?: string;
  action?: string;
  confidence?: number;
  timestamp?: string;
};

type Props = {
  items: FeedItem[];
  maxItems?: number;
};

function tone(severity: string) {
  const s = String(severity || '').toLowerCase();
  if (s === 'high' || s === 'critical' || s === 'error') return 'error';
  if (s === 'medium' || s === 'warning') return 'warning';
  if (s === 'low' || s === 'success') return 'success';
  return 'intelligence';
}

function label(agent: string) {
  const a = String(agent || 'system').toLowerCase();
  if (a.includes('security')) return 'Security';
  if (a.includes('code')) return 'Code';
  if (a.includes('deploy')) return 'Deploy';
  if (a.includes('monitor')) return 'Monitor';
  if (a.includes('meta')) return 'Meta';
  if (a.includes('knowledge')) return 'Learning';
  return 'System';
}

function icon(agent: string) {
  const a = String(agent || 'system').toLowerCase();
  if (a.includes('security')) return 'SH';
  if (a.includes('code')) return 'CD';
  if (a.includes('deploy')) return 'DP';
  if (a.includes('monitor')) return 'MN';
  if (a.includes('meta')) return 'MT';
  if (a.includes('knowledge')) return 'KN';
  return 'SY';
}

function compact(text: string, max = 96) {
  const line = String(text || '').replace(/\s+/g, ' ').trim();
  if (line.length <= max) return line;
  return `${line.slice(0, max - 3)}...`;
}

export default function AgentFeedCards({ items, maxItems = 10 }: Props) {
  const [expanded, setExpanded] = React.useState<string | null>(null);
  const filtered = React.useMemo(() => {
    const out: FeedItem[] = [];
    const seen = new Set<string>();

    for (const row of items.slice(-80)) {
      const msg = compact(String(row.message || ''), 140);
      if (!msg) continue;
      const key = `${String(row.agent || '').toLowerCase()}|${String(row.type || '').toLowerCase()}|${msg.toLowerCase()}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ ...row, message: msg });
    }

    return out.slice(-maxItems);
  }, [items, maxItems]);

  if (!filtered.length) {
    return <div className="tiny">Waiting for agent events...</div>;
  }

  return (
    <div className="agent-feed-list">
      <AnimatePresence initial={false}>
        {filtered.map((item, idx) => {
          const id = `${idx}-${item.timestamp || ''}-${item.message || ''}`;
          const isOpen = expanded === id;
          const sev = String(item.severity || 'info').toLowerCase();
          return (
            <motion.article
              key={id}
              layout
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.2 }}
              className="agent-feed-card"
              onClick={() => setExpanded((prev) => (prev === id ? null : id))}
            >
              <div className="agent-feed-head">
                <div className="agent-feed-id">
                  <span className="agent-feed-icon">{icon(String(item.agent || 'system'))}</span>
                  <strong>{label(String(item.agent || 'system'))}</strong>
                </div>
                <Badge variant={tone(sev) as any}>{sev.toUpperCase()}</Badge>
              </div>
              <div className="agent-feed-title">{compact(String(item.title || item.type || 'update'), 72)}</div>
              <div className="agent-feed-message">{compact(String(item.message || ''), isOpen ? 220 : 110)}</div>
              {isOpen ? (
                <div className="agent-feed-meta tiny">
                  {item.action ? <span>Action: {compact(item.action, 70)}</span> : null}
                  {typeof item.confidence === 'number' ? <span>Confidence: {Math.round(item.confidence * 100)}%</span> : null}
                </div>
              ) : null}
            </motion.article>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
