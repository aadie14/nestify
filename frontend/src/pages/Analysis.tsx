import React from 'react';
import axios from 'axios';
import { Download, ShieldCheck, Wrench, Rocket, Activity } from 'lucide-react';
import { useParams, useNavigate } from 'react-router-dom';
import Button from '../components/ui/Button';
import StateMessage from '../components/ui/StateMessage';

type FeedItem = {
  agent?: string;
  message?: string;
  severity?: string;
  title?: string;
  status?: string;
};

type SecurityIssue = {
  severity?: string;
  title?: string;
  message?: string;
  action?: string;
};

type FixItem = {
  fix_type?: string;
  file?: string;
  status?: string;
};

type AutonomousResponse = {
  feed?: FeedItem[];
  audit?: {
    summary?: string;
    security_issues?: SecurityIssue[];
    fixes?: FixItem[];
    deployment_plan?: { platform?: string; reason?: string; confidence?: number };
  };
};

type StatusProgressItem = {
  agent?: string;
  phase?: string;
  message?: string;
  feed?: {
    agent?: string;
    title?: string;
    message?: string;
    severity?: string;
  };
  agent_event?: {
    agent?: string;
    event?: string;
    details?: string;
  };
};

type StatusResponse = {
  project?: {
    status?: string;
    execution_state?: {
      status?: string;
      step?: string;
    };
  };
  progress?: StatusProgressItem[];
};

type AnalysisStageKey = 'scan' | 'security' | 'learning' | 'planning';

type AnalysisStage = {
  key: AnalysisStageKey;
  label: string;
};

const ANALYSIS_STAGES: AnalysisStage[] = [
  { key: 'scan', label: 'Scanning' },
  { key: 'security', label: 'Security Analysis' },
  { key: 'learning', label: 'Learning Match' },
  { key: 'planning', label: 'Planning' },
];

function shortAgentName(value: string | undefined): string {
  const agent = String(value || 'system').trim();
  if (!agent) return 'system';
  return agent.length > 24 ? `${agent.slice(0, 24)}...` : agent;
}

function normalizeAgentLabel(value: string): string {
  const v = String(value || '').toLowerCase();
  if (v.includes('security')) return 'Security';
  if (v.includes('deploy') || v.includes('platform')) return 'Planner';
  if (v.includes('code') || v.includes('fix') || v.includes('simulation')) return 'Code';
  if (v.includes('cost') || v.includes('learning') || v.includes('debate')) return 'Learning';
  return 'System';
}

function oneLine(text: string, max = 110): string {
  const compact = String(text || '').replace(/\s+/g, ' ').trim();
  if (compact.length <= max) return compact;
  return `${compact.slice(0, max - 3)}...`;
}

function stageIndexFromExecution(step: string): number {
  const s = String(step || '').toLowerCase();
  if (s === 'input' || s === 'code_analysis' || s === 'execution_test') return 0;
  if (s === 'security_audit' || s === 'auto_fixes') return 1;
  if (s === 'agent_debate' || s === 'cost_analysis') return 2;
  if (s === 'deployment' || s === 'verification' || s === 'retry_loop' || s === 'monitoring' || s === 'completed') return 3;
  return 0;
}

function stageState(index: number, active: number, executionStatus: string): 'done' | 'running' | 'pending' {
  const doneStatus = ['live', 'completed', 'success'];
  const failedStatus = ['failed', 'error'];
  if (doneStatus.includes(executionStatus)) return 'done';
  if (failedStatus.includes(executionStatus)) {
    if (index < active) return 'done';
    if (index === active) return 'running';
    return 'pending';
  }
  if (index < active) return 'done';
  if (index === active) return 'running';
  return 'pending';
}

