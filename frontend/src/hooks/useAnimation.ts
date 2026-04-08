import { useMemo } from 'react';

export function useAnimation() {
  const reducedMotion = useMemo(() => {
    if (typeof window === 'undefined') return false;
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }, []);

  const fadeInUp = reducedMotion
    ? { initial: {}, animate: {}, transition: { duration: 0 } }
    : {
        initial: { opacity: 0, y: 10 },
        animate: { opacity: 1, y: 0 },
        transition: { duration: 0.25, ease: 'easeOut' },
      };

  const staggerContainer = reducedMotion
    ? { animate: { transition: { staggerChildren: 0 } } }
    : { animate: { transition: { staggerChildren: 0.05 } } };

  return { reducedMotion, fadeInUp, staggerContainer };
}
