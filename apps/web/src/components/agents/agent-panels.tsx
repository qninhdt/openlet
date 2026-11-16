import { lazy, Suspense, useCallback, useState } from 'react';
import { Check, ChevronDown, FileText, SlidersHorizontal, X, Circle } from 'lucide-react';
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
import { previewFiles, useAgentPreview, type AgentProfile } from './agent-preview';
import { EditorTabs } from './editor-tabs';
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
        selected={p.session.panelTab}
        onSelect={(panelTab) => p.updateSession({ panelTab })}
        items={[
          ...p.session.files.flatMap((id) => {
            const file = previewFiles.find((file) => file.id === id);
            return file
              ? [{ id, label: file.name, icon: <FileText />, onClose: () => p.closeFile(id) }]
              : [];
          }),
        ]}
      />
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

function AgentSettingsForm() {
  const p = useAgentPreview();
  const [draft, setDraft] = useState(p.profile);
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
        <DialogTitle>Agent settings</DialogTitle>
        <DialogDescription>
          Identity, model and instructions for {p.profile.name}.
        </DialogDescription>
      </DialogHeader>
      <form
        aria-label="Agent settings"
        onSubmit={(event) => {
          event.preventDefault();
          if (!draft.name.trim()) return;
          p.updateProfile({ ...draft, name: draft.name.trim() });
          p.updateSession({ settingsOpen: false });
        }}
      >
        <FieldGroup className="gap-5 px-5 pb-5">
          <div className="flex items-center gap-4">
            <AgentAvatar name={p.fixture.name} className="size-14 shrink-0" />
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
              <AgentModelPicker compact value={draft} onChange={updateDraft} />
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
          <span className="mr-auto text-caption text-muted-foreground max-sm:w-full">
            Saved in this preview only
          </span>
          <Button
            type="button"
            variant="ghost"
            onClick={() => p.updateSession({ settingsOpen: false })}
          >
            Cancel
          </Button>
          <Button type="submit" disabled={!dirty || !draft.name.trim()}>
            Save changes
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
        textAccess={{ writable: true, saveText: p.saveFile, getTextSession, setTextSession }}
      />
    </Suspense>
  );
}

export function AgentPanel() {
  const p = useAgentPreview();
  return (
    <aside aria-label="Agent side panel" className="h-full min-h-0 bg-sidebar">
      {p.session.files.map((id) => {
        const file = previewFiles.find((file) => file.id === id);
        return file ? (
          <div key={id} hidden={p.session.panelTab !== id} className="h-full">
            <FilePreview id={id} />
          </div>
        ) : null;
      })}
    </aside>
  );
}
