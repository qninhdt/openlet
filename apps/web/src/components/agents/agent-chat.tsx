import { fileText } from '@/lib/file-refs';
import { AgentMessageScroller } from './agent-scroll';
import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
  ThreadPrimitive,
  MessagePrimitive,
  useAuiState,
  type ThreadMessageLike,
} from '@assistant-ui/react';
import { Upload, RotateCcw, MessageCircleQuestion, ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Bubble, BubbleContent } from '@/components/ui/bubble';
import { Message, MessageContent } from '@/components/ui/message';
import { MessageScrollerContent, MessageScrollerItem } from '@/components/ui/message-scroller';
import { agentAppearance } from '@/components/agent-appearance';
import { messageKey } from '@/lib/agent-api';
import { AgentMarkdown } from './agent-rich-content';
import { previewFiles, useAgentPreview } from './agent-preview';
import { AgentFileCard } from './agent-tools';
import { ConversationComposer } from './agent-conversation';
import { MessageActions } from './message-actions';
import { MessageReactions } from './message-reactions';
import { cn } from '@/lib/utils';
import { transcriptStyles } from '@/components/ui/styles';

function ChatBubble() {
  const p = useAgentPreview();
  const id = useAuiState((s) => s.message.id);
  const message = p.chatMessages.find((m) => messageKey(m) === id)!;
  const user = message.role === 'user';
  return (
    <MessageScrollerItem messageId={id} scrollAnchor={user}>
      <MessagePrimitive.Root asChild>
        <Message align={user ? 'end' : 'start'}>
          <MessageContent>
            <MessageActions
              own={user}
              text={message.content}
              title={new Date(message.created_at).toLocaleString()}
              reaction={
                !message.status
                  ? {
                      emoji:
                        message.reactions?.find(
                          (r) => r.actor_kind === 'user' && r.actor_id === p.actorId,
                        )?.emoji ?? null,
                      onReact: (emoji) => void p.reactMessage(message, emoji),
                    }
                  : undefined
              }
              onReply={() =>
                p.updateSession({
                  reply: {
                    id: message.id,
                    role: message.role,
                    content: fileText(message.content).slice(0, 240),
                  },
                })
              }
            >
              <Bubble
                align={user ? 'end' : 'start'}
                variant={user ? 'agent' : 'muted'}
                className={cn(!!message.reactions?.length && 'mb-6')}
              >
                <BubbleContent className="flex flex-col gap-2">
                  {message.reply && (
                    <button
                      type="button"
                      className="min-w-0 rounded-lg bg-foreground/5 px-3 py-2 text-left text-caption"
                      onClick={() => {
                        const target = document.getElementById(
                          `chat-${message.reply!.role}-${message.reply!.id}`,
                        );
                        if (target) target.scrollIntoView({ block: 'center', behavior: 'smooth' });
                        else if (p.live.chat.hasNextPage) void p.live.chat.fetchNextPage();
                      }}
                    >
                      <span className="block font-medium">
                        {message.reply.role === 'user' ? 'You' : p.profile.name}
                      </span>
                      <span className="line-clamp-2">{fileText(message.reply.content)}</span>
                    </button>
                  )}
                  <div id={`chat-${message.role}-${message.id}`}>
                    <AgentMarkdown text={message.content} />
                  </div>
                  {message.file_ids?.map((id) => {
                    const file = previewFiles.find((f) => f.id === id);
                    return file ? <AgentFileCard key={id} file={file} /> : null;
                  })}
                </BubbleContent>
                <MessageReactions
                  reactions={message.reactions}
                  actorId={p.actorId}
                  own={user}
                  onReact={(emoji) => void p.reactMessage(message, emoji)}
                />
              </Bubble>
            </MessageActions>
            {message.status === 'failed' ? (
              <div
                role="alert"
                className="flex items-center justify-end gap-2 text-caption text-destructive"
              >
                Not sent
                <Button variant="ghost" size="sm" onClick={() => void p.retryMessage(message)}>
                  <RotateCcw />
                  Retry
                </Button>
              </div>
            ) : message.status === 'sending' ? (
              <span role="status" className="self-end text-xs text-muted-foreground">
                Sending…
              </span>
            ) : null}
          </MessageContent>
        </Message>
      </MessagePrimitive.Root>
    </MessageScrollerItem>
  );
}
const convertMessage = (message: ThreadMessageLike) => message;

