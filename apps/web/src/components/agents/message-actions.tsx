import { useState, type ReactNode } from 'react';
import { Copy, Link, MoreHorizontal, Reply } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import {
  ContextMenu,
  ContextMenuTrigger,
  ContextMenuContent,
  ContextMenuItem,
} from '@/components/ui/context-menu';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from '@/components/ui/dropdown-menu';
import { ReactionPicker, ReactionMenu, type ReactionAction } from './message-reactions';
import { cn } from '@/lib/utils';

type Actions = { text: string; onReply?: () => void; reaction?: ReactionAction; link?: string };

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    toast.error('Could not copy this message.');
  }
}

// Both entry points expose the same actions, as in OpenBot's MessageMenuItems.
function MenuItems({
  text,
  onReply,
  reaction,
  link,
  context = false,
}: Actions & { context?: boolean }) {
  const Item = context ? ContextMenuItem : DropdownMenuItem;
  return (
    <>
      {onReply && (
        <Item onSelect={onReply}>
          <Reply />
          Reply
        </Item>
      )}
      {reaction && <ReactionMenu {...reaction} context={context} />}
      <Item onSelect={() => void copy(text)}>
        <Copy />
        Copy
      </Item>
      {link && (
        <Item onSelect={() => void copy(link)}>
          <Link />
          Copy message link
        </Item>
      )}
    </>
  );
}

export function MessageMenu({ children, ...actions }: Actions & { children: ReactNode }) {
  return (
    <ContextMenu modal={false}>
      <ContextMenuTrigger asChild className="select-text">
        {children}
      </ContextMenuTrigger>
      <ContextMenuContent>
        <MenuItems {...actions} context />
      </ContextMenuContent>
    </ContextMenu>
  );
}

export function MessageActions({
  children,
  text,
  onReply,
  reaction,
  own = false,
  wide = false,
  context = true,
  title,
  link,
}: Actions & {
  children: ReactNode;
  own?: boolean;
  wide?: boolean;
  context?: boolean;
  title?: string;
}) {
  const [open, setOpen] = useState(false);
  const row = (
    <div
      data-slot="message-action-shell"
      data-own={own}
      title={title}
      onContextMenu={() => setOpen(false)}
      className={cn(
        'group/actions flex w-full min-w-0 items-center gap-1',
        own && 'flex-row-reverse',
      )}
    >
      <div
        className={cn(
          'min-w-0 [&>[data-slot=bubble]]:max-w-full',
          reaction ? 'max-w-[min(calc(100%-88px),720px)]' : 'max-w-[min(calc(100%-60px),720px)]',
          wide && 'max-w-[calc(100%-60px)] flex-1',
        )}
      >
        {children}
      </div>
      <div
        data-slot="message-actions"
        className={cn(
          'flex shrink-0 items-center gap-0.5 text-muted-foreground opacity-0 transition-opacity group-hover/actions:opacity-100 group-focus-within/actions:opacity-100 [&:has([data-state=open])]:opacity-100',
          open && 'opacity-100',
          'max-sm:opacity-100',
        )}
      >
        {reaction && <ReactionPicker {...reaction} />}
        {onReply && (
          <Button variant="ghost" size="icon-xs" aria-label="Reply to message" onClick={onReply}>
            <Reply />
          </Button>
        )}
        <DropdownMenu open={open} onOpenChange={setOpen}>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-xs" aria-label="Message actions">
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="top" align={own ? 'end' : 'start'}>
            <MenuItems text={text} onReply={onReply} reaction={reaction} link={link} />
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
  return context ? (
    <MessageMenu text={text} onReply={onReply} reaction={reaction} link={link}>
      {row}
    </MessageMenu>
  ) : (
    row
  );
}

export function ActivityComposer() {
  return (
    <div className="shrink-0 px-1.5 pt-1 pb-1.5">
      <div className="flex min-h-14 items-center rounded-3xl border border-input bg-muted px-4">
        <textarea
          disabled
          rows={1}
          aria-label="Activity messages"
          placeholder="You can’t send messages here."
          className="w-full resize-none bg-transparent text-sm leading-6 text-muted-foreground outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed"
        />
      </div>
    </div>
  );
}
