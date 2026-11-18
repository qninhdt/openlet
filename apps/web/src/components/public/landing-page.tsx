import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from 'react';
import { Link } from '@tanstack/react-router';
import {
  ArrowRight,
  Check,
  CalendarClock,
  FileText,
  Folder,
  LockKeyhole,
  MessageCircle,
  Network,
  Play,
  ShieldCheck,
  Users,
} from 'lucide-react';
import { AgentAvatar } from '@/components/agent-avatar';
import { AppLogo } from '@/components/app-logo';
import { ProviderLogo } from '@/components/agents/provider-logo';
import { Button } from '@/components/ui/button';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion';
import { cn } from '@/lib/utils';
import { PublicLayout, sectionTitle, siteAction, siteWidth, usePageTitle } from './public-layout';

const AgentNetwork = lazy(() => import('./agent-network'));
const providers = [
  { name: 'OpenAI', label: 'OpenAI' },
  { name: 'Anthropic', label: 'Claude' },
  { name: 'Google', label: 'Gemini' },
] as const;
const facts = [
  [
    'Do I need a dedicated computer?',
    'You can chat with agents and work with cloud storage from your browser. A dedicated computer is not required for these features.',
  ],
  [
    'Can several people work with the same agent?',
    'Yes. Each person has a private conversation with the agent. Workspace owners with permission can follow its work in Activity.',
  ],
  [
    'What is the difference between Leta and Leti?',
    'Leta is the persistent agent you work with. It can delegate a task to a Leti, with its own name, role and activity, inside a Box.',
  ],
  [
    'Where do files live?',
    'Files belong to workspace storage: personal, team, agent or conversation storage. Access is checked against the permissions for that storage.',
  ],
  [
    'Can I send files in a conversation?',
    'Upload a file, choose one from storage, or drag it into the message box. File mentions open the same viewer and editor used in Storage.',
  ],
  [
    'Can agents run scheduled work?',
    'Schedulers can deliver work to an agent’s inbox. You can follow the resulting activity and respond when the agent asks a question or requests a decision.',
  ],
];

function Agent({ name, size = 'size-10' }: { name: string; size?: string }) {
  return <AgentAvatar name={name} className={size} />;
}

function Feature({
  title,
  description,
  children,
  className,
}: {
  title: string;
  description: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <article
      data-avatar-hover
      className={cn(
        'group flex min-w-0 flex-col overflow-hidden rounded-[28px] border border-foreground/10 bg-card transition-colors hover:border-foreground/20',
        className,
      )}
    >
      {children}
      <div className="mt-auto p-7 sm:p-8">
        <h3 className="text-2xl leading-tight font-semibold tracking-[-0.035em]">{title}</h3>
        <p className="mt-3 text-[15px] leading-6 text-muted-foreground">{description}</p>
      </div>
    </article>
  );
}

function DemoMessage({
  name,
  time,
  children,
}: {
  name: string;
  time: string;
  children: ReactNode;
}) {
  return (
    <div className="flex items-start gap-3">
      <Agent name={name} />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-semibold">{name}</span>
          <span className="text-[11px] text-muted-foreground">{time}</span>
        </div>
        <div className="mt-1 text-sm leading-6 text-foreground/85">{children}</div>
      </div>
    </div>
  );
}

function TeamDemo() {
  return (
    <div className="relative mt-8 ml-8 flex min-h-[430px] flex-col overflow-hidden rounded-tl-3xl border-t border-l border-foreground/10 bg-background md:min-h-[440px]">
      <div className="flex h-14 items-center justify-between border-b border-foreground/8 px-5 text-sm font-medium">
        <span>
          <span className="mr-2 text-muted-foreground">#</span>launch
        </span>
        <div className="flex -space-x-2">
          {['Atlas', 'Scout', 'Forge'].map((n) => (
            <Agent key={n} name={n} size="size-8" />
          ))}
        </div>
      </div>
      <div className="space-y-7 p-5 sm:p-6">
        <DemoMessage name="Atlas" time="9:12">
          Scout, can you research the launch?
          <br />
          Forge, turn the findings into a brief.
        </DemoMessage>
        <p className="pl-13 text-xs text-muted-foreground">Atlas handed the research to Scout</p>
        <DemoMessage name="Scout" time="9:26">
          The findings are ready. I added the sources to Team storage.
        </DemoMessage>
        <DemoMessage name="Forge" time="9:31">
          The brief is ready for your review.
          <div className="mt-3 flex w-fit items-center gap-2 rounded-xl border border-foreground/10 bg-card px-3 py-2">
            <FileText className="size-4 text-[var(--brand)]" />
            <span className="text-xs">Launch brief.md</span>
            <Check className="ml-3 size-3 text-muted-foreground" />
          </div>
        </DemoMessage>
        <div
          className="public-message ml-13 inline-flex gap-1 rounded-full bg-muted px-3 py-2"
          aria-hidden="true"
        >
          {[0, 1, 2].map((i) => (
            <span key={i} className="size-1 rounded-full bg-muted-foreground" />
          ))}
        </div>
      </div>
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-linear-to-t from-card to-transparent"
      />
    </div>
  );
}

