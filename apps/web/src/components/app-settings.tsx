import { useEffect, useState } from 'react';
import { useTheme } from 'next-themes';
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from '@/components/ui/field';
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

const defaultPreferences = {
  sendShortcut: 'enter',
  showAgentSteps: false,
  compactMessageActions: true,
};

function readPreferences() {
  try {
    const saved = JSON.parse(localStorage.getItem('openlet-preferences') ?? '{}');
    return {
      sendShortcut: saved.sendShortcut === 'modifier-enter' ? 'modifier-enter' : 'enter',
      showAgentSteps: saved.showAgentSteps === true,
      compactMessageActions: saved.compactMessageActions !== false,
    };
  } catch {
    return defaultPreferences;
  }
}

export function AppSettings({ section }: { section: SettingsSection }) {
  const [preferences, setPreferences] = useState(readPreferences);
  const { theme, setTheme } = useTheme();
  useEffect(() => {
    try {
      localStorage.setItem('openlet-preferences', JSON.stringify(preferences));
    } catch {
      /* Browser storage may be disabled. */
    }
  }, [preferences]);

  return (
    <div className="h-full overflow-y-auto p-6 max-sm:p-4">
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">
        {section === 'general' ? 'General' : 'Appearance'}
      </h1>
      <section aria-labelledby="settings-section-title" className="flex flex-col gap-2">
        <h2 id="settings-section-title" className="text-sm font-medium">
          {section === 'general' ? 'Conversations' : 'Colors'}
        </h2>
        <FieldGroup className="settings-group gap-0 overflow-hidden rounded-2xl border">
          {section === 'general' ? (
            <>
              <Field variant="row" className="settings-row" orientation="responsive">
                <FieldContent>
                  <FieldLabel htmlFor="send-shortcut">Send shortcut</FieldLabel>
                  <FieldDescription>
                    Choose the keys that send a message on this device and browser.
                  </FieldDescription>
                </FieldContent>
                <Select
                  value={preferences.sendShortcut}
                  onValueChange={(sendShortcut) => setPreferences({ ...preferences, sendShortcut })}
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
                  <FieldLabel htmlFor="show-agent-steps">Show agent steps</FieldLabel>
                  <FieldDescription>
                    Open the thinking and tool steps of each turn by default on this device and
                    browser.
                  </FieldDescription>
                </FieldContent>
                <Switch
                  id="show-agent-steps"
                  checked={preferences.showAgentSteps}
                  onCheckedChange={(showAgentSteps) =>
                    setPreferences({ ...preferences, showAgentSteps })
                  }
                />
              </Field>
              <div className="px-4">
                <Separator />
              </div>
              <Field variant="row" className="settings-row" orientation="horizontal">
                <FieldContent>
                  <FieldLabel htmlFor="compact-message-actions">Compact message actions</FieldLabel>
                  <FieldDescription>
                    Show message actions beside a message. When this is off, actions appear below
                    it.
                  </FieldDescription>
                </FieldContent>
                <Switch
                  id="compact-message-actions"
                  checked={preferences.compactMessageActions}
                  onCheckedChange={(compactMessageActions) =>
                    setPreferences({ ...preferences, compactMessageActions })
                  }
                />
              </Field>
            </>
          ) : (
            <Field variant="row" className="settings-row" orientation="responsive">
              <FieldContent>
                <FieldLabel htmlFor="theme-choice">Theme</FieldLabel>
                <FieldDescription>Choose how Openlet looks on this device.</FieldDescription>
              </FieldContent>
              <Select value={theme} onValueChange={setTheme}>
                <SelectTrigger id="theme-choice" className="w-full shrink-0 @md/field-group:w-42">
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
    </div>
  );
}
