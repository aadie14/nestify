import React, { useState } from 'react';
import { Brain, ChevronDown, ChevronUp, Lightbulb } from 'lucide-react';

type Props = {
  agent: string;
  thought: string;
  decision: string;
  confidence: number;
  evidence?: string[];
  data?: Record<string, unknown>;
};

const AGENT_CONFIG: Record<string, { label: string; color: string }> = {
  code_analyst: { label: 'Code Intelligence', color: '#3B82F6' },
  security_expert: { label: 'Security Analysis', color: '#A855F7' },
  cost_optimizer: { label: 'Cost Optimization', color: '#10B981' },
  platform_strategist: { label: 'Platform Selection', color: '#F97316' },
};

export default function AgentReasoningCard({ agent, thought, decision, confidence, evidence, data }: Props) {
  const [open, setOpen] = useState(false);
  const key = String(agent || '').toLowerCase();
  const config = AGENT_CONFIG[key] || { label: agent || 'Agent', color: '#6B7280' };

  return (
    <div className="card" style={{ borderColor: '#3f3f46', display: 'grid', gap: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div
            style={{
              width: 34,
              height: 34,
              borderRadius: 10,
              display: 'grid',
              placeItems: 'center',
              background: `${config.color}20`,
              border: `1px solid ${config.color}50`,
            }}
          >
            <Brain size={18} color={config.color} />
          </div>
          <div>
            <div style={{ fontWeight: 700 }}>{config.label}</div>
            <div className="tiny">Confidence {Math.round((confidence || 0) * 100)}%</div>
          </div>
        </div>

        <button className="btn btn-ghost" onClick={() => setOpen((v) => !v)}>
          {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          Details
        </button>
      </div>

      <div style={{ border: '1px solid #3f3f46', borderRadius: 10, padding: 12, background: 'rgba(39,39,42,0.45)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
          <Lightbulb size={14} color="#f59e0b" />
          <span className="tiny">Thought Process</span>
        </div>
        <p style={{ margin: 0 }}>{thought || 'No reasoning provided.'}</p>
      </div>

      <div style={{ borderLeft: `3px solid ${config.color}`, background: `${config.color}12`, padding: 10, borderRadius: 8 }}>
        <div className="tiny" style={{ marginBottom: 4 }}>Decision</div>
        <div>{decision || 'No decision summary available.'}</div>
      </div>

      {open ? (
        <div style={{ display: 'grid', gap: 10 }}>
          {evidence && evidence.length > 0 ? (
            <div>
              <div className="tiny" style={{ marginBottom: 6 }}>Supporting Evidence</div>
              {evidence.map((item, idx) => (
                <div key={idx} className="tiny" style={{ color: '#d4d4d8' }}>
                  • {item}
                </div>
              ))}
            </div>
          ) : null}

          {data ? (
            <details>
              <summary className="tiny" style={{ cursor: 'pointer' }}>Raw Data</summary>
              <pre
                className="mono"
                style={{ marginTop: 8, padding: 10, borderRadius: 8, border: '1px solid #3f3f46', background: '#101114' }}
              >
                {JSON.stringify(data, null, 2)}
              </pre>
            </details>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
