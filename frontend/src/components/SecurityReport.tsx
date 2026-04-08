import React from 'react';
import { AlertTriangle, ChevronDown, ShieldCheck } from 'lucide-react';
import Card from './ui/Card';
import Badge from './ui/Badge';

type Findings = {
  critical?: Array<Record<string, unknown>>;
  high?: Array<Record<string, unknown>>;
  medium?: Array<Record<string, unknown>>;
  info?: Array<Record<string, unknown>>;
};

type Props = {
  score: number;
  findings: Findings;
};

export default function SecurityReport({ score, findings }: Props) {
  const critical = findings.critical?.length || 0;
  const high = findings.high?.length || 0;
  const medium = findings.medium?.length || 0;

  const renderFindingGroup = (title: string, items: Array<Record<string, unknown>> = []) => (
    <details className="menu-popdown" open={title === 'Critical Findings' && items.length > 0}>
      <summary>
        {title} ({items.length}) <ChevronDown size={14} />
      </summary>
      <div className="menu-popdown-content" style={{ gridTemplateColumns: '1fr' }}>
        {items.length === 0 ? (
          <div className="tiny">No items in this category.</div>
        ) : (
          items.slice(0, 8).map((item, index) => (
            <article key={`${title}-${index}`} className="finding-card">
              <div style={{ fontWeight: 700 }}>{String(item.title || item.rule_id || item.type || `Finding ${index + 1}`)}</div>
              <div className="tiny" style={{ marginTop: 4 }}>
                {String(item.description || item.message || item.recommendation || 'No additional detail provided.')}
              </div>
              {item.file ? <div className="tiny mono" style={{ marginTop: 6 }}>File: {String(item.file)}</div> : null}
            </article>
          ))
        )}
      </div>
    </details>
  );

  return (
    <Card className="report-card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3 style={{ margin: 0 }}>Security Report</h3>
        <Badge variant={critical > 0 ? 'error' : high > 0 ? 'warning' : 'success'}>
          <ShieldCheck size={14} /> Score {score}/100
        </Badge>
      </div>

      <div className="grid-3" style={{ marginTop: 12 }}>
        <div className="metric-item">
          <div className="metric-label">Critical</div>
          <div className="metric-value" style={{ color: '#ef4444' }}>{critical}</div>
        </div>
        <div className="metric-item">
          <div className="metric-label">High</div>
          <div className="metric-value" style={{ color: '#f59e0b' }}>{high}</div>
        </div>
        <div className="metric-item">
          <div className="metric-label">Medium</div>
          <div className="metric-value" style={{ color: '#fde047' }}>{medium}</div>
        </div>
      </div>

      <div style={{ marginTop: 12 }}>
        {critical + high + medium === 0 ? (
          <div className="tiny">No major findings detected in current scan.</div>
        ) : (
          <div className="tiny" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <AlertTriangle size={14} color="#f59e0b" />
            Review generated PDF for full exploit and remediation details.
          </div>
        )}
      </div>

      <div style={{ marginTop: 12, display: 'grid', gap: 8 }}>
        {renderFindingGroup('Critical Findings', findings.critical || [])}
        {renderFindingGroup('High Findings', findings.high || [])}
        {renderFindingGroup('Medium Findings', findings.medium || [])}
      </div>
    </Card>
  );
}
