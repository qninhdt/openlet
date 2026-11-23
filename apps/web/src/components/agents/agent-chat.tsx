import { fileText } from '@/lib/file-refs';
import { AgentMessageScroller } from './agent-scroll';
import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
  ThreadPrimitive,
  MessagePrimitive,
  useAuiState,
  type ThreadMessageLike,
} from '@assistant-ui/react';
import { Upload, RotateCcw, Check, CheckCheck } from 'lucide-react';
import { AgentAvatar } from '@/components/agent-avatar';
import { Button } from '@/components/ui/button';
import { Bubble, BubbleContent } from '@/components/ui/bubble';
import { Message, MessageContent } from '@/components/ui/message';
import { MessageScrollerContent, MessageScrollerItem } from '@/components/ui/message-scroller';
import { agentAppearance } from '@/components/agent-appearance';
import { messageKey } from '@/lib/agent-api';
import { AgentMarkdown } from './agent-rich-content';
import { useAgentPreview } from './agent-preview';
import { ConversationComposer } from './agent-conversation';
import { MessageActions } from './message-actions';
import { MessageReactions } from './message-reactions';
import { cn } from '@/lib/utils';
import { transcriptStyles } from '@/components/ui/styles';
import { MessageFiles } from './message-files';

function ChatBubble() {
  const p = useAgentPreview();
  const id = useAuiState((s) => s.message.id);
  const index = p.chatMessages.findIndex((m) => messageKey(m) === id);
  const message = p.chatMessages[index];
  // The external runtime can render an evicted row until it reconciles a refreshed page.
  if (!message) return null;
  const user = message.role === 'user';
  const grouped =
    !!message.message_group_id &&
    p.chatMessages[index - 1]?.message_group_id === message.message_group_id;
  const lastMessage = p.chatMessages.at(-1);
  const latestMessage = p.live.chat.data?.pages[0]?.items[0];
  const showReceipt =
    user &&
    message === lastMessage &&
    (!p.linkedMessage || (latestMessage?.role === message.role && latestMessage.id === message.id));
  return (
    <MessageScrollerItem messageId={id} className={grouped ? '-mt-2' : undefined}>
      <MessagePrimitive.Root asChild>
        <Message align={user ? 'end' : 'start'}>
          <MessageContent className="gap-0.5">
            <MessageActions
              own={user}
              text={message.content}
              title={new Date(message.created_at).toLocaleString()}
              link={
                !message.status
                  ? `${window.location.origin}/app/${p.workspace.id}/agents/${p.resource.id}?${new URLSearchParams({ message: message.id, role: message.role })}`
                  : undefined
              }
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
              <div
                id={`chat-${message.role}-${message.id}`}
                className={cn(
                  'relative flex min-w-0 max-w-full flex-col gap-1 rounded-lg transition-shadow data-[linked=true]:ring-2 data-[linked=true]:ring-ring data-[linked=true]:ring-offset-4 data-[linked=true]:ring-offset-background',
                  user && 'items-end',
                  !!message.reactions?.length && !showReceipt && 'mb-6',
                )}
              >
                {(message.content || message.reply) && (
                  <Bubble
                    align={user ? 'end' : 'start'}
                    variant={user ? 'agent' : 'muted'}
                    className="max-w-full"
                  >
                    <BubbleContent className="flex flex-col gap-2">
                      {message.reply && (
                        <button
                          type="button"
                          className="min-w-0 rounded-lg bg-foreground/5 px-3 py-2 text-left text-caption"
                          onClick={() => {
                            void p.jumpToMessage(message.reply!);
                          }}
                        >
                          <span className="block font-medium">
                            {message.reply.role === 'user' ? 'You' : p.profile.name}
                          </span>
                          <span className="line-clamp-2">{fileText(message.reply.content)}</span>
                        </button>
                      )}
                      {message.content && (
                        <AgentMarkdown text={message.content} sources={message.sources} />
                      )}
                    </BubbleContent>
                  </Bubble>
                )}
                <MessageFiles references={message.file_refs} />
                <MessageReactions
                  reactions={message.reactions}
                  actorId={p.actorId}
                  own={user}
                  onReact={(emoji) => void p.reactMessage(message, emoji)}
                />
              </div>
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
            ) : showReceipt ? (
              <span
                className="mr-2 self-end text-xs text-muted-foreground"
                title={
                  message.read_at
                    ? `Read ${new Date(message.read_at).toLocaleString()}`
                    : 'Delivered to inbox'
                }
                aria-label={message.read_at ? 'Read by agent' : 'Delivered'}
              >
                {message.read_at ? (
                  <CheckCheck className="size-3.5" />
                ) : (
                  <Check className="size-3.5" />
                )}
              </span>
            ) : null}
          </MessageContent>
        </Message>
      </MessagePrimitive.Root>
    </MessageScrollerItem>
  );
}
const convertMessage = (message: ThreadMessageLike) => message;

