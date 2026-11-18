import { useRef, useState } from 'react';
import { Pause, Play, Trash2 } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { useNavigate } from '@tanstack/react-router';
import type { AgentResource } from '@/lib/agent-api';
import { draftKey, writeDraft } from '@/lib/chat-drafts';
import { useBackend } from '@/lib/backend';
import { Button } from '@/components/ui/button';
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
  AlertDialogAction,
} from '@/components/ui/alert-dialog';
import { useAgentPreview } from './agent-preview';

export function AgentControls({ action }: { action: 'pause' | 'delete' }) {
  const p = useAgentPreview();
  const { api, actorId } = useBackend();
  const client = useQueryClient();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [deleting, setDeleting] = useState(false);
  const command = useRef<{ action: string; id: string } | null>(null);
  const paused = !!p.live.profile.data?.paused;
  async function run(action: 'pause' | 'resume' | 'delete') {
    if (busy) return;
    if (command.current?.action !== action) command.current = { action, id: crypto.randomUUID() };
    setBusy(true);
    setError('');
    try {
      await api!(p.live.path + (action === 'delete' ? '' : '/' + action), {
        method: action === 'delete' ? 'DELETE' : 'POST',
        body: JSON.stringify({ request_id: command.current.id }),
      });
      if (action === 'delete') {
        client.setQueryData<AgentResource[]>(['agents', actorId, p.workspace.id], (items) =>
          items?.filter((agent) => agent.id !== p.resource.id),
        );
        try {
          writeDraft(draftKey(actorId, p.workspace.id, p.resource.id), { text: '', reply: null });
        } catch {
          /* Session access is removed by the server. */
        }
        await navigate({
          to: '/app/$workspaceId',
          params: { workspaceId: p.workspace.id },
          replace: true,
        });
      }
      await Promise.all([
        ...(action === 'delete' ? [] : [p.live.refresh()]),
        client.invalidateQueries({ queryKey: ['agents', actorId, p.workspace.id] }),
        client.invalidateQueries({ queryKey: ['box-graph', actorId, p.workspace.id] }),
        client.invalidateQueries({ queryKey: ['agent-sidebar', actorId, p.workspace.id] }),
      ]);
      command.current = null;
      setDeleting(false);
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        {action === 'pause' && p.capabilities.can_edit_settings && (
          <Button
            variant="outline"
            size="sm"
            disabled={busy || p.live.profile.data?.state !== 'active'}
            onClick={() => void run(paused ? 'resume' : 'pause')}
          >
            {paused ? <Play /> : <Pause />}
            {busy ? 'Updating…' : paused ? 'Resume' : 'Pause'}
          </Button>
        )}
        {action === 'delete' && p.capabilities.can_delete && (
          <Button variant="destructive" size="sm" disabled={busy} onClick={() => setDeleting(true)}>
            <Trash2 />
            Delete
          </Button>
        )}
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <AlertDialog open={deleting} onOpenChange={(open) => !busy && setDeleting(open)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {p.profile.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              This permanently deletes the agent, its Box, conversations and files. This cannot be
              undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Keep agent</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={busy}
              onClick={(event) => {
                event.preventDefault();
                void run('delete');
              }}
            >
              {busy ? 'Deleting…' : 'Delete agent'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
