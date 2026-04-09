import React from 'react';
import axios from 'axios';
import { useParams } from 'react-router-dom';
import Card from '../components/ui/Card';
import Badge from '../components/ui/Badge';
import StateMessage from '../components/ui/StateMessage';

type MonitorResponse = {
  monitoring?: {
    metrics?: { p50?: number | null; p95?: number | null; p99?: number | null; error_rate?: number | null };
    status?: string;
    recommendations?: string[];
  };
};

function fmtLatency(value: number | null | undefined) {
  if (typeof value !== 'number') return '-';
  return `${Math.round(value)} ms`;
}

function fmtRate(value: number | null | undefined) {
  if (typeof value !== 'number') return '-';
  return `${(value * 100).toFixed(2)}%`;
}

export default function DashboardPage() {
  const params = useParams<{ projectId: string }>();
  const projectId = Number(params.projectId || 0);

  const [data, setData] = React.useState<MonitorResponse | null>(null);
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
        setData(response.data || null);
        setError(null);
      } catch {
        if (!alive) return;
        setError('Could not load monitoring data. Verify backend and retry.');
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

  if (!projectId) {
    return <StateMessage variant="empty" title="No project selected" detail="Run analysis and deploy before monitoring." />;
  }

  if (loading) {
    return <StateMessage variant="loading" title="Loading monitoring" detail="Collecting runtime metrics and recommendations." />;
  }

  if (error) {
    return <StateMessage variant="error" title="Monitor unavailable" detail={error} />;
  }

  const monitoring = data?.monitoring || {};
  const metrics = monitoring.metrics || {};
  const health = String(monitoring.status || 'degraded').toLowerCase();
  const recommendations = monitoring.recommendations || [];

  return (
    <div className="focus-shell">
      <section className="focus-primary">
        <Card>
          <div className="section-head">
            <h2>Monitor</h2>
            <Badge variant={health === 'healthy' ? 'success' : 'warning'}>{health.toUpperCase()}</Badge>
          </div>

          <div className="grid-4">
            <div className="metric-item">
              <div className="metric-label">p50</div>
              <div className="metric-value">{fmtLatency(metrics.p50)}</div>
            </div>
            <div className="metric-item">
              <div className="metric-label">p95</div>
              <div className="metric-value">{fmtLatency(metrics.p95)}</div>
            </div>
            <div className="metric-item">
              <div className="metric-label">p99</div>
              <div className="metric-value">{fmtLatency(metrics.p99)}</div>
            </div>
            <div className="metric-item">
              <div className="metric-label">Error Rate</div>
              <div className="metric-value">{fmtRate(metrics.error_rate)}</div>
            </div>
          </div>
        </Card>
      </section>

      <Card>
        <h3>Recommendations</h3>
        <div className="stack-list">
          {recommendations.length ? recommendations.map((item, idx) => (
            <div key={`${item}-${idx}`} className="audit-row">
              <Badge variant="intelligence">REC</Badge>
              <div className="audit-title">{item}</div>
            </div>
          )) : <div className="tiny">No recommendations right now.</div>}
        </div>
      </Card>
    </div>
  );
}
