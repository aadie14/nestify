import React from 'react';

type Props = {
  logs: Array<any>;
  recommendations: string[];
};

export default function MonitoringConsole({ logs, recommendations }: Props) {
  const recent = logs.slice(-30);
  return (
    <section className="card" style={{ display: 'grid', gap: 12 }}>
      <h3 style={{ margin: 0 }}>Monitoring Console</h3>
      <div className="console-box">
        {recent.length === 0 ? <div className="tiny">No logs yet.</div> : null}
        {recent.map((log, idx) => (
          <div key={idx} className="console-line">
            <span className="tiny">[{String(log.created_at || '').slice(11, 19) || '--:--:--'}]</span>
            <span style={{ color: '#a1a1aa' }}>{String(log.stage || 'system')}:</span>
            <span>{String(log.message || '')}</span>
          </div>
        ))}
      </div>

      <div>
        <div className="tiny" style={{ marginBottom: 6 }}>AI Recommendations</div>
        {recommendations.length === 0 ? <div className="tiny">Recommendations will appear after monitoring signals stabilize.</div> : null}
        {recommendations.map((item, idx) => (
          <div key={idx} className="tiny" style={{ color: '#d4d4d8' }}>• {item}</div>
        ))}
      </div>
    </section>
  );
}
