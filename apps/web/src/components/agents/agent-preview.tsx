import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react';
import { useSearch } from '@tanstack/react-router';
import { toast } from 'sonner';
import { workspaces } from '@/lib/shell-model';
import { mimeForName, type StorageTextSession } from '@/components/storage/storage-context';
import { downloadNodes, type StorageNode } from '@/lib/storage-preview';

export type AgentProfile = {
  name: string;
  title: string;
  description: string;
  instructions: string;
  model: string;
  effort: string;
};
export type PreviewFile = { id: string; name: string; language: string; content: string };
export const previewFiles: PreviewFile[] = [
  {
    id: 'launch-plan',
    name: 'Launch plan.md',
    language: 'markdown',
    content:
      '# Friday\u2019s launch plan\n\nThe release is planned for **Friday, November 20 at 10:00, Vietnam time**.\n\n## Audience\n\nThe first release targets workspace owners. It does not promise general availability or dedicated computers.\n\n## Checklist\n\n- [x] Research summary \u2014 Scout\n- [x] Release configuration \u2014 Forge\n- [x] Budget validation \u2014 $250 of $300\n- [ ] Announcement wording \u2014 Linh\n- [ ] Owner approval before publishing\n\n## Channels\n\n| Channel | Owner | Budget | Status |\n| --- | --- | --- | --- |\n| Blog and changelog | Forge | $0 | Ready |\n| Newsletter | Pulse | $120 | In review |\n| Social posts | Scout | $80 | Ready |\n| Contingency | Atlas | $50 | Reserved |\n\n## Next step\n\nConfirm the channels, audience and announcement copy. Nothing is published by this plan.\n',
  },
  {
    id: 'research',
    name: 'Research notes.md',
    language: 'markdown',
    content:
      '# Research notes\n\nThese fictional interview notes are sample data for the UI demo.\n\n## Shared files and ownership\n\n> \u201cI lose time finding which file an agent used. A shared place with clear ownership would help.\u201d \u2014 Interview P03\n\nP01 and P07 also described switching between files and conversations to track who owns a task.\n\n## Evidence boundaries\n\n- Shared files and clear ownership are recurring needs.\n- No controlled productivity measurement was collected.\n- Do not use percentage improvements in the announcement.\n\n## Source verification\n\nThe original P03 transcript is in the owner\u2019s Personal storage. The working notes can guide the draft; the quotation needs verification before publication.\n\n## Launch scope\n\nThe first announcement goes to workspace owners. Broader availability is a separate decision.\n',
  },
  {
    id: 'release',
    name: 'release.ts',
    language: 'typescript',
    content:
      "type Channel = 'blog' | 'newsletter' | 'social';\n\nexport const release = {\n  title: 'A shared place for your work',\n  scheduledAt: '2026-11-20T10:00:00+07:00',\n  channels: ['blog', 'newsletter'] as Channel[],\n};\n",
  },
  {
    id: 'budget',
    name: 'Launch budget.csv',
    language: 'csv',
    content:
      'Channel,Owner,Budget USD,Status\nBlog,Forge,0,Ready\nNewsletter,Pulse,120,In review\nSocial posts,Scout,80,Ready\nContingency,Atlas,50,Reserved\n',
  },
  {
    id: 'announcement',
    name: 'Announcement.md',
    language: 'markdown',
    content:
      '# A shared place for your work\n\nYour files, decisions and agents can now live in the same workspace.\n\n## What is ready\n\n- Nested folders and shared storage\n- Agent conversations and clear ownership\n- Human approval before the next step\n\n## Before Friday\n\nConfirm the audience, proofread the changelog and approve the final launch budget.\n',
  },
  {
    id: 'check-release',
    name: 'check_release.py',
    language: 'python',
    content:
      'import csv\nimport io\nfrom pathlib import Path\n\nprint("Loading Launch budget.csv")\nbudget = Path("Launch budget.csv").read_text(encoding="utf-8")\nprint("Checking UTF-8 input... OK")\nrows = list(csv.DictReader(io.StringIO(budget)))\nassert all(key in rows[0] for key in ["Channel", "Owner", "Budget USD"])\nprint("Checking required columns... OK")\nassert all(row["Owner"] for row in rows), "Every channel needs an owner"\nprint("Checking owners... OK")\nfor row in rows:\n    print(f"  {row[\'Channel\']:<14}{row[\'Owner\']:<10}${row[\'Budget USD\']}")\ntotal = sum(int(row["Budget USD"]) for row in rows)\nprint(f"Budget: ${total} / $300")\nif total > 300:\n    raise SystemExit(f"ERROR: Budget exceeds limit: {total}")\nprint(f"Remaining headroom: ${300 - total}")\nprint(f"Validated {len(rows)} budget rows")\nprint("All checks passed.")\n',
  },
];

