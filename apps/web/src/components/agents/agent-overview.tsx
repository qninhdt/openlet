import { useState } from 'react';
import { ChevronRight } from 'lucide-react';
import { AgentControls } from './agent-controls';
import { AgentAccess } from './agent-access';
import { AgentModelPicker } from './agent-model-picker';
import { AvatarPicker } from '@/components/avatar-picker';
import { AgentAvatar } from '@/components/agent-avatar';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Field, FieldLabel } from '@/components/ui/field';
import { useAgentPreview, type AgentProfile } from './agent-preview';
import { useAgentScroll } from './agent-scroll';

export function AgentOverview() {
  const p = useAgentPreview();
  const scroll = useAgentScroll<HTMLElement>(`${p.resource.id}:overview`);
  const [edit, setEdit] = useState<{ id: string; profile: AgentProfile } | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const draft = edit?.id === p.resource.id ? edit.profile : p.profile;
  const dirty = JSON.stringify(draft) !== JSON.stringify(p.profile);
  const editable = p.capabilities.can_edit_settings;
  const ready = !!p.live.profile.data && !!p.live.settings.data;
  const update = (patch: Partial<AgentProfile>) =>
    setEdit({ id: p.resource.id, profile: { ...draft, ...patch } });
  const pending = p.requests.filter((request) => request.status === 'pending');
  return (
    <section
      {...scroll.viewportProps}
      aria-label="Agent overview"
      className="h-full min-w-0 overflow-y-auto bg-background"
    >
      <div className="mx-auto w-full max-w-3xl px-5 py-8 sm:px-10 sm:py-10">
        <header className="mb-8 flex items-start gap-4">
          {editable && ready ? (
            <AvatarPicker
              name={draft.name}
              value={draft.appearance ?? undefined}
              onChange={(appearance) => update({ appearance })}
            />
          ) : (
            <AgentAvatar name={draft.name} appearance={draft.appearance} className="size-16" />
          )}
          <div className="min-w-0 flex-1 pt-1">
            {editable ? (
              <>
                <Input
                  aria-label="Agent name"
                  value={draft.name}
                  maxLength={255}
                  disabled={saving || !ready}
                  onChange={(e) => update({ name: e.target.value })}
                  className="h-8 border-transparent bg-transparent px-1 text-xl font-medium shadow-none hover:border-input focus-visible:border-input md:text-xl"
                />
                <Input
                  aria-label="Agent title"
                  value={draft.title}
                  maxLength={255}
                  disabled={saving || !ready}
                  onChange={(e) => update({ title: e.target.value })}
                  className="h-7 border-transparent bg-transparent px-1 text-sm text-muted-foreground shadow-none hover:border-input focus-visible:border-input"
                />
              </>
            ) : (
              <>
                <h2 className="truncate text-xl font-medium">{draft.name}</h2>
                <p className="mt-1 text-sm text-muted-foreground">{draft.title}</p>
              </>
            )}
          </div>
          <div className="pt-1">
            <AgentControls action="pause" />
          </div>
        </header>
        {!!pending.length && (
          <section aria-label="For you" className="mb-8">
            <h3 className="mb-2 text-sm font-medium">For you</h3>
            <ul className="divide-y border-y">
              {pending.map((request) => (
                <li key={request.id}>
                  <button
                    type="button"
                    className="flex w-full items-center gap-3 rounded-md px-2 py-3 text-left text-sm hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring"
                    onClick={() => p.updateSession({ mainTab: 'agent', requestOpen: request.id })}
                  >
                    <span className="min-w-0 flex-1">{request.title}</span>
                    <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
        <form
          className="flex flex-col gap-6"
          aria-label="Edit agent"
          onSubmit={async (event) => {
            event.preventDefault();
            if (!draft.name.trim() || !ready || saving) return;
            setSaving(true);
            setError('');
            try {
              await p.saveProfile(draft);
              setEdit(null);
            } catch (issue) {
              setError((issue as Error).message);
            } finally {
              setSaving(false);
            }
          }}
        >
          <Field>
            <FieldLabel htmlFor="overview-description">Description</FieldLabel>
            <Textarea
              id="overview-description"
              value={draft.description}
              rows={2}
              maxLength={4000}
              disabled={!editable || !ready || saving}
              onChange={(e) => update({ description: e.target.value })}
            />
          </Field>
          <div className="flex min-w-0 items-center justify-between gap-4 border-y py-3">
            <span className="text-sm font-medium">Model</span>
            <AgentModelPicker
              value={draft}
              onChange={update}
              disabled={!editable || !ready || saving}
            />
          </div>
          {editable && (
            <Field>
              <FieldLabel htmlFor="overview-instructions">Instructions</FieldLabel>
              <Textarea
                id="overview-instructions"
                value={draft.instructions}
                rows={8}
                maxLength={32000}
                disabled={!ready || saving}
                onChange={(e) => update({ instructions: e.target.value })}
              />
            </Field>
          )}
          {(error || p.live.settings.error) && (
            <p role="alert" className="text-sm text-destructive">
              {error || p.live.settings.error?.message}
            </p>
          )}
          {dirty && editable && (
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="ghost"
                disabled={saving}
                onClick={() => {
                  setEdit(null);
                  setError('');
                }}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={saving || !ready || !draft.name.trim()}>
                {saving ? 'Saving…' : 'Save changes'}
              </Button>
            </div>
          )}
        </form>
        {editable && (
          <div className="mt-8 border-t pt-6">
            <AgentAccess key={p.resource.id} />
          </div>
        )}
        {p.capabilities.can_delete && (
          <div className="mt-8 border-t pt-5">
            <AgentControls action="delete" />
          </div>
        )}
      </div>
    </section>
  );
}
