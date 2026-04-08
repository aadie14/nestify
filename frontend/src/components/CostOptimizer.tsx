import React from 'react';
import { DollarSign, Sparkles } from 'lucide-react';
import Card from './ui/Card';
import Button from './ui/Button';
import Badge from './ui/Badge';
import { formatCurrency } from '../utils/formatters';

type Props = {
  optimization: any;
  onApply: () => void;
};

export default function CostOptimizer({ optimization, onApply }: Props) {
  const current = optimization?.current_monthly_cost_usd;
  const recommended = optimization?.recommended_monthly_cost_usd;
  const savings = optimization?.potential_monthly_savings_usd;
  const utilization = Math.max(10, Math.min(100, Number(optimization?.suggested_memory_utilization_percent || 62)));

  return (
    <Card>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
        <h3 style={{ margin: 0 }}>Cost Optimization</h3>
        <Badge variant="success">
          <Sparkles size={14} /> Savings Model
        </Badge>
      </div>

      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8, marginTop: 16 }}>
        <DollarSign size={24} color="#10b981" />
        <div style={{ fontSize: 44, lineHeight: 1, fontWeight: 700, color: '#10b981' }}>{formatCurrency(savings || 0)}</div>
      </div>
      <div className="tiny" style={{ marginTop: 6 }}>
        Estimated monthly savings vs default deployment resources
      </div>

      <div style={{ marginTop: 16, display: 'grid', gap: 8 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span className="tiny">Current</span>
          <span className="tiny mono">{formatCurrency(current)}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span className="tiny">Recommended</span>
          <span className="tiny mono">{formatCurrency(recommended)}</span>
        </div>
      </div>

      <div style={{ marginTop: 14 }}>
        <div className="tiny" style={{ marginBottom: 6 }}>
          Resource utilization
        </div>
        <div className="progress-wrap">
          <div className="progress-bar" style={{ width: `${utilization}%`, background: 'var(--gradient-success)' }} />
        </div>
      </div>

      <div style={{ marginTop: 16 }}>
        <Button variant="primary" onClick={onApply}>
          Apply Optimization
        </Button>
      </div>
    </Card>
  );
}
