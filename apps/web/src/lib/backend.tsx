import {
  createContext,
  useContext,
  useMemo,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { ClerkProvider, useAuth, useUser } from '@clerk/react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, type Api } from './agent-api';
import { Navigate, useLocation } from '@tanstack/react-router';
import { AppLoading, PageFailure } from '@/components/public/page-state';
import { publishableKey, safeReturnTo } from './auth-navigation';
import { defaultPreferences, type Account } from './account';
import { useTheme } from 'next-themes';
import { clearAccountDrafts } from './chat-drafts';
import { clearUploads } from './upload-resume';
import { clearDevAccount, devAuthEnabled, readDevAccount } from './dev-auth';
import { RealtimeProvider, type RealtimeContextValue } from './realtime';

async function parseJsonResponse<T>(response: Response): Promise<T> {
  if (response.status === 204 || response.status === 205) return {} as T;
  const text = await response.text();
  if (!text.trim()) return {} as T;
  return JSON.parse(text) as T;
}

export type Backend = {
  preview?: boolean;
  previewRealtime?: RealtimeContextValue;
  enabled: boolean;
  ready: boolean;
  actorId: string;
  api: Api | null;
  request: ((path: string, init?: RequestInit) => Promise<Response>) | null;
  account?: Account;
  updateAccount?: (patch: Partial<Omit<Account, 'id'>>) => Promise<void>;
  logout?: () => Promise<void>;
};
const BackendContext = createContext<Backend>({
  enabled: false,
  ready: false,
  actorId: '',
  api: null,
  request: null,
});
const baseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') ?? '';

export const apiUrl = (path: string) => baseUrl + path;

export function AuthProvider({ children }: { children: ReactNode }) {
  const inherited = useContext(BackendContext);
  if (inherited.preview || devAuthEnabled) return children;
  return publishableKey ? (
    <ClerkProvider publishableKey={publishableKey}>{children}</ClerkProvider>
  ) : (
    children
  );
}
export function BackendProvider({ children }: { children: ReactNode }) {
  const inherited = useContext(BackendContext);
  if (inherited.preview) return children;
  if (devAuthEnabled) return <DevBackend>{children}</DevBackend>;
  return publishableKey ? (
    <ClerkBackend>{children}</ClerkBackend>
  ) : (
    <PageFailure
      title="Sign-in unavailable"
      message="Authentication is not configured on this installation. Set the Clerk publishable key and restart the web server."
    />
  );
}
function DevBackend({ children }: { children: ReactNode }) {
  const [devAccount, setDevAccount] = useState(() => readDevAccount());
  const { setTheme } = useTheme();
  const href = useLocation({ select: (location) => location.href });
  const client = useQueryClient();
  const userId = devAccount?.user_id;
  const session = useMemo(() => ({ controller: new AbortController() }), [userId]);
  const consistency = useRef({ actor: userId, token: '' });
  const request = useMemo(
    () => async (path: string, init?: RequestInit) => {
      const controller = session.controller;
      controller.signal.throwIfAborted();
      if (!devAccount?.token) throw new ApiError(401, 'Sign in to continue.');
      if (consistency.current.actor !== userId || !consistency.current.token)
        consistency.current = {
          actor: userId,
          token: sessionStorage.getItem(`openlet-zed:${userId}`) ?? '',
        };
      const response = await fetch(baseUrl + path, {
        ...init,
        signal: init?.signal
          ? AbortSignal.any([controller.signal, init.signal])
          : controller.signal,
        headers: {
          'Content-Type': 'application/json',
          ...(consistency.current.actor === userId && consistency.current.token
            ? { 'x-openlet-zed-token': consistency.current.token }
            : {}),
          ...init?.headers,
          Authorization: `Bearer ${devAccount.token}`,
        },
      });
      controller.signal.throwIfAborted();
      const revision = response.headers.get('x-openlet-zed-token');
      if (revision && response.ok) {
        consistency.current = { actor: userId, token: revision };
        sessionStorage.setItem(`openlet-zed:${userId}`, revision);
      }
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new ApiError(
          response.status,
          body?.detail ?? body?.message ?? 'The request could not be completed.',
        );
      }
      return response;
    },
    [devAccount, userId, session],
  );
  const api = useMemo<Api>(
    () =>
      async <T,>(path: string, init?: RequestInit) =>
        parseJsonResponse<T>(await request(path, init)),
    [request],
  );
  const identity = useQuery({
    queryKey: ['identity', userId],
    enabled: Boolean(devAccount?.token),
    retry: false,
    queryFn: ({ signal }) => api<Account>('/v1/me', { signal }),
  });
  useEffect(() => {
    if (identity.error instanceof ApiError && identity.error.status === 401) {
      clearDevAccount();
      setDevAccount(null);
    }
  }, [identity.error]);
  useEffect(() => {
    if (identity.data) setTheme(identity.data.preferences?.theme ?? 'system');
  }, [identity.data?.preferences?.theme, !!identity.data, setTheme]);
  return (
    <BackendContext.Provider
      value={{
        enabled: true,
        ready: Boolean(devAccount && identity.data),
        actorId: identity.data?.id ?? '',
        api,
        request,
        account: identity.data,
        updateAccount: async (patch) => {
          const account = await api<Account>('/v1/me', {
            method: 'PATCH',
            body: JSON.stringify(patch),
          });
          client.setQueryData(['identity', userId], account);
          await client.invalidateQueries({ queryKey: ['workspace-members'] });
        },
        logout: async () => {
          session.controller.abort();
          clearAccountDrafts(identity.data?.id ?? '');
          clearUploads(identity.data?.id ?? '');
          await client.cancelQueries();
          clearDevAccount();
          client.clear();
          sessionStorage.removeItem(`openlet-zed:${userId}`);
          setDevAccount(null);
          window.location.replace('/login');
        },
      }}
    >
      {devAccount && identity.isPending ? (
        <AppLoading />
      ) : identity.error ? (
        <PageFailure
          title="Workspace unavailable"
          message={identity.error.message}
          retry={() => {
            void identity.refetch();
          }}
        />
      ) : devAccount ? (
        <RealtimeProvider>
          <div key={userId}>{children}</div>
        </RealtimeProvider>
      ) : (
        <Navigate to="/login" search={{ returnTo: safeReturnTo(href) }} replace />
      )}
    </BackendContext.Provider>
  );
}
function ClerkBackend({ children }: { children: ReactNode }) {
  const { isLoaded, isSignedIn, getToken, userId, signOut } = useAuth();
  const { setTheme } = useTheme();
  const { user, isLoaded: userLoaded } = useUser();
  const href = useLocation({ select: (location) => location.href });
  const client = useQueryClient();
  const [signingOut, setSigningOut] = useState(false);
  const session = useMemo(() => ({ controller: new AbortController() }), [userId]);
  useEffect(() => {
    if (session.controller.signal.aborted) session.controller = new AbortController();
    return () => session.controller.abort();
  }, [session]);
  const previousActor = useRef(userId);
  const consistency = useRef({ actor: userId, token: '' });
  useEffect(() => {
    if (previousActor.current !== userId) {
      client.clear();
      previousActor.current = userId;
    }
  }, [client, userId]);
  const request = useMemo(
    () => async (path: string, init?: RequestInit) => {
      const controller = session.controller;
      controller.signal.throwIfAborted();
      if (consistency.current.actor !== userId || !consistency.current.token)
        consistency.current = {
          actor: userId,
          token: sessionStorage.getItem(`openlet-zed:${userId}`) ?? '',
        };
      const token = await getToken({ template: 'openlet' });
      if (!token) throw new ApiError(401, 'Sign in to continue.');
      const response = await fetch(baseUrl + path, {
        ...init,
        signal: init?.signal
          ? AbortSignal.any([controller.signal, init.signal])
          : controller.signal,
        headers: {
          'Content-Type': 'application/json',
          ...(consistency.current.actor === userId && consistency.current.token
            ? { 'x-openlet-zed-token': consistency.current.token }
            : {}),
          ...init?.headers,
          Authorization: `Bearer ${token}`,
        },
      });
      controller.signal.throwIfAborted();
      const revision = response.headers.get('x-openlet-zed-token');
      if (revision && response.ok) {
        consistency.current = { actor: userId, token: revision };
        sessionStorage.setItem(`openlet-zed:${userId}`, revision);
      }
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new ApiError(
          response.status,
          body?.detail ?? body?.message ?? 'The request could not be completed.',
        );
      }
      return response;
    },
    [getToken, userId, session],
  );
  const api = useMemo<Api>(
    () =>
      async <T,>(path: string, init?: RequestInit) =>
        parseJsonResponse<T>(await request(path, init)),
    [request],
  );
  const identity = useQuery({
    queryKey: ['identity', userId],
    enabled: !!isSignedIn && userLoaded,
    retry: false,
    queryFn: async () => {
      try {
        return await api<Account>('/v1/me');
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 404) throw error;
        const onboarded = await api<Account>('/v1/me:onboard', {
          method: 'POST',
          body: '{}',
        });
        await user?.reload();
        await getToken({ template: 'openlet', skipCache: true });
        return onboarded;
      }
    },
  });
  useEffect(() => {
    if (identity.data) setTheme(identity.data.preferences?.theme ?? 'system');
  }, [identity.data?.preferences?.theme, !!identity.data, setTheme]);
  return (
    <BackendContext.Provider
      value={{
        enabled: true,
        ready: !!isLoaded && !!identity.data,
        actorId: identity.data?.id ?? '',
        api,
        request,
        account: identity.data,
        updateAccount: async (patch) => {
          const account = await api<Account>('/v1/me', {
            method: 'PATCH',
            body: JSON.stringify(patch),
          });
          client.setQueryData(['identity', userId], account);
          await client.invalidateQueries({ queryKey: ['workspace-members'] });
        },
        logout: async () => {
          setSigningOut(true);
          session.controller.abort();
          try {
            clearAccountDrafts(identity.data?.id ?? '');
            clearUploads(identity.data?.id ?? '');
            await client.cancelQueries();
            await signOut({ redirectUrl: '/login' });
            client.clear();
            consistency.current = { actor: undefined, token: '' };
            sessionStorage.removeItem(`openlet-zed:${userId}`);
          } catch (error) {
            session.controller = new AbortController();
            setSigningOut(false);
            throw error;
          }
        },
      }}
    >
      {signingOut || !isLoaded || !userLoaded || (isSignedIn && identity.isPending) ? (
        <AppLoading />
      ) : identity.error ? (
        <PageFailure
          title="Workspace unavailable"
          message={identity.error.message}
          retry={() => {
            void identity.refetch();
          }}
        />
      ) : isSignedIn ? (
        <RealtimeProvider>
          <div key={userId}>{children}</div>
        </RealtimeProvider>
      ) : (
        <Navigate to="/login" search={{ returnTo: safeReturnTo(href) }} replace />
      )}
    </BackendContext.Provider>
  );
}
export const useBackend = () => useContext(BackendContext);
export function usePreferences() {
  return { ...defaultPreferences, ...useBackend().account?.preferences };
}
export { baseUrl };

// Only mounted by the isolated public playground; live routes still require Clerk.
export function PreviewBackendProvider({
  value,
  children,
}: {
  value: Backend;
  children: ReactNode;
}) {
  return <BackendContext.Provider value={value}>{children}</BackendContext.Provider>;
}
