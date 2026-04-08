import React from 'react';
import { motion } from 'framer-motion';
import { useWebSocket } from '../hooks/useWebSocket';
import axios from 'axios';
import { AlertCircle, Brain, Check, Clock3, Copy, Database, DollarSign, ExternalLink, Shield, Zap } from 'lucide-react';
import Card from './ui/Card';
import Progress from './ui/Progress';
import Button from './ui/Button';
import Badge from './ui/Badge';
import SkeletonValue from './ui/SkeletonValue';
import { useAnimation } from '../hooks/useAnimation';

type Props = { projectId: number };

type StatusPayload = {
  status?: string;
  progress?: Array<{ phase?: string }>;
};

function deriveDeploymentProgress(statusData: StatusPayload | null, messageCount: number, blockingError: string | null): number {
  if (blockingError) return 100;
  if (!statusData) return messageCount === 0 ? 5 : Math.min(95, Math.max(10, Math.round((messageCount / 20) * 100)));
  const status = String(statusData.status || '').toLowerCase();
  if (status === 'completed' || status === 'live' || status === 'failed') return 100;

  const phase = String(statusData.progress?.[statusData.progress.length - 1]?.phase || '').toLowerCase();
  if (phase.includes('scan')) return 20;
  if (phase.includes('analy')) return 40;
  if (phase.includes('impact')) return 55;
  if (phase.includes('simulation')) return 65;
  if (phase.includes('fix')) return 75;
  if (phase.includes('deploy')) return 90;
  if (phase.includes('monitor')) return 95;

  return messageCount === 0 ? 10 : Math.min(95, Math.max(10, Math.round((messageCount / 20) * 100)));
}

