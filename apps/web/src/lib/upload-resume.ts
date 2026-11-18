import type { StorageNode } from './storage-preview.js';

export type UploadResume = {
  requestId: string;
  uploadId?: string;
  workspace: string;
  storage: string;
  parent: string;
  name: string;
  fileName: string;
  size: number;
  modified: number;
  checksum: string;
  created: number;
  replace?: Pick<
    StorageNode,
    | 'id'
    | 'version'
    | 'name'
    | 'fileType'
    | 'mime'
    | 'kind'
    | 'storage'
    | 'parent'
    | 'size'
    | 'updated'
  >;
};

const prefix = 'openlet-upload-resume:';
export function readUploads(actor: string): UploadResume[] {
  if (!actor) return [];
  try {
    const value: unknown = JSON.parse(localStorage.getItem(prefix + actor) ?? '[]');
    if (!Array.isArray(value)) return [];
    return value.filter(
      (item): item is UploadResume =>
        item &&
        typeof item.requestId === 'string' &&
        typeof item.workspace === 'string' &&
        typeof item.storage === 'string' &&
        typeof item.parent === 'string' &&
        typeof item.name === 'string' &&
        typeof item.fileName === 'string' &&
        typeof item.checksum === 'string' &&
        Number.isSafeInteger(item.size) &&
        item.size >= 0 &&
        Number.isFinite(item.modified) &&
        item.created > Date.now() - 7 * 86_400_000,
    );
  } catch {
    return [];
  }
}

export function rememberUpload(actor: string, upload: UploadResume) {
  if (!actor) return;
  localStorage.setItem(
    prefix + actor,
    JSON.stringify([
      ...readUploads(actor).filter((item) => item.requestId !== upload.requestId),
      upload,
    ]),
  );
}

export function forgetUpload(actor: string, requestId: string) {
  if (!actor) return;
  try {
    localStorage.setItem(
      prefix + actor,
      JSON.stringify(readUploads(actor).filter((item) => item.requestId !== requestId)),
    );
  } catch {
    /* The server still expires abandoned transfers. */
  }
}

export function clearUploads(actor: string) {
  try {
    localStorage.removeItem(prefix + actor);
  } catch {
    /* Storage may be disabled. */
  }
}
