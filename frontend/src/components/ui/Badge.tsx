import React from 'react';

type Variant = 'default' | 'success' | 'warning' | 'error' | 'intelligence';

type Props = {
  children: React.ReactNode;
  variant?: Variant;
};

export default function Badge({ children, variant = 'default' }: Props) {
  const styles: Record<Variant, React.CSSProperties> = {
    default: { background: 'rgba(63,63,70,0.45)', border: '1px solid #3f3f46', color: '#d4d4d8' },
    success: { background: 'rgba(0,217,163,0.2)', border: '1px solid rgba(0,217,163,0.45)', color: '#b6ffe9' },
    warning: { background: 'rgba(245,158,11,0.2)', border: '1px solid rgba(245,158,11,0.45)', color: '#fcd34d' },
    error: { background: 'rgba(239,68,68,0.2)', border: '1px solid rgba(239,68,68,0.45)', color: '#fca5a5' },
    intelligence: { background: 'rgba(0,217,163,0.2)', border: '1px solid rgba(0,217,163,0.45)', color: '#b6ffe9' },
  };

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        borderRadius: 999,
        padding: '4px 10px',
        fontSize: 12,
        fontWeight: 600,
        ...styles[variant],
      }}
    >
      {children}
    </span>
  );
}
