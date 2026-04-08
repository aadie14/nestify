import React, { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { useParams, useSearchParams } from 'react-router-dom';
import { ExternalLink } from 'lucide-react';

import AIDebateStream, { DebateStreamEvent } from '../components/AIDebateStream';
import { useWebSocket } from '../hooks/useWebSocket';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import StateMessage from '../components/ui/StateMessage';
import { toTitleCase } from '../utils/formatters';

const SUPPORTED_DEPLOY_PROVIDERS = new Set(['vercel', 'netlify', 'railway', 'local']);

function normalizeProviderLabel(provider: unknown, fallback = 'pending'): string {
  const normalized = String(provider || '').trim().toLowerCase();
  if (!normalized) return fallback;
  return SUPPORTED_DEPLOY_PROVIDERS.has(normalized) ? normalized : fallback;
}

type LifecycleState = 'thinking' | 'deploying' | 'verifying' | 'live' | 'failed';

function resolveLifecycleState(statusData: any, deploymentFailed: boolean): LifecycleState {
  if (deploymentFailed) return 'failed';
  const status = String(statusData?.status || '').toLowerCase();
  const executionStep = String(statusData?.execution_state?.step || '').toLowerCase();
  if (status === 'live' || status === 'completed' || executionStep === 'completed') return 'live';
  if (executionStep === 'verification' || executionStep === 'monitoring' || executionStep === 'self_healing_loop') return 'verifying';
  if (executionStep === 'deployment') return 'deploying';
  return 'thinking';
}

function lifecycleCopy(state: LifecycleState, reason: string): string {
  if (state === 'failed') return `Deployment paused. ${reason || 'I am diagnosing the failure and preparing the safest retry path.'}`;
  if (state === 'live') return 'Deployment verified. Monitoring is active and the release path is stable.';
  if (state === 'verifying') return 'Release candidate is up. I am validating live health and runtime behavior before final handoff.';
  if (state === 'deploying') return 'Applying the deployment strategy and provider configuration selected from your app profile.';
  return 'Building context from telemetry, recent actions, and deployment constraints.';
}

function localPreviewCopy(reason: string): string {
  const base = 'Deployment is currently running in local preview mode, not on a public cloud platform.';
  if (!reason) return `${base} Configure VERCEL_TOKEN or NETLIFY_API_TOKEN for public static hosting.`;
  return `${base} ${reason}`;
}

function retryGuidance(failureReason: string, fixSuggestion: string, attempts: number, provider: string): string {
  const reason = failureReason || 'Deployment failed due to runtime or provider mismatch.';
  const fix = fixSuggestion || 'I will adjust provider strategy, validate env setup, and retry with safer defaults.';
  return `Attempt ${Math.max(1, attempts)} on ${toTitleCase(provider || 'auto')} failed: ${reason} Next step: ${fix}`;
}

function inferAutonomousType(text: string, phase: string): DebateStreamEvent['type'] {
  const combined = `${text} ${phase}`.toLowerCase();
  if (combined.includes('fail') || combined.includes('error') || combined.includes('blocked')) return 'failure';
  if (combined.includes('success') || combined.includes('complete') || combined.includes('live')) return 'success';
  if (combined.includes('retry') || combined.includes('re-run') || combined.includes('again')) return 'retry';
  if (combined.includes('fix') || combined.includes('patch') || combined.includes('update') || combined.includes('added') || combined.includes('env')) return 'fix';
  if (combined.includes('deploy') || combined.includes('publish') || combined.includes('action')) return 'action';
  return 'thinking';
}

function withFixMarker(item: string): string {
  const clean = String(item || '').replace(/\s+/g, ' ').trim();
  if (!clean) return '';
  if (clean.startsWith('[+]') || clean.startsWith('[~]')) return clean;
  if (/(add|added|set|create|created|inject|configured)\b/i.test(clean)) return `[+] ${clean}`;
  return `[~] ${clean}`;
}

function oneLine(value: unknown, fallback: string): string {
  const cleaned = String(value || '').replace(/\s+/g, ' ').trim();
  if (!cleaned) return fallback;
  return cleaned.slice(0, 140);
}

function roleWithEmoji(rawRole: string, rawAgent: string): string {
  const combined = `${rawRole} ${rawAgent}`.toLowerCase();
  if (combined.includes('meta')) return '🧠 Meta-Agent';
  if (combined.includes('security')) return '🛡️ Security';
  if (combined.includes('deploy')) return '🚀 Deploy';
  if (combined.includes('fix') || combined.includes('code')) return '💻 Code';
  return '🤖 Agent';
}

export default function DeploymentPage() {
  const params = useParams<{ projectId: string }>();
  const [searchParams] = useSearchParams();
  const projectId = Number(params.projectId || 0);
  const { messages } = useWebSocket(projectId || null);

  const [deploymentData, setDeploymentData] = useState<any>(null);
  const [reportData, setReportData] = useState<any>(null);
  const [statusData, setStatusData] = useState<any>(null);
  const [optimizationData, setOptimizationData] = useState<any>(null);
  const [optimizationLoading, setOptimizationLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [executionStarted, setExecutionStarted] = useState(false);
  const [executionRunning, setExecutionRunning] = useState(false);
  const [executionAttempt, setExecutionAttempt] = useState(0);
  const [executionStateLabel, setExecutionStateLabel] = useState('Idle');
  const [executionFailureReason, setExecutionFailureReason] = useState<string | null>(null);
  const [syntheticEvents, setSyntheticEvents] = useState<DebateStreamEvent[]>([]);
  const [downloadingReport, setDownloadingReport] = useState(false);
  const [actionRunning, setActionRunning] = useState(false);

  useEffect(() => {
    if (!projectId) return;
    let alive = true;

    const load = async () => {
      try {
        setOptimizationLoading(true);
        const [deployment, report, status] = await Promise.all([
          axios.get(`/api/v1/projects/${projectId}/deployment`),
          axios.get(`/api/v1/projects/${projectId}/report`),
          axios.get(`/api/v1/projects/${projectId}/status`),
        ]);

        let optimization = null;
        try {
          const optimizationResponse = await axios.get(`/api/v1/optimization/${projectId}`);
          optimization = optimizationResponse.data;
        } catch {
          optimization = null;
        }

        if (!alive) return;
        setDeploymentData(deployment.data);
        setReportData(report.data);
        setStatusData(status.data);
        setOptimizationData(optimization);
        setLoadError(null);
      } catch {
        if (!alive) return;
        setLoadError('Could not refresh deployment state. Next: confirm backend connectivity and retry.');
      } finally {
        if (alive) setOptimizationLoading(false);
      }
    };

    load();
    const timer = window.setInterval(load, 4000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [projectId]);

  const pushExecutionEvent = (
    role: string,
    action: string,
    reason: string,
    result: string,
    type: DebateStreamEvent['type'] = 'action',
  ) => {
    setSyntheticEvents((prev) => [
      ...prev,
      {
        agent: role.toLowerCase().replace(/[^a-z]+/g, '_'),
        role,
        message: oneLine(action, 'Executing step'),
        reason: oneLine(reason, 'Based on previous execution signal'),
        result: oneLine(result, 'Step executed'),
        type,
      },
    ].slice(-32));
  };

  useEffect(() => {
    if (!projectId) return;
    if (searchParams.get('start') !== '1') return;
    if (executionStarted) return;

    let alive = true;
    setExecutionStarted(true);
    setExecutionRunning(true);
    setExecutionStateLabel('Initializing');
    setExecutionFailureReason(null);

    const run = async () => {
      pushExecutionEvent('🧠 Meta-Agent', 'Preparing autonomous execution', 'Autonomous Fix & Deploy was triggered by user', 'Execution workflow started', 'thinking');
      setExecutionAttempt(1);
      setExecutionStateLabel('Running');

      try {
        const response = await axios.post(`/api/v1/projects/${projectId}/autonomous-fix-deploy`);
        const status = String(response?.data?.status || '').toLowerCase();
        const url = String(response?.data?.deployment_url || '').trim();
        const details = (response?.data?.details && typeof response.data.details === 'object') ? response.data.details : {};
        const provider = String(response?.data?.provider || '').trim();

        if (url || status === 'deployed') {
          setExecutionStateLabel(provider.toLowerCase() === 'local' ? 'Local Fallback Live' : 'Live');
          pushExecutionEvent('🚀 Deploy', 'Autonomous flow completed', 'Controlled deploy/fix/retry sequence finished', url || 'Live URL available', 'success');
        } else {
          const failure = oneLine(details?.plain_english_error || details?.reason || response?.data?.blocking_reason, 'Deployment currently blocked by a missing prerequisite');
          setExecutionFailureReason(failure);
          setExecutionStateLabel('Failed');
          pushExecutionEvent('🚀 Deploy', 'Autonomous flow failed', failure, 'Manual intervention required', 'failure');
        }
      } catch (error: any) {
        const detail = error?.response?.data?.detail;
        const reason = oneLine(typeof detail === 'string' ? detail : (detail?.plain_english_error || detail?.reason), 'Deployment failed due to unknown provider error');
        setExecutionFailureReason(reason);
        setExecutionStateLabel('Failed');
        pushExecutionEvent('🚀 Deploy', 'Autonomous flow failed', reason, 'Manual intervention required', 'failure');
      } finally {
        if (alive) setExecutionRunning(false);
      }
    };

    run();

    return () => {
      alive = false;
    };
  }, [projectId, searchParams, executionStarted]);

  const executionState = statusData?.execution_state || {};

  const insights = deploymentData?.agentic_insights || reportData?.agentic_insights || {};
  const deploymentUrl = deploymentData?.deployment_url || reportData?.project?.public_url || '';
  const liveUrl = deploymentUrl || `http://127.0.0.1:8000/preview/${projectId}`;
  const localhostPreviewUrl = `http://localhost:8000/preview/${projectId}`;
  const deploymentProviderLabel = normalizeProviderLabel(deploymentData?.provider, 'auto');
  const reportChosenPlatform = normalizeProviderLabel(
    insights?.deployment_intelligence?.chosen_platform || deploymentData?.provider,
    'pending',
  );
  const optimizationProvider = normalizeProviderLabel(optimizationData?.provider, reportChosenPlatform);
  const chosenProvider = reportChosenPlatform || deploymentProviderLabel || optimizationProvider;
  const latestDeploymentIssue = String(
    executionState?.errors?.[executionState.errors.length - 1] ||
    deploymentData?.details?.plain_english_error ||
    deploymentData?.details?.error ||
    ''
  ).trim();
  const deploymentFailed = String(statusData?.status || deploymentData?.status || '').toLowerCase() === 'failed' || !!latestDeploymentIssue;
  const lifecycleState = resolveLifecycleState(statusData, deploymentFailed);
  const isLocalPreview = deploymentProviderLabel === 'local' || liveUrl.includes('/preview/');
  const localFallbackReason = String(
    deploymentData?.details?.note ||
    deploymentData?.details?.reason ||
    ''
  ).trim();
  const failureReason = String(
    deploymentData?.details?.plain_english_error ||
    deploymentData?.details?.error ||
    latestDeploymentIssue ||
    ''
  ).trim();
  const failureFixSuggestion = String(
    deploymentData?.details?.fix_suggestion ||
    deploymentData?.details?.note ||
    insights?.deployment_intelligence?.recovery_plan ||
    ''
  ).trim();
  const lifecycleNarration = lifecycleCopy(lifecycleState, failureReason);
  const effectiveNarration = isLocalPreview ? localPreviewCopy(localFallbackReason) : lifecycleNarration;
  const decisionReasonShort = String(
    insights?.deployment_intelligence?.rationale ||
    'Best fit for static + fast cold start'
  )
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 160);
  const decisionPlatform = toTitleCase(chosenProvider || deploymentProviderLabel || 'railway');

  const fixItems = useMemo<string[]>(() => {
    const details = (deploymentData?.details || {}) as Record<string, any>;
    const fromArrays = [
      ...(Array.isArray(details?.what_i_fixed) ? details.what_i_fixed : []),
      ...(Array.isArray(details?.fixes_applied) ? details.fixes_applied : []),
      ...(Array.isArray(details?.changes) ? details.changes : []),
    ]
      .map((item) => withFixMarker(String(item || '')))
      .filter(Boolean);

    const fromMessages = (messages || [])
      .slice(-36)
      .map((item) => String(item.user_message || item.thought || item.message || item.decision || ''))
      .filter((line) => /fix|patch|update|added|set|config|env/i.test(line))
      .slice(-4)
      .map((line) => withFixMarker(line));

    const fallback = failureFixSuggestion ? [withFixMarker(failureFixSuggestion)] : [];
    return [...fromArrays, ...fromMessages, ...fallback].filter(Boolean).slice(-5);
  }, [deploymentData?.details, messages, failureFixSuggestion]);

  const nextActionRequired = String(
    deploymentData?.next_action ||
    deploymentData?.details?.next_action ||
    (failureFixSuggestion
      ? `Apply suggested fix and retry deployment: ${failureFixSuggestion}`
      : 'Provide required provider credentials and retry deployment.')
  ).trim();

  const blockerMessage = String(
    deploymentData?.blocking_reason ||
    deploymentData?.details?.reason ||
    failureReason ||
    'Autonomous execution is blocked by an unresolved deployment prerequisite.'
  ).trim();

  const debateEvents = useMemo<DebateStreamEvent[]>(() => {
    const seeded = (messages || [])
      .filter((item) => String(item.type || '').toLowerCase() !== 'argument' && String(item.phase || '').toLowerCase() !== 'reasoning')
      .slice(-48)
      .map((item) => {
      const text = String(item.user_message || item.thought || item.message || item.decision || 'Evaluating next deployment action.').replace(/\s+/g, ' ').trim();
      const phase = String(item.phase || item.status || '').toLowerCase();
      const role = String(item.agent || 'Execution Agent').replace(/_/g, ' ');
      const data = (item.data && typeof item.data === 'object' ? item.data : {}) as Record<string, unknown>;
      const reason = String(item.reason || data.reason || '').replace(/\s+/g, ' ').trim();
      const result = String(item.result || data.result || '').replace(/\s+/g, ' ').trim();
      const type = inferAutonomousType(text, phase);
      return {
        agent: String(item.agent || 'agent'),
        role: roleWithEmoji(role, String(item.agent || 'agent')),
        message: oneLine(text, 'Working on execution details.'),
        reason: reason || undefined,
        result: result || undefined,
        type,
        cycle: typeof item.cycle === 'number' ? item.cycle : undefined,
        confidence: typeof item.confidence === 'number' ? item.confidence : undefined,
      };
    });

    const combinedSeeded = [...seeded, ...syntheticEvents].slice(-72);

    if (combinedSeeded.length > 0) {
      const terminalEvents: DebateStreamEvent[] = [];
      if (deploymentFailed) {
        terminalEvents.push({
          agent: 'meta_agent',
          role: '🧠 Meta-Agent',
          message: oneLine(blockerMessage, 'Deployment blocked'),
          reason: oneLine(failureReason, 'A deployment prerequisite is currently unmet'),
          result: 'Retry or fallback is required',
          type: 'failure',
        });
        if (failureFixSuggestion) {
          terminalEvents.push({
            agent: 'fix_agent',
            role: '💻 Code',
            message: oneLine(withFixMarker(failureFixSuggestion), 'Applying remediation patch'),
            reason: 'Previous attempt failed with configuration/runtime issue',
            result: 'Fix candidate prepared',
            type: 'fix',
          });
        }
        terminalEvents.push({
          agent: 'meta_agent',
          role: '🚀 Deploy',
          message: oneLine(`Retrying deployment`, 'Retrying deployment'),
          reason: oneLine(nextActionRequired, 'Failure reason was identified'),
          result: 'Fallback strategy queued',
          type: 'retry',
        });
      } else if (lifecycleState === 'live') {
        terminalEvents.push({
          agent: 'meta_agent',
          role: '🚀 Deploy',
          message: 'Deployment successful. Live verification checks passed.',
          reason: 'All verification checks completed successfully',
          result: 'System is live and stable',
          type: 'success',
        });
      }
      return [...combinedSeeded, ...terminalEvents].slice(-72);
    }

    return [
      {
        agent: 'meta_agent',
        role: '🧠 Meta-Agent',
        message: oneLine(effectiveNarration, 'Preparing deployment context'),
        reason: 'Execution panel is waiting for deployment actions',
        result: 'First autonomous action will stream shortly',
        type: lifecycleState === 'failed' ? 'failure' : lifecycleState === 'live' ? 'success' : 'thinking',
      },
      ...(lifecycleState === 'failed'
        ? [{
            agent: 'meta_agent',
            role: '🚀 Deploy',
            message: oneLine('Retrying deployment', 'Retrying deployment'),
            reason: oneLine(nextActionRequired, 'Deployment prerequisites changed'),
            result: 'Recovery flow engaged',
            type: 'retry' as const,
          }]
        : []),
    ];
  }, [messages, effectiveNarration, lifecycleState, deploymentFailed, failureFixSuggestion, blockerMessage, nextActionRequired, syntheticEvents, failureReason]);

  const onDownloadAuditReport = async () => {
    if (!projectId || downloadingReport) return;
    try {
      setDownloadingReport(true);
      const response = await axios.get(`/api/v1/projects/${projectId}/report/pdf`, { responseType: 'blob' });
      const blob = new Blob([response.data], { type: 'application/pdf' });
      const downloadUrl = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = `nestify-report-${projectId}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(downloadUrl);
    } finally {
      setDownloadingReport(false);
    }
  };

  const onRunAutonomous = async () => {
    if (!projectId || actionRunning) return;
    try {
      setActionRunning(true);
      setExecutionFailureReason(null);
      setExecutionStateLabel('Running');
      setExecutionAttempt((prev) => prev + 1);
      await axios.post(`/api/v1/projects/${projectId}/autonomous-fix-deploy`);
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      setExecutionFailureReason(oneLine(typeof detail === 'string' ? detail : (detail?.reason || detail?.plain_english_error), 'Autonomous execution failed.'));
    } finally {
      setActionRunning(false);
    }
  };

  const riskCritical = Number(reportData?.findings?.critical?.length || 0);
  const riskHigh = Number(reportData?.findings?.high?.length || 0);
  const riskMedium = Number(reportData?.findings?.medium?.length || 0);
  const currentAction = oneLine(
    debateEvents[debateEvents.length - 1]?.message || executionStateLabel || 'Preparing autonomous execution',
    'Preparing autonomous execution',
  );
  const headerConfidence = Math.round(
    Math.max(0.4, Math.min(0.99, Number(debateEvents[debateEvents.length - 1]?.confidence || (deploymentFailed ? 0.55 : 0.92)))) * 100,
  );

  if (!projectId) {
    return (
      <StateMessage
        variant="empty"
        title="Upload a project to begin"
        detail="Start from Upload, then open deployment once analysis is available."
      />
    );
  }

  return (
    <div className="control-room-page">
      <section className="control-room-shell">
        <div className="control-room-left">
          <AIDebateStream
            events={debateEvents}
            loadingHint={effectiveNarration}
            headline="Deployment Execution"
            compact
          />
        </div>

        <aside className="control-room-right sticky-control-panel">
          {optimizationLoading ? (
            <StateMessage
              variant="loading"
              title="Refreshing deployment intelligence"
              detail="Reconciling provider health, status, and runtime metrics."
            />
          ) : null}

          {loadError ? (
            <StateMessage
              variant="error"
              title="Deployment state unavailable"
              detail={loadError}
            />
          ) : null}

          <Card className="autonomous-engine-header view-transition">
            <div className="autonomous-engine-title">🧠 Status</div>
            <div className="tiny">{currentAction}</div>
            <div className="tiny" style={{ marginTop: 4 }}>Deploying → {decisionPlatform}</div>
            <div className="tiny">Confidence: {headerConfidence}%</div>
          </Card>

          <Card className="live-intel-section view-transition">
            <div className="tiny">📊 Summary</div>
            <div className="tiny"><strong>Platform:</strong> {decisionPlatform}</div>
            <div className="tiny">{decisionReasonShort || 'Chosen using runtime fit, risk posture, and deployment reliability.'}</div>
            <div className="live-risk-grid" style={{ marginTop: 6 }}>
              <div className="live-risk-cell critical">Critical {riskCritical}</div>
              <div className="live-risk-cell high">High {riskHigh}</div>
              <div className="live-risk-cell medium">Medium {riskMedium}</div>
            </div>
            <ul className="autonomous-fix-list" style={{ marginTop: 8 }}>
              {(fixItems.length ? fixItems : ['[~] No fix applied yet']).slice(0, 3).map((item, idx) => (
                <li key={`${item}-${idx}`}>{item}</li>
              ))}
            </ul>
            {(executionFailureReason || deploymentFailed) ? (
              <div className="tiny">Failure: {oneLine(executionFailureReason || failureReason || blockerMessage, 'Deployment blocked by unresolved prerequisites')}</div>
            ) : null}
            {(deploymentFailed || executionFailureReason) ? (
              <div className="tiny">Fallback: {localhostPreviewUrl}</div>
            ) : null}
          </Card>

          <div className="live-intel-actions" style={{ marginTop: 'auto' }}>
            <Button variant="primary" onClick={onRunAutonomous} disabled={actionRunning || executionRunning}>
              {actionRunning || executionRunning ? 'Running Autonomous Flow...' : 'Autonomous Fix & Deploy'}
            </Button>
            <Button variant="secondary" onClick={onDownloadAuditReport} disabled={downloadingReport}>
              {downloadingReport ? 'Generating report...' : 'Download Full Audit Report'}
            </Button>
            <a className="live-link" href={liveUrl} target="_blank" rel="noreferrer" style={{ marginTop: 4 }}>
              Open Live URL <ExternalLink size={14} />
            </a>
          </div>
        </aside>
      </section>
    </div>
  );
}
