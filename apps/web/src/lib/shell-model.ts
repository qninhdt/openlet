export const destinations = ['agents', 'schedule', 'storage', 'settings'] as const;
export type Destination = (typeof destinations)[number];

// shortcut: preview fixtures only; replace with workspace and Leta queries when wiring pages.
export const workspaces = [
  {
    id: 'personal',
    name: 'Personal workspace',
    agents: [
      { id: 'atlas', name: 'Atlas', role: 'Assistant', pinned: true },
      { id: 'scout', name: 'Scout', role: 'Research', pinned: true },
      { id: 'forge', name: 'Forge', role: 'Builder', pinned: false },
      { id: 'pulse', name: 'Pulse', role: 'Signals', pinned: false },
    ],
  },
  {
    id: 'team',
    name: 'Team workspace',
    agents: [{ id: 'sage', name: 'Sage', role: 'Team assistant', pinned: true }],
  },
];

export const settingsSections = ['general', 'appearance'] as const;
export type SettingsSection = (typeof settingsSections)[number];
export type ShellSearch = {
  workspace: string;
  view: Destination;
  agent: string;
  section: SettingsSection;
  storage: string;
  folder: string;
  file: string;
};

export function parseShellSearch(search: Record<string, unknown>): ShellSearch {
  const workspace = workspaces.find((item) => item.id === search.workspace) ?? workspaces[0];
  const view =
    destinations.find((item) => item === (search.view === 'library' ? 'storage' : search.view)) ??
    'agents';
  const agent = workspace.agents.find((item) => item.id === search.agent) ?? workspace.agents[0];
  const section = settingsSections.find((item) => item === search.section) ?? 'general';
  const text = (key: string) => (typeof search[key] === 'string' ? (search[key] as string) : '');
  return {
    workspace: workspace.id,
    view,
    agent: agent.id,
    section,
    storage: text('storage'),
    folder: text('folder'),
    file: text('file'),
  };
}
