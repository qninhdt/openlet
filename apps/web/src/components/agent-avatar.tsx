import { createContext, useContext, useEffect, useId, useMemo, useRef, useState } from 'react';
import { BotEngine } from '@/vendor/bloub/engine';
import { EXPRESSION_BY_ID, type ExpressionId } from '@/vendor/bloub/expressions';
import { RAYON, DEMI_VIEWBOX } from '@/vendor/bloub/repere';
import { SHAPE_BY_ID } from '@/vendor/bloub/skins';
import { cn } from '@/lib/utils';

import { agentAppearance, type AgentAppearance } from './agent-appearance';

export const AvatarAppearances = createContext<Record<string, AgentAppearance>>({});
export const AvatarWorking = createContext<Record<string, boolean>>({});
const hoverFaces: (ExpressionId | 'wink')[] = ['wink', 'surpris', 'excite', 'attentif', 'curieux'];
const workingFaces = [...EXPRESSION_BY_ID.values()];

/** React renderer for the original jeremy-prt/bloub engine. */
export function AgentAvatar({
  name,
  appearance: stored,
  agentId,
  working: requestedWorking,
  className,
}: {
  name: string;
  appearance?: AgentAppearance | null;
  agentId?: string;
  working?: boolean;
  className?: string;
}) {
  const mask = useId();
  const identities = useContext(AvatarAppearances);
  const activity = useContext(AvatarWorking);
  const working = requestedWorking ?? activity[agentId ?? ''] ?? activity[`name:${name}`] ?? false;
  const saved = stored ?? identities[agentId ?? ''] ?? identities[`name:${name}`];
  const appearance = useMemo(() => agentAppearance(name, saved), [name, saved]);
  const engine = useMemo(
    () =>
      new BotEngine(
        RAYON,
        'idle',
        SHAPE_BY_ID.get(appearance.shape)?.radii ?? null,
        EXPRESSION_BY_ID.get(appearance.expression) ?? null,
      ),
    [appearance.shape, appearance.expression],
  );
  const stillFrame = useMemo(() => engine.sample(0), [engine]);
  const [animation, setAnimation] = useState({ engine, frame: stillFrame });
  const frame = animation.engine === engine ? animation.frame : stillFrame;
  const [interaction, setInteraction] = useState<{ active: boolean; face: ExpressionId | 'wink' }>({
    active: false,
    face: 'curieux',
  });
  const element = useRef<HTMLSpanElement>(null);
  const [visible, setVisible] = useState(false);
  const [motionAllowed, setMotionAllowed] = useState(false);
  useEffect(() => {
    const avatar = element.current;
    if (!avatar) return;
    const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting));
    observer.observe(avatar);
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const syncMotion = () => setMotionAllowed(!document.hidden && !media.matches);
    syncMotion();
    document.addEventListener('visibilitychange', syncMotion);
    media.addEventListener('change', syncMotion);
    // Like OpenBot, the whole enclosing control owns hover and keyboard focus.
    const target =
      avatar.closest<HTMLElement>(
        '[data-avatar-hover], button, a, [role="button"], [role="link"], [role="menuitem"]',
      ) ?? avatar;
    const start = () => {
      const choices = hoverFaces.filter((face) => face !== appearance.expression);
      setInteraction({ active: true, face: choices[Math.floor(Math.random() * choices.length)] });
    };
    const stop = () => setInteraction((current) => ({ ...current, active: false }));
    const focus = (event: FocusEvent) => {
      if (event.target instanceof Element && event.target.matches(':focus-visible')) start();
    };
    const blur = (event: FocusEvent) => {
      if (!(event.relatedTarget instanceof Node) || !target.contains(event.relatedTarget)) stop();
    };
    target.addEventListener('pointerenter', start);
    target.addEventListener('pointerleave', stop);
    target.addEventListener('focusin', focus);
    target.addEventListener('focusout', blur);
    return () => {
      observer.disconnect();
      document.removeEventListener('visibilitychange', syncMotion);
      media.removeEventListener('change', syncMotion);
      target.removeEventListener('pointerenter', start);
      target.removeEventListener('pointerleave', stop);
      target.removeEventListener('focusin', focus);
      target.removeEventListener('focusout', blur);
    };
  }, [appearance.expression]);
  const time = useRef(0);
  useEffect(() => {
    if (!visible) return;
    const expression =
      EXPRESSION_BY_ID.get(
        working
          ? 'attentif'
          : interaction.active && motionAllowed && interaction.face !== 'wink'
            ? interaction.face
            : appearance.expression,
      ) ?? null;
    const changeAt = time.current - (motionAllowed ? 0 : BotEngine.SHAPE_MORPH);
    engine.setState(
      !working && interaction.active && motionAllowed && interaction.face === 'wink'
        ? 'wink'
        : 'idle',
      changeAt,
    );
    engine.setExpression(expression, changeAt);
    if (!motionAllowed) {
      setAnimation({ engine, frame: engine.sample(time.current) });
      return;
    }
    let raf = 0;
    let previous = performance.now();
    const settleAt = time.current + BotEngine.SHAPE_MORPH;
    let face = expression;
    let nextFace = time.current + 0.7 + Math.random() * 2.5;
    const tick = (now: number) => {
      if (document.hidden) return;
      if (now - previous >= 1000 / 30) {
        time.current += Math.min((now - previous) / 1000, 0.1);
        previous = now;
        if (working && time.current >= nextFace) {
          const choices = workingFaces.filter((candidate) => candidate !== face);
          face = choices[Math.floor(Math.random() * choices.length)];
          engine.setExpression(face, time.current);
          nextFace = time.current + 0.7 + Math.random() * 2.5;
        }
        setAnimation({ engine, frame: engine.sample(time.current) });
      }
      if (working || interaction.active || time.current < settleAt)
        raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [engine, working, interaction, visible, motionAllowed, appearance.expression]);
  return (
    <span
      ref={element}
      aria-hidden="true"
      data-avatar="bloub"
      data-agent={name}
      data-shape={appearance.shape}
      className={cn('inline-block size-10 shrink-0', className)}
      data-working={working || undefined}
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
