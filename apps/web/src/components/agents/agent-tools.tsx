import type { ToolCallMessagePartComponent, ToolCallMessagePartProps } from '@assistant-ui/react';
import {
  ArrowRight,
  CalendarClock,
  Check,
  Clock3,
  FileCheck2,
  FilePenLine,
  FileSearch,
  FileText,
  Folder,
  Globe2,
  History,
  Inbox,
  LoaderCircle,
  MessageSquare,
  Network,
  Pause,
  Search,
  Send,
  ShieldCheck,
  Terminal,
  Trash2,
  TriangleAlert,
  Users,
  X,
} from 'lucide-react';
import type { ReactNode } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { AgentAvatar } from '@/components/agent-avatar';
import { FileIcon } from '@/components/storage/file-icon';
import { cn } from '@/lib/utils';
import { AccessRequestCard, AskCard } from './agent-hitl';
import { MessagePreview } from './message-preview';
import { MessageFiles } from './message-files';
import { AgentMarkdown, HighlightedCode } from './agent-rich-content';
import { useAgentPreview } from './agent-preview';
import { InputItems } from './agent-inputs';
import { ActivityIdentity } from './activity-identity';
import type { ToolResult } from '@/lib/agent-presentation';
import type { FileRef } from '@/lib/file-refs';

function resultOf(props: ToolCallMessagePartProps): ToolResult {
  return (props.result ?? {}) as ToolResult;
}

function ToolStep({
  props,
  label,
  icon,
  children,
  wide = false,
}: {
  props: ToolCallMessagePartProps;
  label: string;
  icon: ReactNode;
  children?: ReactNode;
  wide?: boolean;
}) {
  const error = props.isError || props.status.type === 'incomplete';
  return (
    <div
      className="grid w-full min-w-0 justify-items-start"
      data-tool={props.toolName}
      data-tool-call={props.toolCallId}
    >
      <div
        className={cn(
          'flex w-fit max-w-full min-w-0 items-center gap-2 py-1.5 text-caption text-muted-foreground [&>svg]:size-3.5 [&>svg]:shrink-0',
          error && 'text-destructive',
        )}
      >
        {error ? <TriangleAlert /> : icon}
        <span className="min-w-0 flex-1 truncate">{label}</span>
        {props.status.type === 'running' ? (
          <LoaderCircle className="animate-spin motion-reduce:animate-none" />
        ) : (
          !error && props.result !== undefined && <Check />
        )}
      </div>
      {children != null && (
        <div
          className={cn(
            'max-w-full min-w-0 pt-3 pb-3 pl-5.5',
            wide ? 'w-(--message-wide-bubble-width)' : 'w-fit',
          )}
        >
          {children}
        </div>
      )}
    </div>
  );
}

// OpenBot action cards fit their content, with a 520px ceiling; code artifacts use the wide message width.
function ActionCard({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      data-slot="agent-action-card"
      className={cn(
        'w-fit max-w-[min(100%,520px)] min-w-[min(100%,320px)] overflow-hidden rounded-xl border text-sm wrap-anywhere',
        className,
      )}
    >
      {children}
    </div>
  );
}
function Status({ children }: { children?: string }) {
  if (!children) return null;
  return <Badge variant={children === 'Failed' ? 'destructive' : 'secondary'}>{children}</Badge>;
}
function FileLink({ file, children }: { file: FileRef; children?: ReactNode }) {
  const p = useAgentPreview();
  return (
    <Button
      variant="ghost"
      size="xs"
      className="h-auto min-w-0 max-w-full justify-start px-0 text-left whitespace-normal"
      onClick={() => void p.openFileReference(file)}
      aria-label={`Inspect ${file.label}`}
    >
      <FileText />
      <span className="min-w-0 wrap-anywhere">{children ?? file.label}</span>
    </Button>
  );
}
function EmptyResult({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <div className="flex items-start gap-3 py-3 text-sm text-muted-foreground [&>svg]:mt-0.5 [&>svg]:size-4 [&>svg]:shrink-0">
      {icon}
      <p>{children}</p>
    </div>
  );
}

