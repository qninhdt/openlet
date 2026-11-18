import type { AgentAppearance } from '@/components/agent-appearance';

export type Preferences = {
  theme: 'system' | 'light' | 'dark';
  sendShortcut: 'enter' | 'modifier-enter';
  messageSound: boolean;
};
export const defaultPreferences: Preferences = {
  theme: 'system',
  sendShortcut: 'enter',
  messageSound: true,
};
export type Account = {
  id: string;
  displayName: string;
  avatarUrl?: string;
  appearance?: AgentAppearance;
  preferences?: Partial<Preferences>;
};
