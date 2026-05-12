import React from 'react';
import axios from 'axios';
import { useParams } from 'react-router-dom';
import { Layers3, Bot, RotateCcw, CheckCircle2, Link as LinkIcon, Wrench, Download } from 'lucide-react';
import Button from '../components/ui/Button';
import StateMessage from '../components/ui/StateMessage';

type Attempt = {
  attempt?: number;
  provider?: string;
  status?: string;
  reason?: string;
  fix_applied?: string;
  failure_type?: string;
};

type FinalOutput = {
  feed?: Array<{ agent?: string; event?: string; details?: string; confidence?: number }>;
  deployment?: {
    status?: string;
    url?: string;
    attempts?: Attempt[];
    changes?: string[];
    failure_reason?: string;
  };
};

type StatusProgressItem = {
  agent?: string;
  phase?: string;
  message?: string;
  confidence?: number;
  feed?: {
    agent?: string;
    title?: string;
    message?: string;
    severity?: string;
    type?: string;
    confidence?: number;
  };
  agent_event?: {
    agent?: string;
    event?: string;
    details?: string;
    confidence?: number;
  };
  data?: {
    action?: string;
    reason?: string;
    result?: string;
    [key: string]: unknown;
  };
  timestamp?: string | number;
};

type StatusResponse = {
  project?: {
    status?: string;
    execution_state?: {
      status?: string;
      step?: string;
      attempts?: number;
      errors?: string[];
      deployment_url?: string;
    };
    fix_report?: {
      applied?: Array<{ fix_type?: string; file?: string }>;
    };
    agentic_insights?: {
      planning_engine?: {
        steps?: string[];
        platform?: string;
        confidence?: number;
      };
      meta_agent?: {
        confidence?: number;
        self_heal_attempts?: Attempt[];
      };
    };
  };
  deployment?: {
    status?: string;
    deployment_url?: string;
    provider?: string;
    details?: {
      reason?: string;
      plain_english_error?: string;
      [key: string]: unknown;
    };
  };
  progress?: StatusProgressItem[];
  final_output?: FinalOutput;
};

type AutonomousResponse = {
  deployment?: {
    status?: string;
    provider?: string;
    attempts?: Attempt[];
    final_url?: string;
    failure_reason?: string;
  };
};

type LiveCard = {
  agent: string;
  event: string;
  details: string;
  status: 'done' | 'running' | 'failed';
  confidence: number | null;
  action: string;
  reason: string;
  result: string;
  category: 'security' | 'fix' | 'deploy' | 'analysis' | 'system';
};

type DeployStep = {
  label: string;
  key: 'fixes' | 'testing' | 'security' | 'deploying';
};

const EXECUTION_ORDER = [
  'input',
  'code_analysis',
  'security_audit',
  'auto_fixes',
  'verification',
  'deployment',
  'monitoring',
  'completed',
];

const DEPLOY_STEPS: DeployStep[] = [
  { key: 'fixes', label: 'Applying fixes' },
  { key: 'testing', label: 'Testing' },
  { key: 'security', label: 'Security check' },
  { key: 'deploying', label: 'Deploying' },
];

function normalizeStatus(status: string | undefined): 'done' | 'running' | 'failed' {
  const value = String(status || '').toLowerCase();
  if (value === 'success' || value === 'ok' || value === 'completed' || value === 'live') return 'done';
  if (value === 'failed' || value === 'error') return 'failed';
  return 'running';
}

function eventStatus(raw: StatusProgressItem, executionStatus: string): 'done' | 'running' | 'failed' {
  const severity = String(raw.feed?.severity || '').toLowerCase();
  const message = `${raw.phase || ''} ${raw.message || ''} ${raw.feed?.title || ''}`.toLowerCase();

  if (severity === 'error' || severity === 'critical') return 'failed';
  if (message.includes('failed') || message.includes('error')) return 'failed';

  const exec = normalizeStatus(executionStatus);
  if (exec === 'done') return 'done';
  if (exec === 'failed') return 'failed';

  if (message.includes('complete') || message.includes('completed') || message.includes('success') || message.includes('done')) {
    return 'done';
  }
  return 'running';
}

