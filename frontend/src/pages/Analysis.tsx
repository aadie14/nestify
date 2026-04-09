import React from 'react';
import axios from 'axios';
import { useParams, useNavigate } from 'react-router-dom';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import StateMessage from '../components/ui/StateMessage';
import AgentFeedCards, { FeedItem } from '../components/AgentFeedCards';

type AutonomousResponse = {
  feed?: FeedItem[];
  audit?: {
    summary?: string;
    security_issues?: Array<{
      severity?: string;
      title?: string;
      message?: string;
      action?: string;
    }>;
    fixes?: Array<{ fix_type?: string; file?: string; status?: string; note?: string }>;
    deployment_plan?: { platform?: string; reason?: string; confidence?: number };
    cost_estimate?: { provider?: string; monthly_cost_usd?: number; config?: { memory_mb?: number; cpu?: number } };
    confidence_score?: number;
  };
};

type ReportResponse = {
  code_profile?: {
    graph_nodes?: number;
    graph_edges?: number;
    files_scanned?: number;
  };
};

function severityBadge(value: string) {
  const s = String(value || '').toLowerCase();
  if (s === 'high' || s === 'critical') return 'error';
  if (s === 'medium') return 'warning';
  return 'intelligence';
}

export default function AnalysisPage() {
  const params = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const projectId = Number(params.projectId || 0);

  const [data, setData] = React.useState<AutonomousResponse | null>(null);
  const [report, setReport] = React.useState<ReportResponse | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!projectId) return;
    let alive = true;

    const load = async (initial = false) => {
      try {
        if (initial) setLoading(true);
        const [autonomous, rep] = await Promise.all([
          axios.get(`/api/v1/projects/${projectId}/autonomous-response`),
          axios.get(`/api/v1/projects/${projectId}/report`),
        ]);
        if (!alive) return;
        setData(autonomous.data || null);
        setReport(rep.data || null);
        setError(null);
      } catch {
        if (!alive) return;
        setError('Could not load analysis workspace. Verify backend and retry.');
      } finally {
        if (alive && initial) setLoading(false);
      }
    };

    load(true);
    const timer = window.setInterval(() => load(false), 2500);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [projectId]);

  if (!projectId) {
    return <StateMessage variant="empty" title="No project selected" detail="Open Input and create a project first." />;
  }

  if (loading) {
    return <StateMessage variant="loading" title="Loading analysis" detail="Preparing agent feed and audit panels." />;
  }

  if (error) {
    return <StateMessage variant="error" title="Analysis unavailable" detail={error} />;
  }

  const feed = data?.feed || [];
  const audit = data?.audit || {};
  const issues = audit.security_issues || [];
  const fixes = audit.fixes || [];
  const deploymentPlan = audit.deployment_plan || {};
  const cost = audit.cost_estimate || {};

  return (
    <div className="analysis-shell">
      <section className="analysis-center">
        <Card>
          <div className="section-head">
            <h2>Analysis Feed</h2>
            <Button variant="primary" onClick={() => navigate(`/deployment/${projectId}`)}>Go To Deploy</Button>
          </div>
          <AgentFeedCards items={feed} maxItems={12} />
        </Card>

        <Card>
          <div className="section-head">
            <h3>Graph View</h3>
            <Badge variant="intelligence">Optional</Badge>
          </div>
          <div className="grid-3">
            <div className="metric-item">
              <div className="metric-label">Files</div>
              <div className="metric-value">{report?.code_profile?.files_scanned ?? '-'}</div>
            </div>
            <div className="metric-item">
              <div className="metric-label">Nodes</div>
              <div className="metric-value">{report?.code_profile?.graph_nodes ?? '-'}</div>
            </div>
            <div className="metric-item">
              <div className="metric-label">Edges</div>
              <div className="metric-value">{report?.code_profile?.graph_edges ?? '-'}</div>
            </div>
          </div>
        </Card>
      </section>

      <aside className="analysis-right">
        <Card>
          <h3>Audit</h3>
          <div className="tiny">{audit.summary || 'Structured audit ready.'}</div>
        </Card>

        <Card>
          <h3>Security Issues</h3>
          <div className="stack-list">
            {issues.length ? issues.slice(0, 8).map((issue, idx) => (
              <div key={`${issue.title}-${idx}`} className="audit-row">
                <Badge variant={severityBadge(issue.severity || 'info') as any}>{String(issue.severity || 'info').toUpperCase()}</Badge>
                <div>
                  <div className="audit-title">{issue.title || 'Issue'}</div>
                  <div className="tiny">{issue.message || 'Detected issue'}</div>
                </div>
              </div>
            )) : <div className="tiny">No critical findings.</div>}
          </div>
        </Card>

        <Card>
          <h3>Suggested Fixes</h3>
          <div className="stack-list">
            {fixes.length ? fixes.slice(0, 8).map((fix, idx) => (
              <div key={`${fix.file}-${idx}`} className="audit-row">
                <Badge variant="intelligence">FIX</Badge>
                <div>
                  <div className="audit-title">{fix.fix_type || 'remediation'}</div>
                  <div className="tiny">{fix.file || 'unknown file'}</div>
                </div>
              </div>
            )) : <div className="tiny">No fix entries yet.</div>}
          </div>
        </Card>

        <Card>
          <h3>Deployment Plan</h3>
          <div className="stack-list">
            <div className="audit-row">
              <Badge variant="success">PLATFORM</Badge>
              <div className="audit-title">{deploymentPlan.platform || 'pending'}</div>
            </div>
            <div className="tiny">{deploymentPlan.reason || 'Provider selected from profile, risk, and cost signals.'}</div>
          </div>
        </Card>

        <Card>
          <h3>Cost Estimate</h3>
          <div className="grid-2">
            <div className="metric-item">
              <div className="metric-label">Provider</div>
              <div className="metric-value">{cost.provider || '-'}</div>
            </div>
            <div className="metric-item">
              <div className="metric-label">Monthly</div>
              <div className="metric-value">{typeof cost.monthly_cost_usd === 'number' ? `$${cost.monthly_cost_usd.toFixed(2)}` : '-'}</div>
            </div>
          </div>
        </Card>

        <Card>
          <h3>Confidence Score</h3>
          <div className="metric-value">{typeof audit.confidence_score === 'number' ? `${Math.round(audit.confidence_score * 100)}%` : '-'}</div>
        </Card>
      </aside>
    </div>
  );
}
