import {
  createRootRoute,
  createRoute,
  createRouter,
  lazyRouteComponent,
  type SearchSchemaInput,
} from '@tanstack/react-router';
import { RootLayout, WorkspacePage } from '@/pages';
import { parseLegacySearch, type ShellLocation } from '@/lib/shell-model';
import { RouteError } from '@/components/public/page-state';
import { safeReturnTo } from '@/lib/auth-navigation';

const LandingPage = lazyRouteComponent(
  () => import('./components/public/landing-page'),
  'LandingPage',
);
const LoginPage = lazyRouteComponent(() => import('./components/public/auth-page'), 'LoginPage');
const NotFoundPage = lazyRouteComponent(
  () => import('./components/public/not-found-page'),
  'NotFoundPage',
);
const SignInCallback = lazyRouteComponent(
  () => import('./components/public/auth-page'),
  'SignInCallback',
);
const WorkspacesPage = lazyRouteComponent(
  () => import('./components/public/workspace-pages'),
  'WorkspacesPage',
);
const JoinPage = lazyRouteComponent(
  () => import('./components/public/workspace-pages'),
  'JoinPage',
);
const LegalPage = lazyRouteComponent(() => import('./components/public/legal-page'), 'LegalPage');
const AppPreview = lazyRouteComponent(
  () => import('./components/public/app-preview'),
  'AppPreview',
);
const AppShell = lazyRouteComponent(() => import('./components/app-shell'), 'AppShell');
const AgentOverview = lazyRouteComponent(
  () => import('./components/agents/agent-overview'),
  'AgentOverview',
);
const LegacyWorkspaceEntry = lazyRouteComponent(
  () => import('./workspace-pages'),
  'LegacyWorkspaceEntry',
);
const WorkspaceEntry = lazyRouteComponent(() => import('./workspace-pages'), 'WorkspaceEntry');
const AgentLayout = lazyRouteComponent(() => import('./workspace-pages'), 'AgentLayout');
const AgentChat = lazyRouteComponent(() => import('./workspace-pages'), 'AgentChat');
const ActivityPage = lazyRouteComponent(() => import('./workspace-pages'), 'ActivityPage');
const AgentBoxPage = lazyRouteComponent(() => import('./workspace-pages'), 'AgentBoxPage');
const BoxPage = lazyRouteComponent(() => import('./workspace-pages'), 'BoxPage');
const StorageEntry = lazyRouteComponent(() => import('./workspace-pages'), 'StorageEntry');
const StoragePage = lazyRouteComponent(() => import('./workspace-pages'), 'StoragePage');
const SettingsPage = lazyRouteComponent(() => import('./workspace-pages'), 'SettingsPage');

