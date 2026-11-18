import { StorageImage } from './storage-image';
import {
  Fragment,
  lazy,
  Suspense,
  useEffect,
  useRef,
  useState,
  type PointerEvent,
  type ReactNode,
} from 'react';
import {
  CheckSquare,
  Columns3,
  Copy,
  Download,
  File,
  Folder,
  House,
  FolderInput,
  Grid2X2,
  Info,
  List,
  MoreVertical,
  Pencil,
  Plus,
  RotateCcw,
  Search,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { EditorTabs } from '@/components/agents/editor-tabs';
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
  AlertDialogAction,
} from '@/components/ui/alert-dialog';
import { StorageRootIcon } from './storage-root-icon';
import { FileIcon } from './file-icon';
import { Button } from '@/components/ui/button';
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuSeparator,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuGroup,
  ContextMenuSeparator,
  ContextMenuItem,
  ContextMenuTrigger,
} from '@/components/ui/context-menu';
import { Progress } from '@/components/ui/progress';
import { formatBytes } from '@/lib/storage-preview';
import {
  useStorageBrowser,
  rootId,
  ancestors,
  type StorageNode,
  type StorageView,
} from './storage-context';
import { useStorageDrop, useStoragePointerDrag } from './storage-drag';
import { StorageDialogs } from './storage-dialogs';
import { StorageSearch } from './storage-search';
import { StorageAccess } from './storage-access';
const StorageViewer = lazy(() =>
  import('./storage-viewer').then((module) => ({ default: module.StorageViewer })),
);

