import { useState } from 'react';
import { useBackend, usePreferences } from '@/lib/backend';
import type { Preferences } from '@/lib/account';
import { AccountProfile } from './account-profile';
import { WorkspaceSettings } from './workspace-settings';
import { Field, FieldContent, FieldGroup, FieldLabel } from '@/components/ui/field';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { Switch } from '@/components/ui/switch';
import type { SettingsSection } from '@/lib/shell-model';

export function AppSettings({ section }: { section: SettingsSection }) {
  const { updateAccount } = useBackend();
  const preferences = usePreferences();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const setPreferences = async (next: Partial<Preferences>) => {
    if (!updateAccount) return;
    setSaving(true);
    setError('');
    try {
      await updateAccount({ preferences: next });
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-[960px] px-5 py-8 sm:px-10 sm:py-10">
        <h1 className="mb-8 text-xl font-medium">
          {
            {
              general: 'General',
              appearance: 'Appearance',
              profile: 'Your profile',
              workspace: 'General',
              members: 'Members',
            }[section]
          }
        </h1>
        {error && (
          <p role="alert" className="mb-4 text-sm text-destructive">
            {error}
          </p>
        )}
        {section === 'profile' ? (
          <AccountProfile />
        ) : section === 'workspace' || section === 'members' ? (
          <WorkspaceSettings section={section === 'members' ? 'members' : 'general'} />
        ) : (
          <fieldset disabled={saving || !updateAccount} className="min-w-0">
            <section
              aria-label={section === 'general' ? 'General settings' : 'Appearance settings'}
              className="flex flex-col gap-2"
            >
              <FieldGroup className="settings-group gap-0 overflow-hidden rounded-2xl border">
                {section === 'general' ? (
                  <>
                    <Field variant="row" className="settings-row" orientation="responsive">
                      <FieldContent>
                        <FieldLabel htmlFor="send-shortcut">Send shortcut</FieldLabel>
                      </FieldContent>
                      <Select
                        value={preferences.sendShortcut}
                        onValueChange={(sendShortcut) =>
                          void setPreferences({
                            sendShortcut: sendShortcut as Preferences['sendShortcut'],
                          })
                        }
                      >
                        <SelectTrigger
                          id="send-shortcut"
                          className="w-full shrink-0 @md/field-group:w-42"
                        >
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectGroup>
                            <SelectItem value="enter">Enter to send</SelectItem>
                            <SelectItem value="modifier-enter">Ctrl / ⌘ Enter to send</SelectItem>
                          </SelectGroup>
                        </SelectContent>
                      </Select>
                    </Field>
                    <div className="px-4">
                      <Separator />
                    </div>
                    <Field variant="row" className="settings-row" orientation="horizontal">
                      <FieldContent>
                        <FieldLabel htmlFor="message-sound">Message sounds</FieldLabel>
                      </FieldContent>
                      <Switch
                        id="message-sound"
                        checked={preferences.messageSound}
                        onCheckedChange={(messageSound) => void setPreferences({ messageSound })}
                      />
                    </Field>
                  </>
                ) : (
                  <Field variant="row" className="settings-row" orientation="responsive">
                    <FieldContent>
                      <FieldLabel htmlFor="theme-choice">Theme</FieldLabel>
                    </FieldContent>
                    <Select
                      value={preferences.theme}
                      onValueChange={(theme) =>
                        void setPreferences({ theme: theme as Preferences['theme'] })
                      }
                    >
                      <SelectTrigger
                        id="theme-choice"
                        className="w-full shrink-0 @md/field-group:w-42"
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectGroup>
                          <SelectItem value="system">System</SelectItem>
                          <SelectItem value="light">Light</SelectItem>
                          <SelectItem value="dark">Dark</SelectItem>
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                  </Field>
                )}
              </FieldGroup>
            </section>
          </fieldset>
        )}
      </div>
    </div>
  );
}
