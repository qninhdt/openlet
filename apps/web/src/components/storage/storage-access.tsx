import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Users } from 'lucide-react';
import { useBackend } from '@/lib/backend';
import type { Member } from '@/components/workspace-settings';
import { useStorageBrowser } from './storage-context';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';

type Actor = { userId?: string; agentId?: string };
type Grant = { actor: Actor; role: string };
type Access = {
  ownership?: Actor & { workspaceId?: string; conversationId?: string };
  grants?: Grant[];
  visibility: string;
};
const actorKey = (actor: Actor) =>
  actor.agentId ? `agent:${actor.agentId}` : `user:${actor.userId}`;

export function StorageAccess() {
  const b = useStorageBrowser();
  const { api, actorId } = useBackend();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState('');
  const [role, setRole] = useState('STORAGE_ROLE_VIEWER');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const path = `/v1/workspaces/${b.workspace.id}/storages/${b.storage.id}`;
  const key = ['storage-access', actorId, b.workspace.id, b.storage.id];
  const access = useQuery({
    queryKey: key,
    queryFn: () => api!<Access>(path + '/access'),
    enabled: open,
  });
  const members = useQuery({
    queryKey: ['workspace-members', actorId, b.workspace.id],
    enabled: open,
    queryFn: async () => {
      const people: Member[] = [];
      let token = '';
      do {
        const page = await api!<{ members?: Member[]; nextPageToken?: string }>(
          `/v1/workspaces/${b.workspace.id}/members?` +
            new URLSearchParams({ page_size: '100', page_token: token }),
        );
        people.push(...(page.members ?? []));
        token = page.nextPageToken ?? '';
      } while (token);
      return people;
    },
  });
  const actors = [
    ...(members.data ?? []).map((member) => ({
      key: `user:${member.user.id}`,
      label: member.user.displayName,
      actor: { userId: member.user.id } as Actor,
    })),
    ...b.workspace.agents
      .filter((agent) => agent.id)
      .map((agent) => ({
        key: `agent:${agent.id}`,
        label: `${agent.name} (agent)`,
        actor: { agentId: agent.id } as Actor,
      })),
  ];
  const name = (actor: Actor) =>
    actors.find((item) => item.key === actorKey(actor))?.label ?? actor.agentId ?? actor.userId;
  async function change(actor: Actor, nextRole?: string) {
    setBusy(true);
    setError('');
    try {
      await api!(path + (nextRole ? ':setAccess' : ':revokeAccess'), {
        method: 'POST',
        body: JSON.stringify({ actor, ...(nextRole ? { role: nextRole } : {}) }),
      });
      await Promise.all([
        client.invalidateQueries({ queryKey: key }),
        client.invalidateQueries({ queryKey: ['storage-roots', actorId, b.workspace.id] }),
      ]);
      setSelected('');
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Could not update access.');
    } finally {
      setBusy(false);
    }
  }
  if (!b.storage.manageAccess || b.storage.isConversation) return null;
  const available = actors.filter(
    (item) =>
      !access.data?.grants?.some((grant) => actorKey(grant.actor) === item.key) &&
      (!access.data?.ownership || actorKey(access.data.ownership) !== item.key),
  );
  return (
    <Dialog open={open} onOpenChange={(value) => !busy && setOpen(value)}>
      <DialogTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Manage storage access"
          title="Manage storage access"
        >
          <Users />
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Access to {b.storage.name}</DialogTitle>
          <DialogDescription>
            Owners manage sharing. Editors can change files; viewers can read and download.
          </DialogDescription>
        </DialogHeader>
        {(error || access.error || members.error) && (
          <p role="alert" className="text-sm text-destructive">
            {error || access.error?.message || members.error?.message}
          </p>
        )}
        {access.isPending ? (
          <p role="status" className="text-sm">
            Loading access…
          </p>
        ) : (
          <>
            <p className="text-sm">
              Owner:{' '}
              {access.data?.ownership?.workspaceId
                ? 'Workspace'
                : access.data?.ownership?.conversationId
                  ? 'Conversation participants (inherited)'
                  : access.data?.ownership
                    ? name(access.data.ownership)
                    : 'Inherited'}
            </p>
            {access.data?.visibility === 'STORAGE_VISIBILITY_PUBLIC' && (
              <p className="text-xs text-muted-foreground">
                Workspace members and agents inherit read access. Removing an explicit grant does
                not remove inherited access.
              </p>
            )}
            <ul className="max-h-64 divide-y overflow-y-auto">
              {access.data?.grants?.map((grant) => (
                <li key={actorKey(grant.actor)} className="flex flex-wrap items-center gap-2 py-2">
                  <span className="min-w-0 flex-1 truncate text-sm">{name(grant.actor)}</span>
                  <Select
                    value={grant.role}
                    onValueChange={(value) => void change(grant.actor, value)}
                    disabled={busy}
                  >
                    <SelectTrigger aria-label={`Role for ${name(grant.actor)}`} className="w-28">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectGroup>
                        <SelectItem value="STORAGE_ROLE_VIEWER">Viewer</SelectItem>
                        <SelectItem value="STORAGE_ROLE_EDITOR">Editor</SelectItem>
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() => void change(grant.actor)}
                  >
                    Remove
                  </Button>
                </li>
              ))}
            </ul>
            <form
              className="flex flex-wrap gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                const actor = actors.find((item) => item.key === selected)?.actor;
                if (actor) void change(actor, role);
              }}
            >
              <Select
                value={selected}
                onValueChange={setSelected}
                disabled={busy || !available.length}
              >
                <SelectTrigger aria-label="Member or agent" className="min-w-36 flex-1">
                  <SelectValue placeholder="Choose a member or agent" />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {available.map((item) => (
                      <SelectItem key={item.key} value={item.key}>
                        {item.label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
              <Select value={role} onValueChange={setRole} disabled={busy}>
                <SelectTrigger aria-label="Access role" className="w-28">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value="STORAGE_ROLE_VIEWER">Viewer</SelectItem>
                    <SelectItem value="STORAGE_ROLE_EDITOR">Editor</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
              <Button disabled={busy || !selected}>{busy ? 'Saving…' : 'Share'}</Button>
            </form>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