const rootRoute = createRootRoute({
  component: RootLayout,
  notFoundComponent: NotFoundPage,
  errorComponent: RouteError,
});
const landingRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: LandingPage,
});
const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/login',
  validateSearch: (search: Record<string, unknown> & SearchSchemaInput) => ({
    returnTo: safeReturnTo(search.returnTo),
  }),
  component: LoginPage,
});
const signInCallbackRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/sso-callback',
  component: SignInCallback,
});
const workspacesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/workspaces',
  component: WorkspacesPage,
});
const joinRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/join',
  validateSearch: (search: Record<string, unknown> & SearchSchemaInput) => ({
    token: typeof search.token === 'string' ? search.token : '',
  }),
  component: JoinPage,
});
const privacyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/privacy',
  component: () => <LegalPage kind="privacy" />,
});
const termsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/terms',
  component: () => <LegalPage kind="terms" />,
});
const previewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/app-preview',
  component: AppPreview,
});
const appRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/app',
  component: WorkspacePage,
});
const legacyRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/',
  validateSearch: (search: Record<string, unknown> & SearchSchemaInput) =>
    Object.fromEntries(
      Object.entries(parseLegacySearch(search)).filter(([key, value]) => search[key] && value),
    ) as Partial<ShellLocation>,
  component: LegacyWorkspaceEntry,
});
const workspaceRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '$workspaceId',
  component: AppShell,
});
const workspaceIndex = createRoute({
  getParentRoute: () => workspaceRoute,
  path: '/',
  component: WorkspaceEntry,
});
const agentsRoute = createRoute({
  getParentRoute: () => workspaceRoute,
  path: 'agents',
  staticData: { view: 'agents' },
});
const agentsIndex = createRoute({
  getParentRoute: () => agentsRoute,
  path: '/',
  component: WorkspaceEntry,
});
const agentRoute = createRoute({
  getParentRoute: () => agentsRoute,
  path: '$agentId',
  component: AgentLayout,
});
const chatRoute = createRoute({
  getParentRoute: () => agentRoute,
  path: '/',
  staticData: { agentTab: 'agent' },
  validateSearch: (search: Record<string, unknown> & SearchSchemaInput) => ({
    message: typeof search.message === 'string' ? search.message : undefined,
    role: search.role === 'assistant' ? ('assistant' as const) : ('user' as const),
  }),
  component: AgentChat,
});
const overviewRoute = createRoute({
  getParentRoute: () => agentRoute,
  path: 'overview',
  staticData: { agentTab: 'overview' },
  component: AgentOverview,
});
const activityRoute = createRoute({
  getParentRoute: () => agentRoute,
  path: 'activity',
  staticData: { agentTab: 'activity' },
  component: ActivityPage,
});
const agentBoxRoute = createRoute({
  getParentRoute: () => agentRoute,
  path: 'box',
  staticData: { agentTab: 'box' },
  component: AgentBoxPage,
});
const letiRoute = createRoute({
  getParentRoute: () => agentRoute,
  path: 'letis/$letiId/activity',
  component: ActivityPage,
});
const boxesRoute = createRoute({
  getParentRoute: () => workspaceRoute,
  path: 'boxes',
  staticData: { view: 'boxes' },
});
const boxesIndex = createRoute({ getParentRoute: () => boxesRoute, path: '/', component: BoxPage });
const scopedBoxRoute = createRoute({ getParentRoute: () => boxesRoute, path: '$agentId' });
const scopedBoxIndex = createRoute({
  getParentRoute: () => scopedBoxRoute,
  path: '/',
  component: BoxPage,
});
const boxLetiRoute = createRoute({
  getParentRoute: () => scopedBoxRoute,
  path: 'letis/$letiId/activity',
  component: ActivityPage,
  validateSearch: (search: Record<string, unknown> & SearchSchemaInput) => ({
    scope: search.scope === 'all' ? ('all' as const) : undefined,
  }),
});
const storageRoute = createRoute({
  getParentRoute: () => workspaceRoute,
  path: 'storage',
  staticData: { view: 'storage' },
});
const storageIndex = createRoute({
  getParentRoute: () => storageRoute,
  path: '/',
  component: StorageEntry,
  validateSearch: (search: Record<string, unknown> & SearchSchemaInput) => ({
    folder: typeof search.folder === 'string' && search.folder ? search.folder : undefined,
    file: typeof search.file === 'string' && search.file ? search.file : undefined,
  }),
});
const storageRootRoute = createRoute({ getParentRoute: () => storageRoute, path: '$storageId' });
const storageBrowserRoute = createRoute({
  getParentRoute: () => storageRootRoute,
  path: '/',
  component: StoragePage,
});
const folderRoute = createRoute({
  getParentRoute: () => storageRootRoute,
  path: 'folders/$folderId',
  component: StoragePage,
});
const fileRoute = createRoute({
  getParentRoute: () => storageRootRoute,
  path: 'files/$nodeId',
  component: StoragePage,
});
const settingsRoute = createRoute({
  getParentRoute: () => workspaceRoute,
  path: 'settings',
  staticData: { view: 'settings' },
});
const settingsIndex = createRoute({
  getParentRoute: () => settingsRoute,
  path: '/',
  component: SettingsPage,
});
const settingsSection = createRoute({
  getParentRoute: () => settingsRoute,
  path: '$section',
  component: SettingsPage,
});

export const router = createRouter({
  routeTree: rootRoute.addChildren([
    landingRoute,
    loginRoute,
    signInCallbackRoute,
    workspacesRoute,
    joinRoute,
    privacyRoute,
    termsRoute,
    previewRoute,
    appRoute.addChildren([
      legacyRoute,
      workspaceRoute.addChildren([
        workspaceIndex,
        agentsRoute.addChildren([
          agentsIndex,
          agentRoute.addChildren([
            chatRoute,
            overviewRoute,
            activityRoute,
            agentBoxRoute,
            letiRoute,
          ]),
        ]),
        boxesRoute.addChildren([
          boxesIndex,
          scopedBoxRoute.addChildren([scopedBoxIndex, boxLetiRoute]),
        ]),
        storageRoute.addChildren([
          storageIndex,
          storageRootRoute.addChildren([storageBrowserRoute, folderRoute, fileRoute]),
        ]),
        settingsRoute.addChildren([settingsIndex, settingsSection]),
      ]),
    ]),
  ]),
  scrollRestoration: true,
});

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}
