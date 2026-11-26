import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Bell, CheckCircle2, MessageCircleQuestion, ShieldCheck, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import {
  Drawer,
  DrawerContent,
  DrawerDescription,
  DrawerHeader,
  DrawerTitle,
  DrawerTrigger,
} from '@/components/ui/drawer';
import { Skeleton } from '@/components/ui/skeleton';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useIsMobile } from '@/hooks/use-mobile';
import { useBackend } from '@/lib/backend';
import { useRealtime } from '@/lib/realtime';
import type { HumanRequest, Page } from '@/lib/agent-api';
import { RequestForm } from './agent-requests';

export function HitlInboxBell({ workspaceId }: { workspaceId: string }) {
  const backend = useBackend();
  const realtime = useRealtime();
  const client = useQueryClient();
  const mobile = useIsMobile(721);
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState<'pending' | 'all'>('pending');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Record<string, string[]>>>({});

  const queryKey = ['human-requests', backend.actorId, workspaceId, filter];
  const inbox = useQuery({
    queryKey,
    enabled: backend.enabled && backend.ready && Boolean(backend.api),
    refetchInterval: 30000,
    queryFn: () => {
      const qs = new URLSearchParams({ workspace_id: workspaceId });
      if (filter === 'pending') qs.set('status', 'pending');
      return backend.api!<Page<HumanRequest>>(`/v1/hitl-requests?${qs}`);
    },
  });

  useEffect(() => {
    if (!backend.enabled) return;
    return realtime.onLetaUserEvent((env) => {
      if (env.type === 'hitl.updated') {
        void client.invalidateQueries({ queryKey: ['human-requests', backend.actorId] });
      }
    });
  }, [backend.enabled, backend.actorId, realtime, client]);

  const items = inbox.data?.items ?? [];
  const pendingCount =
    inbox.data?.pending_count ?? items.filter((r) => r.status === 'pending').length;
  const selected = items.find((r) => r.id === selectedId) ?? items[0] ?? null;

  async function decide(
    request: HumanRequest,
    status: 'answered' | 'accepted' | 'denied',
    response?: HumanRequest['response'],
  ) {
    await backend.api!(`/v1/hitl-requests/${request.id}/decide`, {
      method: 'POST',
      body: JSON.stringify({ status, response }),
    });
    await client.invalidateQueries({ queryKey: ['human-requests', backend.actorId] });
  }

  const triggerButton = (
    <Button
      type="button"
      variant="ghost"
      size="icon-lg"
      aria-label={pendingCount > 0 ? `Requests inbox (${pendingCount} pending)` : 'Requests inbox'}
      className="relative"
    >
      <Bell />
      {pendingCount > 0 && (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute top-1.5 right-1.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] leading-none font-medium text-primary-foreground tabular-nums"
        >
          {Math.min(pendingCount, 99)}
        </span>
      )}
    </Button>
  );

  const body = (
    <div className="flex max-h-[min(640px,78dvh)] min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b px-4 py-3">
        <h2 className="flex-1 text-sm font-medium">Requests inbox</h2>
        <div className="flex items-center gap-1 rounded-lg bg-muted p-0.5">
          <Button
            type="button"
            variant={filter === 'pending' ? 'secondary' : 'ghost'}
            size="xs"
            onClick={() => setFilter('pending')}
          >
            Pending{pendingCount > 0 ? ` (${pendingCount})` : ''}
          </Button>
          <Button
            type="button"
            variant={filter === 'all' ? 'secondary' : 'ghost'}
            size="xs"
            onClick={() => setFilter('all')}
          >
            All
          </Button>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          aria-label="Close requests inbox"
          onClick={() => setOpen(false)}
        >
          <X />
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-4">
        {inbox.error && (
          <p role="alert" className="mb-3 text-sm text-destructive">
            {inbox.error.message}
          </p>
        )}
        {inbox.isPending ? (
          <div className="space-y-3" role="status" aria-label="Loading requests">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : !items.length ? (
          <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
            <CheckCircle2 className="size-7 text-muted-foreground" />
            <p className="text-sm font-medium">All caught up</p>
            <p className="max-w-xs text-caption text-muted-foreground">
              Agent questions and storage access approvals will appear here in real time.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {items.length > 1 && (
              <div className="flex flex-col gap-1" role="listbox" aria-label="HITL requests">
                {items.map((item) => (
                  <Button
                    key={item.id}
                    type="button"
                    variant={selected?.id === item.id ? 'secondary' : 'ghost'}
                    size="sm"
                    className="justify-start font-normal"
                    onClick={() => setSelectedId(item.id)}
                  >
                    {item.type === 'ask' ? <MessageCircleQuestion /> : <ShieldCheck />}
                    <span className="min-w-0 flex-1 truncate text-left">{item.title}</span>
                    <span className="shrink-0 text-xs capitalize text-muted-foreground">
                      {item.status}
                    </span>
                  </Button>
                ))}
              </div>
            )}
            {selected && (
              <div className="space-y-3 border-t pt-3 first:border-t-0 first:pt-0">
                <div>
                  <h3 className="text-sm font-medium">{selected.title}</h3>
                  <p className="mt-0.5 text-caption text-muted-foreground">
                    {selected.requester_name ? `${selected.requester_name} · ` : ''}
                    {new Date(selected.created_at).toLocaleString()}
                  </p>
                </div>
                <RequestForm
                  key={selected.id}
                  request={selected}
                  close={() => setSelectedId(null)}
                  draft={drafts[selected.id] ?? {}}
                  onDraft={(next) => setDrafts((cur) => ({ ...cur, [selected.id]: next }))}
                  onAnswer={decide}
                  onRefresh={() => inbox.refetch()}
                />
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );

  if (mobile) {
    return (
      <Drawer open={open} onOpenChange={setOpen}>
        <DrawerTrigger asChild>{triggerButton}</DrawerTrigger>
        <DrawerContent className="max-h-[85dvh]">
          <DrawerHeader className="sr-only">
            <DrawerTitle>Requests inbox</DrawerTitle>
            <DrawerDescription>
              Review and respond to agent questions and access requests.
            </DrawerDescription>
          </DrawerHeader>
          {body}
        </DrawerContent>
      </Drawer>
    );
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Tooltip>
        <TooltipTrigger asChild>
          <PopoverTrigger asChild>{triggerButton}</PopoverTrigger>
        </TooltipTrigger>
        <TooltipContent side="right" sideOffset={8} className="hidden md:block">
          Requests inbox
        </TooltipContent>
      </Tooltip>
      <PopoverContent
        side="right"
        align="end"
        sideOffset={8}
        className="w-112 max-w-[calc(100vw-4rem)] gap-0 overflow-hidden p-0"
      >
        {body}
      </PopoverContent>
    </Popover>
  );
}