function ProviderDemo() {
  return (
    <div
      className="overflow-hidden pt-10 pb-1 [mask-image:linear-gradient(90deg,transparent,black_12%,black_88%,transparent)]"
      aria-label="OpenAI, Claude and Gemini"
    >
      {[false, true].map((reverse) => (
        <div
          key={String(reverse)}
          aria-hidden="true"
          className={cn(
            'public-marquee mb-3 flex w-max gap-2',
            reverse && 'public-marquee-reverse',
          )}
        >
          {[...providers, ...providers, ...providers, ...providers].map((p, i) => (
            <span
              key={i}
              className="inline-flex h-11 items-center gap-2 rounded-full border border-foreground/10 bg-muted px-4 text-sm"
            >
              <ProviderLogo provider={p.name} />
              {p.label}
            </span>
          ))}
        </div>
      ))}
    </div>
  );
}

function StorageDemo() {
  return (
    <article className="relative flex min-h-[300px] overflow-hidden rounded-[28px] bg-[var(--brand)] text-[var(--brand-foreground)] md:items-center">
      <div className="relative z-10 w-[57%] self-center py-8 pr-4 pl-7 sm:pl-8">
        <h3 className="text-2xl leading-tight font-semibold tracking-[-0.035em]">
          A home for
          <br />
          your work
        </h3>
        <p className="mt-3 text-[15px] leading-6 opacity-80">
          Files, conversations and shared knowledge, organized in your workspace.
        </p>
      </div>
      <div className="absolute top-17 -right-8 w-[49%] rounded-tl-2xl border border-current/15 bg-background/20 text-sm shadow-lg">
        <div className="flex items-center justify-between border-b border-current/15 px-4 py-4 text-xs font-medium">
          Workspace
          <LockKeyhole className="size-3.5" />
        </div>
        <div className="space-y-5 p-4">
          {['Personal', 'Team', 'Agent files', 'Conversations'].map((label) => (
            <div key={label} className="flex items-center gap-3">
              <Folder className="size-4" />
              {label}
            </div>
          ))}
        </div>
      </div>
    </article>
  );
}

function WorkflowDemo() {
  const steps = [
    { name: 'Atlas', task: 'Review the weekly plan' },
    { name: 'Scout', task: 'Collect the source material' },
    { name: 'Forge', task: 'Write the report' },
  ];
  return (
    <div className="px-6 pt-8 sm:px-8">
      <div className="flex items-center gap-2 rounded-xl border border-foreground/10 bg-background px-4 py-3 text-xs">
        <CalendarClock className="size-4 text-[var(--brand)]" />
        <div>
          <p className="text-muted-foreground">Every Monday</p>
          <p className="mt-1 font-medium">Weekly report · 9:00</p>
        </div>
      </div>
      {steps.map((step) => (
        <div key={step.name}>
          <div className="mx-auto h-7 w-px bg-foreground/15" />
          <div className="flex items-center gap-3 rounded-xl border border-foreground/10 bg-background px-3 py-3">
            <Agent name={step.name} size="size-8" />
            <div className="min-w-0">
              <p className="text-xs font-semibold">{step.name}</p>
              <p className="mt-1 text-[11px] text-muted-foreground">{step.task}</p>
            </div>
            <Check className="ml-auto size-3 text-[var(--brand)]" />
          </div>
        </div>
      ))}
      <div className="mx-auto h-7 w-px bg-foreground/15" />
      <div className="rounded-xl border border-foreground/10 bg-background p-4 text-xs">
        <p className="text-muted-foreground">Question</p>
        <p className="mt-2">Ready to share the report?</p>
        <div className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-muted px-3 py-1.5">
          <Check className="size-3" />
          Review together
        </div>
      </div>
    </div>
  );
}

