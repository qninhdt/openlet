export type DraftReply = { id: string; role: 'user' | 'assistant'; content: string };
export type ChatDraft = { text: string; reply: DraftReply | null };
export const draftKey = (actor: string, workspace: string, agent: string) =>
  `openlet-draft:${actor}:${workspace}:${agent}`;
export function readDraft(key: string): ChatDraft {
  try {
    const saved = JSON.parse(localStorage.getItem(key) ?? '{}');
    const reply = saved.reply;
    return {
      text: typeof saved.text === 'string' ? saved.text : '',
      reply:
        reply &&
        typeof reply.id === 'string' &&
        ['user', 'assistant'].includes(reply.role) &&
        typeof reply.content === 'string'
          ? reply
          : null,
    };
  } catch {
    return { text: '', reply: null };
  }
}
export function writeDraft(key: string, patch: Partial<ChatDraft>) {
  const next = { ...readDraft(key), ...patch };
  if (!next.text && !next.reply) localStorage.removeItem(key);
  else localStorage.setItem(key, JSON.stringify(next));
}

export function accountDraftKeys(actor: string) {
  try {
    return Object.keys(localStorage).filter((key) => key.startsWith(`openlet-draft:${actor}:`));
  } catch {
    return [];
  }
}
export function clearAccountDrafts(actor: string) {
  for (const key of accountDraftKeys(actor)) {
    try {
      localStorage.removeItem(key);
    } catch {
      /* Account-scoped data remains inaccessible to other accounts. */
    }
  }
}
