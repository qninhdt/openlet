import { useWorkspaceMembers } from '@/lib/workspace-members';
import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useBackend } from '@/lib/backend';
import { useAgentPreview } from './agent-preview';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

export function AgentAccess() {
  const p = useAgentPreview();
  const { api, actorId } = useBackend();
  const client = useQueryClient();
  const [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const key = ['agent-access', actorId, p.workspace.id, p.resource.id];
  const access = useQuery({
    queryKey: key,
    queryFn: async () => {
      const people: { user_id: string; role: string }[] = [];
      let cursor = '';
      do {
        const page = await api!<{ items: typeof people; next_cursor: string | null }>(
          p.live.path + '/access?' + new URLSearchParams({ cursor }),
        );
        people.push(...page.items);
        cursor = page.next_cursor ?? '';
      } while (cursor);
      return people;
    },
  });
  const members = useWorkspaceMembers(p.workspace.id);
  async function change(user: string, grant: boolean) {
    setBusy(true);
    setError('');
    try {
      await api!(p.live.path + '/operators/' + user, { method: grant ? 'PUT' : 'DELETE' });
      await Promise.all([
        client.invalidateQueries({ queryKey: key }),
        client.invalidateQueries({ queryKey: ['agents', actorId, p.workspace.id] }),
      ]);
      setSelected('');
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const available =
    members.data?.filter(
      (member) => !access.data?.some((person) => person.user_id === member.user.id),
    ) ?? [];
  return (
    <section className="flex flex-col gap-3" aria-label="Agent access">
      <h3 className="text-sm font-medium">Agent access</h3>
      {(error || access.error || members.error) && (
        <p role="alert" className="text-sm text-destructive">
          {error || access.error?.message || members.error?.message}
        </p>
      )}
      {(access.isPending || members.isPending) && (
        <p role="status" className="text-sm text-muted-foreground">
          Loading access…
        </p>
      )}
      <ul className="divide-y">
        {access.data?.map((person) => (
          <li key={person.user_id + person.role} className="flex items-center gap-2 py-2 text-sm">
            <span className="min-w-0 flex-1 truncate">
              {members.data?.find((member) => member.user.id === person.user_id)?.user
                .displayName ?? person.user_id}
            </span>
            <span className="text-xs text-muted-foreground capitalize">{person.role}</span>
            {person.role === 'operator' && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={busy}
                onClick={() => void change(person.user_id, false)}
              >
                Remove
              </Button>
            )}
          </li>
        ))}
      </ul>
      <div className="flex gap-2">
        <Select value={selected} onValueChange={setSelected} disabled={busy || !available.length}>
          <SelectTrigger aria-label="Workspace member" className="min-w-0 flex-1">
            <SelectValue placeholder="Choose a member" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {available.map((member) => (
                <SelectItem key={member.user.id} value={member.user.id}>
                  {member.user.displayName}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <Button
          type="button"
          variant="outline"
          disabled={busy || !selected}
          onClick={() => void change(selected, true)}
        >
          Add operator
        </Button>
      </div>
    </section>
  );
}
