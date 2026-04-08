import React, { useState } from 'react';
import { Download, Rocket } from 'lucide-react';
import Card from './ui/Card';
import Button from './ui/Button';

type Props = {
  fixesCount: number;
  platform: string;
  onAutoDeploy: () => Promise<void>;
  onManual: () => Promise<void>;
  downloadingPdf?: boolean;
  canAutoDeploy?: boolean;
  blockedReason?: string | null;
};

export default function DecisionPoint({
  fixesCount,
  platform,
  onAutoDeploy,
  onManual,
  downloadingPdf = false,
  canAutoDeploy = true,
  blockedReason = null,
}: Props) {
  const [deploying, setDeploying] = useState(false);

  const triggerDeploy = async () => {
    if (deploying || !canAutoDeploy) return;
    setDeploying(true);
    try {
      await onAutoDeploy();
    } finally {
      setDeploying(false);
    }
  };

  return (
    <Card className="decision-card">
      <h3 style={{ marginTop: 0 }}>Your Decision</h3>
      <div className="grid-2" style={{ marginTop: 10 }}>
        <div className="metric-item decision-panel" style={{ padding: 16 }}>
          <h4 style={{ marginTop: 0, marginBottom: 6 }}>Autonomous Production Deployment</h4>
          <div className="tiny">Apply all {fixesCount} validated fixes and release to {platform || 'recommended platform'}.</div>
          {!canAutoDeploy && blockedReason ? (
            <div className="tiny" style={{ marginTop: 8, color: '#fca5a5' }}>{blockedReason}</div>
          ) : null}
          <div style={{ marginTop: 12, display: 'grid', gap: 8 }}>
            <Button variant="primary" onClick={triggerDeploy} loading={deploying} disabled={!canAutoDeploy}>
              <Rocket size={14} /> Full Autonomous Deployment (Self-Healing Enabled)
            </Button>
          </div>
        </div>

        <div className="metric-item decision-panel" style={{ padding: 16 }}>
          <h4 style={{ marginTop: 0, marginBottom: 6 }}>Manual Remediation Workflow</h4>
          <div className="tiny">Download a detailed security and deployment report for manual fixes.</div>
          <div style={{ marginTop: 12, display: 'grid', gap: 8 }}>
            <Button variant="ghost" onClick={onManual}>
              <Download size={14} /> {downloadingPdf ? 'Preparing PDF...' : 'Download Detailed Report'}
            </Button>
          </div>
        </div>
      </div>
    </Card>
  );
}
