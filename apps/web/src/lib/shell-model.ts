export const destinations = ['agents', 'boxes', 'storage', 'settings'] as const;
export type Destination = (typeof destinations)[number];

export const settingsSections = [
  'profile',
  'general',
  'appearance',
  'workspace',
  'members',
] as const;
export type SettingsSection = (typeof settingsSections)[number];
export type AgentTab = 'agent' | 'overview' | 'activity' | 'box' | `leti:${string}`;
export type ShellLocation = {
  workspace: string;
  view: Destination;
  agent: string;
  section: SettingsSection;
  storage: string;
  folder: string;
  file: string;
  boxAgent: string;
  mainTab: AgentTab;
};

export function parseLegacySearch(search: Record<string, unknown>): ShellLocation {
  const view =
    destinations.find(
      (item) =>
        item ===
        (search.view === 'library'
          ? 'storage'
          : search.view === 'schedule'
            ? 'boxes'
            : search.view),
    ) ?? 'agents';
  const section = settingsSections.find((item) => item === search.section) ?? 'general';
  const text = (key: string) => (typeof search[key] === 'string' ? (search[key] as string) : '');
  return {
    workspace: text('workspace'),
    view,
    agent: text('agent'),
    section,
    storage: text('storage'),
    folder: text('folder'),
    file: text('file'),
    boxAgent: text('boxAgent'),
    mainTab: 'agent',
  };
}
