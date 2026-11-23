import { useState } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { ArrowLeft, CalendarClock, CheckCheck, Inbox, Search, ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group';
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from '@/components/ui/select';
import type { Cursor, InboxItem, Page, HumanRequest } from '@/lib/agent-api';
import { queryString } from '@/lib/agent-api';
import { RequestInspector, ScheduleInspector, type ScheduleRecord } from './inbox-sources';
import { useAgentPreview } from './agent-preview';
import { InputMessage } from './agent-inputs';
import { MessageReactions, ReactionPicker } from './message-reactions';
import { MessagePreview } from './message-preview';
import { MessageFiles } from './message-files';
import { AgentMarkdown } from './agent-rich-content';
import { ActivityIdentity } from './activity-identity';

const sourceIcon = {
  schedule: CalendarClock,
  hitl: ShieldCheck,
};
export function ActivityInbox() {
  const p = useAgentPreview();
  return <LiveInbox key={p.activityAgent.id} />;
}
function LiveInbox() {
  const p = useAgentPreview();
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState('all');
  const [unread, setUnread] = useState(false);
  const [selected, setSelected] = useState<InboxItem | null>(null);
  const [source, setSource] = useState<
    { kind: 'request'; item: HumanRequest } | { kind: 'schedule'; item: ScheduleRecord } | null
  >(null);
  const requests = useInfiniteQuery({
    queryKey: [...p.live.scope, 'inbox', 'requests'],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      p.live.api!<Page<HumanRequest>>(
        `${p.live.path}/hitl-requests?agent_id=${p.activityAgent.id}&${queryString(pageParam, 'cursor')}`,
      ),
    getNextPageParam: (page) => page.next_cursor as string | null,
    maxPages: 10,
    refetchInterval: 30000,
  });
  const schedules = useInfiniteQuery({
    queryKey: [...p.live.scope, 'inbox', 'schedules'],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      p.live.api!<Page<ScheduleRecord>>(
        `${p.live.path}/schedules?agent_id=${p.activityAgent.id}&${queryString(pageParam, 'cursor')}`,
      ),
    getNextPageParam: (page) => page.next_cursor as string | null,
    maxPages: 10,
    refetchInterval: 30000,
  });
  const params = new URLSearchParams({
    agent_id: p.activityAgent.id,
    query,
    ...(kind !== 'all' ? { kind } : {}),
    unread: String(unread),
  });
  const list = useInfiniteQuery({
    queryKey: [...p.live.scope, 'inbox', query, kind, unread],
    initialPageParam: null as Cursor | null,
    queryFn: ({ pageParam }) =>
      p.live.api!<Page<InboxItem>>(`${p.live.path}/inbox?${params}&${queryString(pageParam)}`),
    getNextPageParam: (page) => page.next_cursor as Cursor | null,
    maxPages: 10,
    refetchInterval: 30000,
  });
  const detail = useInfiniteQuery({
    queryKey: [...p.live.scope, 'inbox', selected?.conversation_id],
    enabled: !!selected,
    initialPageParam: null as Cursor | null,
    queryFn: ({ pageParam }) =>
      p.live.api!<Page<InboxItem>>(
        `${p.live.path}/inbox/${selected!.conversation_id}/messages?agent_id=${p.activityAgent.id}&${queryString(pageParam)}`,
      ),
    getNextPageParam: (page) => page.next_cursor as Cursor | null,
    maxPages: 10,
    refetchInterval: 30000,
  });
  const error = list.error ?? detail.error ?? requests.error ?? schedules.error;
  return (
    <section aria-label="Agent inbox" className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 space-y-3 border-b p-3">
        {selected || source ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setSelected(null);
              setSource(null);
            }}
          >
            <ArrowLeft />
            All conversations
          </Button>
        ) : (
          <>
            <InputGroup>
              <InputGroupAddon>
                <Search />
              </InputGroupAddon>
              <InputGroupInput
                aria-label="Search inbox"
                placeholder="Search inbox…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </InputGroup>
            <div className="flex items-center justify-between gap-2">
              <Button
                variant={unread ? 'secondary' : 'ghost'}
                size="sm"
                aria-pressed={unread}
                onClick={() => setUnread(!unread)}
              >
                Unread by agent
              </Button>
              <Select value={kind} onValueChange={setKind}>
                <SelectTrigger aria-label="Inbox type" className="w-32">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {[
                    ['all', 'All types'],
                    ['user', 'People'],
                    ['agent', 'Agents'],
                    ['schedule', 'Schedules'],
                    ['hitl', 'Decisions'],
                    ['box', 'Teams'],
                  ].map(([id, label]) => (
                    <SelectItem key={id} value={id}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-2">
        {error && (
          <p role="alert" className="p-3 text-sm text-destructive">
            {error.message}
          </p>
        )}
        {(selected ? detail : list).isPending && (
          <p role="status" className="p-4 text-caption text-muted-foreground">
            Loading inbox…
          </p>
        )}
        {source ? (
          source.kind === 'request' ? (
            <RequestInspector key={source.item.id} request={source.item} />
          ) : (
            <ScheduleInspector key={source.item.id} schedule={source.item} />
          )
        ) : selected ? (
          <>
            <h3 className="px-2 py-3 text-sm font-medium">
              {selected.source_kind === 'user' || selected.source_kind === 'agent' ? (
                <ActivityIdentity
                  kind={selected.source_kind}
                  address={selected.source_id}
                  name={selected.source_name ?? undefined}
                />
              ) : (
                (selected.source_name ?? selected.source_kind)
              )}
            </h3>
            {detail.data?.pages
              .flatMap((page) => page.items)
              .map((item) => (
                <article
                  key={`${item.direction}:${item.id}`}
                  className="mb-3 rounded-xl bg-muted/60 p-3"
                >
                  <div className="mb-2 flex justify-between gap-2 text-xs text-muted-foreground">
                    <span>
                      {item.direction === 'out' && (
                        <ActivityIdentity
                          kind="agent"
                          address={p.activityAgent.id}
                          name={p.activityAgent.name}
                        />
                      )}
                    </span>
                    <span>
                      {item.direction === 'in'
                        ? item.read_at
                          ? 'Read by agent'
                          : 'Unread by agent'
                        : 'Sent'}
                      {item.input_type !== 'reaction' &&
                        item.source_kind === 'user' &&
                        item.source_id === p.actorId && (
                          <ReactionPicker
                            emoji={
                              item.reactions?.find(
                                (r) => r.actor_kind === 'user' && r.actor_id === p.actorId,
                              )?.emoji ?? null
                            }
                            onReact={(emoji) =>
                              void p.reactMessage(
                                { ...item, role: item.direction === 'out' ? 'assistant' : 'user' },
                                emoji,
                              )
                            }
                          />
                        )}
                    </span>
                  </div>
                  {item.direction === 'in' ? (
                    <InputMessage item={{ ...item, source_name: item.source_name ?? undefined }} />
                  ) : (
                    <>
                      <AgentMarkdown text={item.content} sources={item.sources} />
                      <MessageFiles references={item.file_refs} />
                      <MessageReactions reactions={item.reactions} actorId={p.actorId} inline />
                    </>
                  )}
                  <time className="mt-3 block text-xs text-muted-foreground">
                    {new Date(item.created_at).toLocaleString()}
                  </time>
                </article>
              ))}
          </>
        ) : (
          <ul className="divide-y">
            {[
              ...(requests.data?.pages
                .flatMap((page) => page.items)
                .map((item) => ({ kind: 'request' as const, item })) ?? []),
              ...(schedules.data?.pages
                .flatMap((page) => page.items)
                .map((item) => ({ kind: 'schedule' as const, item })) ?? []),
            ]
              .sort((a, b) => b.item.created_at.localeCompare(a.item.created_at))
              .filter(
                (entry) =>
                  !unread &&
                  (kind === 'all' || kind === (entry.kind === 'request' ? 'hitl' : 'schedule')) &&
                  `${entry.item.title} ${entry.kind === 'schedule' ? entry.item.content : ''}`
                    .toLowerCase()
                    .includes(query.toLowerCase()),
              )
              .map((entry) => (
                <li key={entry.item.id}>
                  <button
                    className="flex w-full items-start gap-3 rounded-lg p-3 text-left hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring"
                    onClick={() => setSource(entry)}
                  >
                    <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-muted">
                      {entry.kind === 'request' ? (
                        <ShieldCheck className="size-4 text-muted-foreground" />
                      ) : (
                        <CalendarClock className="size-4 text-muted-foreground" />
                      )}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">
                        {entry.item.title || 'Scheduled instruction'}
                      </span>
                      <span className="mt-1 block text-caption capitalize text-muted-foreground">
                        {entry.kind === 'request'
                          ? `${entry.item.type === 'ask' ? 'Question' : 'Request'} · ${entry.item.status}`
                          : entry.item.deleted_at
                            ? 'Deleted'
                            : entry.item.paused
                              ? 'Paused'
                              : 'Scheduled'}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            {list.data?.pages
              .flatMap((page) => page.items)
              .map((item) => {
                const Icon = sourceIcon[item.source_kind as keyof typeof sourceIcon] ?? Inbox;
                return (
                  <li key={item.conversation_id}>
                    <button
                      className="flex w-full items-start gap-3 rounded-lg p-3 text-left hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring"
                      onClick={() => setSelected(item)}
                    >
                      {item.source_kind !== 'user' && item.source_kind !== 'agent' && (
                        <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-muted">
                          <Icon className="size-4 text-muted-foreground" />
                        </span>
                      )}
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center justify-between gap-2 text-sm font-medium">
                          {item.source_kind === 'user' || item.source_kind === 'agent' ? (
                            <ActivityIdentity
                              kind={item.source_kind}
                              address={item.source_id}
                              name={item.source_name ?? undefined}
                            />
                          ) : (
                            <span className="truncate">{item.source_name ?? item.source_kind}</span>
                          )}
                          {item.unread_count ? (
                            <span
                              title="Unread by agent"
                              className="size-2 shrink-0 rounded-full bg-primary"
                            />
                          ) : (
                            <CheckCheck className="size-3.5 shrink-0 text-muted-foreground" />
                          )}
                        </span>
                        <span className="mt-1 block line-clamp-2 text-caption text-muted-foreground">
                          <MessagePreview text={item.content} />
                        </span>
                        <span className="mt-2 block text-xs text-muted-foreground">
                          {item.direction === 'out' ? 'Sent · ' : ''}
                          {new Date(item.created_at).toLocaleString()}
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
          </ul>
        )}
        {!selected &&
          !source &&
          list.data?.pages[0]?.items.length === 0 &&
          !requests.data?.pages[0]?.items.length &&
          !schedules.data?.pages[0]?.items.length && (
            <p className="px-3 py-12 text-center text-sm text-muted-foreground">
              No matching conversations.
            </p>
          )}
        {!source && (selected ? detail : list).hasNextPage && (
          <Button
            size="sm"
            variant="ghost"
            className="mt-3 w-full"
            onClick={() => void (selected ? detail : list).fetchNextPage()}
          >
            Load more
          </Button>
        )}
        {!selected && !source && requests.hasNextPage && (
          <Button size="sm" variant="ghost" onClick={() => void requests.fetchNextPage()}>
            More requests
          </Button>
        )}
        {!selected && !source && schedules.hasNextPage && (
          <Button size="sm" variant="ghost" onClick={() => void schedules.fetchNextPage()}>
            More schedules
          </Button>
        )}
      </div>
    </section>
  );
}
