import { AgentModelPicker } from './agent-model-picker';
import { AvatarPicker } from '@/components/avatar-picker';
import { useShellNavigate } from '@/lib/shell-navigation';
import { toast } from 'sonner';
import { lazy, Suspense, useCallback, useRef, useState } from 'react';
import { useQueries } from '@tanstack/react-query';
import { useBackend } from '@/lib/backend';
import { Maximize2, Minimize2, X, Inbox, HardDrive } from 'lucide-react';
import { SHAPES, COLORS } from '@/vendor/bloub/skins';
import { Button } from '@/components/ui/button';
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import type { StorageTextSession } from '@/components/storage/storage-context';
import { useCreateAgent } from '@/lib/workspace-directory';
import { ConversationStorage } from './conversation-storage';
import { FileIcon } from '@/components/storage/file-icon';
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
import { useAgentPreview, type AgentProfile } from './agent-preview';
import { EditorTabs } from './editor-tabs';
import { ActivityInbox } from './activity-inbox';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';

const FileViewer = lazy(() =>
  import('@/components/storage/storage-viewer').then((module) => ({ default: module.FileViewer })),
);

export function AgentPanelHeader() {
  const p = useAgentPreview();
  const { actorId } = useBackend();
  const paths = useQueries({
    queries: p.session.files.map((id) => ({
      queryKey: ['file-path', actorId, p.fileNodes[id]?.storage, id],
      queryFn: () => p.filesApi.path(p.fileNodes[id]),
      enabled: !!p.fileNodes[id],
    })),
  });
  return (
    <div className="flex h-(--shell-header-height) min-w-0 items-center">
      <EditorTabs
        label="Agent side panel tabs"
        selected={
          p.activityMode
            ? p.session.panelTab
            : p.session.panelTab === 'inbox'
              ? 'storage'
              : p.session.panelTab
        }
        onSelect={(panelTab) => {
          p.updateSession({ panelTab });
          if (panelTab === 'storage')
            void p.ensureConversation().catch((error) => toast.error(error.message));
        }}
        items={[
          { id: 'storage', label: 'Files', icon: <HardDrive /> },
          ...(p.activityMode ? [{ id: 'inbox', label: 'Inbox', icon: <Inbox /> }] : []),
          ...p.session.files.flatMap((id, index) => {
            const file = p.fileNodes[id];
            return file
              ? [
                  {
                    id,
                    label: file.name,
                    tooltip: paths[index].data,
                    icon: <FileIcon node={file} />,
                    onClose: () => p.closeFile(id),
                  },
                ]
              : [];
          }),
        ]}
      />
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label={p.panelExpanded ? 'Restore side panel' : 'Expand side panel'}
        aria-pressed={p.panelExpanded}
        className="hidden shrink-0 min-[722px]:inline-flex"
        onClick={() => p.setPanelExpanded((expanded) => !expanded)}
      >
        {p.panelExpanded ? <Minimize2 /> : <Maximize2 />}
      </Button>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label="Close side panel"
        className="mr-1 shrink-0"
        onClick={() => p.setPanelOpen(false)}
      >
        <X />
      </Button>
    </div>
  );
}

export function AgentCreateDialog() {
  const p = useAgentPreview();
  return (
    <Dialog open={p.createOpen} onOpenChange={p.setCreateOpen}>
      {p.createOpen && <AgentCreateForm />}
    </Dialog>
  );
}

