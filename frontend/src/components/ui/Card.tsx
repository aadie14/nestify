import React from 'react';

type Props = {
  children: React.ReactNode;
  className?: string;
  hover?: boolean;
  as?: keyof JSX.IntrinsicElements;
};

export default function Card({ children, className = '', hover = true, as = 'section' }: Props) {
  const Tag = as;
  return (
    <Tag className={`card ${className}`} data-hover={hover ? 'true' : 'false'}>
      {children}
    </Tag>
  );
}
