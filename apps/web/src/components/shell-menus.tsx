import { useState } from 'react';
import { Link, useNavigate } from '@tanstack/react-router';
import { Check, LogOut, Plus, Settings, UserRound, Layers3 } from 'lucide-react';
import { toast } from 'sonner';
import { accountDraftKeys } from '@/lib/chat-drafts';
import { useOptionalFileSessions } from './storage/file-sessions';
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
import { useBackend } from '@/lib/backend';
import { useWorkspaces } from '@/lib/workspace-directory';
import { AgentAvatar } from './agent-avatar';
import { Button } from './ui/button';
import { WorkspaceCreateDialog } from './workspace-manager';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  DropdownMenuSub,
  DropdownMenuSubTrigger,
  DropdownMenuSubContent,
} from './ui/dropdown-menu';

export function AccountMenu({ workspace }: { workspace?: string }) {
  const { account, actorId, logout } = useBackend();
  const workspaces = useWorkspaces();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const sessions = useOptionalFileSessions();
  const [confirmLogout, setConfirmLogout] = useState(false);
  function signOut() {
    setBusy(true);
    void logout?.()
      .catch((error: Error) => toast.error(error.message))
      .finally(() => setBusy(false));
  }
  const [busy, setBusy] = useState(false);
  const name = account?.displayName || 'Your account';
  return (
    <>
      <DropdownMenu open={open} onOpenChange={setOpen}>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon-lg" aria-label="Your account">
            <AgentAvatar name={name} appearance={account?.appearance} className="size-8" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          side="right"
          align="end"
          sideOffset={8}
          className="w-64 max-w-[calc(100vw-1rem)]"
        >
          <DropdownMenuLabel className="flex items-center gap-3 py-3">
            <AgentAvatar name={name} appearance={account?.appearance} className="size-10" />
            <span className="min-w-0">
              <span className="block truncate">{name}</span>
            </span>
          </DropdownMenuLabel>
          {workspaces.length > 0 && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuGroup className="max-h-72 overflow-y-auto">
                {workspaces.map((item) => (
                  <DropdownMenuSub key={item.id}>
                    <DropdownMenuSubTrigger
                      aria-label={item.name}
                      aria-current={item.id === workspace ? 'true' : undefined}
                      className="gap-2 py-2"
                      onClick={() => {
                        setOpen(false);
                        void navigate({
                          to: '/app/$workspaceId',
                          params: { workspaceId: item.id },
                        });
                      }}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault();
                          setOpen(false);
                          void navigate({
                            to: '/app/$workspaceId',
                            params: { workspaceId: item.id },
                          });
                        }
                      }}
                    >
                      <span className="grid size-4 shrink-0 place-items-center rounded-full border border-current/20">
                        {item.id === workspace && (
                          <Check aria-label="Current workspace" className="size-3!" />
                        )}
                      </span>
                      <Layers3 />
                      <span className="min-w-0 flex-1 truncate">{item.name}</span>
                    </DropdownMenuSubTrigger>
                    <DropdownMenuSubContent aria-label={`${item.name} actions`} className="w-56">
                      <DropdownMenuGroup>
                        <DropdownMenuItem asChild>
                          <Link
                            to="/app/$workspaceId/settings/$section"
                            params={{ workspaceId: item.id, section: 'workspace' }}
                          >
                            <Settings />
                            Workspace settings
                          </Link>
                        </DropdownMenuItem>
                      </DropdownMenuGroup>
                    </DropdownMenuSubContent>
                  </DropdownMenuSub>
                ))}
              </DropdownMenuGroup>
              <DropdownMenuGroup>
                <DropdownMenuItem onSelect={() => setCreating(true)}>
                  <Plus />
                  New workspace
                </DropdownMenuItem>
              </DropdownMenuGroup>
            </>
          )}
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            {workspace &&
              [
                { section: 'profile', label: 'Your profile', icon: UserRound },
                { section: 'general', label: 'Your settings', icon: Settings },
                { section: 'workspace', label: 'Workspace settings', icon: Layers3 },
              ].map(({ section, label, icon: Icon }) => (
                <DropdownMenuItem key={section} asChild>
                  <Link
                    to="/app/$workspaceId/settings/$section"
                    params={{ workspaceId: workspace, section }}
                  >
                    <Icon />
                    {label}
                  </Link>
                </DropdownMenuItem>
              ))}
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuItem
              disabled={!logout || busy}
              onSelect={(event) => {
                event.preventDefault();
                const dirty = [...(sessions?.values() ?? [])].some(
                  (session) => session.draft !== undefined && session.draft !== session.text,
                );
                if (dirty || accountDraftKeys(actorId).length) setConfirmLogout(true);
                else signOut();
              }}
            >
              <LogOut />
              {busy ? 'Signing out…' : 'Sign out'}
            </DropdownMenuItem>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
      <WorkspaceCreateDialog open={creating} onOpenChange={setCreating} />
      <AlertDialog open={confirmLogout} onOpenChange={(open) => !busy && setConfirmLogout(open)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Sign out and discard drafts?</AlertDialogTitle>
            <AlertDialogDescription>
              Unsaved file changes and unsent messages on this device will be removed. Save or send
              them first if you want to keep them.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Keep working</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={busy}
              onClick={(event) => {
                event.preventDefault();
                signOut();
              }}
            >
              {busy ? 'Signing out…' : 'Sign out and discard'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