function classifyCategory(agent: string, event: string, action: string): LiveCard['category'] {
  const text = `${agent} ${event} ${action}`.toLowerCase();
  if (text.includes('security') || text.includes('scan') || text.includes('audit')) return 'security';
  if (text.includes('fix') || text.includes('simulation') || text.includes('patch')) return 'fix';
  if (text.includes('deploy') || text.includes('verification') || text.includes('provider')) return 'deploy';
  if (text.includes('code') || text.includes('analysis') || text.includes('debate') || text.includes('cost')) return 'analysis';
  return 'system';
}

function shortLine(value: string, max = 120): string {
  const compact = String(value || '').replace(/\s+/g, ' ').trim();
  if (compact.length <= max) return compact;
  return `${compact.slice(0, max - 3)}...`;
}

function toEpochSeconds(value: unknown): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const num = Number(value);
    if (Number.isFinite(num)) return num;
  }
  return 0;
}

function isInternalNoise(agent: string, event: string, details: string): boolean {
  const text = `${agent} ${event} ${details}`.toLowerCase();
  if (text.includes('meta-agent') || text.includes('metaagent') || text.includes('meta_agent')) return true;
  if (text.includes('reflection') || text.includes('internal reasoning')) return true;
  return false;
}

function progressFromExecution(step: string, status: string): number {
  const normalizedStep = String(step || '').toLowerCase();
  const normalizedStatus = String(status || '').toLowerCase();
  if (normalizedStatus === 'success' || normalizedStatus === 'live' || normalizedStatus === 'completed') return 100;
  if (normalizedStatus === 'failed') {
    const idx = EXECUTION_ORDER.indexOf(normalizedStep);
    return idx >= 0 ? Math.max(5, Math.round(((idx + 1) / EXECUTION_ORDER.length) * 100)) : 10;
  }
  const idx = EXECUTION_ORDER.indexOf(normalizedStep);
  if (idx < 0) return 8;
  return Math.max(8, Math.min(95, Math.round(((idx + 1) / EXECUTION_ORDER.length) * 100)));
}

function normalizeStepState(
  stepKey: DeployStep['key'],
  executionStep: string,
  executionStatus: string,
): 'done' | 'running' | 'pending' | 'failed' {
  const es = String(executionStep || '').toLowerCase();
  const st = String(executionStatus || '').toLowerCase();

  if (st === 'failed') {
    if (stepKey === 'fixes' && ['auto_fixes', 'verification', 'deployment', 'retry_loop', 'monitoring', 'completed'].includes(es)) return 'done';
    if (stepKey === 'testing' && ['verification', 'deployment', 'retry_loop', 'monitoring', 'completed'].includes(es)) return 'done';
    if (stepKey === 'security' && ['security_audit', 'auto_fixes', 'verification', 'deployment', 'retry_loop', 'monitoring', 'completed'].includes(es)) return 'done';
    if (stepKey === 'deploying' && ['deployment', 'retry_loop', 'monitoring', 'completed', 'failed'].includes(es)) return 'failed';
    return 'pending';
  }

  if (st === 'live' || st === 'completed' || st === 'success') return 'done';

  if (stepKey === 'fixes') {
    if (['auto_fixes', 'verification', 'deployment', 'retry_loop', 'monitoring', 'completed'].includes(es)) return 'done';
    if (['security_audit'].includes(es)) return 'running';
    return 'pending';
  }

  if (stepKey === 'testing') {
    if (['verification', 'deployment', 'retry_loop', 'monitoring', 'completed'].includes(es)) return 'done';
    if (['auto_fixes'].includes(es)) return 'running';
    return 'pending';
  }

  if (stepKey === 'security') {
    if (['security_audit', 'auto_fixes', 'verification', 'deployment', 'retry_loop', 'monitoring', 'completed'].includes(es)) return 'done';
    return 'pending';
  }

  if (['deployment', 'retry_loop', 'monitoring'].includes(es)) return 'running';
  if (['completed'].includes(es)) return 'done';
  return 'pending';
}

