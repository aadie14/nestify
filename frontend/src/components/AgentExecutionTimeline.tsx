import React, { useEffect, useMemo, useRef } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Brain, CheckCircle2, AlertTriangle, Loader2, Sparkles } from 'lucide-react';

export type ExecutionStatus = 'thinking' | 'success' | 'failed';

export type ExecutionMessage = {
  id?: string;
  status: ExecutionStatus;
  text: string;
  icon?: 'analysis' | 'detect' | 'deploy' | 'fix' | 'retry';
  timestamp?: string | number;
};

type Props = {
  messages: ExecutionMessage[];
  title?: string;
  autoScroll?: boolean;
};

function statusMeta(status: ExecutionStatus) {
  if (status === 'success') {
    return {
      label: 'Success',
      color: 'var(--brand-success)',
      badgeBg: 'rgba(0, 217, 163, 0.14)',
      badgeBorder: 'rgba(0, 217, 163, 0.45)',
      icon: <CheckCircle2 size={14} />,
    };
  }
  if (status === 'failed') {
    return {
      label: 'Failed',
      color: 'var(--brand-error)',
      badgeBg: 'rgba(239, 68, 68, 0.14)',
      badgeBorder: 'rgba(239, 68, 68, 0.45)',
      icon: <AlertTriangle size={14} />,
    };
  }
  return {
    label: 'Thinking',
    color: 'var(--brand-warning)',
    badgeBg: 'rgba(245, 158, 11, 0.14)',
    badgeBorder: 'rgba(245, 158, 11, 0.45)',
    icon: <Loader2 size={14} className="spin" />,
  };
}

function actionIcon(icon?: ExecutionMessage['icon']) {
  if (icon === 'analysis') return <Brain size={14} />;
  if (icon === 'detect') return <Sparkles size={14} />;
  if (icon === 'deploy') return <Sparkles size={14} />;
  if (icon === 'fix') return <Sparkles size={14} />;
  if (icon === 'retry') return <Sparkles size={14} />;
  return <Sparkles size={14} />;
}

function formatTime(value?: string | number) {
  if (value == null) return '';
  const date = typeof value === 'number' ? new Date(value) : new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleTimeString();
}

export default function AgentExecutionTimeline({
  messages,
  title = 'Agent Execution Timeline',
  autoScroll = true,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  const normalized = useMemo(
    () =>
      messages.map((item, index) => ({
        ...item,
        id: item.id || `${item.timestamp || Date.now()}-${index}`,
      })),
    [messages],
  );

  useEffect(() => {
    if (!autoScroll || !containerRef.current) return;
    containerRef.current.scrollTop = containerRef.current.scrollHeight;
  }, [normalized.length, autoScroll]);

  return (
    <section className="card" style={{ display: 'grid', gap: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
        <h3 style={{ margin: 0 }}>{title}</h3>
        <div className="tiny">{normalized.length} events</div>
      </div>

      <div ref={containerRef} style={{ maxHeight: 420, overflow: 'auto', display: 'grid', gap: 8, paddingRight: 4 }}>
        <AnimatePresence initial={false}>
          {normalized.map((item) => {
            const meta = statusMeta(item.status);
            return (
              <motion.article
                key={item.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.22, ease: 'easeOut' }}
                style={{
                  border: '1px solid #304863',
                  borderRadius: 12,
                  padding: 10,
                  background: 'rgba(17, 26, 40, 0.7)',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10 }}>
                  <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, color: '#c8d5ea' }}>
                    {actionIcon(item.icon)}
                    <strong style={{ fontSize: 13 }}>{item.text}</strong>
                  </div>
                  <span
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 6,
                      border: `1px solid ${meta.badgeBorder}`,
                      borderRadius: 999,
                      padding: '2px 8px',
                      fontSize: 11,
                      color: meta.color,
                      background: meta.badgeBg,
                    }}
                  >
                    {meta.icon}
                    {meta.label}
                  </span>
                </div>
                {item.timestamp ? <div className="tiny" style={{ marginTop: 6 }}>{formatTime(item.timestamp)}</div> : null}
              </motion.article>
            );
          })}
        </AnimatePresence>

        {normalized.length === 0 ? (
          <div className="tiny">AI is thinking...</div>
        ) : null}
      </div>
    </section>
  );
}
