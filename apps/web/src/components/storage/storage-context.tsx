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
import { useNavigate, useSearch } from '@tanstack/react-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  ancestors,
  branch,
  loadStorage,
  saveStorage,
  rootId,
  storageRoots,
  topNodes,
  type StorageNode,
  type StorageSnapshot,
  type StorageRoot,
  type Collision,
  NameConflict,
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
function useBrowser(workspace: { id: string; agents: readonly { name: string }[] }) {
  const search = useSearch({ from: '/app' });
  const navigate = useNavigate();
  const client = useQueryClient();
  const roots = useMemo(() => storageRoots(workspace), [workspace]);
  const key = ['storage-preview', workspace.id];
  const query = useQuery({
    queryKey: key,
    queryFn: () => loadStorage(workspace.id, roots),
    enabled: search.view === 'storage',
    staleTime: Infinity,
  });
  const snapshot = query.data ?? { nodes: [] };
  const queue = useRef(Promise.resolve());
  const textSession = useRef<StorageTextSession | null>(null);
  const getTextSession = useCallback(() => textSession.current, []);
  const setTextSession = useCallback((session: StorageTextSession | null) => {
    textSession.current = session;
  }, []);
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
  const drag = useRef<string[]>([]);
  const [dragging, setDragging] = useState(0);
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
  const storage =
    roots.find((root) => root.id === search.storage) ??
    roots.find((root) => root.id === last?.storage) ??
    roots[0];
  const requestedFolder = search.folder || (search.storage ? '' : last?.folder);
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
      node.storage === storage.id &&
      !ancestors(snapshot.nodes, node.id).some((at) => at.trashed),
  );
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
    if (query.data && !trash)
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
  async function change(
    update: (current: StorageSnapshot) => StorageSnapshot | Promise<StorageSnapshot>,
  ) {
    setPending((n) => n + 1);
    const run = queue.current.then(async () => {
      const current = client.getQueryData<StorageSnapshot>(key);
      if (!current) throw new Error('Wait for storage to finish loading.');
      const next = await update(current);
      await saveStorage(workspace.id, next);
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
  function go(storage: string, folder = '') {
    void navigate({
      to: '/app',
      search: (previous) => ({ ...previous, view: 'storage', storage, folder, file: '' }),
    });
  }
  function open(node: StorageNode) {
    if (trash) return;
    if (node.kind === 'folder') go(node.storage, node.id);
    else void navigate({ to: '/app', search: (previous) => ({ ...previous, file: node.id }) });
  }
  function closeFile() {
    void navigate({ to: '/app', search: (previous) => ({ ...previous, file: '' }), replace: true });
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
    setDragging(0);
    drag.current = [];
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
      await change((current) => trashNodes(current, ids));
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
      await change((current) => ids.reduce((next, id) => restoreNode(next, id), current));
      clearSelection();
      toast.success('Restored');
    } catch (error) {
      report(error);
    }
  }
  async function download(ids: string[]) {
    try {
      setProgress({ label: 'Preparing download', done: 0, total: ids.length });
      await downloadNodes(snapshot, ids, (done, total) =>
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
    try {
      writable(destination);
      setProgress({ label: 'Uploading', done: 0, total: files.length });
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
          setProgress({ label: 'Uploading', done: index + 1, total: files.length });
        }
        return next;
      });
      setConflict(null);
      toast.success(`${files.length} file${files.length === 1 ? '' : 's'} uploaded`);
    } catch (error) {
      if (error instanceof NameConflict)
        setConflict({
          names: error.names,
          retry: (next) => upload(files, destination, parentId, next),
        });
      else report(error);
    } finally {
      setProgress(null);
    }
  }
  async function saveText(node: StorageNode, text: string) {
    const blob = new Blob([text], { type: node.mime || 'text/plain' });
    if (blob.size > 1_000_000) throw new Error('Text editing is limited to 1 MB.');
    const updated = { ...node, blob, url: undefined, size: blob.size, updated: Date.now() };
    await change((current) => {
      const existing = current.nodes.find((item) => item.id === node.id);
      if (!existing || ancestors(current.nodes, node.id).some((item) => item.trashed))
        throw new Error('This file is no longer available.');
      writable(existing.storage);
      if (
        existing.blob !== node.blob ||
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
    roots,
    query,
    snapshot,
    storage,
    parent,
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
    move,
    download,
    upload,
    clipboard,
    setClipboard,
    paste,
    drag,
    dragging,
    setDragging,
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
}: {
  workspace: { id: string; agents: readonly { name: string }[] };
  children: ReactNode;
}) {
  const browser = useBrowser(workspace);
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
