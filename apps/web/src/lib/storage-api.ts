import { Crc32c, crc32c } from '@aws-crypto/crc32c';
import { ApiError, type Api } from './agent-api.js';
import { readUploads, rememberUpload, forgetUpload, type UploadResume } from './upload-resume.js';
import { classifyFile } from './file-types.js';
import { rootId, type StorageNode, type StorageRoot } from './storage-preview.js';

type RemoteNode = {
  id: string;
  storageId: string;
  parentId?: string;
  name: string;
  kind: 'NODE_KIND_DIRECTORY' | 'NODE_KIND_FILE';
  updatedAt: string;
  readonly?: boolean;
  file?: {
    mediaType: string;
    sizeBytes: string;
    version: string;
    type?: StorageNode['fileType'];
    processing?: StorageNode['processing'];
  };
};
export type LiveStorage = StorageRoot & { root: string };
export function storageApi(
  api: Api,
  workspace: string,
  request?: ((path: string, init?: RequestInit) => Promise<Response>) | null,
  actor = '',
) {
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
    fileType: n.file?.type,
    processing: n.file?.processing,
    updated: Date.parse(n.updatedAt),
    readonly: n.readonly,
    read: () => blob(n.storageId, n.id),
    thumbnail: request
      ? async () =>
          (
            await request(`${base}/${n.storageId}/nodes/${n.id}/image?maxWidth=480&maxHeight=480`)
          ).blob()
      : undefined,
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
          capabilities?: { write?: boolean; manageAccess?: boolean };
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
          manageAccess: !!item.capabilities?.manageAccess,
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
    const trimmed = query.trim();
    const pattern =
      trimmed.includes('*') || trimmed.includes('?') || trimmed.includes('[')
        ? trimmed
        : `**/*${trimmed}*`;
    const result = await post<{
      hits?: {
        nodeId?: string;
        path?: string;
        artifactPath?: string;
        kind?: string;
        sizeBytes?: string;
        updatedAt?: string;
      }[];
    }>(`${base}/${storage}/files:glob`, {
      root: locator(storage, rootId(storage)),
      pattern,
      includeHidden: false,
      limit: 100,
    });
    const hits = (result.hits ?? []).filter((h) => !h.artifactPath && h.nodeId);
    const hydrated = await Promise.all(
      hits.map(async (hit) => {
        try {
          return await stat(storage, hit.nodeId!);
        } catch {
          const cleanPath = (hit.path ?? '').replace(/^\/+/, '');
          const name = cleanPath.split('/').pop() || hit.nodeId!;
          return {
            id: hit.nodeId!,
            storage,
            parent: rootId(storage),
            name,
            kind: hit.kind === 'directory' ? ('folder' as const) : ('file' as const),
            mime: '',
            size: Number(hit.sizeBytes ?? 0),
            version: 0,
            updated: hit.updatedAt ? Date.parse(hit.updatedAt) : Date.now(),
            read: () => blob(storage, hit.nodeId!),
          } satisfies StorageNode;
        }
      }),
    );
    return hydrated;
  }
  async function searchContent(
    storage: string,
    query: string,
    mode: 'text' | 'semantic',
    _pageToken = '',
  ): Promise<{
    hits: {
      fileId: string;
      path?: string;
      artifactPath?: string;
      text?: string;
      node?: StorageNode;
      lineNumber?: number;
    }[];
    nextPageToken?: string;
  }> {
    if (mode === 'semantic') {
      const page = await post<{
        hits?: {
          fileId: string;
          path: string;
          artifactPath?: string;
          text: string;
          score: number;
        }[];
      }>(`${base}/${storage}/files:semanticSearch`, { root: { path: '/' }, query, limit: 25 });
      return { hits: page.hits ?? [] };
    }
    const page = await post<{
      hits?: {
        fileId: string;
        path?: string;
        artifactPath?: string;
        lineNumber?: number;
        lineText?: string;
      }[];
      truncated?: boolean;
    }>(`${base}/${storage}/files:grep`, {
      root: locator(storage, rootId(storage)),
      pattern: query,
      literal: true,
      caseSensitive: false,
      limit: 100,
    });
    return {
      hits: (page.hits ?? []).map((hit) => ({
        fileId: hit.fileId,
        path: hit.path,
        artifactPath: hit.artifactPath,
        text: hit.lineText ?? '',
        lineNumber: hit.lineNumber,
      })),
    };
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
  async function path(current: StorageNode) {
    const names: string[] = [];
    const seen = new Set<string>();
    let at = current;
    while (!at.id.startsWith('root:')) {
      if (seen.has(at.id)) throw new Error('Could not resolve the file path.');
      seen.add(at.id);
      if (at.name) names.unshift(at.name);
      if (at.parent.startsWith('root:')) break;
      at = await stat(current.storage, at.parent);
    }
    return '/' + names.join('/');
  }
  async function retryProcessing(current: StorageNode, requestId: string) {
    return node(
      await post<RemoteNode>(`${base}/${current.storage}/nodes/${current.id}:retryProcessing`, {
        expectedVersion: String(current.version),
        requestId,
      }),
    );
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
    replace?: StorageNode,
    options: { signal?: AbortSignal; resume?: UploadResume } = {},
  ) {
    options.signal?.throwIfAborted();
    const { kind, mediaType } = classifyFile(name);
    if (kind === 'unsupported') throw new Error('Unsupported file extension.');
    const textFile = kind === 'text';
    if (replace && (replace.kind !== 'file' || replace.readonly))
      throw new Error('Only writable files can be replaced. Choose Keep both instead.');
    if (replace && replace.fileType !== (textFile ? 'FILE_TYPE_TEXT' : 'FILE_TYPE_BLOB'))
      throw new Error(
        'Replacing a file with a different storage type is not supported. Choose Keep both instead.',
      );
    if (textFile) {
      const text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(
        await file.arrayBuffer(),
      );
      options.signal?.throwIfAborted();
      onProgress?.(0, file.size);
      const created = replace
        ? await save(replace, text)
        : await create(storage, parent, name, { content: text, mediaType });
      onProgress?.(file.size, file.size);
      return created;
    }
    const signal = options.signal;
    const hash = new Crc32c();
    try {
      signal?.throwIfAborted();
      for (let offset = 0; offset < file.size; offset += 8 * 1024 * 1024) {
        signal?.throwIfAborted();
        hash.update(
          new Uint8Array(await file.slice(offset, offset + 8 * 1024 * 1024).arrayBuffer()),
        );
      }
      signal?.throwIfAborted();
    } catch (error) {
      if (signal?.aborted && signal.reason !== 'pause' && options.resume)
        await cancelUpload(options.resume);
      throw error;
    }
    const value = hash.digest();
    const digest = btoa(
      String.fromCharCode(value >>> 24, (value >>> 16) & 255, (value >>> 8) & 255, value & 255),
    );
    let saved =
      options.resume ??
      readUploads(actor).find(
        (item) =>
          item.workspace === workspace &&
          item.storage === storage &&
          item.parent === parent &&
          item.name === name &&
          item.checksum === digest &&
          item.size === file.size &&
          item.replace?.id === replace?.id &&
          item.replace?.version === replace?.version,
      );
    if (
      saved &&
      (saved.fileName !== file.name ||
        saved.size !== file.size ||
        saved.modified !== file.lastModified ||
        saved.checksum !== digest)
    )
      throw new Error('Select the original file with the same contents to resume this upload.');
    saved ??= {
      workspace,
      storage,
      parent,
      name,
      fileName: file.name,
      size: file.size,
      modified: file.lastModified,
      checksum: digest,
      requestId: crypto.randomUUID(),
      created: Date.now(),
      ...(replace ? { replace } : {}),
    };
    // Persist only transfer metadata; file bytes and signed URLs stay out of browser storage.
    rememberUpload(actor, saved);
    const put = (url: string, headers: Record<string, string>, body: Blob, offset = 0) =>
      new Promise<string | null>((resolve, reject) => {
        signal?.throwIfAborted();
        const xhr = new XMLHttpRequest();
        const abort = () => xhr.abort();
        xhr.open('PUT', url);
        for (const [key, value] of Object.entries(headers)) xhr.setRequestHeader(key, value);
        xhr.upload.onprogress = (event) => onProgress?.(offset + event.loaded, file.size);
        xhr.onload = () =>
          xhr.status >= 200 && xhr.status < 300
            ? resolve(xhr.getResponseHeader('etag'))
            : reject(new Error('Upload failed. Retry to resume the parts already sent.'));
        xhr.onerror = () =>
          reject(
            new Error(
              'Connection interrupted. Retry to resume, or select the same file after reopening the app.',
            ),
          );
        xhr.onabort = () => reject(new DOMException('Upload cancelled.', 'AbortError'));
        xhr.onloadend = () => signal?.removeEventListener('abort', abort);
        signal?.addEventListener('abort', abort, { once: true });
        xhr.send(body);
      });
    type Part = { partNumber: number; etag: string; checksum: string };
    type Upload = {
      id: string;
      completed?: RemoteNode;
      transferred?: boolean;
      completedParts?: Part[];
      transfer: {
        putUrl: string;
        headers: Record<string, string>;
        multipart?: boolean;
        partSizeBytes?: string;
      };
    };
    try {
      let transfer: Upload;
      if (saved.uploadId) {
        try {
          transfer = await api<Upload>(`${base}/${storage}/uploads/${saved.uploadId}`);
        } catch (error) {
          if (error instanceof ApiError && error.status === 404) {
            forgetUpload(actor, saved.requestId);
            delete saved.uploadId;
            saved.requestId = crypto.randomUUID();
            throw new Error('This upload has expired. Retry to start a new transfer.');
          }
          throw error;
        }
      } else {
        transfer = await post<Upload>(`${base}/${storage}/uploads`, {
          ...(replace
            ? {
                replace: {
                  target: { nodeId: replace.id },
                  expectedVersion: String(replace.version),
                },
              }
            : { create: { parent: locator(storage, parent), name } }),
          mediaType,
          sizeBytes: String(file.size),
          checksum: digest,
          requestId: saved.requestId,
        });
        saved.uploadId = transfer.id;
        rememberUpload(actor, saved);
      }
      if (transfer.completed) {
        forgetUpload(actor, saved.requestId);
        onProgress?.(file.size, file.size);
        return node(transfer.completed);
      }
      signal?.throwIfAborted();
      const parts: Part[] = [];
      if (!transfer.transferred && transfer.transfer.multipart) {
        const partSize = Number(transfer.transfer.partSizeBytes);
        if (!Number.isSafeInteger(partSize) || partSize <= 0)
          throw new Error('Invalid upload part size.');
        for (let offset = 0, partNumber = 1; offset < file.size; offset += partSize, partNumber++) {
          signal?.throwIfAborted();
          const body = file.slice(offset, offset + partSize);
          const digest = checksum(new Uint8Array(await body.arrayBuffer()));
          let part = transfer.completedParts?.find(
            (part) => part.partNumber === partNumber && part.checksum === digest && part.etag,
          );
          if (!part) {
            const signed = await post<{
              parts: { url: string; headers: Record<string, string> }[];
            }>(`${base}/${storage}/uploads/${transfer.id}:signParts`, {
              parts: [{ partNumber, checksum: digest }],
            });
            const etag = await put(signed.parts[0].url, signed.parts[0].headers, body, offset);
            if (!etag) throw new Error('Upload response is missing ETag. Check storage CORS.');
            part = { partNumber, etag, checksum: digest };
          }
          parts.push(part);
          onProgress?.(Math.min(offset + partSize, file.size), file.size);
        }
      } else if (!transfer.transferred) {
        await put(transfer.transfer.putUrl, transfer.transfer.headers, file);
      }
      signal?.throwIfAborted();
      const result = node(
        await post<RemoteNode>(`${base}/${storage}/uploads/${transfer.id}:complete`, { parts }),
      );
      forgetUpload(actor, saved.requestId);
      onProgress?.(file.size, file.size);
      return result;
    } catch (error) {
      if (signal?.aborted && signal.reason !== 'pause') {
        if (saved.uploadId)
          await api(`${base}/${storage}/uploads/${saved.uploadId}`, { method: 'DELETE' });
        forgetUpload(actor, saved.requestId);
        throw new DOMException('Upload cancelled.', 'AbortError');
      }
      throw error;
    }
  }
  async function cancelUpload(saved: UploadResume) {
    if (saved.uploadId)
      await api(`${base}/${saved.storage}/uploads/${saved.uploadId}`, { method: 'DELETE' });
    forgetUpload(actor, saved.requestId);
  }
  function resumeUpload(
    saved: UploadResume,
    file: File,
    onProgress: (loaded: number, total: number) => void,
    signal: AbortSignal,
  ) {
    return upload(saved.storage, saved.parent, file, saved.name, onProgress, saved.replace, {
      signal,
      resume: saved,
    });
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
  async function purge(current: StorageNode) {
    if (!current.trashId) throw new Error('Reload Trash before deleting this item.');
    await api(`${base}/${current.storage}/trash/${current.trashId}`, { method: 'DELETE' });
  }
  async function quota() {
    const result = await api<{ usedBytes: string; quotaBytes: string }>(
      `/v1/workspaces/${workspace}/storage-quota`,
    );
    return { used: Number(result.usedBytes ?? 0), total: Number(result.quotaBytes ?? 0) };
  }
  return {
    bind: (storage: string, root: string) => roots.set(storage, root),
    listRoots,
    list,
    search,
    searchContent,
    descendants,
    stat,
    path,
    retryProcessing,
    blob,
    save,
    create,
    transfer,
    upload,
    resumeUpload,
    cancelUpload,
    trash,
    listTrash,
    restore,
    purge,
    quota,
  };
}