function PeopleDemo() {
  return (
    <div className="relative mx-8 mt-8 overflow-hidden rounded-2xl border border-foreground/10 bg-background">
      <div className="flex items-center justify-between border-b border-foreground/10 px-5 py-4 text-sm">
        <span>Launch workspace</span>
        <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
          <Users className="size-3.5" />3 members
        </span>
      </div>
      <div className="space-y-5 p-5">
        <div className="flex gap-3">
          <span className="grid size-8 shrink-0 place-items-center rounded-full bg-muted text-xs">
            M
          </span>
          <p className="text-sm leading-6">
            <strong className="mr-2 font-medium">Maya</strong>
            <span className="text-foreground/75">Atlas, can you prepare the launch brief?</span>
          </p>
        </div>
        <DemoMessage name="Atlas" time="11:05">
          I’ll use the files in Team storage and ask Sam to review it.
        </DemoMessage>
      </div>
    </div>
  );
}

function PersistDemo() {
  return (
    <div className="mx-8 mt-8 rounded-2xl border border-foreground/10 bg-background p-5">
      <div className="flex items-center gap-3">
        <Agent name="Atlas" />
        <div>
          <p className="text-sm font-medium">Atlas</p>
          <p className="mt-1 text-xs text-muted-foreground">Assistant</p>
        </div>
        <div className="ml-auto flex items-center gap-2 rounded-full bg-muted px-3 py-1.5 text-xs">
          <ProviderLogo provider="OpenAI" />
          <ArrowRight className="size-3 text-muted-foreground" />
          <ProviderLogo provider="Anthropic" />
        </div>
      </div>
      <p className="mt-5 text-sm leading-6 text-foreground/80">
        The launch brief, sources and work in progress stay with the agent.
      </p>
      <div className="mt-4 flex flex-wrap gap-2 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5 rounded-full border border-foreground/10 px-3 py-1.5">
          <Folder className="size-3" />
          Files
        </span>
        <span className="flex items-center gap-1.5 rounded-full border border-foreground/10 px-3 py-1.5">
          <MessageCircle className="size-3" />
          Conversations
        </span>
      </div>
    </div>
  );
}

function Features() {
  return (
    <section
      id="features"
      aria-labelledby="features-title"
      className={cn(siteWidth, 'scroll-mt-10 py-16 sm:py-24')}
    >
      <header>
        <h2 id="features-title" className={sectionTitle}>
          What Openlet does
        </h2>
        <p className="mt-7 max-w-[620px] text-lg leading-relaxed text-muted-foreground">
          One workspace for your agents, your team and your files. Keep conversations simple and
          follow the work when you need to.
        </p>
      </header>
      <div className="mt-14 grid gap-4 lg:mt-18 lg:grid-cols-12">
        <Feature
          title="Agents work as a team"
          description="Give each agent a name, a role and instructions. Leta can delegate tasks to Leti agents, share files and bring the results back."
          className="lg:col-span-7 lg:row-span-2"
        >
          <TeamDemo />
        </Feature>
        <Feature
          title="Work with different models"
          description="Choose a model for the work at hand. Your workspace gives agents a common place to work with files and tools."
          className="lg:col-span-5"
        >
          <ProviderDemo />
        </Feature>
        <div className="lg:col-span-5">
          <StorageDemo />
        </div>
        <Feature
          title="People and agents, together"
          description="Invite your team into a workspace. Each person has their own conversation with an agent, with shared files when the work calls for it."
          className="lg:col-span-8"
        >
          <PeopleDemo />
        </Feature>
        <Feature
          title="Keep work moving"
          description="Schedule recurring work, follow the steps in Activity and answer questions when a decision is needed."
          className="lg:col-span-4 lg:row-span-2"
        >
          <WorkflowDemo />
        </Feature>
        <Feature
          title="Your agent keeps its workspace"
          description="Files and conversations belong to the workspace. Return to the same agent and pick up the work where you left it."
          className="lg:col-span-8"
        >
          <PersistDemo />
        </Feature>
      </div>
      <p className="mt-4 text-xs text-muted-foreground">
        Illustrative workspace and conversations.
      </p>
    </section>
  );
}