export function AgentChat() {
  const [dropping, setDropping] = useState(false);
  const p = useAgentPreview();
  const lastDelivery = p.chatMessages.findLast((message) => message.role === 'assistant');
  useEffect(() => {
    const read = () => {
      if (
        p.session.mainTab === 'agent' &&
        document.visibilityState === 'visible' &&
        document.hasFocus() &&
        lastDelivery
      )
        void p.markChatRead(lastDelivery.id);
    };
    read();
    window.addEventListener('focus', read);
    document.addEventListener('visibilitychange', read);
    return () => {
      window.removeEventListener('focus', read);
      document.removeEventListener('visibilitychange', read);
    };
  }, [lastDelivery?.id, p.markChatRead, p.session.mainTab]);
  const messages = useMemo<ThreadMessageLike[]>(
    () => p.chatMessages.map((m) => ({ id: messageKey(m), role: m.role, content: m.content })),
    [p.chatMessages],
  );
  const runtime = useExternalStoreRuntime({
    messages,
    convertMessage,
    isRunning: false,
    onNew: async (message) => {
      await p.send(
        message.content
          .filter((c) => c.type === 'text')
          .map((c) => c.text)
          .join('\n'),
      );
    },
  });
  const error = p.live.profile.error ?? p.live.chat.error;
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root
        aria-label={`${p.profile.name} private chat`}
        onDragOverCapture={(event) => {
          if (event.dataTransfer.types.includes('Files')) {
            event.preventDefault();
            event.dataTransfer.dropEffect = 'copy';
            setDropping(true);
          }
        }}
        onDragLeave={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node)) setDropping(false);
        }}
        onDropCapture={(event) => {
          const files = Array.from(event.dataTransfer.files);
          if (!files.length) return;
          event.preventDefault();
          event.stopPropagation();
          setDropping(false);
          for (const file of files) void p.queueUpload(file);
        }}
        style={
          {
            '--agent-color': agentAppearance(p.profile.name, p.profile.appearance).background,
            '--agent-foreground': agentAppearance(p.profile.name, p.profile.appearance).foreground,
          } as CSSProperties
        }
        className="relative flex h-full min-h-0 min-w-0 flex-col"
      >
        {dropping && (
          <div className="pointer-events-none absolute inset-2 z-40 flex flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed border-ring bg-background/95 text-sm">
            <Upload className="size-8 text-muted-foreground" />
            Drop files to attach
          </div>
        )}
        {p.live.enabled && p.live.connection !== 'Live' && (
          <p role="status" className="px-4 py-2 text-xs text-muted-foreground">
            {p.live.connection}
          </p>
        )}
        {error && (
          <p role="alert" className="px-4 py-2 text-sm text-destructive">
            {error.message}
          </p>
        )}
        <AgentMessageScroller positionKey={`${p.fixture.id}:chat`}>
          <MessageScrollerContent className={transcriptStyles}>
            {p.live.enabled && p.live.chat.hasNextPage && (
              <Button
                variant="ghost"
                size="sm"
                disabled={p.live.chat.isFetchingNextPage}
                onClick={() => void p.live.chat.fetchNextPage()}
              >
                Load earlier messages
              </Button>
            )}
            {p.live.enabled && p.live.profile.data?.state === 'provisioning' && (
              <p role="status" className="py-8 text-center text-sm text-muted-foreground">
                Preparing agent…
              </p>
            )}
            {p.live.enabled && p.live.chat.isPending && (
              <p role="status" className="py-8 text-center text-sm text-muted-foreground">
                Loading conversation…
              </p>
            )}
            {!p.chatMessages.length && !p.live.chat.isPending && (
              <p className="py-12 text-center text-sm text-muted-foreground">
                Start a conversation with {p.profile.name}.
              </p>
            )}
            <ThreadPrimitive.Messages components={{ Message: ChatBubble }} />
            {p.requests.map((request) => (
              <MessageScrollerItem key={request.id} messageId={`request:${request.id}`}>
                <button
                  type="button"
                  className="mx-auto flex max-w-full items-center gap-2 rounded-lg px-3 py-2 text-caption text-muted-foreground hover:bg-muted hover:text-foreground"
                  onClick={() => p.updateSession({ requestOpen: request.id })}
                >
                  {request.type === 'ask' ? (
                    <MessageCircleQuestion className="size-3.5 shrink-0" />
                  ) : (
                    <ShieldCheck className="size-3.5 shrink-0" />
                  )}
                  <span className="truncate">{request.title}</span>
                  <span className="shrink-0">
                    · {request.status === 'pending' ? 'Waiting for you' : request.status}
                  </span>
                </button>
              </MessageScrollerItem>
            ))}
          </MessageScrollerContent>
        </AgentMessageScroller>
        {p.capabilities.can_chat && <ConversationComposer />}
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}
