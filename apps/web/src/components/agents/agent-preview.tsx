import { useShellLocation, useShellNavigate } from '@/lib/shell-navigation';
import { useUploads } from '@/components/storage/uploads';
import {
  createContext,
  useCallback,
  useEffect,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import type { AgentTab } from '@/lib/shell-model';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { useWorkspaces } from '@/lib/workspace-directory';
import { useAgentLive } from '@/lib/agent-live';
import { useBoxGraph, type BoxAgent, type BoxGraph } from '@/lib/box-api';
import type { AgentAppearance } from '@/components/agent-appearance';
import { AvatarAppearances, AvatarWorking } from '@/components/agent-avatar';
import { demoBoxGraph } from './box-demo';
import type { ChatMessage, ReplyRef, HumanRequest, InputItem } from '@/lib/agent-api';
import { useAgentOrganization } from '@/lib/agent-organization';
import { useBackend } from '@/lib/backend';
import { demoChat, demoRequests, demoSidebar } from './agent-chat-fixtures';
import { mimeForName, type StorageTextSession } from '@/components/storage/storage-context';
import { useFileSessions } from '@/components/storage/file-sessions';
import { storageApi } from '@/lib/storage-api';
import type { ComposerEditorHandle } from './composer-editor';
import type { ComposerSelection } from './openbot/composer-dom';
import { fileText, fileToken, type FileRef } from '@/lib/file-refs';
import {
  loadStorage,
  updateStorage,
  storageRoots,
  rootId,
  downloadNodes,
  type StorageNode,
} from '@/lib/storage-preview';

export type AgentProfile = {
  appearance?: AgentAppearance;
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

export type PreviewMessage = {
  inputs?: InputItem[];
  id: string;
  text: string;
  created_at: string;
  reply?: ReplyRef | null;
  files: PreviewFile[];
};
type UploadJob = { id: string; status: 'uploading' | 'failed' };
type AgentSession = {
  uploads: UploadJob[];
  feedback: InputItem[];
  reply: ReplyRef | null;
  messages: PreviewMessage[];
  files: string[];
  panelTab: string;
  settingsOpen: boolean;
  mainTab: AgentTab;
  letis: BoxAgent[];
  requestDrafts: Record<string, Record<string, string[]>>;
  requestOpen: string | null;
  requestResults: Record<string, HumanRequest>;
  paused: boolean;
  schedulePaused: boolean;
  schedule?: { title: string; time: string; content: string };
  answers?: Record<string, string[]>;
  approval?: 'accepted' | 'denied';
};
const emptySession = (): AgentSession => ({
  uploads: [],
  feedback: [],
  requestDrafts: {},
  requestOpen: null,
  requestResults: {},
  reply: null,
  messages: [],
  files: [],
  panelTab: 'storage',
  settingsOpen: false,
  mainTab: 'agent',
  letis: [],
  paused: false,
  schedulePaused: false,
});

function usePreviewState() {
  const search = useShellLocation();
  const workspaces = useWorkspaces();
  const workspace = workspaces.find((item) => item.id === search.workspace)!;
  const fixture = workspace.agents.find((item) => item.id === search.agent)!;
  const navigate = useShellNavigate();
  const backend = useBackend();
  const uploads = useUploads();
  const queryClient = useQueryClient();
  const filesApi = useMemo(
    () => (backend.api ? storageApi(backend.api, workspace.id) : null),
    [backend.api, workspace.id],
  );
  const [sessions, setSessions] = useState<Record<string, AgentSession>>(() =>
    Object.fromEntries(workspace.agents.map((agent) => [agent.id, emptySession()])),
  );
  const session = { ...(sessions[fixture.id] ?? emptySession()), mainTab: search.mainTab };
  const drafts = useRef(new Map<string, string>()).current;
  const composers = useRef(new Map<string, ComposerEditorHandle>()).current;
  const scrollPositions = useRef(
    new Map<
      string,
      {
        top: number;
        atEnd: boolean;
        messageId?: string;
        offset?: number;
      }
    >(),
  ).current;
  const boxViews = useRef(
    new Map<
      string,
      {
        viewport?: { x: number; y: number; zoom: number };
        collapsed?: string[];
        schedule?: string;
      }
    >(),
  ).current;
  const selectedLetiId = search.mainTab.startsWith('leti:') ? search.mainTab.slice(5) : undefined;
  const activityMode = search.mainTab === 'activity' || !!selectedLetiId;
  const live = useAgentLive(
    workspace.id,
    fixture.id,
    search.view === 'agents' || search.view === 'boxes',
    fixture.state,
    selectedLetiId ?? fixture.id,
  );
  const boxRoot = search.view === 'boxes' && !selectedLetiId ? search.boxAgent : fixture.id;
  const graphQuery = useBoxGraph(
    workspace.id,
    boxRoot,
    search.view === 'agents' || search.view === 'boxes',
  );
  const [optimistic, setOptimistic] = useState<Record<string, ChatMessage[]>>({});
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
  const fileSessions = useFileSessions();
  const getFileSession = useCallback(
    (id: string) => fileSessions.get(`${fileNodes[id]?.storage}/${id}`) ?? null,
    [fileSessions, fileNodes],
  );
  const setFileSession = useCallback(
    (id: string, value: StorageTextSession | null) => {
      const key = `${value?.node.storage ?? fileNodes[id]?.storage}/${id}`;
      if (value) fileSessions.set(key, value);
      else fileSessions.delete(key);
    },
    [fileSessions, fileNodes],
  );
  async function saveFile(node: StorageNode, text: string) {
    if (new Blob([text]).size > 1_000_000) throw new Error('Text editing is limited to 1 MB.');
    let updated: StorageNode;
    if (filesApi) updated = await filesApi.save(node, text);
    else {
      const blob = new Blob([text], { type: node.mime });
      updated = {
        ...node,
        blob,
        size: blob.size,
        updated: Date.now(),
        version: (node.version ?? 0) + 1,
      };
      await updateStorage(workspace.id, storageRoots(workspace), (snapshot) => {
        const existing = snapshot.nodes.find((n) => n.id === node.id) ?? fileNodes[node.id];
        if (
          !existing ||
          existing.updated !== node.updated ||
          (existing.version ?? 0) !== (node.version ?? 0)
        )
          throw new Error('This file changed since you opened it. Reopen it before saving.');
        return { nodes: [...snapshot.nodes.filter((n) => n.id !== node.id), updated] };
      });
    }
    setFileNodes((current) => ({ ...current, [node.id]: updated }));
    await queryClient.invalidateQueries({ queryKey: ['storage-folder'] });
    await queryClient.invalidateQueries({ queryKey: ['storage-preview'] });
    return updated;
  }
  type ConversationStorage = {
    id: string;
    storage_id: string;
    root_node_id: string;
    workspace_id: string;
    ready: boolean;
  };
  const conversationKey = ['conversation-storage', backend.actorId, workspace.id, fixture.id];
  async function createConversation(): Promise<ConversationStorage> {
    if (backend.api)
      return backend.api<ConversationStorage>(live.path + '/conversation-storage', {
        method: 'POST',
        body: '{}',
      });
    const storage = `${workspace.id}:conversation:${fixture.id}`;
    return {
      id: storage,
      storage_id: storage,
      root_node_id: rootId(storage),
      workspace_id: workspace.id,
      ready: true,
    };
  }
  const conversation = useQuery<ConversationStorage>({
    queryKey: conversationKey,
    enabled: false,
    queryFn: createConversation,
  });
  async function ensureConversation(): Promise<ConversationStorage> {
    return queryClient.fetchQuery({
      queryKey: conversationKey,
      staleTime: Infinity,
      queryFn: createConversation,
    });
  }
  const [fileCloseRequest, setFileCloseRequest] = useState<string | null>(null);
  async function uploadConversation(
    file: File,
    report?: (fraction: number) => void,
  ): Promise<StorageNode> {
    const storage = await ensureConversation();
    let node: StorageNode;
    if (filesApi)
      node = await filesApi.upload(
        storage.storage_id,
        storage.root_node_id,
        file,
        file.name,
        (loaded, total) => report?.(total ? loaded / total : 1),
      );
    else {
      node = {
        id: crypto.randomUUID(),
        storage: storage.storage_id,
        parent: storage.root_node_id,
        name: file.name,
        kind: 'file',
        mime: file.type || mimeForName(file.name),
        size: file.size,
        updated: Date.now(),
        blob: file,
      };
      await updateStorage(workspace.id, storageRoots(workspace), (snapshot) => {
        if (
          snapshot.nodes.some(
            (n) =>
              n.storage === storage.storage_id &&
              n.parent === storage.root_node_id &&
              n.name === file.name &&
              !n.trashed,
          )
        )
          throw new Error('A file with this name already exists. Rename it and retry.');
        return { nodes: [...snapshot.nodes, node] };
      });
    }
    setFileNodes((current) => ({ ...current, [node.id]: node }));
    await queryClient.invalidateQueries({ queryKey: ['storage-folder'] });
    await queryClient.invalidateQueries({ queryKey: ['storage-preview'] });
    return node;
  }
  async function openFileReference(ref: FileRef) {
    try {
      let node = fileNodes[ref.node_id];
      if (filesApi) node = await filesApi.stat(ref.storage_id, ref.node_id);
      else if (!node)
        node = (await loadStorage(workspace.id, storageRoots(workspace))).nodes.find(
          (n) => n.id === ref.node_id && n.storage === ref.storage_id,
        )!;
      if (!node) throw new Error('This file is no longer available.');
      setFileNodes((current) => ({ ...current, [node.id]: node }));
      openFile(node);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not open file.');
    }
  }
  function insertFileIntoDraft(
    agentId: string,
    node: StorageNode,
    label = node.name,
    selection?: ComposerSelection,
  ) {
    const ref = { label, storage_id: node.storage, node_id: node.id };
    const editor = composers.get(agentId);
    if (editor) editor.insertFile(ref, selection);
    else {
      const draft = drafts.get(agentId) ?? '';
      const at = selection ?? { start: draft.length, end: draft.length };
      const prefix = draft.slice(0, at.start);
      drafts.set(
        agentId,
        prefix +
          (prefix && !/\s$/.test(prefix) ? ' ' : '') +
          fileToken(ref) +
          ' ' +
          draft.slice(at.end),
      );
    }
  }
  const [copyRequest, setCopyRequest] = useState<StorageNode | null>(null);
  async function attachFile(
    node: StorageNode,
    copy = false,
    label = node.name,
    selection?: ComposerSelection,
  ) {
    const agentId = fixture.id;
    try {
      let ref: FileRef = { storage_id: node.storage, node_id: node.id, label };
      if (backend.api)
        ref = await backend.api<FileRef>(live.path + '/file-reference', {
          method: 'POST',
          body: JSON.stringify({ ...ref, copy, request_id: crypto.randomUUID() }),
        });
      else if (copy) {
        const storage = await ensureConversation();
        const clone = {
          ...node,
          id: crypto.randomUUID(),
          storage: storage.storage_id,
          parent: storage.root_node_id,
        };
        await updateStorage(workspace.id, storageRoots(workspace), (snapshot) => ({
          nodes: [...snapshot.nodes, clone],
        }));
        ref = { storage_id: clone.storage, node_id: clone.id, label };
        setFileNodes((current) => ({ ...current, [clone.id]: clone }));
      }
      insertFileIntoDraft(
        agentId,
        { ...node, storage: ref.storage_id, id: ref.node_id },
        ref.label,
        selection,
      );
      setCopyRequest(null);
    } catch (error) {
      if (!copy && error instanceof Error && 'status' in error && error.status === 403)
        setCopyRequest(node);
      else toast.error(error instanceof Error ? error.message : 'Could not attach this file.');
    }
  }
  async function queueUpload(file: File, selection?: ComposerSelection) {
    const agentId = fixture.id;
    const id = crypto.randomUUID();
    const patch = (fn: (session: AgentSession) => AgentSession) =>
      setSessions((current) => ({ ...current, [agentId]: fn(current[agentId] ?? emptySession()) }));
    const remove = () =>
      patch((stored) => ({ ...stored, uploads: stored.uploads.filter((job) => job.id !== id) }));
    await uploads.enqueue({
      id,
      name: file.name,
      destination: `${profile.name} · Files`,
      onRemove: remove,
      run: async (report) => {
        patch((stored) => ({
          ...stored,
          uploads: [...stored.uploads.filter((job) => job.id !== id), { id, status: 'uploading' }],
        }));
        try {
          const node = await uploadConversation(file, report);
          insertFileIntoDraft(agentId, node, node.name, selection);
          remove();
        } catch (error) {
          patch((stored) => ({
            ...stored,
            uploads: stored.uploads.map((job) => (job.id === id ? { id, status: 'failed' } : job)),
          }));
          throw error;
        }
      },
    });
  }
  const [profiles, setProfiles] = useState<Record<string, AgentProfile>>(() =>
    Object.fromEntries(
      workspace.agents.map((agent) => [
        agent.id,
        {
          name: agent.name,
          title: agent.role,
          appearance: agent.appearance,
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
  const organization = useAgentOrganization(
    workspace.id,
    workspace.agents.filter((a) => a.pinned).map((a) => a.id),
  );
  const pins = organization.layout.pins.filter((id) => workspace.agents.some((a) => a.id === id));
  const [folderEditor, setFolderEditor] = useState<{
    id: string | null;
    parent_id: string | null;
    name: string;
    agent_id?: string;
  } | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const readKey = ['agent-chat-reads', backend.actorId, workspace.id];
  const readStorage = `openlet-chat-reads:${backend.actorId}:${workspace.id}`;
  const loadReads = (): Record<string, string> => {
    try {
      const saved: unknown = JSON.parse(localStorage.getItem(readStorage) ?? '{}');
      if (
        saved &&
        typeof saved === 'object' &&
        !Array.isArray(saved) &&
        Object.values(saved).every((v) => typeof v === 'string')
      )
        return saved as Record<string, string>;
    } catch {
      /* Preview read markers can be reset safely. */
    }
    return {};
  };
  const reads = useQuery<Record<string, string>>({
    queryKey: readKey,
    enabled: !backend.enabled,
    queryFn: loadReads,
    initialData: backend.enabled ? undefined : loadReads,
    staleTime: Infinity,
  });
  const readRequests = useRef(new Set<string>());
  const markChatRead = useCallback(
    async (through: string) => {
      const key = `${backend.actorId}:${workspace.id}:${fixture.id}:${through}`;
      if (readRequests.current.has(key)) return;
      readRequests.current.add(key);
      try {
        if (backend.enabled) {
          await backend.api!(`/v1/workspaces/${workspace.id}/letas/${fixture.id}/messages/read`, {
            method: 'PUT',
            body: JSON.stringify({ through }),
          });
          await queryClient.invalidateQueries({
            queryKey: ['agents', backend.actorId, workspace.id],
          });
        } else {
          const readKey = ['agent-chat-reads', backend.actorId, workspace.id];
          const next = queryClient.setQueryData<Record<string, string>>(readKey, (current) => ({
            ...current,
            [fixture.id]: through,
          }));
          try {
            localStorage.setItem(readStorage, JSON.stringify(next));
          } catch {
            /* Keep the current tab's read state when storage is unavailable. */
          }
        }
      } catch {
        readRequests.current.delete(key);
      }
    },
    [backend, workspace.id, fixture.id, queryClient, readStorage],
  );
  const [reactionOverrides, setReactionOverrides] = useState<
    Record<string, ChatMessage['reactions']>
  >({});
  const reactionQueues = useRef(new Map<string, Promise<void>>());
  const [panelOpen, setPanelOpen] = useState(false);
  const [panelExpanded, setPanelExpanded] = useState(false);
  useEffect(() => {
    if (!panelOpen) setPanelExpanded(false);
  }, [panelOpen]);
  const sidebarChats = Object.fromEntries(
    workspace.agents.map((agent) => {
      const last = sessions[agent.id]?.messages.at(-1);
      const summary = demoSidebar[agent.id];
      return [
        agent.id,
        backend.enabled
          ? {
              preview: fileText(agent.preview ?? ''),
              updated_at: agent.updated_at ?? '',
              unread_count: agent.unread_count ?? 0,
            }
          : {
              preview: fileText(last?.text ?? summary?.preview ?? ''),
              updated_at: last?.created_at ?? summary?.updated_at ?? '',
              unread_count: reads.data?.[agent.id] ? 0 : (summary?.unread_count ?? 0),
            },
      ];
    }),
  );
  function updateSession(patch: Partial<AgentSession>) {
    setSessions((current) => ({
      ...current,
      [fixture.id]: { ...(current[fixture.id] ?? emptySession()), ...patch },
    }));
    if (patch.mainTab)
      void navigate({
        mainTab: patch.mainTab,
        ...(patch.mainTab === 'agent' ? { view: 'agents' } : {}),
      });
  }
  function savePins(next: string[]) {
    void organization.save({ ...organization.layout, pins: next }).catch(() => {});
  }
  function openFile(file: Pick<PreviewFile, 'id'>) {
    updateSession({
      files: session.files.includes(file.id) ? session.files : [...session.files, file.id],
      panelTab: file.id,
    });
    setPanelOpen(true);
  }
  function closeFile(id: string, discard = false) {
    const draft = getFileSession(id);
    if (!discard && draft?.draft !== undefined && draft.draft !== draft.text) {
      setFileCloseRequest(id);
      return;
    }
    setFileSession(id, null);
    setFileCloseRequest(null);
    const files = session.files.filter((file) => file !== id);
    updateSession({
      files,
      panelTab:
        session.panelTab === id
          ? (files.at(-1) ?? (activityMode ? 'inbox' : 'storage'))
          : session.panelTab,
    });
  }
  function togglePanel() {
    if (!panelOpen && !activityMode) {
      if (session.panelTab === 'inbox') updateSession({ panelTab: 'storage' });
      void ensureConversation().catch((error) => toast.error(error.message));
    }
    setPanelOpen((open) => !open);
  }
  const profile =
    live.enabled && live.profile.data
      ? {
          name: live.profile.data.name,
          title: live.profile.data.title ?? fixture.role,
          appearance: live.profile.data.appearance,
          description: live.profile.data.description,
          instructions: live.settings.data?.system_prompt ?? '',
          model: live.profile.data.model_id ?? 'Default model',
          effort: live.profile.data.reasoning_effort ?? '',
        }
      : (profiles[fixture.id] ?? {
          name: fixture.name,
          title: fixture.role,
          appearance: fixture.appearance,
          description: '',
          instructions: '',
          model: 'Default model',
          effort: '',
        });
  const capabilities = live.enabled
    ? ((live.profile.error ? undefined : live.profile.data?.capabilities) ?? {
        can_chat: false,
        can_view_activity: false,
        can_edit_settings: false,
      })
    : { can_chat: true, can_view_activity: true, can_edit_settings: true };
  const baseMessages = useMemo<ChatMessage[]>(() => {
    if (live.enabled) {
      const remote = live.chat.data?.pages.flatMap((page) => page.items) ?? [];
      const canonicalIds = new Set(remote.map((message) => `${message.role}:${message.id}`));
      return [
        ...remote,
        ...(optimistic[fixture.id] ?? []).filter(
          (message) => !canonicalIds.has(`${message.role}:${message.id}`),
        ),
      ].sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id));
    }
    return [
      ...demoChat(fixture.id),
      ...session.messages.map((message) => ({
        id: message.id,
        role: 'user' as const,
        content: message.text,
        reply: message.reply,
        created_at: message.created_at,
        file_ids: message.files.map((file) => file.id),
      })),
    ];
  }, [live.enabled, live.chat.data, optimistic, fixture.id, session.messages]);
  const chatMessages = useMemo(
    () =>
      baseMessages.map((message) => ({
        ...message,
        reactions:
          reactionOverrides[`${fixture.id}:${message.role}:${message.id}`] ?? message.reactions,
      })),
    [baseMessages, reactionOverrides, fixture.id],
  );
  async function reactMessage(
    message: Pick<ChatMessage, 'id' | 'role' | 'reactions'>,
    emoji: string | null,
  ) {
    const agentId = fixture.id;
    const key = `${agentId}:${message.role}:${message.id}`;
    const previous = message.reactions ?? [];
    const next = previous.filter(
      (r) => !(r.actor_kind === 'user' && r.actor_id === backend.actorId),
    );
    if (emoji) next.push({ actor_kind: 'user', actor_id: backend.actorId, emoji });
    setReactionOverrides((current) => ({ ...current, [key]: next }));
    if (!live.enabled) {
      if (message.role === 'assistant') {
        const payload = {
          actor: { kind: 'user' as const, id: backend.actorId },
          target: {
            message_id: message.id,
            kind: 'outgoing' as const,
            content:
              baseMessages
                .find((m) => m.id === message.id && m.role === message.role)
                ?.content.slice(0, 240) ?? '',
          },
          previous_emoji:
            previous.find((r) => r.actor_kind === 'user' && r.actor_id === backend.actorId)
              ?.emoji ?? null,
          emoji,
        };
        setSessions((current) => {
          const stored = current[agentId] ?? emptySession();
          return {
            ...current,
            [agentId]: {
              ...stored,
              feedback: [
                ...stored.feedback.filter((i) => i.input_payload?.target.message_id !== message.id),
                {
                  id: crypto.randomUUID(),
                  source_kind: 'user',
                  source_id: backend.actorId,
                  source_name: 'You',
                  input_type: 'reaction',
                  silent: true,
                  input_payload: payload,
                  content: `Reacted ${emoji ?? '(removed)'}`,
                },
              ],
            },
          };
        });
      }
      return;
    }
    const operation = (reactionQueues.current.get(key) ?? Promise.resolve()).then(async () => {
      try {
        await live.api!(live.path + `/messages/${message.role}/${message.id}/reaction`, {
          method: 'PUT',
          body: JSON.stringify({ request_id: crypto.randomUUID(), emoji }),
        });
        await live.refresh();
      } catch (error) {
        toast.error(error instanceof Error ? error.message : 'Could not save reaction.');
        void live.refresh();
      } finally {
        if (reactionQueues.current.get(key) === operation) {
          setReactionOverrides((current) => {
            const rest = { ...current };
            delete rest[key];
            return rest;
          });
          reactionQueues.current.delete(key);
        }
      }
    });
    reactionQueues.current.set(key, operation);
    await operation;
  }
  const requests = live.enabled
    ? (live.requests.data?.pages.flatMap((page) => page.items) ?? [])
    : demoRequests(fixture.id).map((request) => session.requestResults[request.id] ?? request);
  async function retryMessage(message: ChatMessage) {
    setOptimistic((current) => ({
      ...current,
      [fixture.id]: (current[fixture.id] ?? []).map((item) =>
        item.id === message.id ? { ...item, status: 'sending' } : item,
      ),
    }));
    try {
      await live.api!(live.path + '/messages', {
        method: 'POST',
        body: JSON.stringify({
          message_id: message.id,
          content: message.content,
          in_reply_to: message.reply?.id ?? null,
          in_reply_to_role: message.reply?.role ?? null,
        }),
      });
      await live.refresh();
      setOptimistic((current) => ({
        ...current,
        [fixture.id]: (current[fixture.id] ?? []).filter((item) => item.id !== message.id),
      }));
    } catch (error) {
      setOptimistic((current) => ({
        ...current,
        [fixture.id]: (current[fixture.id] ?? []).map((item) =>
          item.id === message.id ? { ...item, status: 'failed' } : item,
        ),
      }));
      toast.error(
        error instanceof Error ? error.message : 'Message could not be sent. Retry it below.',
      );
    }
  }
  async function send(text: string) {
    if (session.uploads.length) {
      toast.error('Finish or remove the pending uploads before sending.');
      return;
    }
    if (!text.trim()) return;
    drafts.delete(fixture.id);
    composers.get(fixture.id)?.clear();
    if (live.enabled) {
      const message: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'user',
        content: text.trim(),
        created_at: new Date().toISOString(),
        reply: session.reply,
        status: 'sending',
      };
      setOptimistic((current) => ({
        ...current,
        [fixture.id]: [...(current[fixture.id] ?? []), message],
      }));
      updateSession({ reply: null });
      await retryMessage(message);
    } else
      updateSession({
        messages: [
          ...session.messages,
          {
            id: crypto.randomUUID(),
            text: text.trim(),
            created_at: new Date().toISOString(),
            reply: session.reply,
            files: [],
            inputs: session.feedback.length
              ? [
                  ...session.feedback,
                  {
                    id: crypto.randomUUID(),
                    source_kind: 'user',
                    source_id: backend.actorId,
                    source_name: 'You',
                    content: text.trim(),
                  },
                ]
              : undefined,
          },
        ],
        reply: null,
        feedback: [],
      });
  }
  async function answerRequest(
    request: HumanRequest,
    status: 'answered' | 'accepted' | 'denied',
    response?: HumanRequest['response'],
  ) {
    if (live.enabled) {
      await live.api!(`/v1/hitl-requests/${request.id}/answer`, {
        method: 'POST',
        body: JSON.stringify({ status, response }),
      });
      await live.refresh();
    } else
      updateSession({
        requestResults: {
          ...session.requestResults,
          [request.id]: {
            ...request,
            status,
            response,
            resolved_at: new Date().toISOString(),
            outcome: status === 'accepted' ? { status: 'granted' } : null,
          },
        },
      });
  }
  const graph = useMemo<BoxGraph>(
    () =>
      live.enabled
        ? ({
            agents: graphQuery.data?.pages.flatMap((p) => p.agents) ?? [],
            boxes: graphQuery.data?.pages.flatMap((p) => p.boxes) ?? [],
            edges: graphQuery.data?.pages.flatMap((p) => p.edges) ?? [],
            schedules: graphQuery.data?.pages.flatMap((p) => p.schedules) ?? [],
            roots: graphQuery.data?.pages.flatMap((p) => p.roots) ?? [],
          } as BoxGraph)
        : demoBoxGraph({
            ...workspace,
            agents: workspace.agents.map((a) => ({
              ...a,
              name: profiles[a.id]?.name ?? a.name,
              role: profiles[a.id]?.title ?? a.role,
              appearance: profiles[a.id]?.appearance ?? a.appearance,
            })),
          }),
    [live.enabled, graphQuery.data, workspace, profiles],
  );
  const selectedLeti =
    graph.agents.find((a) => a.id === selectedLetiId && a.leta_id === fixture.id && a.box_id) ??
    session.letis.find((a) => a.id === selectedLetiId);
  useEffect(() => {
    if (!selectedLeti) return;
    setSessions((current) => {
      const stored = current[fixture.id] ?? emptySession();
      return stored.letis.some((a) => a.id === selectedLeti.id)
        ? current
        : {
            ...current,
            [fixture.id]: { ...stored, letis: [...stored.letis, selectedLeti] },
          };
    });
  }, [selectedLeti, fixture.id]);
  useEffect(() => {
    if (search.view !== 'agents' && search.view !== 'boxes') return;
    setSessions((current) => {
      const stored = current[fixture.id] ?? emptySession();
      return {
        ...current,
        [fixture.id]: {
          ...stored,
          mainTab: search.mainTab,
          panelTab: activityMode
            ? 'inbox'
            : stored.panelTab === 'inbox'
              ? 'storage'
              : stored.panelTab,
        },
      };
    });
    setPanelOpen(activityMode || (search.mainTab !== 'box' && session.files.length > 0));
    // Navigation restores the selected surface; toggling a panel within that surface stays local.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fixture.id, search.view, search.mainTab]);
  const activityAgent =
    (selectedLeti ? (graph.agents.find((a) => a.id === selectedLeti.id) ?? selectedLeti) : null) ??
    ({
      id: selectedLetiId ?? fixture.id,
      leta_id: fixture.id,
      box_id: null,
      ...profile,
      model_id: profile.model,
      status: 'idle',
    } as BoxAgent);
  const activityBox = graph.boxes.find((box) => box.id === activityAgent.box_id);
  const activityContact = graph.agents.find(
    (agent) =>
      agent.id ===
      (activityBox && activityBox.representative_agent_id !== activityAgent.id
        ? activityBox.representative_agent_id
        : fixture.id),
  );
  const peerEdge = graph.edges.find(
    (edge) => edge.agent_low_id === activityAgent.id || edge.agent_high_id === activityAgent.id,
  );
  const activityPeer =
    graph.agents.find(
      (agent) =>
        agent.id ===
        (peerEdge?.agent_low_id === activityAgent.id
          ? peerEdge.agent_high_id
          : peerEdge?.agent_low_id),
    ) ?? activityContact;
  return {
    fixture,
    graphQuery,
    graph,
    activityAgent,
    activityContact,
    activityPeer,
    activityMode:
      activityMode && capabilities.can_view_activity && (!selectedLetiId || !!selectedLeti),
    openLeti: (agent: BoxAgent) => {
      setSessions((current) => {
        const stored = current[agent.leta_id] ?? emptySession();
        return {
          ...current,
          [agent.leta_id]: {
            ...stored,
            mainTab: `leti:${agent.id}`,
            panelTab: 'inbox',
            letis: stored.letis.some((a) => a.id === agent.id)
              ? stored.letis
              : [...stored.letis, agent],
          },
        };
      });
      setPanelOpen(true);
      void navigate({
        view: search.view === 'boxes' ? 'boxes' : 'agents',
        agent: agent.leta_id,
        mainTab: `leti:${agent.id}`,
      });
    },
    openRootActivity: (id: string) => {
      setSessions((current) => ({
        ...current,
        [id]: { ...(current[id] ?? emptySession()), mainTab: 'activity', panelTab: 'inbox' },
      }));
      setPanelOpen(true);
      void navigate({ view: 'agents', agent: id, mainTab: 'activity' });
    },
    closeLeti: (id: string) => {
      updateSession({
        letis: session.letis.filter((a) => a.id !== id),
        ...(session.mainTab === `leti:${id}` ? { mainTab: 'box', panelTab: 'storage' } : {}),
      });
      if (session.mainTab === `leti:${id}`) setPanelOpen(false);
    },
    selectMainTab: (tab: AgentSession['mainTab']) => {
      const activity = tab === 'activity' || tab.startsWith('leti:');
      updateSession({
        mainTab: tab,
        ...(activity
          ? { panelTab: 'inbox' }
          : session.panelTab === 'inbox'
            ? { panelTab: 'storage' }
            : {}),
      });
      setPanelOpen(activity || (tab !== 'box' && session.files.length > 0));
    },
    mainTabFor: (id: string) => sessions[id]?.mainTab ?? 'agent',
    fileNodes,
    drafts,
    composers,
    scrollPositions,
    boxViews,
    attachFile,
    queueUpload,
    copyRequest,
    setCopyRequest,
    filesApi,
    conversation,
    ensureConversation,
    uploadConversation,
    openFileReference,
    insertFileIntoDraft,
    fileCloseRequest,
    setFileCloseRequest,
    saveFile,
    getFileSession,
    setFileSession,
    downloadFile: (id: string) =>
      downloadNodes({ nodes: Object.values(fileNodes) }, [id], () => {}),
    workspace,
    profiles: Object.fromEntries(
      workspace.agents.map((a) => [
        a.id,
        (!live.enabled ? profiles[a.id] : undefined) ?? {
          name: a.name,
          title: a.role,
          appearance: a.appearance,
          description: '',
          instructions: '',
          model: 'Default model',
          effort: '',
        },
      ]),
    ),
    profile,
    rememberProfile: (id: string, draft: AgentProfile) =>
      setProfiles((current) => ({ ...current, [id]: draft })),
    live,
    capabilities,
    chatMessages,
    sidebarChats,
    markChatRead,
    requests,
    retryMessage,
    answerRequest,
    pins,
    organization,
    folderEditor,
    setFolderEditor,
    createOpen,
    setCreateOpen,
    reactMessage,
    actorId: backend.actorId,
    session,
    updateSession,
    panelExpanded,
    setPanelExpanded,
    panelOpen: panelOpen,
    setPanelOpen,
    pendingRequests: live.enabled
      ? (live.requests.data?.pages[0]?.pending_count ?? 0)
      : requests.filter((r) => r.status === 'pending').length,
    savePins,
    openFile,
    closeFile,
    togglePanel,
    send,
    saveProfile: async (draft: AgentProfile) => {
      if (live.enabled) {
        await live.api!(live.path + `/agents/${fixture.id}`, {
          method: 'PATCH',
          body: JSON.stringify({
            name: draft.name.trim(),
            title: draft.title,
            ...(draft.appearance
              ? { appearance: { shape: draft.appearance.shape, color: draft.appearance.color } }
              : {}),
            description: draft.description,
            system_prompt: draft.instructions,
            model_id: draft.model === 'Default model' ? null : draft.model,
            reasoning_effort: draft.effort ? draft.effort.toLowerCase() : null,
          }),
        });
        await live.refresh();
      } else setProfiles((current) => ({ ...current, [fixture.id]: draft }));
    },
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

// Interaction drafts live outside the query cache and survive tab/agent switches.
const PreviewContext = createContext<ReturnType<typeof usePreviewState> | null>(null);
export function AgentPreviewProvider({ children }: { children: ReactNode }) {
  const state = usePreviewState();
  const appearances = useMemo(
    () =>
      Object.fromEntries([
        ...state.workspace.agents.flatMap((a) =>
          a.appearance
            ? [
                [a.id, a.appearance],
                [`name:${a.name}`, a.appearance],
              ]
            : [],
        ),
        ...state.graph.agents.flatMap((a) =>
          a.appearance
            ? [
                [a.id, a.appearance],
                [`name:${a.name}`, a.appearance],
              ]
            : [],
        ),
      ]),
    [state.workspace, state.graph],
  );
  const working = useMemo(
    () =>
      Object.fromEntries(
        state.graph.agents.flatMap((agent) => {
          const active = agent.status === 'working' && !state.graphQuery.isError;
          return [
            [agent.id, active],
            [`name:${agent.name}`, active],
          ];
        }),
      ),
    [state.graph, state.graphQuery.isError],
  );
  return (
    <PreviewContext.Provider value={state}>
      <AvatarAppearances value={appearances}>
        <AvatarWorking value={working}>{children}</AvatarWorking>
      </AvatarAppearances>
    </PreviewContext.Provider>
  );
}
export function useAgentPreview() {
  const state = useContext(PreviewContext);
  if (!state) throw new Error('AgentPreviewProvider is missing');
  return state;
}
