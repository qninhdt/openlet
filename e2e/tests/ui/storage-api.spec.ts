import { expect, test } from '@playwright/test';
import { storageApi } from '../../../apps/web/src/lib/storage-api.js';
import type { Api } from '../../../apps/web/src/lib/agent-api.js';
import { fileReferences, fileToken, fileText } from '../../../apps/web/src/lib/file-refs.js';

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
  file: { mediaType: 'text/markdown', sizeBytes: '4', version: '7' },
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
  expect(await files.listRoots()).toEqual([
    { id: 'storage', name: 'Team', root: 'remote-root', write: true },
  ]);
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
  const api: Api = async <T>(path: string, init?: RequestInit): Promise<T> => {
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