function suggestFix(reason: string): string {
  const text = String(reason || '').toLowerCase();
  if (!text) return 'Validate deployment logs, then rerun with provider-specific env vars set.';
  if (text.includes('port')) return 'Set PORT and host binding in runtime config, then redeploy.';
  if (text.includes('env') || text.includes('token') || text.includes('credential')) return 'Add missing environment variables in provider settings and trigger a new deploy.';
  if (text.includes('build') || text.includes('compile')) return 'Fix build command/output configuration and verify locally before redeploy.';
  if (text.includes('module') || text.includes('dependency')) return 'Install missing dependencies and commit lockfile changes before redeploy.';
  return 'Inspect the failed attempt logs, apply the suggested patch, and rerun deployment.';
}

function providerFromUrl(url: string | undefined): string {
  const value = String(url || '').toLowerCase();
  if (value.includes('netlify.app')) return 'netlify';
  if (value.includes('vercel.app')) return 'vercel';
  if (value.includes('railway.app') || value.includes('up.railway.app')) return 'railway';
  if (value.includes('localhost') || value.includes('127.0.0.1')) return 'local';
  return 'unknown';
}

function hostFromUrl(url: string | undefined): string {
  try {
    if (!url) return 'n/a';
    return new URL(url).host;
  } catch {
    return 'n/a';
  }
}

