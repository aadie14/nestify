import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { TrendingUp } from 'lucide-react';
import Card from './ui/Card';
import SkeletonValue from './ui/SkeletonValue';

type Batch = {
  batch: string;
  deployments: number;
  success_rate: number;
  avg_time_seconds: number;
};

type LearningProof = {
  success_rate_by_batch: Batch[];
  improvement: {
    success_rate_increase: number;
    time_reduction: number;
    total_deployments: number;
  } | null;
  patterns_discovered: number;
  proof_statement: string;
};

export default function LearningProofCard() {
  const [data, setData] = useState<LearningProof | null>(null);

  useEffect(() => {
    let alive = true;
    axios
      .get('/api/v1/metrics/learning-proof')
      .then((res) => {
        if (!alive) return;
        setData(res.data || null);
      })
      .catch(() => {
        if (!alive) return;
        setData(null);
      });

    return () => {
      alive = false;
    };
  }, []);

  if (!data) {
    return (
      <Card>
        <h3 style={{ marginTop: 0 }}>Learning Proof</h3>
        <div className="tiny">No learning trend data yet.</div>
      </Card>
    );
  }

  const latest = data.success_rate_by_batch[data.success_rate_by_batch.length - 1];
  const first = data.success_rate_by_batch[0];

  return (
    <Card>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
        <h3 style={{ margin: 0 }}>Learning Proof</h3>
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--brand-primary)' }}>
          <TrendingUp size={14} />
          <span className="tiny">Continuous improvement</span>
        </div>
      </div>

      <div className="grid-3" style={{ marginTop: 12 }}>
        <div className="metric-item">
          <div className="metric-label">Patterns discovered</div>
          <div className="metric-value">{data.patterns_discovered}</div>
        </div>
        <div className="metric-item">
          <div className="metric-label">First batch success</div>
          <div className="metric-value">{first ? `${Math.round(first.success_rate * 100)}%` : <SkeletonValue width={48} />}</div>
        </div>
        <div className="metric-item">
          <div className="metric-label">Latest batch success</div>
          <div className="metric-value" style={{ color: 'var(--brand-primary)' }}>
            {latest ? `${Math.round(latest.success_rate * 100)}%` : <SkeletonValue width={48} />}
          </div>
        </div>
      </div>

      {data.improvement ? (
        <div style={{ marginTop: 12, border: '1px solid rgba(16,185,129,0.35)', borderRadius: 10, padding: 10, background: 'rgba(16,185,129,0.1)' }}>
          <div className="tiny">Success rate increase: {(data.improvement.success_rate_increase * 100).toFixed(1)}%</div>
          <div className="tiny">Average time reduction: {data.improvement.time_reduction.toFixed(1)}s</div>
          <div className="tiny">Total deployments tracked: {data.improvement.total_deployments}</div>
        </div>
      ) : null}

      <p className="tiny" style={{ marginTop: 10 }}>{data.proof_statement}</p>
    </Card>
  );
}
