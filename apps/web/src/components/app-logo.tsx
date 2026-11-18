import type { ComponentProps } from 'react';
import { cn } from '@/lib/utils';
import { APP_LOGO_EYE_POINTS } from '@/lib/app-logo-shape';

// Shape adapted from Nightly Labs OpenBot's app-logo-shape.ts; see public/third-party/openbot.
export function AppLogo({
  className,
  animated = false,
  ...props
}: ComponentProps<'svg'> & { animated?: boolean }) {
  return (
    <svg
      viewBox="0 0 240 240"
      aria-hidden="true"
      className={cn('size-5 shrink-0', className)}
      {...props}
    >
      <rect width="240" height="240" rx="50" fill="var(--brand)" />
      <g
        className={animated ? 'openlet-logo-eyes' : undefined}
        fill="none"
        stroke="var(--brand-foreground)"
        strokeWidth="9.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <polyline points={APP_LOGO_EYE_POINTS.left} />
        <polyline points={APP_LOGO_EYE_POINTS.right} />
      </g>
    </svg>
  );
}
