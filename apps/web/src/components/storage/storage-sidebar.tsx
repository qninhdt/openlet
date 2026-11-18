import { useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, Files, MessageSquare, Search, Trash2 } from 'lucide-react';
import { Separator } from '@/components/ui/separator';
import { StorageRootIcon } from './storage-root-icon';
import { AgentAvatar } from '@/components/agent-avatar';
import { Button } from '@/components/ui/button';
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group';
import { useStorageBrowser, rootId, type StorageRoot } from './storage-context';
import { useStorageDrop } from './storage-drag';
import { cn } from '@/lib/utils';

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

function AgentStorageRow({
  agent,
  personalRoot,
  conversationRoot,
  onNavigate,
}: {
  agent: { id?: string; name: string; role?: string };
  personalRoot?: StorageRoot;
  conversationRoot?: StorageRoot;
  onNavigate: () => void;
}) {
  const b = useStorageBrowser();
  const isPersonalActive = !!personalRoot && b.storage.id === personalRoot.id && !b.trash;
  const isConvActive = !!conversationRoot && b.storage.id === conversationRoot.id && !b.trash;
  const isAnyActive = isPersonalActive || isConvActive;

  const [open, setOpen] = useState(isAnyActive);
  const [ensuring, setEnsuring] = useState(false);

  useEffect(() => {
    if (isAnyActive) {
      setOpen(true);
    }
  }, [isAnyActive]);

  const dropPersonal = useStorageDrop(
    personalRoot?.id ?? '',
    personalRoot ? rootId(personalRoot.id) : '',
  );
  const dropConv = useStorageDrop(
    conversationRoot?.id ?? '',
    conversationRoot ? rootId(conversationRoot.id) : '',
  );

  const handleSelectPersonal = () => {
    if (personalRoot) {
      b.go(personalRoot.id);
      onNavigate();
    }
  };

  const handleSelectConversation = async () => {
    if (conversationRoot) {
      b.go(conversationRoot.id);
      onNavigate();
      return;
    }
    if (agent.id && b.ensureConversationStorage) {
      try {
        setEnsuring(true);
        const conv = await b.ensureConversationStorage(agent.id);
        b.go(conv.id);
        onNavigate();
      } finally {
        setEnsuring(false);
      }
    }
  };

  return (
    <div className="flex flex-col">
      <button
        type="button"
        className={cn(
          'storage-agent-row flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-sm hover:bg-sidebar-accent transition-colors',
          isAnyActive && 'font-medium text-foreground',
        )}
        onClick={() => setOpen((prev) => !prev)}
      >
        <span className="grid size-5 shrink-0 place-items-center">
          <AgentAvatar name={agent.name} className="size-5 shrink-0" />
        </span>
        <span className="flex-1 truncate">{agent.name}</span>
        <span className="p-0.5 text-muted-foreground">
          {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        </span>
      </button>

      {open && (
        <div className="ml-4 flex flex-col gap-0.5 border-l border-sidebar-border/70 pl-2 pt-0.5 pb-1">
          {/* Sub-item 1: Files (Personal của agent) */}
          <button
            type="button"
            {...(personalRoot ? dropPersonal : {})}
            aria-current={isPersonalActive ? 'page' : undefined}
            onClick={handleSelectPersonal}
            className={cn(
              'storage-root-row flex h-7 w-full items-center gap-2 rounded-md px-2 text-left text-xs hover:bg-sidebar-accent transition-colors',
              isPersonalActive
                ? 'bg-sidebar-accent font-medium text-sidebar-accent-foreground'
                : 'text-muted-foreground hover:text-foreground',
              'data-drop:bg-accent data-drop:outline-2 data-drop:-outline-offset-2 data-drop:outline-ring',
            )}
          >
            <Files className="size-3.5 shrink-0" />
            <span className="truncate">Files</span>
          </button>

          {/* Sub-item 2: Conversation (giữa User và Agent) */}
          <button
            type="button"
            {...(conversationRoot ? dropConv : {})}
            aria-current={isConvActive ? 'page' : undefined}
            onClick={() => void handleSelectConversation()}
            disabled={ensuring}
            className={cn(
              'storage-root-row flex h-7 w-full items-center gap-2 rounded-md px-2 text-left text-xs hover:bg-sidebar-accent transition-colors',
              isConvActive
                ? 'bg-sidebar-accent font-medium text-sidebar-accent-foreground'
                : 'text-muted-foreground hover:text-foreground',
              'data-drop:bg-accent data-drop:outline-2 data-drop:-outline-offset-2 data-drop:outline-ring',
            )}
          >
            <MessageSquare className="size-3.5 shrink-0" />
            <span className="truncate">Conversation</span>
            {ensuring && (
              <span className="ml-auto text-[10px] text-muted-foreground">Loading…</span>
            )}
          </button>
        </div>
      )}
    </div>
  );
}

export function StorageSidebar({ onNavigate }: { onNavigate: () => void }) {
  const b = useStorageBrowser();
  const [filter, setFilter] = useState('');
  const q = filter.trim().toLowerCase();

  // Team storages (exclude agent personal & conversation storages)
  const teamRoots = b.roots
    .filter(
      (root) => !root.agent && !root.isConversation && !root.name.startsWith('Conversation · '),
    )
    .filter((root) => root.name.toLowerCase().includes(q));

  // Agents list
  const workspaceAgents = b.workspace?.agents ?? [];
  const agentNames = Array.from(
    new Set([
      ...workspaceAgents.map((a) => a.name),
      ...b.roots.filter((r) => r.agent && !r.isConversation).map((r) => r.agent!),
    ]),
  );

  const agentItems = agentNames
    .map((name) => {
      const agent = workspaceAgents.find((a) => a.name === name) ?? {
        id: b.roots.find((r) => r.agent === name)?.agentId,
        name,
      };
      const personalRoot = b.roots.find(
        (r) =>
          !r.isConversation &&
          !r.name.startsWith('Conversation · ') &&
          (r.agent === name || r.name === name),
      );
      const conversationRoot = b.roots.find(
        (r) =>
          (r.isConversation && r.agent === name) || r.name.startsWith(`Conversation · ${name} · `),
      );
      return { agent, personalRoot, conversationRoot };
    })
    .filter(({ agent }) => {
      if (!q) return true;
      return (
        agent.name.toLowerCase().includes(q) || 'files'.includes(q) || 'conversation'.includes(q)
      );
    });

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
          {teamRoots.map((root) => (
            <StorageRow key={root.id} root={root} onNavigate={onNavigate} />
          ))}
        </div>
        {teamRoots.length > 0 && agentItems.length > 0 && (
          <Separator decorative={false} aria-label="Storage groups" className="my-3" />
        )}
        <div className="flex flex-col gap-1">
          {agentItems.map(({ agent, personalRoot, conversationRoot }) => (
            <AgentStorageRow
              key={agent.name}
              agent={agent}
              personalRoot={personalRoot}
              conversationRoot={conversationRoot}
              onNavigate={onNavigate}
            />
          ))}
        </div>
        {!teamRoots.length && !agentItems.length && (
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
