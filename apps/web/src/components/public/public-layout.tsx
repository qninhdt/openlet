import { useEffect, useState, type ReactNode } from 'react';
import { Link } from '@tanstack/react-router';
import { ArrowRight, ChevronDown, Menu } from 'lucide-react';
import { AppLogo } from '@/components/app-logo';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from '@/components/ui/sheet';
import { cn } from '@/lib/utils';
import './public-motion.css';

export const siteWidth = 'mx-auto w-full max-w-[1280px] px-4 sm:px-8 lg:px-12';
export const sectionTitle =
  'text-balance text-[clamp(2.5rem,4.5vw,4rem)] leading-[1.05] font-medium tracking-[-0.045em]';
export const siteAction = 'h-12 gap-2 rounded-full px-6 text-sm font-medium';
const copyrightYear = new Date().getFullYear();
const navigation = [
  ['Features', '/#features'],
  ['For teams', '/#teams'],
  ['Questions', '/#questions'],
] as const;

export function usePageTitle(title: string, description?: string) {
  useEffect(() => {
    const previous = document.title;
    document.title = `${title} · Openlet`;
    const meta = document.querySelector<HTMLMetaElement>('meta[name="description"]');
    const previousDescription = meta?.content;
    if (meta && description) meta.content = description;
    return () => {
      document.title = previous;
      if (meta && previousDescription !== undefined) meta.content = previousDescription;
    };
  }, [title, description]);
}

export function PublicBrand({ large = false }: { large?: boolean }) {
  return (
    <Link
      to="/"
      aria-label="Openlet home"
      className={cn(
        'inline-flex shrink-0 items-center font-semibold tracking-[-0.025em]',
        large ? 'gap-6 text-4xl' : 'gap-3 text-base',
      )}
    >
      <AppLogo animated className={large ? 'size-20' : 'size-7'} />
      Openlet
    </Link>
  );
}

export function SiteHeader() {
  const [open, setOpen] = useState(false);
  return (
    <header className={cn(siteWidth, 'relative z-20 flex h-20 items-center justify-between gap-5')}>
      <PublicBrand />
      <nav
        aria-label="Main navigation"
        className="hidden items-center gap-1 rounded-full border border-foreground/8 bg-foreground/3 p-1 lg:flex"
      >
        {navigation.map(([label, href]) => (
          <a
            key={label}
            href={href}
            className="rounded-full px-4 py-2 text-[13px] text-muted-foreground transition-colors hover:bg-foreground/5 hover:text-foreground"
          >
            {label}
          </a>
        ))}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              className="gap-1.5 rounded-full text-[13px] text-muted-foreground"
            >
              Resources
              <ChevronDown className="size-3" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent className="public-theme dark w-52" align="end">
            <DropdownMenuItem asChild>
              <a href="https://github.com/qninhdt/openlet" target="_blank" rel="noreferrer">
                Source code
                <ArrowRight className="ml-auto size-3" />
              </a>
            </DropdownMenuItem>
            <DropdownMenuItem asChild>
              <Link to="/privacy">Privacy</Link>
            </DropdownMenuItem>
            <DropdownMenuItem asChild>
              <Link to="/terms">Terms</Link>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </nav>
      <div className="flex items-center gap-2">
        <Button asChild className="hidden h-9 rounded-full px-5 sm:inline-flex">
          <Link to="/login">Get started</Link>
        </Button>
        <Button
          asChild
          variant="outline"
          className="h-9 rounded-full border-foreground/15 bg-foreground/5 px-4"
        >
          <Link to="/app">
            App
            <ArrowRight className="size-3.5" />
          </Link>
        </Button>
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetTrigger asChild>
            <Button
              aria-label="Open navigation"
              variant="ghost"
              size="icon"
              className="rounded-full lg:hidden"
            >
              <Menu />
            </Button>
          </SheetTrigger>
          <SheetContent
            className="public-theme dark w-[min(90vw,380px)] p-6"
            onCloseAutoFocus={(event) => {
              const target = document.getElementById(location.hash.slice(1));
              if (!target) return;
              event.preventDefault();
              target.scrollIntoView();
            }}
          >
            <SheetTitle className="mb-6">
              <PublicBrand />
            </SheetTitle>
            <nav aria-label="Mobile navigation" className="flex flex-col gap-2">
              {navigation.map(([label, href]) => (
                <a
                  key={label}
                  href={href}
                  onClick={() => setOpen(false)}
                  className="rounded-xl px-3 py-3 text-lg hover:bg-accent"
                >
                  {label}
                </a>
              ))}
              <Link
                to="/workspaces"
                onClick={() => setOpen(false)}
                className="rounded-xl px-3 py-3 text-lg hover:bg-accent"
              >
                Workspaces
              </Link>
              <Link
                to="/privacy"
                onClick={() => setOpen(false)}
                className="px-3 py-3 text-muted-foreground"
              >
                Privacy
              </Link>
              <Link
                to="/terms"
                onClick={() => setOpen(false)}
                className="px-3 py-3 text-muted-foreground"
              >
                Terms
              </Link>
            </nav>
            <Button asChild className="mt-auto h-12 rounded-full">
              <Link to="/login" onClick={() => setOpen(false)}>
                Get started
                <ArrowRight />
              </Link>
            </Button>
          </SheetContent>
        </Sheet>
      </div>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className={cn(siteWidth, 'pt-20 pb-8 md:pt-24')}>
      <div className="grid gap-14 md:grid-cols-[1.1fr_1fr] md:gap-24">
        <div>
          <PublicBrand />
          <p className="mt-8 max-w-[430px] text-[clamp(1.6rem,2.5vw,2.1rem)] leading-[1.25] tracking-[-0.035em]">
            A shared workspace for your agents, your team and the work you do together.
          </p>
          <Button asChild className="mt-7 rounded-full">
            <Link to="/login">
              Get started
              <ArrowRight />
            </Link>
          </Button>
        </div>
        <div className="grid grid-cols-2 gap-8 text-sm">
          <nav aria-label="Product links" className="flex flex-col items-start gap-4">
            <p className="mb-2 text-xs text-muted-foreground">Product</p>
            {navigation.map(([label, href]) => (
              <a key={label} href={href} className="hover:underline hover:underline-offset-4">
                {label}
              </a>
            ))}
            <Link to="/app">Open app</Link>
            <Link to="/workspaces">Workspaces</Link>
          </nav>
          <nav aria-label="Resource links" className="flex flex-col items-start gap-4">
            <p className="mb-2 text-xs text-muted-foreground">Resources</p>
            <a href="https://github.com/qninhdt/openlet" target="_blank" rel="noreferrer">
              GitHub
            </a>
            <Link to="/privacy">Privacy</Link>
            <Link to="/terms">Terms</Link>
          </nav>
        </div>
      </div>
      <div className="mt-20 flex flex-wrap justify-between gap-3 border-t border-foreground/8 pt-6 text-xs text-muted-foreground">
        <span>© {copyrightYear} Openlet</span>
        <span>Your agents. One workspace.</span>
      </div>
    </footer>
  );
}

export function PublicLayout({
  children,
  chrome = true,
}: {
  children: ReactNode;
  chrome?: boolean;
}) {
  return (
    <div className="public-theme dark min-h-svh overflow-x-clip bg-background font-[Inter_Variable,sans-serif] text-foreground selection:bg-[var(--brand)] selection:text-[var(--brand-foreground)]">
      {chrome && <SiteHeader />}
      {children}
      {chrome && <SiteFooter />}
    </div>
  );
}
