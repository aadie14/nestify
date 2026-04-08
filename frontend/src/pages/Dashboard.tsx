import React from 'react';
import axios from 'axios';
import { AlertTriangle, Gauge, RefreshCcw, RotateCcw, ShieldCheck, Undo2 } from 'lucide-react';
import { useParams } from 'react-router-dom';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import StateMessage from '../components/ui/StateMessage';
import { formatCurrency, formatPercent, toTitleCase } from '../utils/formatters';

export default function DashboardPage() {
  const params = useParams<{ projectId: string }>();
  const projectId = Number(params.projectId || 0);
  const [reportData, setReportData] = React.useState<any>(null);
  const [statusData, setStatusData] = React.useState<any>(null);
  const [optimizationData, setOptimizationData] = React.useState<any>(null);
  const [actionError, setActionError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [actionFeedback, setActionFeedback] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!projectId) return;
    let alive = true;

    const load = async () => {
      try {
        setLoading(true);
        const [report, status, optimization] = await Promise.all([
          axios.get(`/api/v1/projects/${projectId}/report`),
          axios.get(`/api/v1/projects/${projectId}/status`),
          axios.get(`/api/v1/optimization/${projectId}`),
        ]);
        if (!alive) return;
        setReportData(report.data || null);
        setStatusData(status.data || null);
        setOptimizationData(optimization.data || null);
        setLoadError(null);
      } catch {
        if (!alive) return;
        setLoadError('Could not load dashboard telemetry. Next: confirm the backend API is reachable, then refresh.');
      } finally {
        if (alive) setLoading(false);
      }
    };

    load();
    const timer = window.setInterval(load, 4000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [projectId]);

  const controlRequest = async (action: 'restart' | 'redeploy' | 'stop') => {
    try {
      setActionError(null);
      setActionFeedback(`${toTitleCase(action)} request received. Applying changes now...`);
      await axios.post(`/api/v1/projects/${projectId}/${action}`);
      const status = await axios.get(`/api/v1/projects/${projectId}/status`);
      setStatusData(status.data || null);
      setActionFeedback(`${toTitleCase(action)} completed. Telemetry has been refreshed.`);
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      setActionError(typeof detail === 'string' && detail.trim() ? `${detail} Next: validate deployment health and retry ${action}.` : `Could not ${action}. Next: check service status and retry.`);
      setActionFeedback(null);
    }
  };

  const insights = reportData?.agentic_insights || {};
  const runtime = insights?.production_insights?.metrics || {};
  const p95 = Number(runtime?.p95_ms || 0);
  const errorRate = Number(runtime?.error_rate || 0);
  const findings = reportData?.findings || {};
  const critical = Number((findings?.critical || []).length || 0);
  const high = Number((findings?.high || []).length || 0);
  const medium = Number((findings?.medium || []).length || 0);
  const provider = optimizationData?.provider || insights?.deployment_intelligence?.chosen_platform || 'pending';
  const recommendedCost = optimizationData?.monthly_cost_usd;
  const recommendedConfig = optimizationData?.recommended_resource_config || {};
  const currentConfig = optimizationData?.current_resource_config || {};

  if (!projectId) {
    return (
      <StateMessage
        variant="empty"
        title="Upload a project to begin"
        detail="Create a project from Upload before opening the monitor dashboard."
      />
    );
  }

  return (
    <div className="focus-shell">
      <section className="focus-primary">
      {loading ? (
        <StateMessage
          variant="loading"
          title="Refreshing runtime telemetry"
          detail="Updating health, risk, and cost insights in real time."
        />
      ) : null}

      {loadError ? (
        <StateMessage
          variant="error"
          title="Telemetry unavailable"
          detail={loadError}
        />
      ) : null}

      {actionFeedback ? (
        <StateMessage
          variant="success"
          title="Action update"
          detail={actionFeedback}
        />
      ) : null}

      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 'var(--text-h1)' }}>AI Operations Summary</h1>
            <div className="tiny" style={{ marginTop: 6 }}>
              Nestify is continuously evaluating runtime health, risk, and cost posture for this deployment.
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <Button variant="secondary" onClick={() => controlRequest('restart')}>
              <RotateCcw size={14} /> Restart
            </Button>
            <Button variant="ghost" onClick={() => controlRequest('redeploy')}>
              <RefreshCcw size={14} /> Redeploy
            </Button>
            <Button variant="ghost" disabled>
              <Undo2 size={14} /> Rollback
            </Button>
          </div>
        </div>
        {actionError ? (
          <StateMessage
            variant="error"
            title="Action could not be completed"
            detail={actionError}
            className="fade-in"
          />
        ) : null}

        <div className="grid-3" style={{ marginTop: 12 }}>
          <div className="metric-item">
            <div className="metric-label">Runtime state</div>
            <div className="metric-value">{toTitleCase(String(statusData?.status || 'monitoring'))}</div>
          </div>
          <div className="metric-item">
            <div className="metric-label">P95 latency</div>
            <div className="metric-value">{p95 ? `${p95.toFixed(0)} ms` : 'Calculating...'}</div>
          </div>
          <div className="metric-item">
            <div className="metric-label">Error rate</div>
            <div className="metric-value" style={{ color: errorRate > 0.05 ? 'var(--brand-error)' : errorRate > 0.02 ? 'var(--brand-warning)' : 'var(--brand-primary)' }}>
              {formatPercent(errorRate, 2)}
            </div>
          </div>
        </div>
      </Card>
      </section>

      <details className="progressive-details">
        <summary>Runtime, security, and cost details</summary>
        <div className="progressive-details-body">
          <section className="grid-2">
            <Card>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Gauge size={16} color="var(--brand-primary)" />
                <h3 style={{ margin: 0 }}>Runtime Health</h3>
              </div>
              <div className="grid-2" style={{ marginTop: 12 }}>
                <div className="metric-item">
                  <div className="metric-label">P95 Latency</div>
                  <div className="metric-value">{p95 ? `${p95.toFixed(0)} ms` : 'Calculating...'}</div>
                </div>
                <div className="metric-item">
                  <div className="metric-label">Error Rate</div>
                  <div className="metric-value" style={{ color: errorRate > 0.05 ? 'var(--brand-error)' : errorRate > 0.02 ? 'var(--brand-warning)' : 'var(--brand-primary)' }}>
                    {formatPercent(errorRate, 2)}
                  </div>
                </div>
              </div>
              <div className="tiny" style={{ marginTop: 10 }}>
                Status: {toTitleCase(String(statusData?.status || 'monitoring'))}
              </div>
            </Card>

            <Card>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <ShieldCheck size={16} color="var(--brand-primary)" />
                <h3 style={{ margin: 0 }}>Security Findings Summary</h3>
              </div>
              <div className="grid-3" style={{ marginTop: 12 }}>
                <div className="metric-item">
                  <div className="metric-label">Critical</div>
                  <div className="metric-value" style={{ color: 'var(--brand-error)' }}>{critical}</div>
                </div>
                <div className="metric-item">
                  <div className="metric-label">High</div>
                  <div className="metric-value" style={{ color: 'var(--brand-warning)' }}>{high}</div>
                </div>
                <div className="metric-item">
                  <div className="metric-label">Medium</div>
                  <div className="metric-value">{medium}</div>
                </div>
              </div>
            </Card>
          </section>

          <Card>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <AlertTriangle size={16} color="var(--brand-primary)" />
              <h3 style={{ margin: 0 }}>Cost Optimization Recommendations</h3>
            </div>
            <div className="grid-3" style={{ marginTop: 12 }}>
              <div className="metric-item">
                <div className="metric-label">Provider</div>
                <div className="metric-value">{toTitleCase(String(provider || 'pending'))}</div>
              </div>
              <div className="metric-item">
                <div className="metric-label">Estimated Monthly Cost</div>
                <div className="metric-value">{recommendedCost != null ? formatCurrency(recommendedCost) : 'Calculating...'}</div>
              </div>
              <div className="metric-item">
                <div className="metric-label">Recommended Config</div>
                <div className="metric-value">{recommendedConfig?.memory_mb ? `${recommendedConfig.memory_mb}MB / ${Number(recommendedConfig.cpu || 0).toFixed(2)} vCPU` : 'Calculating...'}</div>
              </div>
            </div>
            <div className="tiny" style={{ marginTop: 10 }}>
              Current config: {currentConfig?.memory_mb ? `${currentConfig.memory_mb}MB / ${Number(currentConfig.cpu || 0).toFixed(2)} vCPU` : 'Unavailable'}
            </div>
          </Card>
        </div>
      </details>
    </div>
  );
}
