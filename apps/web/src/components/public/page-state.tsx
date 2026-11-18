import type { ReactNode } from 'react';
import { Link } from '@tanstack/react-router';
import { ArrowLeft, RotateCw } from 'lucide-react';
import { AppLogo } from '@/components/app-logo';
import { Button } from '@/components/ui/button';
import { PublicLayout, siteAction, usePageTitle } from './public-layout';

export function AppLoading({ label = 'Opening your workspace…' }: { label?: string }) {
  return (
    <main
      id="main-content"
      role="status"
      aria-live="polite"
      aria-busy="true"
      className="grid min-h-dvh place-items-center bg-background p-6 text-foreground"
    >
      <div className="flex flex-col items-center gap-6">
        <AppLogo animated className="size-14" />
        <p className="text-sm text-muted-foreground">{label}</p>
      </div>
    </main>
  );
}

export function TransactionalPage({
  title,
  description,
  children,
}: {
  title: string;
  description: ReactNode;
  children?: ReactNode;
}) {
  usePageTitle(title);
  return (
    <PublicLayout>
      <main id="main-content" className="flex min-h-[65svh] items-center justify-center px-5 py-20">
        <section
          className="w-full max-w-[480px] rounded-3xl border border-foreground/10 bg-card p-7 text-center sm:p-12"
          aria-labelledby="transaction-title"
        >
          <AppLogo animated className="mx-auto mb-7 size-14" />
          <h1
            id="transaction-title"
            className="text-balance text-3xl font-medium tracking-[-0.035em]"
          >
            {title}
          </h1>
          <div className="mt-4 text-sm leading-6 text-muted-foreground">{description}</div>
          {children}
        </section>
      </main>
    </PublicLayout>
  );
}

export function PageFailure({
  title = 'Something went wrong',
  message,
  retry,
}: {
  title?: string;
  message: string;
  retry?: () => void;
}) {
  return (
    <TransactionalPage title={title} description={<p role="alert">{message}</p>}>
      <div className="mt-7 flex flex-wrap justify-center gap-3">
        {retry && (
          <Button className={siteAction} onClick={retry}>
            <RotateCw className="size-4" />
            Try again
          </Button>
        )}
        <Button variant="outline" className={siteAction} asChild>
          <Link to="/">
            <ArrowLeft className="size-4" />
            Back to home
          </Link>
        </Button>
      </div>
    </TransactionalPage>
  );
}

export function RouteError() {
  return (
    <PageFailure
      message="This page could not be loaded. Try again, or return to the home page."
      retry={() => window.location.reload()}
    />
  );
}
