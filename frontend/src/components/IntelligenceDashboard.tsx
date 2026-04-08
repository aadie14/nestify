import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { Activity, AlertTriangle, ShieldCheck, Sparkles } from 'lucide-react';
import { useDeployment } from '../hooks/useDeployment';
import CostOptimizer from './CostOptimizer';
import LearningStats from './LearningStats';
import LearningProofCard from './LearningProofCard';
import PatternExplorer from './PatternExplorer';
import Card from './ui/Card';
import Badge from './ui/Badge';
import SkeletonValue from './ui/SkeletonValue';
import { formatPercent, toTitleCase } from '../utils/formatters';

type Props = { projectId: number };

export default function IntelligenceDashboard({ projectId }: Props) {
  const { deployment, loading, error } = useDeployment(projectId);
  const [optimization, setOptimization] = useState<any>(null);

  useEffect(() => {
    axios
      .get(`/api/v1/optimization/${projectId}/analyze`)
      .then((res) => setOptimization(res.data))
      .catch(() => setOptimization(null));
  }, [projectId]);

  const applyOptimization = async () => {
    await axios.post(`/api/v1/agentic/optimize/${projectId}`, {});
    const refreshed = await axios.get(`/api/v1/optimization/${projectId}/analyze`);
    setOptimization(refreshed.data);
  };

  const insights = (deployment?.project?.agentic_insights || {}) as Record<string, any>;
  const codeProfile = (insights.code_profile || {}) as Record<string, any>;
  const security = (insights.security_reasoning || {}) as Record<string, any>;
  const production = (insights.production_insights || {}) as Record<string, any>;
  const p95 = Number(production?.metrics?.p95_ms || 0);
  const errorRate = Number(production?.metrics?.error_rate || 0);

  const liveStatusColor = errorRate > 0.08 ? '#ef4444' : errorRate > 0.02 ? '#f59e0b' : 'var(--brand-primary)';

  return (
    <div className="page">
      <Card hover={false}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 'var(--text-h1)' }}>Intelligence Dashboard</h1>
            <p className="muted" style={{ marginTop: 8 }}>
              Live deployment intelligence and post-release optimization telemetry
            </p>
            {deployment?.project?.public_url ? (
              <div className="tiny mono" style={{ marginTop: 8 }}>
                {deployment.project.public_url}
              </div>
            ) : null}
          </div>
          <Badge variant="intelligence">
            <Sparkles size={14} /> Always-On Agentic Engine
          </Badge>
        </div>
        {loading ? <div className="tiny" style={{ marginTop: 8 }}>Loading deployment...</div> : null}
        {error ? <div style={{ marginTop: 8, color: '#ef4444', fontSize: 13 }}>{error}</div> : null}
      </Card>

      <div className="grid-2">
        <div className="page">
          <CostOptimizer optimization={optimization} onApply={applyOptimization} />
          <PatternExplorer projectId={projectId} />
        </div>

        <div className="page">
          <Card>
            <h3 style={{ marginTop: 0, marginBottom: 12 }}>Production Metrics</h3>
            <div className="metric-grid">
              <div className="metric-item">
                <div className="metric-label">P95 Latency</div>
                <div className="metric-value">{p95 ? `${p95.toFixed(0)} ms` : <SkeletonValue width={64} />}</div>
              </div>
              <div className="metric-item">
                <div className="metric-label">Error Rate</div>
                <div className="metric-value" style={{ color: liveStatusColor }}>
                  {formatPercent(errorRate, 2)}
                </div>
              </div>
              <div className="metric-item">
                <div className="metric-label">Framework</div>
                <div className="metric-value">{toTitleCase(String(codeProfile.framework || 'unknown'))}</div>
              </div>
              <div className="metric-item">
                <div className="metric-label">Runtime</div>
                <div className="metric-value">{toTitleCase(String(codeProfile.runtime || 'unknown'))}</div>
              </div>
            </div>
          </Card>

          <Card>
            <h3 style={{ marginTop: 0, marginBottom: 12 }}>Security Findings</h3>
            <div style={{ display: 'grid', gap: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <ShieldCheck size={16} color="var(--brand-primary)" />
                <span className="tiny">Contextual security enrichment active</span>
              </div>
              <div style={{ border: 0, borderRadius: 10, padding: 12, background: 'rgba(30,30,33,0.5)' }}>
                <div className="tiny">Why dangerous</div>
                <p style={{ marginTop: 8, marginBottom: 0 }}>
                  {String(security.summary || 'Security reasoning will appear here as findings are enriched.')}
                </p>
              </div>
            </div>
          </Card>

          <Card>
            <h3 style={{ marginTop: 0, marginBottom: 12 }}>Deployment Health</h3>
            <div style={{ display: 'grid', gap: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Activity size={16} color="var(--brand-primary)" />
                <span className="tiny">Runtime monitoring connected</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <AlertTriangle size={16} color="#f59e0b" />
                <span className="tiny">Anomaly watchlist auto-populated from previous patterns</span>
              </div>
            </div>
          </Card>
        </div>
      </div>

      <LearningStats />
      <LearningProofCard />
    </div>
  );
}
