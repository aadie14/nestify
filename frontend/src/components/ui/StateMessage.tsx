import React from 'react';
import { motion } from 'framer-motion';

type Variant = 'info' | 'loading' | 'error' | 'success' | 'empty';

type Props = {
  variant?: Variant;
  title: string;
  detail?: string;
  className?: string;
};

export default function StateMessage({
  variant = 'info',
  title,
  detail,
  className = '',
}: Props) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: 'easeOut' }}
      className={`state-message ${variant} ${className}`.trim()}
      role={variant === 'error' ? 'alert' : 'status'}
      aria-live="polite"
    >
      <div className="state-message-title">{title}</div>
      {detail ? <div className="state-message-detail">{detail}</div> : null}
    </motion.div>
  );
}
