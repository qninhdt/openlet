import { messageSent } from '@/lib/message-sound';
import { draftKey, readDraft, writeDraft, type ChatDraft } from '@/lib/chat-drafts';
import { useNavigate as useRouterNavigate, useSearch } from '@tanstack/react-router';
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
import { useWorkspaces, type Workspace } from '@/lib/workspace-directory';
import { useAgentLive } from '@/lib/agent-live';
import { useBoxGraph, type BoxAgent, type BoxGraph } from '@/lib/box-api';
import type { AgentAppearance } from '@/components/agent-appearance';
import { AvatarAppearances, AvatarWorking } from '@/components/agent-avatar';
import type { ChatMessage, ReplyRef, HumanRequest } from '@/lib/agent-api';
import { useAgentOrganization } from '@/lib/agent-organization';
import { useBackend } from '@/lib/backend';
import { type StorageTextSession } from '@/components/storage/storage-context';
import { useFileSessions } from '@/components/storage/file-sessions';
import { storageApi } from '@/lib/storage-api';
import type { ComposerEditorHandle } from './composer-editor';
import type { ComposerSelection } from './openbot/composer-dom';
import { fileLink, fileReferences, fileText, type FileRef } from '@/lib/file-refs';
import { toUiChatMessage } from '@/lib/chat-api';
import { downloadNodes, type StorageNode } from '@/lib/storage-preview';

export type AgentProfile = {
  appearance?: AgentAppearance;
  name: string;
  title: string;
  description: string;
  instructions: string;
  model: string;
  effort: string;
};
type UploadJob = { id: string; status: 'uploading' | 'failed' };
type AgentSession = {
  uploads: UploadJob[];
  reply: ReplyRef | null;
  files: string[];
  panelTab: string;
  mainTab: AgentTab;
  letis: BoxAgent[];
  requestDrafts: Record<string, Record<string, string[]>>;
  requestOpen: string | null;
};
const emptySession = (): AgentSession => ({
  uploads: [],
  requestDrafts: {},
  requestOpen: null,
  reply: null,
  files: [],
  panelTab: 'storage',
  mainTab: 'agent',
  letis: [],
});