const teamCards = [
  {
    title: 'A shared place to work',
    label: 'Workspace',
    copy: 'Bring people and agents together around the same projects.',
    color: 'bg-[var(--brand)]',
    Icon: Users,
  },
  {
    title: 'The right files, together',
    label: 'Storage',
    copy: 'Keep personal work separate and share the files your team needs.',
    color: 'bg-[#67bd91]',
    Icon: Folder,
  },
  {
    title: 'Follow the work',
    label: 'Activity',
    copy: 'See what agents are doing, the tools they use and the decisions waiting for you.',
    color: 'bg-[#dbb665]',
    Icon: Network,
  },
  {
    title: 'Make room for your team',
    label: 'Members',
    copy: 'Invite teammates and manage who can access your workspace.',
    color: 'bg-[var(--brand)]',
    Icon: ShieldCheck,
  },
];

function Teams() {
  const [active, setActive] = useState(0);
  const stack = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = stack.current;
    if (!element) return;
    let frame = 0;
    const measure = () => {
      frame = 0;
      const cards = Array.from(element.children) as HTMLElement[];
      const style = getComputedStyle(element);
      const step = parseFloat(style.getPropertyValue('--stack-step'));
      const gap = parseFloat(style.rowGap);
      let next = 0;
      cards.forEach((card, i) => {
        const box = card.getBoundingClientRect();
        const distance = cards[i + 1] ? cards[i + 1].getBoundingClientRect().top - box.top : 0;
        const covered = cards[i + 1]
          ? Math.min(1, Math.max(0, 1 - (distance - step) / (box.height + gap - step)))
          : 0;
        card.style.setProperty('--covered', covered.toFixed(3));
        if (covered > 0.5) next = i + 1;
      });
      setActive(next);
    };
    const scroll = () => {
      if (!frame) frame = requestAnimationFrame(measure);
    };
    window.addEventListener('scroll', scroll, { passive: true });
    window.addEventListener('resize', scroll);
    measure();
    return () => {
      window.removeEventListener('scroll', scroll);
      window.removeEventListener('resize', scroll);
      cancelAnimationFrame(frame);
    };
  }, []);
  return (
    <section
      id="teams"
      className={cn(siteWidth, 'scroll-mt-12 py-20 sm:py-32')}
      aria-labelledby="teams-title"
    >
      <div className="grid items-start gap-14 lg:grid-cols-[.9fr_1.1fr] lg:gap-20">
        <div className="lg:sticky lg:top-25">
          <h2 id="teams-title" className={sectionTitle}>
            Openlet
            <br />
            for Teams
          </h2>
          <p className="mt-7 text-2xl tracking-[-0.025em]">AI teammates for your team.</p>
          <p className="mt-4 max-w-sm text-lg leading-relaxed text-muted-foreground">
            A workspace for the people you work with, the agents you rely on and the files you
            share.
          </p>
          <Button asChild className={cn(siteAction, 'mt-7')}>
            <Link to="/login">
              Start a workspace
              <ArrowRight className="size-4" />
            </Link>
          </Button>
          <ol className="mt-12 hidden border-l border-foreground/10 lg:block">
            {teamCards.map((card, i) => (
              <li
                key={card.label}
                className={cn(
                  '-ml-px flex items-center gap-3 border-l py-3 pl-5 text-sm',
                  active === i
                    ? 'border-[var(--brand)] text-foreground'
                    : 'border-transparent text-muted-foreground',
                )}
              >
                <span className="font-mono text-[10px]">{String(i + 1).padStart(2, '0')}</span>
                {card.label}
              </li>
            ))}
          </ol>
        </div>
        <div
          ref={stack}
          className="relative grid gap-4 pb-12 [--stack-top:16px] [--stack-step:52px] lg:gap-6 lg:[--stack-top:100px] lg:[--stack-step:56px]"
        >
          {teamCards.map(({ title, label, copy, color, Icon }, i) => (
            <article
              key={label}
              className={cn(
                'sticky flex min-h-[360px] origin-top flex-col overflow-hidden rounded-[28px] px-7 pb-7 text-[var(--brand-foreground)] [scale:calc(1-var(--covered,0)*.05)] [filter:brightness(calc(1-var(--covered,0)*.22))] motion-reduce:scale-100 sm:min-h-[390px] sm:px-9 sm:pb-9',
                color,
              )}
              style={{ top: `calc(var(--stack-top) + ${i} * var(--stack-step))` }}
            >
              <div className="relative flex h-(--stack-step) shrink-0 items-center justify-between text-[10px] font-medium">
                <span className="rounded-full border border-current/20 px-3 py-1.5">{label}</span>
                <span className="font-mono">0{i + 1} / 04</span>
              </div>
              <Icon
                aria-hidden="true"
                strokeWidth={1.25}
                className="absolute top-24 right-8 size-24 opacity-75 sm:size-36"
              />
              <div className="relative mt-auto pt-30">
                <h3 className="max-w-[320px] text-4xl leading-[1.05] font-medium tracking-[-0.04em] sm:text-5xl">
                  {title}
                </h3>
                <p className="mt-5 max-w-[330px] text-base leading-6 opacity-80">{copy}</p>
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function Closing() {
  const ref = useRef<HTMLElement>(null);
  const [near, setNear] = useState(false);
  useEffect(() => {
    if (!ref.current) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setNear(true);
          observer.disconnect();
        }
      },
      { rootMargin: '300px' },
    );
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  const colors = ['bleu', 'vert', 'ambre', 'violet', 'turquoise', 'rose', 'rouge'];
  return (
    <section
      ref={ref}
      aria-labelledby="closing-title"
      className="relative isolate flex min-h-[610px] items-center justify-center overflow-hidden px-5 py-28 text-center"
    >
      <div
        aria-hidden="true"
        className="pointer-events-auto absolute top-1/2 left-1/2 -z-20 w-[2150px] -translate-1/2 [mask-image:linear-gradient(transparent,black_15%,black_85%,transparent)]"
      >
        {near &&
          Array.from({ length: 8 }, (_, row) => (
            <div key={row} className="public-comb-row">
              {Array.from({ length: 23 }, (_, col) => {
                const color = colors[(row * 5 + col * 3) % colors.length];
                return (
                  <span key={col} className="public-comb-cell">
                    <AgentAvatar
                      name={`Teammate ${row}-${col}`}
                      appearance={{ shape: 'squircle', color }}
                      className="size-full scale-125"
                    />
                  </span>
                );
              })}
            </div>
          ))}
      </div>
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(ellipse_at_center,var(--background)_15%,transparent_80%)] backdrop-blur-[1px]"
      />
      <div className="max-w-[760px]">
        <h2 id="closing-title" className={sectionTitle}>
          Meet your first teammate
        </h2>
        <p className="mx-auto mt-6 max-w-[620px] text-lg leading-relaxed text-foreground/85">
          Give an agent a role, bring your files and start a conversation. Keep your team and your
          work in one workspace.
        </p>
        <div className="mt-9 flex flex-wrap justify-center gap-3">
          <Button className={siteAction} asChild>
            <Link to="/login">
              Get started
              <ArrowRight />
            </Link>
          </Button>
          <Button
            variant="outline"
            className={cn(siteAction, 'border-foreground/25 bg-background/20')}
            asChild
          >
            <Link to="/app">Explore the app</Link>
          </Button>
        </div>
      </div>
    </section>
  );
}

function LandingPreview() {
  const frame = useRef<HTMLIFrameElement>(null);
  const preview = useRef<HTMLElement>(null);
  const [loaded, setLoaded] = useState(false);
  const [start, setStart] = useState(false);
  useEffect(() => {
    const id = window.setTimeout(() => setStart(true), 300);
    return () => clearTimeout(id);
  }, []);
  useEffect(() => {
    if (!start || !preview.current) return;
    let visible = false,
      ready = false;
    const sync = () => {
      if (ready)
        frame.current?.contentWindow?.postMessage(
          { type: visible && !document.hidden ? 'openlet:preview:start' : 'openlet:preview:pause' },
          location.origin,
        );
    };
    const receive = (event: MessageEvent) => {
      if (
        event.origin !== location.origin ||
        event.source !== frame.current?.contentWindow ||
        event.data?.type !== 'openlet:preview:ready'
      )
        return;
      ready = true;
      setLoaded(true);
      sync();
    };
    const observer = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      sync();
    });
    observer.observe(preview.current);
    window.addEventListener('message', receive);
    document.addEventListener('visibilitychange', sync);
    return () => {
      observer.disconnect();
      window.removeEventListener('message', receive);
      document.removeEventListener('visibilitychange', sync);
    };
  }, [start]);
  return (
    <section
      ref={preview}
      data-landing-preview
      aria-label="Interactive Openlet app preview"
      className="relative z-10 mt-16 h-[590px] overflow-hidden rounded-xl border border-foreground/15 bg-sidebar sm:mt-24 sm:h-[620px] lg:aspect-[16/10] lg:h-auto lg:max-h-[760px]"
    >
      {!loaded && (
        <div role="status" className="absolute inset-0 grid place-items-center">
          <div className="flex flex-col items-center gap-4">
            <AppLogo animated className="size-12" />
            <span className="text-xs text-muted-foreground">Opening the preview…</span>
          </div>
        </div>
      )}
      {start && (
        <iframe
          ref={frame}
          title="Openlet app preview"
          src="/app-preview"
          sandbox="allow-forms allow-same-origin allow-scripts allow-downloads"
          className={cn(
            'relative size-full border-0 transition-opacity duration-300',
            loaded ? 'opacity-100' : 'opacity-0',
          )}
        />
      )}
    </section>
  );
}

