import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { Centrifuge, type Subscription } from 'centrifuge';
import { baseUrl, useBackend } from './backend';

export type RealtimeEnvelope<T = Record<string, unknown>> = {
  type: string;
  data: T;
};

export type RealtimeStatus = 'disconnected' | 'connecting' | 'connected' | 'reconnecting';

type SubscriptionListener = {
  onEvent: (event: RealtimeEnvelope) => void;
  onRecovered?: (recovered: boolean) => void;
};

type ManagedSub = {
  sub: Subscription;
  listeners: Set<SubscriptionListener>;
};

export type RealtimeContextValue = {
  status: RealtimeStatus;
  subscribe: (
    channel: string,
    getToken: (() => Promise<string>) | undefined,
    listener: SubscriptionListener,
  ) => () => void;
  onChatUserEvent: (handler: (event: RealtimeEnvelope) => void) => () => void;
  onLetaUserEvent: (handler: (event: RealtimeEnvelope) => void) => () => void;
};

const RealtimeContext = createContext<RealtimeContextValue>({
  status: 'disconnected',
  subscribe: () => () => {},
  onChatUserEvent: () => () => {},
  onLetaUserEvent: () => () => {},
});

function websocketUrl() {
  if (baseUrl) {
    const u = new URL(baseUrl, window.location.origin);
    u.protocol = u.protocol === 'https:' ? 'wss:' : 'ws:';
    u.pathname = `${u.pathname.replace(/\/$/, '')}/connection/websocket`;
    return u.toString();
  }
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/connection/websocket`;
}

function parseEnvelope(raw: unknown): RealtimeEnvelope | null {
  if (!raw || typeof raw !== 'object') return null;
  const obj = raw as Record<string, unknown>;
  if (typeof obj.type !== 'string') return null;
  const data =
    obj.data && typeof obj.data === 'object' ? (obj.data as Record<string, unknown>) : {};
  return { type: obj.type, data };
}

export function RealtimeProvider({ children }: { children: ReactNode }) {
  const backend = useBackend();
  if (backend.previewRealtime) {
    return (
      <RealtimeContext.Provider value={backend.previewRealtime}>
        {children}
      </RealtimeContext.Provider>
    );
  }
  return <LiveRealtimeProvider>{children}</LiveRealtimeProvider>;
}

function LiveRealtimeProvider({ children }: { children: ReactNode }) {
  const backend = useBackend();
  const [status, setStatus] = useState<RealtimeStatus>('disconnected');
  const clientRef = useRef<Centrifuge | null>(null);
  const subsRef = useRef<Map<string, ManagedSub>>(new Map());
  const chatUserListeners = useRef<Set<(event: RealtimeEnvelope) => void>>(new Set());
  const letaUserListeners = useRef<Set<(event: RealtimeEnvelope) => void>>(new Set());

  const ensureSub = useCallback(
    (
      client: Centrifuge,
      channel: string,
      getToken: (() => Promise<string>) | undefined,
    ): ManagedSub => {
      const existing = subsRef.current.get(channel);
      if (existing) return existing;
      const listeners = new Set<SubscriptionListener>();
      const sub = client.newSubscription(channel, getToken ? { getToken } : {});
      sub.on('publication', (ctx) => {
        const envelope = parseEnvelope(ctx.data);
        if (!envelope) return;
        for (const l of listeners) l.onEvent(envelope);
      });
      sub.on('subscribed', (ctx) => {
        for (const l of listeners) l.onRecovered?.(Boolean(ctx.wasRecovering && ctx.recovered));
      });
      sub.subscribe();
      const managed: ManagedSub = { sub, listeners };
      subsRef.current.set(channel, managed);
      return managed;
    },
    [],
  );

  useEffect(() => {
    if (!backend.enabled || !backend.ready || !backend.actorId || !backend.api) {
      setStatus('disconnected');
      return;
    }
    const api = backend.api;
    const actorId = backend.actorId;
    setStatus('connecting');

    const client = new Centrifuge(websocketUrl(), {
      getToken: async () => {
        const res = await api<{ token: string }>('/v1/realtime:connectToken', {
          method: 'POST',
          body: '{}',
        });
        return res.token;
      },
      minReconnectDelay: 500,
      maxReconnectDelay: 15000,
    });
    clientRef.current = client;

    client.on('connected', () => setStatus('connected'));
    client.on('connecting', () =>
      setStatus((cur) => (cur === 'connected' ? 'reconnecting' : 'connecting')),
    );
    client.on('disconnected', () => setStatus('disconnected'));

    // Subscribe personal user-limited channels (#actorId enforced natively by Centrifugo v6).
    const chatPersonal = ensureSub(client, `chat:user#${actorId}`, undefined);
    const chatListener: SubscriptionListener = {
      onEvent: (env) => {
        for (const fn of chatUserListeners.current) fn(env);
      },
    };
    chatPersonal.listeners.add(chatListener);

    const letaPersonal = ensureSub(client, `leta:user#${actorId}`, undefined);
    const letaListener: SubscriptionListener = {
      onEvent: (env) => {
        for (const fn of letaUserListeners.current) fn(env);
      },
    };
    letaPersonal.listeners.add(letaListener);

    client.connect();

    return () => {
      chatPersonal.listeners.delete(chatListener);
      letaPersonal.listeners.delete(letaListener);
      for (const [, managed] of subsRef.current) {
        managed.sub.unsubscribe();
        client.removeSubscription(managed.sub);
      }
      subsRef.current.clear();
      client.disconnect();
      clientRef.current = null;
      setStatus('disconnected');
    };
  }, [backend.enabled, backend.ready, backend.actorId, backend.api, ensureSub]);

  const subscribe = useCallback(
    (
      channel: string,
      getToken: (() => Promise<string>) | undefined,
      listener: SubscriptionListener,
    ) => {
      const client = clientRef.current;
      if (!client) return () => {};
      const managed = ensureSub(client, channel, getToken);
      managed.listeners.add(listener);
      return () => {
        managed.listeners.delete(listener);
        if (managed.listeners.size === 0) {
          managed.sub.unsubscribe();
          client.removeSubscription(managed.sub);
          subsRef.current.delete(channel);
        }
      };
    },
    [ensureSub],
  );

  const onChatUserEvent = useCallback((handler: (event: RealtimeEnvelope) => void) => {
    chatUserListeners.current.add(handler);
    return () => {
      chatUserListeners.current.delete(handler);
    };
  }, []);

  const onLetaUserEvent = useCallback((handler: (event: RealtimeEnvelope) => void) => {
    letaUserListeners.current.add(handler);
    return () => {
      letaUserListeners.current.delete(handler);
    };
  }, []);

  const value = useMemo<RealtimeContextValue>(
    () => ({ status, subscribe, onChatUserEvent, onLetaUserEvent }),
    [status, subscribe, onChatUserEvent, onLetaUserEvent],
  );

  return <RealtimeContext.Provider value={value}>{children}</RealtimeContext.Provider>;
}

export function useRealtime() {
  return useContext(RealtimeContext);
}
