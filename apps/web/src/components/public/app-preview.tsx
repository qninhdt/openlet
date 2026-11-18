import { useEffect, useMemo } from 'react';
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { router } from '@/router';
import { PreviewBackendProvider } from '@/lib/backend';
import { createLandingDemo } from './landing-demo';

export function AppPreview() {
  const demo = useMemo(() => createLandingDemo(), []);
  const client = useMemo(
    () => new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 1000 } } }),
    [],
  );
  const previewRouter = useMemo(
    () =>
      createRouter({
        routeTree: router.routeTree,
        history: createMemoryHistory({
          initialEntries: [
            `/app/preview/agents/atlas${window.innerWidth <= 720 ? '/' : '/activity'}`,
          ],
        }),
        scrollRestoration: true,
      }),
    [],
  );
  useEffect(() => {
    demo.activate();
    let ready = false;
    const readyTimer = setInterval(() => {
      if (!ready) window.parent.postMessage({ type: 'openlet:preview:ready' }, location.origin);
    }, 250);
    const start = () => {
      ready = true;
      demo.play();
    };
    const receive = (event: MessageEvent) => {
      if (event.origin !== location.origin || event.source !== window.parent) return;
      if (event.data?.type === 'openlet:preview:start') {
        ready = true;
        start();
      }
      if (event.data?.type === 'openlet:preview:pause') {
        demo.pause();
      }
    };
    const unsubscribe = previewRouter.subscribe('onResolved', () => {
      const params = previewRouter.state.matches.findLast((m) => 'agentId' in m.params)?.params;
      if (params && 'agentId' in params && typeof params.agentId === 'string')
        demo.select(params.agentId);
      if (!ready) {
        window.parent.postMessage({ type: 'openlet:preview:ready' }, location.origin);
        if (window.parent === window) start();
      }
    });
    const visibility = () => {
      if (document.hidden) {
        demo.pause();
      } else if (ready && window.parent === window) {
        demo.play();
      }
    };
    window.addEventListener('message', receive);
    document.addEventListener('visibilitychange', visibility);
    return () => {
      clearInterval(readyTimer);
      unsubscribe();
      window.removeEventListener('message', receive);
      document.removeEventListener('visibilitychange', visibility);
      demo.dispose();
      client.clear();
    };
  }, [demo, client, previewRouter]);
  return (
    <div className="dark relative h-dvh bg-background text-foreground [&_.h-dvh]:h-full">
      <QueryClientProvider client={client}>
        <PreviewBackendProvider value={demo.backend}>
          <RouterProvider router={previewRouter} />
        </PreviewBackendProvider>
      </QueryClientProvider>
    </div>
  );
}
