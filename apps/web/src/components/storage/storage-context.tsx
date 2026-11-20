import { useShellLocation, useShellNavigate } from '@/lib/shell-navigation';
import { useUploads } from './uploads';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useFileSessions } from './file-sessions';
import { apiUrl, useBackend } from '@/lib/backend';
import { downloadArchive } from '@/lib/archive-download';
import { storageApi } from '@/lib/storage-api';
import { classifyFile } from '@/lib/file-types';
import { toast } from 'sonner';
import {
  ancestors,
  branch,
  rootId,
  topNodes,
  type StorageNode,
  type StorageSnapshot,
  type StorageRoot,
  type Collision,
  NameConflict,
  uniqueName,
  validateName,
  fileBlob,
  downloadNodes,
  formatBytes,
} from '@/lib/storage-preview';

export type StorageView = 'mosaic' | 'grid' | 'list';
export interface StorageTextSession {
  node: StorageNode;
  text: string;
  bom: boolean;
  crlf: boolean;
  truncated: boolean;
  scroll?: { source: number; preview: number };
  draft?: string;
  source: boolean;
}
export interface TransferRequest {
  ids: string[];
  copy: boolean;
  storage: string;
  parent: string;
}
export interface UploadFile {
  file: File;
  path: string;
}
type NameRequest =
  | { kind: 'create' | 'create-file'; parent: string; storage: string }
  | { kind: 'rename'; node: StorageNode };
