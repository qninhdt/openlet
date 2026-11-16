import { useMemo, useState, type CSSProperties } from 'react';
import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
  ThreadPrimitive,
  MessagePrimitive,
  useAuiState,
  type ThreadMessageLike,
} from '@assistant-ui/react';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { MessageScrollerContent, MessageScrollerItem } from '@/components/ui/message-scroller';
import { agentAppearance } from '@/components/agent-appearance';
import type { ActivityEntry } from '@/lib/agent-api';
import { useAgentPreview } from './agent-preview';
import { AgentMarkdown } from './agent-rich-content';
import { AgentMessageParts } from './agent-reasoning';
import { activityMessages } from '@/lib/agent-activity-messages';
import { InputItems, Compaction } from './agent-inputs';
import { MessageActions, ActivityComposer } from './message-actions';
import { Bubble, BubbleContent } from '@/components/ui/bubble';
import { transcriptStyles } from '@/components/ui/styles';
import { AgentMessageScroller } from './agent-scroll';

function ActivityText({ text }: { text: string }) {
  return (
    <Bubble variant="muted" className="max-w-full">
      <BubbleContent>
        <AgentMarkdown text={text} />
      </BubbleContent>
    </Bubble>
  );
}

function ActivityMessage() {
  const p = useAgentPreview();
  const message = useAuiState((s) => s.message);
  const id = message.id;
  const entryIds = message.metadata.custom.entryIds as string[];
  const entries = p.live.activity.data?.pages.flatMap((page) => page.items) ?? [];
  const entry = entries.find((item) => item.id === entryIds[0]);
  const client = useQueryClient();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  async function load(entry: ActivityEntry) {
    setLoading(true);
    setError('');
    try {
      const full = await p.live.api!<ActivityEntry>(
        `${p.live.path}/agents/${entry.agent_id}/activity/${entry.id}`,
      );
      client.setQueryData(
        [...p.live.scope, 'activity'],
        (old: { pages: { items: ActivityEntry[] }[] } | undefined) =>
          old
            ? {
                ...old,
                pages: old.pages.map((page) => ({
                  ...page,
                  items: page.items.map((item) => (item.id === entry.id ? full : item)),
                })),
              }
            : old,
      );
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Could not load details.');
    } finally {
      setLoading(false);
    }
  }
  const oversized = entries.filter((entry) => entryIds.includes(entry.id) && entry.has_details);
  return (
    <MessageScrollerItem messageId={id}>
      <MessagePrimitive.Root className="min-w-0">
        {entry?.kind === 'compaction' ? (
          <Compaction text={entry.payload.text ?? ''} />
        ) : entry?.kind === 'inbox_input' ? (
          <MessageActions own text={entry.payload.text ?? ''}>
            {entry.payload.ui?.items ? (
              <InputItems items={entry.payload.ui.items} />
            ) : (
              <p className="whitespace-pre-wrap text-sm">{entry.payload.text}</p>
            )}
          </MessageActions>
        ) : (
          <MessageActions
            wide
            text={entries
              .filter((item) => entryIds.includes(item.id))
              .map((item) => item.payload.text ?? item.payload.reasoning ?? '')
              .filter(Boolean)
              .join('\n\n')}
          >
            <div className="flex min-w-0 flex-col gap-2.5">
              <AgentMessageParts Text={ActivityText} />
            </div>
          </MessageActions>
        )}
        {error && (
          <p role="alert" className="my-2 text-sm text-destructive">
            {error}
          </p>
        )}
        {oversized.map((entry) => (
          <Button
            key={entry.id}
            size="sm"
            variant="outline"
            className="my-2"
            disabled={loading}
            onClick={() => void load(entry)}
          >
            {loading ? 'Loading…' : 'Load full details'}
          </Button>
        ))}
      </MessagePrimitive.Root>
    </MessageScrollerItem>
  );
}
const convertMessage = (message: ThreadMessageLike) => message;

export function LiveActivity() {
  const p = useAgentPreview();
  const entries = useMemo(
    () =>
      [...(p.live.activity.data?.pages.flatMap((page) => page.items) ?? [])].sort(
        (a, b) => a.seq - b.seq,
      ),
    [p.live.activity.data],
  );
  const messages = useMemo(
    () => activityMessages(entries, p.live.streaming),
    [entries, p.live.streaming],
  );
  const runtime = useExternalStoreRuntime({
    messages,
    convertMessage,
    isRunning: false,
    onNew: async () => {},
  });
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root
        aria-label="Agent activity timeline"
        style={
          {
            '--agent-color': agentAppearance(p.activityAgent.name, p.activityAgent.appearance)
              .background,
            '--agent-foreground': agentAppearance(p.activityAgent.name, p.activityAgent.appearance)
              .foreground,
          } as CSSProperties
        }
        className="flex h-full min-h-0 min-w-0 flex-col [--message-wide-bubble-width:min(100%,max(720px,70%),1200px)]"
      >
        {p.live.connection !== 'Live' && (
          <p role="status" className="px-4 py-2 text-xs text-muted-foreground">
            {p.live.connection}
          </p>
        )}
        <AgentMessageScroller positionKey={`${p.activityAgent.id}:activity`}>
          <MessageScrollerContent className={transcriptStyles}>
            {p.live.activity.error && (
              <p role="alert" className="text-sm text-destructive">
                {p.live.activity.error.message}
              </p>
            )}
            {p.live.activity.hasNextPage && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => void p.live.activity.fetchNextPage()}
              >
                Load earlier activity
              </Button>
            )}
            {p.live.activity.isPending && (
              <p role="status" className="py-8 text-sm text-muted-foreground">
                Loading activity…
              </p>
            )}
            {!entries.length && !p.live.activity.isPending && (
              <p className="py-12 text-center text-sm text-muted-foreground">
                The agent hasn’t started working yet.
              </p>
            )}
            <ThreadPrimitive.Messages components={{ Message: ActivityMessage }} />
          </MessageScrollerContent>
        </AgentMessageScroller>
        <ActivityComposer />
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}
