import { useEffect, useState } from 'react';
import { ChevronLeft, ChevronRight, Folder, HardDrive } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { formatBytes } from '@/lib/storage-preview';
import { useStorageBrowser, ancestors, rootId, type TransferRequest } from './storage-context';

export function StorageDialogs() {
  const b = useStorageBrowser();
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [destination, setDestination] = useState({ storage: b.storage.id, parent: b.parent });
  useEffect(() => {
    setName(b.nameRequest?.kind === 'rename' ? b.nameRequest.node.name : '');
    setError('');
  }, [b.nameRequest]);
  useEffect(() => {
    if (b.transfer) setDestination({ storage: b.transfer.storage, parent: b.transfer.parent });
  }, [b.transfer]);
  const transfer = b.transfer;
  const crossStorage = transfer?.ids.some(
    (id) => b.snapshot.nodes.find((node) => node.id === id)?.storage !== destination.storage,
  );
  const destinationNode = b.snapshot.nodes.find((node) => node.id === destination.parent);
  const invalid = (id: string) =>
    !!transfer?.ids.some(
      (source) =>
        source === id || ancestors(b.snapshot.nodes, id).some((node) => node.id === source),
    );
  async function submitName(event: React.FormEvent) {
    event.preventDefault();
    setError('');
    try {
      await b.saveName(name);
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Could not save.');
    }
  }
  function choose(root: string, folder = rootId(root)) {
    setDestination({ storage: root, parent: folder });
  }
  function confirmTransfer() {
    if (transfer) void b.move({ ...transfer, ...destination } as TransferRequest);
  }
  return (
    <>
      <Dialog open={!!b.nameRequest} onOpenChange={(open) => !open && b.setNameRequest(null)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>{b.nameRequest?.kind === 'rename' ? 'Rename' : 'New folder'}</DialogTitle>
            <DialogDescription>
              {b.nameRequest?.kind === 'rename'
                ? 'Choose a name for this item.'
                : 'Create a folder in this location.'}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={submitName} className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="storage-name">Name</Label>
              <Input
                id="storage-name"
                autoFocus
                value={name}
                onChange={(event) => setName(event.target.value)}
                aria-invalid={!!error}
              />
              {error && (
                <p role="alert" className="text-sm text-destructive">
                  {error}
                </p>
              )}
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => b.setNameRequest(null)}>
                Cancel
              </Button>
              <Button type="submit" disabled={!!b.pending || !name.trim()}>
                {b.pending ? 'Saving…' : 'Save'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <Dialog open={!!transfer} onOpenChange={(open) => !open && b.setTransfer(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {transfer?.copy ? 'Copy' : 'Move'} {transfer?.ids.length} item
              {transfer?.ids.length === 1 ? '' : 's'}
            </DialogTitle>
            <DialogDescription>
              {crossStorage
                ? 'Moving between storages changes who can access these files. The destination storage’s permissions will apply.'
                : 'Choose a destination folder.'}
            </DialogDescription>
          </DialogHeader>
          <div className="flex gap-1 overflow-x-auto pb-1">
            {b.roots.map((root) => (
              <Button
                key={root.id}
                size="sm"
                variant={destination.storage === root.id ? 'secondary' : 'ghost'}
                disabled={!root.write}
                onClick={() => choose(root.id)}
              >
                {root.name}
              </Button>
            ))}
          </div>
          <div className="rounded-lg border">
            <div className="flex items-center gap-2 border-b p-2">
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Parent folder"
                disabled={!destinationNode}
                onClick={() => choose(destination.storage, destinationNode?.parent)}
              >
                <ChevronLeft />
              </Button>
              <HardDrive className="size-4 text-muted-foreground" />
              <span className="truncate text-sm">
                {destinationNode?.name ??
                  b.roots.find((root) => root.id === destination.storage)?.name}
              </span>
            </div>
            <div className="h-52 overflow-auto p-1">
              {b.snapshot.nodes
                .filter(
                  (node) =>
                    node.parent === destination.parent && node.kind === 'folder' && !node.trashed,
                )
                .map((node) => (
                  <Button
                    key={node.id}
                    variant="ghost"
                    className="w-full justify-start font-normal"
                    disabled={invalid(node.id)}
                    onClick={() => choose(node.storage, node.id)}
                  >
                    <Folder />
                    {node.name}
                    <ChevronRight className="ml-auto" />
                  </Button>
                ))}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => b.setTransfer(null)}>
              Cancel
            </Button>
            <Button disabled={!!b.pending || invalid(destination.parent)} onClick={confirmTransfer}>
              {b.pending ? 'Working…' : transfer?.copy ? 'Copy here' : 'Move here'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={!!b.conflict} onOpenChange={(open) => !open && b.setConflict(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>An item with this name already exists</DialogTitle>
            <DialogDescription className="break-words">
              {b.conflict?.names.join(', ')}. Keep both adds a number to the new name. Replace moves
              the existing item to Trash.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => b.setConflict(null)}>
              Cancel
            </Button>
            <Button
              variant="secondary"
              disabled={!!b.pending}
              onClick={() => void b.conflict?.retry('keep')}
            >
              Keep both
            </Button>
            <Button disabled={!!b.pending} onClick={() => void b.conflict?.retry('replace')}>
              Replace
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={!!b.deleteIds.length} onOpenChange={(open) => !open && b.setDeleteIds([])}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Move to Trash?</DialogTitle>
            <DialogDescription>
              {b.deleteIds.length} item{b.deleteIds.length === 1 ? '' : 's'} and any files inside
              will move to Trash. You can restore them later.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => b.setDeleteIds([])}>
              Cancel
            </Button>
            <Button variant="destructive" disabled={!!b.pending} onClick={() => void b.remove()}>
              Move to Trash
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={!!b.details} onOpenChange={(open) => !open && b.setDetails(null)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle className="break-all">{b.details?.name}</DialogTitle>
            <DialogDescription>File details</DialogDescription>
          </DialogHeader>
          {b.details && (
            <dl className="storage-details grid grid-cols-[80px_minmax(0,1fr)] gap-3 text-caption [&>dt]:text-muted-foreground [&>dd]:wrap-anywhere">
              <dt>Type</dt>
              <dd>{b.details.kind === 'folder' ? 'Folder' : b.details.mime || 'File'}</dd>
              <dt>Size</dt>
              <dd>{b.details.kind === 'folder' ? '—' : formatBytes(b.details.size)}</dd>
              <dt>Storage</dt>
              <dd>{b.roots.find((root) => root.id === b.details?.storage)?.name}</dd>
              <dt>Location</dt>
              <dd>
                {ancestors(b.snapshot.nodes, b.details.id)
                  .slice(0, -1)
                  .map((node) => node.name)
                  .join(' / ') || '/'}
              </dd>
              <dt>Modified</dt>
              <dd>{new Date(b.details.updated).toLocaleString()}</dd>
            </dl>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