type BrowserOptions = {
  root?: StorageRoot & { root?: string };
  onOpenFile?: (node: StorageNode, line?: number) => void;
  onAttachFiles?: (nodes: StorageNode[]) => void;
};
function useBrowser(
  workspace: {
    id: string;
    name?: string;
    agents: readonly { id?: string; name: string; role?: string }[];
  },
  options: BrowserOptions = {},
) {
  const routeSearch = useShellLocation();
  const [localLocation, setLocalLocation] = useState({
    storage: options.root?.id ?? '',
    folder: '',
    file: '',
  });
  const search = options.root ? { ...routeSearch, view: 'storage', ...localLocation } : routeSearch;
  const navigate = useShellNavigate();
  const client = useQueryClient();
  const backend = useBackend();
  const uploads = useUploads();
  const live = useMemo(
    () => storageApi(backend.api!, workspace.id, backend.request, backend.actorId),
    [backend.api, backend.request, backend.actorId, workspace.id],
  );
  const quotaQuery = useQuery({
    queryKey: ['storage-quota', backend.actorId, workspace.id],
    queryFn: () => live.quota(),
    enabled: backend.ready && search.view === 'storage',
    refetchInterval: 30_000,
  });
  const rootsQuery = useQuery({
    queryKey: ['storage-roots', backend.actorId, workspace.id],
    queryFn: () => live!.listRoots(),
    enabled: !!live && backend.ready && !options.root,
    refetchInterval: 30_000,
  });
  if (options.root?.root) live?.bind(options.root.id, options.root.root);
  const rawRoots: StorageRoot[] = options.root ? [options.root] : (rootsQuery.data ?? []);
  const roots = rawRoots.map((root) => {
    if ('root' in root && typeof root.root === 'string') live?.bind(root.id, root.root);
    const agent = workspace.agents.find((a) => a.name === root.name);
    if (agent) {
      return { ...root, agent: agent.name, agentId: agent.id, title: agent.role };
    }
    const convAgent = workspace.agents.find((a) =>
      root.name.startsWith(`Conversation · ${a.name} · `),
    );
    if (convAgent) {
      return {
        ...root,
        name: `${convAgent.name} · Conversation`,
        agent: convAgent.name,
        agentId: convAgent.id,
        isConversation: true,
      };
    }
    return root;
  });
  const key = ['storage-live', backend.actorId, workspace.id];
  const query = useQuery({
    queryKey: key,
    queryFn: () => Promise.resolve({ nodes: [] } as StorageSnapshot),
    enabled: search.view === 'storage',
    staleTime: Infinity,
  });
  const snapshot = query.data ?? { nodes: [] };
  const textSessions = useFileSessions();
  const getTextSession = useCallback(
    (id: string) => {
      const node = snapshot.nodes.find((n) => n.id === id);
      return node ? (textSessions.get(`${node.storage}/${id}`) ?? null) : null;
    },
    [textSessions, snapshot.nodes],
  );
  const setTextSession = useCallback(
    (id: string, session: StorageTextSession | null) => {
      const node = session?.node ?? snapshot.nodes.find((n) => n.id === id);
      if (!node) return;
      if (session) textSessions.set(`${node.storage}/${id}`, session);
      else textSessions.delete(`${node.storage}/${id}`);
    },
    [textSessions, snapshot.nodes],
  );
  const [tabs, setTabs] = useState<Record<string, string[]>>({});
  const locations = useRef<Record<string, { folder: string; file: string }>>({});
  const [closeRequest, setCloseRequest] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [selecting, setSelecting] = useState(false);
  const anchor = useRef<string | null>(null);
  const [filter, setFilter] = useState('');
  const [type, setType] = useState('all');
  const [sort, setSort] = useState('name');
  const [transfer, setTransfer] = useState<TransferRequest | null>(null);
  const [nameRequest, setNameRequest] = useState<NameRequest | null>(null);
  const [deleteIds, setDeleteIds] = useState<string[]>([]);
  const [purgeIds, setPurgeIds] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  const [lineTarget, setLineTarget] = useState<{ id: string; line: number; request: string }>();
  const [details, setDetails] = useState<StorageNode | null>(null);
  const [conflict, setConflict] = useState<{
    names: string[];
    upload?: boolean;
    retry: (mode: Collision) => Promise<void>;
  } | null>(null);
  const downloadController = useRef<AbortController | null>(null);
  useEffect(() => () => downloadController.current?.abort(), [workspace.id]);
  const [progress, setProgress] = useState<{
    label: string;
    done: number;
    total: number;
    cancel?: () => void;
  } | null>(null);
  const [clipboard, setClipboard] = useState<{ ids: string[]; copy: boolean } | null>(null);
  const [dropTarget, setDropTarget] = useState('');
  const last = useMemo(() => {
    try {
      return JSON.parse(
        localStorage.getItem(`openlet-storage-location:${workspace.id}`) ?? 'null',
      ) as { storage: string; folder: string } | null;
    } catch {
      return null;
    }
  }, [workspace.id]);
  const storage = roots.find((root) => root.id === search.storage) ??
    (search.storage ? { id: search.storage, name: 'Storage', write: false } : undefined) ??
    roots.find((root) => root.id === last?.storage) ??
    roots[0] ?? { id: '', name: 'Storage', write: false };
  const targetFile = snapshot.nodes.find(
    (node) => node.id === search.file && node.storage === storage.id,
  );
  const requestedFolder =
    search.folder ||
    (search.file
      ? (locations.current[storage.id]?.folder ??
        (targetFile?.parent === rootId(storage.id) ? '' : targetFile?.parent))
      : search.storage
        ? ''
        : last?.folder);
  const [pathError, setPathError] = useState<{ target: string; message: string } | null>(null);
  const folder = snapshot.nodes.find(
    (node) =>
      node.id === requestedFolder &&
      node.storage === storage.id &&
      node.kind === 'folder' &&
      !ancestors(snapshot.nodes, node.id).some((at) => at.trashed),
  );
  const parent = folder?.id ?? rootId(storage.id);
  const trash = search.folder === 'trash';
  const path = folder ? ancestors(snapshot.nodes, folder.id) : [];
  const file = snapshot.nodes.find(
    (node) =>
      node.id === search.file &&
      node.kind === 'file' &&
      node.storage === storage.id &&
      !ancestors(snapshot.nodes, node.id).some((at) => at.trashed),
  );
  const folderQuery = useQuery({
    queryKey: ['storage-folder', backend.actorId, workspace.id, storage.id, requestedFolder ?? ''],
    queryFn: () =>
      trash
        ? live!.listTrash(storage.id)
        : live!.list(storage.id, requestedFolder || rootId(storage.id)),
    enabled: !!live && (!!options.root || !!rootsQuery.data) && search.view === 'storage',
    refetchInterval: 15_000,
  });
  useEffect(() => {
    if (!folderQuery.data) return;
    client.setQueryData<StorageSnapshot>(key, (previous) => ({
      nodes: [
        ...(previous?.nodes ?? []).filter(
          (node) =>
            node.storage !== storage.id ||
            (trash ? !node.trashed : node.parent !== (requestedFolder || rootId(storage.id))),
        ),
        ...folderQuery.data!,
      ].filter((node, index, all) => all.findLastIndex((other) => other.id === node.id) === index),
    }));
  }, [folderQuery.data]);
  useEffect(() => {
    const target = search.file || requestedFolder;
    if (!target || target === 'trash') return;
    let cancelled = false;
    void (async () => {
      const parents: StorageNode[] = [];
      let id = target;
      while (id && !id.startsWith('root:')) {
        const existing = snapshot.nodes.find((n) => n.id === id);
        const node = existing ?? (await live.stat(storage.id, id));
        if (node.name) parents.push(node);
        if (node.parent === id) break;
        id = node.parent;
      }
      if (!cancelled) {
        setPathError(null);
        client.setQueryData<StorageSnapshot>(key, (current) => ({
          nodes: [
            ...(current?.nodes ?? []).filter((n) => !parents.some((p) => p.id === n.id)),
            ...parents,
          ],
        }));
      }
    })().catch((error) => {
      if (!cancelled)
        setPathError({
          target,
          message: error instanceof Error ? error.message : 'This file is unavailable.',
        });
    });
    return () => {
      cancelled = true;
    };
  }, [live, search.file, requestedFolder, storage.id]);
  async function loadFolder(storage: string, parent: string) {
    const nodes = await live.list(storage, parent);
    client.setQueryData<StorageSnapshot>(key, (previous) => ({
      nodes: [
        ...(previous?.nodes ?? []).filter(
          (node) => node.storage !== storage || node.parent !== parent,
        ),
        ...nodes,
      ],
    }));
  }
  async function refreshLive() {
    await Promise.all([
      client.invalidateQueries({ queryKey: ['storage-folder', backend.actorId, workspace.id] }),
      client.invalidateQueries({ queryKey: ['storage-quota', backend.actorId, workspace.id] }),
    ]);
  }
  const [view, setViewState] = useState<StorageView>('grid');
  useEffect(() => {
    const saved = localStorage.getItem(`openlet-storage-view:${storage.id}`);
    setViewState(saved === 'mosaic' || saved === 'list' ? saved : 'grid');
  }, [storage.id]);
  function setView(value: StorageView) {
    setViewState(value);
    localStorage.setItem(`openlet-storage-view:${storage.id}`, value);
  }
  useEffect(() => {
    setSelected(new Set());
    setSelecting(false);
    setFilter('');
    setType('all');
    anchor.current = null;
    if (query.data && !trash && !options.root)
      localStorage.setItem(
        `openlet-storage-location:${workspace.id}`,
        JSON.stringify({
          storage: storage.id,
          folder: parent === rootId(storage.id) ? '' : parent,
        }),
      );
  }, [storage.id, parent, trash, query.data !== undefined]);
  const visible = snapshot.nodes
    .filter(
      (node) =>
        node.storage === storage.id &&
        (trash ? node.trashed : node.parent === parent && !node.trashed),
    )
    .filter((node) => node.name.toLowerCase().includes(filter.toLowerCase()))
    .filter((node) => type === 'all' || node.kind === 'folder' || fileCategory(node) === type)
    .sort((a, b) => {
      if (a.kind !== b.kind) return a.kind === 'folder' ? -1 : 1;
      if (sort === 'updated') return b.updated - a.updated;
      if (sort === 'size') return b.size - a.size;
      return a.name.localeCompare(b.name, undefined, { numeric: true });
    });
  function report(error: unknown) {
    toast.error(error instanceof Error ? error.message : 'The operation could not be completed.');
  }
  function writable(id = storage.id) {
    if (!roots.find((root) => root.id === id)?.write) throw new Error('This storage is read-only.');
  }
  useEffect(() => {
    if (search.view !== 'storage' || (!options.root && !search.storage)) return;
    locations.current[storage.id] = { folder: requestedFolder ?? '', file: search.file ?? '' };
    if (file)
      setTabs((previous) =>
        previous[storage.id]?.includes(file.id)
          ? previous
          : { ...previous, [storage.id]: [...(previous[storage.id] ?? []), file.id] },
      );
  }, [
    storage.id,
    requestedFolder,
    search.file,
    file?.id,
    search.view,
    search.storage,
    options.root,
  ]);
  const openFiles = (tabs[storage.id] ?? []).flatMap((id) => {
    const node = snapshot.nodes.find(
      (node) => node.id === id && node.storage === storage.id && !node.trashed,
    );
    return node ? [node] : [];
  });
  function go(storage: string, folder?: string) {
    const saved = locations.current[storage];
    const destination = folder === undefined ? (saved?.folder ?? '') : folder;
    const targetFile = folder === undefined ? (saved?.file ?? '') : '';
    if (options.root) {
      setLocalLocation({ storage, folder: destination, file: targetFile });
      return;
    }
    void navigate({ view: 'storage', storage, folder: destination, file: targetFile });
  }
  function open(node: StorageNode, line?: number) {
    setLineTarget(
      line && line > 0 ? { id: node.id, line, request: crypto.randomUUID() } : undefined,
    );
    if (trash) return;
    if (node.kind === 'folder') go(node.storage, node.id);
    else if (options.onOpenFile) options.onOpenFile(node, line);
    else if (options.root) setLocalLocation((previous) => ({ ...previous, file: node.id }));
    else void navigate({ view: 'storage', storage: node.storage, file: node.id });
  }
  function closeFile(id = file?.id, discard = false) {
    if (!id) return;
    const session = getTextSession(id);
    if (!discard && session?.draft !== undefined && session.draft !== session.text) {
      setCloseRequest(id);
      return;
    }
    const index = openFiles.findIndex((node) => node.id === id);
    const remaining = openFiles.filter((node) => node.id !== id);
    setTabs((previous) => ({ ...previous, [storage.id]: remaining.map((node) => node.id) }));
    setTextSession(id, null);
    setCloseRequest(null);
    if (search.file === id)
      if (options.root)
        setLocalLocation((previous) => ({
          ...previous,
          file: remaining[Math.max(0, index - 1)]?.id ?? '',
        }));
      else
        void navigate(
          {
            view: 'storage',
            storage: storage.id,
            folder: folder?.id ?? '',
            file: remaining[Math.max(0, index - 1)]?.id ?? '',
          },
          { replace: true },
        );
  }
  function toggle(node: StorageNode, modifiers: { shiftKey?: boolean } = {}) {
    setSelecting(true);
    setSelected((previous) => {
      const next = new Set(previous);
      const from = visible.findIndex((at) => at.id === anchor.current);
      const to = visible.findIndex((at) => at.id === node.id);
      if (modifiers.shiftKey && from >= 0 && to >= 0)
        for (const at of visible.slice(Math.min(from, to), Math.max(from, to) + 1)) next.add(at.id);
      else {
        if (next.has(node.id)) next.delete(node.id);
        else next.add(node.id);
        anchor.current = node.id;
      }
      return next;
    });
  }
  function clearSelection() {
    setSelected(new Set());
    setSelecting(false);
  }
  async function move(request: TransferRequest, mode: Collision = 'ask') {
    try {
      writable(request.storage);
      if (!request.copy)
        for (const node of topNodes(snapshot.nodes, request.ids)) writable(node.storage);
      {
        const sources = topNodes(snapshot.nodes, request.ids);
        let destination = await live.list(request.storage, request.parent);
        const conflicts = sources.filter(
          (node) =>
            (request.copy || node.storage !== request.storage || node.parent !== request.parent) &&
            destination.some((other) => other.name === node.name),
        );
        if (mode === 'ask' && conflicts.length)
          throw new NameConflict(conflicts.map((node) => node.name));
        for (const node of sources) {
          if (!request.copy && node.storage === request.storage && node.parent === request.parent)
            continue;
          const conflict = destination.find((other) => other.name === node.name);
          const name =
            conflict && mode === 'keep'
              ? uniqueName(node.name, destination, request.parent)
              : node.name;
          // Keep the destination recoverable if the subsequent transfer fails.
          if (conflict && mode === 'replace') await live.trash(conflict);
          const transferred = await live.transfer(
            node,
            request.storage,
            request.parent,
            request.copy,
            name,
          );
          destination = [
            ...destination.filter((other) => other.id !== conflict?.id || mode !== 'replace'),
            transferred,
          ];
        }
        await refreshLive();
      }
      setTransfer(null);
      setConflict(null);
      clearSelection();
      toast.success(
        `${request.ids.length} item${request.ids.length === 1 ? '' : 's'} ${request.copy ? 'copied' : 'moved'}`,
      );
    } catch (error) {
      if (error instanceof NameConflict)
        setConflict({ names: error.names, retry: (next) => move(request, next) });
      else report(error);
    }
  }
  function drop(ids: string[], destination: string, parent: string) {
    setDropTarget('');
    const request = { ids, storage: destination, parent, copy: false };
    if (ids.some((id) => snapshot.nodes.find((node) => node.id === id)?.storage !== destination))
      setTransfer(request);
    else void move(request);
  }
  async function saveName(name: string) {
    if (!nameRequest || pending) return;
    const request = nameRequest;
    const nextName = validateName(name);
    const storage = request.kind === 'rename' ? request.node.storage : request.storage;
    writable(storage);
    const type = classifyFile(nextName);
    if (request.kind === 'create-file' && type.kind !== 'text')
      throw new Error('Use a text or code extension, such as .txt, .md or .py.');
    setPending(true);
    try {
      const node =
        request.kind === 'rename'
          ? await live.transfer(request.node, storage, request.node.parent, false, nextName)
          : await live.create(
              storage,
              request.parent,
              nextName,
              request.kind === 'create-file'
                ? { content: '', mediaType: type.mediaType }
                : undefined,
            );
      client.setQueryData<StorageSnapshot>(key, (current) => ({
        nodes: [...(current?.nodes ?? []).filter((n) => n.id !== node.id), node],
      }));
      await refreshLive();
      setNameRequest(null);
      if (request.kind === 'create-file') open(node);
    } finally {
      setPending(false);
    }
  }
  async function purge() {
    if (pending) return;
    setPending(true);
    const failed: string[] = [];
    const errors: string[] = [];
    try {
      for (const [index, id] of purgeIds.entries()) {
        const node = snapshot.nodes.find((n) => n.id === id);
        setProgress({ label: 'Deleting permanently', done: index, total: purgeIds.length });
        try {
          if (!node?.trashed) throw new Error('Reload Trash before deleting this item.');
          writable(node.storage);
          await live.purge(node);
        } catch (error) {
          failed.push(id);
          errors.push(
            `${node?.name ?? id}: ${error instanceof Error ? error.message : 'Could not delete.'}`,
          );
        }
      }
      await refreshLive();
      setPurgeIds(failed);
      clearSelection();
      if (failed.length)
        toast.error(`${failed.length} item(s) could not be deleted`, {
          description: errors.join('\n'),
        });
      else toast.success('Permanently deleted');
    } finally {
      setPending(false);
      setProgress(null);
    }
  }
  async function remove(ids = deleteIds) {
    try {
      for (const node of topNodes(snapshot.nodes, ids)) writable(node.storage);
      if (live) {
        for (const node of topNodes(snapshot.nodes, ids)) await live.trash(node);
        await refreshLive();
      }
      setDeleteIds([]);
      clearSelection();
      toast.success('Moved to Trash', {
        action: {
          label: 'Undo',
          onClick: () => {
            void restore(ids);
          },
        },
      });
    } catch (error) {
      report(error);
    }
  }
  async function restore(ids: string[]) {
    try {
      writable();
      if (live) {
        for (const id of ids) {
          const node = snapshot.nodes.find((n) => n.id === id);
          if (node) await live.restore(node);
        }
        await refreshLive();
      }
      clearSelection();
      toast.success('Restored');
    } catch (error) {
      report(error);
    }
  }
  async function download(ids: string[]) {
    if (progress || downloadController.current) return;
    const controller = new AbortController();
    downloadController.current = controller;
    const cancel = () => controller.abort();
    try {
      const selected = topNodes(snapshot.nodes, ids);
      if (selected.length > 1 || selected[0]?.kind === 'folder') {
        setProgress({ label: 'Preparing archive…', done: 0, total: 0, cancel });
        const result = await downloadArchive({
          api: backend.api!,
          request: backend.request!,
          url: apiUrl,
          workspace: workspace.id,
          nodes: selected,
          signal: controller.signal,
          onBytes: (bytes) =>
            setProgress({
              label: `Downloading archive · ${formatBytes(bytes)}`,
              done: 0,
              total: 0,
              cancel,
            }),
        });
        if (result === 'browser')
          toast.success(
            'Download started. Progress and Cancel are available in your browser downloads.',
          );
      } else {
        setProgress({ label: 'Preparing download', done: 0, total: ids.length });
        await downloadNodes({ nodes: selected }, ids, (done, total) =>
          setProgress({ label: 'Preparing download', done, total }),
        );
      }
    } catch (error) {
      if (!(error instanceof DOMException && error.name === 'AbortError')) report(error);
    } finally {
      downloadController.current = null;
      setProgress(null);
    }
  }
  async function upload(
    files: UploadFile[],
    destination = storage.id,
    parentId = parent,
    mode: Collision = 'ask',
  ) {
    if (!files.length) return;
    const id = crypto.randomUUID();
    const pendingFiles = [...files];
    await uploads.enqueue({
      id,
      name: files.length === 1 ? files[0].file.name : `${files.length} files`,
      destination: roots.find((root) => root.id === destination)?.name ?? 'Storage',
      run: (report, signal) =>
        performUpload([...pendingFiles], destination, parentId, mode, report, id, signal, () =>
          pendingFiles.shift(),
        ),
    });
  }
  async function performUpload(
    files: UploadFile[],
    destination = storage.id,
    parentId = parent,
    mode: Collision,
    reportProgress: (fraction: number) => void,
    uploadId: string,
    signal: AbortSignal,
    onUploaded: () => void,
  ) {
    if (!files.length) return;
    let remaining = files;
    try {
      writable(destination);
      reportProgress(0);
      if (live) {
        const destinations = new Map<string, string>([['', parentId]]);
        for (const [index, { file, path }] of files.entries()) {
          signal.throwIfAborted();
          const parts = path.split('/').filter(Boolean).map(validateName);
          const name = parts.pop()!;
          let parent = parentId,
            prefix = '';
          for (const part of parts) {
            prefix += '/' + part;
            let id = destinations.get(prefix);
            if (!id) {
              const items = await live.list(destination, parent);
              const existing = items.find((n) => n.name === part);
              if (existing?.kind === 'file') throw new Error('A file blocks this folder.');
              id = existing?.id ?? (await live.create(destination, parent, part)).id;
              destinations.set(prefix, id);
            }
            parent = id;
          }
          remaining = files.slice(index);
          const siblings = await live.list(destination, parent);
          const conflict = siblings.find((node) => node.name === name);
          if (conflict && mode === 'ask') throw new NameConflict([name]);
          const filename = conflict && mode === 'keep' ? uniqueName(name, siblings, parent) : name;
          const replace = conflict && mode === 'replace' ? conflict : undefined;
          if (replace?.kind === 'folder')
            throw new Error('A folder cannot be replaced by a file. Choose Keep both instead.');
          const quota = await live.quota();
          if (file.size > quota.total - quota.used)
            throw new Error(
              'There is not enough workspace storage for this file. Free space in Trash and try again.',
            );
          await live.upload(
            destination,
            parent,
            file,
            filename,
            (loaded, total) =>
              reportProgress((index + (total ? loaded / total : 1)) / files.length),
            replace,
            { signal },
          );
          onUploaded();
          reportProgress((index + 1) / files.length);
        }
        await refreshLive();
      }
      setConflict(null);
    } catch (error) {
      if (error instanceof NameConflict)
        setConflict({
          names: error.names,
          upload: true,
          retry: async (next) => {
            uploads.remove(uploadId);
            await upload(remaining, destination, parentId, next);
          },
        });
      throw error;
    }
  }
  async function saveText(node: StorageNode, text: string) {
    const updated = await live.save(node, text);
    client.setQueryData<StorageSnapshot>(key, (current) => ({
      nodes: (current?.nodes ?? []).map((n) => (n.id === node.id ? updated : n)),
    }));
    await refreshLive();
    return updated;
  }
  const ensureConversationStorage = useCallback(
    async (agentId: string) => {
      const res = await backend.api!<{ storage_id: string; root_node_id: string }>(
        `/v1/workspaces/${workspace.id}/letas/${agentId}/conversation-storage`,
        { method: 'POST', body: '{}' },
      );
      live?.bind(res.storage_id, res.root_node_id);
      await client.invalidateQueries({
        queryKey: ['storage-roots', backend.actorId, workspace.id],
      });
      return {
        id: res.storage_id,
        name: 'Conversation',
        root: res.root_node_id,
        write: true,
      };
    },
    [backend.api, backend.actorId, workspace.id, live, client],
  );
  function paste() {
    if (clipboard) void move({ ...clipboard, storage: storage.id, parent });
  }
  return {
    workspace,
    ensureConversationStorage,
    resumeLocation: locations.current[storage.id] ?? { folder: folder?.id ?? '', file: '' },
    unavailable:
      (!!rootsQuery.data || !!options.root) && !roots.some((root) => root.id === storage.id),
    attachFiles: options.onAttachFiles,
    roots,
    quota: quotaQuery,
    query: {
      ...query,
      isPending: (!options.root && rootsQuery.isPending) || folderQuery.isPending,
      error:
        rootsQuery.error ??
        folderQuery.error ??
        (pathError && pathError.target === (search.file || requestedFolder)
          ? new Error(pathError.message)
          : null),
    },
    snapshot,
    storage,
    parent,
    folderId: folder?.id ?? '',
    path,
    file,
    lineTarget,
    trash,
    visible,
    selected,
    setSelected,
    selecting,
    setSelecting,
    toggle,
    clearSelection,
    filter,
    setFilter,
    type,
    setType,
    sort,
    setSort,
    transfer,
    setTransfer,
    nameRequest,
    setNameRequest,
    saveName,
    saveText,
    getTextSession,
    setTextSession,
    deleteIds,
    setDeleteIds,
    remove,
    restore,
    purgeIds,
    setPurgeIds,
    purge,
    details,
    setDetails,
    conflict,
    setConflict,
    progress,
    pending,
    view,
    setView,
    go,
    open,
    closeFile,
    openFiles,
    closeRequest,
    setCloseRequest,
    move,
    loadFolder,
    download,
    upload,
    searchContent: live.searchContent,
    clipboard,
    setClipboard,
    paste,
    dropTarget,
    setDropTarget,
    drop,
    report,
  };
}
export function fileCategory(node: StorageNode) {
  if (node.mime.startsWith('image/')) return 'images';
  if (/csv|spreadsheet/.test(node.mime)) return 'spreadsheets';
  if (/audio|video/.test(node.mime)) return 'media';
  if (/pdf|markdown|word|presentation/.test(node.mime)) return 'documents';
  return 'other';
}
export type StorageBrowser = ReturnType<typeof useBrowser>;
const Context = createContext<StorageBrowser | null>(null);
export function StorageProvider({
  workspace,
  children,
  root,
  onOpenFile,
  onAttachFiles,
}: BrowserOptions & {
  workspace: {
    id: string;
    name?: string;
    agents: readonly { id?: string; name: string; role?: string }[];
  };
  children: ReactNode;
}) {
  const browser = useBrowser(workspace, { root, onOpenFile, onAttachFiles });
  return <Context.Provider value={browser}>{children}</Context.Provider>;
}
export function useStorageBrowser() {
  const value = useContext(Context);
  if (!value) throw new Error('StorageProvider is missing.');
  return value;
}
export function effectiveWrite(browser: StorageBrowser, nodes: StorageNode[]) {
  return nodes.every((node) => browser.roots.find((root) => root.id === node.storage)?.write);
}
export { fileBlob, branch, ancestors, rootId };
export type { StorageNode, StorageRoot };
