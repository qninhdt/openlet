import { useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from '@tanstack/react-router';
import { toast } from 'sonner';
import { useBackend } from '@/lib/backend';
import type { Account } from '@/lib/account';
import { useShellLocation } from '@/lib/shell-navigation';
import { AgentAvatar } from './agent-avatar';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Field, FieldGroup, FieldLabel } from './ui/field';
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
  AlertDialogAction,
} from './ui/alert-dialog';

export type Member = { user: Account; role: string };
type Invitation = { id: string; email: string; expiresAt: string; acceptedByUserId?: string };

export function WorkspaceSettings({ section }: { section: 'general' | 'members' }) {
  const { workspace } = useShellLocation();
  const { api, actorId } = useBackend();
  const client = useQueryClient();
  const navigate = useNavigate();
  const path = `/v1/workspaces/${workspace}`;
  const [name, setName] = useState<string | null>(null);
  const [email, setEmail] = useState('');
  const [inviteLink, setInviteLink] = useState('');
  const invitationRequest = useRef({ email: '', id: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [confirm, setConfirm] = useState<{
    title: string;
    description: string;
    action: () => Promise<unknown>;
  } | null>(null);
  const detail = useQuery({
    queryKey: ['workspace-settings', actorId, workspace],
    queryFn: () => api!<{ name: string; role?: string }>(path),
  });
  const members = useQuery({
    queryKey: ['workspace-members', actorId, workspace],
    queryFn: async () => {
      const items: Member[] = [];
      let token = '';
      do {
        const page = await api!<{ members?: Member[]; nextPageToken?: string }>(
          path + '/members?' + new URLSearchParams({ page_size: '100', page_token: token }),
        );
        items.push(...(page.members ?? []));
        token = page.nextPageToken ?? '';
      } while (token);
      return items;
    },
  });
  const owner =
    members.data?.some(
      (member) => member.user.id === actorId && member.role === 'WORKSPACE_ROLE_OWNER',
    ) ?? false;
  const invitations = useQuery({
    queryKey: ['workspace-invitations', actorId, workspace],
    enabled: owner,
    queryFn: async () => {
      const items: Invitation[] = [];
      let token = '';
      do {
        const page = await api!<{ invitations?: Invitation[]; nextPageToken?: string }>(
          path + '/invitations?' + new URLSearchParams({ page_size: '100', page_token: token }),
        );
        items.push(...(page.invitations ?? []));
        token = page.nextPageToken ?? '';
      } while (token);
      return items.filter(
        (item) => !item.acceptedByUserId && new Date(item.expiresAt).getTime() > Date.now(),
      );
    },
  });
  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError('');
    try {
      await action();
      await Promise.all(
        ['workspace-settings', 'workspace-members', 'workspace-invitations', 'workspaces'].map(
          (key) => client.invalidateQueries({ queryKey: [key, actorId] }),
        ),
      );
      setConfirm(null);
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (detail.isPending || members.isPending) return <p role="status">Loading workspace…</p>;
  if (detail.error || members.error)
    return (
      <p role="alert" className="text-destructive">
        {(detail.error ?? members.error)!.message}
      </p>
    );
  return (
    <div className="flex w-full flex-col gap-6">
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {section === 'general' && (
        <form
          className="flex flex-col gap-4 rounded-xl border p-4"
          onSubmit={(event) => {
            event.preventDefault();
            void run(() =>
              api!(path, {
                method: 'PATCH',
                body: JSON.stringify({ name: (name ?? detail.data!.name).trim() }),
              }),
            );
          }}
        >
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="workspace-name">Workspace name</FieldLabel>
              <Input
                id="workspace-name"
                value={name ?? detail.data!.name}
                onChange={(event) => setName(event.target.value)}
                maxLength={200}
                required
                disabled={!owner || busy}
              />
            </Field>
          </FieldGroup>
          {owner && (
            <Button
              className="self-start"
              disabled={
                busy ||
                !(name ?? detail.data!.name).trim() ||
                name === null ||
                name === detail.data!.name
              }
            >
              Save name
            </Button>
          )}
        </form>
      )}
      {section === 'members' && (
        <>
          <section className="flex flex-col gap-3" aria-labelledby="members-title">
            <h2 id="members-title" className="sr-only">
              Members
            </h2>
            <ul className="divide-y">
              {members.data?.map((member) => (
                <li key={member.user.id} className="flex flex-wrap items-center gap-3 py-3">
                  <AgentAvatar
                    name={member.user.displayName}
                    appearance={member.user.appearance}
                    className="size-9"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">
                      {member.user.displayName}
                      {member.user.id === actorId ? ' (you)' : ''}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {member.role === 'WORKSPACE_ROLE_OWNER' ? 'Owner' : 'Member'}
                    </p>
                  </div>
                  {owner && member.role !== 'WORKSPACE_ROLE_OWNER' && (
                    <>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={busy}
                        onClick={() =>
                          setConfirm({
                            title: 'Transfer ownership?',
                            description: `${member.user.displayName} will manage this workspace. You will become a member.`,
                            action: () =>
                              api!(path + ':transferOwnership', {
                                method: 'POST',
                                body: JSON.stringify({ newOwnerUserId: member.user.id }),
                              }),
                          })
                        }
                      >
                        Make owner
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={busy}
                        onClick={() =>
                          setConfirm({
                            title: 'Remove member?',
                            description: `${member.user.displayName} will lose access to this workspace and its agents.`,
                            action: () =>
                              api!(path + `/members/${member.user.id}`, { method: 'DELETE' }),
                          })
                        }
                      >
                        Remove
                      </Button>
                    </>
                  )}
                </li>
              ))}
            </ul>
          </section>
          {owner ? (
            <>
              <section className="flex flex-col gap-4" aria-labelledby="invite-title">
                <h2 id="invite-title" className="text-base font-medium">
                  Invite a member
                </h2>
                <form
                  className="flex items-end gap-2"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void run(async () => {
                      const target = email.trim().toLowerCase();
                      if (invitationRequest.current.email !== target)
                        invitationRequest.current = { email: target, id: crypto.randomUUID() };
                      const result = await api!<{ token?: string }>(path + '/invitations', {
                        method: 'POST',
                        body: JSON.stringify({
                          email: target,
                          requestId: invitationRequest.current.id,
                        }),
                      });
                      if (result.token)
                        setInviteLink(
                          `${window.location.origin}/join?token=${encodeURIComponent(result.token)}`,
                        );
                      invitationRequest.current = { email: '', id: '' };
                      setEmail('');
                    });
                  }}
                >
                  <Field className="min-w-0 flex-1">
                    <FieldLabel htmlFor="invite-email">Email</FieldLabel>
                    <Input
                      id="invite-email"
                      type="email"
                      value={email}
                      onChange={(event) => setEmail(event.target.value)}
                      required
                      disabled={busy}
                    />
                  </Field>
                  <Button disabled={busy || !email.trim()}>Create invite</Button>
                </form>
                {inviteLink && (
                  <Field>
                    <FieldLabel htmlFor="invite-link">Share this invitation link</FieldLabel>
                    <div className="flex gap-2">
                      <Input
                        id="invite-link"
                        value={inviteLink}
                        readOnly
                        onFocus={(event) => event.target.select()}
                      />
                      <Button
                        variant="outline"
                        onClick={() =>
                          navigator.clipboard
                            .writeText(inviteLink)
                            .then(() => toast.success('Invitation link copied.'))
                            .catch(() => toast.error('Select and copy the invitation link.'))
                        }
                      >
                        Copy link
                      </Button>
                    </div>
                  </Field>
                )}
                {invitations.error && (
                  <p role="alert" className="text-sm text-destructive">
                    {invitations.error.message}
                  </p>
                )}
                <ul className="divide-y">
                  {invitations.data?.map((item) => (
                    <li key={item.id} className="flex items-center gap-3 py-2">
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm">{item.email}</p>
                        <p className="text-xs text-muted-foreground">
                          Expires {new Date(item.expiresAt).toLocaleString()}
                        </p>
                      </div>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={busy}
                        onClick={() =>
                          void run(() =>
                            api!(path + `/invitations/${item.id}`, { method: 'DELETE' }),
                          )
                        }
                      >
                        Revoke
                      </Button>
                    </li>
                  ))}
                </ul>
              </section>
            </>
          ) : null}
        </>
      )}
      {section === 'general' && !owner && (
        <Button
          variant="outline"
          className="self-start"
          disabled={busy}
          onClick={() =>
            setConfirm({
              title: 'Leave workspace?',
              description: 'You will need a new invitation to return.',
              action: async () => {
                await api!(path + `/members/${actorId}`, { method: 'DELETE' });
                await navigate({ to: '/workspaces' });
              },
            })
          }
        >
          Leave workspace
        </Button>
      )}
      <AlertDialog open={!!confirm} onOpenChange={(open) => !open && !busy && setConfirm(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{confirm?.title}</AlertDialogTitle>
            <AlertDialogDescription>{confirm?.description}</AlertDialogDescription>
          </AlertDialogHeader>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={busy}
              onClick={(event) => {
                event.preventDefault();
                if (confirm) void run(confirm.action);
              }}
            >
              {busy ? 'Saving…' : 'Confirm'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
