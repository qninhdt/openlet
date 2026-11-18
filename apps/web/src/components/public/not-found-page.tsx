import { useRef } from 'react';
import { Link, useLocation } from '@tanstack/react-router';
import { ArrowRight, Home } from 'lucide-react';
import { AppLogo } from '@/components/app-logo';
import { Button } from '@/components/ui/button';
import { PublicLayout, siteAction, usePageTitle } from './public-layout';

export function NotFoundPage() {
  usePageTitle('Page not found');
  const path = useLocation({ select: (location) => location.pathname });
  const stage = useRef<HTMLDivElement>(null);
  return (
    <PublicLayout>
      <main
        id="main-content"
        className="relative flex min-h-[720px] flex-col items-center justify-center overflow-hidden px-5 py-14 text-center"
        onPointerMove={(event) => {
          if (
            !stage.current ||
            matchMedia('(prefers-reduced-motion: reduce)').matches ||
            event.pointerType !== 'mouse'
          )
            return;
          stage.current.style.setProperty(
            '--eye-x',
            `${Math.max(-5, Math.min(5, (event.clientX / innerWidth - 0.5) * 10))}px`,
          );
          stage.current.style.setProperty(
            '--eye-y',
            `${Math.max(-4, Math.min(4, (event.clientY / innerHeight - 0.5) * 8))}px`,
          );
        }}
        onPointerLeave={() => {
          stage.current?.style.setProperty('--eye-x', '0px');
          stage.current?.style.setProperty('--eye-y', '0px');
        }}
      >
        <div
          ref={stage}
          aria-hidden="true"
          className="flex items-center justify-center gap-3 text-[clamp(7rem,17vw,13rem)] leading-none font-medium tracking-[-0.06em] sm:gap-6"
        >
          <span>4</span>
          <AppLogo
            animated
            className="size-[.75em] -rotate-8 [&_g]:translate-x-(--eye-x) [&_g]:translate-y-(--eye-y)"
          />
          <span>4</span>
        </div>
        <h1 className="mt-9 text-balance text-4xl font-medium tracking-[-0.04em] sm:text-5xl">
          This page wandered off
        </h1>
        <p className="mt-5 max-w-md text-base leading-7 text-muted-foreground">
          The link may be out of date, or the page moved. Check the address, or try one of these
          pages.
        </p>
        <div className="mt-7 flex flex-wrap justify-center gap-3">
          <Button asChild className={siteAction}>
            <Link to="/">
              <Home className="size-4" />
              Back to home
            </Link>
          </Button>
          <Button asChild variant="outline" className={siteAction}>
            <Link to="/app">
              Open workspace
              <ArrowRight className="size-4" />
            </Link>
          </Button>
        </div>
        <div className="mt-10 w-full max-w-[520px] overflow-hidden rounded-xl border border-foreground/10 bg-sidebar text-left text-xs sm:text-sm">
          <div aria-hidden="true" className="flex gap-1.5 border-b border-foreground/8 p-3">
            {[0, 1, 2].map((i) => (
              <i key={i} className="size-2 rounded-full bg-foreground/25" />
            ))}
          </div>
          <div className="space-y-2 p-5 font-mono leading-6">
            <p className="break-all">
              <span className="text-[var(--brand)]">$</span> openlet open{' '}
              <span className="text-muted-foreground">{path}</span>
            </p>
            <p className="text-muted-foreground">→ Checking the address…</p>
            <p>
              404 · Nothing lives here.
              <span
                aria-hidden="true"
                className="public-caret ml-1 inline-block h-3 w-1.5 bg-[var(--brand)] align-middle"
              />
            </p>
          </div>
        </div>
        <nav aria-label="Suggested pages" className="mt-7 flex gap-6 text-sm text-muted-foreground">
          <Link to="/workspaces" className="hover:text-foreground">
            Workspaces
          </Link>
          <a href="/#questions" className="hover:text-foreground">
            Questions
          </a>
          <Link to="/login" className="hover:text-foreground">
            Sign in
          </Link>
        </nav>
      </main>
    </PublicLayout>
  );
}
