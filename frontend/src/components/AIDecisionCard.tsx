import React from 'react';

type Props = {
  decision: string;
  confidence: number;
  attemptCount: number;
  currentPhase: string;
  lastAction: string;
  title?: string;
};

function clampConfidence(value: number) {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(1, value));
}

export default function AIDecisionCard({
  decision,
  confidence,
  attemptCount,
  currentPhase,
  lastAction,
  title = 'AI Decision',
}: Props) {
  const normalized = clampConfidence(confidence);
  const confidencePercent = Math.round(normalized * 100);
  const safeDecision = (decision || 'Pending').replace(/\s+/g, ' ').trim();
  const safePhase = (currentPhase || 'Initializing').replace(/\s+/g, ' ').trim();
  const safeAction = (lastAction || 'Preparing next autonomous action').replace(/\s+/g, ' ').trim();

  return (
    <section className="card decision-panel-compact">
      <h3 style={{ margin: 0 }}>{title}</h3>

      <div className="decision-block">
        <div className="tiny">Decision</div>
        <div className="decision-value">{safeDecision}</div>
      </div>

      <div className="decision-block" style={{ display: 'grid', gap: 6 }}>
        <div className="tiny">Confidence</div>
        <div className="ai-confidence-track">
          <div className="ai-confidence-fill" style={{ width: `${confidencePercent}%` }} />
        </div>
        <div className="decision-kv">{confidencePercent}%</div>
      </div>

      <div className="decision-block">
        <div className="tiny">Status</div>
        <div className="decision-kv-row">
          <span className="decision-kv">Attempt {Math.max(1, Number(attemptCount) || 1)}</span>
          <span className="decision-kv">{safePhase}</span>
        </div>
      </div>

      <div className="decision-block">
        <div className="tiny">Last action</div>
        <div className="decision-last-action">{safeAction}</div>
      </div>
    </section>
  );
}
