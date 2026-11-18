import { zipSync } from 'fflate';

export interface StorageRoot {
  id: string;
  name: string;
  agent?: string;
  agentId?: string;
  isConversation?: boolean;
  title?: string;
  write: boolean;
  manageAccess?: boolean;
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
  fileType?: 'FILE_TYPE_TEXT' | 'FILE_TYPE_BLOB';
  processing?: { stage: string; errorCode?: string };
  readonly?: boolean;
  trashId?: string;
  read?: () => Promise<Blob>;
  thumbnail?: () => Promise<Blob>;
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
