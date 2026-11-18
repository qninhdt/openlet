import { useCallback, useEffect, useRef } from 'react';
import type { ChatMessage } from './agent-api.js';
type SoundMessage = Pick<ChatMessage, 'id' | 'role' | 'created_at' | 'read_at'>;

export function newAssistantMessages(
  previous: SoundMessage[] | undefined,
  current: SoundMessage[],
) {
  if (!previous) return [];
  const seen = new Set(previous.map((message) => message.id));
  const latest = previous.length
    ? Math.max(...previous.map((message) => Date.parse(message.created_at)))
    : -Infinity;
  return current.filter(
    (message) =>
      message.role === 'assistant' &&
      !seen.has(message.id) &&
      Date.parse(message.created_at) >= latest,
  );
}

export function messageSent(scope: string, id: string) {
  window.dispatchEvent(new CustomEvent('openlet:message-sent', { detail: { scope, id } }));
}

export function useMessageSound(
  scope: string,
  messages: SoundMessage[] | undefined,
  enabled: boolean,
) {
  const previous = useRef<{ scope: string; messages?: SoundMessage[] }>({ scope });
  const audio = useRef<AudioContext | null>(null);
  useEffect(() => {
    if (!enabled) return;
    const activate = () => {
      audio.current ??= new AudioContext();
      void audio.current.resume().catch(() => {});
    };
    document.addEventListener('pointerdown', activate);
    document.addEventListener('keydown', activate);
    return () => {
      document.removeEventListener('pointerdown', activate);
      document.removeEventListener('keydown', activate);
      void audio.current?.close().catch(() => {});
      audio.current = null;
    };
  }, [enabled]);
  const play = useCallback(
    (messageIds: string[], sent = false) => {
      const context = audio.current;
      if (!enabled || !messageIds.length || context?.state !== 'running') return;
      const perform = () => {
        const key = `openlet-message-sounds:${scope.split(':')[0]}`;
        try {
          const seen = JSON.parse(localStorage.getItem(key) ?? '[]') as string[];
          const ids = messageIds.map((id) => `${scope}:${sent ? 'sent:' : ''}${id}`);
          if (ids.every((id) => seen.includes(id))) return;
          localStorage.setItem(key, JSON.stringify([...seen, ...ids].slice(-200)));
        } catch {
          /* Sound still works when browser storage is unavailable. */
        }
        if (context.state !== 'running') return;
        const oscillator = context.createOscillator();
        const gain = context.createGain();
        oscillator.connect(gain);
        gain.connect(context.destination);
        const now = context.currentTime;
        oscillator.frequency.setValueAtTime(660, now);
        oscillator.frequency.setValueAtTime(sent ? 550 : 880, now + 0.08);
        gain.gain.setValueAtTime(0, now);
        gain.gain.linearRampToValueAtTime(0.055, now + 0.012);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.23);
        oscillator.start(now);
        oscillator.stop(now + 0.24);
        oscillator.onended = () => {
          oscillator.disconnect();
          gain.disconnect();
        };
      };
      if (navigator.locks)
        void navigator.locks.request('openlet-message-sound', perform).catch(() => {});
      else perform();
    },
    [scope, enabled],
  );
  useEffect(() => {
    const sent = (event: Event) => {
      const { scope: target, id } = (event as CustomEvent<{ scope: string; id: string }>).detail;
      if (target === scope) play([id], true);
    };
    window.addEventListener('openlet:message-sent', sent);
    return () => window.removeEventListener('openlet:message-sent', sent);
  }, [scope, play]);
  useEffect(() => {
    if (!messages) return;
    const fresh =
      previous.current.scope === scope
        ? newAssistantMessages(previous.current.messages, messages)
        : [];
    previous.current = { scope, messages };
    play(fresh.map((message) => message.id));
  }, [scope, messages, play]);
}
