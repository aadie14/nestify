import React from 'react';
import { CheckCircle2, Circle, Loader2 } from 'lucide-react';

type StageStatus = 'pending' | 'active' | 'complete' | 'failed';

type Stage = {
  key: string;
  label: string;
  description: string;
  status: StageStatus;
};

type Props = {
  stages: Stage[];
  onSelect?: (stageKey: string) => void;
};

export default function ProjectPipelineView({ stages, onSelect }: Props) {
  const iconFor = (status: StageStatus) => {
    if (status === 'complete') return <CheckCircle2 size={16} color="#10b981" />;
    if (status === 'active') return <Loader2 size={16} color="#8b5cf6" className="spin" />;
    return <Circle size={16} color={status === 'failed' ? '#ef4444' : '#71717a'} />;
  };

  return (
    <section className="card" style={{ display: 'grid', gap: 12 }}>
      <h3 style={{ margin: 0 }}>Project Pipeline</h3>
      <div className="pipeline-row">
        {stages.map((stage, idx) => (
          <React.Fragment key={stage.key}>
            <button
              className={`pipeline-stage ${stage.status}`}
              onClick={() => onSelect?.(stage.key)}
              type="button"
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                {iconFor(stage.status)}
                <span style={{ fontWeight: 600 }}>{stage.label}</span>
              </div>
              <div className="tiny" style={{ marginTop: 4 }}>{stage.description}</div>
            </button>
            {idx < stages.length - 1 ? <div className="pipeline-connector" /> : null}
          </React.Fragment>
        ))}
      </div>
    </section>
  );
}
