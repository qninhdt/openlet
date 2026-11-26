import type { Api, ChatMessage, Json } from './agent-api.js';
import type { FileRef, MessageSource } from './file-refs.js';

export type ChatActor = {
  type: 'user' | 'agent';
  id: string;
};

export type ChatMember = {
  actorType: 'user' | 'agent';
  actorId: string;
  role: 'admin' | 'member';
  lastReadSeq?: string | number;
};

export type ChatAttachmentDto = {
  storageId: string;
  nodeId: string;
  kind?: string;
  name?: string;
  mediaType?: string;
  sizeBytes?: string | number;
};

export type ChatMentionDto = {
  kind: string;
  id: string;
  storageId?: string;
  nodeId?: string;
  label?: string;
};

export type ChatReactionDto = {
  actorType: 'user' | 'agent';
  actorId: string;
  emoji: string;
};

export type ChatMessageDto = {
  id: string;
  conversationId: string;
  seq: string | number;
  senderType: 'user' | 'agent';
  senderId: string;
  content: string;
  attachments?: ChatAttachmentDto[];
  mentions?: ChatMentionDto[];
  replyToId?: string;
  reactions?: ChatReactionDto[];
  metadata?: Record<string, Json>;
  createdAt: string;
  editedAt?: string;
  deletedAt?: string;
};

export type ChatConversationDto = {
  id: string;
  workspaceId: string;
  type: 'dm' | 'group';
  title?: string;
  handle?: string;
  storageId?: string;
  storageReady?: boolean;
  lastSeq?: string | number;
  lastMessageSeq?: string | number;
  lastMsgAt?: string;
  unreadCount?: string | number;
  members?: ChatMember[];
  lastMessagePreview?: {
    id?: string;
    messageId?: string;
    seq?: string | number;
    senderType: 'user' | 'agent';
    senderId: string;
    snippet: string;
    hasAttachments?: boolean;
    createdAt?: string;
  };
  createdAt?: string;
  updatedAt?: string;
};

export type SidebarFolderDto = {
  id: string;
  name: string;
  parentId?: string;
};

export type SidebarLayoutDto = {
  folders?: SidebarFolderDto[];
  assignments?: Record<string, string>;
  pins?: string[];
  order?: string[];
  collapsed?: string[];
};

export type SidebarResponseDto = {
  revision: number;
  layout?: SidebarLayoutDto;
};

export function toUiChatMessage(msg: ChatMessageDto, currentUserId: string): ChatMessage {
  const isUser = msg.senderType === 'user' && msg.senderId === currentUserId;
  const fileRefs: FileRef[] = (msg.attachments ?? []).map((att) => ({
    storage_id: att.storageId,
    node_id: att.nodeId,
    label: att.name || 'Attachment',
    kind: att.kind === 'folder' ? 'folder' : 'file',
    name: att.name,
    mime: att.mediaType,
    size: att.sizeBytes ? Number(att.sizeBytes) : undefined,
  }));
  const rawSources = Array.isArray(msg.metadata?.sources)
    ? (msg.metadata.sources as Record<string, Json>[])
    : [];
  const sources: MessageSource[] = rawSources.flatMap((s): MessageSource[] => {
    if (s.kind === 'web' && typeof s.url === 'string') {
      return [{ kind: 'web', url: s.url, title: typeof s.title === 'string' ? s.title : s.url }];
    }
    if (typeof s.storage_id === 'string' && typeof s.node_id === 'string') {
      return [
        {
          kind: s.kind === 'folder' ? 'folder' : 'file',
          storage_id: s.storage_id,
          node_id: s.node_id,
          label:
            (typeof s.path === 'string' && s.path.split('/').pop()) ||
            (typeof s.label === 'string' && s.label) ||
            'File',
        },
      ];
    }
    return [];
  });
  return {
    id: msg.id,
    seq: Number(msg.seq || 0),
    role: isUser ? 'user' : 'assistant',
    sender_type: msg.senderType,
    sender_id: msg.senderId,
    content: msg.deletedAt ? '[Message deleted]' : msg.content,
    created_at: msg.createdAt,
    conversation_id: msg.conversationId,
    reply_to_id: msg.replyToId || null,
    edited_at: msg.editedAt || null,
    deleted_at: msg.deletedAt || null,
    file_refs: fileRefs.length ? fileRefs : undefined,
    sources: sources.length ? sources : undefined,
    reactions: (msg.reactions ?? []).map((r) => ({
      actor_kind: r.actorType,
      actor_id: r.actorId,
      emoji: r.emoji,
    })),
  };
}

