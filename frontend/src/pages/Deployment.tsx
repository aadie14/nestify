import React from 'react';
import axios from 'axios';
import { useParams } from 'react-router-dom';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import StateMessage from '../components/ui/StateMessage';
import AgentFeedCards, { FeedItem } from '../components/AgentFeedCards';

type Attempt = {
  attempt?: number;
  provider?: string;
  status?: string;
  reason?: string;
  fix_applied?: string | null;
};

type DeployResponse = {
  feed?: FeedItem[];
  deployment?: {
    status?: string;
    attempts?: Attempt[];
    final_url?: string | null;
    failure_reason?: string | null;
  };
};

const STEPS = [
  'Applying fixes',
  'Running tests',
  'Security validation',
  'Deployment',
  'Monitoring',
];

function stepState(index: number, status: string) {
  const s = String(status || '').toLowerCase();
  if (s === 'success') return index < STEPS.length ? 'done' : 'todo';
  if (s === 'failed') return index < 3 ? 'done' : index === 3 ? 'failed' : 'todo';
  return index === 0 ? 'running' : 'todo';
}

export default function DeploymentPage() {
  const params = useParams<{ projectId: string }>();
  const projectId = Number(params.projectId || 0);

  const [data, setData] = React.useState<DeployResponse | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [running, setRunning] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async (initial = false) => {
    if (!projectId) return;
    try {
      if (initial) setLoading(true);
      const response = await axios.get(`/api/v1/projects/${projectId}/autonomous-response`);
      setData(response.data || null);
      setError(null);
    } catch {
      setError('Could not load deploy workspace. Verify backend and retry.');
    } finally {
      if (initial) setLoading(false);
    }
  }, [projectId]);

  React.useEffect(() => {
    if (!projectId) return;
    let alive = true;
    const tick = async () => {
      if (!alive) return;
      await load(false);
    };

    load(true);
    const timer = window.setInterval(tick, 2500);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [projectId, load]);

  const runDeploy = async () => {
    if (!projectId || running) return;
    try {
      setRunning(true);
      setError(null);
      await axios.post(`/api/v1/projects/${projectId}/autonomous-fix-deploy`, {});
      await load(false);
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Autonomous deployment failed to start.');
    } finally {
      setRunning(false);
    }
  };

  if (!projectId) {
    return <StateMessage variant="empty" title="No project selected" detail="Start from Input and Analysis first." />;
  }

  if (loading) {
    return <StateMessage variant="loading" title="Loading deployment" detail="Preparing steps and attempt timeline." />;
  }

  if (error) {
    return <StateMessage variant="error" title="Deploy unavailable" detail={error} />;
  }

  const deployment = data?.deployment || {};
  const attempts = deployment.attempts || [];
  const status = String(deployment.status || 'failed').toLowerCase();
  const feed = data?.feed || [];

  return (
    <div className="analysis-shell">
      <section className="analysis-center">
        <Card>
          <div className="section-head">
            <h2>Deploy</h2>
            <Button variant="primary" loading={running} onClick={runDeploy}>Start Autonomous Deploy</Button>
          </div>

          <div className="deploy-steps">
            {STEPS.map((step, idx) => {
              const state = stepState(idx, status);
              return (
                <div key={step} className={`deploy-step ${state}`}>
                  <span className="deploy-dot" />
                  <span>{step}</span>
                  {state === 'done' ? <Badge variant="success">Done</Badge> : null}
                  {state === 'running' ? <Badge variant="intelligence">Running</Badge> : null}
                  {state === 'failed' ? <Badge variant="error">Failed</Badge> : null}
                </div>
              );
            })}
          </div>
        </Card>

        <Card>
          <h3>Deployment Attempts</h3>
          <div className="stack-list">
            {attempts.length ? attempts.map((attempt, idx) => (
              <div key={`${attempt.attempt}-${idx}`} className="attempt-row">
                <div>
                  <div className="audit-title">Attempt {attempt.attempt || idx + 1}</div>
                  <div className="tiny">{attempt.provider || 'auto'} • {attempt.reason || 'execution update'}</div>
                  {attempt.fix_applied ? <div className="tiny">Fix applied: {attempt.fix_applied}</div> : null}
                </div>
                <Badge variant={String(attempt.status || '').toLowerCase() === 'success' ? 'success' : 'warning'}>
                  {String(attempt.status || 'running').toUpperCase()}
                </Badge>
              </div>
            )) : <div className="tiny">No attempts recorded yet.</div>}
          </div>
        </Card>

        <Card>
          <h3>Agent Feed</h3>
          <AgentFeedCards items={feed} maxItems={8} />
        </Card>
      </section>

      <aside className="analysis-right">
        <Card>
          <h3>Final Result</h3>
          <div className="stack-list">
            <div className="audit-row">
              <Badge variant={status === 'success' ? 'success' : 'error'}>{status.toUpperCase()}</Badge>
              <div className="audit-title">{status === 'success' ? 'Deployment live' : 'Deployment blocked'}</div>
            </div>
            <div className="tiny">URL: {deployment.final_url || 'Not available'}</div>
            {deployment.failure_reason ? <div className="tiny">Reason: {deployment.failure_reason}</div> : null}
            <div className="tiny">Confidence: {status === 'success' ? 'High' : 'Medium'}</div>
          </div>
        </Card>
      </aside>
    </div>
  );
}