export default function DeploymentProgress({ projectId }: Props) {
  const { messages, status } = useWebSocket(projectId);
  const { fadeInUp } = useAnimation();
  const [statusData, setStatusData] = React.useState<StatusPayload | null>(null);
  const [blockingError, setBlockingError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!projectId) return;
    let alive = true;

    const poll = async () => {
      try {
        const res = await axios.get(`/api/v1/projects/${projectId}/status`);
        if (!alive) return;
        setStatusData(res.data || null);
      } catch {
        if (!alive) return;
      }
    };

    poll();
    const timer = window.setInterval(poll, 3000);

    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [projectId]);

  React.useEffect(() => {
    if (!projectId) return;
    let alive = true;

    const pollReport = async () => {
      try {
        const res = await axios.get(`/api/v1/projects/${projectId}/report`);
        if (!alive) return;
        const logs = Array.isArray(res.data?.logs) ? res.data.logs : [];
        const deploymentErrors = logs.filter(
          (log: any) =>
            String(log?.stage || '').toLowerCase().includes('deployment') &&
            String(log?.level || '').toLowerCase() === 'error'
        );
        const lastError = deploymentErrors.length ? String(deploymentErrors[deploymentErrors.length - 1]?.message || '') : '';
        setBlockingError(lastError || null);
      } catch {
        if (!alive) return;
      }
    };

    pollReport();
    const timer = window.setInterval(pollReport, 5000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [projectId]);

  const getAgentIcon = (agent?: string) => {
    const normalized = (agent || '').toLowerCase();
    if (normalized.includes('security')) return <Shield size={18} color="var(--brand-primary)" aria-label="Security agent" />;
    if (normalized.includes('cost')) return <DollarSign size={18} color="var(--brand-primary)" aria-label="Cost agent" />;
    if (normalized.includes('platform')) return <Database size={18} color="var(--brand-primary)" aria-label="Platform agent" />;
    if (normalized.includes('heal')) return <Zap size={18} color="var(--brand-primary)" aria-label="Self-heal agent" />;
    return <Brain size={18} color="var(--brand-primary)" aria-label="Code agent" />;
  };

  const getStatusIcon = (statusValue?: string) => {
    if (statusValue === 'error') return <AlertCircle size={18} color="#ef4444" aria-label="Error" />;
    if (statusValue === 'complete') {
      return <Check size={18} color="#10b981" aria-label="Completed" />;
    }
    return <Clock3 size={18} color="#f59e0b" aria-label="In progress" />;
  };

  const last = messages.length > 0 ? messages[messages.length - 1] : undefined;
  const isComplete =
    !!blockingError ||
    (!!last && (last.status === 'complete' || `${last.message || ''}`.toLowerCase().includes('deployed')));
  const progress = deriveDeploymentProgress(statusData, messages.length, blockingError);
  const successful = messages.filter((message) => message.status === 'complete').length;
  const failed = messages.filter((message) => message.status === 'error').length;
  const active = messages.filter((message) => message.status === 'active').length;
  const deploymentUrl =
    ((last?.details?.data as Record<string, unknown> | undefined)?.deployment_url as string | undefined)
    || (last?.details?.deployment_url as string | undefined)
    || (last?.details?.url as string | undefined);

  const copyUrl = async () => {
    if (!deploymentUrl || typeof deploymentUrl !== 'string') return;
    try {
      await navigator.clipboard.writeText(deploymentUrl);
    } catch {
      // Ignore clipboard failures silently.
    }
  };

  const formatTime = (value?: string) => {
    if (!value) return '...';
    const numeric = Number(value);
    const date = Number.isFinite(numeric) ? new Date(numeric * 1000) : new Date(value);
    if (Number.isNaN(date.getTime())) return '...';
    return date.toLocaleTimeString();
  };

  return (
    <section className="grid-2" aria-live="polite">
      <div className="page">
        <Card className="card" hover={false}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center' }}>
            <div>
              <h2 style={{ margin: 0, fontSize: 'var(--text-h2)' }}>Deployment Timeline</h2>
              <div className="muted" style={{ marginTop: 6 }}>
                Project #{projectId} • real-time agent orchestration
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span className={`status-dot ${status === 'connected' ? 'live' : ''}`} />
              <span className="tiny">{status === 'connected' ? 'Live stream connected' : 'Reconnecting stream'}</span>
            </div>
          </div>

          <div style={{ marginTop: 14 }}>
            <Progress value={progress} label={`${progress}% pipeline completion`} />
          </div>
        </Card>

        <div className="timeline">
          {messages.length === 0 ? (
            <Card className="timeline-card" hover={false}>
              <div className="skeleton" style={{ height: 22, width: '55%', marginBottom: 10 }} />
              <div className="skeleton" style={{ height: 16, width: '90%', marginBottom: 8 }} />
              <div className="skeleton" style={{ height: 16, width: '70%' }} />
            </Card>
          ) : null}

          {messages.map((message, index) => (
            <motion.article
              key={`${index}-${message.timestamp}`}
              className="timeline-item"
              initial={fadeInUp.initial}
              animate={fadeInUp.animate}
              transition={fadeInUp.transition}
            >
              <div className="timeline-orb">{getAgentIcon(message.agent)}</div>
              <Card className="timeline-card" hover={true}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <h3 style={{ margin: 0, fontSize: 'var(--text-h3)' }}>{message.agent || 'Agent'}</h3>
                    <Badge
                      variant={
                        message.status === 'error'
                          ? 'error'
                          : message.status === 'complete'
                            ? 'success'
                            : message.status === 'active'
                              ? 'warning'
                              : 'default'
                      }
                    >
                      {message.status || 'pending'}
                    </Badge>
                  </div>
                  {getStatusIcon(message.status)}
                </div>

                <p style={{ marginTop: 10, marginBottom: 8, fontWeight: 600 }}>{message.message || 'Processing update'}</p>
                <p className="tiny" style={{ marginTop: 0 }}>
                  Phase: {message.phase || 'pending'} • {formatTime(message.timestamp)}
                </p>

                {message.details ? (
                  <details style={{ marginTop: 8 }}>
                    <summary className="tiny" style={{ cursor: 'pointer' }}>
                      Why did this happen?
                    </summary>
                    <div
                      style={{
                        marginTop: 8,
                        border: 0,
                        borderRadius: 10,
                        background: 'rgba(30, 30, 33, 0.45)',
                        padding: 10,
                      }}
                    >
                      <pre className="mono" style={{ whiteSpace: 'pre-wrap', margin: 0, color: '#d4d4d8', fontSize: 12 }}>
                        {JSON.stringify(message.details, null, 2)}
                      </pre>
                    </div>
                  </details>
                ) : null}
              </Card>
            </motion.article>
          ))}
        </div>

        {isComplete ? (
          <motion.div initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.22 }}>
            <div className="success-box" style={{ display: 'grid', gap: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {blockingError ? <AlertCircle size={18} color="#ef4444" /> : <Check size={18} color="#10b981" />}
                <strong>{blockingError ? 'Deployment blocked' : 'Deployment complete'}</strong>
              </div>
              {blockingError ? <div className="tiny">{blockingError}</div> : null}
              {typeof deploymentUrl === 'string' ? (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
                  <span className="mono" style={{ fontSize: 12 }}>
                    {deploymentUrl}
                  </span>
                  <Button variant="ghost" onClick={copyUrl} aria-label="Copy deployment URL">
                    <Copy size={14} /> Copy
                  </Button>
                  <Button
                    variant="success"
                    onClick={() => window.open(deploymentUrl, '_blank', 'noopener,noreferrer')}
                    aria-label="Open deployed site"
                  >
                    <ExternalLink size={14} /> View Site
                  </Button>
                </div>
              ) : null}
              {typeof deploymentUrl !== 'string' && !blockingError ? <SkeletonValue width={190} height={14} /> : null}
            </div>
          </motion.div>
        ) : null}
      </div>

      <aside className="desktop-sidebar" style={{ position: 'sticky', top: 24, alignSelf: 'start', display: 'grid', gap: 16 }}>
        <Card>
          <h3 style={{ marginTop: 0 }}>Live Metrics</h3>
          <div className="metric-grid">
            <div className="metric-item">
              <div className="metric-label">Total events</div>
              <div className="metric-value">{messages.length}</div>
            </div>
            <div className="metric-item">
              <div className="metric-label">Active steps</div>
              <div className="metric-value">{active}</div>
            </div>
            <div className="metric-item">
              <div className="metric-label">Completed</div>
              <div className="metric-value" style={{ color: '#10b981' }}>
                {successful}
              </div>
            </div>
            <div className="metric-item">
              <div className="metric-label">Errors</div>
              <div className="metric-value" style={{ color: failed > 0 ? '#ef4444' : '#a1a1aa' }}>
                {failed}
              </div>
            </div>
          </div>
        </Card>

        <Card>
          <h3 style={{ marginTop: 0 }}>Pipeline story</h3>
          <p className="muted" style={{ marginTop: 8 }}>
            Intelligence agents are sequencing security, cost and deployment decisions into a single explainable timeline.
          </p>
          <div style={{ marginTop: 10 }}>
            <Badge variant="intelligence">AI Reasoning Visible</Badge>
          </div>
        </Card>
      </aside>
    </section>
  );
}
