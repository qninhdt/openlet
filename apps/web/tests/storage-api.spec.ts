import { expect, test } from '@playwright/test';
import { storageApi } from '../src/lib/storage-api.js';
import type { Api } from '../src/lib/agent-api.js';
import { fileMarkdown, fileReferences, fileToken, fileText } from '../src/lib/file-refs.js';
import { readTextFile, serializeTextFile } from '../src/lib/text-file.js';
import { newAssistantMessages } from '../src/lib/message-sound.js';

const directory = (id: string, parentId = 'remote-root') => ({
  id,
  parentId,
  storageId: 'storage',
  name: id,
  kind: 'NODE_KIND_DIRECTORY',
  updatedAt: '2026-11-16T00:00:00Z',
});
const file = {
  ...directory('report.md', 'nested'),
  kind: 'NODE_KIND_FILE',
  file: { type: 'FILE_TYPE_TEXT', mediaType: 'text/markdown', sizeBytes: '4', version: '7' },
};

test('live adapter binds root IDs, paginates, searches nested files and loads full download branches', async () => {
  const calls: { path: string; body?: Record<string, unknown> }[] = [];
  const api: Api = async <T>(path: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ path, body });
    let result: unknown;
    if (path.endsWith('/storages?pageSize=100&pageToken='))
      result = {
        storages: [
          {
            id: 'storage',
            name: 'Shared',
            rootNodeId: 'remote-root',
            capabilities: { write: true },
          },
        ],
      };
    else if (path.includes('remote-root/children')) result = { nodes: [directory('nested')] };
    else if (path.includes('nested/children'))
      result = path.endsWith('pageToken=next')
        ? { nodes: [file] }
        : { nodes: [], nextPageToken: 'next' };
    else if (path.endsWith('/files:search')) result = { hits: [file] };
    else if (path.endsWith(':download'))
      result = { text: { content: 'data', mediaType: 'text/markdown' } };
    else throw new Error(`Unexpected API call: ${path}`);
    return result as T;
  };
  const files = storageApi(api, 'workspace');
  const roots = await files.listRoots();
  expect(roots).toEqual([
    { id: 'storage', name: 'Team', root: 'remote-root', write: true, manageAccess: false },
  ]);
  // A picker may receive cached roots populated by another adapter instance.
  const picker = storageApi(api, 'workspace');
  for (const root of roots) picker.bind(root.id, root.root);
  expect((await picker.list('storage', 'root:storage'))[0].parent).toBe('root:storage');
  await picker.search('storage', 'report');
  const folders = await files.list('storage', 'root:storage');
  expect(folders[0].parent).toBe('root:storage');
  const branch = await files.descendants(folders[0]);
  expect(branch.map((n) => n.id)).toEqual(['nested', 'report.md']);
  expect(await (await branch[1].read!()).text()).toBe('data');
  expect((await files.search('storage', 'report'))[0].version).toBe(7);
  expect(calls.find((call) => call.path.endsWith('/files:search'))?.body).toEqual({
    root: { nodeId: 'remote-root' },
    query: 'report',
    pageSize: 100,
  });
});

test('live edits pass the opened version and surface conflicts without silently replacing bytes', async () => {
  let body: Record<string, unknown> | undefined;
  const api: Api = async <T>(_path: string, init?: RequestInit): Promise<T> => {
    if (init?.method === 'PATCH') {
      body = JSON.parse(String(init.body));
      throw new Error('File changed. Reload before saving.');
    }
    return file as T;
  };
  const files = storageApi(api, 'workspace');
  const opened = await files.stat('storage', 'report.md');
  await expect(files.save(opened, 'my draft')).rejects.toThrow('File changed');
  expect(body).toMatchObject({ replace: 'my draft', expectedVersion: '7' });
  expect(opened.version).toBe(7);
});

test('file chips round-trip escaped custom labels without turning ordinary paths into references', () => {
  const reference = { storage_id: 'storage', node_id: 'node', label: 'bản [dự toán] \\ final' };
  const token = fileToken(reference);
  expect(fileReferences(`Review ${token} please`)).toEqual([reference]);
  expect(fileReferences('Budget.xlsx /mnt/storage/Budget.xlsx')).toEqual([]);
  expect(fileText(`Review ${token} please`)).toBe(`Review ${reference.label} please`);
});

