import { useRef, useState } from 'react';
import { Link, Navigate, useNavigate } from '@tanstack/react-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { LoaderCircle, Plus } from 'lucide-react';
import { BackendProvider, useBackend } from '@/lib/backend';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { AccountMenu } from './shell-menus';
import { AppLogo } from './app-logo';
import { Field, FieldLabel } from './ui/field';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from './ui/dialog';
import { AppLoading } from './public/page-state';
type Workspace = { id: string; name: string };

export function WorkspaceCreateDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent aria-describedby={undefined} className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>New workspace</DialogTitle>
        </DialogHeader>
        <WorkspaceCreateForm onCreated={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}
function WorkspaceCreateForm({ onCreated }: { onCreated?: () => void }) {
  const { api, actorId } = useBackend();
  const client = useQueryClient();
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const busy = useRef(false);
  const request = useRef({ name: '', id: '' });
  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={async (event) => {
        event.preventDefault();
        if (busy.current || !name.trim()) return;
        busy.current = true;
        setPending(true);
        setError('');
        if (request.current.name !== name.trim())
          request.current = { name: name.trim(), id: crypto.randomUUID() };
        try {
          const workspace = await api!<Workspace>('/v1/workspaces', {
            method: 'POST',
            body: JSON.stringify({ name: name.trim(), request_id: request.current.id }),
          });
          await client.invalidateQueries({ queryKey: ['workspaces', actorId] });
          onCreated?.();
          await navigate({
            to: '/app/$workspaceId',
            params: { workspaceId: workspace.id },
          });
        } catch (issue) {
          setError(
            issue instanceof Error ? issue.message : 'Could not create workspace. Try again.',
          );
        } finally {
          busy.current = false;
          setPending(false);
        }
      }}
    >
      <Field>
        <FieldLabel htmlFor="new-workspace-name">Workspace name</FieldLabel>
        <Input
          id="new-workspace-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="My workspace"
          maxLength={200}
          required
          autoFocus
          disabled={pending}
        />
      </Field>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <Button type="submit" disabled={pending || !name.trim()}>
        {pending ? <LoaderCircle className="size-4 animate-spin" /> : <Plus className="size-4" />}
        {pending ? 'Creating workspace…' : 'Create workspace'}
      </Button>
    </form>
  );
}

export function WorkspacesPage() {
  return (
    <BackendProvider>
      <WorkspaceEntry />
    </BackendProvider>
  );
}
function WorkspaceEntry() {
  const { api, actorId } = useBackend();
  const directory = useQuery({
    queryKey: ['workspaces', actorId],
    queryFn: () => api!<{ workspaces?: Workspace[] }>('/v1/workspaces?page_size=100'),
  });
  if (directory.isPending) return <AppLoading label="Loading workspaces…" />;
  if (directory.error)
    return (
      <div className="space-y-3 p-6">
        <p role="alert">{directory.error.message}</p>
        <Button onClick={() => void directory.refetch()}>Retry</Button>
      </div>
    );
  const first = directory.data.workspaces?.[0];
  if (first) return <Navigate to="/app/$workspaceId" params={{ workspaceId: first.id }} replace />;
  return (
    <div className="flex h-dvh bg-background text-foreground">
      <nav
        aria-label="Account navigation"
        className="page-rail flex w-13 shrink-0 flex-col items-center py-4"
      >
        <Link to="/" aria-label="Openlet home">
          <AppLogo />
        </Link>
        <div className="mt-auto">
          <AccountMenu />
        </div>
      </nav>
      <main id="main-content" className="flex min-w-0 flex-1 items-center justify-center p-6">
        <section className="w-full max-w-md">
          <h1 className="mb-6 text-xl font-medium">Create a workspace</h1>
          <WorkspaceCreateForm />
        </section>
      </main>
    </div>
  );
}
