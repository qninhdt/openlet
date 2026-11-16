import { useId, useState } from 'react';
import {
  CalendarClock,
  CheckCheck,
  ChevronDown,
  CircleHelp,
  Clock3,
  Inbox,
  ListFilter,
  MessageSquare,
  Pause,
  Play,
  Search,
  Settings,
  ShieldCheck,
  UserRound,
} from 'lucide-react';
import { AgentAvatar } from '@/components/agent-avatar';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty';
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group';
import { Separator } from '@/components/ui/separator';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { Textarea } from '@/components/ui/textarea';
import { focusStyles } from '@/components/ui/styles';
import { FileIcon } from '@/components/storage/file-icon';
import { cn } from '@/lib/utils';
import { previewFiles, useAgentPreview } from './agent-preview';
import { ProviderLogo } from './provider-logo';
import { InputMessage } from './agent-inputs';
import { useAgentScroll } from './agent-scroll';

// shortcut: illustrative activity records; replace with authorized inbox/request/schedule API data when connected.
const activities = [
  {
    id: 'launch-review',
    kind: 'message',
    title: 'Launch review',
    sender: 'You',
    time: '2m',
    content:
      'Please check the launch plan against the latest budget. Keep the announcement focused on workspace owners, and flag anything that still needs a decision before Friday.',
    fileId: 'launch-plan',
    unread: true,
  },
  {
    id: 'launch-decisions',
    kind: 'question',
    title: 'Launch decisions',
    sender: 'You',
    time: '5m',
    content: 'Who should receive the announcement, and which channels should we use?',
  },
  {
    id: 'research-access',
    kind: 'request',
    title: 'Research source access',
    sender: 'You',
    time: '8m',
    content: 'Read access to your Personal storage to verify the research sources.',
  },
  {
    id: 'weekly-report',
    kind: 'schedule',
    title: 'Weekly workspace report',
    sender: '',
    time: '12m',
    content:
      'Summarize this week’s decisions, open questions and changed files. Send the report to me every Monday morning.',
  },
  {
    id: 'research-ready',
    kind: 'message',
    title: 'Research is ready',
    sender: 'Scout',
    time: '18m',
    content:
      'The research notes are ready. Three interviews mention shared file ownership. The P03 quotation still needs to be checked against the original transcript before it goes into the announcement.',
    fileId: 'research',
    unread: false,
  },
  {
    id: 'budget-confirmation',
    kind: 'question',
    title: 'Confirm the launch budget',
    sender: 'Linh',
    time: '24m',
    content: 'Can we reserve $250 for the launch, with the remaining $50 held as contingency?',
  },
] as const;

type Activity = {
  id: string;
  kind: 'message' | 'question' | 'request' | 'schedule';
  title: string;
  sender: string;
  time: string;
  content: string;
  fileId?: string;
  unread?: boolean;
};
const kinds = {
  message: 'Message',
  question: 'Question',
  request: 'Request',
  schedule: 'Schedule',
};
const icons = {
  message: MessageSquare,
  question: CircleHelp,
  request: ShieldCheck,
  schedule: CalendarClock,
};

function ActivityFile({ id }: { id: string }) {
  const p = useAgentPreview();
  const file = previewFiles.find((item) => item.id === id)!;
  return (
    <Button
      variant="outline"
      size="sm"
      className="max-w-full justify-start font-normal"
      onClick={() => p.openFile(file)}
    >
      <FileIcon node={p.fileNodes[id]} />
      <span className="truncate">{file.name}</span>
    </Button>
  );
}

