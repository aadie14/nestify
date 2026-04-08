import React from 'react';
import { motion } from 'framer-motion';

type Props = {
  value: number;
  label?: string;
};

export default function Progress({ value, label }: Props) {
  const clamped = Math.max(0, Math.min(100, value));
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      {label ? <div className="tiny">{label}</div> : null}
      <div className="progress-wrap" role="progressbar" aria-valuenow={Math.round(clamped)} aria-valuemin={0} aria-valuemax={100}>
        <motion.div
          className="progress-bar"
          animate={{ width: `${clamped}%` }}
          transition={{ type: 'spring', stiffness: 120, damping: 22, mass: 0.5 }}
        />
      </div>
    </div>
  );
}
