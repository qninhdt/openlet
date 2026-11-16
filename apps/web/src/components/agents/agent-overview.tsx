import { useId, useState } from 'react';
import {
  ArrowDownLeft,
  CalendarClock,
  Check,
  CheckCheck,
  ChevronDown,
  CircleHelp,
  Clock3,
  Inbox,
  ListFilter,
  MessageSquare,
  MoreHorizontal,
  Pause,
  Play,
  Search,
  Settings,
  ShieldCheck,
  UserRound,
} from 'lucide-react';
import { AgentAvatar } from '@/components/agent-avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
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
import { AccessRequestCard, AskCard } from './agent-hitl';
import { previewFiles, useAgentPreview } from './agent-preview';
import { ProviderLogo } from './provider-logo';

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

type Activity = (typeof activities)[number];
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
              Every Monday at <span className="tabular-nums">{saved.time}</span>
            </p>
            <p className="mt-0.5 text-caption text-muted-foreground">
              Asia/Ho_Chi_Minh · UTC+07:00
            </p>
          </div>
        </div>
        <Badge variant="outline" className="font-normal">
          {p.session.schedulePaused ? 'Paused' : 'Active'}
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
              {p.session.schedulePaused
                ? 'No runs while paused'
                : `Next: Mon, Nov 23 · ${saved.time}`}
            </span>
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
  const schedule: Schedule = p.session.schedule ?? {
    title: activities[3].title,
    time: '09:00',
    content: activities[3].content,
  };
  const needsYou =
    item.sender === 'You' &&
    ((item.kind === 'question' && !p.session.answers) ||
      (item.kind === 'request' && !p.session.approval));
  const Icon = icons[item.kind];
  const status =
    item.kind === 'question'
      ? item.sender === 'Linh'
        ? 'Waiting for Linh'
        : p.session.answers
          ? 'Answered'
          : 'Needs your answer'
      : item.kind === 'request'
        ? p.session.approval === 'accepted'
          ? 'Allowed in preview'
          : p.session.approval === 'denied'
            ? 'Declined'
            : 'Needs your approval'
        : item.kind === 'schedule'
          ? p.session.schedulePaused
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
              {item.kind === 'message' && item.sender === 'Scout' ? (
                <AgentAvatar name="Scout" className="size-8" />
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
                          ? `${p.profile.name} hasn’t read this message yet`
                          : `Read by ${p.profile.name}`}
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
            <AskCard inline />
          ) : item.kind === 'request' ? (
            <AccessRequestCard inline />
          ) : item.kind === 'schedule' ? (
            <ScheduleDetails
              saved={schedule}
              onSave={(schedule) => p.updateSession({ schedule })}
            />
          ) : (
            <div className="flex flex-col items-start gap-3">
              <p className="whitespace-pre-wrap text-sm leading-relaxed">{item.content}</p>
              {'fileId' in item && <ActivityFile id={item.fileId} />}
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

export function AgentOverview() {
  const p = useAgentPreview();
  const pending = p.pendingRequests;
  const [needsYou, setNeedsYou] = useState(false);
  const [kind, setKind] = useState('all');
  const [query, setQuery] = useState('');
  const provider = p.profile.model.startsWith('Claude')
    ? 'Anthropic'
    : p.profile.model.startsWith('GPT')
      ? 'OpenAI'
      : 'Google';
  const visible = activities.filter(
    (item) =>
      (!needsYou ||
        (item.sender === 'You' &&
          ((item.kind === 'question' && !p.session.answers) ||
            (item.kind === 'request' && !p.session.approval)))) &&
      (kind === 'all' || kind === item.kind) &&
      `${item.kind === 'schedule' && p.session.schedule ? `${p.session.schedule.title} ${p.session.schedule.content}` : `${item.title} ${item.content}`} ${item.sender} ${kinds[item.kind]}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  return (
    <section
      aria-label="Agent overview"
      className="h-full min-w-0 overflow-y-auto overscroll-contain bg-background"
    >
      <div className="mx-auto flex w-full max-w-5xl flex-col px-4 pt-6 pb-12 sm:px-7 sm:pt-8 lg:px-10">
        <header className="flex items-start gap-3 sm:gap-4">
          <AgentAvatar name={p.fixture.name} className="size-12 shrink-0 sm:size-14" />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="truncate text-xl font-medium tracking-tight">{p.profile.name}</h2>
              <div className="flex shrink-0 items-center gap-1">
                <Button
                  variant="outline"
                  size="sm"
                  aria-label="Edit agent settings"
                  onClick={() => p.openSettings()}
                >
                  <Settings />
                  Settings
                </Button>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" size="icon-sm" aria-label="Agent actions">
                      <MoreHorizontal />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuGroup>
                      <DropdownMenuItem
                        onSelect={() => p.updateSession({ paused: !p.session.paused })}
                      >
                        {p.session.paused ? <Play /> : <Pause />}
                        {p.session.paused ? 'Resume agent' : 'Pause agent'}
                      </DropdownMenuItem>
                    </DropdownMenuGroup>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            </div>
            <p className="mt-2 max-w-prose text-sm leading-relaxed text-muted-foreground">
              {p.profile.description}
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 text-caption text-muted-foreground">
              <span className="inline-flex items-center gap-1.5 text-foreground">
                {p.session.paused ? (
                  <Pause className="size-3.5" />
                ) : (
                  <span className="size-1.5 rounded-full bg-foreground/60" />
                )}
                {p.session.paused ? 'Paused' : 'Idle'}
              </span>
              <span className="inline-flex items-center gap-1.5">
                <ProviderLogo provider={provider} />
                {p.profile.model} · {p.profile.effort}
              </span>
              <span>Local preview</span>
            </div>
          </div>
        </header>
        <Separator className="mt-7" />
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 py-3">
          <div className="flex items-center gap-1" role="group" aria-label="Activity scope">
            <Button
              variant={needsYou ? 'ghost' : 'secondary'}
              size="sm"
              aria-pressed={!needsYou}
              onClick={() => setNeedsYou(false)}
            >
              All
            </Button>
            <Button
              variant={needsYou ? 'secondary' : 'ghost'}
              size="sm"
              aria-pressed={needsYou}
              onClick={() => setNeedsYou(true)}
            >
              Needs you
              <Badge variant="secondary" className="h-4.5 min-w-4.5 px-1 font-normal tabular-nums">
                {pending}
              </Badge>
            </Button>
          </div>
          <div className="ml-auto flex min-w-0 items-center gap-1">
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
        <div className="flex items-center justify-between px-2 pt-5 pb-1 text-caption text-muted-foreground sm:px-3">
          <span>Latest activity</span>
          <span className="inline-flex items-center gap-1">
            <ArrowDownLeft className="size-3.5" />
            Newest first
          </span>
        </div>
        <ul aria-label="Agent activity" className="flex min-w-0 flex-col divide-y divide-border/60">
          {activities.map((item) => (
            <ActivityRow key={item.id} item={item} hidden={!visible.includes(item)} />
          ))}
        </ul>
        {!visible.length && (
          <Empty className="py-16">
            <EmptyHeader>
              <EmptyMedia variant="icon">{needsYou ? <Check /> : <Inbox />}</EmptyMedia>
              <EmptyTitle>
                {needsYou && !query && kind === 'all'
                  ? 'You’re all caught up'
                  : 'No matching activity'}
              </EmptyTitle>
              <EmptyDescription>
                {needsYou && !query && kind === 'all'
                  ? 'There are no questions or requests waiting for you.'
                  : 'Try another search or clear the filters.'}
              </EmptyDescription>
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