function AgentCreateForm() {
  const p = useAgentPreview();
  const createAgent = useCreateAgent();
  const navigate = useShellNavigate();
  const creation = useRef<{ signature: string; id: string } | null>(null);
  const [draft, setDraft] = useState<AgentProfile>(() => ({
    name: '',
    title: 'Assistant',
    description: '',
    instructions: '',
    model: 'Default model',
    effort: '',
    appearance: {
      shape: SHAPES[crypto.getRandomValues(new Uint8Array(1))[0] % SHAPES.length].id,
      color: COLORS.filter((c) => !['encre', 'creme', 'gris', 'brun'].includes(c.id))[
        crypto.getRandomValues(new Uint8Array(1))[0] % 8
      ].id,
    },
  }));
  const close = () => p.setCreateOpen(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const updateDraft = (patch: Partial<AgentProfile>) =>
    setDraft((current) => ({ ...current, ...patch }));
  return (
    <DialogContent
      aria-describedby={undefined}
      className="max-h-[calc(100dvh-2rem)] gap-0 overflow-y-auto p-0 sm:max-w-xl"
      onInteractOutside={(event) => {
        if (draft.name.trim()) event.preventDefault();
      }}
    >
      <DialogHeader className="px-5 pt-5 pb-4">
        <DialogTitle>New agent</DialogTitle>
      </DialogHeader>
      <form
        aria-label="New agent"
        onSubmit={async (event) => {
          event.preventDefault();
          if (!draft.name.trim()) return;
          setSaving(true);
          setError('');
          try {
            const signature = JSON.stringify(draft);
            if (creation.current?.signature !== signature)
              creation.current = { signature, id: crypto.randomUUID() };
            const id = await createAgent(p.workspace.id, {
              request_id: creation.current.id,
              name: draft.name.trim(),
              title: draft.title,
              ...(draft.appearance
                ? { appearance: { shape: draft.appearance.shape, color: draft.appearance.color } }
                : {}),
              description: draft.description,
              system_prompt: draft.instructions,
              model_id: draft.model === 'Default model' ? null : draft.model,
              reasoning_effort: draft.effort ? draft.effort.toLowerCase() : null,
            });
            close();
            await navigate({ view: 'agents', agent: id, mainTab: 'agent' });
          } catch (error) {
            setError(error instanceof Error ? error.message : 'Could not save settings.');
          } finally {
            setSaving(false);
          }
        }}
      >
        {error && (
          <p role="alert" className="px-5 pb-4 text-sm text-destructive">
            {error}
          </p>
        )}
        <FieldGroup className="gap-5 px-5 pb-5">
          <div className="flex items-center gap-4">
            <AvatarPicker
              name={draft.name || 'Agent'}
              value={draft.appearance ?? undefined}
              onChange={(appearance) => updateDraft({ appearance })}
            />
            <Field className="min-w-0 flex-1">
              <FieldLabel htmlFor="agent-name">Name</FieldLabel>
              <Input
                id="agent-name"
                pattern="[A-Za-z]+"
                required
                maxLength={255}
                value={draft.name}
                onChange={(event) => updateDraft({ name: event.target.value })}
              />
            </Field>
          </div>
          <Field>
            <FieldLabel htmlFor="agent-title">Title</FieldLabel>
            <Input
              id="agent-title"
              required
              maxLength={255}
              value={draft.title}
              onChange={(event) => updateDraft({ title: event.target.value })}
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="agent-description">Description</FieldLabel>
            <Textarea
              id="agent-description"
              rows={2}
              maxLength={4000}
              value={draft.description}
              onChange={(event) => updateDraft({ description: event.target.value })}
            />
          </Field>
          <AgentModelPicker value={draft} onChange={updateDraft} />
          <Field>
            <FieldLabel htmlFor="agent-instructions">Instructions</FieldLabel>
            <Textarea
              id="agent-instructions"
              rows={6}
              maxLength={32000}
              value={draft.instructions}
              onChange={(event) => updateDraft({ instructions: event.target.value })}
            />
          </Field>
        </FieldGroup>
        <DialogFooter className="flex-row flex-wrap items-center justify-end border-t px-5 py-3">
          <Button type="button" variant="ghost" onClick={close}>
            Cancel
          </Button>
          <Button type="submit" disabled={saving || !draft.name.trim()}>
            {saving ? 'Creating…' : 'Create agent'}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}

function FilePreview({ id }: { id: string }) {
  const p = useAgentPreview();
  const focus = p.fileFocus?.id === id ? p.fileFocus : undefined;
  const { getFileSession, setFileSession } = p;
  const getTextSession = useCallback(() => getFileSession(id), [getFileSession, id]);
  const setTextSession = useCallback(
    (session: StorageTextSession | null) => setFileSession(id, session),
    [setFileSession, id],
  );
  return (
    <Suspense
      fallback={
        <p role="status" className="p-4 text-sm text-muted-foreground">
          Loading preview…
        </p>
      }
    >
      <FileViewer
        embedded
        active={p.panelOpen && p.session.panelTab === id}
        node={p.fileNodes[id]}
        focusLine={focus && 'line' in focus ? focus : undefined}
        focusPage={focus && 'page' in focus ? focus : undefined}
        onClose={() => p.closeFile(id)}
        onDownload={() => void p.downloadFile(id)}
        textAccess={{
          writable: !p.fileNodes[id].readonly,
          saveText: p.saveFile,
          getTextSession,
          setTextSession,
        }}
      />
    </Suspense>
  );
}

export function AgentPanel() {
  const p = useAgentPreview();
  return (
    <aside aria-label="Agent side panel" className="h-full min-h-0 bg-sidebar">
      <div
        hidden={
          (p.session.panelTab === 'inbox' && !p.activityMode ? 'storage' : p.session.panelTab) !==
          'storage'
        }
        className="h-full"
      >
        <ConversationStorage />
      </div>
      <AlertDialog
        open={!!p.fileCloseRequest}
        onOpenChange={(open) => !open && p.setFileCloseRequest(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Close without saving?</AlertDialogTitle>
            <AlertDialogDescription>Your changes have not been saved.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep editing</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => p.closeFile(p.fileCloseRequest!, true)}
            >
              Discard changes
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      {p.activityMode && (
        <div hidden={p.session.panelTab !== 'inbox'} className="h-full">
          <ActivityInbox />
        </div>
      )}
      {p.session.files.map((id) => {
        const file = p.fileNodes[id];
        return file ? (
          <div
            key={id}
            hidden={
              (p.session.panelTab === 'inbox' && !p.activityMode
                ? 'storage'
                : p.session.panelTab) !== id
            }
            className="h-full"
          >
            <FilePreview id={id} />
          </div>
        ) : null;
      })}
    </aside>
  );
}
