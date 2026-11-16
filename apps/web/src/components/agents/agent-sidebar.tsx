import { useState } from 'react';
import { Pin, PinOff, Settings, ChevronLeft, ChevronRight } from 'lucide-react';
import { AgentAvatar } from '@/components/agent-avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  ContextMenu,
  ContextMenuTrigger,
  ContextMenuContent,
  ContextMenuGroup,
  ContextMenuItem,
} from '@/components/ui/context-menu';
import { focusStyles } from '@/components/ui/styles';
import { cn } from '@/lib/utils';
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
  const listed = p.workspace.agents.filter((agent) => !p.pins.includes(agent.id));
  const previews: Record<string, string> = {
    atlas: 'The launch plan is ready for review.',
    scout: 'Can I read your research documents?',
    forge: 'Updated release.ts. All checks passed.',
    pulse: 'Your Friday briefing is scheduled.',
    sage: 'The team summary is ready.',
  };
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
            onSelect={() =>
              p.savePins(pinned ? p.pins.filter((pin) => pin !== id) : [...p.pins, id])
            }
          >
            {pinned ? <PinOff /> : <Pin />}
            {pinned ? 'Unpin agent' : 'Pin agent'}
          </ContextMenuItem>
          <ContextMenuItem
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
  return (
    <div className="flex min-w-0 flex-col gap-3 pb-4">
      <div
        aria-label="Pinned agents"
        className={cn(
          'min-h-2 rounded-lg py-1',
          dragged && 'min-h-25 bg-accent/40',
          over === 'pins' && 'ring-1 ring-ring',
        )}
        onDragOver={(event) => {
          if (dragged) {
            event.preventDefault();
            setOver('pins');
          }
        }}
        onDragLeave={() => setOver('')}
        onDrop={(event) => {
          event.preventDefault();
          if (dragged && !p.pins.includes(dragged)) p.savePins([...p.pins, dragged]);
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
                      'group/pin flex shrink-0 cursor-grab flex-col items-center gap-1 rounded-lg text-center hover:bg-accent active:cursor-grabbing',
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
                      if (!dragged) return;
                      event.preventDefault();
                      event.stopPropagation();
                      setOver(id);
                    }}
                    onDrop={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      if (dragged && dragged !== id) {
                        const ids = p.pins.filter((pin) => pin !== dragged);
                        ids.splice(ids.indexOf(id), 0, dragged);
                        p.savePins(ids);
                      }
                      setDragged('');
                      setOver('');
                    }}
                  >
                    <AgentAvatar name={fixture.name} className={compact ? 'size-12' : 'size-14'} />
                    {!compact && (
                      <span className="w-full truncate text-caption leading-4">{agent.name}</span>
                    )}
                    {!compact && agent.title && (
                      <Badge
                        variant="secondary"
                        className="h-4.5 max-w-full rounded-sm px-1 text-caption font-normal"
                      >
                        <span className="truncate">{agent.title}</span>
                      </Badge>
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
      {!compact && (
        <div className="flex h-6 items-center px-2 text-caption font-medium">Agents</div>
      )}
      <div className="flex flex-col gap-1">
        {listed.map((fixture) => {
          const agent = p.profiles[fixture.id];
          return (
            <ContextMenu key={fixture.id}>
              <ContextMenuTrigger asChild>
                <Button
                  aria-label={`${agent.name} ${agent.title}`}
                  variant={fixture.id === p.fixture.id ? 'secondary' : 'ghost'}
                  className={cn(
                    'h-(--shell-agent-row-height) w-full gap-2 border-0 p-2',
                    compact ? 'justify-center' : 'justify-start',
                  )}
                  title={compact ? `${agent.name} · ${agent.title}` : undefined}
                  aria-current={fixture.id === p.fixture.id ? 'page' : undefined}
                  draggable
                  onDragStart={(event) => {
                    setDragged(fixture.id);
                    event.dataTransfer.setData('text/openlet-agent', fixture.id);
                  }}
                  onDragEnd={() => {
                    setDragged('');
                    setOver('');
                  }}
                  onClick={() => onSelect(fixture.id)}
                >
                  <AgentAvatar name={fixture.name} className="size-(--shell-agent-avatar-size)" />
                  {!compact && (
                    <span className="flex min-w-0 flex-1 flex-col items-start gap-0.5">
                      <span className="flex max-w-full items-center gap-1.25">
                        <span className="truncate text-agent leading-5">{agent.name}</span>
                        <Badge
                          variant="outline"
                          className="h-4.5 min-w-0 shrink rounded-sm px-1 text-caption font-normal"
                        >
                          <span className="truncate">{agent.title}</span>
                        </Badge>
                      </span>
                      <span className="w-full truncate text-left text-sm leading-4.5 font-normal text-muted-foreground">
                        {previews[fixture.id]}
                      </span>
                    </span>
                  )}
                </Button>
              </ContextMenuTrigger>
              {menu(fixture.id, false)}
            </ContextMenu>
          );
        })}
        {!listed.length && (
          <p className="px-2 py-2 text-caption text-muted-foreground">All agents are pinned.</p>
        )}
      </div>
    </div>
  );
}