type Schedule = { title: string; time: string; content: string };
function ScheduleDetails({
  saved,
  onSave,
}: {
  saved: Schedule;
  onSave: (value: Schedule) => void;
}) {
  const p = useAgentPreview();
  const child = !!p.activityAgent.box_id;
  const [draft, setDraft] = useState(saved);
  const [editing, setEditing] = useState(false);
  const dirty = JSON.stringify(saved) !== JSON.stringify(draft);
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-muted/50 px-3 py-2.5">
        <div className="flex items-center gap-2.5">
          <CalendarClock className="size-4 shrink-0 text-muted-foreground" />
          <div className="text-sm">
            <p>
              {child ? 'Weekdays' : 'Every Monday'} at{' '}
              <span className="tabular-nums">{saved.time}</span>
            </p>
            <p className="mt-0.5 text-caption text-muted-foreground">
              Asia/Ho_Chi_Minh · UTC+07:00
            </p>
          </div>
        </div>
        <Badge variant="outline" className="font-normal">
          {!child && p.session.schedulePaused ? 'Paused' : 'Active'}
        </Badge>
      </div>
      {editing ? (
        <form
          aria-label="Edit weekly schedule"
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (!draft.title.trim() || !draft.content.trim()) return;
            const next = { ...draft, title: draft.title.trim(), content: draft.content.trim() };
            onSave(next);
            setDraft(next);
            setEditing(false);
          }}
        >
          <FieldGroup className="gap-4">
            <Field>
              <FieldLabel htmlFor="schedule-title">Title</FieldLabel>
              <Input
                id="schedule-title"
                required
                maxLength={255}
                value={draft.title}
                onChange={(event) => setDraft({ ...draft, title: event.target.value })}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="schedule-time">Monday, at</FieldLabel>
              <Input
                id="schedule-time"
                type="time"
                required
                value={draft.time}
                onChange={(event) => setDraft({ ...draft, time: event.target.value })}
                className="w-36"
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="schedule-instructions">Instructions</FieldLabel>
              <Textarea
                id="schedule-instructions"
                required
                maxLength={32000}
                rows={3}
                value={draft.content}
                onChange={(event) => setDraft({ ...draft, content: event.target.value })}
              />
            </Field>
          </FieldGroup>
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                setDraft(saved);
                setEditing(false);
              }}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              disabled={!dirty || !draft.title.trim() || !draft.content.trim()}
            >
              Save schedule
            </Button>
          </div>
        </form>
      ) : (
        <>
          <p className="text-sm leading-relaxed">{saved.content}</p>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="flex items-center gap-1.5 text-caption text-muted-foreground">
              <Clock3 className="size-3.5" />
              {child
                ? `Weekdays · ${saved.time}`
                : p.session.schedulePaused
                  ? 'No runs while paused'
                  : `Next: Mon, Nov 23 · ${saved.time}`}
            </span>
            {!child && (
              <div className="flex gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => p.updateSession({ schedulePaused: !p.session.schedulePaused })}
                >
                  {p.session.schedulePaused ? <Play /> : <Pause />}
                  {p.session.schedulePaused ? 'Resume schedule' : 'Pause schedule'}
                </Button>
                <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
                  Edit schedule
                </Button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function ActivityRow({ item, hidden }: { item: Activity; hidden: boolean }) {
  const p = useAgentPreview();
  const [open, setOpen] = useState(false);
  const readStatusId = useId();
  const schedule: Schedule = (!p.activityAgent.box_id ? p.session.schedule : undefined) ?? {
    title: item.kind === 'schedule' ? item.title : activities[3].title,
    time: '09:00',
    content: item.kind === 'schedule' ? item.content : activities[3].content,
  };
  const request = p.requests.find(
    (request) => request.type === (item.kind === 'question' ? 'ask' : 'approval'),
  );
  const needsYou =
    item.sender === 'You' &&
    (item.kind === 'question' || item.kind === 'request') &&
    request?.status === 'pending';
  const Icon = icons[item.kind];
  const status =
    item.kind === 'question'
      ? item.sender === 'Linh'
        ? 'Waiting for Linh'
        : request?.status === 'answered'
          ? 'Answered'
          : 'Needs your answer'
      : item.kind === 'request'
        ? request?.status === 'accepted'
          ? 'Allowed'
          : request?.status === 'denied'
            ? 'Declined'
            : 'Needs your approval'
        : item.kind === 'schedule'
          ? p.activityAgent.box_id
            ? 'Weekdays · 09:00'
            : p.session.schedulePaused
              ? 'Paused'
              : `Mon, Nov 23 · ${schedule.time}`
          : item.unread
            ? 'Unread by agent'
            : 'Read by agent';
  return (
    <Collapsible open={open} onOpenChange={setOpen} asChild>
      <li data-activity={item.kind} hidden={hidden} className="min-w-0">
        <CollapsibleTrigger asChild>
          <button
            type="button"
            aria-label={`${open ? 'Collapse' : 'Expand'} ${item.kind === 'schedule' ? schedule.title : item.title}`}
            aria-describedby={item.kind === 'message' ? readStatusId : undefined}
            className={cn(
              focusStyles,
              'group flex w-full min-w-0 items-start gap-3 rounded-lg px-2 py-4 text-left transition-colors hover:bg-muted/50 sm:gap-4 sm:px-3',
            )}
          >
            <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
              {item.kind === 'message' && item.sender !== 'You' && item.sender !== 'Linh' ? (
                <AgentAvatar name={item.sender} className="size-8" />
              ) : item.kind === 'message' ? (
                <UserRound className="size-4" />
              ) : (
                <Icon className="size-4" />
              )}
            </span>
            <span className="flex min-w-0 flex-1 flex-col gap-1.5">
              <span className="flex min-w-0 items-start justify-between gap-3">
                <span
                  className={cn(
                    'min-w-0 break-words text-sm font-medium',
                    item.kind === 'message' && item.unread && 'font-semibold',
                  )}
                >
                  {item.kind === 'schedule' ? schedule.title : item.title}
                </span>
                <span className="flex shrink-0 items-center gap-2 text-caption font-normal text-muted-foreground">
                  {item.kind === 'message' && (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span
                          role="img"
                          aria-label={item.unread ? 'Unread by agent' : 'Read by agent'}
                          className={cn(
                            focusStyles,
                            'inline-flex size-4 items-center justify-center rounded-sm',
                          )}
                        >
                          {item.unread ? (
                            <span className="size-2 rounded-full bg-(--brand)" />
                          ) : (
                            <CheckCheck className="size-4" />
                          )}
                        </span>
                      </TooltipTrigger>
                      <TooltipContent>
                        {item.unread
                          ? `${p.activityAgent.name} hasn’t read this message yet`
                          : `Read by ${p.activityAgent.name}`}
                      </TooltipContent>
                    </Tooltip>
                  )}
                  {item.kind === 'message' && (
                    <span id={readStatusId} className="sr-only">
                      {item.unread ? 'Unread by agent' : 'Read by agent'}
                    </span>
                  )}
                  {item.time}
                  <ChevronDown
                    className={cn(
                      'size-3.5 transition-transform motion-reduce:transition-none',
                      open && 'rotate-180',
                    )}
                  />
                </span>
              </span>
              <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-caption text-muted-foreground">
                <span className="inline-flex items-center gap-1">
                  <Icon className="size-3" />
                  {kinds[item.kind]}
                </span>
                {item.sender && (
                  <>
                    <span aria-hidden="true">·</span>
                    <span>
                      {item.kind === 'message'
                        ? item.sender
                        : `To ${item.sender.toLowerCase() === 'you' ? 'you' : item.sender}`}
                    </span>
                  </>
                )}
                {item.kind !== 'message' && (
                  <>
                    <span aria-hidden="true">·</span>
                    <span
                      className={cn(
                        'inline-flex items-center gap-1',
                        needsYou && 'font-medium text-foreground',
                      )}
                    >
                      {needsYou && <span className="size-1.5 rounded-full bg-primary" />}
                      {status}
                    </span>
                  </>
                )}
              </span>
              {!open && (
                <span className="line-clamp-2 text-sm leading-relaxed text-muted-foreground">
                  {item.kind === 'schedule' ? schedule.content : item.content}
                </span>
              )}
            </span>
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent
          forceMount
          hidden={!open}
          className="min-w-0 pt-3 pr-2 pb-5 pl-13 sm:pr-3 sm:pl-15 [&>section]:max-w-2xl"
        >
          {item.kind === 'question' && item.sender === 'You' ? (
            <p className="text-sm text-muted-foreground">
              This question is shown in the recipient’s chat. Only the addressed person can answer.
            </p>
          ) : item.kind === 'request' ? (
            <p className="text-sm text-muted-foreground">
              Storage permission request. The addressed person can allow or decline it in chat.
            </p>
          ) : item.kind === 'schedule' ? (
            <ScheduleDetails
              saved={schedule}
              onSave={(schedule) => p.updateSession({ schedule })}
            />
          ) : (
            <div className="flex flex-col items-start gap-3">
              <p className="whitespace-pre-wrap text-sm leading-relaxed">{item.content}</p>
              {item.fileId && <ActivityFile id={item.fileId} />}
              {item.kind === 'question' && (
                <p className="flex items-center gap-1.5 text-caption text-muted-foreground">
                  <Clock3 className="size-3.5" />
                  Only Linh can answer this question.
                </p>
              )}
            </div>
          )}
        </CollapsibleContent>
      </li>
    </Collapsible>
  );
}

export function PreviewInbox() {
  const p = useAgentPreview();
  const [kind, setKind] = useState('all');
  const [query, setQuery] = useState('');
  const records: Activity[] = p.activityAgent.box_id
    ? [
        {
          id: `${p.activityAgent.id}-parent`,
          kind: 'message',
          title: p.activityContact?.name ?? p.profile.name,
          sender: p.activityContact?.name ?? p.profile.name,
          time: '2m',
          content: 'Check the launch evidence and share the findings with the representative.',
          unread: true,
        },
        {
          id: `${p.activityAgent.id}-peer`,
          kind: 'message',
          title: p.activityPeer?.name ?? p.profile.name,
          sender: p.activityPeer?.name ?? p.profile.name,
          time: '8m',
          content:
            'Keep the announcement limited to workspace owners. The budget is $250 of the $300 cap.',
          unread: false,
          fileId: 'research',
        },
        {
          id: `${p.activityAgent.id}-schedule`,
          kind: 'schedule',
          title: 'Morning briefing',
          sender: '',
          time: '12m',
          content: 'Review new research before the morning briefing.',
        },
      ]
    : [...activities];
  const visible = records.filter(
    (item) =>
      (kind === 'all' || kind === item.kind) &&
      `${item.kind === 'schedule' && p.session.schedule ? `${p.session.schedule.title} ${p.session.schedule.content}` : `${item.title} ${item.content}`} ${item.sender} ${kinds[item.kind]}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  return (
    <section
      aria-label="Agent inbox"
      className="h-full min-w-0 overflow-y-auto overscroll-contain bg-background"
    >
      <div className="mx-auto flex w-full flex-col px-3 pt-1 pb-8">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 py-3">
          <div className="flex w-full min-w-0 items-center gap-1 [&>[data-slot=input-group]]:flex-1">
            <InputGroup className="w-32 sm:w-44">
              <InputGroupInput
                aria-label="Search agent activity"
                placeholder="Search…"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
              <InputGroupAddon>
                <Search />
              </InputGroupAddon>
            </InputGroup>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant={kind === 'all' ? 'ghost' : 'secondary'}
                  size="icon-sm"
                  aria-label="Filter activity"
                  title={
                    kind === 'all'
                      ? 'Filter activity'
                      : `Filter: ${kinds[kind as keyof typeof kinds]}`
                  }
                >
                  <ListFilter />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuRadioGroup value={kind} onValueChange={setKind}>
                  <DropdownMenuRadioItem value="all">All types</DropdownMenuRadioItem>
                  {Object.entries(kinds).map(([value, label]) => (
                    <DropdownMenuRadioItem value={value} key={value}>
                      {label}
                    </DropdownMenuRadioItem>
                  ))}
                </DropdownMenuRadioGroup>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
        <Separator />
        <ul aria-label="Agent activity" className="flex min-w-0 flex-col divide-y divide-border/60">
          {(p.activityAgent.box_id ? [] : p.session.feedback)
            .filter(
              (i) =>
                (kind === 'all' || kind === 'message') &&
                `${i.content} ${i.input_payload?.target.content}`
                  .toLowerCase()
                  .includes(query.toLowerCase()),
            )
            .map((item) => (
              <li
                key={item.id}
                className="py-4"
                title="Waiting silently until the next message, or until the agent reads its inbox"
              >
                <InputMessage item={item} />
                <span className="mt-2 block pl-11 text-xs text-muted-foreground">
                  Queued silently
                </span>
              </li>
            ))}
          {records.map((item) => (
            <ActivityRow key={item.id} item={item} hidden={!visible.includes(item)} />
          ))}
        </ul>
        {!visible.length && !p.session.feedback.length && (
          <Empty className="py-16">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <Inbox />
              </EmptyMedia>
              <EmptyTitle>No matching activity</EmptyTitle>
              <EmptyDescription>Try another search or clear the filters.</EmptyDescription>
            </EmptyHeader>
            {(query || kind !== 'all') && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setQuery('');
                  setKind('all');
                }}
              >
                Clear filters
              </Button>
            )}
          </Empty>
        )}
      </div>
    </section>
  );
}

export function AgentOverview() {
  const p = useAgentPreview();
  const scroll = useAgentScroll<HTMLElement>(`${p.fixture.id}:overview`);
  const model = p.profile.model.toLowerCase();
  const provider =
    model.includes('claude') || model.includes('anthropic')
      ? 'Anthropic'
      : model.includes('gpt') || model.includes('openai')
        ? 'OpenAI'
        : 'Google';
  return (
    <section
      {...scroll.viewportProps}
      aria-label="Agent overview"
      className="h-full min-w-0 overflow-y-auto bg-background"
    >
      <div className="mx-auto max-w-3xl px-5 py-8 sm:px-10 sm:py-12">
        <header className="flex items-start gap-4">
          <AgentAvatar
            name={p.profile.name}
            appearance={p.profile.appearance}
            className="size-14 shrink-0"
          />
          <div className="min-w-0 flex-1">
            <div className="flex items-center justify-between gap-3">
              <h2 className="truncate text-xl font-medium">{p.profile.name}</h2>
              {p.capabilities.can_edit_settings && (
                <Button
                  variant="outline"
                  size="sm"
                  aria-label="Edit agent settings"
                  onClick={() => p.openSettings()}
                >
                  <Settings />
                  Settings
                </Button>
              )}
            </div>
            <p className="mt-1 text-sm text-muted-foreground">{p.profile.title}</p>
          </div>
        </header>
        <p className="mt-7 max-w-prose text-sm leading-relaxed">{p.profile.description}</p>
        <dl className="mt-8 divide-y border-y text-sm">
          <div className="flex justify-between gap-4 py-4">
            <dt className="text-muted-foreground">Workspace</dt>
            <dd>{p.workspace.name}</dd>
          </div>
          <div className="flex justify-between gap-4 py-4">
            <dt className="text-muted-foreground">Status</dt>
            <dd>
              {p.live.enabled
                ? p.live.profile.data?.paused
                  ? 'Paused'
                  : (p.live.profile.data?.state ?? 'Loading…')
                : p.session.paused
                  ? 'Paused'
                  : 'Idle'}
            </dd>
          </div>
          <div className="flex justify-between gap-4 py-4">
            <dt className="text-muted-foreground">Model</dt>
            <dd className="flex min-w-0 items-center gap-2">
              <ProviderLogo provider={provider} />
              <span className="truncate">{p.profile.model}</span>
            </dd>
          </div>
        </dl>
        <section aria-label="For you" className="mt-9">
          <h3 className="mb-3 text-sm font-medium">For you</h3>
          {p.requests.filter((request) => request.status === 'pending').length ? (
            <ul className="divide-y">
              {p.requests
                .filter((request) => request.status === 'pending')
                .map((request) => (
                  <li key={request.id}>
                    <button
                      type="button"
                      className="flex w-full items-center gap-3 rounded-lg px-2 py-3 text-left hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring"
                      onClick={() => p.updateSession({ mainTab: 'agent', requestOpen: request.id })}
                    >
                      {request.type === 'ask' ? (
                        <CircleHelp className="size-4 shrink-0 text-muted-foreground" />
                      ) : (
                        <ShieldCheck className="size-4 shrink-0 text-muted-foreground" />
                      )}
                      <span className="min-w-0 flex-1 truncate text-sm">{request.title}</span>
                      <ChevronDown className="size-3.5 -rotate-90 text-muted-foreground" />
                    </button>
                  </li>
                ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">Nothing waiting for you.</p>
          )}
        </section>
      </div>
    </section>
  );
}
