import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { BotEngine } from '@/vendor/bloub/engine';
import { EXPRESSION_BY_ID } from '@/vendor/bloub/expressions';
import { RAYON, DEMI_VIEWBOX } from '@/vendor/bloub/repere';
import { SHAPE_BY_ID } from '@/vendor/bloub/skins';
import { cn } from '@/lib/utils';

import { agentAppearance } from './agent-appearance';

/** React renderer for the original jeremy-prt/bloub engine. */
export function AgentAvatar({ name, className }: { name: string; className?: string }) {
  const mask = useId();
  const appearance = useMemo(() => agentAppearance(name), [name]);
  const engine = useMemo(
    () =>
      new BotEngine(
        RAYON,
        'idle',
        SHAPE_BY_ID.get(appearance.shape)?.radii ?? null,
        EXPRESSION_BY_ID.get(appearance.expression) ?? null,
      ),
    [appearance],
  );
  const stillFrame = useMemo(() => engine.sample(0), [engine]);
  const [animation, setAnimation] = useState({ engine, frame: stillFrame });
  const frame = animation.engine === engine ? animation.frame : stillFrame;
  const [hovered, setHovered] = useState(false);
  const time = useRef(0);
  useEffect(() => {
    if (!hovered || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    let raf = 0;
    let previous = performance.now();
    const tick = (now: number) => {
      if (now - previous >= 1000 / 30) {
        time.current += (now - previous) / 1000;
        previous = now;
        setAnimation({ engine, frame: engine.sample(time.current) });
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [engine, hovered]);
  return (
    <span
      aria-hidden="true"
      data-avatar="bloub"
      data-agent={name}
      data-shape={appearance.shape}
      className={cn('inline-block size-10 shrink-0', className)}
      onPointerEnter={() => setHovered(true)}
      onPointerLeave={() => setHovered(false)}
    >
      <svg
        className="size-full"
        viewBox={`${-DEMI_VIEWBOX} ${-DEMI_VIEWBOX} ${DEMI_VIEWBOX * 2} ${DEMI_VIEWBOX * 2}`}
      >
        <defs>
          <mask
            id={mask}
            maskUnits="userSpaceOnUse"
            x={-DEMI_VIEWBOX}
            y={-DEMI_VIEWBOX}
            width={DEMI_VIEWBOX * 2}
            height={DEMI_VIEWBOX * 2}
          >
            <path d={frame.bodyPath} fill="white" />
            {frame.eyes.map((eye, index) => (
              <path key={index} d={eye.d} transform={eye.matrix} opacity={eye.alpha} fill="black" />
            ))}
          </mask>
        </defs>
        <g transform="scale(1.25)">
          <path d={frame.bodyPath} fill="var(--background)" />
          <path
            d={frame.bodyPath}
            opacity={frame.bodyAlpha}
            fill={appearance.background}
            mask={`url(#${mask})`}
          />
        </g>
      </svg>
    </span>
  );
}