function usePreviewState() {
  const search = useShellLocation();
  const workspaces = useWorkspaces();
  const workspace = workspaces.find((item) => item.id === search.workspace)!;
  const resource: Workspace['agents'][number] = workspace.agents.find(
    (item) => item.id === search.agent,
  ) ?? { id: '', name: '', role: '', pinned: false };
  const navigate = useShellNavigate();
  const routerNavigate = useRouterNavigate();
  const messageSearch = useSearch({ strict: false });
  const backend = useBackend();
  const uploads = useUploads();
  const queryClient = useQueryClient();
  const filesApi = useMemo(
    () => storageApi(backend.api!, workspace.id, backend.request, backend.actorId),
    [backend.api, backend.request, backend.actorId, workspace.id],
  );
  const [sessions, setSessions] = useState<Record<string, AgentSession>>(() =>
    Object.fromEntries(
      workspace.agents.map((agent) => [
        agent.id,
        {
          ...emptySession(),
          reply: readDraft(draftKey(backend.actorId, workspace.id, agent.id)).reply,
        },
      ]),
    ),
  );
  const session = { ...(sessions[resource.id] ?? emptySession()), mainTab: search.mainTab };
  const drafts = useRef(
    new Map(
      workspace.agents.map((agent) => [
        agent.id,
        readDraft(draftKey(backend.actorId, workspace.id, agent.id)).text,
      ]),
    ),
  ).current;
  const draftWarning = useRef(false);
  function persistDraft(agent: string, patch: Partial<ChatDraft>) {
    try {
      writeDraft(draftKey(backend.actorId, workspace.id, agent), patch);
    } catch {
      if (!draftWarning.current)
        toast.error('Drafts cannot be saved in this browser. Keep this tab open until you send.');
      draftWarning.current = true;
    }
  }
  function setDraft(agent: string, text: string) {
    drafts.set(agent, text);
    persistDraft(agent, { text });
  }
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
    resource.id,
    !!resource.id && (search.view === 'agents' || search.view === 'boxes'),
    resource.state,
    selectedLetiId ?? resource.id,
  );
  const linkedMessage = search.mainTab === 'agent' ? messageSearch.message : undefined;
  const linkedRole = messageSearch.role ?? 'user';
  const messageContext = useQuery({
    queryKey: [...live.scope, 'message-context', live.conversationId, linkedMessage, linkedRole],
    enabled:
      !!resource.id &&
      !!live.conversationId &&
      !!linkedMessage &&
      backend.ready &&
      !!live.chatClient,
    queryFn: async () => {
      const page = await live.chatClient!.listMessages(live.conversationId, {
        aroundMessageId: linkedMessage!,
        limit: 30,
      });
      return {
        items: (page.messages ?? []).map((m) => toUiChatMessage(m, backend.actorId)),
      };
    },
  });
  function jumpToMessage(message: Pick<ChatMessage, 'id' | 'role'> | null) {
    return routerNavigate({
      to: '/app/$workspaceId/agents/$agentId',
      params: { workspaceId: workspace.id, agentId: resource.id },
      search: { message: message?.id, role: message?.role ?? 'user' },
      resetScroll: false,
    });
  }
  const boxRoot = search.view === 'boxes' && !selectedLetiId ? search.boxAgent : resource.id;
  const graphQuery = useBoxGraph(
    workspace.id,
    boxRoot,
    (!!resource.id && search.view === 'agents' && live.manage) || search.view === 'boxes',
  );
  const [optimistic, setOptimistic] = useState<Record<string, ChatMessage[]>>({});
  const [fileNodes, setFileNodes] = useState<Record<string, StorageNode>>({});
  const [fileFocus, setFileFocus] = useState<
    { id: string; request: string } & ({ line: number } | { page: number })
  >();
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
    const updated = await filesApi.save(node, text);
    setFileNodes((current) => ({ ...current, [node.id]: updated }));
    await queryClient.invalidateQueries({ queryKey: ['storage-folder'] });
    return updated;
  }
  type ConversationStorage = {
    id: string;
    storage_id: string;
    root_node_id: string;
    workspace_id: string;
    ready: boolean;
  };
  const conversationKey = ['conversation-storage', backend.actorId, workspace.id, resource.id];
  async function createConversation(): Promise<ConversationStorage> {
    const convId =
      live.conversationId ||
      (await live.chatClient!.createOrGetDM({ type: 'agent', id: resource.id })).id;
    const res = await live.chatClient!.ensureConversationStorage(convId);
    return {
      id: convId,
      storage_id: res.storageId,
      root_node_id: res.rootNodeId,
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
    signal?: AbortSignal,
  ): Promise<StorageNode> {
    const storage = await ensureConversation();
    const node = await filesApi.upload(
      storage.storage_id,
      storage.root_node_id,
      file,
      file.name,
      (loaded, total) => report?.(total ? loaded / total : 1),
      undefined,
      { signal },
    );
    setFileNodes((current) => ({ ...current, [node.id]: node }));
    await queryClient.invalidateQueries({ queryKey: ['storage-folder'] });
    return node;
  }
  async function openFileReference(ref: FileRef, line?: number, page?: number) {
    try {
      const node = await filesApi.stat(ref.storage_id, ref.node_id);
      if (!node) throw new Error('This attachment is no longer available.');
      if (node.kind === 'folder') {
        await navigate({ view: 'storage', storage: node.storage, folder: node.id, file: '' });
        return;
      }
      setFileNodes((current) => ({ ...current, [node.id]: node }));
      openFile(node, line, page);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not open attachment.');
    }
  }
  function insertFileIntoDraft(
    agentId: string,
    node: StorageNode,
    label = node.name,
    selection?: ComposerSelection,
  ) {
    const ref = { label, storage_id: node.storage, node_id: node.id, kind: node.kind };
    const editor = composers.get(agentId);
    if (editor) editor.insertFile(ref, selection);
    else {
      const draft = drafts.get(agentId) ?? '';
      const at = selection ?? { start: draft.length, end: draft.length };
      const prefix = draft.slice(0, at.start);
      setDraft(
        agentId,
        prefix +
          (prefix && !/\s$/.test(prefix) ? ' ' : '') +
          fileLink(ref) +
          ' ' +
          draft.slice(at.end),
      );
    }
  }
  const [copyRequest, setCopyRequest] = useState<{
    node: StorageNode;
    label: string;
    selection?: ComposerSelection;
  } | null>(null);
  async function attachFile(
    node: StorageNode,
    copy = false,
    label = node.name,
    selection?: ComposerSelection,
  ) {
    const agentId = resource.id;
    try {
      let targetNode = node;
      if (copy) {
        const storage = await ensureConversation();
        targetNode = await filesApi.transfer(node, storage.storage_id, storage.root_node_id, true);
      }
      insertFileIntoDraft(agentId, targetNode, label, selection);
      setCopyRequest(null);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not attach this file.');
    }
  }
  async function queueUpload(file: File, selection?: ComposerSelection) {
    const agentId = resource.id;
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
      run: async (report, signal) => {
        patch((stored) => ({
          ...stored,
          uploads: [...stored.uploads.filter((job) => job.id !== id), { id, status: 'uploading' }],
        }));
        try {
          const node = await uploadConversation(file, report, signal);
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
  const organization = useAgentOrganization(workspace.id);
  const pins = organization.layout.pins.filter((id) => workspace.agents.some((a) => a.id === id));
  const [folderEditor, setFolderEditor] = useState<{
    id: string | null;
    parent_id: string | null;
    name: string;
    agent_id?: string;
  } | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const readRequests = useRef(new Set<string>());
  const markChatRead = useCallback(
    async (_through: string, seq?: number) => {
      const convId = live.conversationId;
      if (!convId || !live.chatClient || !seq) return;
      const key = `${backend.actorId}:${workspace.id}:${convId}:${seq}`;
      if (readRequests.current.has(key)) return;
      readRequests.current.add(key);
      try {
        await live.chatClient.markRead(convId, seq);
        await queryClient.invalidateQueries({
          queryKey: ['agents', backend.actorId, workspace.id],
        });
      } catch {
        readRequests.current.delete(key);
      }
    },
    [backend.actorId, workspace.id, live.conversationId, live.chatClient, queryClient],
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
      return [
        agent.id,
        {
          preview: fileText(agent.preview ?? ''),
          updated_at: agent.updated_at ?? '',
          unread_count: agent.unread_count ?? 0,
        },
      ];
    }),
  );
  function updateSession(patch: Partial<AgentSession>) {
    if ('reply' in patch) persistDraft(resource.id, { reply: patch.reply });
    setSessions((current) => ({
      ...current,
      [resource.id]: { ...(current[resource.id] ?? emptySession()), ...patch },
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
  function openFile(file: Pick<StorageNode, 'id'>, line?: number, page?: number) {
    setFileFocus(
      line
        ? { id: file.id, line, request: crypto.randomUUID() }
        : page
          ? { id: file.id, page, request: crypto.randomUUID() }
          : undefined,
    );
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
  const profile = live.profile.data
    ? {
        name: live.profile.data.name,
        title: live.profile.data.title ?? resource.role,
        appearance: live.profile.data.appearance,
        description: live.profile.data.description,
        instructions: live.settings.data?.custom_instructions ?? '',
        model: live.profile.data.model_id ?? 'Default model',
        effort: live.profile.data.reasoning_effort ?? '',
      }
    : {
        name: resource.name,
        title: resource.role,
        appearance: resource.appearance,
        description: '',
        instructions: '',
        model: 'Default model',
        effort: '',
      };
  const capabilities = (live.profile.error ? undefined : live.profile.data?.capabilities) ?? {
    can_chat: false,
    can_view_activity: false,
    can_edit_settings: false,
  };
  const baseMessages = useMemo<ChatMessage[]>(() => {
    const remote = linkedMessage
      ? (messageContext.data?.items ?? [])
      : (live.chat.data?.pages.flatMap((page) => page.items) ?? []);
    const canonicalIds = new Set(remote.map((message) => `${message.role}:${message.id}`));
    return [
      ...remote,
      ...(optimistic[resource.id] ?? []).filter(
        (message) => !canonicalIds.has(`${message.role}:${message.id}`),
      ),
    ].sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id));
  }, [live.chat.data, messageContext.data, linkedMessage, optimistic, resource.id]);
  const chatMessages = useMemo(() => {
    const byId = new Map(baseMessages.map((m) => [m.id, m]));
    return baseMessages.map((message) => {
      const parent =
        !message.reply && message.reply_to_id ? byId.get(message.reply_to_id) : undefined;
      return {
        ...message,
        ...(message.role === 'user' &&
        !message.read_at &&
        message.seq &&
        message.seq <= live.agentLastReadSeq
          ? { read_at: message.created_at }
          : {}),
        ...(parent
          ? {
              reply: {
                id: parent.id,
                role: parent.role,
                content: parent.content,
              },
            }
          : {}),
        reactions:
          reactionOverrides[`${resource.id}:${message.role}:${message.id}`] ?? message.reactions,
      };
    });
  }, [baseMessages, reactionOverrides, resource.id, live.agentLastReadSeq]);
  async function reactMessage(
    message: Pick<ChatMessage, 'id' | 'role' | 'reactions'>,
    emoji: string | null,
  ) {
    const agentId = resource.id;
    const key = `${agentId}:${message.role}:${message.id}`;
    const previous = message.reactions ?? [];
    const next = previous.filter(
      (r) => !(r.actor_kind === 'user' && r.actor_id === backend.actorId),
    );
    if (emoji) next.push({ actor_kind: 'user', actor_id: backend.actorId, emoji });
    setReactionOverrides((current) => ({ ...current, [key]: next }));
    const operation = (reactionQueues.current.get(key) ?? Promise.resolve()).then(async () => {
      try {
        const convId = live.conversationId;
        if (!convId || !live.chatClient) throw new Error('Conversation not ready.');
        const prevEmoji = previous.find(
          (r) => r.actor_kind === 'user' && r.actor_id === backend.actorId,
        )?.emoji;
        if (emoji) {
          if (prevEmoji && prevEmoji !== emoji) {
            await live.chatClient.removeReaction(convId, message.id, prevEmoji).catch(() => {});
          }
          await live.chatClient.addReaction(convId, message.id, emoji);
        } else if (prevEmoji) {
          await live.chatClient.removeReaction(convId, message.id, prevEmoji);
        }
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
  const requests = live.requests.data?.pages.flatMap((page) => page.items) ?? [];
  async function retryMessage(message: ChatMessage) {
    setOptimistic((current) => ({
      ...current,
      [resource.id]: (current[resource.id] ?? []).map((item) =>
        item.id === message.id ? { ...item, status: 'sending' } : item,
      ),
    }));
    try {
      const convId =
        live.conversationId ||
        (await live.chatClient!.createOrGetDM({ type: 'agent', id: resource.id })).id;
      const refs = fileReferences(message.content);
      const mentions = refs.map((ref) => ({
        kind: ref.kind ?? 'file',
        id: ref.node_id,
        storageId: ref.storage_id,
        nodeId: ref.node_id,
        label: ref.label,
      }));
      const sent = await live.chatClient!.sendMessage(convId, {
        idempotencyKey: message.id,
        content: message.content,
        replyToId: message.reply?.id ?? null,
        mentions,
      });
      setOptimistic((current) => ({
        ...current,
        [resource.id]: (current[resource.id] ?? []).map((item) =>
          item.id === message.id ? { ...item, id: sent.id, status: undefined } : item,
        ),
      }));
      messageSent(`${backend.actorId}:${workspace.id}`, sent.id);
      await live.refresh();
      const key = draftKey(backend.actorId, workspace.id, resource.id);
      if (!drafts.get(resource.id)?.trim() && readDraft(key).text.trim() === message.content)
        persistDraft(resource.id, { text: '', reply: null });
      setOptimistic((current) => ({
        ...current,
        [resource.id]: (current[resource.id] ?? []).filter(
          (item) => item.id !== message.id && item.id !== sent.id,
        ),
      }));
    } catch (error) {
      setOptimistic((current) => ({
        ...current,
        [resource.id]: (current[resource.id] ?? []).map((item) =>
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
    drafts.delete(resource.id);
    composers.get(resource.id)?.clear();
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
      [resource.id]: [...(current[resource.id] ?? []), message],
    }));
    updateSession({ reply: null });
    persistDraft(resource.id, { text, reply: message.reply ?? null });
    await retryMessage(message);
  }
  async function answerRequest(
    request: HumanRequest,
    status: 'answered' | 'accepted' | 'denied',
    response?: HumanRequest['response'],
  ) {
    await live.api!(`/v1/hitl-requests/${request.id}/decide`, {
      method: 'POST',
      body: JSON.stringify({ status, response }),
    });
    await live.refresh();
    await queryClient.invalidateQueries({ queryKey: ['human-requests', backend.actorId] });
  }
  const graph = useMemo<BoxGraph>(
    () => ({
      agents: graphQuery.data?.pages.flatMap((p) => p.agents) ?? [],
      boxes: graphQuery.data?.pages.flatMap((p) => p.boxes) ?? [],
      additional_links: graphQuery.data?.pages.flatMap((p) => p.additional_links) ?? [],
      schedules: graphQuery.data?.pages.flatMap((p) => p.schedules) ?? [],
      letas: graphQuery.data?.pages.flatMap((p) => p.letas) ?? [],
    }),
    [graphQuery.data],
  );
  const selectedLeti =
    graph.agents.find((a) => a.id === selectedLetiId && a.leta_id === resource.id && a.box_id) ??
    session.letis.find((a) => a.id === selectedLetiId);
  useEffect(() => {
    if (!selectedLeti) return;
    setSessions((current) => {
      const stored = current[resource.id] ?? emptySession();
      return stored.letis.some((a) => a.id === selectedLeti.id)
        ? current
        : {
            ...current,
            [resource.id]: { ...stored, letis: [...stored.letis, selectedLeti] },
          };
    });
  }, [selectedLeti, resource.id]);
  useEffect(() => {
    if (!resource.id || (search.view !== 'agents' && search.view !== 'boxes')) return;
    setSessions((current) => {
      const stored = current[resource.id] ?? emptySession();
      return {
        ...current,
        [resource.id]: {
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
  }, [resource.id, search.view, search.mainTab]);
  const activityAgent =
    (selectedLeti ? (graph.agents.find((a) => a.id === selectedLeti.id) ?? selectedLeti) : null) ??
    ({
      id: selectedLetiId ?? resource.id,
      leta_id: resource.id,
      box_id: null,
      ...profile,
      model_id: profile.model,
      status: 'idle',
    } as BoxAgent);
  const activityBox = graph.boxes.find((box) => box.id === activityAgent.box_id);
  const activityContact = graph.agents.find(
    (agent) =>
      agent.id ===
      (activityBox && activityBox.leader_agent_id !== activityAgent.id
        ? activityBox.leader_agent_id
        : resource.id),
  );
  return {
    resource,
    graphQuery,
    graph,
    activityAgent,
    activityContact,
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
    fileFocus,
    drafts,
    setDraft,
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
        {
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
    live,
    capabilities,
    chatMessages,
    linkedMessage,
    linkedRole,
    messageContext,
    jumpToMessage,
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
    pendingRequests: live.requests.data?.pages[0]?.pending_count ?? 0,
    savePins,
    openFile,
    closeFile,
    togglePanel,
    send,
    saveProfile: async (draft: AgentProfile) => {
      await live.api!(live.path + `/agents/${resource.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          name: draft.name.trim(),
          title: draft.title,
          ...(draft.appearance
            ? { appearance: { shape: draft.appearance.shape, color: draft.appearance.color } }
            : {}),
          description: draft.description,
          custom_instructions: draft.instructions,
          model_id: draft.model === 'Default model' ? null : draft.model,
          reasoning_effort: draft.effort ? draft.effort.toLowerCase() : null,
        }),
      });
      await Promise.all([
        live.refresh(),
        queryClient.invalidateQueries({ queryKey: ['agents', backend.actorId, workspace.id] }),
        queryClient.invalidateQueries({ queryKey: ['box-graph', backend.actorId, workspace.id] }),
      ]);
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
