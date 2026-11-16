import { fileText } from '@/lib/file-refs';
import { useMemo, useRef, useState, type CSSProperties } from 'react';
import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
  ThreadPrimitive,
  MessagePrimitive,
  useAuiState,
  type ThreadMessageLike,
} from '@assistant-ui/react';
import { ArrowUp, Plus, X, Upload, HardDrive } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { agentAppearance } from '@/components/agent-appearance';
import { Bubble, BubbleContent } from '@/components/ui/bubble';
import { Message, MessageContent } from '@/components/ui/message';
import { MessageScrollerContent, MessageScrollerItem } from '@/components/ui/message-scroller';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from '@/components/ui/dropdown-menu';
import { AgentFileCard } from './agent-tools';
import { AgentMarkdown } from './agent-rich-content';
import { AgentMessageParts } from './agent-reasoning';
import { previewFiles, useAgentPreview } from './agent-preview';
import { ComposerEditor } from './composer-editor';
import { FilePicker } from './file-picker';
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
  AlertDialogAction,
} from '@/components/ui/alert-dialog';
import { PendingRequests } from './agent-requests';
import { LiveActivity } from './agent-activity';
import { AgentMessageScroller } from './agent-scroll';
import { InputItems, Compaction } from './agent-inputs';
import { MessageActions, MessageMenu, ActivityComposer } from './message-actions';
import {
  demoActivityInputs,
  demoAttachments,
  sampleMessages,
  letiMessages,
  letiInputs,
} from './agent-demo';
import { transcriptStyles } from '@/components/ui/styles';

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
    <MessageActions
      own={user}
      context={false}
      text={text}
      onReply={() =>
        p.updateSession({
          reply: { id: message.id, role: user ? 'user' : 'assistant', content: text.slice(0, 240) },
          mainTab: 'agent',
        })
      }
    >
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
    </MessageActions>
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
  const inputs =
    local?.inputs ??
    (p.activityAgent.box_id
      ? letiInputs(
          p.activityAgent.id,
          p.activityContact?.name ?? p.profile.name,
          p.activityPeer?.name,
        )
      : demoActivityInputs(p.fixture.id))[message.id] ??
    (user
      ? [{ id: message.id, source_kind: 'user', source_name: 'You', content: text }]
      : undefined);
  if (inputs)
    return (
      <MessageScrollerItem messageId={message.id}>
        <MessageActions text={inputs.map((item) => item.content).join('\n\n')} own>
          <InputItems items={inputs} />
        </MessageActions>
      </MessageScrollerItem>
    );
  if (message.id === `${p.activityAgent.id}-compaction`)
    return (
      <MessageScrollerItem messageId={message.id}>
        <Compaction text={text} />
      </MessageScrollerItem>
    );
  return (
    <MessageScrollerItem messageId={message.id} scrollAnchor={user}>
      <MessageMenu
        text={text}
        onReply={() =>
          p.updateSession({
            reply: {
              id: message.id,
              role: user ? 'user' : 'assistant',
              content: text.slice(0, 240),
            },
            mainTab: 'agent',
          })
        }
      >
        <MessagePrimitive.Root asChild>
          <Message align={user ? 'end' : 'start'}>
            <MessageContent>
              {local?.reply && (
                <blockquote className="max-w-[80%] border-l border-border pl-3 text-caption text-muted-foreground">
                  {fileText(local.reply.content)}
                </blockquote>
              )}
              <AgentMessageParts Text={TextPart} />
            </MessageContent>
          </Message>
        </MessagePrimitive.Root>
      </MessageMenu>
    </MessageScrollerItem>
  );
}

export function ConversationComposer() {
  const p = useAgentPreview();
  const fileInput = useRef<HTMLInputElement>(null);
  const [picker, setPicker] = useState(false);
  const [empty, setEmpty] = useState(true);
  return (
    <div className="mx-auto w-full max-w-[calc(clamp(1440px,65vw,1920px)+12px)] shrink-0 px-1.5 pt-1 pb-1.5">
      <div
        data-slot="conversation-composer"
        className="relative flex flex-col rounded-3xl border border-input bg-muted focus-within:border-ring data-drop:border-ring data-drop:outline-2 data-drop:outline-ring"
      >
        <PendingRequests />
        {p.session.reply && (
          <div className="mx-3 mt-3 flex items-start gap-2 rounded-xl border bg-sidebar p-3">
            <div className="min-w-0 flex-1">
              <p className="text-xs text-muted-foreground">Replying to a message</p>
              <p className="mt-1 line-clamp-2 text-caption">{fileText(p.session.reply.content)}</p>
            </div>
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label="Cancel reply"
              onClick={() => p.updateSession({ reply: null })}
            >
              <X />
            </Button>
          </div>
        )}
        <div className="flex min-h-12 items-end gap-1 p-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label="Attach file">
                <Plus />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" side="top">
              <DropdownMenuItem onSelect={() => fileInput.current?.click()}>
                <Upload />
                Upload file
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setPicker(true)}>
                <HardDrive />
                Choose from storage
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <input
            ref={fileInput}
            type="file"
            multiple
            hidden
            aria-label="Attach files"
            onChange={(event) => {
              for (const file of Array.from(event.target.files ?? [])) void p.queueUpload(file);
              event.target.value = '';
            }}
          />
          <ComposerEditor onEmptyChange={setEmpty} />
          <Button
            disabled={!!p.session.uploads.length || empty}
            onClick={() => p.composers.get(p.fixture.id)?.submit()}
            size="icon-sm"
            aria-label="Send message"
            className="rounded-full"
          >
            <ArrowUp />
          </Button>
        </div>
      </div>
      <FilePicker
        open={picker}
        onClose={() => setPicker(false)}
        onSelect={(node) => {
          void p.attachFile(node);
          setPicker(false);
        }}
      />
      <AlertDialog open={!!p.copyRequest} onOpenChange={(open) => !open && p.setCopyRequest(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Send a copy?</AlertDialogTitle>
            <AlertDialogDescription>
              {p.profile.name} cannot read this file. Copy it to your conversation storage so both
              of you can edit it.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => void p.attachFile(p.copyRequest!, true)}>
              Send a copy
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

const convertMessage = (message: ThreadMessageLike) => message;

export function AgentActivity() {
  const p = useAgentPreview();
  return p.live.enabled ? <LiveActivity /> : <PreviewActivity />;
}

function PreviewActivity() {
  const p = useAgentPreview();
  const messages = useMemo<ThreadMessageLike[]>(
    () => [
      ...(p.activityAgent.box_id
        ? letiMessages(
            p.activityAgent.id,
            p.activityContact?.id === p.fixture.id ? 'root' : p.activityContact?.name,
          )
        : sampleMessages(p.fixture.id)),
      ...(p.activityAgent.box_id ? [] : p.session.messages).map((m) => ({
        id: m.id,
        role: 'user' as const,
        content: m.text || ' ',
      })),
    ],
    [
      p.fixture.id,
      p.activityAgent.id,
      p.activityAgent.box_id,
      p.activityContact,
      p.session.messages,
    ],
  );
  const runtime = useExternalStoreRuntime({
    messages,
    convertMessage,
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
        aria-label={`${p.activityAgent.name} conversation`}
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
        <AgentMessageScroller positionKey={`${p.activityAgent.id}:activity`}>
          <MessageScrollerContent className={transcriptStyles}>
            <ThreadPrimitive.Messages components={{ Message: ConversationMessage }} />
          </MessageScrollerContent>
        </AgentMessageScroller>
        <ActivityComposer />
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}
