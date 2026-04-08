import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { CheckCircle2, GitBranch, Layers3 } from 'lucide-react';
import Card from './ui/Card';
import Badge from './ui/Badge';
import { formatPercent, toTitleCase } from '../utils/formatters';

type Props = { projectId: number };

type PatternResult = {
  pattern_id?: string;
  rank_score?: number;
  score?: number;
  pattern?: {
    code_profile?: { framework?: string };
    fixes_applied?: string[];
    platform_choice?: string;
  };
};

type PatternResponse = {
  similar_patterns?: PatternResult[];
  insights?: { summary?: string };
};

export default function PatternExplorer({ projectId }: Props) {
  const [data, setData] = useState<PatternResponse | null>(null);

  useEffect(() => {
    axios
      .get(`/api/v1/agentic/patterns/${projectId}`)
      .then((res) => setData(res.data))
      .catch(() => setData({ similar_patterns: [], insights: { summary: 'No patterns available.' } }));
  }, [projectId]);

  const patterns = data?.similar_patterns || [];

  return (
    <Card>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <h3 style={{ margin: 0 }}>Pattern Explorer</h3>
        <Badge variant="intelligence">
          <Layers3 size={14} /> {patterns.length} similar deployments
        </Badge>
      </div>
      <p className="muted" style={{ marginTop: 8 }}>
        {data?.insights?.summary || 'Loading pattern insights...'}
      </p>

      <div style={{ marginTop: 12, display: 'grid', gap: 10 }}>
        {patterns.length === 0 ? (
          <div className="tiny">No pattern matches yet. Deploy more projects to grow confidence.</div>
        ) : null}

        {patterns.slice(0, 6).map((item, index) => {
          const framework = item.pattern?.code_profile?.framework || 'unknown';
          const confidence = Number(item.rank_score || item.score || 0);
          const fixes = item.pattern?.fixes_applied || [];
          return (
            <div
              key={item.pattern_id || index}
              style={{
                border: '1px solid #3f3f46',
                borderRadius: 12,
                background: 'rgba(30,30,33,0.7)',
                padding: 12,
                display: 'grid',
                gap: 8,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  <GitBranch size={14} color="#8b5cf6" />
                  <span>{toTitleCase(framework)}</span>
                </div>
                <Badge variant={confidence > 0.65 ? 'success' : 'warning'}>{formatPercent(confidence, 1)} confidence</Badge>
              </div>

              <div className="tiny">Applied {fixes.length} proactive fixes</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {fixes.slice(0, 3).map((fix) => (
                  <span
                    key={fix}
                    style={{
                      borderRadius: 999,
                      border: '1px solid rgba(16,185,129,0.45)',
                      background: 'rgba(16,185,129,0.15)',
                      color: '#6ee7b7',
                      fontSize: 12,
                      padding: '3px 8px',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 4,
                    }}
                  >
                    <CheckCircle2 size={12} /> {fix}
                  </span>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