test('replace keeps file identity and version checks for text and blob without trashing', async () => {
  const calls: { path: string; body?: Record<string, unknown> }[] = [];
  const api: Api = async <T>(path: string, init?: RequestInit) => {
    calls.push({ path, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    return (path.endsWith('/uploads') ? { completed: file } : file) as T;
  };
  const files = storageApi(api, 'workspace');
  const opened = await files.stat('storage', 'report.md');
  const text = new File(['new text'], 'report.md');
  await files.upload('storage', 'nested', text, text.name, undefined, opened);
  expect(calls.at(-1)).toMatchObject({
    path: '/v1/workspaces/workspace/storages/storage/nodes/report.md/text',
    body: { replace: 'new text', expectedVersion: '7' },
  });
  const binary = {
    ...opened,
    name: 'image.png',
    mime: 'image/png',
    fileType: 'FILE_TYPE_BLOB' as const,
  };
  await files.upload(
    'storage',
    'nested',
    new File(['png'], 'image.png', { type: 'image/png' }),
    'image.png',
    undefined,
    binary,
  );
  expect(calls.at(-1)?.body).toMatchObject({
    replace: { target: { nodeId: opened.id }, expectedVersion: '7' },
  });
  expect(calls.at(-1)?.body).not.toHaveProperty('create');
  const count = calls.length;
  await expect(
    files.upload('storage', 'nested', text, text.name, undefined, binary),
  ).rejects.toThrow('different storage type');
  await expect(
    files.upload('storage', 'nested', text, text.name, undefined, { ...opened, kind: 'folder' }),
  ).rejects.toThrow('Only writable files');
  expect(calls).toHaveLength(count);
  expect(calls.some((call) => call.path.includes(':trash'))).toBe(false);
});

test('Trash pagination retains deletion IDs and quota bytes are parsed', async () => {
  const deleted: string[] = [];
  const api: Api = async <T>(path: string, init?: RequestInit) => {
    if (init?.method === 'DELETE') {
      deleted.push(path);
      return {} as T;
    }
    if (path.endsWith('/storage-quota')) return { usedBytes: '1024', quotaBytes: '2048' } as T;
    return (
      path.endsWith('pageToken=next')
        ? { entries: [{ id: 'trash-two', node: { ...file, id: 'two' } }] }
        : { entries: [{ id: 'trash-one', node: file }], nextPageToken: 'next' }
    ) as T;
  };
  const files = storageApi(api, 'workspace');
  const trash = await files.listTrash('storage');
  expect(trash.map((node) => node.trashId)).toEqual(['trash-one', 'trash-two']);
  await files.purge(trash[1]);
  expect(deleted).toEqual(['/v1/workspaces/workspace/storages/storage/trash/trash-two']);
  await expect(files.purge({ ...trash[0], trashId: undefined })).rejects.toThrow('Reload Trash');
  expect(await files.quota()).toEqual({ used: 1024, total: 2048 });
});

test('file mentions render outside code while code examples stay literal', () => {
  const token = fileToken({ storage_id: 'storage', node_id: 'node', label: 'draft [1]' });
  expect(fileMarkdown(token)).toContain('(openlet-file:storage/node)');
  for (const code of [
    `\`${token}\``,
    `\`\`${token}\`\``,
    `\`\`\`md\n${token}\n\`\`\``,
    `~~~\n${token}\n~~~~`,
    `\`\`\`\n${token}`,
  ])
    expect(fileMarkdown(code)).toBe(code);
  expect(fileMarkdown(`\`unclosed ${token}`)).toContain('(openlet-file:storage/node)');
});

test('text previews preserve BOM and CRLF on save and reject binary content', async () => {
  const node = {
    id: 'file',
    storage: 'storage',
    parent: 'root',
    name: 'notes.txt',
    kind: 'file' as const,
    mime: 'text/plain',
    size: 0,
    updated: 0,
    blob: new Blob(['\uFEFFhello\r\nworld\r\n']),
  };
  const loaded = await readTextFile(node);
  expect(loaded).toMatchObject({ text: 'hello\nworld\n', bom: true, crlf: true, truncated: false });
  expect(serializeTextFile(loaded.text, loaded)).toBe('\uFEFFhello\r\nworld\r\n');
  await expect(readTextFile({ ...node, blob: new Blob(['a\0b']) })).rejects.toThrow('binary data');
  expect((await readTextFile({ ...node, blob: new Blob(['x'.repeat(1_000_001)]) })).truncated).toBe(
    true,
  );
});

test('message sounds ignore history, reads, duplicate refresh and earlier pagination', () => {
  const old = {
    id: 'old',
    role: 'assistant' as const,
    content: 'old',
    created_at: '2026-11-17T00:00:00Z',
  };
  const next = { ...old, id: 'next', created_at: '2026-11-17T00:01:00Z' };
  expect(newAssistantMessages(undefined, [old])).toEqual([]);
  expect(newAssistantMessages([], [next])).toEqual([next]);
  expect(newAssistantMessages([old], [{ ...old, read_at: next.created_at }])).toEqual([]);
  expect(newAssistantMessages([next], [next, old])).toEqual([]);
  expect(newAssistantMessages([old], [next, old])).toEqual([next]);
  expect(newAssistantMessages([next, old], [next, old])).toEqual([]);
  expect(newAssistantMessages([old], [{ ...next, role: 'user' }, old])).toEqual([]);
});

test('content search sends semantic scope and uses the server result limit', async () => {
  const calls: Record<string, unknown>[] = [];
  const api: Api = async <T>(path: string, init?: RequestInit) => {
    calls.push(JSON.parse(String(init?.body)));
    if (path.endsWith(':semanticSearch')) {
      return {
        hits: [{ fileId: file.id, path: '/nested/report.md', text: 'passage', score: 0.9 }],
      } as T;
    }
    return {
      hits: [{ node: file, snippet: 'relevant content', path: 'nested/report.md', lineNumber: 12 }],
      nextPageToken: 'next',
    } as T;
  };
  const files = storageApi(api, 'workspace');
  files.bind('storage', 'remote-root');
  const page = await files.searchContent('storage', 'relevant', 'text', 'previous');
  expect(page.hits[0]).toMatchObject({
    node: { id: file.id, version: 7 },
    text: 'relevant content',
    path: 'nested/report.md',
    lineNumber: 12,
  });
  expect(page.nextPageToken).toBe('next');
  expect(calls[0]).toEqual({
    root: { nodeId: 'remote-root' },
    query: 'relevant',
    pageSize: 50,
    pageToken: 'previous',
  });
  const semantic = await files.searchContent('storage', 'describe a topic', 'semantic');
  expect(semantic.hits).toEqual([
    { fileId: file.id, path: '/nested/report.md', text: 'passage', score: 0.9 },
  ]);
  expect(calls[1]).toEqual({
    root: { path: '/' },
    query: 'describe a topic',
  });
});

test('interrupted multipart uploads resume server-confirmed parts after recreating the adapter; cancel aborts the transfer', async () => {
  const { crc32c } = await import('@aws-crypto/crc32c');
  const { readUploads } = await import('../src/lib/upload-resume.js');
  const memory = new Map<string, string>();
  const previousStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  const previousXHR = Object.getOwnPropertyDescriptor(globalThis, 'XMLHttpRequest');
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: (key: string) => memory.get(key) ?? null,
      setItem: (key: string, value: string) => memory.set(key, value),
    },
  });
  const sent: string[] = [],
    calls: string[] = [];
  let interrupt = true,
    cancelled = false;
  class XHR {
    upload = { onprogress: (_event: { loaded: number }) => {} };
    status = 200;
    url = '';
    onload = () => {};
    onerror = () => {};
    onabort = () => {};
    onloadend = () => {};
    open(_method: string, url: string) {
      this.url = url;
    }
    setRequestHeader() {}
    getResponseHeader() {
      return 'etag';
    }
    send() {
      sent.push(this.url);
      queueMicrotask(() => {
        if (cancelled) this.abort();
        else if (this.url === 'part-2' && interrupt) this.onerror();
        else this.onload();
        this.onloadend();
      });
    }
    abort() {
      this.onabort();
      this.onloadend();
    }
  }
  Object.defineProperty(globalThis, 'XMLHttpRequest', { configurable: true, value: XHR });
  const original = new File(['abcdefghijkl'], 'source.pdf', {
    type: 'application/pdf',
    lastModified: 100,
  });
  const digest = (bytes: string) => {
    const sum = crc32c(new TextEncoder().encode(bytes));
    return Buffer.from([sum >>> 24, (sum >>> 16) & 255, (sum >>> 8) & 255, sum & 255]).toString(
      'base64',
    );
  };
  const transfer = { id: 'transfer', transfer: { multipart: true, partSizeBytes: '4' } };
  const api: Api = async <T>(path: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? 'GET'} ${path}`);
    if (init?.method === 'DELETE') return {} as T;
    if (path.endsWith('/uploads')) return transfer as T;
    if (path.endsWith('/transfer'))
      return {
        ...transfer,
        completedParts: [{ partNumber: 1, etag: 'etag', checksum: digest('abcd') }],
      } as T;
    if (path.endsWith(':signParts')) {
      const { parts } = JSON.parse(String(init?.body));
      return { parts: [{ url: `part-${parts[0].partNumber}`, headers: {} }] } as T;
    }
    if (path.endsWith(':complete')) {
      expect(
        JSON.parse(String(init?.body)).parts.map((part: { partNumber: number }) => part.partNumber),
      ).toEqual([1, 2, 3]);
      return {
        ...file,
        file: { ...file.file, mediaType: 'application/pdf', type: 'FILE_TYPE_BLOB' },
      } as T;
    }
    throw new Error(path);
  };
  try {
    const first = storageApi(api, 'workspace', null, 'actor');
    await expect(first.upload('storage', 'root', original)).rejects.toThrow(
      'Connection interrupted',
    );
    expect(readUploads('actor')).toHaveLength(1);
    expect(readUploads('different-account')).toEqual([]);
    expect(calls.some((call) => call.startsWith('DELETE'))).toBe(false);
    interrupt = false;
    const resumed = storageApi(api, 'workspace', null, 'actor');
    await resumed.upload('storage', 'root', original);
    expect(sent).toEqual(['part-1', 'part-2', 'part-2', 'part-3']);
    expect(calls.filter((call) => call.endsWith('/uploads'))).toHaveLength(1);
    expect(readUploads('actor')).toEqual([]);
    const controller = new AbortController();
    cancelled = true;
    const running = resumed.upload(
      'storage',
      'root',
      original,
      original.name,
      () => controller.abort(),
      undefined,
      { signal: controller.signal },
    );
    // The XHR abort below exercises cleanup while bytes are in flight.
    const abortXHR = XHR.prototype.send;
    XHR.prototype.send = function () {
      controller.abort();
      abortXHR.call(this);
    };
    await expect(running).rejects.toThrow();
    expect(calls.some((call) => call.startsWith('DELETE') && call.endsWith('/transfer'))).toBe(
      true,
    );
    expect(readUploads('actor')).toEqual([]);
  } finally {
    if (previousStorage) Object.defineProperty(globalThis, 'localStorage', previousStorage);
    else Reflect.deleteProperty(globalThis, 'localStorage');
    if (previousXHR) Object.defineProperty(globalThis, 'XMLHttpRequest', previousXHR);
    else Reflect.deleteProperty(globalThis, 'XMLHttpRequest');
  }
});

test('archive downloads stream to disk, abort partial writes and delegate native downloads without buffering', async () => {
  const { downloadArchive } = await import('../src/lib/archive-download.js');
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, 'window');
  const originalDocument = Object.getOwnPropertyDescriptor(globalThis, 'document');
  const chunks: number[] = [];
  let aborted = false,
    clicked = '',
    requests = 0;
  const node = {
    id: 'folder',
    storage: 'storage',
    parent: 'root',
    name: 'Folder',
    kind: 'folder' as const,
    mime: '',
    size: 0,
    updated: 0,
  };
  const controller = new AbortController();
  const picker = async () => ({
    createWritable: async () =>
      new WritableStream<Uint8Array>({
        write(chunk) {
          chunks.push(chunk.byteLength);
        },
        abort() {
          aborted = true;
        },
      }),
  });
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: { showSaveFilePicker: picker },
  });
  const request = async () => {
    requests++;
    return new Response(
      new ReadableStream<Uint8Array>({
        start(stream) {
          stream.enqueue(new Uint8Array(4));
          stream.enqueue(new Uint8Array(8));
          stream.close();
        },
      }),
    );
  };
  const options = {
    api: (async () => ({ ticket: 'one-use-ticket' })) as Api,
    request,
    url: (path: string) => `https://api.example.com${path}`,
    workspace: 'workspace',
    nodes: [node],
    signal: controller.signal,
    onBytes: (_bytes: number) => {},
  };
  try {
    expect(await downloadArchive(options)).toBe('saved');
    expect(chunks).toEqual([4, 8]);
    expect(aborted).toBe(false);
    await expect(
      downloadArchive({ ...options, onBytes: () => controller.abort() }),
    ).rejects.toThrow();
    expect(aborted).toBe(true);
    Object.defineProperty(globalThis, 'window', { configurable: true, value: {} });
    Object.defineProperty(globalThis, 'document', {
      configurable: true,
      value: {
        createElement: () => ({
          href: '',
          click() {
            clicked = this.href;
          },
        }),
      },
    });
    const before = requests;
    expect(await downloadArchive({ ...options, signal: new AbortController().signal })).toBe(
      'browser',
    );
    expect(requests).toBe(before);
    expect(clicked).toBe('https://api.example.com/v1/archive-downloads/one-use-ticket');
  } finally {
    if (originalWindow) Object.defineProperty(globalThis, 'window', originalWindow);
    else Reflect.deleteProperty(globalThis, 'window');
    if (originalDocument) Object.defineProperty(globalThis, 'document', originalDocument);
    else Reflect.deleteProperty(globalThis, 'document');
  }
});

