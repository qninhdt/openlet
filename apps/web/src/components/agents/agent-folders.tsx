// Port of OpenBot's SidebarSectionHeader / SidebarSectionEditor / SidebarMoveToSubmenu.
import { useState } from 'react';
import {
  ArrowDown,
  ArrowUp,
  Check,
  Folder,
  FolderInput,
  FolderOpen,
  FolderPlus,
  Pencil,
  Trash2,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  ContextMenu,
  ContextMenuTrigger,
  ContextMenuContent,
  ContextMenuGroup,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuSub,
  ContextMenuSubTrigger,
  ContextMenuSubContent,
} from '@/components/ui/context-menu';
import { folderDestination, folderLabel, type AgentFolder } from '@/lib/agent-organization';
import { useAgentPreview } from './agent-preview';
import { cn } from '@/lib/utils';

export function AgentMoveMenu({ id }: { id: string }) {
  const p = useAgentPreview();
  const { layout, save, busy } = p.organization;
  const move = (folder: string | null) => {
    const assignments = { ...layout.assignments };
    if (folder) assignments[id] = folder;
    else delete assignments[id];
    void save({ ...layout, assignments }).catch(() => {});
  };
  return (
    <ContextMenuSub>
      <ContextMenuSubTrigger disabled={busy}>
        <FolderInput />
        Move to…
      </ContextMenuSubTrigger>
      <ContextMenuSubContent>
        <ContextMenuGroup>
          {layout.folders.map((f) => (
            <ContextMenuItem key={f.id} onSelect={() => move(f.id)}>
              {layout.assignments[id] === f.id ? <Check /> : <Folder />}
              <span className="truncate">{folderLabel(layout.folders, f.id)}</span>
            </ContextMenuItem>
          ))}
          <ContextMenuItem onSelect={() => move(null)}>
            {!layout.assignments[id] ? <Check /> : <Folder />}Unassigned
          </ContextMenuItem>
        </ContextMenuGroup>
        <ContextMenuSeparator />
        <ContextMenuGroup>
          <ContextMenuItem
            onSelect={() =>
              p.setFolderEditor({ id: null, parent_id: null, name: '', agent_id: id })
            }
          >
            <FolderPlus />
            New folder
          </ContextMenuItem>
        </ContextMenuGroup>
      </ContextMenuSubContent>
    </ContextMenuSub>
  );
}
export function FolderEditor() {
  const p = useAgentPreview();
  const editor = p.folderEditor!;
  const [name, setName] = useState(editor.name);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  async function submit() {
    if (!name.trim() || saving) return;
    setSaving(true);
    const layout = p.organization.layout;
    const id = editor.id ?? crypto.randomUUID();
    const folder = { id, name: name.trim(), parent_id: editor.parent_id };
    try {
      await p.organization.save({
        ...layout,
        folders: editor.id
          ? layout.folders.map((f) => (f.id === id ? folder : f))
          : [...layout.folders, folder],
        assignments: editor.agent_id
          ? { ...layout.assignments, [editor.agent_id]: id }
          : layout.assignments,
        collapsed: layout.collapsed.filter((f) => f !== editor.parent_id),
      });
      p.setFolderEditor(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Could not save folder.');
      setSaving(false);
    }
  }
  return (
    <div className="px-1 py-1">
      <Input
        autoFocus
        aria-label={editor.id ? 'Rename folder' : 'New folder name'}
        maxLength={80}
        value={name}
        disabled={saving}
        aria-invalid={!!error}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.nativeEvent.isComposing || e.keyCode === 229) return;
          if (e.key === 'Enter') {
            e.preventDefault();
            void submit();
          }
          if (e.key === 'Escape') p.setFolderEditor(null);
        }}
        onBlur={(e) => {
          if (!saving && !error && e.relatedTarget) p.setFolderEditor(null);
        }}
      />
      {error && (
        <p role="alert" className="pt-1 text-caption text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
export function AgentFolderSection({
  folder,
  children,
  dragged,
  drop,
  onDrag,
  over,
  setOver,
}: {
  folder: AgentFolder;
  children: React.ReactNode;
  dragged: string;
  drop: (folder: string | null) => void;
  onDrag: (id: string) => void;
  over: string;
  setOver: (id: string) => void;
}) {
  const p = useAgentPreview();
  const { layout, save, busy } = p.organization;
  const collapsed =
    layout.collapsed.includes(folder.id) &&
    !(p.folderEditor?.id === null && p.folderEditor.parent_id === folder.id);
  const parent = layout.folders.find((f) => f.id === folder.parent_id);
  const siblings = layout.folders.filter((f) => f.parent_id === folder.parent_id);
  const index = siblings.findIndex((f) => f.id === folder.id);
  const empty =
    !p.workspace.agents.some(
      (a) =>
        layout.assignments[a.id] === folder.id &&
        !p.pins.includes(a.id) &&
        !p.sidebarChats[a.id].unread_count,
    ) && !layout.folders.some((f) => f.parent_id === folder.id);
  const canDrop =
    !dragged.startsWith('folder:') ||
    folderDestination(layout.folders, dragged.slice(7), folder.id);
  const mutate = (folders: AgentFolder[]) => void save({ ...layout, folders }).catch(() => {});
  const move = (offset: number) => {
    const target = siblings[index + offset];
    if (!target) return;
    const folders = [...layout.folders];
    const from = folders.findIndex((f) => f.id === folder.id),
      to = folders.findIndex((f) => f.id === target.id);
    [folders[from], folders[to]] = [folders[to], folders[from]];
    mutate(folders);
  };
  return (
    <section
      aria-label={folderLabel(layout.folders, folder.id)}
      className="flex min-w-0 flex-col"
      onDragOver={(e) => {
        if (!dragged || !canDrop) return;
        e.preventDefault();
        e.stopPropagation();
        setOver(folder.id);
      }}
      onDragLeave={() => setOver('')}
      onDrop={(e) => {
        if (!dragged || !canDrop) return;
        e.preventDefault();
        e.stopPropagation();
        drop(folder.id);
      }}
    >
      {p.folderEditor?.id === folder.id ? (
        <FolderEditor key={folder.id} />
      ) : (
        <ContextMenu>
          <ContextMenuTrigger asChild>
            <Button
              variant="ghost"
              aria-label={folder.name}
              aria-expanded={!collapsed}
              aria-controls={`folder-${folder.id}`}
              disabled={busy}
              draggable
              onDragStart={(e) => {
                e.stopPropagation();
                onDrag('folder:' + folder.id);
              }}
              onDragEnd={() => onDrag('')}
              onClick={() =>
                void save({
                  ...layout,
                  collapsed: collapsed
                    ? layout.collapsed.filter((f) => f !== folder.id)
                    : [...layout.collapsed, folder.id],
                }).catch(() => {})
              }
              className={cn(
                'h-8 w-full justify-between gap-2 px-1.75 text-caption leading-4 font-normal text-foreground hover:bg-transparent aria-expanded:bg-transparent',
                over === folder.id && 'bg-accent ring-1 ring-ring',
              )}
            >
              <span className="min-w-0 truncate">
                {parent && <span className="text-muted-foreground">{parent.name} / </span>}
                {folder.name}
              </span>
              {collapsed || empty ? (
                <Folder className="shrink-0 text-muted-foreground" />
              ) : (
                <FolderOpen className="shrink-0 text-muted-foreground" />
              )}
            </Button>
          </ContextMenuTrigger>
          <ContextMenuContent>
            <ContextMenuGroup>
              <ContextMenuItem onSelect={() => p.setFolderEditor({ ...folder })}>
                <Pencil />
                Rename
              </ContextMenuItem>
              <ContextMenuItem
                disabled={!folderDestination(layout.folders, 'new', folder.id)}
                onSelect={() => p.setFolderEditor({ id: null, parent_id: folder.id, name: '' })}
              >
                <FolderPlus />
                New folder inside
              </ContextMenuItem>
              <ContextMenuSub>
                <ContextMenuSubTrigger>
                  <FolderInput />
                  Move to…
                </ContextMenuSubTrigger>
                <ContextMenuSubContent>
                  <ContextMenuGroup>
                    {folder.parent_id && (
                      <ContextMenuItem
                        onSelect={() =>
                          mutate(
                            layout.folders.map((f) =>
                              f.id === folder.id ? { ...f, parent_id: null } : f,
                            ),
                          )
                        }
                      >
                        <FolderOpen />
                        Top level
                      </ContextMenuItem>
                    )}
                    {layout.folders
                      .filter(
                        (f) =>
                          f.id !== folder.parent_id &&
                          folderDestination(layout.folders, folder.id, f.id),
                      )
                      .map((f) => (
                        <ContextMenuItem
                          key={f.id}
                          onSelect={() =>
                            mutate(
                              layout.folders.map((item) =>
                                item.id === folder.id ? { ...item, parent_id: f.id } : item,
                              ),
                            )
                          }
                        >
                          <Folder />
                          <span className="truncate">{folderLabel(layout.folders, f.id)}</span>
                        </ContextMenuItem>
                      ))}
                  </ContextMenuGroup>
                </ContextMenuSubContent>
              </ContextMenuSub>
              <ContextMenuItem disabled={index === 0} onSelect={() => move(-1)}>
                <ArrowUp />
                Move up
              </ContextMenuItem>
              <ContextMenuItem disabled={index === siblings.length - 1} onSelect={() => move(1)}>
                <ArrowDown />
                Move down
              </ContextMenuItem>
            </ContextMenuGroup>
            <ContextMenuSeparator />
            <ContextMenuGroup>
              <ContextMenuItem
                variant="destructive"
                onSelect={() => {
                  const assignments = { ...layout.assignments };
                  for (const [id, target] of Object.entries(assignments))
                    if (target === folder.id) {
                      if (folder.parent_id) assignments[id] = folder.parent_id;
                      else delete assignments[id];
                    }
                  void save({
                    ...layout,
                    folders: layout.folders
                      .filter((f) => f.id !== folder.id)
                      .map((f) =>
                        f.parent_id === folder.id ? { ...f, parent_id: folder.parent_id } : f,
                      ),
                    assignments,
                    collapsed: layout.collapsed.filter((f) => f !== folder.id),
                  }).catch(() => {});
                }}
              >
                <Trash2 />
                Delete folder
              </ContextMenuItem>
            </ContextMenuGroup>
          </ContextMenuContent>
        </ContextMenu>
      )}
      <div
        id={`folder-${folder.id}`}
        hidden={collapsed}
        className="flex min-w-0 flex-col gap-1 [&>section]:mt-1.5"
      >
        {children}
        {p.folderEditor?.id === null && p.folderEditor.parent_id === folder.id && (
          <FolderEditor key={`new:${folder.id}`} />
        )}
      </div>
    </section>
  );
}
