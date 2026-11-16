import {
  createRootRoute,
  createRoute,
  createRouter,
  type SearchSchemaInput,
} from '@tanstack/react-router';

import { LandingPage, LoginPage, NotFoundPage, RootLayout, WorkspacePage } from '@/pages';
import { parseShellSearch } from '@/lib/shell-model';

const rootRoute = createRootRoute({
  component: RootLayout,
  notFoundComponent: NotFoundPage,
});

const landingRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: LandingPage,
});

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/login',
  component: LoginPage,
});

const workspaceRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/app',
  validateSearch: (search: Record<string, unknown> & SearchSchemaInput) => parseShellSearch(search),
  component: WorkspacePage,
});

export const router = createRouter({
  routeTree: rootRoute.addChildren([landingRoute, loginRoute, workspaceRoute]),
  scrollRestoration: true,
});

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}
