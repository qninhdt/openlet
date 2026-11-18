import type { Api } from './agent-api.js';
import type { StorageNode } from './storage-preview.js';

type SavePicker = (options: {
  suggestedName: string;
  types: { description: string; accept: Record<string, string[]> }[];
}) => Promise<{ createWritable: () => Promise<WritableStream<Uint8Array>> }>;

export async function downloadArchive({
  api,
  request,
  url,
  workspace,
  nodes,
  signal,
  onBytes,
}: {
  api: Api;
  request: (path: string, init?: RequestInit) => Promise<Response>;
  url: (path: string) => string;
  workspace: string;
  nodes: StorageNode[];
  signal: AbortSignal;
  onBytes: (bytes: number) => void;
}) {
  if (
    !nodes.length ||
    nodes.length > 100 ||
    nodes.some((node) => node.storage !== nodes[0].storage)
  )
    throw new Error('Select up to 100 items from the same storage to download an archive.');
  const path = `/v1/workspaces/${workspace}/storages/${nodes[0].storage}/nodes`;
  const body = JSON.stringify({ targets: nodes.map((node) => ({ nodeId: node.id })) });
  const picker = (window as Window & { showSaveFilePicker?: SavePicker }).showSaveFilePicker;
  if (!picker) {
    signal.throwIfAborted();
    const result = await api<{ ticket: string }>(path + ':archiveDownload', {
      method: 'POST',
      body,
      signal,
    });
    signal.throwIfAborted();
    const link = document.createElement('a');
    link.href = url(`/v1/archive-downloads/${encodeURIComponent(result.ticket)}`);
    link.download = 'Openlet files.zip';
    link.rel = 'noreferrer';
    link.referrerPolicy = 'no-referrer';
    link.click();
    return 'browser' as const;
  }
  // The picker must run in the original click gesture, before requesting the archive.
  const handle = await picker.call(window, {
    suggestedName: 'Openlet files.zip',
    types: [{ description: 'ZIP archive', accept: { 'application/zip': ['.zip'] } }],
  });
  signal.throwIfAborted();
  const output = await handle.createWritable();
  try {
    const response = await request(path + ':downloadArchive', { method: 'POST', body, signal });
    if (!response.ok || !response.body)
      throw new Error('Could not start the archive download. Try again.');
    let bytes = 0;
    const progress = new TransformStream<Uint8Array, Uint8Array>({
      transform(chunk, controller) {
        bytes += chunk.byteLength;
        onBytes(bytes);
        controller.enqueue(chunk);
      },
    });
    await response.body.pipeThrough(progress).pipeTo(output, { signal });
    return 'saved' as const;
  } catch (error) {
    await output.abort(error).catch(() => {});
    throw error;
  }
}
