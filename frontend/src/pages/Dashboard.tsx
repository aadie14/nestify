import React from 'react';
import axios from 'axios';
import { useParams } from 'react-router-dom';
import { Activity, Shield, Lightbulb } from 'lucide-react';
import StateMessage from '../components/ui/StateMessage';

type MonitorResponse = {
  monitoring?: {
    metrics?: { p50?: number | null; p95?: number | null; p99?: number | null; error_rate?: number | null };
    status?: string;
    recommendations?: string[];
  };
};

function fmtLatency(value: number | null | undefined): string {
  return typeof value === 'number' ? `${Math.round(value)} ms` : '-';
}

function fmtRate(value: number | null | undefined): string {
  return typeof value === 'number' ? `${(value * 100).toFixed(2)}%` : '-';
}

function normalizeStatus(value: string | undefined): string {
  const status = String(value || '').toLowerCase();
  if (status === 'healthy') return 'healthy';
  if (status === 'degraded') return 'degraded';
  return 'monitoring';
}

export default function DashboardPage() {
  const params = useParams<{ projectId: string }>();
  const projectId = Number(params.projectId || 0);

  const [payload, setPayload] = React.useState<MonitorResponse | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!projectId) return;
    let alive = true;

    const load = async (initial = false) => {
      try {
        if (initial) setLoading(true);
        const response = await axios.get(`/api/v1/projects/${projectId}/autonomous-response`);
        if (!alive) return;
        setPayload(response.data || null);
        setError(null);
      } catch {
        if (!alive) return;
        setError('Could not load monitoring data.');
      } finally {
        if (alive && initial) setLoading(false);
      }
    };

    load(true);
    const timer = window.setInterval(() => load(false), 3000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [projectId]);

  if (!projectId) return <StateMessage variant="empty" title="No project" detail="Start from Input tab." />;
  if (loading) return <StateMessage variant="loading" title="Loading monitor" detail="Collecting live metrics." />;
  if (error) return <StateMessage variant="error" title="Monitor unavailable" detail={error} />;

  const monitoring = payload?.monitoring || {};
  const metrics = monitoring.metrics || {};
  const recommendations = monitoring.recommendations || [];
  const status = normalizeStatus(monitoring.status);

  return (
    <div className="neo-page">
      <section className="neo-hero compact">
        <div className="neo-kicker">Tab 4 · Monitor</div>
        <h1>Live Runtime Observability</h1>
      </section>

      <section className="neo-stack-xl">
        <article className="neo-panel glass">
          <div className="neo-panel-head">
            <h3><Activity size={16} /> Metrics</h3>
            <span className={`neo-status ${status}`}>{status}</span>
          </div>
          <div className="neo-metric-grid">
            <div className="neo-metric-card"><span>P50</span><strong>{fmtLatency(metrics.p50)}</strong></div>
            <div className="neo-metric-card"><span>P95</span><strong>{fmtLatency(metrics.p95)}</strong></div>
            <div className="neo-metric-card"><span>P99</span><strong>{fmtLatency(metrics.p99)}</strong></div>
            <div className="neo-metric-card"><span>Error Rate</span><strong>{fmtRate(metrics.error_rate)}</strong></div>
          </div>
        </article>

        <article className="neo-panel glass">
          <div className="neo-panel-head">
            <h3><Shield size={16} /> Status</h3>
          </div>
          <div className="neo-status-board">
            <div className="neo-status-line"><span>Health</span><strong>{status}</strong></div>
            <div className="neo-status-line"><span>Latency posture</span><strong>{metrics.p95 && metrics.p95 < 400 ? 'good' : 'watch'}</strong></div>
            <div className="neo-status-line"><span>Error posture</span><strong>{metrics.error_rate && metrics.error_rate > 0.01 ? 'elevated' : 'stable'}</strong></div>
          </div>
        </article>

        <article className="neo-panel glass">
          <div className="neo-panel-head">
            <h3><Lightbulb size={16} /> Recommendations</h3>
          </div>
          <div className="neo-reco-list">
            {recommendations.length ? recommendations.slice(0, 8).map((item, idx) => (
              <div key={`${item}-${idx}`} className="neo-reco-item">{item}</div>
            )) : <div className="tiny">No recommendations currently.</div>}
          </div>
        </article>
      </section>
    </div>
  );
}