export function LandingPage() {
  usePageTitle(
    'Your agents, working together',
    'A shared workspace for persistent AI agents, your team and your files.',
  );
  const [networkNear, setNetworkNear] = useState(false);
  const network = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!network.current) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setNetworkNear(true);
          observer.disconnect();
        }
      },
      { rootMargin: '350px' },
    );
    observer.observe(network.current);
    return () => observer.disconnect();
  }, []);
  return (
    <PublicLayout>
      <main id="main-content">
        <div className="relative isolate">
          <section
            className={cn(siteWidth, 'relative pt-15 pb-10 text-center sm:pt-24 lg:pt-28')}
            aria-labelledby="landing-title"
          >
            <div className="relative z-10 mx-auto flex max-w-[880px] flex-col items-center">
              <h1
                id="landing-title"
                className="mt-8 flex flex-wrap items-center justify-center gap-x-[.16em] text-[clamp(3.5rem,6.5vw,6.75rem)] leading-[.96] font-medium tracking-[-0.055em]"
              >
                <span>Meet</span>
                <AppLogo animated className="size-[.82em] translate-y-[.04em]" />
                <span>Openlet</span>
              </h1>
              <p className="mt-8 max-w-[730px] text-[clamp(1rem,1.5vw,1.25rem)] leading-[1.55] text-muted-foreground">
                A persistent workspace for your AI teammates. Agents hand off work, use tools and
                collaborate with your team. Your conversations and files, together in one place.
              </p>
              <div className="mt-8 flex w-full flex-col items-center justify-center gap-3 sm:flex-row">
                <Button asChild className={cn(siteAction, 'w-full max-w-80 sm:w-auto')}>
                  <Link to="/login">
                    Get started
                    <ArrowRight className="size-4" />
                  </Link>
                </Button>
                <Button
                  asChild
                  variant="outline"
                  className={cn(
                    siteAction,
                    'w-full max-w-80 border-foreground/20 bg-foreground/5 sm:w-auto',
                  )}
                >
                  <a href="#preview">
                    <Play className="size-3.5" />
                    Explore Openlet
                  </a>
                </Button>
              </div>
            </div>
            <div id="preview" className="scroll-mt-5">
              <LandingPreview />
            </div>
          </section>
        </div>
        <div ref={network} className="min-h-[850px]">
          {networkNear && (
            <Suspense fallback={<div className="h-[900px]" />}>
              <AgentNetwork />
            </Suspense>
          )}
        </div>
        <Features />
        <Teams />
        <section
          id="questions"
          aria-labelledby="questions-title"
          className={cn(siteWidth, 'scroll-mt-12 py-20 sm:py-30')}
        >
          <div className="grid gap-10 lg:grid-cols-[.8fr_1.2fr] lg:gap-20">
            <header>
              <h2 id="questions-title" className={sectionTitle}>
                Questions
              </h2>
              <p className="mt-6 max-w-xs text-lg leading-relaxed text-muted-foreground">
                Short answers about agents, workspaces and your files.
              </p>
            </header>
            <Accordion type="single" collapsible>
              {facts.map(([question, answer], i) => (
                <AccordionItem key={question} value={`faq-${i}`} className="border-foreground/10">
                  <AccordionTrigger className="items-center gap-5 rounded-none py-6 text-base font-medium hover:no-underline">
                    {question}
                  </AccordionTrigger>
                  <AccordionContent className="h-auto max-w-[60ch] pb-6 text-[15px] leading-7 text-muted-foreground">
                    {answer}
                  </AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          </div>
        </section>
        <Closing />
      </main>
    </PublicLayout>
  );
}
