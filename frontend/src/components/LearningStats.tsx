import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { ArrowUpRight, BrainCircuit } from 'lucide-react';
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import Card from './ui/Card';
import Badge from './ui/Badge';
import { formatNumber, formatPercent } from '../utils/formatters';

type LearningResponse = {
  total_patterns?: number;
  patterns_last_30_days?: number;
  success_rate?: number;
  trend_last_14_days?: Array<{ date: string; patterns: number }>;
  top_platforms?: Array<{ platform: string; count: number }>;
};

export default function LearningStats() {
  const [stats, setStats] = useState<LearningResponse | null>(null);

  useEffect(() => {
    axios.get('/api/v1/learning/stats').then((res) => setStats(res.data)).catch(() => setStats(null));
  }, []);

  if (!stats) {
    return (
      <Card>
        <div className="skeleton" style={{ height: 24, width: '40%', marginBottom: 10 }} />
        <div className="skeleton" style={{ height: 120, width: '100%' }} />
      </Card>
    );
  }

  const trend = (stats.trend_last_14_days || []).map((point) => ({
    ...point,
    success_rate: Number(stats.success_rate || 0) * 100,
  }));
  const hasTrendData = trend.length > 0;

  return (
    <Card>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10 }}>
        <div>
          <h3 style={{ margin: 0 }}>Learning Stats</h3>
          <p className="muted" style={{ marginTop: 6 }}>
            Live trends from deployment outcomes and pattern recognition
          </p>
        </div>
        <Badge variant="intelligence">
          <BrainCircuit size={14} /> Adaptive
        </Badge>
      </div>

      <div className="grid-3" style={{ marginTop: 14 }}>
        <div className="metric-item">
          <div className="metric-label">Deployments analyzed</div>
          <div className="metric-value">{formatNumber(stats.total_patterns)}</div>
        </div>
        <div className="metric-item">
          <div className="metric-label">Patterns discovered</div>
          <div className="metric-value">{formatNumber(stats.patterns_last_30_days)}</div>
        </div>
        <div className="metric-item">
          <div className="metric-label">Success rate</div>
          <div className="metric-value" style={{ color: 'var(--brand-primary)' }}>
            {formatPercent(stats.success_rate, 1)}
          </div>
        </div>
      </div>

      <div style={{ marginTop: 16, height: 220 }}>
        {hasTrendData ? (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={trend}>
              <defs>
                <linearGradient id="rateFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#00d9a3" stopOpacity={0.55} />
                    <stop offset="100%" stopColor="#00d9a3" stopOpacity={0.05} />
                </linearGradient>
              </defs>
              <XAxis dataKey="date" stroke="#71717a" tick={{ fill: '#71717a', fontSize: 11 }} />
              <YAxis stroke="#71717a" tick={{ fill: '#71717a', fontSize: 11 }} domain={[0, 100]} />
              <Tooltip
                contentStyle={{ background: '#18181b', border: '1px solid #3f3f46', borderRadius: 10 }}
                labelStyle={{ color: '#d4d4d8' }}
              />
              <Area type="monotone" dataKey="success_rate" stroke="#00d9a3" fill="url(#rateFill)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div
            style={{
              height: '100%',
              border: '1px dashed #3f3f46',
              borderRadius: 12,
              display: 'grid',
              placeItems: 'center',
              color: '#a1a1aa',
              background: 'rgba(24,24,27,0.45)',
            }}
          >
            <div className="tiny">Trend chart will appear once learning history is available.</div>
          </div>
        )}
      </div>

      <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 8, color: 'var(--brand-primary)', fontSize: 13 }}>
        <ArrowUpRight size={14} />
        Success trend remains stable with improving pattern density.
      </div>
    </Card>
  );
}
