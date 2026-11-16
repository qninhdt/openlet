import { useEffect, useMemo, useRef, type CSSProperties, type PropsWithChildren } from 'react';
import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
  ThreadPrimitive,
  MessagePrimitive,
  ComposerPrimitive,
  ActionBarPrimitive,
  useAuiState,
  useAui,
  type ThreadMessageLike,
  type ToolCallMessagePartComponent,
} from '@assistant-ui/react';
import {
  ArrowUp,
  Check,
  ChevronRight,
  Copy,
  Paperclip,
  Plus,
  Reply,
  TriangleAlert,
  X,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { agentAppearance } from '@/components/agent-appearance';
import { Bubble, BubbleContent } from '@/components/ui/bubble';
import { Message, MessageContent } from '@/components/ui/message';
import {
  MessageScrollerProvider,
  MessageScroller,
  MessageScrollerViewport,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerButton,
} from '@/components/ui/message-scroller';
import { Marker, MarkerContent } from '@/components/ui/marker';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
} from '@/components/ui/dropdown-menu';
import { AgentFileCard, agentToolRenderers } from './agent-tools';
import { AgentMarkdown } from './agent-rich-content';
import { previewFiles, useAgentPreview } from './agent-preview';
import { demoAttachments, sampleMessages } from './agent-demo';

function ToolGroup({
  children,
  startIndex,
  endIndex,
}: PropsWithChildren<{ startIndex: number; endIndex: number }>) {
  const actionable = useAuiState((state) =>
    state.message.content
      .slice(startIndex, endIndex + 1)
      .some(
        (part) => part.type === 'tool-call' && ['hitl_ask', 'hitl_request'].includes(part.toolName),
      ),
  );
  const failed = useAuiState(
    (state) =>
      state.message.content
        .slice(startIndex, endIndex + 1)
        .filter((part) => part.type === 'tool-call' && part.isError).length,
  );
  if (actionable) return <>{children}</>;
  return (
    <Collapsible
      defaultOpen
      className="mb-1 grid w-full min-w-0 justify-items-start"
      data-slot="agent-tool-group"
    >
      <CollapsibleTrigger className="group/steps flex items-center gap-1.5 rounded-md py-1 text-caption text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">
        {failed ? (
          <TriangleAlert className="size-3.5 text-destructive" />
        ) : (
          <Check className="size-3.5" />
        )}
        <span>
          {endIndex - startIndex + 1} steps{failed ? ` · ${failed} failed` : ' completed'}
        </span>
        <ChevronRight className="size-3.5 transition-transform group-data-[state=open]/steps:rotate-90 motion-reduce:transition-none" />
      </CollapsibleTrigger>
      <CollapsibleContent className="ml-3 w-[calc(100%-12px)] min-w-0 border-l pt-3 pb-1.5 pl-3">
        {children}
      </CollapsibleContent>
    </Collapsible>
  );
}

function TextPart({ text }: { text: string }) {
  const p = useAgentPreview();
  const message = useAuiState((state) => state.message);
  const user = message.role === 'user';
  const local = p.session.messages.find((item) => item.id === message.id);
  const files = user
    ? (local?.files ?? [])
    : (demoAttachments[message.id] ?? []).flatMap((id) => {
        const file = previewFiles.find((item) => item.id === id);
        return file ? [file] : [];
      });
  return (
    <Bubble align={user ? 'end' : 'start'} variant={user ? 'agent' : 'muted'}>
      <BubbleContent className="flex flex-col gap-2">
        <AgentMarkdown text={text} />
        {!!files.length && (
          <div className="flex flex-wrap gap-2">
            {files.map((file) => (
              <AgentFileCard key={file.id} file={file} />
            ))}
          </div>
        )}
      </BubbleContent>
    </Bubble>
  );
}

function ConversationMessage() {
  const p = useAgentPreview();
  const message = useAuiState((state) => state.message);
  const user = message.role === 'user';
  const text = message.content
    .filter((part) => part.type === 'text')
    .map((part) => part.text)
    .join('\n');
  const local = p.session.messages.find((item) => item.id === message.id);
  return (
    <MessageScrollerItem messageId={message.id} scrollAnchor={user}>
      <MessagePrimitive.Root asChild>
        <Message align={user ? 'end' : 'start'}>
          <MessageContent>
            {local?.reply && (
              <blockquote className="max-w-[80%] border-l border-border pl-3 text-caption text-muted-foreground">
                {local.reply}
              </blockquote>
            )}
            <MessagePrimitive.Parts
              components={{
                Text: TextPart,
                tools: agentToolRenderers as {
                  by_name: Record<string, ToolCallMessagePartComponent>;
                  Fallback: ToolCallMessagePartComponent;
                },
                ToolGroup,
              }}
            />
            <ActionBarPrimitive.Root className="flex min-h-6 items-center gap-0.5 text-muted-foreground opacity-0 transition-opacity group-hover/message:opacity-100 group-focus-within/message:opacity-100 pointer-coarse:opacity-100">
              <ActionBarPrimitive.Copy asChild>
                <Button variant="ghost" size="icon-xs" aria-label="Copy message">
                  <Copy />
                </Button>
              </ActionBarPrimitive.Copy>
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label="Reply to message"
                onClick={() => p.updateSession({ reply: text })}
              >
                <Reply />
              </Button>
              <span className="ml-1 text-xs">
                {local ? 'Saved locally · no agent connected' : 'Sample conversation'}
              </span>
            </ActionBarPrimitive.Root>
          </MessageContent>
        </Message>
      </MessagePrimitive.Root>
    </MessageScrollerItem>
  );
}

