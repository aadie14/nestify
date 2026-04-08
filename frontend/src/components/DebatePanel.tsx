import React from 'react';

type Props = {
  transcript: Array<any>;
  finalDecision: string;
  summary: string;
  confidence: number;
};

export default function DebatePanel({ transcript, finalDecision, summary, confidence }: Props) {
  const proposals = transcript.find((item) => item?.type === 'proposals')?.statements || [];

  return (
    <section className="card debate-grid">
      <div>
        <h3 style={{ marginTop: 0 }}>Debate Arguments</h3>
        <div style={{ display: 'grid', gap: 8 }}>
          {proposals.length === 0 ? <div className="tiny">No live arguments yet.</div> : null}
          {proposals.map((item: any, idx: number) => (
            <div key={idx} className="debate-msg">
              <div style={{ fontWeight: 600 }}>{String(item.agent || 'Agent')}</div>
              <div className="tiny" style={{ marginTop: 4 }}>
                {String(item.reasoning || `I recommend ${item.platform || 'this option'} for this deployment.`)}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="debate-summary">
        <h3 style={{ marginTop: 0 }}>Final Decision</h3>
        <div style={{ fontSize: 24, fontWeight: 700 }}>{String(finalDecision || 'pending').toUpperCase()}</div>
        <p style={{ marginTop: 10 }}>{summary || 'Final decision will appear once debate completes.'}</p>
        <div className="tiny">Confidence: {Math.round((confidence || 0) * 100)}%</div>
      </div>
    </section>
  );
}
