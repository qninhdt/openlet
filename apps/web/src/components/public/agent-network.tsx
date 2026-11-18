import { useEffect, useRef } from 'react';
import { ProviderLogo } from '@/components/agents/provider-logo';
import { RAYON, DEMI_VIEWBOX } from '@/vendor/bloub/repere';
import { BotEngine } from '@/vendor/bloub/engine';
import { SHAPE_BY_ID, COLOR_BY_ID } from '@/vendor/bloub/skins';
import { EXPRESSION_BY_ID } from '@/vendor/bloub/expressions';
import { sectionTitle } from './public-layout';
import {
  buildAgentNetwork,
  drawAgentNetwork,
  regrowAgentNetwork,
  agentNetworkNodeAt,
  agentNetworkHubAt,
  startHubSignal,
  type NetworkAssets,
  type NetworkView,
  type HubSignal,
} from './agent-network-scene';

const colors = ['bleu', 'vert', 'ambre', 'violet', 'turquoise', 'rose', 'rouge'];
const shapes = ['squircle', 'galet', 'cercle', 'hexagone', 'nuage', 'triangle', 'goutte'];

async function svgImage(svg: string, size = 128) {
  const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }));
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    const bitmap = document.createElement('canvas');
    bitmap.width = size;
    bitmap.height = size;
    bitmap.getContext('2d')?.drawImage(image, 0, 0, size, size);
    return bitmap;
  } finally {
    URL.revokeObjectURL(url);
  }
}

