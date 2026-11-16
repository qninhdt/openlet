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
import { useBackend } from '@/lib/backend';
import { storageApi } from '@/lib/storage-api';
import { toast } from 'sonner';
import {
  ancestors,
  branch,
  loadStorage,
  updateStorage,
  rootId,
  storageRoots,
  topNodes,
  type StorageNode,
  type StorageSnapshot,
  type StorageRoot,
  type Collision,
  NameConflict,
  uniqueName,
  transferNodes,
  trashNodes,
  restoreNode,
  validateName,
  fileBlob,
  downloadNodes,
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
  { kind: 'create'; parent: string; storage: string } | { kind: 'rename'; node: StorageNode };
type BrowserOptions = {
  root?: StorageRoot & { root?: string };
  onOpenFile?: (node: StorageNode) => void;
  onAttachFiles?: (nodes: StorageNode[]) => void;
};
function useBrowser(
  workspace: { id: string; agents: readonly { name: string; role?: string }[] },
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
    () => (backend.api ? storageApi(backend.api, workspace.id) : null),
    [backend.api, workspace.id],
  );
  const rootsQuery = useQuery({
    queryKey: ['storage-roots', backend.actorId, workspace.id],
    queryFn: () => live!.listRoots(),
    enabled: !!live && backend.ready && !options.root,
    refetchInterval: 30_000,
  });
  if (options.root?.root) live?.bind(options.root.id, options.root.root);
  const previewRoots = useMemo(() => storageRoots(workspace), [workspace]);
  const rawRoots: StorageRoot[] = options.root
    ? [options.root]
    : live
      ? (rootsQuery.data ?? [{ id: 'loading', name: 'Storage', write: false }])
      : previewRoots;
  const roots = rawRoots.map((root) => {
    if ('root' in root && typeof root.root === 'string') live?.bind(root.id, root.root);
    const agent = workspace.agents.find((a) => a.name === root.name);
    return agent ? { ...root, agent: agent.name, title: agent.role } : root;
  });
  const key = [live ? 'storage-live' : 'storage-preview', backend.actorId, workspace.id];
  const query = useQuery({
    queryKey: key,
    queryFn: () =>
      live
        ? Promise.resolve({ nodes: [] } as StorageSnapshot)
        : loadStorage(workspace.id, previewRoots),
    enabled: search.view === 'storage',
    staleTime: Infinity,
  });
  const snapshot = query.data ?? { nodes: [] };
  const queue = useRef(Promise.resolve());
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
  const [pending, setPending] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [selecting, setSelecting] = useState(false);
  const anchor = useRef<string | null>(null);
  const [filter, setFilter] = useState('');
  const [type, setType] = useState('all');
  const [sort, setSort] = useState('name');
  const [transfer, setTransfer] = useState<TransferRequest | null>(null);
  const [nameRequest, setNameRequest] = useState<NameRequest | null>(null);
  const [deleteIds, setDeleteIds] = useState<string[]>([]);
  const [details, setDetails] = useState<StorageNode | null>(null);
  const [conflict, setConflict] = useState<{
    names: string[];
    retry: (mode: Collision) => Promise<void>;
  } | null>(null);
  const [progress, setProgress] = useState<{ label: string; done: number; total: number } | null>(
    null,
  );
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
    if (!live) return;
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
    if (!live) return;
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
    await client.invalidateQueries({ queryKey: ['storage-folder', backend.actorId, workspace.id] });
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
  async function change(update: (current: StorageSnapshot) => StorageSnapshot) {
    setPending((n) => n + 1);
    const run = queue.current.then(async () => {
      const current = client.getQueryData<StorageSnapshot>(key);
      if (!current) throw new Error('Wait for storage to finish loading.');
      if (live) throw new Error('This operation must use the storage API.');
      const next = await updateStorage(workspace.id, previewRoots, update);
      client.setQueryData(key, next);
    });
    queue.current = run.catch(() => undefined);
    try {
      await run;
    } finally {
      setPending((n) => n - 1);
    }
  }
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
  function open(node: StorageNode) {
    if (trash) return;
    if (node.kind === 'folder') go(node.storage, node.id);
    else if (options.onOpenFile) options.onOpenFile(node);
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
      if (live) {
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
      } else
        await change((current) =>
          transferNodes(current, request.ids, request.storage, request.parent, request.copy, mode),
        );
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
    if (!nameRequest) return;
    const request = nameRequest;
    const nextName = validateName(name);
    const storage = request.kind === 'create' ? request.storage : request.node.storage;
    writable(storage);
    if (live) {
      if (request.kind === 'create') await live.create(storage, request.parent, nextName);
      else await live.transfer(request.node, storage, request.node.parent, false, nextName);
      await refreshLive();
      setNameRequest(null);
      return;
    }
    await change((current) => {
      const parent =
        request.kind === 'create'
          ? request.parent
          : current.nodes.find((node) => node.id === request.node.id)?.parent;
      if (!parent) throw new Error('This item is no longer available.');
      if (
        current.nodes.some(
          (node) =>
            node.parent === parent &&
            !node.trashed &&
            node.name === nextName &&
            (request.kind === 'create' || node.id !== request.node.id),
        )
      )
        throw new Error('An item with that name already exists.');
      if (request.kind === 'rename')
        return {
          nodes: current.nodes.map((node) =>
            node.id === request.node.id ? { ...node, name: nextName, updated: Date.now() } : node,
          ),
        };
      return {
        nodes: [
          ...current.nodes,
          {
            id: crypto.randomUUID(),
            storage,
            parent,
            name: nextName,
            kind: 'folder',
            mime: '',
            size: 0,
            updated: Date.now(),
          },
        ],
      };
    });
    setNameRequest(null);
  }
  async function remove(ids = deleteIds) {
    try {
      for (const node of topNodes(snapshot.nodes, ids)) writable(node.storage);
      if (live) {
        for (const node of topNodes(snapshot.nodes, ids)) await live.trash(node);
        await refreshLive();
      } else await change((current) => trashNodes(current, ids));
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
      } else await change((current) => ids.reduce((next, id) => restoreNode(next, id), current));
      clearSelection();
      toast.success('Restored');
    } catch (error) {
      report(error);
    }
  }
  async function download(ids: string[]) {
    try {
      setProgress({ label: 'Preparing download', done: 0, total: ids.length });
      const downloadSnapshot = live
        ? { nodes: (await Promise.all(topNodes(snapshot.nodes, ids).map(live.descendants))).flat() }
        : snapshot;
      await downloadNodes(downloadSnapshot, ids, (done, total) =>
        setProgress({ label: 'Preparing download', done, total }),
      );
    } catch (error) {
      report(error);
    } finally {
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
    await uploads.enqueue({
      id,
      name: files.length === 1 ? files[0].file.name : `${files.length} files`,
      destination: roots.find((root) => root.id === destination)?.name ?? 'Storage',
      run: (report) => performUpload(files, destination, parentId, mode, report, id),
    });
  }
  async function performUpload(
    files: UploadFile[],
    destination = storage.id,
    parentId = parent,
    mode: Collision,
    reportProgress: (fraction: number) => void,
    uploadId: string,
  ) {
    if (!files.length) return;
    let remaining = files;
    try {
      writable(destination);
      reportProgress(0);
      if (live) {
        const destinations = new Map<string, string>([['', parentId]]);
        for (const [index, { file, path }] of files.entries()) {
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
          if (conflict && mode === 'replace') await live.trash(conflict);
          await live.upload(destination, parent, file, filename, (loaded, total) =>
            reportProgress((index + (total ? loaded / total : 1)) / files.length),
          );
          reportProgress((index + 1) / files.length);
        }
        await refreshLive();
      } else
        await change((current) => {
          let next = { nodes: [...current.nodes] };
          const destinations = new Map<string, string>([['', parentId]]);
          for (const [index, { file, path }] of files.entries()) {
            const parts = path.split('/').filter(Boolean).map(validateName);
            const filename = parts.pop() ?? validateName(file.name);
            let parent = parentId;
            let directoryPath = '';
            for (const part of parts) {
              directoryPath += '/' + part;
              let id = destinations.get(directoryPath);
              if (!id) {
                const existing = next.nodes.find(
                  (node) => node.parent === parent && node.name === part && !node.trashed,
                );
                if (existing && existing.kind !== 'folder')
                  throw new Error(`A file named ${part} blocks this folder.`);
                id = existing?.id ?? crypto.randomUUID();
                if (!existing)
                  next.nodes.push({
                    id,
                    storage: destination,
                    parent,
                    name: part,
                    kind: 'folder',
                    mime: '',
                    size: 0,
                    updated: Date.now(),
                  });
                destinations.set(directoryPath, id);
              }
              parent = id;
            }
            const incoming: StorageNode = {
              id: crypto.randomUUID(),
              storage: destination,
              parent: 'incoming',
              name: filename,
              kind: 'file',
              mime: file.type || mimeForName(filename),
              size: file.size,
              updated: file.lastModified,
              blob: file,
            };
            next.nodes.push(incoming);
            next = transferNodes(next, [incoming.id], destination, parent, false, mode);
            reportProgress((index + 1) / files.length);
          }
          return next;
        });
      setConflict(null);
    } catch (error) {
      if (error instanceof NameConflict)
        setConflict({
          names: error.names,
          retry: async (next) => {
            uploads.remove(uploadId);
            await upload(remaining, destination, parentId, next);
          },
        });
      throw error;
    }
  }
  async function saveText(node: StorageNode, text: string) {
    if (live) {
      const updated = await live.save(node, text);
      client.setQueryData<StorageSnapshot>(key, (current) => ({
        nodes: (current?.nodes ?? []).map((n) => (n.id === node.id ? updated : n)),
      }));
      await refreshLive();
      return updated;
    }
    const blob = new Blob([text], { type: node.mime || 'text/plain' });
    if (blob.size > 1_000_000) throw new Error('Text editing is limited to 1 MB.');
    const updated = {
      ...node,
      blob,
      url: undefined,
      size: blob.size,
      updated: Date.now(),
      version: (node.version ?? 0) + 1,
    };
    await change((current) => {
      const existing = current.nodes.find((item) => item.id === node.id);
      if (!existing || ancestors(current.nodes, node.id).some((item) => item.trashed))
        throw new Error('This file is no longer available.');
      writable(existing.storage);
      if (
        (existing.version ?? 0) !== (node.version ?? 0) ||
        existing.url !== node.url ||
        existing.updated !== node.updated
      )
        throw new Error('This file changed since you opened it. Reopen it before saving.');
      return { nodes: current.nodes.map((item) => (item.id === node.id ? updated : item)) };
    });
    return updated;
  }
  function paste() {
    if (clipboard) void move({ ...clipboard, storage: storage.id, parent });
  }
  return {
    resumeLocation: locations.current[storage.id] ?? { folder: folder?.id ?? '', file: '' },
    unavailable:
      (!live || !!rootsQuery.data || !!options.root) &&
      (!roots.some((root) => root.id === storage.id) ||
        (!live &&
          !!query.data &&
          ((!!search.file && !file) ||
            (!!requestedFolder && requestedFolder !== 'trash' && !folder)))),
    attachFiles: options.onAttachFiles,
    roots,
    query: live
      ? {
          ...query,
          isPending: (!options.root && rootsQuery.isPending) || folderQuery.isPending,
          error:
            rootsQuery.error ??
            folderQuery.error ??
            (pathError && pathError.target === (search.file || requestedFolder)
              ? new Error(pathError.message)
              : null),
        }
      : query,
    snapshot,
    storage,
    parent,
    folderId: folder?.id ?? '',
    path,
    file,
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
export function mimeForName(name: string) {
  const extension = name.split('.').pop()?.toLowerCase();
  return (
    (
      {
        md: 'text/markdown',
        txt: 'text/plain',
        json: 'application/json',
        csv: 'text/csv',
        html: 'text/html',
        js: 'text/javascript',
        ts: 'text/plain',
        xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      } as Record<string, string>
    )[extension ?? ''] ?? 'application/octet-stream'
  );
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
  workspace: { id: string; agents: readonly { name: string; role?: string }[] };
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