export function chatApi(api: Api, workspaceId: string) {
  const base = `/v1/workspaces/${workspaceId}`;
  return {
    createOrGetDM: (target: ChatActor) =>
      api<ChatConversationDto>(`${base}/conversations:dm`, {
        method: 'POST',
        body: JSON.stringify({ target }),
      }),
    createGroup: (title: string, members: ChatActor[], handle?: string) =>
      api<ChatConversationDto>(`${base}/conversations`, {
        method: 'POST',
        body: JSON.stringify({ title, members, ...(handle ? { handle } : {}) }),
      }),
    listConversations: (pageSize = 100, pageToken = '') =>
      api<{ conversations?: ChatConversationDto[]; nextPageToken?: string }>(
        `${base}/conversations?${new URLSearchParams({
          pageSize: String(pageSize),
          ...(pageToken ? { pageToken } : {}),
        })}`,
      ),
    listAgentConversations: (agentId: string, pageSize = 50, pageToken = '') =>
      api<{ conversations?: ChatConversationDto[]; nextPageToken?: string }>(
        `${base}/agents/${agentId}/conversations?${new URLSearchParams({
          pageSize: String(pageSize),
          ...(pageToken ? { pageToken } : {}),
        })}`,
      ),
    getConversation: (conversationId: string) =>
      api<ChatConversationDto>(`${base}/conversations/${conversationId}`),
    updateGroup: (conversationId: string, patch: { title?: string; handle?: string }) =>
      api<ChatConversationDto>(`${base}/conversations/${conversationId}`, {
        method: 'PATCH',
        body: JSON.stringify(patch),
      }),
    addMembers: (conversationId: string, members: ChatActor[]) =>
      api<ChatConversationDto>(`${base}/conversations/${conversationId}/members`, {
        method: 'POST',
        body: JSON.stringify({ members }),
      }),
    removeMember: (conversationId: string, actorType: 'user' | 'agent', actorId: string) =>
      api<ChatConversationDto>(
        `${base}/conversations/${conversationId}/members/${actorType}/${actorId}`,
        { method: 'DELETE' },
      ),
    leaveConversation: (conversationId: string) =>
      api<Record<string, never>>(`${base}/conversations/${conversationId}:leave`, {
        method: 'POST',
        body: '{}',
      }),
    ensureConversationStorage: (conversationId: string) =>
      api<{ storageId: string; rootNodeId: string }>(
        `${base}/conversations/${conversationId}:ensureStorage`,
        { method: 'POST', body: '{}' },
      ),
    listMessages: (
      conversationId: string,
      opts: {
        beforeSeq?: number;
        afterSeq?: number;
        aroundSeq?: number;
        aroundMessageId?: string;
        limit?: number;
        query?: string;
      } = {},
    ) => {
      const qs = new URLSearchParams();
      if (opts.beforeSeq) qs.set('beforeSeq', String(opts.beforeSeq));
      if (opts.afterSeq) qs.set('afterSeq', String(opts.afterSeq));
      if (opts.aroundSeq) qs.set('aroundSeq', String(opts.aroundSeq));
      if (opts.aroundMessageId) qs.set('aroundMessageId', opts.aroundMessageId);
      if (opts.limit) qs.set('limit', String(opts.limit));
      if (opts.query) qs.set('query', opts.query);
      const suffix = qs.toString() ? `?${qs}` : '';
      return api<{
        messages?: ChatMessageDto[];
        hasBefore?: boolean;
        hasAfter?: boolean;
        hasMore?: boolean;
      }>(`${base}/conversations/${conversationId}/messages${suffix}`);
    },
    sendMessage: (
      conversationId: string,
      body: {
        idempotencyKey: string;
        content: string;
        replyToId?: string | null;
        attachments?: ChatAttachmentDto[];
        mentions?: ChatMentionDto[];
      },
    ) =>
      api<ChatMessageDto>(`${base}/conversations/${conversationId}/messages`, {
        method: 'POST',
        body: JSON.stringify({
          idempotencyKey: body.idempotencyKey,
          content: body.content,
          ...(body.replyToId ? { replyToId: body.replyToId } : {}),
          ...(body.attachments?.length ? { attachments: body.attachments } : {}),
          ...(body.mentions?.length ? { mentions: body.mentions } : {}),
        }),
      }),
    editMessage: (conversationId: string, messageId: string, content: string) =>
      api<ChatMessageDto>(`${base}/conversations/${conversationId}/messages/${messageId}`, {
        method: 'PATCH',
        body: JSON.stringify({ content }),
      }),
    deleteMessage: (conversationId: string, messageId: string) =>
      api<Record<string, never>>(`${base}/conversations/${conversationId}/messages/${messageId}`, {
        method: 'DELETE',
      }),
    addReaction: (conversationId: string, messageId: string, emoji: string) =>
      api<Record<string, never>>(
        `${base}/conversations/${conversationId}/messages/${messageId}/reactions/${encodeURIComponent(emoji)}`,
        { method: 'PUT', body: '{}' },
      ),
    removeReaction: (conversationId: string, messageId: string, emoji: string) =>
      api<Record<string, never>>(
        `${base}/conversations/${conversationId}/messages/${messageId}/reactions/${encodeURIComponent(emoji)}`,
        { method: 'DELETE' },
      ),
    markRead: (conversationId: string, lastReadSeq: number) =>
      api<{ lastReadSeq?: string | number }>(`${base}/conversations/${conversationId}:markRead`, {
        method: 'POST',
        body: JSON.stringify({ seq: String(lastReadSeq) }),
      }),
    setTyping: (conversationId: string, active: boolean) =>
      api<Record<string, never>>(`${base}/conversations/${conversationId}:typing`, {
        method: 'POST',
        body: JSON.stringify({ active }),
      }),
    getSidebar: () => api<SidebarResponseDto>(`${base}/chat/sidebar`),
    updateSidebar: (revision: number, layout: SidebarLayoutDto) =>
      api<SidebarResponseDto>(`${base}/chat/sidebar`, {
        method: 'PUT',
        body: JSON.stringify({ revision, layout }),
      }),
    getRealtimeToken: (conversationId: string) =>
      api<{ channel: string; token: string; expiresAt?: string }>(`${base}/chat:realtimeToken`, {
        method: 'POST',
        body: JSON.stringify({ channel: `chat:conv:${conversationId}` }),
      }),
  };
}