test('cancelling a resumed upload during hashing removes the session; navigation preserves it', async () => {
  const { readUploads, rememberUpload } = await import('../src/lib/upload-resume.js');
  const memory = new Map<string, string>();
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: (key: string) => memory.get(key) ?? null,
      setItem: (key: string, value: string) => memory.set(key, value),
    },
  });
  try {
    for (const reason of ['pause', undefined]) {
      const controller = new AbortController();
      const saved = {
        workspace: 'workspace',
        storage: 'storage',
        parent: 'root',
        name: 'source.pdf',
        fileName: 'source.pdf',
        size: 3,
        modified: 100,
        checksum: 'digest',
        requestId: 'request',
        uploadId: 'transfer',
        created: Date.now(),
      };
      rememberUpload('actor', saved);
      const source = new File(['pdf'], 'source.pdf', { lastModified: 100 });
      source.slice = () =>
        ({
          arrayBuffer: async () => {
            controller.abort(reason);
            return new TextEncoder().encode('pdf').buffer;
          },
        }) as Blob;
      const deleted: string[] = [];
      const api: Api = async <T>(path: string, init?: RequestInit) => {
        expect(init?.method).toBe('DELETE');
        deleted.push(path);
        return {} as T;
      };
      await expect(
        storageApi(api, 'workspace', null, 'actor').resumeUpload(
          saved,
          source,
          () => {},
          controller.signal,
        ),
      ).rejects.toBeDefined();
      expect(deleted.length).toBe(reason === 'pause' ? 0 : 1);
      expect(readUploads('actor').length).toBe(reason === 'pause' ? 1 : 0);
    }
  } finally {
    if (previous) Object.defineProperty(globalThis, 'localStorage', previous);
    else Reflect.deleteProperty(globalThis, 'localStorage');
  }
});

