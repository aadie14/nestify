import React from 'react';
import { ChevronDown } from 'lucide-react';
import Button from './ui/Button';
import SkeletonValue from './ui/SkeletonValue';

type Props = {
  status: string;
  provider?: string;
  deploymentUrl?: string;
  cost?: number | null;
  createdAt?: string;
  details?: Record<string, unknown>;
  onRedeploy: () => Promise<void>;
  onRestart: () => Promise<void>;
  onStop: () => Promise<void>;
};

export default function DeploymentResultCard({ status, provider, deploymentUrl, cost, createdAt, details, onRedeploy, onRestart, onStop }: Props) {
  const normalizedProvider = String(provider || '').toLowerCase();
  const normalizedStatus = String(status || '').toLowerCase();
  const plainEnglishError =
    typeof details?.plain_english_error === 'string'
      ? details.plain_english_error
      : typeof details?.error === 'string'
        ? details.error
        : null;
  const detailNote = typeof details?.note === 'string' ? details.note : null;

  const liveUrlHint = (() => {
    if (deploymentUrl) return null;
    if (plainEnglishError) return plainEnglishError;
    if (detailNote) return detailNote;
    if (normalizedProvider === 'local') {
      return 'This app is running on local preview because no public provider token was configured.';
    }
    if (normalizedStatus === 'failed') {
      return 'Deployment failed. Open logs in the monitoring panel and redeploy after fixing provider configuration.';
    }
    return 'Live URL will appear when deployment is ready.';
  })();

  return (
    <section className="card" style={{ display: 'grid', gap: 12 }}>
      <h3 style={{ margin: 0 }}>Deployment Result</h3>
      <div className="grid-3">
        <div className="metric-item"><div className="metric-label">Status</div><div className="metric-value">{status || 'unknown'}</div></div>
        <div className="metric-item"><div className="metric-label">Platform</div><div className="metric-value">{provider || <SkeletonValue width={70} />}</div></div>
        <div className="metric-item"><div className="metric-label">Estimated Cost</div><div className="metric-value">{cost == null ? <SkeletonValue width={84} /> : `$${Number(cost).toFixed(2)}/mo`}</div></div>
      </div>

      {deploymentUrl ? (
        <a href={deploymentUrl} target="_blank" rel="noreferrer" className="mono" style={{ color: 'var(--brand-primary)' }}>
          {deploymentUrl}
        </a>
      ) : (
        <div className="tiny" style={{ color: 'var(--brand-warning)' }}>{liveUrlHint}</div>
      )}

      <div className="tiny">Updated: {createdAt || <SkeletonValue width={72} />}</div>

      <details className="menu-popdown">
        <summary>
          Deployment Controls <ChevronDown size={14} />
        </summary>
        <div className="menu-popdown-content" style={{ gridTemplateColumns: 'repeat(3, minmax(0, 1fr))' }}>
          <Button variant="secondary" onClick={onRedeploy}>Redeploy</Button>
          <Button variant="ghost" onClick={onRestart}>Restart</Button>
          <Button variant="ghost" onClick={onStop}>Stop</Button>
        </div>
      </details>
    </section>
  );
}
