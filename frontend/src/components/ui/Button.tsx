import React from 'react';
import { motion } from 'framer-motion';

type ButtonVariant = 'primary' | 'secondary' | 'success' | 'ghost';

type Props = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: 'md' | 'lg';
  loading?: boolean;
  children: React.ReactNode;
};

export default function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  children,
  className = '',
  disabled,
  ...props
}: Props) {
  const variantClass = {
    primary: 'btn-primary',
    secondary: 'btn-secondary',
    success: 'btn-success',
    ghost: 'btn-ghost',
  }[variant];

  return (
    <motion.button
      whileTap={{ scale: 0.98 }}
      className={`btn ${variantClass} ${size === 'lg' ? 'btn-lg' : ''} ${className}`}
      disabled={disabled || loading}
      aria-busy={loading}
      {...props}
    >
      {loading ? 'Working...' : children}
    </motion.button>
  );
}
