import { useState } from 'react';
import { Search, Trash2 } from 'lucide-react';
import { Separator } from '@/components/ui/separator';
import { StorageRootIcon } from './storage-root-icon';
import { Button } from '@/components/ui/button';
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group';
import { useStorageBrowser, rootId, type StorageRoot } from './storage-context';
import { useStorageDrop } from './storage-drag';

function StorageRow({ root, onNavigate }: { root: StorageRoot; onNavigate: () => void }) {
  const b = useStorageBrowser();
  const drop = useStorageDrop(root.id, rootId(root.id));
  return (
    <button
      {...drop}
      className="storage-root-row flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-sm hover:bg-sidebar-accent aria-[current=page]:bg-sidebar-accent [&>svg]:size-5 [&>svg]:shrink-0 [&>svg]:stroke-[1.5] [&>svg]:text-muted-foreground data-drop:bg-accent data-drop:outline-2 data-drop:-outline-offset-2 data-drop:outline-ring"
      aria-current={b.storage.id === root.id && !b.trash ? 'page' : undefined}
      onClick={() => {
        b.go(root.id);
        onNavigate();
      }}
    >
      <StorageRootIcon root={root} />
      <span className="truncate">{root.name}</span>
    </button>
  );
}
export function StorageSidebar({ onNavigate }: { onNavigate: () => void }) {
  const b = useStorageBrowser();
  const [filter, setFilter] = useState('');
  const roots = b.roots.filter((root) => root.name.toLowerCase().includes(filter.toLowerCase()));
  return (
    <div className="flex h-full min-h-0 flex-col bg-sidebar">
      <div className="px-3 pt-2 pb-2">
        <InputGroup>
          <InputGroupAddon>
            <Search />
          </InputGroupAddon>
          <InputGroupInput
            aria-label="Search storages"
            placeholder="Search storages…"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          />
        </InputGroup>
      </div>
      <nav aria-label="Storages" className="min-h-0 flex-1 overflow-auto px-3 pb-3">
        <div className="flex flex-col gap-1">
          {roots
            .filter((root) => !root.agent)
            .map((root) => (
              <StorageRow key={root.id} root={root} onNavigate={onNavigate} />
            ))}
        </div>
        <Separator decorative={false} aria-label="Storage groups" className="my-3" />
        <div className="flex flex-col gap-1">
          {roots
            .filter((root) => root.agent)
            .map((root) => (
              <StorageRow key={root.id} root={root} onNavigate={onNavigate} />
            ))}
        </div>
        {!roots.length && (
          <p className="p-3 text-sm text-muted-foreground">No matching storages.</p>
        )}
      </nav>
      <div className="border-t px-3 py-2">
        <Button
          variant={b.trash ? 'secondary' : 'ghost'}
          className="w-full justify-start font-normal"
          onClick={() => {
            b.go(b.storage.id, 'trash');
            onNavigate();
          }}
        >
          <Trash2 />
          Trash
          <span className="ml-auto text-xs text-muted-foreground">
            {b.snapshot.nodes.filter((node) => node.storage === b.storage.id && node.trashed)
              .length || ''}
          </span>
        </Button>
      </div>
    </div>
  );
}
