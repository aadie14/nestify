import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import axios from 'axios';
import AIDebateStream, { DebateStreamEvent } from '../components/AIDebateStream';
import LiveIntelligencePanel from '../components/LiveIntelligencePanel';
import CostComparisonTable from '../components/CostComparisonTable';
import SecurityReport from '../components/SecurityReport';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import StateMessage from '../components/ui/StateMessage';
import TechnicalDetailsDrawer from '../components/TechnicalDetailsDrawer';
import { useAgentDebate } from '../hooks/useAgentDebate';
import { useWebSocket } from '../hooks/useWebSocket';
import { formatCurrencyINR, toTitleCase } from '../utils/formatters';

type ReportResponse = {
  project?: {
    security_score?: number;
    preferred_provider?: string;
    public_url?: string;
  };
  deployment?: {
    deployment_url?: string;
    provider?: string;
    status?: string;
    details?: Record<string, unknown>;
  };
  findings?: {
    critical?: Array<Record<string, unknown>>;
    high?: Array<Record<string, unknown>>;
    medium?: Array<Record<string, unknown>>;
    info?: Array<Record<string, unknown>>;
  };
  fixes?: Array<Record<string, unknown>>;
  remediation_steps?: Array<{
    severity?: string;
    title?: string;
    location?: string;
    recommendation?: string;
  }>;
  agentic_insights?: {
    cost?: {
      cheapest_platform?: string;
    };
    deployment_intelligence?: {
      chosen_platform?: string;
      rationale?: string;
      reasoning?: string;
      estimated_monthly_cost_usd?: number;
      alternatives?: Array<{ provider?: string; score?: number }>;
    };
    cost_optimization?: {
      recommended?: {
        monthly_cost_usd?: number;
      };
      comparison_matrix?: Array<{
        config?: { label?: string };
        monthly_cost_usd?: number;
        monthly_cost_inr?: number;
      }>;
      note?: string;
    };
  };
};

type StatusResponse = {
  status?: string;
  pipeline_state?: Record<string, string>;
  progress?: Array<{
    phase?: string;
    message?: string;
  }>;
};

type OptimizationResponse = {
  provider?: string;
  cheapest_provider?: string;
  monthly_cost_usd?: number;
  monthly_cost_inr?: number;
  current_monthly_cost_usd?: number | null;
  current_monthly_cost_inr?: number | null;
  recommended_monthly_cost_usd?: number;
  recommended_monthly_cost_inr?: number;
  recommended_resource_config?: {
    memory_mb?: number;
    cpu?: number;
    label?: string;
  };
  current_resource_config?: {
    memory_mb?: number;
    cpu?: number;
    source?: string;
  };
  analysis?: {
    comparison_matrix?: Array<{
      config?: { label?: string; memory_mb?: number; cpu?: number };
      monthly_cost_usd?: number;
      monthly_cost_inr?: number;
    }>;
  };
  savings_percentage?: number | null;
  provider_costs_inr?: Record<string, number>;
  usd_to_inr_rate?: number;
  fx_updated_at?: string;
  fx_fallback?: boolean;
};

type RecoveryAttempt = {
  attempt: number;
  action: 'deploy' | 'redeploy';
  status: 'running' | 'failed' | 'succeeded';
  title: string;
  fixApplied: string;
  failureReason?: string;
};

type RecoveryMetadata = {
  fixApplied: string;
  failureReason: string;
};

const SUPPORTED_DEPLOY_PROVIDERS = new Set(['vercel', 'netlify', 'railway', 'local']);

function normalizeProviderName(value: unknown): string {
  const normalized = String(value || '').trim().toLowerCase();
  return SUPPORTED_DEPLOY_PROVIDERS.has(normalized) ? normalized : '';
}

function isAnalysisComplete(statusData: StatusResponse | null): boolean {
  if (!statusData) return false;
  const status = String(statusData.status || '').toLowerCase();
  if (status === 'completed' || status === 'live' || status === 'failed') return true;

  const state = statusData.pipeline_state || {};
  const required = ['code_analysis', 'agent_debate', 'security_audit'];
  return required.every((step) => {
    const value = String(state[step] || '').toLowerCase();
    return value === 'done' || value === 'complete' || value === 'completed' || value === 'success' || value === 'skipped';
  });
}

