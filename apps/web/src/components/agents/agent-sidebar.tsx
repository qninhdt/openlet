import { useState } from 'react';
import { Pin, PinOff, Settings, ChevronLeft, ChevronRight } from 'lucide-react';
import { AgentAvatar } from '@/components/agent-avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import {
  ContextMenu,
  ContextMenuTrigger,
  ContextMenuContent,
  ContextMenuGroup,
  ContextMenuItem,
} from '@/components/ui/context-menu';
import { focusStyles } from '@/components/ui/styles';
import { cn } from '@/lib/utils';
import { AgentMoveMenu, AgentFolderSection, FolderEditor } from './agent-folders';
import { folderDestination } from '@/lib/agent-organization';
import { useAgentPreview } from './agent-preview';

export function AgentSidebar({
  onSelect,
  compact = false,
}: {
  onSelect: (id: string) => void;
  compact?: boolean;
}) {
  const p = useAgentPreview();
  const [dragged, setDragged] = useState('');
  const [over, setOver] = useState('');
  const [heldUnread, setHeldUnread] = useState<string[]>([]);
  const layout = p.organization.layout;
  const ordered = [...p.workspace.agents].sort((a, b) => {
    const ai = layout.order.indexOf(a.id),
      bi = layout.order.indexOf(b.id);
    return (ai < 0 ? 10000 : ai) - (bi < 0 ? 10000 : bi);
  });
  const listed = ordered.filter((agent) => !p.pins.includes(agent.id));
  const unread = listed.filter(
    (agent) => p.sidebarChats[agent.id].unread_count > 0 || heldUnread.includes(agent.id),
  );
  const regular = listed.filter((agent) => !unread.some((item) => item.id === agent.id));
  function drop(folder: string | null, before?: string) {
    if (!dragged) return;
    if (dragged.startsWith('folder:')) {
      const id = dragged.slice(7);
      if (folderDestination(layout.folders, id, folder))
        void p.organization
          .save({
            ...layout,
            folders: layout.folders.map((f) => (f.id === id ? { ...f, parent_id: folder } : f)),
          })
          .catch(() => {});
    } else {
      const assignments = { ...layout.assignments };
      if (folder) assignments[dragged] = folder;
      else delete assignments[dragged];
      const order = ordered.map((a) => a.id).filter((id) => id !== dragged);
      order.splice(before ? order.indexOf(before) : order.length, 0, dragged);
      void p.organization
        .save({ ...layout, assignments, order, pins: p.pins.filter((id) => id !== dragged) })
        .catch(() => {});
    }
    setDragged('');
    setOver('');
  }

  function avatar(fixture: (typeof ordered)[number], pinned = false) {
    const count = p.sidebarChats[fixture.id].unread_count;
    return (
      <span
        className={cn(
          'relative grid shrink-0 place-items-center',
          pinned ? (compact ? 'size-12' : 'size-14') : 'size-(--shell-agent-avatar-size)',
        )}
      >
        <AgentAvatar
          agentId={fixture.id}
          name={fixture.name}
          appearance={p.profiles[fixture.id]?.appearance ?? fixture.appearance}
          className="size-full"
        />
        {count > 0 && (
          <span
            data-slot="agent-unread-badge"
            aria-label={`${count} unread messages`}
            className={cn(
              'pointer-events-none absolute -end-1.5 -bottom-1 inline-flex h-5.5 min-w-5.5 items-center justify-center rounded-full border-3 border-sidebar bg-sidebar-primary bg-clip-padding px-0.75 text-caption leading-4 font-medium text-sidebar-primary-foreground tabular-nums group-hover/agent:border-accent',
              fixture.id === p.fixture.id && 'border-accent',
            )}
          >
            {Math.min(count, 99)}
          </span>
        )}
      </span>
    );
  }
  function move(id: string, offset: number) {
    const ids = [...p.pins];
    const from = ids.indexOf(id);
    const to = from + offset;
    if (from < 0 || to < 0 || to >= ids.length) return;
    ids.splice(from, 1);
    ids.splice(to, 0, id);
    p.savePins(ids);
  }
  function menu(id: string, pinned: boolean) {
    return (
      <ContextMenuContent>
        <ContextMenuGroup>
          <ContextMenuItem
            disabled={p.organization.busy || !p.organization.ready}
            onSelect={() =>
              p.savePins(pinned ? p.pins.filter((pin) => pin !== id) : [...p.pins, id])
            }
          >
            {pinned ? <PinOff /> : <Pin />}
            {pinned ? 'Unpin agent' : 'Pin agent'}
          </ContextMenuItem>
          <AgentMoveMenu id={id} />
          <ContextMenuItem
            disabled={p.live.enabled && (id !== p.fixture.id || !p.capabilities.can_edit_settings)}
            onSelect={() => {
              onSelect(id);
              p.openSettings(id);
            }}
          >
            <Settings />
            Agent settings
          </ContextMenuItem>
          {pinned && (
            <>
              <ContextMenuItem disabled={p.pins.indexOf(id) === 0} onSelect={() => move(id, -1)}>
                <ChevronLeft />
                Move earlier
              </ContextMenuItem>
              <ContextMenuItem
                disabled={p.pins.indexOf(id) === p.pins.length - 1}
                onSelect={() => move(id, 1)}
              >
                <ChevronRight />
                Move later
              </ContextMenuItem>
            </>
          )}
        </ContextMenuGroup>
      </ContextMenuContent>
    );
  }
  function agentRow(fixture: (typeof listed)[number], inUnread = false) {
    const agent = p.profiles[fixture.id];
    const summary = p.sidebarChats[fixture.id];
    return (
      <ContextMenu key={fixture.id}>
        <ContextMenuTrigger asChild>
          <Button
            aria-label={`${agent.name} ${agent.title}`}
            variant={fixture.id === p.fixture.id ? 'secondary' : 'ghost'}
            className={cn(
              'group/agent h-(--shell-agent-row-height) w-full gap-2 border-0 p-2 text-left',
              over === fixture.id && 'ring-1 ring-ring',
              compact ? 'justify-center' : 'justify-start',
            )}
            title={compact ? `${agent.name} · ${agent.title}` : undefined}
            aria-current={fixture.id === p.fixture.id ? 'page' : undefined}
            draggable={!inUnread}
            onDragOver={(event) => {
              if (inUnread || !dragged || dragged.startsWith('folder:')) return;
              event.preventDefault();
              event.stopPropagation();
              setOver(fixture.id);
            }}
            onDrop={(event) => {
              if (inUnread || !dragged || dragged.startsWith('folder:')) return;
              event.preventDefault();
              event.stopPropagation();
              drop(layout.assignments[fixture.id] ?? null, fixture.id);
            }}
            onDragStart={(event) => {
              setDragged(fixture.id);
              event.dataTransfer.setData('text/openlet-agent', fixture.id);
            }}
            onDragEnd={() => {
              setDragged('');
              setOver('');
            }}
            onClick={(event) => {
              if (inUnread && event.detail > 0)
                setHeldUnread((ids) => (ids.includes(fixture.id) ? ids : [...ids, fixture.id]));
              onSelect(fixture.id);
            }}
          >
            {avatar(fixture)}
            {!compact && (
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="flex min-w-0 items-baseline justify-between gap-2">
                  <span className="grid min-w-0 grid-cols-[fit-content(calc(100%-29px))_minmax(24px,1fr)] items-center gap-1.25 overflow-hidden">
                    <span className="min-w-0 truncate text-agent leading-5 font-medium">
                      {agent.name}
                    </span>
                    {agent.title && (
                      <Badge
                        variant="outline"
                        className="h-4.5 min-w-0 max-w-full justify-self-start rounded-xs bg-accent px-1 py-0 text-caption leading-4 font-normal text-muted-foreground"
                      >
                        <span className="truncate">{agent.title}</span>
                      </Badge>
                    )}
                  </span>
                  {summary.updated_at && (
                    <time
                      dateTime={summary.updated_at}
                      className="shrink-0 text-caption leading-4 font-normal text-muted-foreground @max-[210px]:hidden"
                    >
                      {new Date(summary.updated_at).toLocaleTimeString([], {
                        hour: 'numeric',
                        minute: '2-digit',
                      })}
                    </time>
                  )}
                </span>
                <span className="w-full truncate text-left text-sm leading-4.5 font-normal text-muted-foreground">
                  {summary.preview}
                </span>
              </span>
            )}
          </Button>
        </ContextMenuTrigger>
        {menu(fixture.id, false)}
      </ContextMenu>
    );
  }
  function folderSection(folder: (typeof layout.folders)[number]): React.ReactNode {
    return (
      <AgentFolderSection
        key={folder.id}
        folder={folder}
        dragged={dragged}
        drop={drop}
        onDrag={setDragged}
        over={over}
        setOver={setOver}
      >
        {regular.filter((a) => layout.assignments[a.id] === folder.id).map((a) => agentRow(a))}
        {layout.folders.filter((f) => f.parent_id === folder.id).map(folderSection)}
      </AgentFolderSection>
    );
  }
  return (
    <div
      className="@container flex min-w-0 flex-col gap-1.5 pb-4"
      onPointerLeave={() => setHeldUnread([])}
    >
      {p.organization.error && (
        <p role="alert" className="px-2 text-caption text-destructive">
          {p.organization.error.message}
        </p>
      )}
      <div
        aria-label="Pinned agents"
        className={cn(
          'rounded-lg pt-1 pb-0.5',
          !p.pins.length && !dragged && 'hidden',
          dragged && 'min-h-25 bg-accent/40',
          over === 'pins' && 'ring-1 ring-ring',
        )}
        onDragOver={(event) => {
          if (dragged && !dragged.startsWith('folder:')) {
            event.preventDefault();
            setOver('pins');
          }
        }}
        onDragLeave={() => setOver('')}
        onDrop={(event) => {
          event.preventDefault();
          if (dragged && !dragged.startsWith('folder:') && !p.pins.includes(dragged))
            p.savePins([...p.pins, dragged]);
          setDragged('');
          setOver('');
        }}
      >
        <div className="mx-auto flex w-full max-w-59 flex-wrap justify-center gap-2 p-0.5">
          {p.pins.map((id) => {
            const fixture = p.workspace.agents.find((agent) => agent.id === id)!;
            const agent = p.profiles[id];
            return (
              <ContextMenu key={id}>
                <ContextMenuTrigger asChild>
                  <button
                    type="button"
                    aria-label={`${agent.name} ${agent.title}`}
                    aria-current={id === p.fixture.id ? 'page' : undefined}
                    draggable
                    className={cn(
                      focusStyles,
                      'group/agent flex shrink-0 cursor-grab flex-col items-center gap-1 rounded-md text-center hover:bg-accent active:cursor-grabbing',
                      compact ? 'size-15 p-1.5' : 'h-25.5 w-18 px-0.5 py-1',
                      id === p.fixture.id && 'bg-accent',
                      over === id && 'ring-1 ring-ring',
                    )}
                    onClick={() => onSelect(id)}
                    title={compact ? `${agent.name} · ${agent.title}` : undefined}
                    onDragStart={(event) => {
                      setDragged(id);
                      event.dataTransfer.setData('text/openlet-agent', id);
                    }}
                    onDragEnd={() => {
                      setDragged('');
                      setOver('');
                    }}
                    onDragOver={(event) => {
                      if (!dragged || dragged.startsWith('folder:')) return;
                      event.preventDefault();
                      event.stopPropagation();
                      setOver(id);
                    }}
                    onDrop={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      if (dragged && !dragged.startsWith('folder:') && dragged !== id) {
                        const ids = p.pins.filter((pin) => pin !== dragged);
                        ids.splice(ids.indexOf(id), 0, dragged);
                        p.savePins(ids);
                      }
                      setDragged('');
                      setOver('');
                    }}
                  >
                    {avatar(fixture, true)}
                    {!compact && (
                      <span className="flex min-h-8.5 w-full min-w-0 flex-col items-center gap-0.5">
                        <span className="w-full truncate text-caption leading-4 font-normal">
                          {agent.name}
                        </span>
                        {agent.title && (
                          <Badge
                            variant="outline"
                            className="h-4.5 max-w-full rounded-xs bg-accent px-1 py-0 text-caption leading-4 font-normal text-muted-foreground"
                          >
                            <span className="truncate">{agent.title}</span>
                          </Badge>
                        )}
                      </span>
                    )}
                  </button>
                </ContextMenuTrigger>
                {menu(id, true)}
              </ContextMenu>
            );
          })}
          {dragged && !p.pins.length && (
            <span className="self-center text-caption text-muted-foreground">Drop here to pin</span>
          )}
        </div>
      </div>
      {unread.length > 0 && (
        <section aria-label="Unread agents" className="flex min-w-0 flex-col">
          {!compact && (
            <h2 className="flex h-8 items-center gap-2 px-1.75 text-caption leading-4 font-normal text-muted-foreground">
              Unread
              {unread.some((a) => p.sidebarChats[a.id].unread_count > 0) && (
                <Badge
                  variant="secondary"
                  className="h-4 min-w-4 rounded-full px-1 py-0 text-caption leading-4 font-normal text-muted-foreground"
                >
                  {unread.filter((a) => p.sidebarChats[a.id].unread_count > 0).length}
                </Badge>
              )}
            </h2>
          )}
          {unread.map((agent) => agentRow(agent, true))}
          <Separator className="mt-2" />
        </section>
      )}
      <div className="flex flex-col gap-1.5">
        {compact ? (
          regular.map((a) => agentRow(a))
        ) : (
          <>
            {layout.folders.filter((f) => !f.parent_id).map(folderSection)}
            <section
              aria-label="Unassigned agents"
              onDragOver={(e) => {
                if (dragged) {
                  e.preventDefault();
                  e.stopPropagation();
                }
              }}
              onDrop={(e) => {
                e.preventDefault();
                e.stopPropagation();
                drop(null);
              }}
              className="flex min-h-2 flex-col gap-1"
            >
              {layout.folders.length > 0 && regular.some((a) => !layout.assignments[a.id]) && (
                <h2 className="flex h-8 items-center px-1.75 text-caption leading-4 font-normal text-muted-foreground">
                  Unassigned
                </h2>
              )}
              {regular.filter((a) => !layout.assignments[a.id]).map((a) => agentRow(a))}
            </section>
            {p.folderEditor?.id === null && !p.folderEditor.parent_id && (
              <FolderEditor key="new-root" />
            )}
          </>
        )}
        {!listed.length && !layout.folders.length && (
          <p className="px-2 py-2 text-caption text-muted-foreground">All agents are pinned.</p>
        )}
      </div>
    </div>
  );
}