function avatarImage(index: number) {
  const color = (COLOR_BY_ID.get(colors[index % colors.length]) ?? COLOR_BY_ID.get('bleu')!).hex;
  const engine = new BotEngine(
    RAYON,
    'idle',
    SHAPE_BY_ID.get(shapes[index % shapes.length])?.radii ?? null,
    EXPRESSION_BY_ID.get('curieux') ?? null,
  );
  const frame = engine.sample(index * 0.37);
  const eyes = frame.eyes
    .map(
      (eye) => `<path d="${eye.d}" transform="${eye.matrix}" opacity="${eye.alpha}" fill="black"/>`,
    )
    .join('');
  return {
    color,
    image: svgImage(
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${-DEMI_VIEWBOX} ${-DEMI_VIEWBOX} ${DEMI_VIEWBOX * 2} ${DEMI_VIEWBOX * 2}"><defs><mask id="m" maskUnits="userSpaceOnUse" x="${-DEMI_VIEWBOX}" y="${-DEMI_VIEWBOX}" width="${DEMI_VIEWBOX * 2}" height="${DEMI_VIEWBOX * 2}"><path d="${frame.bodyPath}" fill="white"/>${eyes}</mask></defs><path d="${frame.bodyPath}" fill="white"/><path d="${frame.bodyPath}" fill="${color}" mask="url(#m)"/></svg>`,
    ),
  };
}

export default function AgentNetwork() {
  const stage = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const heading = useRef<HTMLElement>(null);
  const marks = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = stage.current,
      surface = canvas.current;
    const context = surface?.getContext('2d');
    if (!element || !surface || !context?.roundRect) return;
    let network = buildAgentNetwork({
      seed: 8173,
      avatarCount: 24,
      markCount: 3,
      hubLabel: 'Openlet',
      agents: [
        { label: 'Atlas', avatar: 24, mark: 0 },
        { label: 'Scout', avatar: 25, mark: 1 },
        { label: 'Forge', avatar: 26, mark: 2 },
      ],
      messages: [
        'Scout, research the launch.',
        'The findings are in Team storage.',
        'I’ll turn them into a launch brief.',
      ],
    });
    const style = getComputedStyle(element);
    const token = (key: string) => style.getPropertyValue(key).trim();
    const assets: NetworkAssets = {
      avatars: [],
      avatarColors: [],
      marks: [],
      font: style.fontFamily,
      colors: {
        hub: token('--brand'),
        hubEye: token('--brand-foreground'),
        dot: token('--border'),
        badge: token('--muted'),
        canvas: token('--background'),
        bubble: token('--card'),
        bubbleBorder: token('--border'),
        bubbleText: token('--foreground'),
        label: token('--muted-foreground'),
        hubPulse: token('--foreground'),
      },
    };
    const view: NetworkView = { width: 0, height: 0, top: 0, narrow: false };
    const media = matchMedia('(prefers-reduced-motion: reduce)');
    let time = 0,
      last = 0,
      frame = 0,
      ratio = 1,
      visible = false,
      disposed = false;
    let signals: HubSignal[] = [];
    const now = () => (media.matches ? network.end : time);
    const draw = () => {
      context.setTransform(1, 0, 0, 1, 0, 0);
      context.clearRect(0, 0, surface.width, surface.height);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      signals = signals.filter((s) => s.end > now());
      drawAgentNetwork(context, network, assets, view, now(), !media.matches, signals);
    };
    const tick = (stamp: number) => {
      frame = 0;
      if (!visible || document.hidden || disposed) return;
      if (!last || stamp - last >= 1000 / 30) {
        time += last ? Math.min(0.05, (stamp - last) / 1000) : 0;
        last = stamp;
        draw();
      }
      if (!media.matches) frame = requestAnimationFrame(tick);
    };
    const play = () => {
      cancelAnimationFrame(frame);
      last = 0;
      frame = requestAnimationFrame(tick);
    };
    const resize = () => {
      ratio = Math.min(2, devicePixelRatio || 1);
      view.width = element.clientWidth;
      view.height = element.clientHeight;
      view.narrow = view.width < 640;
      view.top =
        (heading.current?.getBoundingClientRect().bottom ?? 0) -
        element.getBoundingClientRect().top;
      element.style.setProperty('--network-top', `${view.top}px`);
      surface.width = Math.round(view.width * ratio);
      surface.height = Math.round(view.height * ratio);
      draw();
    };
    const click = (event: MouseEvent) => {
      if (media.matches) return;
      const rect = surface.getBoundingClientRect(),
        x = event.clientX - rect.left,
        y = event.clientY - rect.top;
      if (agentNetworkHubAt(network, view, now(), x, y)) {
        const signal = startHubSignal(network, 'ripple', now());
        if (signal) signals.push(signal);
      } else {
        const root = agentNetworkNodeAt(network, view, now(), x, y);
        if (root >= 0 && time >= network.end) {
          network = regrowAgentNetwork(network, root, now(), {
            seed: Date.now(),
            avatarCount: 24,
            markCount: 3,
          });
          signals = [];
          time = 0;
        }
      }
    };
    const observer = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      play();
    });
    observer.observe(element);
    const resizer = new ResizeObserver(resize);
    resizer.observe(element);
    surface.addEventListener('click', click);
    document.addEventListener('visibilitychange', play);
    media.addEventListener('change', play);
    const avatars = Array.from({ length: 27 }, (_, i) => avatarImage(i));
    assets.avatarColors = avatars.map((a) => a.color);
    void Promise.all(avatars.map((a) => a.image))
      .then((images) => {
        if (!disposed) {
          assets.avatars = images;
          draw();
        }
      })
      .catch(() => {});
    void Promise.all(
      Array.from(marks.current?.querySelectorAll('svg') ?? []).map((mark) =>
        svgImage(
          new XMLSerializer()
            .serializeToString(mark)
            .replaceAll('currentColor', token('--foreground')),
        ),
      ),
    )
      .then((images) => {
        if (!disposed) {
          assets.marks = images;
          draw();
        }
      })
      .catch(() => {});
    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      observer.disconnect();
      resizer.disconnect();
      surface.removeEventListener('click', click);
      document.removeEventListener('visibilitychange', play);
      media.removeEventListener('change', play);
    };
  }, []);
  return (
    <section id="agents" aria-labelledby="network-title" className="relative py-16 sm:py-24">
      <div ref={stage} className="relative h-[720px] w-full sm:h-[900px]">
        <canvas
          ref={canvas}
          aria-hidden="true"
          className="public-network-canvas absolute inset-0 size-full"
        />
        <header
          ref={heading}
          className="pointer-events-none relative z-10 mx-auto max-w-[760px] px-5 text-center"
        >
          <h2 id="network-title" className={sectionTitle}>
            Your agents work
            <br />
            together.
          </h2>
          <p className="mt-7 text-lg leading-relaxed text-muted-foreground">
            Each agent has a role, instructions and storage. They hand off tasks, share files and
            keep the work moving.
          </p>
        </header>
        <div ref={marks} className="hidden" aria-hidden="true">
          <ProviderLogo provider="OpenAI" />
          <ProviderLogo provider="Anthropic" />
          <ProviderLogo provider="Google" />
        </div>
      </div>
    </section>
  );
}