function deriveProgress(statusData: StatusResponse | null): number {
  if (!statusData) return 5;
  const status = (statusData.status || '').toLowerCase();
  if (status === 'completed' || status === 'failed' || status === 'live') return 100;

  const last = statusData.progress?.[statusData.progress.length - 1];
  const phase = (last?.phase || '').toLowerCase();
  if (phase === 'scanning') return 30;
  if (phase === 'analyzing') return 60;
  if (phase === 'deploying') return 85;
  if (phase === 'monitoring') return 95;

  const state = statusData.pipeline_state || {};
  const keys = Object.keys(state);
  if (!keys.length) return 10;
  const doneLike = keys.filter((k) => {
    const raw = state[k];
    const normalized = typeof raw === 'string' ? raw.toLowerCase() : '';
    return ['done', 'skipped', 'failed'].includes(normalized);
  }).length;
  return Math.max(10, Math.min(99, Math.round((doneLike / keys.length) * 100)));
}

function intelligentLoadingCopy(runStatus: string, progressValue: number): string {
  if (runStatus === 'failed') return 'Diagnosing the last failure and preparing the safest next move.';
  if (progressValue < 25) return 'Understanding your architecture and startup paths.';
  if (progressValue < 55) return 'Correlating findings with known deployment failure patterns.';
  if (progressValue < 80) return 'Prioritizing fixes and selecting deployment strategy.';
  if (progressValue < 100) return 'Validating deployability and confidence before handoff.';
  return 'Analysis completed. Preparing deployment-ready summary.';
}

function roleFromAgent(agent: string): string {
  const normalized = agent.toLowerCase();
  if (normalized.includes('meta') || normalized.includes('coordinator') || normalized.includes('orchestrator')) return 'Meta-Agent';
  if (normalized.includes('security')) return 'Security Agent';
  if (normalized.includes('cost')) return 'Cost Agent';
  if (normalized.includes('architect') || normalized.includes('deploy') || normalized.includes('platform')) return 'Architect';
  if (normalized.includes('fix') || normalized.includes('heal')) return 'Fix Agent';
  if (normalized.includes('code') || normalized.includes('scan') || normalized.includes('analy')) return 'Code Agent';
  return 'Specialist Agent';
}

function toPlainMessage(raw: string): string {
  const simplified = raw
    .replace(/heuristic/gi, 'estimate')
    .replace(/SLA/gi, 'reliability target')
    .replace(/runtime mismatch/gi, 'runtime issue')
    .replace(/deployment manifest/gi, 'deployment setup')
    .replace(/orchestrator/gi, 'meta-agent')
    .replace(/\s+/g, ' ')
    .trim();

  if (!simplified) return 'Reviewing the next best move.';
  if (simplified.length <= 170) return simplified;
  return `${simplified.slice(0, 167)}...`;
}

function inferDebateType(message: string, status: string, fallback: string): DebateStreamEvent['type'] {
  const combined = `${message} ${status} ${fallback}`.toLowerCase();
  if (combined.includes('failed') || combined.includes('error') || combined.includes('blocked')) return 'failure';
  if (combined.includes('complete') || combined.includes('success') || combined.includes('live')) return 'success';
  if (combined.includes('retry') || combined.includes('re-run') || combined.includes('try again')) return 'retry';
  if (combined.includes('fix') || combined.includes('patch') || combined.includes('updated') || combined.includes('added') || combined.includes('environment variable')) return 'fix';
  if (combined.includes('deploy') || combined.includes('apply') || combined.includes('publish') || combined.includes('choose') || combined.includes('selected') || combined.includes('prefer')) return 'action';
  return 'thinking';
}

