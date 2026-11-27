import { createRoot } from 'react-dom/client';
import App from '../src/App';
import { createLandingDemo } from '../src/components/public/landing-demo';
import { ApiError } from '../src/lib/agent-api';
import { PreviewBackendProvider, type Backend } from '../src/lib/backend';
import { RealtimeProvider } from '../src/lib/realtime';
import '../src/globals.css';

const demo = createLandingDemo();
const preferences = {
  messageSound: true,
  compactMessageActions: new URLSearchParams(location.search).get('compact') === 'true',
};
const request: NonNullable<Backend['request']> = async (path, init) => {
  const response = await fetch('/__browser_fixture' + path, init);
  return response.status === 501 ? demo.backend.request!(path, init) : response;
};
const backend: Backend = {
  ...demo.backend,
  account: {
    id: demo.backend.actorId,
    displayName: 'Browser fixture',
    preferences,
  },
  request,
  api: async <T,>(path: string, init?: RequestInit): Promise<T> => {
    const response = await request(path, init);
    if (!response.ok) throw new ApiError(response.status, 'Browser fixture request failed');
    return response.json();
  },
};

createRoot(document.getElementById('root')!).render(
  <PreviewBackendProvider value={backend}>
    <RealtimeProvider>
      <App />
    </RealtimeProvider>
  </PreviewBackendProvider>,
);