function EarlierMessages() {
  const { live } = useAgentPreview();
  const { hasNextPage, isFetching, isFetchingNextPage, isFetchNextPageError, fetchNextPage } =
    live.chat;
  const marker = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = marker.current;
    if (!element || !hasNextPage || isFetching || isFetchNextPageError) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) void fetchNextPage({ cancelRefetch: false });
      },
      {
        root: element.closest('[data-slot="message-scroller-viewport"]'),
        rootMargin: '96px 0px 0px',
      },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [hasNextPage, isFetching, isFetchNextPageError, fetchNextPage]);
  if (!hasNextPage) return null;
  return (
    <div ref={marker} className="min-h-px">
      {isFetchingNextPage && (
        <span role="status" className="sr-only">
          Loading earlier messages
        </span>
      )}
      {isFetchNextPageError && (
        <p className="text-center text-xs text-muted-foreground">
          Could not load earlier messages.
        </p>
      )}
    </div>
  );
}

export function AgentChat() {
  const [dropping, setDropping] = useState(false);
  const p = useAgentPreview();
  useEffect(() => {
    if (!p.linkedMessage || !p.messageContext.data) return;
    let target: HTMLElement | null = null;
    const frame = requestAnimationFrame(() => {
      target = document.getElementById(`chat-${p.linkedRole}-${p.linkedMessage}`);
      target?.scrollIntoView({ block: 'center' });
      if (target) target.dataset.linked = 'true';
    });
    const timer = setTimeout(() => {
      if (target) delete target.dataset.linked;
    }, 3000);
    return () => {
      cancelAnimationFrame(frame);
      clearTimeout(timer);
      if (target) delete target.dataset.linked;
    };
  }, [p.linkedMessage, p.linkedRole, p.messageContext.data]);
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
    isRunning: !!p.live.processing.data?.working,
    onNew: async (message) => {
      await p.send(
        message.content
          .filter((c) => c.type === 'text')
          .map((c) => c.text)
          .join('\n'),
      );
    },
  });
  const error = p.live.profile.error ?? p.live.chat.error ?? p.messageContext.error;
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
        {p.linkedMessage && (
          <div className="px-3 py-1">
            <Button variant="ghost" size="sm" onClick={() => void p.jumpToMessage(null)}>
              Return to latest messages
            </Button>
          </div>
        )}
        <AgentMessageScroller positionKey={`${p.resource.id}:chat:${p.linkedMessage ?? ''}`}>
          <MessageScrollerContent className={cn(transcriptStyles, 'gap-2')}>
            {!p.linkedMessage && p.live.enabled && <EarlierMessages />}
            {p.linkedMessage && p.messageContext.isPending && (
              <p role="status" className="py-6 text-center text-sm text-muted-foreground">
                Loading message context…
              </p>
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
            {p.live.processing.data?.working && (
              <div role="status" className="pointer-events-none flex items-center pt-3 pb-2 pl-2">
                <span className="sr-only">{p.profile.name} is thinking…</span>
                <span className="relative inline-flex" style={{ color: 'var(--agent-color)' }}>
                  <span className="agent-thinking-dots" aria-hidden="true">
                    <i />
                    <i />
                    <i />
                  </span>
                  <AgentAvatar
                    name={p.profile.name}
                    appearance={p.profile.appearance}
                    working
                    className="size-8"
                  />
                </span>
              </div>
            )}
          </MessageScrollerContent>
        </AgentMessageScroller>
        {p.capabilities.can_chat && <ConversationComposer />}
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}