export default function AnalysisPage() {
  const navigate = useNavigate();
  const { projectId } = useParams();
  const parsedId = useMemo(() => (projectId ? Number(projectId) : null), [projectId]);
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [statusData, setStatusData] = useState<StatusResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [downloadingPdf, setDownloadingPdf] = useState(false);
  const [deployError, setDeployError] = useState<string | null>(null);
  const [recoveryAttempts, setRecoveryAttempts] = useState<RecoveryAttempt[]>([]);
  const [recoveryStage, setRecoveryStage] = useState<string>('idle');
  const [recoveryRunning, setRecoveryRunning] = useState(false);
  const [optimization, setOptimization] = useState<OptimizationResponse | null>(null);
  const [optimizationLoading, setOptimizationLoading] = useState(false);
  const [manualModeOpen, setManualModeOpen] = useState(false);
  const [manualSourceType, setManualSourceType] = useState<'github' | 'file'>('github');
  const [manualGithubUrl, setManualGithubUrl] = useState('');
  const [manualFile, setManualFile] = useState<File | null>(null);
  const [manualSubmitting, setManualSubmitting] = useState(false);
  const [manualError, setManualError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const { rounds } = useAgentDebate(parsedId);
  const { messages } = useWebSocket(parsedId);

  useEffect(() => {
    if (!parsedId) return;
    let alive = true;
    let initial = true;

    const load = async () => {
      try {
        if (initial) setLoading(true);
        const res = await axios.get(`/api/v1/projects/${parsedId}/report`);
        if (!alive) return;
        setReport(res.data || null);
        setLoadError(null);
      } catch {
        if (!alive) return;
        if (initial) setReport(null);
        setLoadError('Could not load analysis report. Next: verify backend is running, then refresh this page.');
      } finally {
        if (alive && initial) {
          setLoading(false);
          initial = false;
        }
      }
    };

    load();
    const id = window.setInterval(load, 4000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [parsedId]);

  useEffect(() => {
    if (!parsedId) return;
    let alive = true;

    const tick = async () => {
      try {
        const res = await axios.get(`/api/v1/projects/${parsedId}/status`);
        if (!alive) return;
        setStatusData(res.data || null);
        setLoadError(null);
      } catch {
        if (!alive) return;
        setLoadError('Live status is unavailable. Next: check API connectivity and retry.');
      }
    };

    tick();
    const id = window.setInterval(tick, 3000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [parsedId]);

  const fixesCount = report?.fixes?.length || 0;
  const criticalCount = report?.findings?.critical?.length || 0;
  const highCount = report?.findings?.high?.length || 0;
  const mediumCount = report?.findings?.medium?.length || 0;
  const platform =
    normalizeProviderName(report?.agentic_insights?.cost?.cheapest_platform) ||
    normalizeProviderName(report?.agentic_insights?.deployment_intelligence?.chosen_platform) ||
    'pending';
  const chosenPlatform = normalizeProviderName(report?.agentic_insights?.deployment_intelligence?.chosen_platform) || platform;
  const platformRationale =
    report?.agentic_insights?.deployment_intelligence?.rationale ||
    'Platform chosen from security, deployment fit, and projected cost signals.';
  const estimatedMonthlyCost =
    report?.agentic_insights?.deployment_intelligence?.estimated_monthly_cost_usd ??
    report?.agentic_insights?.cost_optimization?.recommended?.monthly_cost_usd;
  const comparison = report?.agentic_insights?.cost_optimization?.comparison_matrix || [];
  const costNote = report?.agentic_insights?.cost_optimization?.note || '';
  const progressValue = deriveProgress(statusData);
  const progressItems = statusData?.progress || [];
  const lastProgressMessage = progressItems.length
    ? progressItems[progressItems.length - 1]?.message || 'Running analysis pipeline...'
    : 'Running analysis pipeline...';
  const runStatus = (statusData?.status || 'processing').toLowerCase();
  const intelligentLoading = intelligentLoadingCopy(runStatus, progressValue);
  const analysisComplete = isAnalysisComplete(statusData);
  const terminalAnalysisState = ['completed', 'live', 'failed'].includes(runStatus);

  useEffect(() => {
    if (!parsedId || !(analysisComplete || terminalAnalysisState)) return;
    let alive = true;

    const loadOptimization = async () => {
      try {
        setOptimizationLoading(true);
        const res = await axios.get(`/api/v1/optimization/${parsedId}`);
        if (!alive) return;
        setOptimization(res.data || null);
      } catch {
        if (!alive) return;
        setOptimization(null);
      } finally {
        if (alive) setOptimizationLoading(false);
      }
    };

    loadOptimization();
    const id = window.setInterval(loadOptimization, 5000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [parsedId, analysisComplete, terminalAnalysisState]);

  const expandedFixPlan = useMemo(() => {
    const fixItems = Array.isArray(report?.fixes) ? report!.fixes : [];
    const mappedFixes = fixItems.map((fix: any, idx: number) => ({
      title: String(fix.title || fix.file || fix.fix_type || `Fix ${idx + 1}`),
      description: String(
        fix.recommendation ||
        fix.note ||
        fix.action ||
        fix.description ||
        ''
      ).trim(),
    }));

    const usefulMapped = mappedFixes.filter((item) => item.description.length > 0);
    if (usefulMapped.length > 0) return usefulMapped;

    const findings = report?.findings || {};
    const bySeverity = [
      ...(findings.critical || []),
      ...(findings.high || []),
      ...(findings.medium || []),
      ...(findings.info || []),
    ];

    const fromFindings = bySeverity.slice(0, 8).map((finding: any, idx: number) => ({
      title: String(finding.title || finding.type || `Finding ${idx + 1}`),
      description: String(
        finding.recommendation ||
        finding.description ||
        finding.message ||
        'Review this finding and apply the suggested remediation.'
      ),
    }));

    if (fromFindings.length > 0) return fromFindings;

    const remediation = Array.isArray(report?.remediation_steps) ? report!.remediation_steps : [];
    return remediation.slice(0, 10).map((step, idx) => ({
      title: String(step.title || `Remediation ${idx + 1}`),
      description: String(step.recommendation || `Review ${step.location || 'the impacted location'} and apply this remediation.`),
    }));
  }, [report]);

  const deployBlockedReason = analysisComplete
    ? null
    : 'Analysis is still running. Deployment unlocks automatically when analysis reaches completed.';

  const deploySequenceSteps = [
    { key: 'analysis-check', label: 'Validate analysis completion' },
    { key: 'deploy-1', label: 'Attempt deployment' },
    { key: 'redeploy-1', label: 'Recovery attempt 1' },
    { key: 'redeploy-2', label: 'Recovery attempt 2' },
    { key: 'complete', label: 'Deployment handoff complete' },
  ] as const;

  const getStepState = (stepKey: string): 'pending' | 'active' | 'complete' | 'failed' => {
    if (recoveryStage === 'idle') {
      return stepKey === 'analysis-check' ? 'active' : 'pending';
    }
    if (recoveryStage === 'failed') {
      if (stepKey === 'complete') return 'failed';
      if (stepKey === 'analysis-check') return 'complete';
      return recoveryAttempts.some((item) => item.title === deploySequenceSteps.find((step) => step.key === stepKey)?.label && item.status === 'succeeded')
        ? 'complete'
        : recoveryAttempts.some((item) => item.title === deploySequenceSteps.find((step) => step.key === stepKey)?.label && item.status === 'failed')
          ? 'failed'
          : 'pending';
    }
    if (recoveryStage === 'complete') {
      return stepKey === 'analysis-check' || stepKey === 'complete' || stepKey === 'deploy-1' || stepKey === 'redeploy-1' || stepKey === 'redeploy-2'
        ? 'complete'
        : 'pending';
    }
    if (stepKey === recoveryStage) return 'active';

    const ordered = ['analysis-check', 'deploy-1', 'redeploy-1', 'redeploy-2', 'complete'];
    const current = ordered.indexOf(recoveryStage);
    const candidate = ordered.indexOf(stepKey);
    if (candidate > -1 && current > -1 && candidate < current) return 'complete';
    return 'pending';
  };

  const optimizationProvider =
    normalizeProviderName(optimization?.cheapest_provider) ||
    normalizeProviderName(optimization?.provider) ||
    chosenPlatform;
  const deployedProviderHint =
    normalizeProviderName(report?.deployment?.provider) ||
    normalizeProviderName(report?.project?.preferred_provider);
  const optimizationCurrentMonthlyCost = optimization?.current_monthly_cost_inr;
  const optimizationRecommendedConfig = optimization?.recommended_resource_config || null;
  const optimizationCurrentConfig = optimization?.current_resource_config || null;
  const optimizationComparison = optimization?.analysis?.comparison_matrix || comparison;

  const matrixCostInInr = (item: { monthly_cost_inr?: number; monthly_cost_usd?: number }) => {
    if (typeof item.monthly_cost_inr === 'number') return item.monthly_cost_inr;
    if (typeof item.monthly_cost_usd === 'number' && typeof optimization?.usd_to_inr_rate === 'number') {
      return item.monthly_cost_usd * optimization.usd_to_inr_rate;
    }
    return null;
  };

  const minimalMonthlyCostInr = optimizationComparison.length
    ? optimizationComparison
      .map((item) => matrixCostInInr(item))
      .filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
      .sort((a, b) => a - b)[0] ?? null
    : null;

  const optimizationEstimatedMonthlyCost =
    minimalMonthlyCostInr ??
    optimization?.monthly_cost_inr ??
    optimization?.recommended_monthly_cost_inr ??
    estimatedMonthlyCost;
  const platformDisplay =
    normalizeProviderName(report?.agentic_insights?.deployment_intelligence?.chosen_platform) ||
    deployedProviderHint ||
    optimizationProvider ||
    normalizeProviderName(report?.project?.preferred_provider) ||
    'railway';
  const platformReasoning =
    report?.agentic_insights?.deployment_intelligence?.rationale ||
    report?.agentic_insights?.deployment_intelligence?.reasoning ||
    platformRationale;

  let savingsPercent: number | null = null;
  if (typeof optimization?.savings_percentage === 'number') {
    savingsPercent = optimization.savings_percentage;
  } else if (
    typeof optimizationCurrentMonthlyCost === 'number' &&
    optimizationCurrentMonthlyCost > 0 &&
    typeof optimizationEstimatedMonthlyCost === 'number'
  ) {
    savingsPercent = ((optimizationCurrentMonthlyCost - optimizationEstimatedMonthlyCost) / optimizationCurrentMonthlyCost) * 100;
  }
  const showSavingsBadge = typeof savingsPercent === 'number' && savingsPercent > 10;

  const debateEvents = useMemo<DebateStreamEvent[]>(() => {
    const fromMessages = messages
      .filter((item) => String(item.type || '').toLowerCase() !== 'argument' && String(item.phase || '').toLowerCase() !== 'reasoning')
      .slice(-80)
      .map((item) => {
      const text = toPlainMessage(String(item.user_message || item.thought || item.decision || item.message || 'Reviewing the next best move.'));
      const status = String(item.status || '').toLowerCase();
      const phase = String(item.phase || item.state || 'analysis');
      const agent = String(item.agent || 'code_agent');
      const data = (item.data && typeof item.data === 'object' ? item.data : {}) as Record<string, unknown>;
      const reason = String(item.reason || data.reason || '').replace(/\s+/g, ' ').trim();
      const result = String(item.result || data.result || '').replace(/\s+/g, ' ').trim();
      return {
        agent,
        role: roleFromAgent(agent),
        message: text,
        reason: reason || undefined,
        result: result || undefined,
        type: inferDebateType(text, status, phase),
        cycle: typeof item.cycle === 'number' ? item.cycle : undefined,
        confidence: typeof item.confidence === 'number' && Number.isFinite(item.confidence)
          ? Math.max(0, Math.min(1, item.confidence))
          : undefined,
      };
    });

    const fromRounds = fromMessages.length > 0 ? [] : rounds.flatMap((round) => {
      if (!Array.isArray(round.statements)) return [];
      return round.statements.flatMap((statement) => {
        const agent = String(statement.agent || 'specialist_agent');
        const role = roleFromAgent(agent);
        const reasoning = toPlainMessage(String(statement.reasoning || statement.message || 'Sharing evaluation details.'));
        const platformHint = String(statement.platform || '').trim();
        if (!reasoning) return [];
        return [{
          agent,
          role,
          message: platformHint
            ? toPlainMessage(`Recommend ${platformHint}: ${reasoning}`)
            : reasoning,
          type: 'action' as const,
        }];
      });
    });

    const merged = [...fromRounds, ...fromMessages].slice(-120);
    const decisionConfidence = Math.max(0.2, Math.min(0.95, progressValue / 100));
    const metaDecision: DebateStreamEvent = {
      agent: 'meta_agent',
      role: 'Meta-Agent',
      message:
        runStatus === 'live'
          ? toPlainMessage(`Deployment finished on ${toTitleCase(platformDisplay)}.`)
          : runStatus === 'failed'
            ? toPlainMessage('Debate closed with a blocker. Recovery options are ready.')
            : toPlainMessage(`Deploying via ${toTitleCase(platformDisplay)} (${Math.round(decisionConfidence * 100)}% confidence).`),
      type: runStatus === 'live' ? 'success' : runStatus === 'failed' ? 'failure' : 'action',
      confidence: decisionConfidence,
    };

    if (merged.length === 0) {
      return [
        {
          agent: 'meta_agent',
          role: 'Meta-Agent',
          message: toPlainMessage(lastProgressMessage || 'Starting agent collaboration now.'),
          type: 'thinking',
          confidence: decisionConfidence,
        },
        metaDecision,
      ];
    }

    const withoutTrailingMeta = merged.filter((event, idx) => !(idx === merged.length - 1 && String(event.role || '').toLowerCase().includes('meta')));
    return [...withoutTrailingMeta, metaDecision];
  }, [messages, rounds, progressValue, runStatus, platformDisplay, lastProgressMessage]);

  const currentDebateEvent = debateEvents[debateEvents.length - 1];
  const aiConfidence =
    typeof currentDebateEvent?.confidence === 'number'
      ? currentDebateEvent.confidence
      : Math.max(0.2, Math.min(0.95, progressValue / 100));
  const confidenceTone = aiConfidence >= 0.8 ? 'high' : aiConfidence >= 0.55 ? 'medium' : 'low';
  const phaseSummary = toTitleCase(String(progressItems[progressItems.length - 1]?.phase || runStatus || 'analysis').replace(/_/g, ' '));
  const analysisLastAction = String(lastProgressMessage || 'Preparing deployment strategy')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 96);

  const liveUrl = String(report?.project?.public_url || report?.deployment?.deployment_url || '').trim();
  const deployedProvider = deployedProviderHint;
  const isLocalPreview = deployedProvider === 'local' || liveUrl.includes('/preview/');
  const localPreviewReason = String((report?.deployment?.details as Record<string, unknown> | undefined)?.note || '').trim();
  const outcomeState: 'thinking' | 'failed' | 'live' | 'ready' =
    runStatus === 'failed'
      ? 'failed'
      : runStatus === 'live'
        ? 'live'
        : analysisComplete
          ? 'ready'
          : 'thinking';

  const whatIFixedSummary = useMemo(() => {
    const fromRetries = recoveryAttempts
      .filter((item) => item.status === 'succeeded' || item.status === 'failed')
      .map((item) => item.fixApplied)
      .filter((item) => item && item.trim().length > 0);
    if (fromRetries.length > 0) return fromRetries.slice(-3);
    return expandedFixPlan.map((item) => item.title).filter(Boolean).slice(0, 3);
  }, [recoveryAttempts, expandedFixPlan]);

  const securityMiniStream = useMemo(
    () => debateEvents
      .filter((event) => String(event.role || event.agent || '').toLowerCase().includes('security'))
      .slice(-3)
      .map((event) => ({
        agent: 'Security Agent',
        message: String(event.message || '').replace(/\s+/g, ' ').trim(),
      })),
    [debateEvents],
  );

  const decisionReasonShort = String(platformReasoning || 'Best fit for static + fast cold start')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 72);

  const rawDebateLines = useMemo(() => {
    const fromWs = (messages || []).slice(-32).map((item) => {
      const phase = String(item.phase || item.state || item.status || 'runtime').replace(/_/g, ' ');
      const agent = String(item.agent || 'agent').replace(/_/g, ' ');
      const text = String(item.user_message || item.thought || item.message || item.decision || '').replace(/\s+/g, ' ').trim();
      return `[${phase}] ${agent}: ${text || 'No message payload'}`;
    });

    if (fromWs.length > 0) return fromWs;
    const fromProgress = (progressItems || []).slice(-16).map((item) => {
      const phase = String(item.phase || 'runtime').replace(/_/g, ' ');
      const message = String(item.message || 'No message payload').replace(/\s+/g, ' ').trim();
      return `[${phase}] system: ${message}`;
    });
    return fromProgress;
  }, [messages, progressItems]);

  const platformAlternatives = report?.agentic_insights?.deployment_intelligence?.alternatives || [];

  const renderCostValue = (value: number | null | undefined) => {
    if (optimizationLoading || (!analysisComplete && value == null)) {
      return <div className="skeleton-line" style={{ width: 130 }} />;
    }
    if (value == null || Number.isNaN(Number(value))) {
      return <span className="tiny">Calculating...</span>;
    }
    return <>{formatCurrencyINR(value)}</>;
  };

  const renderResourceConfig = (
    cfg: { memory_mb?: number; cpu?: number; label?: string; source?: string } | null,
    label: string,
  ) => {
    if (optimizationLoading || (!analysisComplete && !cfg)) {
      return <div className="skeleton-line" style={{ width: 180 }} />;
    }
    if (!cfg) {
      return <div className="tiny">{label}: Calculating...</div>;
    }
    return (
      <div className="tiny">
        {label}: {Number(cfg.memory_mb || 0)}MB / {Number(cfg.cpu || 0).toFixed(2)} vCPU
      </div>
    );
  };

  const onAutoDeploy = async () => {
    if (!parsedId) return;
    if (!analysisComplete) {
      setDeployError('Analysis is still running. Wait for analysis to complete before starting deployment.');
      return;
    }
    navigate(`/deployment/${parsedId}?start=1`);
  };

  const onDownloadAuditReport = async () => {
    if (!parsedId) return;
    try {
      setDownloadingPdf(true);
      const response = await axios.get(`/api/v1/projects/${parsedId}/report/pdf`, {
        responseType: 'blob',
      });

      const blob = new Blob([response.data], { type: 'application/pdf' });
      const downloadUrl = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = `nestify-report-${parsedId}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(downloadUrl);
    } finally {
      setDownloadingPdf(false);
    }
  };

  const onManualResubmit = async () => {
    if (manualSubmitting) return;
    setManualError(null);

    try {
      setManualSubmitting(true);
      let res;

      if (manualSourceType === 'github') {
        if (!manualGithubUrl.trim()) {
          setManualError('Paste a GitHub repository URL to re-run analysis.');
          return;
        }
        res = await axios.post('/api/v1/projects/github', {
          github_url: manualGithubUrl.trim(),
          provider: 'auto',
        });
      } else {
        if (!manualFile) {
          setManualError('Upload an updated ZIP codebase to continue.');
          return;
        }
        const body = new FormData();
        body.append('file', manualFile);
        body.append('agentic', 'true');
        body.append('provider', 'auto');
        res = await axios.post('/api/v1/projects/upload', body);
      }

      const nextProjectId = Number(res?.data?.project_id || 0);
      if (!nextProjectId) {
        setManualError('Manual re-run started but no project id was returned.');
        return;
      }

      window.localStorage.setItem('nestify:lastProjectId', String(nextProjectId));
      navigate(`/analysis/${nextProjectId}`);
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      setManualError(
        typeof detail === 'string' && detail.trim()
          ? `${detail.trim()} Next: verify source access and try manual re-analysis again.`
          : 'Could not start manual re-analysis. Next: verify source upload/GitHub URL and retry.',
      );
    } finally {
      setManualSubmitting(false);
    }
  };

  if (!parsedId) {
    return (
      <main className="page-shell">
        <StateMessage
          variant="empty"
          title="Upload a project to begin"
          detail="Open the Upload page, submit a project, then return to analysis."
        />
      </main>
    );
  }

  return (
    <main className="control-room-page">
      <section className="control-room-shell">
        <div className="control-room-left">
          <AIDebateStream
            events={debateEvents}
            loadingHint={intelligentLoading}
            headline="AI Conversation Stream"
            compact
          />
        </div>

        <aside className="control-room-right sticky-control-panel">
          {loading ? (
            <StateMessage
              variant="loading"
              title="Building analysis context"
              detail={intelligentLoading}
            />
          ) : null}

          {loadError ? (
            <StateMessage
              variant="error"
              title="Analysis data unavailable"
              detail={loadError}
            />
          ) : null}

          <LiveIntelligencePanel
            platformDecision={`Deploying via ${toTitleCase(platformDisplay || 'railway')}`}
            decisionReason={decisionReasonShort}
            confidence={aiConfidence}
            securityStream={securityMiniStream}
            fixSummary={whatIFixedSummary}
            riskSummary={{
              critical: criticalCount,
              high: highCount,
              medium: mediumCount,
            }}
            onPrimaryAction={onAutoDeploy}
            onSecondaryAction={onDownloadAuditReport}
            primaryDisabled={!analysisComplete || recoveryRunning}
            secondaryDisabled={downloadingPdf}
            secondaryLabel="Download Audit Report"
            secondaryLoading={downloadingPdf}
            secondaryLoadingLabel="Generating report..."
          />

          <Card className={`ai-result-card ${outcomeState} view-transition`}>
            <div className="tiny">Status</div>
            <div style={{ fontSize: 18, fontWeight: 700, marginTop: 4 }}>
              {outcomeState === 'live' ? 'Execution complete' : outcomeState === 'failed' ? 'Blocked' : 'In progress'}
            </div>
            <div className="tiny" style={{ marginTop: 8 }}>
              {outcomeState === 'live'
                ? isLocalPreview
                  ? 'Local preview is running. Public deployment not completed.'
                  : 'Deployment succeeded and endpoint is reachable.'
                : outcomeState === 'failed'
                  ? 'Execution failed. Review technical details for exact cause and retry actions.'
                  : 'AI is analyzing and preparing the deployment path.'}
            </div>

            <div style={{ marginTop: 10 }}>
              <div className="tiny">Confidence: {Math.round(aiConfidence * 100)}%</div>
              <div className={`ai-confidence-track ${confidenceTone}`}>
                <div className={`ai-confidence-fill ${confidenceTone}`} style={{ width: `${Math.round(aiConfidence * 100)}%` }} />
              </div>
            </div>

            {liveUrl ? (
              <a href={liveUrl} target="_blank" rel="noreferrer" className="live-link" style={{ marginTop: 10 }}>
                {liveUrl}
              </a>
            ) : null}
          </Card>

          {deployError ? (
            <Card className="deploy-error-card">
              <div style={{ color: '#fca5a5', fontWeight: 600 }}>Deployment configuration required</div>
              <div className="tiny" style={{ marginTop: 6 }}>{deployError}</div>
            </Card>
          ) : null}

          <TechnicalDetailsDrawer
            title="View Technical Details"
            securityReport={(
              <SecurityReport
                score={report?.project?.security_score || 0}
                findings={report?.findings || {}}
              />
            )}
            costAnalysis={(
              <>
                <Card>
                  <div className="tiny"><strong>Estimated monthly cost:</strong> {renderCostValue(optimizationEstimatedMonthlyCost)}</div>
                  <div className="tiny" style={{ marginTop: 6 }}><strong>Cheapest recommendation:</strong> {toTitleCase(optimizationProvider || 'pending')}</div>
                  {costNote ? <div className="tiny" style={{ marginTop: 6 }}>{costNote}</div> : null}
                </Card>
                {report?.agentic_insights?.cost_optimization?.recommended && optimizationComparison.length ? (
                  <CostComparisonTable
                    provider={optimizationProvider}
                    recommended={report.agentic_insights.cost_optimization.recommended as any}
                    comparison_matrix={optimizationComparison as any}
                    method="synthetic_predeploy"
                  />
                ) : null}
              </>
            )}
            fixPlan={(
              <Card>
                <div className="tiny"><strong>Fixes identified:</strong> {expandedFixPlan.length}</div>
                <ul className="autonomous-fix-list" style={{ marginTop: 8 }}>
                  {expandedFixPlan.slice(0, 8).map((item, idx) => (
                    <li key={`${item.title}-${idx}`}>[~] {item.title}</li>
                  ))}
                </ul>
              </Card>
            )}
            debateLogs={(
              <Card>
                <div className="raw-log-box">
                  {debateEvents.length ? debateEvents.slice(-16).map((line, idx) => (
                    <div key={`${line.agent}-${line.message}-${idx}`} className="raw-log-line">{line.role || line.agent}: {line.message}</div>
                  )) : <div className="raw-log-line">No agent conversation captured yet.</div>}
                </div>
              </Card>
            )}
            platformBreakdown={(
              <Card>
                <div className="tiny"><strong>Chosen platform:</strong> {toTitleCase(platformDisplay)}</div>
                <div className="tiny" style={{ marginTop: 6 }}><strong>Reasoning:</strong> {platformReasoning}</div>
                <div className="tiny" style={{ marginTop: 6 }}><strong>Cheapest recommendation:</strong> {toTitleCase(optimizationProvider || 'pending')}</div>
                {platformAlternatives.length ? (
                  <div style={{ marginTop: 8 }} className="tiny">
                    Alternatives: {platformAlternatives.slice(0, 3).map((alt) => toTitleCase(String(alt?.provider || 'unknown'))).join(', ')}
                  </div>
                ) : null}
              </Card>
            )}
          />
        </aside>
      </section>
    </main>
  );
}
