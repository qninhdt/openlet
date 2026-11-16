import { crc32c } from '@aws-crypto/crc32c';
import type { Api } from './agent-api.js';
import { rootId, type StorageNode, type StorageRoot } from './storage-preview.js';

type RemoteNode = {
  id: string;
  storageId: string;
  parentId?: string;
  name: string;
  kind: 'NODE_KIND_DIRECTORY' | 'NODE_KIND_FILE';
  updatedAt: string;
  readonly?: boolean;
  file?: { mediaType: string; sizeBytes: string; version: string };
};
export type LiveStorage = StorageRoot & { root: string };
export function storageApi(api: Api, workspace: string) {
  const base = `/v1/workspaces/${workspace}/storages`;
  const post = <T>(path: string, body: object) =>
    api<T>(path, { method: 'POST', body: JSON.stringify(body) });
  const roots = new Map<string, string>();
  const locator = (storage: string, id: string) => ({
    nodeId: id === rootId(storage) ? roots.get(storage) : id,
  });
  const node = (n: RemoteNode): StorageNode => ({
    id: n.id,
    storage: n.storageId,
    parent:
      n.parentId === roots.get(n.storageId)
        ? rootId(n.storageId)
        : (n.parentId ?? rootId(n.storageId)),
    name: n.name,
    kind: n.kind === 'NODE_KIND_DIRECTORY' ? 'folder' : 'file',
    mime: n.file?.mediaType ?? '',
    size: Number(n.file?.sizeBytes ?? 0),
    version: Number(n.file?.version ?? 0),
    updated: Date.parse(n.updatedAt),
    readonly: n.readonly,
    read: () => blob(n.storageId, n.id),
  });
  async function listRoots(): Promise<LiveStorage[]> {
    const result: LiveStorage[] = [];
    let cursor = '';
    do {
      const page = await api<{
        storages?: {
          id: string;
          name: string;
          rootNodeId: string;
          capabilities?: { write?: boolean };
        }[];
        nextPageToken?: string;
      }>(`${base}?pageSize=100&pageToken=${cursor}`);
      for (const item of page.storages ?? []) {
        roots.set(item.id, item.rootNodeId);
        result.push({
          id: item.id,
          name: item.name === 'Shared' ? 'Team' : item.name,
          root: item.rootNodeId,
          write: !!item.capabilities?.write,
        });
      }
      cursor = page.nextPageToken ?? '';
    } while (cursor);
    return result;
  }
  async function list(storage: string, parent: string): Promise<StorageNode[]> {
    const result: StorageNode[] = [];
    let cursor = '';
    do {
      const page = await api<{ nodes?: RemoteNode[]; nextPageToken?: string }>(
        `${base}/${storage}/nodes/${locator(storage, parent).nodeId}/children?pageSize=100&pageToken=${cursor}`,
      );
      result.push(...(page.nodes ?? []).map(node));
      cursor = page.nextPageToken ?? '';
    } while (cursor);
    return result;
  }
  async function search(storage: string, query: string): Promise<StorageNode[]> {
    const result = await post<{ hits?: RemoteNode[] }>(`${base}/${storage}/files:search`, {
      root: locator(storage, rootId(storage)),
      query,
      pageSize: 100,
    });
    return (result.hits ?? []).map(node);
  }
  async function descendants(current: StorageNode): Promise<StorageNode[]> {
    if (current.kind === 'file') return [current];
    const children = await list(current.storage, current.id);
    return [current, ...(await Promise.all(children.map(descendants))).flat()];
  }
  async function blob(storage: string, id: string) {
    const result = await api<{
      text?: { content?: string; mediaType: string };
      blob?: { url: string };
    }>(`${base}/${storage}/nodes/${id}:download`);
    if (result.text) return new Blob([result.text.content ?? ''], { type: result.text.mediaType });
    if (!result.blob) throw new Error('This file is no longer available.');
    const response = await fetch(result.blob.url);
    if (!response.ok) throw new Error('Could not download this file. Try again.');
    return response.blob();
  }
  async function stat(storage: string, id: string) {
    return node(await api<RemoteNode>(`${base}/${storage}/nodes/${id}`));
  }
  async function save(current: StorageNode, text: string) {
    return node(
      await api<RemoteNode>(`${base}/${current.storage}/nodes/${current.id}/text`, {
        method: 'PATCH',
        body: JSON.stringify({
          replace: text,
          expectedVersion: String(current.version),
          requestId: crypto.randomUUID(),
        }),
      }),
    );
  }
  async function create(
    storage: string,
    parent: string,
    name: string,
    text?: { content: string; mediaType: string },
  ) {
    return node(
      await post<RemoteNode>(`${base}/${storage}/nodes`, {
        parent: locator(storage, parent),
        name,
        ...(text ? { text } : { directory: {} }),
        requestId: crypto.randomUUID(),
      }),
    );
  }
  async function transfer(
    current: StorageNode,
    storage: string,
    parent: string,
    copy: boolean,
    name = current.name,
  ) {
    return node(
      await post<RemoteNode>(`${base}/${current.storage}/nodes:${copy ? 'copy' : 'move'}`, {
        source: { nodeId: current.id },
        destinationStorageId: storage,
        parent: locator(storage, parent),
        name,
        requestId: crypto.randomUUID(),
      }),
    );
  }
  const checksum = (bytes: Uint8Array) => {
    const value = crc32c(bytes);
    return btoa(
      String.fromCharCode(value >>> 24, (value >>> 16) & 255, (value >>> 8) & 255, value & 255),
    );
  };
  async function upload(
    storage: string,
    parent: string,
    file: File,
    name = file.name,
    onProgress?: (loaded: number, total: number) => void,
  ) {
    const mediaType =
      file.type ||
      (/\.(md|txt|csv|tsv|py|js|ts|tsx|jsx|go|rs|sh|sql|css|yaml|yml|toml|log)$/i.test(name)
        ? 'text/plain'
        : 'application/octet-stream');
    if (/^text\/|^application\/(json|xml|javascript|yaml|toml)$|\+(json|xml)$/.test(mediaType)) {
      const text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(
        await file.arrayBuffer(),
      );
      onProgress?.(0, file.size);
      const created = await create(storage, parent, name, { content: text, mediaType });
      onProgress?.(file.size, file.size);
      return created;
    }
    const put = (url: string, headers: Record<string, string>, body: Blob, offset = 0) =>
      new Promise<string | null>((resolve, reject) => {
        const request = new XMLHttpRequest();
        request.open('PUT', url);
        for (const [key, value] of Object.entries(headers)) request.setRequestHeader(key, value);
        request.upload.onprogress = (event) => onProgress?.(offset + event.loaded, file.size);
        request.onload = () =>
          request.status >= 200 && request.status < 300
            ? resolve(request.getResponseHeader('etag'))
            : reject(new Error('Upload failed. Retry this file.'));
        request.onerror = () =>
          reject(new Error('Upload failed. Check your connection and retry.'));
        request.send(body);
      });
    const bytes = new Uint8Array(await file.arrayBuffer());
    const upload = await post<{
      id: string;
      completed?: RemoteNode;
      transfer: {
        putUrl: string;
        headers: Record<string, string>;
        multipart?: boolean;
        partSizeBytes?: string;
      };
    }>(`${base}/${storage}/uploads`, {
      create: { parent: locator(storage, parent), name },
      mediaType,
      sizeBytes: String(file.size),
      checksum: checksum(bytes),
      requestId: crypto.randomUUID(),
    });
    if (upload.completed) {
      onProgress?.(file.size, file.size);
      return node(upload.completed);
    }
    try {
      const parts: { partNumber: number; etag: string; checksum: string }[] = [];
      if (upload.transfer.multipart) {
        const partSize = Number(upload.transfer.partSizeBytes);
        for (let offset = 0, partNumber = 1; offset < file.size; offset += partSize, partNumber++) {
          const body = file.slice(offset, offset + partSize);
          const digest = checksum(bytes.subarray(offset, offset + partSize));
          const signed = await post<{ parts: { url: string; headers: Record<string, string> }[] }>(
            `${base}/${storage}/uploads/${upload.id}:signParts`,
            { parts: [{ partNumber, checksum: digest }] },
          );
          const etag = await put(signed.parts[0].url, signed.parts[0].headers, body, offset);
          if (!etag) throw new Error('Upload response is missing ETag. Check storage CORS.');
          parts.push({ partNumber, etag, checksum: digest });
        }
      } else {
        await put(upload.transfer.putUrl, upload.transfer.headers, file);
      }
      return node(
        await post<RemoteNode>(`${base}/${storage}/uploads/${upload.id}:complete`, { parts }),
      );
    } catch (error) {
      await api(`${base}/${storage}/uploads/${upload.id}`, { method: 'DELETE' }).catch(() => {});
      throw error;
    }
  }
  async function trash(current: StorageNode) {
    await post(`${base}/${current.storage}/nodes/${current.id}:trash`, {
      requestId: crypto.randomUUID(),
    });
  }
  async function listTrash(storage: string) {
    const result: StorageNode[] = [];
    let cursor = '';
    do {
      const page = await api<{
        entries?: { id: string; node: RemoteNode }[];
        nextPageToken?: string;
      }>(`${base}/${storage}/trash?pageSize=100&pageToken=${cursor}`);
      result.push(
        ...(page.entries ?? []).map((entry) => ({
          ...node(entry.node),
          trashed: true,
          trashId: entry.id,
        })),
      );
      cursor = page.nextPageToken ?? '';
    } while (cursor);
    return result;
  }
  async function restore(current: StorageNode) {
    return node(
      await post<RemoteNode>(`${base}/${current.storage}/trash/${current.trashId}:restore`, {}),
    );
  }
  return {
    bind: (storage: string, root: string) => roots.set(storage, root),
    listRoots,
    list,
    search,
    descendants,
    stat,
    blob,
    save,
    create,
    transfer,
    upload,
    trash,
    listTrash,
    restore,
  };
}
