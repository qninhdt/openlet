import { zipSync } from 'fflate';

export interface StorageRoot {
  id: string;
  name: string;
  agent?: string;
  title?: string;
  write: boolean;
}
export interface StorageNode {
  id: string;
  storage: string;
  parent: string;
  name: string;
  kind: 'folder' | 'file';
  mime: string;
  size: number;
  updated: number;
  blob?: Blob;
  version?: number;
  readonly?: boolean;
  trashId?: string;
  read?: () => Promise<Blob>;
  url?: string;
  trashed?: boolean;
  originalParent?: string;
}
export interface StorageSnapshot {
  nodes: StorageNode[];
}
export type Collision = 'ask' | 'keep' | 'replace';
export class NameConflict extends Error {
  names: string[];
  constructor(names: string[]) {
    super(`Already exists: ${names.join(', ')}`);
    this.names = names;
  }
}
export const rootId = (storage: string) => `root:${storage}`;
export function storageRoots(workspace: {
  id: string;
  agents: readonly { name: string }[];
}): StorageRoot[] {
  return [
    { id: `${workspace.id}:personal`, name: 'Personal', write: true },
    { id: `${workspace.id}:team`, name: 'Team', write: true },
    ...workspace.agents.map((agent) => ({
      id: `${workspace.id}:${agent.name.toLowerCase()}`,
      name: agent.name,
      agent: agent.name,
      write: true,
    })),
  ];
}
export function ancestors(nodes: StorageNode[], id: string): StorageNode[] {
  const path: StorageNode[] = [];
  const seen = new Set<string>();
  let at = nodes.find((node) => node.id === id);
  while (at && !seen.has(at.id)) {
    seen.add(at.id);
    path.unshift(at);
    at = nodes.find((node) => node.id === at!.parent);
  }
  return path;
}
export function branch(nodes: StorageNode[], id: string): StorageNode[] {
  const ids = new Set([id]);
  let before = 0;
  while (before !== ids.size) {
    before = ids.size;
    for (const node of nodes) if (ids.has(node.parent)) ids.add(node.id);
  }
  return nodes.filter((node) => ids.has(node.id));
}
export function topNodes(nodes: StorageNode[], ids: string[]): StorageNode[] {
  const picked = new Set(ids);
  return nodes.filter(
    (node) =>
      picked.has(node.id) && !ancestors(nodes, node.parent).some((parent) => picked.has(parent.id)),
  );
}
export function validateName(name: string): string {
  const value = name.trim();
  if (
    !value ||
    value === '.' ||
    value === '..' ||
    value.includes('/') ||
    value.includes('\0') ||
    value.length > 255
  )
    throw new Error('Use a name of 1–255 characters without slashes.');
  return value;
}
export function uniqueName(name: string, nodes: StorageNode[], parent: string): string {
  const dot = name.lastIndexOf('.');
  const base = dot > 0 ? name.slice(0, dot) : name;
  const ext = dot > 0 ? name.slice(dot) : '';
  let next = name;
  for (
    let n = 2;
    nodes.some((node) => !node.trashed && node.parent === parent && node.name === next);
    n++
  )
    next = `${base} (${n})${ext}`;
  return next;
}
export function trashNodes(snapshot: StorageSnapshot, ids: string[]): StorageSnapshot {
  const roots = new Set(topNodes(snapshot.nodes, ids).map((node) => node.id));
  return {
    nodes: snapshot.nodes.map((node) =>
      roots.has(node.id)
        ? { ...node, trashed: true, originalParent: node.parent, parent: `trash:${node.storage}` }
        : node,
    ),
  };
}
export function transferNodes(
  snapshot: StorageSnapshot,
  ids: string[],
  storage: string,
  parent: string,
  copy: boolean,
  collision: Collision,
): StorageSnapshot {
  let nodes = [...snapshot.nodes];
  const sources = topNodes(nodes, ids);
  const destination = nodes.find((node) => node.id === parent);
  if (
    parent !== rootId(storage) &&
    (!destination ||
      destination.kind !== 'folder' ||
      destination.storage !== storage ||
      ancestors(nodes, destination.id).some((node) => node.trashed))
  )
    throw new Error('The destination folder is no longer available.');
  for (const source of sources) {
    if (ancestors(nodes, source.id).some((node) => node.trashed))
      throw new Error('Restore this item before moving it.');
    if (source.id === parent || ancestors(nodes, parent).some((node) => node.id === source.id))
      throw new Error('A folder cannot be moved or copied into itself.');
  }
  const conflicts = sources.filter(
    (source) =>
      (copy || source.parent !== parent) &&
      nodes.some((node) => node.parent === parent && !node.trashed && node.name === source.name),
  );
  if (collision === 'ask' && conflicts.length)
    throw new NameConflict(conflicts.map((node) => node.name));
  for (const source of sources) {
    if (!copy && source.parent === parent) continue;
    const conflict = nodes.find(
      (node) => node.parent === parent && !node.trashed && node.name === source.name,
    );
    if (conflict && collision === 'ask') throw new NameConflict([source.name]);
    const name =
      conflict && collision === 'keep' ? uniqueName(source.name, nodes, parent) : source.name;
    if (conflict && collision === 'replace') nodes = trashNodes({ nodes }, [conflict.id]).nodes;
    const children = branch(nodes, source.id);
    const mapping = new Map(
      children.map((node) => [node.id, copy ? crypto.randomUUID() : node.id]),
    );
    const moved = children.map((node) => ({
      ...node,
      id: mapping.get(node.id)!,
      storage,
      parent: node.id === source.id ? parent : mapping.get(node.parent)!,
      name: node.id === source.id ? name : node.name,
      updated: Date.now(),
    }));
    if (!copy) nodes = nodes.filter((node) => !mapping.has(node.id));
    nodes.push(...moved);
  }
  return { nodes };
}
export function restoreNode(snapshot: StorageSnapshot, id: string): StorageSnapshot {
  const node = snapshot.nodes.find((item) => item.id === id);
  if (!node?.trashed) throw new Error('This item is no longer in Trash.');
  const original = snapshot.nodes.find((item) => item.id === node.originalParent);
  const parent =
    original && !ancestors(snapshot.nodes, original.id).some((item) => item.trashed)
      ? original.id
      : rootId(node.storage);
  const name = uniqueName(node.name, snapshot.nodes, parent);
  return {
    nodes: snapshot.nodes.map((item) =>
      item.id === id ? { ...item, parent, name, trashed: false, originalParent: undefined } : item,
    ),
  };
}
export function seedStorage(roots: StorageRoot[]): StorageSnapshot {
  const nodes: StorageNode[] = [];
  const updated = new Date('2026-11-15T09:30:00Z').getTime();
  const folder = (storage: string, parent: string, id: string, name: string) => {
    const node = {
      id: `${storage}:${id}`,
      storage,
      parent,
      name,
      kind: 'folder' as const,
      mime: '',
      size: 0,
      updated,
    };
    nodes.push(node);
    return node.id;
  };
  const text = (
    storage: string,
    parent: string,
    id: string,
    name: string,
    body: string,
    mime = 'text/plain',
  ) => {
    const blob = new Blob([body], { type: mime });
    nodes.push({
      id: `${storage}:${id}`,
      storage,
      parent,
      name,
      kind: 'file',
      mime,
      size: blob.size,
      updated,
      blob,
    });
  };
  for (const root of roots) {
    const parent = rootId(root.id);
    if (root.agent) {
      const reports = folder(root.id, parent, 'reports', 'Reports');
      text(
        root.id,
        parent,
        'notes',
        'Notes.md',
        `# ${root.agent}\n\nWorking notes and files for this agent.\n\n- Research\n- Drafts\n- Reports\n`,
        'text/markdown',
      );
      text(
        root.id,
        reports,
        'summary',
        'Summary.md',
        '# Weekly summary\n\nThe first draft is ready for review.\n',
        'text/markdown',
      );
      continue;
    }
    const documents = folder(root.id, parent, 'documents', 'Documents');
    const images = folder(root.id, parent, 'images', 'Images');
    const projects = folder(root.id, documents, 'projects', 'Projects');
    text(
      root.id,
      parent,
      'readme',
      'Getting started.md',
      '# A place for your work\n\nKeep documents, references, and agent output together.\n\n## This folder\n\n- **Documents** — briefs and project notes\n- **Images** — visual references\n\nChoose a storage on the left, or open a folder to explore.\n',
      'text/markdown',
    );
    text(
      root.id,
      documents,
      'brief',
      'Project brief.md',
      '# OpenLet\n\n## Goal\n\nA shared workspace for people, agents, and files.\n\n| Milestone | Status |\n| --- | --- |\n| App shell | Ready |\n| Storage | In review |\n\n> Keep the useful things close.\n',
      'text/markdown',
    );
    text(
      root.id,
      projects,
      'config',
      'workspace.json',
      '{\n  "name": "OpenLet",\n  "storage": "cloud",\n  "agents": ["Atlas", "Scout"]\n}\n',
      'application/json',
    );
    text(
      root.id,
      parent,
      'budget',
      'Budget.csv',
      'Item,Planned,Actual\nDesign,2400,2100\nDevelopment,6800,6400\nOperations,900,750\n',
      'text/csv',
    );
    for (const [image, name, size] of [
      ['studio', 'Studio.jpg', 117227],
      ['forest', 'Forest.jpg', 219300],
      ['coast', 'Coast.jpg', 169615],
    ] as const) {
      nodes.push({
        id: `${root.id}:${image}`,
        storage: root.id,
        parent: images,
        name,
        kind: 'file',
        mime: 'image/jpeg',
        size,
        updated,
        url: `/storage-preview/${image}.jpg`,
      });
    }
    if (root.name === 'Team') {
      for (const image of nodes.filter((node) => node.parent === images))
        nodes.push({ ...image, id: `${image.id}:root`, parent });
    }
  }
  return { nodes };
}
let database: Promise<IDBDatabase> | undefined;
function db(): Promise<IDBDatabase> {
  return (database ??= new Promise((resolve, reject) => {
    const request = indexedDB.open('openlet-storage-preview', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('workspaces');
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => {
      database = undefined;
      reject(request.error);
    };
  }));
}
// Browser-local data is used only when authentication is disabled.
export async function loadStorage(
  workspace: string,
  roots: StorageRoot[],
): Promise<StorageSnapshot> {
  const database = await db();
  return new Promise((resolve, reject) => {
    const request = database.transaction('workspaces').objectStore('workspaces').get(workspace);
    request.onsuccess = () => resolve(request.result ?? seedStorage(roots));
    request.onerror = () => reject(request.error);
  });
}
export async function saveStorage(workspace: string, snapshot: StorageSnapshot): Promise<void> {
  const database = await db();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction('workspaces', 'readwrite');
    transaction.objectStore('workspaces').put(snapshot, workspace);
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () =>
      reject(transaction.error ?? new Error('Storage save was interrupted.'));
  });
}
export async function updateStorage(
  workspace: string,
  roots: StorageRoot[],
  update: (snapshot: StorageSnapshot) => StorageSnapshot,
): Promise<StorageSnapshot> {
  const database = await db();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction('workspaces', 'readwrite');
    const store = transaction.objectStore('workspaces');
    const request = store.get(workspace);
    let next: StorageSnapshot;
    request.onsuccess = () => {
      try {
        next = update(request.result ?? seedStorage(roots));
        store.put(next, workspace);
      } catch (error) {
        transaction.abort();
        reject(error);
      }
    };
    transaction.oncomplete = () => resolve(next);
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () =>
      reject(transaction.error ?? new Error('Storage save was interrupted.'));
  });
}
export async function fileBlob(node: StorageNode): Promise<Blob> {
  if (node.read) return node.read();
  if (node.blob) return node.blob;
  if (node.url) {
    const response = await fetch(node.url);
    if (!response.ok) throw new Error(`Could not read ${node.name}.`);
    return response.blob();
  }
  throw new Error(`The contents of ${node.name} are unavailable.`);
}
function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
export async function downloadNodes(
  snapshot: StorageSnapshot,
  ids: string[],
  onProgress: (done: number, total: number) => void,
) {
  const selected = topNodes(snapshot.nodes, ids);
  if (selected.length === 1 && selected[0].kind === 'file') {
    saveBlob(await fileBlob(selected[0]), selected[0].name);
    onProgress(1, 1);
    return;
  }
  const entries: Record<string, Uint8Array> = {};
  let done = 0;
  const files = selected.flatMap((node) => branch(snapshot.nodes, node.id));
  for (const root of selected) {
    for (const node of branch(snapshot.nodes, root.id)) {
      const path = ancestors(snapshot.nodes, node.id)
        .slice(ancestors(snapshot.nodes, root.id).length - 1)
        .map((item) => item.name)
        .join('/');
      if (node.kind === 'folder') entries[path + '/'] = new Uint8Array();
      else entries[path] = new Uint8Array(await (await fileBlob(node)).arrayBuffer());
      onProgress(++done, files.length);
    }
  }
  saveBlob(
    new Blob([new Uint8Array(zipSync(entries)).buffer], { type: 'application/zip' }),
    'Files.zip',
  );
}
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
export function fileType(node: StorageNode): string {
  if (node.kind === 'folder') return 'folders';
  if (node.mime.startsWith('image/')) return 'images';
  if (/pdf|markdown|word|presentation/.test(node.mime)) return 'documents';
  if (/csv|spreadsheet/.test(node.mime) || /\.xlsx$/i.test(node.name)) return 'spreadsheets';
  if (/audio|video/.test(node.mime)) return 'media';
  return 'other';
}
