import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAgentPreview } from './agent-preview';
import { loadStorage, storageRoots, rootId, type StorageNode } from '@/lib/storage-preview';
import { StorageProvider } from '@/components/storage/storage-context';
import { StoragePage } from '@/components/storage/storage-page';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from '@/components/ui/select';

export function useFileChoices(enabled: boolean, search = '') {
  const p = useAgentPreview();
  const roots = useQuery({
    queryKey: ['storage-roots', p.actorId, p.workspace.id],
    enabled,
    queryFn: () =>
      p.filesApi ? p.filesApi.listRoots() : Promise.resolve(storageRoots(p.workspace)),
  });
  const [storage, setStorage] = useState('');
  const current = storage || roots.data?.[0]?.id || '';
  const [filter, setFilter] = useState(search);
  useEffect(() => {
    const timer = setTimeout(() => setFilter(search), 150);
    return () => clearTimeout(timer);
  }, [search]);
  const query = useQuery({
    queryKey: ['file-choices', p.actorId, p.workspace.id, current, filter],
    enabled: enabled && !!current,
    queryFn: async () => {
      if (!p.filesApi) {
        const snapshot = await loadStorage(p.workspace.id, storageRoots(p.workspace));
        return snapshot.nodes.filter(
          (n) =>
            !n.trashed &&
            n.kind === 'file' &&
            (filter
              ? n.name.toLowerCase().includes(filter.toLowerCase())
              : n.storage === current && n.parent === rootId(current)),
        );
      }
      if (!filter) return p.filesApi.list(current, rootId(current));
      // shortcut: show the first 100 matches per storage; use the file browser for larger result sets.
      return (
        await Promise.all((roots.data ?? []).map((root) => p.filesApi!.search(root.id, filter)))
      ).flat();
    },
  });
  return { roots, current, setStorage, query, nodes: query.data ?? [] };
}
export function FilePicker({
  open,
  onClose,
  onSelect,
}: {
  open: boolean;
  onClose: () => void;
  onSelect: (node: StorageNode) => void;
}) {
  const files = useFileChoices(open);
  const p = useAgentPreview();
  const root = files.roots.data?.find((item) => item.id === files.current);
  return (
    <Dialog open={open} onOpenChange={(value) => !value && onClose()}>
      <DialogContent className="flex h-[min(640px,85dvh)] max-w-3xl! flex-col gap-3">
        <DialogHeader>
          <DialogTitle>Choose a file</DialogTitle>
        </DialogHeader>
        <Select value={files.current} onValueChange={files.setStorage}>
          <SelectTrigger aria-label="Storage">
            <SelectValue placeholder="Storage" />
          </SelectTrigger>
          <SelectContent>
            {files.roots.data?.map((root) => (
              <SelectItem key={root.id} value={root.id}>
                {root.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="min-h-0 flex-1 overflow-hidden rounded-lg border">
          {files.roots.error ? (
            <p role="alert" className="p-4 text-sm text-destructive">
              {files.roots.error.message}
            </p>
          ) : root ? (
            <StorageProvider
              key={root.id}
              workspace={p.workspace}
              root={root}
              onOpenFile={onSelect}
            >
              <StoragePage embedded />
            </StorageProvider>
          ) : (
            <p role="status" className="p-4 text-sm text-muted-foreground">
              Loading files…
            </p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
