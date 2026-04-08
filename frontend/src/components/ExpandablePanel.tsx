import React from 'react';

type SectionProps = {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
};

function Section({ title, children, defaultOpen = false }: SectionProps) {
  return (
    <details className="menu-popdown" open={defaultOpen}>
      <summary>{title}</summary>
      <div className="menu-popdown-content" style={{ gridTemplateColumns: '1fr' }}>
        {children}
      </div>
    </details>
  );
}

type Props = {
  securityReport: React.ReactNode;
  costMatrix: React.ReactNode;
  fixPlan: React.ReactNode;
  debateLogs: React.ReactNode;
  title?: string;
  defaultOpen?: boolean;
};

export default function ExpandablePanel({
  securityReport,
  costMatrix,
  fixPlan,
  debateLogs,
  title = 'Deep Analysis Panels',
  defaultOpen = false,
}: Props) {
  return (
    <details className="menu-popdown" open={defaultOpen}>
      <summary>{title}</summary>
      <div className="menu-popdown-content" style={{ gridTemplateColumns: '1fr', gap: 10 }}>
        <Section title="Security Report" defaultOpen>
          {securityReport}
        </Section>

        <Section title="Cost Matrix">
          {costMatrix}
        </Section>

        <Section title="Fix Plan">
          {fixPlan}
        </Section>

        <Section title="Debate Logs">
          {debateLogs}
        </Section>
      </div>
    </details>
  );
}
