import React from 'react';
import { Check, DollarSign, TrendingDown, X } from 'lucide-react';

type CostTier = {
  config: {
    memory_mb: number;
    cpu: number | string;
    label: string;
  };
  benchmark: {
    p95_ms: number;
    success_rate: number;
    meets_sla: boolean;
  };
  monthly_cost_usd: number;
};

type Props = {
  provider: string;
  recommended: CostTier;
  comparison_matrix: CostTier[];
  method: 'http_probe' | 'synthetic_predeploy';
};

export default function CostComparisonTable({ provider, recommended, comparison_matrix, method }: Props) {
  const fallback = comparison_matrix.find((row) => String(row.config.label).toLowerCase() === 'recommended');
  const savings = fallback ? Number(fallback.monthly_cost_usd) - Number(recommended.monthly_cost_usd) : 0;

  return (
    <div className="card" style={{ display: 'grid', gap: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <DollarSign size={18} color="#10b981" />
          <h3 style={{ margin: 0 }}>Cost Optimization Analysis</h3>
        </div>
        <span className="tiny" style={{ color: method === 'http_probe' ? '#10b981' : '#a1a1aa' }}>
          {method === 'http_probe' ? 'Live tested' : 'Synthetic estimate'}
        </span>
      </div>

      {savings > 0 && fallback ? (
        <div
          style={{
            border: '1px solid rgba(16,185,129,0.4)',
            borderRadius: 12,
            background: 'rgba(16,185,129,0.12)',
            padding: 12,
            display: 'flex',
            alignItems: 'center',
            gap: 10,
          }}
        >
          <TrendingDown size={18} color="#10b981" />
          <div>
            <div style={{ fontWeight: 700 }}>Saves ${savings.toFixed(2)}/month</div>
            <div className="tiny">
              {Math.round((savings / Math.max(0.01, Number(fallback.monthly_cost_usd))) * 100)}% lower than baseline
            </div>
          </div>
        </div>
      ) : null}

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #3f3f46' }}>
              <th style={{ textAlign: 'left', padding: 10 }} className="tiny">Configuration</th>
              <th style={{ textAlign: 'center', padding: 10 }} className="tiny">Resources</th>
              <th style={{ textAlign: 'center', padding: 10 }} className="tiny">Performance</th>
              <th style={{ textAlign: 'center', padding: 10 }} className="tiny">SLA</th>
              <th style={{ textAlign: 'right', padding: 10 }} className="tiny">Cost</th>
            </tr>
          </thead>
          <tbody>
            {comparison_matrix.map((tier, idx) => {
              const isRecommended = String(tier.config.label).toLowerCase() === String(recommended.config.label).toLowerCase();
              return (
                <tr key={idx} style={{ borderBottom: '1px solid #27272a', background: isRecommended ? 'rgba(139,92,246,0.14)' : 'transparent' }}>
                  <td style={{ padding: 12 }}>
                    <div style={{ fontWeight: 700 }}>{tier.config.label}</div>
                    {isRecommended ? <div className="tiny" style={{ color: '#c4b5fd' }}>Recommended</div> : null}
                  </td>
                  <td style={{ padding: 12, textAlign: 'center' }}>
                    <div>{tier.config.memory_mb}MB</div>
                    <div className="tiny">{tier.config.cpu} vCPU</div>
                  </td>
                  <td style={{ padding: 12, textAlign: 'center' }}>
                    <div>P95 {Number(tier.benchmark.p95_ms || 0).toFixed(0)}ms</div>
                    <div className="tiny">{(Number(tier.benchmark.success_rate || 0) * 100).toFixed(1)}% success</div>
                  </td>
                  <td style={{ padding: 12, textAlign: 'center' }}>
                    {tier.benchmark.meets_sla ? (
                      <span style={{ color: '#10b981', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                        <Check size={14} /> pass
                      </span>
                    ) : (
                      <span style={{ color: '#ef4444', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                        <X size={14} /> fail
                      </span>
                    )}
                  </td>
                  <td style={{ padding: 12, textAlign: 'right', fontWeight: 700 }}>${Number(tier.monthly_cost_usd || 0).toFixed(2)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="tiny" style={{ textAlign: 'right' }}>Provider: {provider || 'unknown'}</div>
    </div>
  );
}
