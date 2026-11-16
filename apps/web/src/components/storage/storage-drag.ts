import { useEffect, useRef, type DragEvent, type PointerEvent } from 'react';
import { useStorageBrowser, type UploadFile } from './storage-context';

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
    'data-storage-drop': parent,
    'data-storage-id': storage,
    onDragOver(event: DragEvent) {
      if (
        !b.roots.find((root) => root.id === storage)?.write ||
        !event.dataTransfer.types.includes('Files')
      )
        return;
      event.preventDefault();
      event.stopPropagation();
      event.dataTransfer.dropEffect = 'copy';
      b.setDropTarget(parent);
    },
    onDragLeave(event: DragEvent) {
      if (!event.currentTarget.contains(event.relatedTarget as Node)) {
        b.setDropTarget('');
      }
    },
    onDrop(event: DragEvent) {
      if (!event.dataTransfer.types.includes('Files')) return;
      event.preventDefault();
      event.stopPropagation();
      b.setDropTarget('');
      void droppedFiles(event.dataTransfer)
        .then((files) => b.upload(files, storage, parent))
        .catch(b.report);
    },
  };
}
function swallowNextClick() {
  const swallow = (event: MouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
  };
  window.addEventListener('click', swallow, { capture: true, once: true });
  setTimeout(() => window.removeEventListener('click', swallow, true), 0);
}

// Adapted from OpenBot 5c1cae0, library-folder-drag.ts (pointer threshold, hit testing, cancellation).
// PolyForm Noncommercial 1.0.0: https://polyformproject.org/licenses/noncommercial/1.0.0/
// Required Notice: Copyright 2026 Synthetify Labs spółka z ograniczoną odpowiedzialnością.
// Required Notice: For a commercial license, contact licenses@openbot.run.
export function useStoragePointerDrag() {
  const b = useStorageBrowser();
  const cleanup = useRef<() => void>(() => {});
  useEffect(() => () => cleanup.current(), []);
  return (event: PointerEvent<HTMLElement>) => {
    if (b.trash || event.button !== 0 || event.pointerType === 'touch') return;
    const element = event.target as HTMLElement;
    const source = element.closest<HTMLElement>('[data-node]');
    if (!source || element.closest('button:not(.storage-item-open),input,[role=menu]')) return;
    const ids = b.selected.has(source.dataset.node!) ? [...b.selected] : [source.dataset.node!];
    const nodes = b.snapshot.nodes.filter((node) => ids.includes(node.id));
    if (!nodes.length) return;
    cleanup.current();
    const origin = { x: event.clientX, y: event.clientY };
    let ghost: HTMLDivElement | undefined;
    let target: HTMLElement | null = null;
    function targetAt(x: number, y: number) {
      const at = document.elementFromPoint(x, y);
      const composer = at?.closest<HTMLElement>('[data-slot=conversation-composer]');
      if (composer && b.attachFiles && nodes.some((node) => node.kind === 'file')) return composer;
      const folder = at?.closest<HTMLElement>('[data-storage-drop]');
      if (!folder || !b.roots.some((root) => root.id === folder.dataset.storageId && root.write))
        return null;
      if (ids.includes(folder.dataset.storageDrop!)) return null;
      return folder;
    }
    function move(e: globalThis.PointerEvent) {
      if (!ghost) {
        if (Math.hypot(e.clientX - origin.x, e.clientY - origin.y) < 6) return;
        ghost = document.createElement('div');
        ghost.className =
          'pointer-events-none fixed left-0 top-0 z-[100] max-w-64 truncate rounded-md border bg-popover px-3.5 py-2 text-sm text-popover-foreground shadow-md';
        ghost.textContent = nodes.length === 1 ? nodes[0].name : `${nodes.length} items`;
        ghost.setAttribute('aria-hidden', 'true');
        document.body.append(ghost);
        for (const id of ids)
          document
            .querySelector<HTMLElement>(`[data-node="${CSS.escape(id)}"]`)
            ?.setAttribute('data-dragging', '');
      }
      e.preventDefault();
      ghost.style.transform = `translate(${e.clientX + 12}px, ${e.clientY + 14}px)`;
      const next = targetAt(e.clientX, e.clientY);
      if (target !== next) {
        target?.removeAttribute('data-drop');
        target = next;
        target?.setAttribute('data-drop', 'true');
      }
    }
    function end() {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', drop);
      window.removeEventListener('pointercancel', end);
      window.removeEventListener('blur', end);
      window.removeEventListener('keydown', key, true);
      target?.removeAttribute('data-drop');
      for (const id of ids)
        document
          .querySelector<HTMLElement>(`[data-node="${CSS.escape(id)}"]`)
          ?.removeAttribute('data-dragging');
      ghost?.remove();
    }
    function drop(e: globalThis.PointerEvent) {
      const dragging = !!ghost;
      const destination = targetAt(e.clientX, e.clientY);
      end();
      if (!dragging) return;
      swallowNextClick();
      if (!destination) return;
      if (destination.dataset.slot === 'conversation-composer')
        b.attachFiles?.(nodes.filter((node) => node.kind === 'file'));
      else b.drop(ids, destination.dataset.storageId!, destination.dataset.storageDrop!);
    }
    function key(e: KeyboardEvent) {
      if (e.key !== 'Escape') return;
      e.preventDefault();
      e.stopPropagation();
      end();
      window.addEventListener('pointerup', swallowNextClick, { once: true });
    }
    window.addEventListener('pointermove', move, { passive: false });
    window.addEventListener('pointerup', drop);
    window.addEventListener('pointercancel', end);
    window.addEventListener('blur', end);
    window.addEventListener('keydown', key, true);
    cleanup.current = end;
  };
}