const FileListTool: ToolCallMessagePartComponent = (props) => {
  const result = resultOf(props);
  return (
    <ToolStep props={props} label={`Listed ${String(props.args.path ?? '~')}`} icon={<Folder />}>
      <ActionCard>
        <div className="flex flex-wrap items-center justify-between gap-2 border-b bg-muted/40 px-3 py-2 text-caption text-muted-foreground">
          <span className="font-mono">{String(props.args.path ?? '~')}</span>
          <span>{result.summary}</span>
        </div>
        <ul className="divide-y">
          {result.items?.map((item) => (
            <li key={item.title} className="flex min-w-0 items-center gap-3 px-3 py-2">
              {item.file ? (
                <FileLink file={item.file} />
              ) : (
                <span className="flex min-w-0 items-center gap-2 text-caption font-medium">
                  <FileIcon node={{ kind: item.kind ?? 'folder', mime: '', name: item.title }} />
                  {item.title}
                </span>
              )}
              <span className="ml-auto shrink-0 text-xs text-muted-foreground tabular-nums">
                {item.meta}
              </span>
            </li>
          ))}
        </ul>
        {!result.items?.length && (
          <div className="px-3">
            <EmptyResult icon={<Folder />}>This directory is empty.</EmptyResult>
          </div>
        )}
      </ActionCard>
    </ToolStep>
  );
};
const FileReadTool: ToolCallMessagePartComponent = (props) => {
  const result = resultOf(props);
  return (
    <ToolStep
      props={props}
      label={`Read ${String(props.args.path ?? '')}`}
      icon={<FileText />}
      wide
    >
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        {result.file && <FileLink file={result.file} />}
        <span>Read snapshot · {result.lineRange}</span>
      </div>
      <HighlightedCode language={'text'} code={result.content ?? result.output ?? ''} />
    </ToolStep>
  );
};
const FileWriteTool: ToolCallMessagePartComponent = (props) => {
  const result = resultOf(props);
  return (
    <ToolStep props={props} label={`Wrote ${String(props.args.path ?? '')}`} icon={<FileCheck2 />}>
      <div className="flex max-w-full flex-col items-start gap-2">
        {result.file ? (
          <div className="rounded-lg border px-3 py-2">
            <FileLink file={result.file} />
          </div>
        ) : (
          <p className="rounded-lg border px-3 py-2 font-mono text-caption">
            {String(props.args.path ?? '')}
          </p>
        )}
      </div>
    </ToolStep>
  );
};
const FileEditTool: ToolCallMessagePartComponent = (props) => {
  const result = resultOf(props);
  const before = String(props.args.old_text ?? '');
  const after = String(props.args.new_text ?? '');
  const code = [
    ...before.split('\n').map((line) => `- ${line}`),
    ...after.split('\n').map((line) => `+ ${line}`),
  ].join('\n');
  return (
    <ToolStep
      props={props}
      label={`Edited ${String(props.args.path ?? '')}`}
      icon={<FilePenLine />}
      wide
    >
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        {result.file && <FileLink file={result.file} />}
        <span className="flex gap-2 font-mono">
          <span>−{before.split('\n').length}</span>
          <span>+{after.split('\n').length}</span>
        </span>
      </div>
      <HighlightedCode language="diff" code={code} />
      <p className="mt-2 text-caption text-muted-foreground">{result.summary}</p>
    </ToolStep>
  );
};
const SearchTool: ToolCallMessagePartComponent = (props) => {
  const result = resultOf(props);
  return (
    <ToolStep
      props={props}
      label={`Searched files for “${String(props.args.query ?? '')}”`}
      icon={<FileSearch />}
    >
      <div className="w-fit max-w-[min(100%,520px)]">
        {!result.items?.length ? (
          <EmptyResult icon={<Search />}>
            {result.summary ?? 'No passages matched this search.'}
          </EmptyResult>
        ) : (
          <ol className="flex flex-col gap-4 py-1">
            {result.items.map((item, index) => (
              <li key={`${item.title}-${index}`} className="flex gap-3">
                <span className="mt-1 flex size-5 shrink-0 items-center justify-center rounded-md border text-xs text-muted-foreground">
                  {index + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="overflow-hidden rounded-xl border">
                    <div className="flex flex-wrap items-center justify-between gap-2 border-b bg-muted/30 px-3 py-2">
                      {item.file ? (
                        <FileLink file={item.file} />
                      ) : (
                        <span className="min-w-0 text-caption font-medium wrap-anywhere">
                          {item.title}
                        </span>
                      )}
                      <span className="text-xs text-muted-foreground">{item.meta}</span>
                    </div>
                    <blockquote className="m-3 border-l border-border pl-3 text-sm leading-relaxed whitespace-pre-wrap text-muted-foreground italic wrap-anywhere">
                      {item.detail}
                    </blockquote>
                  </div>
                </div>
              </li>
            ))}
          </ol>
        )}
      </div>
    </ToolStep>
  );
};
const ExecuteTool: ToolCallMessagePartComponent = (props) => {
  const result = resultOf(props);
  return (
    <ToolStep
      props={props}
      label={`Ran ${String(props.args.command ?? 'command')}`}
      icon={<Terminal />}
      wide
    >
      <HighlightedCode
        language="ansi"
        title="Terminal"
        variant={props.isError ? 'destructive' : 'default'}
        code={`$ ${String(props.args.command ?? '')}\n${result.output ?? ''}`}
      />
    </ToolStep>
  );
};

const ReactionTool: ToolCallMessagePartComponent = (props) => {
  const reaction = resultOf(props).reaction;
  const emoji = reaction
    ? reaction.emoji
    : props.args.action === 'remove'
      ? null
      : String(props.args.emoji ?? '');
  return (
    <ToolStep
      props={props}
      label={emoji ? `Reacted ${emoji}` : 'Removed reaction'}
      icon={<MessageSquare />}
    >
      <div className="flex max-w-[min(100%,520px)] items-start gap-3 py-1">
        {emoji && (
          <span className="grid size-9 shrink-0 place-items-center rounded-full bg-muted text-2xl">
            {emoji}
          </span>
        )}
        {reaction?.content && (
          <blockquote className="min-w-0 border-l-2 pl-3 text-sm leading-relaxed text-muted-foreground wrap-anywhere">
            {reaction.content}
          </blockquote>
        )}
      </div>
    </ToolStep>
  );
};

const InboxTool: ToolCallMessagePartComponent = (props) => {
  const p = useAgentPreview();
  const result = resultOf(props);
  const [recipientKind, recipientHandle] = String(props.args.to ?? '').split(':', 2);
  const send = props.toolName === 'inbox_send';
  const outgoing = result.messages ?? [];
  const list = props.toolName === 'inbox_list';
  return (
    <ToolStep
      props={props}
      label={
        send
          ? outgoing.length > 1
            ? 'Sent messages'
            : 'Sent a message'
          : list
            ? 'Checked inbox conversations'
            : 'Read inbox messages'
      }
      icon={send ? <Send /> : <Inbox />}
    >
      {send ? (
        <ActionCard>
          <div className="flex flex-wrap items-center gap-2 border-b px-3 py-2.5 text-caption">
            <ActivityIdentity
              kind="agent"
              address={p.activityAgent.id}
              name={p.activityAgent.name}
            />
            <ArrowRight aria-label="to" className="size-3.5 shrink-0 text-muted-foreground" />
            <ActivityIdentity
              kind={result.recipient?.kind ?? (recipientKind === 'agent' ? 'agent' : 'user')}
              address={result.recipient?.id ?? recipientHandle}
              name={!result.recipient && !recipientHandle ? 'Recipient' : undefined}
              className="font-medium"
            />
          </div>
          {outgoing.length > 0 && (
            <div className="flex flex-col items-start gap-1 px-3 py-3 text-sm leading-relaxed">
              {outgoing.map((message, index) => (
                <div key={index} className="flex max-w-full flex-col gap-1">
                  {message.content && (
                    <div className="rounded-lg bg-muted px-3 py-2">
                      <AgentMarkdown text={message.content} />
                    </div>
                  )}
                  <MessageFiles references={message.fileRefs} />
                </div>
              ))}
            </div>
          )}
        </ActionCard>
      ) : result.inputItems?.length ? (
        <InputItems items={result.inputItems} />
      ) : result.inputItems ? (
        <EmptyResult icon={<Inbox />}>No matching messages.</EmptyResult>
      ) : list ? (
        <ActionCard>
          <ul className="divide-y">
            {result.items?.map((item) => (
              <li key={item.title} className="flex items-center gap-3 px-3 py-3">
                <AgentAvatar name={item.sender ?? item.title} className="size-9 shrink-0" />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium">{item.title}</span>
                    <Status>{item.status}</Status>
                  </div>
                  <p className="mt-1 text-caption text-muted-foreground">
                    <MessagePreview text={item.detail} />
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">{item.meta}</p>
                </div>
              </li>
            ))}
          </ul>
          {!result.items?.length && (
            <div className="px-3">
              <EmptyResult icon={<Inbox />}>No unread conversations.</EmptyResult>
            </div>
          )}
        </ActionCard>
      ) : (
        <div className="flex w-fit max-w-[min(100%,520px)] flex-col gap-3">
          {result.items?.map((item, index) => (
            <div key={index} className="flex items-start gap-2">
              <AgentAvatar name={item.sender ?? 'Agent'} className="mt-1 size-7 shrink-0" />
              <div className="min-w-0">
                <div className="mb-1 flex flex-wrap items-baseline gap-2 text-xs text-muted-foreground">
                  <span className="font-medium text-foreground">{item.sender}</span>
                  <span>{item.meta}</span>
                </div>
                <div className="rounded-2xl rounded-tl-sm bg-muted px-3 py-2">
                  <p className="mb-1 text-caption font-medium">{item.title}</p>
                  <AgentMarkdown text={item.detail ?? ''} />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </ToolStep>
  );
};

const ScheduleTool: ToolCallMessagePartComponent = (props) => {
  const result = resultOf(props);
  const name = props.toolName;
  const deleted = name === 'schedule_delete';
  const updated = name === 'schedule_update';
  const title = result.title ?? String(props.args.title ?? 'Schedule');
  const label =
    name === 'schedule_create'
      ? 'Created a schedule'
      : deleted
        ? 'Deleted a schedule'
        : updated
          ? 'Updated a schedule'
          : name === 'schedule_list'
            ? 'Checked schedules'
            : 'Read a schedule';
  return (
    <ToolStep props={props} label={label} icon={deleted ? <Trash2 /> : <CalendarClock />}>
      {name === 'schedule_list' ? (
        <ActionCard>
          <ul className="divide-y">
            {result.items?.map((item) => (
              <li key={item.title} className="flex items-start gap-3 px-3 py-3">
                <div className="flex w-14 shrink-0 flex-col items-center gap-1 rounded-lg bg-muted py-2">
                  <CalendarClock className="size-4 text-muted-foreground" />
                  <span className="text-caption font-medium tabular-nums">{item.time}</span>
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium">{item.title}</span>
                    <Status>{item.status}</Status>
                  </div>
                  <p className="mt-1 text-caption text-muted-foreground">{item.detail}</p>
                  {item.meta && <ScheduleTarget target={item.meta} />}
                </div>
              </li>
            ))}
          </ul>
          {!result.items?.length && (
            <div className="px-3">
              <EmptyResult icon={<CalendarClock />}>No schedules yet.</EmptyResult>
            </div>
          )}
        </ActionCard>
      ) : deleted ? (
        <ActionCard>
          <div className="flex items-start gap-3 p-4">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted">
              <Trash2 className="size-5 text-muted-foreground" />
            </div>
            <div className="min-w-0">
              <p className="font-medium line-through decoration-muted-foreground">{title}</p>
              <div className="mt-1">
                <Status>Deleted</Status>
              </div>
            </div>
          </div>
          <p className="border-t px-4 py-3 text-caption text-muted-foreground">{result.summary}</p>
        </ActionCard>
      ) : (
        <ActionCard>
          <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
            <span className="min-w-0 font-medium">{title}</span>
            <Status>{result.status}</Status>
          </div>
          <div className="flex items-start gap-4 p-4">
            <div className="flex w-16 shrink-0 flex-col overflow-hidden rounded-lg border text-center">
              <span className="bg-muted px-1 py-1 text-xs font-medium">
                {result.when?.day ?? <CalendarClock className="mx-auto size-4" />}
              </span>
              <span className="px-1 py-2 text-base font-medium tabular-nums">
                {result.when?.time ?? '—'}
              </span>
            </div>
            <div className="min-w-0 flex-1">
              {updated && result.previousTiming && (
                <p className="mb-1 text-caption text-muted-foreground line-through">
                  {result.previousTiming}
                </p>
              )}
              <p className="text-base leading-snug font-medium">{result.timing}</p>
              <p className="mt-2 flex items-start gap-1.5 text-xs text-muted-foreground">
                <Globe2 className="size-3.5 shrink-0" />
                <span className="wrap-anywhere">{result.timezone}</span>
              </p>
              {result.target && <ScheduleTarget target={result.target} />}
            </div>
          </div>
          <p className="px-4 pb-4 text-caption leading-relaxed">
            {result.content ?? String(props.args.content ?? '')}
          </p>
          <div className="border-t bg-muted/30 px-4 py-3">
            {result.upcoming?.length ? (
              <>
                <p className="mb-2 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                  <Clock3 className="size-3.5" />
                  {result.upcoming.length === 1 ? 'Next run' : 'Upcoming runs'}
                </p>
                <ol className="flex flex-col gap-2">
                  {result.upcoming.map((time, index) => (
                    <li key={time} className="flex items-center gap-2 text-caption tabular-nums">
                      <span
                        className={cn(
                          'size-1.5 shrink-0 rounded-full',
                          index === 0 ? 'bg-foreground' : 'bg-muted-foreground/50',
                        )}
                      />
                      {time}
                    </li>
                  ))}
                </ol>
              </>
            ) : (
              <p className="flex items-center gap-2 text-caption text-muted-foreground">
                <Pause className="size-3.5" />
                {result.status?.toLowerCase() === 'paused'
                  ? 'Paused · no upcoming runs'
                  : 'No forecast available'}
              </p>
            )}
          </div>
        </ActionCard>
      )}
    </ToolStep>
  );
};

function ScheduleTarget({ target }: { target: string }) {
  const { activityAgent, graph, resource } = useAgentPreview();
  const [team, member] = target.split('/', 2);
  const box = graph.boxes.find((item) => item.handle === team || item.name === team);
  const agent =
    graph.agents.find((item) => item.box_id === box?.id && item.name === member) ??
    graph.agents.find((item) => item.name === target || item.handle === target);
  return (
    <ActivityIdentity
      kind={box && !member ? 'box' : 'agent'}
      address={agent?.id ?? box?.id ?? (target === 'Leta' ? resource.id : undefined)}
      name={
        agent?.name ??
        box?.name ??
        (target === 'Leta'
          ? resource.name
          : target === activityAgent.name
            ? activityAgent.name
            : undefined)
      }
      className="mt-2 text-xs text-muted-foreground"
    />
  );
}

const HistoryTool: ToolCallMessagePartComponent = (props) => {
  const result = resultOf(props);
  const search = props.toolName === 'history_search';
  return (
    <ToolStep
      props={props}
      label={
        search
          ? `Searched history for “${String(props.args.query ?? '')}”`
          : `Read history entry ${String(props.args.entry ?? '')}`
      }
      icon={<History />}
    >
      <div className="w-fit max-w-[min(100%,520px)]">
        {search ? (
          result.items?.length ? (
            <ol className="ml-1 border-l pl-4">
              {result.items.map((item, index) => (
                <li key={index} className="relative py-2 first:pt-0 last:pb-0">
                  <span className="absolute -left-5 top-3 size-2 rounded-full border bg-background" />
                  <time className="text-xs text-muted-foreground">{item.meta}</time>
                  <p className="mt-1 text-sm font-medium">{item.title}</p>
                  <p className="mt-1 text-caption leading-relaxed text-muted-foreground">
                    {item.detail}
                  </p>
                </li>
              ))}
            </ol>
          ) : (
            <EmptyResult icon={<History />}>
              {result.summary ?? 'No matching activity.'}
            </EmptyResult>
          )
        ) : (
          <article className="rounded-xl border p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2 border-b pb-3 text-xs text-muted-foreground">
              <span>{result.summary}</span>
              <span>{result.lineRange}</span>
            </div>
            <h4 className="mb-3 text-base font-medium">{result.title}</h4>
            <AgentMarkdown text={result.content ?? ''} />
          </article>
        )}
      </div>
    </ToolStep>
  );
};
const ContextTool: ToolCallMessagePartComponent = (props) => {
  const result = resultOf(props);
  return (
    <ToolStep props={props} label="Checked workspace context" icon={<Users />}>
      <ActionCard>
        <div className="border-b px-4 py-3 font-medium">{result.title}</div>
        <ul className="divide-y">
          {result.items?.map((item) => (
            <li key={item.title} className="flex justify-between gap-3 px-4 py-2 text-caption">
              <ActivityIdentity kind="user" address={item.address} name={item.title} />
              <span className="text-muted-foreground">{item.meta}</span>
            </li>
          ))}
        </ul>
      </ActionCard>
    </ToolStep>
  );
};
const AgentStatusTool: ToolCallMessagePartComponent = (props) => {
  const result = resultOf(props);
  const details = result.agentStatus;
  return (
    <ToolStep props={props} label="Checked agent status" icon={<Users />}>
      <ActionCard>
        <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2.5">
          <div className="min-w-0 space-y-1">
            <ActivityIdentity
              kind="agent"
              address={result.target || String(props.args.target ?? '').replace(/^agent:/, '')}
              name={result.title}
              className="font-medium"
            />
            {details?.title && (
              <p className="text-caption text-muted-foreground">
                {details.title}
                {details.leader && ' · Team lead'}
              </p>
            )}
          </div>
          <Status>
            {result.status ? result.status[0].toUpperCase() + result.status.slice(1) : undefined}
          </Status>
        </div>
        {!!details?.assignments.length && (
          <div className="border-t px-3 py-2.5 text-caption">
            <h3 className="mb-2 font-medium">Work received</h3>
            <ul className="space-y-2">
              {details.assignments.map((item, index) => (
                <li key={item.message || index} className="space-y-1">
                  <ActivityIdentity kind="agent" address={item.sender} />
                  {item.label && <p className="font-medium">{item.label}</p>}
                  {item.preview && (
                    <p className="line-clamp-3 text-muted-foreground">
                      <MessagePreview text={item.preview} />
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
        {!!details?.activity.length && (
          <div className="border-t px-3 py-2.5 text-caption">
            <h3 className="mb-2 font-medium">Recent activity</h3>
            <ul className="space-y-1.5">
              {details.activity.map(({ tool, status, at }, index) => (
                <li key={index} className="flex flex-wrap items-center justify-between gap-2">
                  <span className="capitalize">{tool.replaceAll('_', ' ')}</span>
                  <span className="text-muted-foreground">
                    {at && (
                      <time dateTime={at}>
                        {new Date(at).toLocaleTimeString([], {
                          hour: 'numeric',
                          minute: '2-digit',
                        })}
                      </time>
                    )}
                    {status === 'error' && <span className="ml-2 text-destructive">Failed</span>}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </ActionCard>
    </ToolStep>
  );
};
const BoxTool: ToolCallMessagePartComponent = (props) => {
  const result = resultOf(props);
  const name = props.toolName;
  const deleted = name === 'box_delete';
  return (
    <ToolStep
      props={props}
      label={`${name === 'box_create' ? 'Created' : deleted ? 'Archived' : 'Checked'} ${result.title || 'agent teams'}`}
      icon={deleted ? <Trash2 /> : <Network />}
    >
      {name === 'box_list' ? (
        <ActionCard>
          <ul className="divide-y">
            {result.items?.map((item) => (
              <li key={item.title} className="flex items-start gap-3 p-3">
                <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted">
                  <Network className="size-4 text-muted-foreground" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium">{item.title}</span>
                    <Status>{item.status}</Status>
                  </div>
                  <p className="mt-1 text-caption text-muted-foreground">{item.detail}</p>
                  <p className="mt-2 text-xs text-muted-foreground">{item.meta}</p>
                </div>
              </li>
            ))}
          </ul>
        </ActionCard>
      ) : deleted ? (
        <div className="flex w-fit max-w-[min(100%,520px)] items-start gap-3 py-2">
          <Trash2 className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <div>
            <p className="text-sm">
              <span className="line-through">{result.title}</span>
              <span className="ml-2 text-caption text-muted-foreground">Archived</span>
            </p>
            <p className="mt-1 text-caption leading-relaxed text-muted-foreground">
              {result.summary}
            </p>
          </div>
        </div>
      ) : (
        <ActionCard>
          <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3">
            <span className="flex items-center gap-2 font-medium">
              <Network className="size-4 text-muted-foreground" />
              {result.title}
            </span>
            <Status>{result.status}</Status>
          </div>
          <div className="flex flex-col gap-3 p-4">
            {result.items?.map((item) => (
              <div key={item.title} className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <ActivityIdentity
                      kind="agent"
                      address={item.address}
                      name={item.title}
                      className="font-medium"
                    />
                    <Badge variant={item.title === result.leader ? 'secondary' : 'outline'}>
                      {item.meta}
                    </Badge>
                  </div>
                  <p className="mt-1 text-caption leading-relaxed text-muted-foreground">
                    {item.detail}
                  </p>
                </div>
              </div>
            ))}
          </div>
          <div className="flex flex-col gap-3 border-t bg-muted/30 px-4 py-3">
            {result.edges?.map(([from, to]) => (
              <div key={`${from}-${to}`} className="flex flex-wrap items-center gap-2 text-caption">
                <span>{from}</span>
                <ArrowRight className="size-3.5 text-muted-foreground" />
                <span>{to}</span>
              </div>
            ))}
            <div className="flex items-start gap-2 text-xs text-muted-foreground">
              <Folder className="size-3.5 shrink-0" />
              <span className="font-mono wrap-anywhere">{result.home}</span>
            </div>
          </div>
        </ActionCard>
      )}
    </ToolStep>
  );
};
const HitlStatusTool: ToolCallMessagePartComponent = (props) => {
  const result = resultOf(props);
  const cancelled = props.toolName === 'hitl_cancel';
  const list = props.toolName === 'hitl_list';
  return (
    <ToolStep
      props={props}
      label={
        cancelled ? 'Cancelled a request' : list ? 'Checked human requests' : 'Read a human request'
      }
      icon={cancelled ? <X /> : <ShieldCheck />}
    >
      {list ? (
        <div className="w-fit max-w-[min(100%,520px)]">
          <ul className="divide-y">
            {result.items?.map((item) => (
              <li key={item.title} className="flex items-start gap-3 py-3">
                <Clock3 className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span>{item.title}</span>
                    <Status>{item.status}</Status>
                  </div>
                  <p className="mt-1 text-caption text-muted-foreground">{item.detail}</p>
                  {item.address && (
                    <ActivityIdentity
                      kind="user"
                      address={item.address}
                      className="mt-1 text-xs text-muted-foreground"
                    />
                  )}
                </div>
              </li>
            ))}
          </ul>
          {!result.items?.length && (
            <EmptyResult icon={<ShieldCheck />}>No pending requests.</EmptyResult>
          )}
        </div>
      ) : cancelled ? (
        <div className="flex w-fit max-w-[min(100%,520px)] items-start gap-3 py-2">
          <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-muted">
            <X className="size-3.5 text-muted-foreground" />
          </span>
          <div>
            <p className="text-sm line-through decoration-muted-foreground">{result.title}</p>
            <p className="mt-1 text-caption leading-relaxed text-muted-foreground">
              {result.summary}
            </p>
          </div>
        </div>
      ) : (
        <ActionCard>
          <div className="flex items-center gap-3 border-b px-4 py-3">
            <ShieldCheck className="size-4 shrink-0 text-muted-foreground" />
            <span className="flex-1 font-medium">{result.title}</span>
            <Status>{result.status}</Status>
          </div>
          <div className="flex flex-col gap-3 p-4">
            <p className="text-caption">{result.content}</p>
            {result.target && (
              <ActivityIdentity kind="user" address={result.target} className="text-caption" />
            )}
          </div>
          <p className="border-t bg-muted/30 px-4 py-3 text-xs text-muted-foreground">
            {result.summary}
          </p>
        </ActionCard>
      )}
    </ToolStep>
  );
};
const WebTool: ToolCallMessagePartComponent = (props) => {
  const result = resultOf(props);
  const search = props.toolName === 'websearch';
  const label = search
    ? `Web search${props.args.query ? `: ${String(props.args.query)}` : ''}`
    : `Web fetch (${result.webFormat || String(props.args.format ?? 'markdown')})`;
  return (
    <ToolStep props={props} label={label} icon={<Search />}>
      {props.isError ? (
        <p className="text-caption text-destructive">{result.output}</p>
      ) : result.webSources?.length ? (
        <ActionCard>
          <ul className="divide-y">
            {result.webSources.map((source) => (
              <li key={source.url} className="space-y-1 px-3 py-2 text-caption">
                <a
                  href={source.url}
                  target="_blank"
                  rel="noreferrer"
                  className="font-medium underline underline-offset-3"
                >
                  {source.title}
                </a>
                {source.publishedAt && (
                  <p className="text-muted-foreground">{source.publishedAt}</p>
                )}
                {source.snippet && <p className="text-muted-foreground">{source.snippet}</p>}
              </li>
            ))}
          </ul>
          {result.truncated && (
            <p className="border-t px-3 py-2 text-caption text-muted-foreground">
              Page content was shortened.
            </p>
          )}
        </ActionCard>
      ) : (
        result.webSources && <EmptyResult icon={<Search />}>No sources found.</EmptyResult>
      )}
    </ToolStep>
  );
};

const UnknownTool: ToolCallMessagePartComponent = (props) => (
  <ToolStep props={props} label={props.toolName.replaceAll('_', ' ')} icon={<Search />}>
    {props.result !== undefined && (
      <p className="text-caption whitespace-pre-wrap text-muted-foreground">
        {typeof props.result === 'string' ? props.result : 'This tool has no detailed preview.'}
      </p>
    )}
  </ToolStep>
);

const renderers = {
  by_name: {
    file_list: FileListTool,
    file_read: FileReadTool,
    file_write: FileWriteTool,
    file_edit: FileEditTool,
    file_semantic_search: SearchTool,
    websearch: WebTool,
    webfetch: WebTool,
    execute: ExecuteTool,
    inbox_send: InboxTool,
    inbox_list: InboxTool,
    inbox_read: InboxTool,
    inbox_react: ReactionTool,
    schedule_create: ScheduleTool,
    schedule_get: ScheduleTool,
    schedule_update: ScheduleTool,
    schedule_delete: ScheduleTool,
    schedule_list: ScheduleTool,
    history_search: HistoryTool,
    history_read: HistoryTool,
    get_context: ContextTool,
    agent_status: AgentStatusTool,
    box_create: BoxTool,
    box_list: BoxTool,
    box_get: BoxTool,
    box_delete: BoxTool,
    hitl_ask: AskCard,
    hitl_request: AccessRequestCard,
    hitl_get: HitlStatusTool,
    hitl_list: HitlStatusTool,
    hitl_cancel: HitlStatusTool,
  },
  Fallback: UnknownTool,
};

export const agentToolRenderers = {
  ...renderers,
  by_name: Object.fromEntries(
    Object.entries(renderers.by_name).map(([name, Renderer]) => [
      name,
      (props: ToolCallMessagePartProps) =>
        props.result === undefined || typeof props.result === 'string' ? (
          <UnknownTool {...props} />
        ) : (
          <Renderer {...props} />
        ),
    ]),
  ),
};
