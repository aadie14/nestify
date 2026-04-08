import React from 'react';
import { Rocket, ExternalLink, CheckCircle2 } from 'lucide-react';

type Props = {
  state: 'SUCCESS';
  url: string;
  actions?: string[];
  title?: string;
};

const DEFAULT_ACTIONS = [
  'Fixed env variables',
  'Selected platform',
  'Adjusted config',
];

export default function DeploymentResult({
  state,
  url,
  actions = DEFAULT_ACTIONS,
  title = 'Your app is live',
}: Props) {
  if (state !== 'SUCCESS') return null;

  return (
    <section className="card" style={{ display: 'grid', gap: 12, borderColor: 'rgba(0, 217, 163, 0.55)', background: 'rgba(0, 217, 163, 0.1)' }}>
      <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 24, fontWeight: 800 }}>
        <Rocket size={22} /> {title}
      </div>

      <div style={{ display: 'grid', gap: 6 }}>
        <div className="tiny">URL</div>
        <a href={url} target="_blank" rel="noreferrer" className="live-link" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          {url}
          <ExternalLink size={14} />
        </a>
      </div>

      <div style={{ display: 'grid', gap: 6 }}>
        <div className="tiny">What I did</div>
        <div style={{ display: 'grid', gap: 6 }}>
          {actions.map((item, idx) => (
            <div key={`${idx}-${item}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              <CheckCircle2 size={14} color="var(--brand-success)" />
              <span>{item}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
