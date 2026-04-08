import React from 'react';
import Button from './ui/Button';

type SecurityLine = {
  agent: string;
  message: string;
};

type Props = {
  platformDecision: string;
  decisionReason: string;
  confidence: number;
  securityStream: SecurityLine[];
  fixSummary: string[];
  riskSummary: {
    critical: number;
    high: number;
    medium: number;
  };
  onPrimaryAction: () => void;
  onSecondaryAction: () => void;
  primaryDisabled?: boolean;
  secondaryDisabled?: boolean;
  secondaryLabel?: string;
  secondaryLoadingLabel?: string;
  secondaryLoading?: boolean;
};

function clamp(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(1, value));
}

function toFixBullet(line: string): string {
  const clean = String(line || '').replace(/\s+/g, ' ').trim();
  if (!clean) return '[~] Updated deployment plan';
  if (/^\[[+~-]\]/.test(clean)) return clean;
  if (/(add|added|set|inject|create|enabled|patched)\b/i.test(clean)) return `[+] ${clean}`;
  if (/(remove|removed|delete|deleted|drop|stripped)\b/i.test(clean)) return `[-] ${clean}`;
  return `[~] ${clean}`;
}

export default function LiveIntelligencePanel({
  platformDecision,
  decisionReason,
  confidence,
  securityStream,
  fixSummary,
  riskSummary,
  onPrimaryAction,
  onSecondaryAction,
  primaryDisabled,
  secondaryDisabled,
  secondaryLabel,
  secondaryLoadingLabel,
  secondaryLoading,
}: Props) {
  const confidencePct = Math.round(clamp(confidence) * 100);

  return (
    <section className="card live-intel-panel">
      <div className="live-intel-section">
        <div className="tiny">Platform Decision</div>
        <div className="live-intel-title">{platformDecision}</div>
        <div className="tiny">{decisionReason}</div>
        <div className="live-intel-kv">Confidence {confidencePct}%</div>
      </div>

      <div className="live-intel-section">
        <div className="tiny">Security Summary</div>
        <div className="live-security-stream">
          {(securityStream.length ? securityStream : [{ agent: 'Security Agent', message: 'Monitoring security posture and preparing hardening steps.' }]).slice(-3).map((line, idx) => (
            <div className="live-security-row" key={`${line.agent}-${line.message}-${idx}`}>
              <span className="live-security-agent">🛡 {line.agent}:</span>
              <span className="live-security-msg">{line.message}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="live-intel-section">
        <div className="tiny">Fix Summary</div>
        <ul className="live-fix-list">
          {(fixSummary.length ? fixSummary : ['[~] Awaiting next automated remediation']).slice(0, 4).map((line, idx) => (
            <li key={`${line}-${idx}`}>{toFixBullet(line)}</li>
          ))}
        </ul>
      </div>

      <div className="live-intel-section">
        <div className="tiny">Security Risk Summary</div>
        <div className="live-risk-grid">
          <div className="live-risk-cell critical">Critical {riskSummary.critical}</div>
          <div className="live-risk-cell high">High {riskSummary.high}</div>
          <div className="live-risk-cell medium">Medium {riskSummary.medium}</div>
        </div>
      </div>

      <div className="live-intel-section">
        <div className="tiny">Download Full Audit Report</div>
        <Button variant="secondary" onClick={onSecondaryAction} disabled={secondaryDisabled}>
          {secondaryLoading ? (secondaryLoadingLabel || 'Generating report...') : (secondaryLabel || 'Download Audit Report')}
        </Button>
      </div>

      <div className="live-intel-actions">
        <div className="tiny" style={{ gridColumn: '1 / -1' }}>Action Buttons</div>
        <Button variant="primary" onClick={onPrimaryAction} disabled={primaryDisabled}>
          Autonomous Fix & Deploy
        </Button>
      </div>
    </section>
  );
}
