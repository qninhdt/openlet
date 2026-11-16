import { type DragEvent } from 'react';
import { useStorageBrowser, type UploadFile } from './storage-context';

const mime = 'application/x-openlet-nodes';
// Read entries before awaiting: browsers clear DataTransfer after the drop handler returns.
export async function droppedFiles(data: DataTransfer): Promise<UploadFile[]> {
  async function walk(entry: FileSystemEntry, prefix = ''): Promise<UploadFile[]> {
    if (entry.isFile) {
      const file = await new Promise<File>((resolve, reject) =>
        (entry as FileSystemFileEntry).file(resolve, reject),
      );
      return [{ file, path: prefix + file.name }];
    }
    const reader = (entry as FileSystemDirectoryEntry).createReader();
    const children: FileSystemEntry[] = [];
    for (;;) {
      const batch = await new Promise<FileSystemEntry[]>((resolve, reject) =>
        reader.readEntries(resolve, reject),
      );
      if (!batch.length) break;
      children.push(...batch);
    }
    return (
      await Promise.all(children.map((child) => walk(child, prefix + entry.name + '/')))
    ).flat();
  }
  const entries = Array.from(data.items)
    .map((item) => item.webkitGetAsEntry?.())
    .filter((entry): entry is FileSystemEntry => !!entry);
  const files = Array.from(data.files);
  return entries.length
    ? (await Promise.all(entries.map((entry) => walk(entry)))).flat()
    : files.map((file) => ({ file, path: file.name }));
}
export function useStorageDrop(storage: string, parent: string) {
  const b = useStorageBrowser();
  return {
    'data-drop': b.dropTarget === parent || undefined,
    onDragOver(event: DragEvent) {
      if (
        !b.roots.find((root) => root.id === storage)?.write ||
        !event.dataTransfer.types.some((type) => type === mime || type === 'Files')
      )
        return;
      event.preventDefault();
      event.stopPropagation();
      event.dataTransfer.dropEffect = 'move';
      b.setDropTarget(parent);
    },
    onDragLeave(event: DragEvent) {
      if (!event.currentTarget.contains(event.relatedTarget as Node)) {
        b.setDropTarget('');
      }
    },
    onDrop(event: DragEvent) {
      if (!event.dataTransfer.types.some((type) => type === mime || type === 'Files')) return;
      event.preventDefault();
      event.stopPropagation();
      b.setDropTarget('');
      const payload = event.dataTransfer.getData(mime);
      if (payload) {
        try {
          const ids: unknown = JSON.parse(payload);
          if (Array.isArray(ids) && ids.every((id) => typeof id === 'string'))
            b.drop(ids, storage, parent);
        } catch {
          b.report(new Error('This item could not be dropped.'));
        }
      } else
        void droppedFiles(event.dataTransfer)
          .then((files) => b.upload(files, storage, parent))
          .catch(b.report);
    },
  };
}
export const storageDragMime = mime;