function ConversationComposer() {
  const p = useAgentPreview();
  const aui = useAui();
  const text = useAuiState((state) => state.composer.text);
  const initialDraft = useRef(p.session.draft);
  const update = useRef(p.updateSession);
  useEffect(() => {
    update.current = p.updateSession;
  });
  useEffect(() => {
    aui.composer().setText(initialDraft.current);
  }, [aui]);
  useEffect(() => {
    update.current({ draft: text });
  }, [text]);
  return (
    <div className="mx-auto w-full max-w-[calc(clamp(1440px,65vw,1920px)+12px)] shrink-0 px-1.5 pt-1 pb-1.5">
      <ComposerPrimitive.Root className="flex flex-col overflow-hidden rounded-3xl border border-input bg-muted focus-within:border-ring">
        {p.session.reply && (
          <div className="mx-3 mt-3 flex items-start gap-2 rounded-xl border bg-sidebar p-3">
            <div className="min-w-0 flex-1">
              <p className="text-xs text-muted-foreground">Replying to a message</p>
              <p className="mt-1 line-clamp-2 text-caption">{p.session.reply}</p>
            </div>
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label="Cancel reply"
              onClick={() => p.updateSession({ reply: '' })}
            >
              <X />
            </Button>
          </div>
        )}
        {!!p.session.attachments.length && (
          <div className="flex gap-2 overflow-auto px-3 pt-3">
            {p.session.attachments.map((file) => (
              <div
                key={file.id}
                className="flex shrink-0 items-center gap-1 rounded-lg border px-2 py-1 text-caption"
              >
                <Paperclip className="size-3.5" />
                {file.name}
                <Button
                  variant="ghost"
                  size="icon-xs"
                  aria-label={`Remove ${file.name}`}
                  onClick={() =>
                    p.updateSession({
                      attachments: p.session.attachments.filter((item) => item.id !== file.id),
                    })
                  }
                >
                  <X />
                </Button>
              </div>
            ))}
          </div>
        )}
        <div className="flex min-h-12 items-end gap-1 p-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="secondary" size="icon-sm" aria-label="Attach file">
                <Plus />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" side="top">
              <DropdownMenuLabel>Sample files</DropdownMenuLabel>
              <DropdownMenuGroup>
                {previewFiles.map((file) => (
                  <DropdownMenuItem
                    key={file.id}
                    disabled={p.session.attachments.some((item) => item.id === file.id)}
                    onSelect={() => {
                      p.updateSession({ attachments: [...p.session.attachments, file] });
                      if (!aui.composer().getState().text)
                        aui.composer().setText(`Please review ${file.name}`);
                    }}
                  >
                    <Paperclip />
                    {file.name}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
          <ComposerPrimitive.Input
            aria-label={`Message ${p.profile.name}`}
            placeholder={`Message ${p.profile.name}…`}
            rows={1}
            maxRows={8}
            addAttachmentOnPaste={false}
            className="max-h-48 min-h-7 min-w-0 flex-1 resize-none bg-transparent px-1 py-1 text-sm leading-5 outline-none placeholder:text-muted-foreground"
          />
          <ComposerPrimitive.Send asChild>
            <Button size="icon-sm" aria-label="Send message" className="rounded-full">
              <ArrowUp />
            </Button>
          </ComposerPrimitive.Send>
        </div>
      </ComposerPrimitive.Root>
    </div>
  );
}

export function AgentConversation() {
  const p = useAgentPreview();
  const messages = useMemo<ThreadMessageLike[]>(
    () => [
      ...sampleMessages(p.fixture.id),
      ...p.session.messages.map((message) => ({
        id: message.id,
        role: 'user' as const,
        content: message.text,
      })),
    ],
    [p.fixture.id, p.session.messages],
  );
  const runtime = useExternalStoreRuntime({
    messages,
    convertMessage: (message) => message,
    isRunning: false,
    onNew: async (message) => {
      p.send(
        message.content
          .filter((part) => part.type === 'text')
          .map((part) => part.text)
          .join('\n'),
      );
    },
  });
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root
        aria-label={`${p.profile.name} conversation`}
        style={
          {
            '--agent-color': agentAppearance(p.fixture.name).background,
            '--agent-foreground': agentAppearance(p.fixture.name).foreground,
          } as CSSProperties
        }
        className="flex h-full min-h-0 min-w-0 flex-col [--message-wide-bubble-width:min(100%,max(720px,70%),1200px)]"
      >
        <MessageScrollerProvider autoScroll defaultScrollPosition="end">
          <MessageScroller className="min-h-0 flex-1">
            <MessageScrollerViewport>
              <MessageScrollerContent className="mx-auto min-h-full w-full max-w-[clamp(1440px,65vw,1920px)] gap-3 px-3 pt-2 pb-6">
                <MessageScrollerItem messageId="preview-label">
                  <Marker>
                    <MarkerContent>Today · UI preview</MarkerContent>
                  </Marker>
                </MessageScrollerItem>
                <ThreadPrimitive.Messages components={{ Message: ConversationMessage }} />
              </MessageScrollerContent>
            </MessageScrollerViewport>
            <MessageScrollerButton />
          </MessageScroller>
        </MessageScrollerProvider>
        <ConversationComposer />
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}