export type PreviewMessage = { id: string; text: string; reply?: string; files: PreviewFile[] };
type AgentSession = {
  draft: string;
  reply: string;
  attachments: PreviewFile[];
  messages: PreviewMessage[];
  files: string[];
  panelTab: string;
  settingsOpen: boolean;
  mainTab: 'agent' | 'overview';
  paused: boolean;
  schedulePaused: boolean;
  schedule?: { title: string; time: string; content: string };
  answers?: Record<string, string[]>;
  approval?: 'accepted' | 'denied';
};
const emptySession = (): AgentSession => ({
  draft: '',
  reply: '',
  attachments: [],
  messages: [],
  files: [],
  panelTab: '',
  settingsOpen: false,
  mainTab: 'agent',
  paused: false,
  schedulePaused: false,
});

function usePreviewState() {
  const search = useSearch({ from: '/app' });
  const workspace = workspaces.find((item) => item.id === search.workspace)!;
  const fixture = workspace.agents.find((item) => item.id === search.agent)!;
  const [fileNodes, setFileNodes] = useState<Record<string, StorageNode>>(() =>
    Object.fromEntries(
      previewFiles.map((file) => {
        const blob = new Blob([file.content], { type: mimeForName(file.name) });
        return [
          file.id,
          {
            id: file.id,
            storage: `${workspace.id}:team`,
            parent: `root:${workspace.id}:team`,
            kind: 'file',
            name: file.name,
            mime: blob.type,
            blob,
            size: blob.size,
            updated: 0,
          },
        ];
      }),
    ),
  );
  const fileSessions = useRef<Record<string, StorageTextSession | null>>({});
  const getFileSession = useCallback((id: string) => fileSessions.current[id] ?? null, []);
  const setFileSession = useCallback((id: string, value: StorageTextSession | null) => {
    fileSessions.current[id] = value;
  }, []);
  async function saveFile(node: StorageNode, text: string) {
    const existing = fileNodes[node.id];
    if (!existing || existing.blob !== node.blob || existing.updated !== node.updated)
      throw new Error('This file changed since you opened it. Reopen it before saving.');
    const blob = new Blob([text], { type: node.mime });
    if (blob.size > 1_000_000) throw new Error('Text editing is limited to 1 MB.');
    const updated = { ...node, blob, size: blob.size, updated: Date.now() };
    setFileNodes((current) => ({ ...current, [node.id]: updated }));
    return updated;
  }
  const [profiles, setProfiles] = useState<Record<string, AgentProfile>>(() =>
    Object.fromEntries(
      workspace.agents.map((agent) => [
        agent.id,
        {
          name: agent.name,
          title: agent.role,
          description:
            agent.id === 'scout'
              ? 'Finds useful sources, checks the details, and turns research into clear notes.'
              : 'Keeps the work moving, coordinates with other agents, and brings decisions back to you.',
          instructions:
            'Be clear and practical. Work with the files in this workspace. Ask when a decision needs human input.',
          model: 'Claude Sonnet 4.5',
          effort: 'Medium',
        },
      ]),
    ),
  );
  const [pins, setPins] = useState<string[]>(() => {
    try {
      const saved: unknown = JSON.parse(
        localStorage.getItem(`openlet-agent-pins:${workspace.id}`) ?? 'null',
      );
      if (Array.isArray(saved))
        return [
          ...new Set(
            saved.filter(
              (id): id is string =>
                typeof id === 'string' && workspace.agents.some((agent) => agent.id === id),
            ),
          ),
        ];
    } catch {
      /* A missing browser preference falls back to the fixture. */
    }
    return workspace.agents.filter((agent) => agent.pinned).map((agent) => agent.id);
  });
  const [sessions, setSessions] = useState<Record<string, AgentSession>>(() =>
    Object.fromEntries(workspace.agents.map((agent) => [agent.id, emptySession()])),
  );
  const [panelOpen, setPanelOpen] = useState(false);
  const [panelWidth, setPanelWidth] = useState(360);
  const session = sessions[fixture.id] ?? emptySession();
  function updateSession(patch: Partial<AgentSession>) {
    setSessions((current) => ({
      ...current,
      [fixture.id]: { ...(current[fixture.id] ?? emptySession()), ...patch },
    }));
  }
  function savePins(next: string[]) {
    setPins(next);
    try {
      localStorage.setItem(`openlet-agent-pins:${workspace.id}`, JSON.stringify(next));
    } catch {
      toast.error('Pin order could not be saved in this browser.');
    }
  }
  function openFile(file: PreviewFile) {
    updateSession({
      files: session.files.includes(file.id) ? session.files : [...session.files, file.id],
      panelTab: file.id,
    });
    setPanelOpen(true);
  }
  function closeFile(id: string) {
    const files = session.files.filter((file) => file !== id);
    updateSession({
      files,
      panelTab: session.panelTab === id ? (files.at(-1) ?? '') : session.panelTab,
    });
    if (!files.length) setPanelOpen(false);
  }
  function togglePanel() {
    if (!session.files.length) return;
    setPanelOpen((open) => !open);
  }
  function send(text: string) {
    if (!text.trim() && !session.attachments.length) return;
    updateSession({
      messages: [
        ...session.messages,
        {
          id: crypto.randomUUID(),
          text: text.trim(),
          reply: session.reply,
          files: session.attachments,
        },
      ],
      draft: '',
      reply: '',
      attachments: [],
    });
  }
  return {
    fixture,
    fileNodes,
    saveFile,
    getFileSession,
    setFileSession,
    downloadFile: (id: string) =>
      downloadNodes({ nodes: Object.values(fileNodes) }, [id], () => {}),
    workspace,
    profiles,
    profile: profiles[fixture.id],
    pins,
    session,
    updateSession,
    panelOpen: panelOpen && session.files.length > 0,
    setPanelOpen,
    pendingRequests: Number(!session.answers) + Number(!session.approval),
    panelWidth,
    setPanelWidth,
    savePins,
    openFile,
    closeFile,
    togglePanel,
    send,
    updateProfile: (patch: Partial<AgentProfile>) =>
      setProfiles((current) => ({
        ...current,
        [fixture.id]: { ...current[fixture.id], ...patch },
      })),
    openSettings: (id = fixture.id) => {
      setSessions((current) => ({
        ...current,
        [id]: { ...(current[id] ?? emptySession()), settingsOpen: true },
      }));
    },
  };
}

// shortcut: local UI sessions only; replace with the conversation adapter when connecting the API.
const PreviewContext = createContext<ReturnType<typeof usePreviewState> | null>(null);
export function AgentPreviewProvider({ children }: { children: ReactNode }) {
  const state = usePreviewState();
  return <PreviewContext.Provider value={state}>{children}</PreviewContext.Provider>;
}
export function useAgentPreview() {
  const state = useContext(PreviewContext);
  if (!state) throw new Error('AgentPreviewProvider is missing');
  return state;
}
