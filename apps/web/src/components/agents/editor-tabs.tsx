import { useId, useLayoutEffect, useRef, type ReactNode } from 'react';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { focusStyles } from '@/components/ui/styles';
import './editor-tabs.css';

export type EditorTab = {
  id: string;
  label: string;
  icon: ReactNode;
  title?: ReactNode;
  onClose?: () => void;
};

/** Port of OpenBot's header tabs and measured TabShape, separate from page/form Tabs. */
export function EditorTabs({
  label,
  items,
  selected,
  onSelect,
  children,
}: {
  label: string;
  items: EditorTab[];
  selected: string;
  onSelect: (id: string) => void;
  children?: ReactNode;
}) {
  const id = useId();
  const list = useRef<HTMLDivElement>(null);
  const shape = useRef<HTMLSpanElement>(null);
  useLayoutEffect(() => {
    const element = list.current;
    const fill = shape.current;
    if (!element || !fill) return;
    const place = () => {
      const active = element.querySelector<HTMLElement>('[aria-selected=true]');
      if (!active) return;
      const box = active.getBoundingClientRect();
      const bounds = element.getBoundingClientRect();
      const parent = fill.parentElement!.getBoundingClientRect();
      const left = Math.max(0, box.left - bounds.left);
      const right = Math.min(bounds.width, box.right - bounds.left);
      fill.style.left = `${left + bounds.left - parent.left}px`;
      fill.style.width = `${Math.max(0, right - left)}px`;
    };
    place();
    const observer = new ResizeObserver(place);
    observer.observe(element);
    for (const tab of element.querySelectorAll<HTMLElement>('[role=tab]')) observer.observe(tab);
    element.addEventListener('scroll', place, { passive: true });
    return () => {
      observer.disconnect();
      element.removeEventListener('scroll', place);
    };
  }, [selected, items.map((item) => item.id + item.label).join('|')]);
  return (
    <div className="relative isolate flex h-(--shell-header-height) min-w-0 flex-1 items-end gap-1 px-2">
      <span ref={shape} className="editor-tab-shape" aria-hidden="true" />
      <div
        ref={list}
        role="tablist"
        aria-label={label}
        className="relative flex h-full min-w-0 items-end overflow-x-auto overflow-y-hidden pt-1 scrollbar-none"
      >
        {items.map((item, index) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            id={`${id}-${item.id}`}
            aria-selected={selected === item.id}
            tabIndex={selected === item.id ? 0 : -1}
            className={cn(
              focusStyles,
              'group/editor-tab relative flex h-8 max-w-56 min-w-0 shrink-0 items-center gap-1.5 rounded-t-lg px-2 text-caption leading-4 text-muted-foreground hover:text-foreground aria-selected:text-foreground',
            )}
            aria-label={item.label}
            title={item.label}
            onClick={() => onSelect(item.id)}
            onAuxClick={(event) => {
              if (event.button === 1) {
                event.preventDefault();
                item.onClose?.();
              }
            }}
            onKeyDown={(event) => {
              if (event.key === 'Delete' && item.onClose) {
                event.preventDefault();
                item.onClose();
              }
              const next =
                event.key === 'ArrowRight'
                  ? (index + 1) % items.length
                  : event.key === 'ArrowLeft'
                    ? (index - 1 + items.length) % items.length
                    : event.key === 'Home'
                      ? 0
                      : event.key === 'End'
                        ? items.length - 1
                        : -1;
              if (next < 0) return;
              event.preventDefault();
              onSelect(items[next].id);
              list.current?.querySelectorAll<HTMLElement>('[role=tab]')[next]?.focus();
            }}
          >
            <span className="relative flex size-4 shrink-0 items-center justify-center [&>svg]:size-3.5">
              <span
                className={cn(
                  'flex items-center [&>svg]:size-3.5',
                  item.onClose &&
                    'group-hover/editor-tab:opacity-0 group-focus-visible/editor-tab:opacity-0',
                )}
              >
                {item.icon}
              </span>
              {item.onClose && (
                <span
                  aria-hidden="true"
                  title={`Close ${item.label}`}
                  className="absolute inset-0 flex items-center justify-center opacity-0 group-hover/editor-tab:opacity-100 group-focus-visible/editor-tab:opacity-100"
                  onPointerDown={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                  }}
                  onClick={(event) => {
                    event.stopPropagation();
                    item.onClose?.();
                  }}
                >
                  <X className="size-3.5" />
                </span>
              )}
            </span>
            {item.title ?? <span className="truncate">{item.label}</span>}
          </button>
        ))}
      </div>
      {children}
    </div>
  );
}