export default function AnalysisPage() {
  const params = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const projectId = Number(params.projectId || 0);

  const [payload, setPayload] = React.useState<AutonomousResponse | null>(null);
  const [statusPayload, setStatusPayload] = React.useState<StatusResponse | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!projectId) return;
    let alive = true;

    const load = async (initial = false) => {
      try {
        if (initial) setLoading(true);
        const [analysisRes, statusRes] = await Promise.all([
          axios.get(`/api/v1/projects/${projectId}/autonomous-response`),
          axios.get(`/api/status/${projectId}`),
        ]);
        if (!alive) return;
        setPayload(analysisRes.data || null);
        setStatusPayload(statusRes.data || null);
        setError(null);
      } catch {
        if (!alive) return;
        setError('Could not load analysis data.');
      } finally {
        if (alive && initial) setLoading(false);
      }
    };

    load(true);
    const timer = window.setInterval(() => load(false), 2200);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [projectId]);

  if (!projectId) return <StateMessage variant="empty" title="No project" detail="Start from Input tab." />;
  if (loading) return <StateMessage variant="loading" title="Loading analysis" detail="Building agent feed." />;
  if (error) return <StateMessage variant="error" title="Analysis unavailable" detail={error} />;

  const executionStep = String(statusPayload?.project?.execution_state?.step || '').toLowerCase();
  const executionStatus = String(statusPayload?.project?.execution_state?.status || statusPayload?.project?.status || '').toLowerCase();
  const currentStageIndex = stageIndexFromExecution(executionStep);
  const completedCount = ANALYSIS_STAGES.reduce((acc, _, idx) => {
    return stageState(idx, currentStageIndex, executionStatus) === 'done' ? acc + 1 : acc;
  }, 0);
  const baseProgress = Math.round((completedCount / ANALYSIS_STAGES.length) * 100);
  const progressMessages = (statusPayload?.progress || []) as any[];
  const latestProgress = progressMessages.length > 0 ? progressMessages[progressMessages.length - 1] : null;
  const latestProgressValue = typeof latestProgress?.progress === 'number' ? Math.max(0, Math.min(100, latestProgress.progress)) : 0;
  const analysisProgress = Math.max(baseProgress, latestProgressValue || 0);

  const rawFeed = payload?.feed || [];
  const statusFeed = (statusPayload?.progress || []).map((row) => {
    return {
      agent: String(row.agent_event?.agent || row.feed?.agent || row.agent || 'system'),
      message: String(row.agent_event?.details || row.feed?.message || row.message || row.phase || 'update'),
      severity: String(row.feed?.severity || ''),
      title: String(row.agent_event?.event || row.feed?.title || row.phase || 'update'),
      status: String(row.feed?.severity || '').toLowerCase(),
    } as FeedItem;
  });

  const seenFeed = new Set<string>();
  const feed = [...statusFeed, ...rawFeed]
    .filter((item) => {
      const agent = String(item.agent || '').toLowerCase();
      const text = `${item.title || ''} ${item.message || ''}`.toLowerCase();
      if (!agent && !text.trim()) return false;
      if (agent.includes('meta_agent')) return false;
      if (text.includes('internal reasoning')) return false;
      return true;
    })
    .filter((item) => {
      const key = `${String(item.agent || '').toLowerCase()}|${oneLine(String(item.message || item.title || ''), 70).toLowerCase()}`;
      if (seenFeed.has(key)) return false;
      seenFeed.add(key);
      return true;
    })
    .slice(-12)
    .reverse();

  const audit = payload?.audit || {};
  const issues = (audit.security_issues || []).slice(0, 8);
  const fixes = (audit.fixes || []).slice(0, 8);
  const plan = audit.deployment_plan || {};

  const canDeploy = ['security_audit', 'auto_fixes', 'deployment', 'verification', 'monitoring', 'completed', 'live'].includes(executionStep);

  return (
    <div className="neo-page">
      <section className="neo-hero compact">
        <div className="neo-kicker">Tab 2 · Analysis</div>
        <h1>Agent Intelligence View</h1>
      </section>

      <section className="neo-grid-analysis">
        <div className="neo-panel glass">
          <div className="neo-panel-head">
            <h3>Analysis Progress</h3>
            {canDeploy ? (
              <Button variant="primary" onClick={() => navigate(`/deployment/${projectId}`)}>
                Go To Deploy
              </Button>
            ) : null}
          </div>
          <div className="neo-progress-wrap" aria-label="Analysis completion progress">
            <div className="neo-progress-head">
              <span>Real-time stage progress</span>
              <strong>{analysisProgress}%</strong>
            </div>
            <div className="neo-progress-track">
              <div className="neo-progress-fill" style={{ width: `${analysisProgress}%` }} />
            </div>
          </div>

          <div className="neo-stage-grid" style={{ marginTop: 12, marginBottom: 12 }}>
            {ANALYSIS_STAGES.map((stage, idx) => {
              const state = stageState(idx, currentStageIndex, executionStatus);
              return (
                <div key={stage.key} className={`neo-stage-chip ${state}`}>
                  <span>{state === 'done' ? '✔' : state === 'running' ? '⏳' : '•'}</span>
                  <strong>{stage.label}</strong>
                </div>
              );
            })}
          </div>

          <div className="neo-panel-head" style={{ marginTop: 2 }}>
            <h3>Clean Agent Feed</h3>
            <span className="neo-cap">Max 1 line per event</span>
          </div>
          <div className="neo-feed-list">
            {feed.length ? feed.map((item, idx) => (
              <article key={`${idx}-${item.agent}-${item.message}`} className="neo-feed-card">
                <div className="neo-feed-msg">
                  [{normalizeAgentLabel(shortAgentName(item.agent))}] {oneLine(String(item.message || item.title || 'update'))}
                </div>
              </article>
            )) : <div className="tiny">Waiting for feed events...</div>}
          </div>
        </div>

        <aside className="neo-panel glass neo-audit-panel">
          <div className="neo-panel-head">
            <h3>Audit Panel</h3>
            <a className="neo-link-btn" href={`/api/v1/projects/${projectId}/report/pdf`} target="_blank" rel="noreferrer">
              <Download size={14} /> Download Full Audit Report
            </a>
          </div>

          <div className="neo-audit-section">
            <div className="neo-audit-title"><ShieldCheck size={14} /> Security Issues</div>
            <div className="neo-audit-list">
              {issues.length ? issues.map((item, idx) => (
                <div key={`${item.title}-${idx}`} className="neo-audit-item">
                  <span className={`neo-status ${String(item.severity || 'info').toLowerCase()}`}>{String(item.severity || 'info')}</span>
                  <div>{String(item.title || item.message || 'Security issue')}</div>
                </div>
              )) : <div className="tiny">No active issues</div>}
            </div>
          </div>

          <div className="neo-audit-section">
            <div className="neo-audit-title"><Wrench size={14} /> Fixes</div>
            <div className="neo-audit-list">
              {fixes.length ? fixes.map((item, idx) => (
                <div key={`${item.fix_type}-${idx}`} className="neo-audit-item">
                  <span className="neo-status ok">fix</span>
                  <div>{`${item.fix_type || 'remediation'} · ${item.file || 'unknown file'}`}</div>
                </div>
              )) : <div className="tiny">No fixes logged</div>}
            </div>
          </div>

          <div className="neo-audit-section">
            <div className="neo-audit-title"><Rocket size={14} /> Deployment Plan</div>
            <div className="neo-plan-mini">
              <div><span>Platform</span><strong>{plan.platform || 'pending'}</strong></div>
              <div><span>Confidence</span><strong>{typeof plan.confidence === 'number' ? `${Math.round(plan.confidence * 100)}%` : '-'}</strong></div>
              <div><span>Reason</span><strong>{String(plan.reason || 'Autonomous provider selection').slice(0, 90)}</strong></div>
            </div>
          </div>

          <div className="neo-audit-summary">
            <Activity size={14} />
            <span>{String(audit.summary || 'Analysis complete.').slice(0, 120)}</span>
          </div>
        </aside>
      </section>
    </div>
  );
}
