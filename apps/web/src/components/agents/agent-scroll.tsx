import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { useAgentPreview } from './agent-preview';
import {
  MessageScrollerProvider,
  MessageScroller,
  MessageScrollerViewport,
  MessageScrollerButton,
  useMessageScroller,
} from '@/components/ui/message-scroller';

// Store only the viewport position; MessageScroller still owns following and anchoring.
export function useAgentScroll<T extends HTMLElement = HTMLDivElement>(key: string) {
  const { scrollPositions } = useAgentPreview();
  const [saved] = useState(() => scrollPositions.get(key));
  const ref = useRef<T>(null);
  useLayoutEffect(() => {
    const node = ref.current;
    if (saved && !saved.messageId && node) {
      node.scrollTop = saved.atEnd ? node.scrollHeight : saved.top;
      node.dispatchEvent(new Event('scroll', { bubbles: true }));
    }
    return () => {
      if (!node?.clientHeight) return;
      const top = node.getBoundingClientRect().top;
      const content = node.querySelector('[data-slot=message-scroller-content]');
      const anchor = Array.from(content?.children ?? []).find(
        (item) =>
          item instanceof HTMLElement &&
          item.dataset.messageId &&
          item.getBoundingClientRect().bottom > top,
      ) as HTMLElement | undefined;
      scrollPositions.set(key, {
        top: node.scrollTop,
        atEnd: node.scrollHeight - node.clientHeight - node.scrollTop <= 8,
        messageId: anchor?.dataset.messageId,
        offset:
          anchor && content
            ? anchor.getBoundingClientRect().top -
              top -
              parseFloat(getComputedStyle(content).paddingTop)
            : undefined,
      });
    };
  }, [saved, key, scrollPositions]);
  return {
    saved,
    defaultScrollPosition: saved?.atEnd === false ? ('start' as const) : ('end' as const),
    viewportProps: { ref },
  };
}

function RestoredViewport({
  scroll,
  children,
}: {
  scroll: ReturnType<typeof useAgentScroll<HTMLDivElement>>;
  children: ReactNode;
}) {
  const { scrollToMessage } = useMessageScroller();
  const [restoring, setRestoring] = useState(!!scroll.saved?.messageId && !scroll.saved.atEnd);
  useLayoutEffect(() => {
    const saved = scroll.saved;
    const messageId = saved?.messageId;
    if (!messageId || saved.atEnd) return;
    // Skipped content has estimated heights until its first layout after remounting.
    const frame = requestAnimationFrame(() => {
      scrollToMessage(messageId, { align: 'start', scrollMargin: saved.offset });
      setRestoring(false);
    });
    return () => cancelAnimationFrame(frame);
  }, [scroll.saved, scrollToMessage]);
  return (
    <MessageScrollerViewport
      {...scroll.viewportProps}
      className={
        restoring ? '[&_[data-slot=message-scroller-item]]:[content-visibility:visible]' : undefined
      }
    >
      {children}
    </MessageScrollerViewport>
  );
}

export function AgentMessageScroller({
  positionKey,
  children,
}: {
  positionKey: string;
  children: ReactNode;
}) {
  const scroll = useAgentScroll(positionKey);
  return (
    <MessageScrollerProvider autoScroll defaultScrollPosition={scroll.defaultScrollPosition}>
      <MessageScroller className="min-h-0 flex-1">
        <RestoredViewport scroll={scroll}>{children}</RestoredViewport>
        <MessageScrollerButton />
      </MessageScroller>
    </MessageScrollerProvider>
  );
}
