import React from 'react';
import { MessageCircle, Scale } from 'lucide-react';
import Card from './ui/Card';
import Badge from './ui/Badge';
import { DebateRound } from '../hooks/useAgentDebate';
import { formatCurrency, toTitleCase } from '../utils/formatters';
import SkeletonValue from './ui/SkeletonValue';

type Props = {
  rounds: DebateRound[];
  chosenPlatform?: string;
  platformRationale?: string;
  estimatedMonthlyCost?: number;
};

function simplifyReasoning(text: string): string {
  return text
    .replaceAll('runtime mismatch', 'the app may not run correctly on a provider')
    .replaceAll('deployment complexity', 'setup complexity')
    .replaceAll('heuristic', 'estimated')
    .replaceAll('SLA', 'reliability target');
}

export default function AgentDebateTimeline({ rounds, chosenPlatform, platformRationale, estimatedMonthlyCost }: Props) {
  const renderChallenges = (statement: any) => {
    const objections = Array.isArray(statement.objections)
      ? statement.objections
      : Array.isArray(statement.challenges)
        ? statement.challenges
        : [];
    const concessions = Array.isArray(statement.concessions) ? statement.concessions : [];

    return (
      <div style={{ display: 'grid', gap: 8 }}>
        {objections.length > 0 ? (
          <div>
            <div className="tiny" style={{ color: '#f59e0b' }}>Objections</div>
            {objections.map((item: string, idx: number) => (
              <div key={idx} className="tiny" style={{ color: '#d4d4d8' }}>• {item}</div>
            ))}
          </div>
        ) : null}
        {concessions.length > 0 ? (
          <div>
            <div className="tiny" style={{ color: 'var(--brand-primary)' }}>Concessions</div>
            {concessions.map((item: string, idx: number) => (
              <div key={idx} className="tiny" style={{ color: '#d4d4d8' }}>• {item}</div>
            ))}
          </div>
        ) : null}
        {objections.length === 0 && concessions.length === 0 ? (
          <div className="tiny">No explicit objections were recorded in this round.</div>
        ) : null}
      </div>
    );
  };

  return (
    <Card>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3 style={{ margin: 0 }}>Agent Debate</h3>
        <Badge variant="intelligence">
          <Scale size={14} /> Consensus Engine
        </Badge>
      </div>

      <div style={{ marginTop: 10, border: '1px solid rgba(0,217,163,0.4)', borderRadius: 10, padding: 10, background: 'rgba(0,217,163,0.08)' }}>
        <div className="tiny" style={{ marginBottom: 4 }}>In plain English</div>
        <div style={{ fontWeight: 600 }}>
          The agents chose <strong>{toTitleCase(String(chosenPlatform || 'render'))}</strong> because it best balances deployability, risk, and cost for this project.
        </div>
        <div className="tiny" style={{ marginTop: 6 }}>
          Estimated monthly cost: <strong>{estimatedMonthlyCost == null ? <SkeletonValue width={68} /> : formatCurrency(estimatedMonthlyCost)}</strong>
        </div>
        {platformRationale ? <div className="tiny" style={{ marginTop: 6 }}>{simplifyReasoning(platformRationale)}</div> : null}
      </div>

      <div style={{ marginTop: 12, display: 'grid', gap: 10 }}>
        {rounds.length === 0 ? <div className="tiny">Debate transcript will appear once platform planning starts.</div> : null}

        {rounds.map((round) => (
          <div key={`${round.round}-${round.type}`} style={{ border: 0, borderRadius: 12, padding: 12, background: 'rgba(24,24,27,0.45)' }}>
            <div style={{ fontWeight: 600, marginBottom: 8 }}>
              Round {round.round}: {round.type}
            </div>

            {Array.isArray(round.statements)
              ? round.statements.map((statement, idx) => (
                  <div key={idx} style={{ borderTop: idx ? '1px solid #27272a' : 'none', paddingTop: idx ? 8 : 0, marginTop: idx ? 8 : 0 }}>
                    <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                      <MessageCircle size={14} color="var(--brand-primary)" />
                      <strong>{String(statement.agent || 'Agent')}</strong>
                    </div>
                    {round.type === 'challenges' ? (
                      <div style={{ marginTop: 8 }}>{renderChallenges(statement)}</div>
                    ) : (
                      <>
                        {statement.platform ? <p className="tiny" style={{ marginTop: 6, marginBottom: 4 }}>Proposes: <strong>{String(statement.platform)}</strong></p> : null}
                        <p className="tiny" style={{ marginTop: 2 }}>{simplifyReasoning(String(statement.reasoning || 'No reasoning provided'))}</p>
                      </>
                    )}
                  </div>
                ))
              : null}

            {round.decision ? (
              <div style={{ marginTop: 8, border: '1px solid rgba(0,217,163,0.35)', borderRadius: 10, padding: 10, background: 'rgba(0,217,163,0.1)' }}>
                <div className="tiny">Decision</div>
                <div style={{ marginTop: 4, fontWeight: 600 }}>{String(round.decision.decision || 'pending')}</div>
                <div className="tiny" style={{ marginTop: 4 }}>{simplifyReasoning(String(round.decision.reasoning || ''))}</div>
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </Card>
  );
}
