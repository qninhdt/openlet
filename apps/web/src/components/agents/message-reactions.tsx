// OpenBot's six-emoji picker, expanded row, and reactions anchored to the bubble edge.
import { useState } from 'react';
import { Plus, SmilePlus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { BubbleReactions } from '@/components/ui/bubble';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSub,
  DropdownMenuSubTrigger,
  DropdownMenuSubContent,
} from '@/components/ui/dropdown-menu';
import {
  ContextMenuSub,
  ContextMenuSubTrigger,
  ContextMenuSubContent,
  ContextMenuGroup,
  ContextMenuItem,
} from '@/components/ui/context-menu';
import { cn } from '@/lib/utils';
import type { MessageReaction } from '@/lib/agent-api';

const common = ['👍', '👎', '❤️', '😂', '🎉', '😮'];
const more = ['🔥', '👏', '🙏', '🤔', '👀', '✅', '🚀', '💯'];
const emojiStyle =
  'grid size-7.75 shrink-0 place-items-center rounded-sm p-0 text-xl leading-none focus:bg-accent data-[selected=true]:bg-accent';
export type ReactionAction = { emoji: string | null; onReact: (emoji: string | null) => void };
export function ReactionPicker({ emoji, onReact }: ReactionAction) {
  const [expanded, setExpanded] = useState(false);
  return (
    <DropdownMenu
      modal={false}
      onOpenChange={(open) => {
        if (!open) setExpanded(false);
      }}
    >
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon-xs" aria-label="Add reaction">
          <SmilePlus />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        side="bottom"
        align="start"
        sideOffset={6}
        className="w-auto min-w-0 p-1"
        aria-label="Choose reaction"
      >
        <DropdownMenuGroup className="flex gap-px">
          {common.map((item) => (
            <DropdownMenuItem
              key={item}
              className={emojiStyle}
              aria-label={`React ${item}`}
              data-selected={item === emoji}
              onSelect={() => onReact(item === emoji ? null : item)}
            >
              {item}
            </DropdownMenuItem>
          ))}
          <DropdownMenuItem
            className="grid size-7.75 place-items-center p-0"
            aria-label="More emoji"
            onSelect={(e) => {
              e.preventDefault();
              setExpanded(!expanded);
            }}
          >
            <Plus />
          </DropdownMenuItem>
        </DropdownMenuGroup>
        {expanded && (
          <DropdownMenuGroup className="mt-1 grid grid-cols-8 gap-px border-t pt-1">
            {more.map((item) => (
              <DropdownMenuItem
                key={item}
                className={emojiStyle}
                aria-label={`React ${item}`}
                data-selected={item === emoji}
                onSelect={() => onReact(item === emoji ? null : item)}
              >
                {item}
              </DropdownMenuItem>
            ))}
          </DropdownMenuGroup>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
export function ReactionMenu({
  emoji,
  onReact,
  context = true,
}: ReactionAction & { context?: boolean }) {
  const Sub = context ? ContextMenuSub : DropdownMenuSub;
  const Trigger = context ? ContextMenuSubTrigger : DropdownMenuSubTrigger;
  const Content = context ? ContextMenuSubContent : DropdownMenuSubContent;
  const Group = context ? ContextMenuGroup : DropdownMenuGroup;
  const Item = context ? ContextMenuItem : DropdownMenuItem;
  return (
    <Sub>
      <Trigger>
        <SmilePlus />
        React
      </Trigger>
      <Content aria-label="Choose reaction" className="w-auto min-w-0 p-1">
        {[common, more].map((row, index) => (
          <Group
            key={index}
            className={cn('grid gap-px', index ? 'mt-1 grid-cols-8 border-t pt-1' : 'grid-cols-6')}
          >
            {row.map((item) => (
              <Item
                key={item}
                className={emojiStyle}
                aria-label={`React ${item}`}
                data-selected={item === emoji}
                onSelect={() => onReact(item === emoji ? null : item)}
              >
                {item}
              </Item>
            ))}
          </Group>
        ))}
      </Content>
    </Sub>
  );
}
export function MessageReactions({
  reactions = [],
  actorId,
  own = false,
  onReact,
  inline = false,
}: {
  reactions?: MessageReaction[];
  actorId: string;
  own?: boolean;
  onReact?: (emoji: string | null) => void;
  inline?: boolean;
}) {
  if (!reactions.length) return null;
  const content = reactions.slice(0, 6).map((r) =>
    r.actor_kind === 'user' && r.actor_id === actorId && onReact ? (
      <button
        key={`${r.actor_kind}:${r.actor_id}`}
        type="button"
        aria-label={`Remove reaction ${r.emoji}`}
        title={`You reacted ${r.emoji}`}
        className="grid size-6 place-items-center rounded-full hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring"
        onClick={() => onReact(null)}
      >
        {r.emoji}
      </button>
    ) : (
      <span
        key={`${r.actor_kind}:${r.actor_id}`}
        role="img"
        aria-label={`${r.actor_kind === 'agent' ? 'Agent' : 'User'} reacted ${r.emoji}`}
        className="grid size-6 place-items-center"
      >
        {r.emoji}
      </span>
    ),
  );
  return inline ? (
    <span className="mt-2 flex w-fit items-center gap-0.5 rounded-full bg-muted px-1 text-base">
      {content}
    </span>
  ) : (
    <BubbleReactions
      align={own ? 'start' : 'end'}
      className="gap-0 px-1 py-0 text-base ring-[3px] ring-sidebar"
    >
      {content}
      {reactions.length > 6 && (
        <span className="px-1 text-xs text-muted-foreground">+{reactions.length - 6}</span>
      )}
    </BubbleReactions>
  );
}