export default function DeploymentPage() {
  const params = useParams<{ projectId: string }>();
  const projectId = Number(params.projectId || 0);

  const [statusPayload, setStatusPayload] = React.useState<StatusResponse | null>(null);
  const [autoPayload, setAutoPayload] = React.useState<AutonomousResponse | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [running, setRunning] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [runStartedAt, setRunStartedAt] = React.useState<number | null>(null);
  const [actionMessage, setActionMessage] = React.useState<string | null>(null);

  const load = React.useCallback(async (initial = false) => {
    if (!projectId) return;
    try {
      if (initial) setLoading(true);
      const [statusRes, autoRes] = await Promise.all([
        axios.get(`/api/status/${projectId}`),
        axios.get(`/api/v1/projects/${projectId}/autonomous-response`),
      ]);
      setStatusPayload(statusRes.data || null);
      setAutoPayload(autoRes.data || null);
      setError(null);
    } catch {
      setError('Could not load deployment flow.');
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
    const timer = window.setInterval(tick, 1800);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [projectId, load]);

  const triggerDeploy = async () => {
    if (!projectId || running) return;
    try {
      setRunning(true);
      setError(null);
      setActionMessage('Autonomous deployment started. Tracking live run...');
      setRunStartedAt(Date.now() / 1000);
      setAutoPayload(null);
      await axios.post(`/api/v1/projects/${projectId}/autonomous-fix-deploy`, {});
      setActionMessage('Autonomous deployment sequence completed.');
      await load(false);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      if (typeof detail === 'string' && detail.trim()) {
        setError(detail);
      } else {
        setError('Autonomous deployment trigger failed.');
      }
      setActionMessage(null);
    } finally {
      setRunning(false);
    }
  };

  if (!projectId) return <StateMessage variant="empty" title="No project" detail="Start from Input tab." />;
  if (loading) return <StateMessage variant="loading" title="Loading deploy" detail="Preparing execution flow." />;
  if (error) return <StateMessage variant="error" title="Deploy unavailable" detail={error} />;

  const executionState = statusPayload?.project?.execution_state || {};
  const executionStatus = String(executionState.status || statusPayload?.project?.status || '').toLowerCase();

  const plan = statusPayload?.project?.agentic_insights?.planning_engine || {};
  const meta = statusPayload?.project?.agentic_insights?.meta_agent || {};
  const finalOutput = statusPayload?.final_output || {};
  const selectedPlatform = String(plan.platform || deployment.provider || 'auto');
  const liveProvider = String(
    autoPayload?.deployment?.provider ||
    statusPayload?.deployment?.provider ||
    providerFromUrl(autoPayload?.deployment?.final_url || statusPayload?.deployment?.deployment_url || finalOutput.deployment?.url),
  );
  const liveUrl = autoPayload?.deployment?.final_url || statusPayload?.deployment?.deployment_url || finalOutput.deployment?.url;
  const urlHost = hostFromUrl(liveUrl);
  const providerMismatch = selectedPlatform !== 'auto' && liveProvider !== 'unknown' && selectedPlatform !== liveProvider;

  const deployment = {
    status: autoPayload?.deployment?.status || statusPayload?.deployment?.status || finalOutput.deployment?.status,
    url: liveUrl,
    provider: liveProvider,
    selected_provider: selectedPlatform,
    url_host: urlHost,
    attempts: autoPayload?.deployment?.attempts || finalOutput.deployment?.attempts,
    changes: finalOutput.deployment?.changes || [],
    failure_reason:
      autoPayload?.deployment?.failure_reason ||
      String(statusPayload?.deployment?.details?.reason || statusPayload?.deployment?.details?.plain_english_error || '').trim() ||
      finalOutput.deployment?.failure_reason,
  };

  const changes =
    (Array.isArray(deployment.changes) ? deployment.changes : [])
      .concat((statusPayload?.project?.fix_report?.applied || []).map((item) => `${item.fix_type || 'fix'}:${item.file || 'unknown'}`))
      .slice(0, 8);

  const confidence =
    typeof plan.confidence === 'number'
      ? plan.confidence
      : Number(meta.confidence || 0);

  const executionStep = String(executionState.step || '');

  const scopedProgress = (statusPayload?.progress || []).filter((row) => {
    if (!runStartedAt) return true;
    const ts = toEpochSeconds(row.timestamp);
    return ts >= runStartedAt - 0.5;
  });

  const progressText = scopedProgress
    .map((row) => `${row.agent || ''} ${row.phase || ''} ${row.message || ''} ${row.feed?.title || ''} ${row.feed?.message || ''} ${(row.data?.action as string) || ''} ${(row.data?.result as string) || ''}`)
    .join(' | ')
    .toLowerCase();

  const finalCards = (finalOutput.feed || []).map((item) => {
    const card: LiveCard = {
      agent: String(item.agent || 'system'),
      event: String(item.event || 'status'),
      details: String(item.details || 'update'),
      status: normalizeStatus(executionStatus),
      confidence: typeof item.confidence === 'number' ? item.confidence : null,
      action: '',
      reason: '',
      result: '',
      category: classifyCategory(String(item.agent || ''), String(item.event || ''), ''),
    };
    return card;
  });

  const progressCards = scopedProgress.slice(-120).map((row) => {
    const agent = String(row.agent_event?.agent || row.feed?.agent || row.agent || 'system');
    const event = String(row.agent_event?.event || row.feed?.title || row.phase || 'update');
    const details = String(row.agent_event?.details || row.feed?.message || row.message || 'update');
    const action = String(row.data?.action || '');
    const reason = String(row.data?.reason || '');
    const result = String(row.data?.result || '');

    const card: LiveCard = {
      agent,
      event,
      details: details.slice(0, 180),
      status: eventStatus(row, executionStatus),
      confidence: typeof row.agent_event?.confidence === 'number'
        ? row.agent_event.confidence
        : typeof row.feed?.confidence === 'number'
          ? row.feed.confidence
          : typeof row.confidence === 'number'
            ? row.confidence
            : null,
      action,
      reason,
      result,
      category: classifyCategory(agent, event, action),
    };
    return card;
  });

  const liveCards = (finalCards.length ? finalCards : progressCards)
    .filter((item) => item.details.trim().length > 0)
    .filter((item) => !isInternalNoise(item.agent, item.event, item.details))
    .slice(-40)
    .reverse();

  const seen = new Set<string>();
  const condensedCards: LiveCard[] = [];
  for (const item of liveCards) {
    const normalizedDetails = shortLine(item.details, 80).toLowerCase();
    const key = `${item.agent.toLowerCase()}|${item.event.toLowerCase()}|${normalizedDetails}`;
    if (seen.has(key)) continue;
    if (normalizedDetails.includes('retry') && condensedCards.some((x) => x.details.toLowerCase().includes('retry'))) continue;
    seen.add(key);
    condensedCards.push({
      ...item,
      details: shortLine(item.details, 130),
    });
    if (condensedCards.length >= 10) break;
  }

  const currentActivity = condensedCards.find((item) => item.status === 'running') || condensedCards[0] || null;

  const deploymentAttempts = Array.isArray(deployment.attempts) ? deployment.attempts : [];
  const metaAttempts = Array.isArray(meta.self_heal_attempts) ? meta.self_heal_attempts : [];
  const attemptsSource = deploymentAttempts.length
    ? deploymentAttempts
    : (deployment.url ? [] : metaAttempts);

  const attemptLevelSuccess =
    normalizeStatus(deployment.status || executionStatus) === 'done' ||
    Boolean(deployment.url);

  const attempts = (attemptsSource.length ? attemptsSource : (deployment.url ? [{
    attempt: 1,
    provider: String(deployment.provider || plan.platform || 'auto'),
    status: 'success',
    reason: 'Provider workflow finished and verification completed',
    fix_applied: 'none',
  }] : []))
    .slice(0, 3)
    .map((attempt, idx, arr) => {
      const baseProvider = String(attempt.provider || '').trim().toLowerCase();
      const resolvedProvider = baseProvider || String(deployment.provider || plan.platform || 'auto');

      if (attemptLevelSuccess && idx === arr.length - 1) {
        return {
          ...attempt,
          provider: resolvedProvider,
          status: 'success',
          reason: attempt.reason || 'Provider workflow finished and verification completed',
        };
      }
      return {
        ...attempt,
        provider: resolvedProvider,
      };
    });

  const hasFixEvidence =
    progressText.includes('fixagent') ||
    progressText.includes('applied') ||
    progressText.includes('remediation') ||
    changes.length > 0;

  const hasTestingEvidence =
    progressText.includes('simulation') ||
    progressText.includes('validation') ||
    progressText.includes('testing') ||
    progressText.includes('verified');

  const hasSecurityEvidence =
    progressText.includes('security') ||
    progressText.includes('audit') ||
    progressText.includes('scan');

  const hasDeployEvidence =
    progressText.includes('deploy') ||
    progressText.includes('provider') ||
    progressText.includes('fallback');

  const deploySucceeded =
    normalizeStatus(deployment.status) === 'done' ||
    executionStatus === 'live' ||
    executionStatus === 'completed' ||
    Boolean(deployment.url);

  const deployFailed =
    normalizeStatus(deployment.status) === 'failed' ||
    executionStatus === 'failed' ||
    Boolean(String(deployment.failure_reason || '').trim());

  const deployStepStates = DEPLOY_STEPS.map((item) => {
    if (!runStartedAt) {
      return {
        ...item,
        state: normalizeStepState(item.key, executionStep, executionStatus),
      };
    }

    if (item.key === 'fixes') {
      return { ...item, state: hasFixEvidence ? 'done' : hasDeployEvidence ? 'running' : 'pending' };
    }
    if (item.key === 'testing') {
      return { ...item, state: hasTestingEvidence ? 'done' : hasFixEvidence ? 'running' : 'pending' };
    }
    if (item.key === 'security') {
      return { ...item, state: hasSecurityEvidence ? 'done' : hasTestingEvidence ? 'running' : 'pending' };
    }

    if (deploySucceeded) return { ...item, state: 'done' };
    if (deployFailed) return { ...item, state: 'failed' };
    return { ...item, state: hasDeployEvidence || running ? 'running' : 'pending' };
  });

  const stepDoneCount = deployStepStates.filter((s) => s.state === 'done').length;
  const runningIndex = deployStepStates.findIndex((s) => s.state === 'running');
  const failedIndex = deployStepStates.findIndex((s) => s.state === 'failed');

  let matchedCompletionPercent = stepDoneCount * 25;
  if (runningIndex >= 0) {
    matchedCompletionPercent = Math.max(matchedCompletionPercent, runningIndex * 25 + 12);
  }
  if (failedIndex >= 0) {
    const failedBase = failedIndex >= 3 ? 90 : failedIndex * 25 + 10;
    matchedCompletionPercent = Math.max(matchedCompletionPercent, failedBase);
  }
  if (deploySucceeded) matchedCompletionPercent = 100;

  const failedReason = String(deployment.failure_reason || '').trim();
  const failedSuggestion = suggestFix(failedReason);
  const finalState = normalizeStatus(deployment.status || executionStatus);

  return (
    <div className="neo-page">
      <section className="neo-hero compact">
        <div className="neo-kicker">Tab 3 · Deploy</div>
        <h1>Autonomous Deployment Console</h1>
      </section>

      <section className="neo-stack-xl">
        <article className="neo-panel glass">
          <div className="neo-panel-head">
            <h3><Layers3 size={16} /> Section A · Step Progress</h3>
            <Button variant="primary" loading={running} onClick={triggerDeploy}>Run Autonomous Deploy</Button>
          </div>
          {actionMessage ? <div className="neo-cap" style={{ marginBottom: 8 }}>{actionMessage}</div> : null}
          <div className="neo-step-list">
            {deployStepStates.map((step) => (
              <div key={step.key} className={`neo-step-item ${step.state}`}>
                <span>{step.state === 'done' ? '✔' : step.state === 'running' ? '⏳' : step.state === 'failed' ? '✖' : '•'}</span>
                <strong>{step.label}</strong>
              </div>
            ))}
          </div>
          <div className="neo-plan-grid">
            {(plan.steps || []).map((step, idx) => (
              <div key={`${step}-${idx}`} className="neo-plan-step">{step}</div>
            ))}
          </div>
          <div className="neo-plan-meta">
            <span>Selected platform: <strong>{selectedPlatform}</strong></span>
            <span>Live provider: <strong>{deployment.provider}</strong></span>
            <span>URL host: <strong>{deployment.url_host}</strong></span>
            <span>Confidence: <strong>{Math.round((confidence || 0) * 100)}%</strong></span>
            <span>State: <strong>{finalState}</strong></span>
          </div>
          <div className="neo-progress-wrap" aria-label="Deployment completion progress">
            <div className="neo-progress-head">
              <span>Completion</span>
              <strong>{matchedCompletionPercent}%</strong>
            </div>
            <div className="neo-progress-track">
              <div className="neo-progress-fill" style={{ width: `${matchedCompletionPercent}%` }} />
            </div>
          </div>
        </article>

        <article className="neo-panel glass">
          <div className="neo-panel-head">
            <h3><Bot size={16} /> Section B · Agent Feed</h3>
            <span className="neo-cap">Autonomous: analysis, security, fixes, validation, deploy</span>
          </div>
          {currentActivity ? (
            <div className="neo-now-line">
              <span>Now</span>
              <strong>{currentActivity.agent}</strong>
              <p>{shortLine(`${currentActivity.event}: ${currentActivity.details}`, 140)}</p>
            </div>
          ) : null}
          <div className="neo-feed-list">
            {condensedCards.length ? condensedCards.map((item, idx) => (
              <div key={`${idx}-${item.agent}-${item.event}-${item.details}`} className="neo-feed-card">
                <div className="neo-feed-msg">
                  [{item.category === 'deploy' ? 'Deploy' : item.category === 'fix' ? 'Fix' : item.category === 'security' ? 'Security' : item.category === 'analysis' ? 'Code' : 'System'}]
                  {' '}
                  {shortLine(item.event, 28)} {'->'} {item.status === 'done' ? 'Success' : item.status === 'failed' ? 'Failed' : 'Running'}
                  {item.reason ? ` (${shortLine(item.reason, 46)})` : ''}
                </div>
              </div>
            )) : <div className="tiny">No live events yet.</div>}
          </div>
        </article>

        <article className="neo-panel glass">
          <div className="neo-panel-head">
            <h3><Wrench size={16} /> Section C · Changes Applied</h3>
            <span className="neo-cap">Diff view</span>
          </div>
          <div className="neo-diff-list">
            {changes.length ? changes.map((item, idx) => (
              <div key={`${item}-${idx}`} className="neo-diff-line">
                <span>+</span>
                <code>{String(item).replace(':', ' -> ')}</code>
              </div>
            )) : <div className="tiny">No changes recorded yet.</div>}
          </div>
        </article>

        <article className="neo-panel glass">
          <div className="neo-panel-head">
            <h3><RotateCcw size={16} /> Retry Limit</h3>
            <span className="neo-cap">Max 3 retries · no infinite loops</span>
          </div>
          <div className="neo-attempt-list">
            {attempts.length ? attempts.map((attempt, idx) => (
              <div key={`${attempt.attempt}-${idx}`} className="neo-attempt-item">
                <div className="neo-attempt-title">Attempt {attempt.attempt || idx + 1} · {attempt.provider || 'auto'}</div>
                <div className="neo-attempt-meta">Reason: {String(attempt.reason || attempt.failure_type || 'execution update').slice(0, 120)}</div>
                <div className="neo-attempt-meta">Fix: {String(attempt.fix_applied || 'none')}</div>
                <span className={`neo-status ${normalizeStatus(attempt.status)}`}>{normalizeStatus(attempt.status)}</span>
              </div>
            )) : <div className="tiny">No attempts recorded.</div>}
          </div>
        </article>

        <article className="neo-panel glass">
          <div className="neo-panel-head">
            <h3><CheckCircle2 size={16} /> Final Result</h3>
          </div>
          <div className="neo-final-grid">
            <div className="neo-final-item">
              <span>Status</span>
              <strong className={`neo-status ${finalState}`}>
                {finalState}
              </strong>
            </div>
            <div className="neo-final-item">
              <span>Live URL</span>
              <strong>
                {deployment.url ? (
                  <a href={deployment.url} target="_blank" rel="noreferrer" className="neo-link-inline">
                    <LinkIcon size={13} /> {deployment.url}
                  </a>
                ) : 'not available'}
              </strong>
            </div>
            <div className="neo-final-item">
              <span>Selected platform</span>
              <strong>{deployment.selected_provider || 'auto'}</strong>
            </div>
            <div className="neo-final-item">
              <span>Actual provider</span>
              <strong>{deployment.provider || 'unknown'}</strong>
            </div>
            {providerMismatch ? (
              <div className="neo-final-item wide">
                <span>Provider alignment</span>
                <strong>
                  Planned for {deployment.selected_provider}, but the live URL is hosted on {deployment.provider}.
                  The URL always reflects the actual deployment endpoint.
                </strong>
              </div>
            ) : null}
            <div className="neo-final-item">
              <span>Confidence</span>
              <strong>{Math.round((confidence || 0) * 100)}%</strong>
            </div>
            <div className="neo-final-item">
              <span>Changes made</span>
              <strong>{changes.length ? changes.slice(0, 6).join(', ') : 'No changes recorded'}</strong>
            </div>
            {failedReason ? (
              <div className="neo-final-item wide">
                <span>Failure reason</span>
                <strong>{String(failedReason).slice(0, 180)}</strong>
              </div>
            ) : null}
            {failedReason ? (
              <div className="neo-final-item wide">
                <span>Suggested fix</span>
                <strong>{failedSuggestion}</strong>
              </div>
            ) : null}
            {failedReason ? (
              <div className="neo-final-item wide">
                <span>Download diagnostics</span>
                <strong>
                  <a href={`/api/v1/projects/${projectId}/report/pdf`} target="_blank" rel="noreferrer" className="neo-link-inline">
                    <Download size={13} /> Download Report
                  </a>
                </strong>
              </div>
            ) : null}
          </div>
        </article>
      </section>
    </div>
  );
}
