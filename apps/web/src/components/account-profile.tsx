import { useState } from 'react';
import { useBackend } from '@/lib/backend';
import { agentAppearance } from './agent-appearance';
import { AvatarPicker } from './avatar-picker';
import { Button } from './ui/button';
import { Field, FieldDescription, FieldGroup, FieldLabel } from './ui/field';
import { Input } from './ui/input';

export function AccountProfile() {
  const { account, updateAccount } = useBackend();
  const [name, setName] = useState(account?.displayName ?? '');
  const [appearance, setAppearance] = useState(() => {
    const { shape, color } = agentAppearance(name, account?.appearance);
    return { shape, color };
  });
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  return (
    <form
      className="flex max-w-xl flex-col gap-6"
      onSubmit={async (event) => {
        event.preventDefault();
        if (!updateAccount) return;
        setSaving(true);
        setError('');
        setStatus('');
        try {
          await updateAccount({ displayName: name.trim(), appearance });
          setStatus('Profile saved.');
        } catch (error) {
          setError((error as Error).message);
        } finally {
          setSaving(false);
        }
      }}
    >
      <FieldGroup>
        <Field>
          <FieldLabel>Avatar</FieldLabel>
          <AvatarPicker
            name={name || 'You'}
            value={appearance}
            onChange={setAppearance}
            disabled={saving}
          />
          <FieldDescription>
            Your name and avatar are visible to workspace members.
          </FieldDescription>
        </Field>
        <Field>
          <FieldLabel htmlFor="display-name">Display name</FieldLabel>
          <Input
            id="display-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
            maxLength={255}
            disabled={saving}
            autoComplete="nickname"
          />
        </Field>
      </FieldGroup>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {status && (
        <p role="status" className="text-sm text-muted-foreground">
          {status}
        </p>
      )}
      <Button
        type="submit"
        className="self-start"
        disabled={!updateAccount || saving || !name.trim()}
      >
        {saving ? 'Saving…' : 'Save profile'}
      </Button>
    </form>
  );
}
