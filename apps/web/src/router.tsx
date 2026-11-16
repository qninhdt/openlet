import {
  createRootRoute,
  createRoute,
  createRouter,
  type SearchSchemaInput,
} from '@tanstack/react-router';
import { LandingPage, LoginPage, NotFoundPage, RootLayout, WorkspacePage } from '@/pages';
import { AppShell } from '@/components/app-shell';
import { AgentOverview } from '@/components/agents/agent-overview';
import {
  LegacyWorkspaceEntry,
  WorkspaceEntry,
  AgentLayout,
  AgentChat,
  ActivityPage,
  AgentBoxPage,
  BoxPage,
  StorageEntry,
  StoragePage,
  SettingsPage,
} from '@/workspace-pages';
import { parseLegacySearch } from '@/lib/shell-model';

const rootRoute = createRootRoute({ component: RootLayout, notFoundComponent: NotFoundPage });
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
const appRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/app',
  component: WorkspacePage,
});
const legacyRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/',
  validateSearch: (search: Record<string, unknown> & SearchSchemaInput) =>
    parseLegacySearch(search),
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
    folder: typeof search.folder === 'string' ? search.folder : '',
    file: typeof search.file === 'string' ? search.file : '',
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
