import { useShellNavigate } from '@/lib/shell-navigation';
import { toast } from 'sonner';
import { lazy, Suspense, useCallback, useRef, useState } from 'react';
import {
  Check,
  ChevronDown,
  SlidersHorizontal,
  Maximize2,
  Minimize2,
  X,
  Circle,
  Inbox,
  HardDrive,
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { SHAPES, COLORS } from '@/vendor/bloub/skins';
import { agentAppearance } from '@/components/agent-appearance';
import { AgentAvatar } from '@/components/agent-avatar';
import { Button } from '@/components/ui/button';
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { cn } from '@/lib/utils';
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
import { ProviderLogo } from './provider-logo';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';

const FileViewer = lazy(() =>
  import('@/components/storage/storage-viewer').then((module) => ({ default: module.FileViewer })),
);

const providers = [
  { name: 'Anthropic', models: ['Claude Sonnet 4.5', 'Claude Opus 4.1'] },
  { name: 'OpenAI', models: ['GPT-5', 'GPT-5 mini'] },
  { name: 'Google', models: ['Gemini 2.5 Pro', 'Gemini 2.5 Flash'] },
] as const;

export function AgentModelPicker({
  compact = false,
  value,
  onChange,
}: {
  compact?: boolean;
  value?: AgentProfile;
  onChange?: (patch: Partial<AgentProfile>) => void;
}) {
  const p = useAgentPreview();
  const profile = value ?? p.profile;
  const updateProfile = onChange ?? p.updateProfile;
  const current =
    providers.find((provider) => provider.models.some((model) => model === profile.model)) ??
    providers[0];
  const [providerName, setProviderName] = useState<string>(current.name);
  const [query, setQuery] = useState('');
  const provider = providers.find((item) => item.name === providerName)!;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          aria-label="Choose agent model"
          className={cn('min-w-0 gap-1.5 font-normal', !compact && 'max-w-64')}
        >
          <ProviderLogo provider={current.name} />
          <span className={cn('truncate', !compact && 'max-[1000px]:max-w-24 max-[820px]:hidden')}>
            {profile.model}
          </span>
          <span className={cn('text-muted-foreground', !compact && 'max-[1100px]:hidden')}>
            · {profile.effort}
          </span>
          <ChevronDown />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-84 max-w-[calc(100vw-16px)] overflow-hidden p-0">
        <div className="flex min-h-64">
          <ToggleGroup
            type="single"
            value={providerName}
            onValueChange={(value) => value && setProviderName(value)}
            aria-label="Model provider"
            className="flex w-13 shrink-0 flex-col justify-start rounded-none bg-muted/50 p-1.5"
          >
            {providers.map(({ name }) => (
              <ToggleGroupItem
                key={name}
                value={name}
                aria-label={name}
                title={name}
                size="icon-sm"
              >
                <ProviderLogo provider={name} />
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          <div className="flex min-w-0 flex-1 flex-col gap-3 p-3">
            <div>
              <p className="text-sm font-medium">{provider.name}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">Preview models</p>
            </div>
            <InputGroup>
              <InputGroupInput
                aria-label="Search models"
                placeholder="Search models"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
              <InputGroupAddon>
                <SlidersHorizontal />
              </InputGroupAddon>
            </InputGroup>
            <div role="radiogroup" aria-label="Agent model" className="flex flex-col gap-0.5">
              {provider.models
                .filter((model) => model.toLowerCase().includes(query.toLowerCase()))
                .map((model) => (
                  <Button
                    key={model}
                    role="radio"
                    aria-checked={profile.model === model}
                    variant="ghost"
                    size="sm"
                    className="justify-start font-normal"
                    onClick={() => updateProfile({ model })}
                  >
                    {profile.model === model ? <Check /> : <Circle />}
                    <span className="truncate">{model}</span>
                  </Button>
                ))}
              {!provider.models.some((model) =>
                model.toLowerCase().includes(query.toLowerCase()),
              ) && <p className="py-4 text-caption text-muted-foreground">No matching models.</p>}
            </div>
            <Field orientation="horizontal" className="mt-auto">
              <FieldLabel htmlFor="model-effort">Effort</FieldLabel>
              <Select value={profile.effort} onValueChange={(effort) => updateProfile({ effort })}>
                <SelectTrigger id="model-effort" className="ml-auto w-30">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {['Low', 'Medium', 'High'].map((effort) => (
                      <SelectItem key={effort} value={effort}>
                        {effort}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}

export function AgentPanelHeader() {
  const p = useAgentPreview();
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
          ...p.session.files.flatMap((id) => {
            const file = p.fileNodes[id];
            return file
              ? [
                  {
                    id,
                    label: file.name,
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

export function AgentSettingsDialog() {
  const p = useAgentPreview();
  return (
    <Dialog
      open={p.session.settingsOpen}
      onOpenChange={(settingsOpen) => p.updateSession({ settingsOpen })}
    >
      {p.session.settingsOpen && <AgentSettingsForm key={p.fixture.id} />}
    </Dialog>
  );
}

export function AgentCreateDialog() {
  const p = useAgentPreview();
  return (
    <Dialog open={p.createOpen} onOpenChange={p.setCreateOpen}>
      {p.createOpen && <AgentSettingsForm create />}
    </Dialog>
  );
}

function AgentSettingsForm({ create = false }: { create?: boolean }) {
  const p = useAgentPreview();
  const createAgent = useCreateAgent();
  const navigate = useShellNavigate();
  const creation = useRef<{ signature: string; id: string } | null>(null);
  const [draft, setDraft] = useState<AgentProfile>(() =>
    create
      ? {
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
        }
      : { ...p.profile, appearance: p.profile.appearance ?? agentAppearance(p.profile.name) },
  );
  const close = () => (create ? p.setCreateOpen(false) : p.updateSession({ settingsOpen: false }));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const catalog = useQuery({
    queryKey: [...p.live.scope, 'models'],
    enabled: p.live.enabled,
    queryFn: () =>
      p.live.api!<{ models: { model_id: string; reasoning_efforts: string[] }[] }>(
        `/v1/workspaces/${p.workspace.id}/letas/models`,
      ),
  });
  const dirty = JSON.stringify(draft) !== JSON.stringify(p.profile);
  const updateDraft = (patch: Partial<AgentProfile>) =>
    setDraft((current) => ({ ...current, ...patch }));
  return (
    <DialogContent
      className="max-h-[calc(100dvh-2rem)] gap-0 overflow-y-auto p-0 sm:max-w-xl"
      onInteractOutside={(event) => {
        if (dirty) event.preventDefault();
      }}
    >
      <DialogHeader className="px-5 pt-5 pb-4">
        <DialogTitle>{create ? 'New agent' : 'Agent settings'}</DialogTitle>
        <DialogDescription>
          {create
            ? 'Choose a name, model and instructions.'
            : `Identity, model and instructions for ${p.profile.name}.`}
        </DialogDescription>
      </DialogHeader>
      <form
        aria-label={create ? 'New agent' : 'Agent settings'}
        onSubmit={async (event) => {
          event.preventDefault();
          if (!draft.name.trim()) return;
          setSaving(true);
          setError('');
          try {
            if (create) {
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
              if (!p.live.enabled) p.rememberProfile(id, draft);
              close();
              await navigate({ view: 'agents', agent: id, mainTab: 'agent' });
            } else {
              await p.saveProfile(draft);
              close();
            }
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
            <Popover>
              <PopoverTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  className="size-16 shrink-0 p-1"
                  aria-label="Choose agent avatar"
                >
                  <AgentAvatar
                    name={draft.name || 'Agent'}
                    appearance={draft.appearance}
                    className="size-14"
                  />
                </Button>
              </PopoverTrigger>
              <PopoverContent align="start" aria-label="Agent avatar">
                <Field>
                  <FieldLabel>Shape</FieldLabel>
                  <ToggleGroup
                    type="single"
                    value={draft.appearance?.shape}
                    onValueChange={(shape) =>
                      shape &&
                      updateDraft({
                        appearance: { ...agentAppearance(draft.name, draft.appearance), shape },
                      })
                    }
                    className="grid w-full grid-cols-4"
                  >
                    {SHAPES.map(({ id }) => (
                      <ToggleGroupItem
                        key={id}
                        value={id}
                        aria-label={`Shape ${id}`}
                        className="size-12"
                      >
                        <AgentAvatar
                          name={draft.name || 'Agent'}
                          appearance={{
                            ...agentAppearance(draft.name, draft.appearance),
                            shape: id,
                          }}
                          className="size-9"
                        />
                      </ToggleGroupItem>
                    ))}
                  </ToggleGroup>
                </Field>
                <Field>
                  <FieldLabel>Color</FieldLabel>
                  <ToggleGroup
                    type="single"
                    value={draft.appearance?.color}
                    onValueChange={(color) =>
                      color &&
                      updateDraft({
                        appearance: { ...agentAppearance(draft.name, draft.appearance), color },
                      })
                    }
                    className="grid w-full grid-cols-6"
                  >
                    {COLORS.map(({ id, hex }) => (
                      <ToggleGroupItem
                        key={id}
                        value={id}
                        aria-label={`Color ${id}`}
                        className="size-8"
                      >
                        <span className="size-5 rounded-full border" style={{ background: hex }} />
                      </ToggleGroupItem>
                    ))}
                  </ToggleGroup>
                </Field>
              </PopoverContent>
            </Popover>
            <Field className="min-w-0 flex-1">
              <FieldLabel htmlFor="agent-name">Name</FieldLabel>
              <Input
                id="agent-name"
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
          <Field>
            <FieldLabel>Model</FieldLabel>
            <div className="flex min-w-0 items-center rounded-md border px-1 py-0.5">
              {p.live.enabled ? (
                <div className="flex w-full flex-col gap-3">
                  <Select
                    value={draft.model}
                    onValueChange={(model) => updateDraft({ model, effort: '' })}
                  >
                    <SelectTrigger aria-label="Agent model" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="Default model">Default model</SelectItem>
                      {catalog.data?.models.map((model) => (
                        <SelectItem key={model.model_id} value={model.model_id}>
                          {model.model_id}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Select
                    value={draft.effort || 'default'}
                    onValueChange={(effort) =>
                      updateDraft({ effort: effort === 'default' ? '' : effort })
                    }
                  >
                    <SelectTrigger aria-label="Reasoning effort">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="default">Default effort</SelectItem>
                      {catalog.data?.models
                        .find((model) => model.model_id === draft.model)
                        ?.reasoning_efforts.map((effort) => (
                          <SelectItem key={effort} value={effort}>
                            {effort}
                          </SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                  {catalog.error && (
                    <p role="alert" className="text-caption text-destructive">
                      {catalog.error.message}
                    </p>
                  )}
                </div>
              ) : (
                <AgentModelPicker compact value={draft} onChange={updateDraft} />
              )}
            </div>
          </Field>
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
          <Button type="submit" disabled={saving || (!create && !dirty) || !draft.name.trim()}>
            {saving ? (create ? 'Creating…' : 'Saving…') : create ? 'Create agent' : 'Save changes'}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}

function FilePreview({ id }: { id: string }) {
  const p = useAgentPreview();
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
