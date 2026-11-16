import { createContext, useContext, useMemo, useEffect, useRef, type ReactNode } from 'react';
import { ClerkProvider, useAuth, useUser, SignIn } from '@clerk/react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, type Api } from './agent-api';

type Backend = {
  enabled: boolean;
  ready: boolean;
  actorId: string;
  api: Api | null;
  request: ((path: string, init?: RequestInit) => Promise<Response>) | null;
};
const BackendContext = createContext<Backend>({
  enabled: false,
  ready: true,
  actorId: 'demo-owner',
  api: null,
  request: null,
});
const publishableKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY as string | undefined;
const baseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') ?? '';

export function BackendProvider({ children }: { children: ReactNode }) {
  return publishableKey ? (
    <ClerkProvider publishableKey={publishableKey}>
      <ClerkBackend>{children}</ClerkBackend>
    </ClerkProvider>
  ) : (
    children
  );
}
function ClerkBackend({ children }: { children: ReactNode }) {
  const { isLoaded, isSignedIn, getToken, userId } = useAuth();
  const { user } = useUser();
  const client = useQueryClient();
  const previousActor = useRef(userId);
  useEffect(() => {
    if (previousActor.current !== userId) {
      client.clear();
      previousActor.current = userId;
    }
  }, [client, userId]);
  const request = useMemo(
    () => async (path: string, init?: RequestInit) => {
      const token = await getToken();
      if (!token) throw new ApiError(401, 'Sign in to continue.');
      const response = await fetch(baseUrl + path, {
        ...init,
        headers: {
          'Content-Type': 'application/json',
          ...init?.headers,
          Authorization: `Bearer ${token}`,
        },
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new ApiError(
          response.status,
          body?.detail ?? body?.message ?? 'The request could not be completed.',
        );
      }
      return response;
    },
    [getToken],
  );
  const api = useMemo<Api>(
    () =>
      async <T,>(path: string, init?: RequestInit) =>
        (await request(path, init)).json() as Promise<T>,
    [request],
  );
  const identity = useQuery({
    queryKey: ['identity', userId],
    enabled: !!isSignedIn,
    retry: false,
    queryFn: async () => {
      if (!user?.publicMetadata.openlet_user_id) {
        const onboarded = await api<{ id: string }>('/v1/me:onboard', {
          method: 'POST',
          body: '{}',
        });
        await user?.reload();
        await getToken({ skipCache: true });
        return onboarded;
      }
      return api<{ id: string }>('/v1/me');
    },
  });
  return (
    <BackendContext.Provider
      value={{
        enabled: true,
        ready: !!isLoaded && !!identity.data,
        actorId: identity.data?.id ?? '',
        api,
        request,
      }}
    >
      {!isLoaded || (isSignedIn && identity.isPending) ? (
        <div
          role="status"
          className="grid min-h-dvh place-items-center text-sm text-muted-foreground"
        >
          Loading your workspace…
        </div>
      ) : identity.error ? (
        <div role="alert" className="p-8">
          {identity.error.message}
        </div>
      ) : isSignedIn ? (
        <div key={userId}>{children}</div>
      ) : (
        <div className="grid min-h-dvh place-items-center bg-background">
          <SignIn routing="hash" />
        </div>
      )}
    </BackendContext.Provider>
  );
}
export const useBackend = () => useContext(BackendContext);
export { baseUrl };