function Crumb({
  name,
  storage,
  folder,
  icon,
  current = false,
}: {
  name: string;
  storage: string;
  folder: string;
  icon?: ReactNode;
  current?: boolean;
}) {
  const b = useStorageBrowser();
  const drop = useStorageDrop(storage, folder || rootId(storage));
  return (
    <Button
      {...drop}
      variant="ghost"
      size="xs"
      className={cn(
        'storage-crumb max-w-36 shrink-0 truncate text-sm font-normal text-foreground max-[721px]:max-w-19 max-[721px]:px-1 data-drop:bg-accent data-drop:outline-2 data-drop:-outline-offset-2 data-drop:outline-ring',
        icon && 'storage-crumb-root h-7 max-w-45 gap-1.5 max-[721px]:max-w-28',
      )}
      aria-current={current ? 'page' : undefined}
      title={name}
      onClick={() => {
        if (!current) b.go(storage, folder);
      }}
    >
      {icon}
      <span className={icon ? 'sr-only' : 'truncate'}>{name}</span>
    </Button>
  );
}
function PathSeparator() {
  return (
    <span
      className="storage-path-rule shrink-0 px-0.75 text-sm text-muted-foreground"
      aria-hidden="true"
    >
      /
    </span>
  );
}
export function StorageIdentity() {
  const b = useStorageBrowser();
  const segments = b.trash ? [{ id: 'trash', name: 'Trash', storage: b.storage.id }] : b.path;
  const root = (
    <Crumb
      name="Storage root"
      storage={b.storage.id}
      folder=""
      icon={<House className="size-4" />}
      current={!segments.length}
    />
  );
  return (
    <nav
      aria-label="Storage path"
      className="storage-path flex w-full min-w-0 items-center gap-0.5 overflow-x-auto [scrollbar-width:none]"
    >
      {segments.length ? (
        root
      ) : (
        <h1 className="storage-crumb-heading flex min-w-0 shrink-0 text-inherit font-normal">
          {root}
        </h1>
      )}
      {segments.length > 1 && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="xs"
              aria-label="Parent folders"
              className="hidden max-[721px]:inline-flex"
            >
              …
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent>
            {segments.slice(0, -1).map((node) => (
              <DropdownMenuItem key={node.id} onSelect={() => b.go(node.storage, node.id)}>
                <Folder />
                {node.name}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
      {segments.map((node, index) => {
        const current = index === segments.length - 1;
        const crumb = (
          <Crumb name={node.name} storage={node.storage} folder={node.id} current={current} />
        );
        return (
          <span
            className={cn(
              'storage-path-segment inline-flex shrink-0 items-center gap-0.5',
              !current && 'max-[721px]:hidden',
            )}
            key={node.id}
          >
            <PathSeparator />
            {current ? (
              <h1 className="storage-crumb-heading flex min-w-0 shrink-0 text-inherit font-normal">
                {crumb}
              </h1>
            ) : (
              crumb
            )}
          </span>
        );
      })}
    </nav>
  );
}
export function StorageTabs() {
  const b = useStorageBrowser();
  return (
    <>
      <EditorTabs
        label="Storage tabs"
        selected={b.file?.id ?? 'browser'}
        onSelect={(id) =>
          id === 'browser'
            ? b.go(b.storage.id, b.trash ? 'trash' : b.folderId)
            : b.open(b.openFiles.find((node) => node.id === id)!)
        }
        items={[
          {
            id: 'browser',
            label: b.storage.name,
            icon: <StorageRootIcon root={b.storage} />,
            title: (
              <h1 className="truncate font-normal">
                {b.storage.name}
                {b.storage.title && (
                  <span className="text-muted-foreground"> · {b.storage.title}</span>
                )}
              </h1>
            ),
          },
          ...b.openFiles.map((node) => ({
            id: node.id,
            label: node.name,
            tooltip:
              '/' +
              [b.storage.name, ...ancestors(b.snapshot.nodes, node.id).map((at) => at.name)].join(
                '/',
              ),
            icon: <FileIcon node={node} />,
            onClose: () => b.closeFile(node.id),
          })),
        ]}
      />
      <AlertDialog
        open={!!b.closeRequest}
        onOpenChange={(open) => !open && b.setCloseRequest(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Close without saving?</AlertDialogTitle>
            <AlertDialogDescription>Your changes have not been saved.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep editing</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => b.closeFile(b.closeRequest!, true)}
            >
              Discard changes
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
export function StorageHeaderTools() {
  const b = useStorageBrowser();
  return (
    <>
      <StorageAccess />
      <ToggleGroup
        type="single"
        size="sm"
        value={b.view}
        onValueChange={(value) => value && b.setView(value as StorageView)}
        aria-label="Display mode"
      >
        {[
          { value: 'mosaic', label: 'Mosaic', Icon: Columns3 },
          { value: 'grid', label: 'Grid', Icon: Grid2X2 },
          { value: 'list', label: 'List', Icon: List },
        ].map(({ value, label, Icon }) => (
          <ToggleGroupItem
            key={value}
            value={value}
            aria-label={label}
            title={label}
            size="icon-sm"
          >
            <Icon />
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      <Button
        variant={b.selecting ? 'secondary' : 'ghost'}
        size="icon-sm"
        aria-label={b.selecting ? 'Cancel selection' : 'Select files'}
        title="Select files"
        onClick={() => (b.selecting ? b.clearSelection() : b.setSelecting(true))}
      >
        <CheckSquare />
      </Button>
    </>
  );
}
function nodeActions(b: ReturnType<typeof useStorageBrowser>, node: StorageNode) {
  const ids = b.selected.has(node.id) ? [...b.selected] : [node.id];
  const write = b.roots.find((root) => root.id === node.storage)?.write;
  if (b.trash)
    return [
      { label: 'Restore', icon: RotateCcw, action: () => void b.restore(ids), disabled: !write },
      {
        label: 'Delete permanently',
        icon: Trash2,
        action: () => b.setPurgeIds(ids),
        disabled: !write || b.pending,
        destructive: true,
      },
    ];
  return [
    { label: 'Open', icon: node.kind === 'folder' ? Folder : File, action: () => b.open(node) },
    { label: 'Download', icon: Download, action: () => void b.download(ids) },
    {
      label: 'Move to…',
      icon: FolderInput,
      action: () => b.setTransfer({ ids, copy: false, storage: node.storage, parent: b.parent }),
      disabled: !write,
    },
    {
      label: 'Copy to…',
      icon: Copy,
      action: () => b.setTransfer({ ids, copy: true, storage: node.storage, parent: b.parent }),
    },
    { label: 'Copy', icon: Copy, action: () => b.setClipboard({ ids, copy: true }) },
    {
      label: 'Rename',
      icon: Pencil,
      action: () => b.setNameRequest({ kind: 'rename', node }),
      disabled: !write || ids.length > 1,
    },
    { label: 'Details', icon: Info, action: () => b.setDetails(node) },
    {
      label: 'Move to Trash',
      icon: Trash2,
      action: () => b.setDeleteIds(ids),
      disabled: !write,
      destructive: true,
    },
  ];
}
function NodeCard({ node }: { node: StorageNode }) {
  const b = useStorageBrowser();
  const drop = useStorageDrop(node.storage, node.kind === 'folder' ? node.id : b.parent);
  const [excerpt, setExcerpt] = useState('');
  useEffect(() => {
    let active = true;
    if (node.blob && /^(text\/|application\/json$)/.test(node.mime))
      void node.blob
        .slice(0, 1500)
        .text()
        .then((value) => {
          if (active) setExcerpt(value);
        })
        .catch(() => {});
    return () => {
      active = false;
    };
  }, [node.blob, node.mime]);
  const children =
    node.kind === 'folder'
      ? b.snapshot.nodes.filter((child) => child.parent === node.id && !child.trashed)
      : [];
  const selected = b.selected.has(node.id);
  const actions = nodeActions(b, node);
  const date = new Date(node.updated).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
  });
  function activate(event: React.MouseEvent | React.KeyboardEvent) {
    if (b.selecting || event.ctrlKey || event.metaKey || event.shiftKey || b.trash)
      b.toggle(node, event);
    else b.open(node);
  }
  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>
        <article
          {...(node.kind === 'folder' ? drop : {})}
          className={cn(
            'storage-item relative min-w-0 break-inside-avoid rounded-xl border border-transparent bg-muted hover:border-border hover:bg-accent data-selected:border-ring data-selected:bg-accent data-dragging:opacity-50 data-drop:bg-accent data-drop:outline-2 data-drop:-outline-offset-2 data-drop:outline-ring',
            b.view === 'list' && 'rounded-md bg-transparent',
            b.view === 'mosaic' && node.kind === 'file' && 'mb-4.5',
          )}
          data-node={node.id}
          data-kind={node.kind}
          data-selected={selected || undefined}
          draggable={false}
          onDragStart={(event) => event.preventDefault()}
        >
          <button
            className={cn(
              'storage-item-open flex w-full min-w-0 flex-col items-stretch rounded-[inherit] text-left -outline-offset-2',
              b.view === 'list' &&
                'grid min-h-12 grid-cols-[24px_minmax(0,1fr)_88px_90px] items-center gap-3 py-1 pr-10 pl-3.5 @max-[480px]/storage:grid-cols-[24px_minmax(0,1fr)_65px] @max-[480px]/storage:gap-1.5 @max-[480px]/storage:pr-7.5',
            )}
            aria-label={`Open ${node.name}`}
            aria-pressed={selected}
            onClick={activate}
          >
            <span
              className={cn(
                'storage-item-heading flex h-12.5 min-w-0 items-center gap-3 pr-10 pl-3.5 max-[721px]:gap-2 max-[721px]:pl-2.5',
                node.kind === 'folder' && 'h-13',
                b.view === 'list' && 'contents',
              )}
            >
              <FileIcon node={node} />
              <span
                className="storage-item-name min-w-0 truncate text-sm leading-5 font-medium"
                title={node.name}
              >
                {node.name}
              </span>
            </span>
            {node.kind === 'file' && (
              <span
                className={cn(
                  'storage-item-preview mx-2 mb-2 flex aspect-4/3 w-[calc(100%-16px)] items-center justify-center overflow-hidden rounded-sm bg-background [&>.storage-file-icon]:size-12',
                  b.view === 'list' && 'hidden',
                  b.view === 'mosaic' && 'has-[img]:aspect-auto',
                )}
              >
                {node.mime.startsWith('image/') ? (
                  <StorageImage node={node} className="block size-full" />
                ) : excerpt ? (
                  <span className="storage-text-preview line-clamp-6 w-full self-start p-3.5 text-[0.6875rem] leading-relaxed whitespace-pre-wrap wrap-anywhere text-muted-foreground">
                    {excerpt}
                  </span>
                ) : (
                  <FileIcon node={node} />
                )}
              </span>
            )}
            <span
              className={cn(
                'storage-item-size hidden text-xs text-muted-foreground',
                b.view === 'list' && 'block',
              )}
            >
              {node.kind === 'folder'
                ? `${children.length} item${children.length === 1 ? '' : 's'}`
                : formatBytes(node.size)}
            </span>
            <span
              className={cn(
                'storage-item-date hidden text-xs text-muted-foreground',
                b.view === 'list' && 'block @max-[480px]/storage:hidden',
              )}
            >
              {date}
            </span>
          </button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                className={cn(
                  'storage-item-menu absolute top-2.75 right-2',
                  node.kind === 'folder' && 'top-3',
                  b.view === 'list' && 'top-2.5',
                )}
                variant="ghost"
                size="icon-xs"
                aria-label={`Actions for ${node.name}`}
              >
                <MoreVertical />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuGroup>
                {actions.map(({ label, icon: Icon, action, disabled, ...rest }) => (
                  <Fragment key={label}>
                    {rest.destructive && <DropdownMenuSeparator />}
                    <DropdownMenuItem
                      disabled={disabled}
                      variant={rest.destructive ? 'destructive' : 'default'}
                      onSelect={action}
                    >
                      <Icon />
                      {label}
                    </DropdownMenuItem>
                  </Fragment>
                ))}
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        </article>
      </ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuGroup>
          {actions.map(({ label, icon: Icon, action, disabled, ...rest }) => (
            <Fragment key={label}>
              {rest.destructive && <ContextMenuSeparator />}
              <ContextMenuItem
                disabled={disabled}
                variant={rest.destructive ? 'destructive' : 'default'}
                onSelect={action}
              >
                <Icon />
                {label}
              </ContextMenuItem>
            </Fragment>
          ))}
        </ContextMenuGroup>
      </ContextMenuContent>
    </ContextMenu>
  );
}
function useMarquee() {
  const b = useStorageBrowser();
  const [rect, setRect] = useState<{ x: number; y: number; width: number; height: number } | null>(
    null,
  );
  const cleanup = useRef<() => void>(() => {});
  useEffect(() => () => cleanup.current(), []);
  function start(event: PointerEvent<HTMLDivElement>) {
    if (
      event.button !== 0 ||
      event.pointerType === 'touch' ||
      (event.target as HTMLElement).closest('button,input,[role=checkbox],[data-node]')
    )
      return;
    const surface = event.currentTarget;
    const bounds = surface.getBoundingClientRect();
    const origin = {
      x: event.clientX - bounds.left + surface.scrollLeft,
      y: event.clientY - bounds.top + surface.scrollTop,
    };
    const previous = new Set(b.selected);
    let active = false;
    let pointer = { x: event.clientX, y: event.clientY };
    let raf = 0;
    function draw() {
      if (!active) return;
      if (pointer.y < bounds.top + 48) surface.scrollTop -= 12;
      if (pointer.y > bounds.bottom - 48) surface.scrollTop += 12;
      const end = {
        x: pointer.x - bounds.left + surface.scrollLeft,
        y: pointer.y - bounds.top + surface.scrollTop,
      };
      const box = {
        x: Math.min(origin.x, end.x),
        y: Math.min(origin.y, end.y),
        width: Math.abs(end.x - origin.x),
        height: Math.abs(end.y - origin.y),
      };
      setRect(box);
      const selected = event.ctrlKey || event.metaKey ? new Set(previous) : new Set<string>();
      surface.querySelectorAll<HTMLElement>('[data-node]').forEach((item) => {
        const r = item.getBoundingClientRect();
        const x = r.left - bounds.left + surface.scrollLeft;
        const y = r.top - bounds.top + surface.scrollTop;
        if (
          x < box.x + box.width &&
          x + r.width > box.x &&
          y < box.y + box.height &&
          y + r.height > box.y
        )
          selected.add(item.dataset.node!);
      });
      b.setSelected(selected);
      b.setSelecting(true);
      raf = requestAnimationFrame(draw);
    }
    function move(e: globalThis.PointerEvent) {
      pointer = { x: e.clientX, y: e.clientY };
      if (!active && Math.hypot(e.clientX - event.clientX, e.clientY - event.clientY) > 6) {
        active = true;
        draw();
      }
    }
    function finish() {
      cancelAnimationFrame(raf);
      setRect(null);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', finish);
      window.removeEventListener('keydown', cancel);
    }
    function cancel(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        finish();
        b.setSelected(previous);
      }
    }
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', finish);
    window.addEventListener('keydown', cancel);
    cleanup.current = finish;
  }
  return { rect, start };
}
export function StoragePage({ embedded = false }: { embedded?: boolean } = {}) {
  const b = useStorageBrowser();
  const fileInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const drop = useStorageDrop(b.storage.id, b.parent);
  const { rect, start } = useMarquee();
  const dragStart = useStoragePointerDrag();
  const content = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function key(event: KeyboardEvent) {
      if (
        (event.target as HTMLElement).closest(
          'input,textarea,[contenteditable=true],[role=dialog],[role=menu]',
        ) ||
        b.file ||
        (embedded && !content.current?.contains(event.target as Node)) ||
        (!embedded && !!document.querySelector('[data-embedded-storage]:focus-within'))
      )
        return;
      if (event.key === 'Escape') {
        b.clearSelection();
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a') {
        event.preventDefault();
        b.setSelecting(true);
        b.setSelected(new Set(b.visible.map((node) => node.id)));
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'c' && b.selected.size)
        b.setClipboard({ ids: [...b.selected], copy: true });
      if (
        (event.ctrlKey || event.metaKey) &&
        event.key.toLowerCase() === 'v' &&
        b.clipboard &&
        !b.trash
      ) {
        event.preventDefault();
        b.paste();
      }
      if (event.key === 'Delete' && b.selected.size && !b.trash && b.storage.write)
        b.setDeleteIds([...b.selected]);
    }
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [b]);
  const create = () =>
    b.setNameRequest({ kind: 'create', storage: b.storage.id, parent: b.parent });
  const createFile = () =>
    b.setNameRequest({ kind: 'create-file', storage: b.storage.id, parent: b.parent });
  const upload = (files: File[]) => {
    void b.upload(files.map((file) => ({ file, path: file.webkitRelativePath || file.name })));
  };
  const folders = b.visible.filter((node) => node.kind === 'folder');
  const files = b.visible.filter((node) => node.kind === 'file');
  const emptyActions = (
    <>
      <ContextMenuItem disabled={!b.storage.write || b.trash} onSelect={createFile}>
        <File />
        New file
      </ContextMenuItem>
      <ContextMenuItem disabled={!b.storage.write || b.trash} onSelect={create}>
        <Folder />
        New folder
      </ContextMenuItem>
      <ContextMenuItem
        disabled={!b.storage.write || b.trash}
        onSelect={() => fileInput.current?.click()}
      >
        <Upload />
        Upload files
      </ContextMenuItem>
      <ContextMenuItem disabled={!b.clipboard || !b.storage.write || b.trash} onSelect={b.paste}>
        <Copy />
        Paste
      </ContextMenuItem>
    </>
  );
  if (b.unavailable)
    return (
      <p role="alert" className="p-6 text-sm">
        This storage or file is unavailable.
      </p>
    );
  return (
    <div
      className="storage-page @container/storage relative flex h-full min-w-0 flex-col bg-sidebar"
      data-embedded-storage={embedded || undefined}
      onPointerDownCapture={dragStart}
    >
      {!b.file && (
        <div className="flex min-h-11 items-center gap-2 border-b px-3">
          <StorageIdentity />
          <div className="ml-auto flex shrink-0 items-center gap-1">
            <StorageHeaderTools />
          </div>
        </div>
      )}
      <div
        className="storage-browser flex min-h-0 flex-1 min-w-0 flex-col"
        ref={content}
        hidden={!!b.file}
      >
        <div className="storage-toolbar flex shrink-0 items-center gap-2 px-5 py-3 @max-[560px]/storage:flex-wrap @max-[560px]/storage:gap-1.5 @max-[560px]/storage:px-3">
          {!b.trash && (
            <>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm" disabled={!b.storage.write || !!b.pending}>
                    <Plus />
                    New
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start">
                  <DropdownMenuItem onSelect={createFile}>
                    <File />
                    New file
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={create}>
                    <Folder />
                    New folder
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => fileInput.current?.click()}>
                    <Upload />
                    Upload files
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => folderInput.current?.click()}>
                    <FolderInput />
                    Upload folder
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              <Button
                className="storage-upload-button @max-[560px]/storage:hidden"
                variant="ghost"
                size="sm"
                disabled={!b.storage.write || !!b.pending}
                onClick={() => fileInput.current?.click()}
              >
                <Upload />
                Upload
              </Button>
            </>
          )}
          {b.trash && (
            <Button
              variant="outline"
              size="sm"
              disabled={
                !b.storage.write ||
                b.pending ||
                b.query.isPending ||
                !b.snapshot.nodes.some((node) => node.storage === b.storage.id && node.trashed)
              }
              onClick={() =>
                b.setPurgeIds(
                  b.snapshot.nodes
                    .filter((node) => node.storage === b.storage.id && node.trashed)
                    .map((node) => node.id),
                )
              }
            >
              <Trash2 />
              Empty Trash
            </Button>
          )}
          <InputGroup className="storage-search ml-auto h-7.5 min-w-25 max-w-64 @max-[560px]/storage:max-w-none @max-[560px]/storage:flex-1">
            <InputGroupAddon>
              <Search />
            </InputGroupAddon>
            <InputGroupInput
              aria-label="Search files"
              placeholder="Search this folder…"
              value={b.filter}
              onChange={(event) => b.setFilter(event.target.value)}
            />
          </InputGroup>
          {!b.trash && <StorageSearch />}
          <Select value={b.type} onValueChange={b.setType}>
            <SelectTrigger
              size="sm"
              aria-label="File type"
              className="storage-filter w-29 @max-[700px]/storage:hidden"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {[
                ['all', 'All files'],
                ['images', 'Images'],
                ['documents', 'Documents'],
                ['spreadsheets', 'Spreadsheets'],
                ['media', 'Media'],
                ['other', 'Other'],
              ].map(([id, label]) => (
                <SelectItem key={id} value={id}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={b.sort} onValueChange={b.setSort}>
            <SelectTrigger
              size="sm"
              aria-label="Sort files"
              className="storage-sort w-27.5 @max-[560px]/storage:w-22"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="name">Name</SelectItem>
              <SelectItem value="updated">Modified</SelectItem>
              <SelectItem value="size">Size</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <input
          ref={fileInput}
          type="file"
          multiple
          hidden
          aria-label="Upload files"
          onChange={(event) => {
            upload(Array.from(event.target.files ?? []));
            event.target.value = '';
          }}
        />
        <input
          ref={folderInput}
          type="file"
          multiple
          {...{ webkitdirectory: '' }}
          hidden
          aria-label="Upload folder"
          onChange={(event) => {
            upload(Array.from(event.target.files ?? []));
            event.target.value = '';
          }}
        />
        {b.progress && (
          <div role="status" className="px-5 pt-2 text-xs text-muted-foreground">
            {b.progress.label}
            {b.progress.total > 0 && ` · ${b.progress.done} / ${b.progress.total}`}
            {b.progress.cancel && (
              <Button size="sm" variant="ghost" onClick={b.progress.cancel}>
                Cancel download
              </Button>
            )}
            <Progress
              className="mt-1 h-1"
              value={b.progress.total ? (b.progress.done / b.progress.total) * 100 : 0}
            />
          </div>
        )}
        <ContextMenu>
          <ContextMenuTrigger asChild>
            <div
              {...(!b.trash ? drop : {})}
              className="storage-surface relative min-h-0 flex-1 overflow-auto px-5 pt-1 pb-20 select-none max-[721px]:px-3 data-drop:bg-accent data-drop:outline-2 data-drop:-outline-offset-2 data-drop:outline-ring"
              onPointerDown={start}
              aria-label="Folder contents"
            >
              {b.query.isLoading ? (
                <p
                  role="status"
                  className="storage-empty flex h-full min-h-60 flex-1 flex-col items-center justify-center p-8 text-center text-muted-foreground"
                >
                  Loading files…
                </p>
              ) : b.query.isError ? (
                <div
                  role="alert"
                  className="storage-empty flex h-full min-h-60 flex-1 flex-col items-center justify-center p-8 text-center text-muted-foreground"
                >
                  <p>Could not load this storage.</p>
                  <Button variant="outline" onClick={() => void b.query.refetch()}>
                    Retry
                  </Button>
                </div>
              ) : !b.visible.length ? (
                <div className="storage-empty flex h-full min-h-60 flex-1 flex-col items-center justify-center p-8 text-center text-muted-foreground">
                  <Folder className="mb-3 size-8" strokeWidth={1.25} />
                  <p className="font-medium text-foreground">
                    {b.filter || b.type !== 'all'
                      ? 'No matching files'
                      : b.trash
                        ? 'Trash is empty'
                        : 'This folder is empty'}
                  </p>
                  <p className="mt-1 text-sm">
                    {b.filter || b.type !== 'all'
                      ? 'Try another search or file type.'
                      : b.trash
                        ? 'Deleted items will appear here.'
                        : 'Drop files here or upload something to get started.'}
                  </p>
                </div>
              ) : (
                <>
                  {b.view === 'list' && (
                    <div className="storage-list-head mb-1 grid grid-cols-[minmax(0,1fr)_88px_90px] gap-3 border-b py-2 pr-10 pl-12.5 text-xs text-muted-foreground @max-[480px]/storage:grid-cols-[minmax(0,1fr)_65px] @max-[480px]/storage:pr-7.5 @max-[480px]/storage:[&>span:last-child]:hidden">
                      <span>Name</span>
                      <span>Size</span>
                      <span>Modified</span>
                    </div>
                  )}
                  {b.view !== 'list' ? (
                    <>
                      <div
                        className="storage-items storage-folders mb-8 grid grid-cols-[repeat(auto-fill,minmax(min(220px,100%),1fr))] content-start gap-4.5 empty:hidden max-[721px]:grid-cols-2 max-[721px]:gap-3"
                        data-view="folders"
                      >
                        {folders.map((node) => (
                          <NodeCard key={node.id} node={node} />
                        ))}
                      </div>
                      <div
                        className={cn(
                          'storage-items',
                          b.view === 'grid'
                            ? 'grid grid-cols-[repeat(auto-fill,minmax(min(220px,100%),1fr))] content-start gap-4.5 max-[721px]:grid-cols-2 max-[721px]:gap-3'
                            : b.view === 'mosaic'
                              ? 'columns-4 gap-4.5 [column-width:220px] max-[721px]:columns-2 max-[721px]:gap-3 max-[721px]:[column-width:140px]'
                              : 'flex flex-col gap-0.5',
                        )}
                        data-view={b.view}
                      >
                        {files.map((node) => (
                          <NodeCard key={node.id} node={node} />
                        ))}
                      </div>
                    </>
                  ) : (
                    <div className="storage-items flex flex-col gap-0.5" data-view={b.view}>
                      {b.visible.map((node) => (
                        <NodeCard key={node.id} node={node} />
                      ))}
                    </div>
                  )}
                  <p className="storage-count mt-5 text-xs text-muted-foreground">
                    {b.visible.length} item{b.visible.length === 1 ? '' : 's'}
                  </p>
                </>
              )}
              {rect && (
                <div
                  className="storage-marquee pointer-events-none absolute border border-ring bg-ring/16"
                  style={{ left: rect.x, top: rect.y, width: rect.width, height: rect.height }}
                />
              )}
            </div>
          </ContextMenuTrigger>
          <ContextMenuContent>{emptyActions}</ContextMenuContent>
        </ContextMenu>
        {b.selected.size > 0 && (
          <div
            className="storage-selection absolute bottom-4.5 left-1/2 flex max-w-[calc(100%-24px)] -translate-x-1/2 items-center gap-2 rounded-2xl border bg-popover px-2.5 py-1.5 shadow-lg max-[721px]:gap-0.75 max-[721px]:px-1.5"
            role="toolbar"
            aria-label="Selected files"
          >
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label="Clear selection"
              onClick={b.clearSelection}
            >
              <X />
            </Button>
            <span className="whitespace-nowrap text-sm">{b.selected.size} selected</span>
            {b.trash ? (
              <>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={!b.storage.write || !!b.pending}
                  onClick={() => void b.restore([...b.selected])}
                >
                  <RotateCcw />
                  Restore
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Delete selected permanently"
                  disabled={!b.storage.write || b.pending}
                  onClick={() => b.setPurgeIds([...b.selected])}
                >
                  <Trash2 />
                </Button>
              </>
            ) : (
              <>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Download selected"
                  disabled={!!b.progress}
                  onClick={() => void b.download([...b.selected])}
                >
                  <Download />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Move selected"
                  disabled={!b.storage.write || !!b.pending}
                  onClick={() =>
                    b.setTransfer({
                      ids: [...b.selected],
                      copy: false,
                      storage: b.storage.id,
                      parent: b.parent,
                    })
                  }
                >
                  <FolderInput />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Copy selected"
                  disabled={!!b.pending}
                  onClick={() =>
                    b.setTransfer({
                      ids: [...b.selected],
                      copy: true,
                      storage: b.storage.id,
                      parent: b.parent,
                    })
                  }
                >
                  <Copy />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Trash selected"
                  disabled={!b.storage.write || !!b.pending}
                  onClick={() => b.setDeleteIds([...b.selected])}
                >
                  <Trash2 />
                </Button>
              </>
            )}
          </div>
        )}
      </div>
      <StorageDialogs />
      {b.openFiles.map((node) => (
        <div key={node.id} className="min-h-0 flex-1" hidden={b.file?.id !== node.id}>
          <Suspense
            fallback={
              <p role="status" className="p-4 text-sm text-muted-foreground">
                Loading preview…
              </p>
            }
          >
            <StorageViewer node={node} />
          </Suspense>
        </div>
      ))}
    </div>
  );
}
