import { Link, Outlet } from '@tanstack/react-router';
import type { ReactNode } from 'react';

import { AppShell } from '@/components/app-shell';
import { Button } from '@/components/ui/button';

export function RootLayout() {
  return (
    <>
      <a
        href="#main-content"
        className="sr-only rounded-md bg-background p-3 focus:not-sr-only focus:absolute focus:z-50"
      >
        Skip to content
      </a>
      <Outlet />
    </>
  );
}

function PublicLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-svh">
      <header className="border-b">
        <nav
          aria-label="Main navigation"
          className="mx-auto flex max-w-6xl flex-wrap items-center gap-2 px-6 py-4"
        >
          <Link to="/" className="mr-auto text-lg font-semibold">
            Openlet
          </Link>
          <Button variant="ghost" asChild>
            <Link to="/login">Sign in</Link>
          </Button>
          <Button variant="outline" asChild>
            <Link to="/app">Workspace</Link>
          </Button>
        </nav>
      </header>
      <main id="main-content" className="mx-auto max-w-6xl px-6 py-16">
        {children}
      </main>
    </div>
  );
}

export function LandingPage() {
  return (
    <PublicLayout>
      <div className="flex max-w-2xl flex-col items-start gap-6">
        <h1 className="text-4xl font-semibold tracking-tight">Openlet</h1>
        <p className="text-lg text-muted-foreground">
          A shared workspace for your agents and files.
        </p>
        <Button asChild>
          <Link to="/app">Open workspace</Link>
        </Button>
      </div>
    </PublicLayout>
  );
}

export function LoginPage() {
  return (
    <PublicLayout>
      <h1 className="text-3xl font-semibold">Sign in</h1>
    </PublicLayout>
  );
}

export function WorkspacePage() {
  return <AppShell />;
}

export function NotFoundPage() {
  return (
    <PublicLayout>
      <div className="flex flex-col items-start gap-4">
        <h1 className="text-3xl font-semibold">Page not found</h1>
        <Button asChild>
          <Link to="/">Back to home</Link>
        </Button>
      </div>
    </PublicLayout>
  );
}
