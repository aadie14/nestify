import React from 'react';

type Props = {
  width?: number | string;
  height?: number;
};

export default function SkeletonValue({ width = 72, height = 12 }: Props) {
  return <span className="skeleton" style={{ display: 'inline-block', width, height, verticalAlign: 'middle' }} />;
}