test('durable drafts isolate accounts and logout clears only the current account', async () => {
  const { draftKey, readDraft, writeDraft, accountDraftKeys, clearAccountDrafts } =
    await import('../src/lib/chat-drafts.js');
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  const memory: Record<string, string> = {};
  Object.defineProperties(memory, {
    getItem: { value: (key: string) => memory[key] ?? null },
    setItem: {
      value: (key: string, value: string) => {
        memory[key] = value;
      },
    },
    removeItem: {
      value: (key: string) => {
        delete memory[key];
      },
    },
  });
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: memory });
  try {
    const own = draftKey('one', 'workspace', 'agent');
    const other = draftKey('two', 'workspace', 'agent');
    writeDraft(own, {
      text: 'unsent',
      reply: { id: 'reply', role: 'assistant', content: 'reference' },
    });
    writeDraft(other, { text: 'private to another account' });
    expect(readDraft(own)).toMatchObject({ text: 'unsent', reply: { id: 'reply' } });
    expect(accountDraftKeys('one')).toEqual([own]);
    clearAccountDrafts('one');
    expect(readDraft(own)).toEqual({ text: '', reply: null });
    expect(readDraft(other).text).toBe('private to another account');
    writeDraft(other, { text: '', reply: null });
    expect(accountDraftKeys('two')).toEqual([]);
  } finally {
    if (previous) Object.defineProperty(globalThis, 'localStorage', previous);
    else Reflect.deleteProperty(globalThis, 'localStorage');
  }
});

test('file tab paths resolve ancestors and reject cyclic parents', async () => {
  let cycle = false;
  const api: Api = async <T>(path: string) => {
    if (path.endsWith('/report.md')) return file as T;
    if (path.endsWith('/nested')) return directory('nested', cycle ? 'nested' : 'remote-root') as T;
    throw new Error('Unexpected path lookup');
  };
  const files = storageApi(api, 'workspace');
  files.bind('storage', 'remote-root');
  const current = await files.stat('storage', 'report.md');
  expect(await files.path(current)).toBe('/nested/report.md');
  cycle = true;
  await expect(files.path(current)).rejects.toThrow('Could not resolve the file path.');
});
