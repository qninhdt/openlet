import { createRoot } from 'react-dom/client';
import App from '../src/App';
import { PreviewBackendProvider, type Backend } from '../src/lib/backend';
import { createLandingDemo } from '../src/components/public/landing-demo';
import '../src/globals.css';

const demo = createLandingDemo();
const calls: { path: string; method: string }[] = [];
Object.assign(window, { emptyWorkspaceCalls: calls });
const backend: Backend = {
  ...demo.backend,
  request: async (path, init) => {
    calls.push({ path, method: init?.method ?? 'GET' });
    if (init?.method && init.method !== 'GET') throw new Error('This fixture is read-only');
    return demo.backend.request!(path, init);
  },
  api: async <T,>(path: string, init?: RequestInit): Promise<T> => {
    const method = init?.method ?? 'GET';
    calls.push({ path, method });
    if (method !== 'GET') throw new Error('This fixture is read-only');
    if (path === '/v1/workspaces/preview/letas') return { items: [], next_cursor: null } as T;
    if (path.endsWith('/letas/sidebar'))
      return {
        revision: 1,
        can_create_agent: true,
        layout: { folders: [], assignments: {}, pins: [], order: [], collapsed: [] },
      } as T;
    if (path.includes('/letas/box-view'))
      return { agents: [], boxes: [], edges: [], schedules: [], roots: [], next_cursor: null } as T;
    return demo.backend.api!<T>(path, init);
  },
};
createRoot(document.getElementById('root')!).render(
  <PreviewBackendProvider value={backend}>
    <App />
  </PreviewBackendProvider>,
);
