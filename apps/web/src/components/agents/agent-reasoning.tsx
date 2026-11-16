import type { ComponentType, PropsWithChildren } from 'react';
import {
  groupPartByType,
  MessagePrimitive,
  useAuiState,
  type ToolCallMessagePartComponent,
} from '@assistant-ui/react';
import { ChevronRight, LoaderCircle, TriangleAlert } from 'lucide-react';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { AgentMarkdown } from './agent-rich-content';
import { agentToolRenderers } from './agent-tools';

export function AgentReasoning({ text, streaming = false }: { text: string; streaming?: boolean }) {
  if (!text) return null;
  return (
    <div
      aria-busy={streaming || undefined}
      className="min-w-0 max-w-3xl py-1 text-sm text-muted-foreground italic"
      data-slot="agent-reasoning"
    >
      <AgentMarkdown text={text} />
    </div>
  );
}

function AgentSteps({
  children,
  indices,
  running,
}: PropsWithChildren<{ indices: readonly number[]; running: boolean }>) {
  const count = useAuiState(
    (s) => indices.filter((i) => s.message.content[i].type === 'tool-call').length,
  );
  const failed = useAuiState(
    (s) =>
      indices.filter((i) => {
        const part = s.message.content[i];
        return part.type === 'tool-call' && part.isError;
      }).length,
  );
  return (
    <Collapsible
      defaultOpen
      className="mb-1 grid w-full min-w-0 justify-items-start"
      data-slot="agent-tool-group"
    >
      <CollapsibleTrigger className="group/steps flex items-center gap-1.5 rounded-md py-1 text-caption text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">
        {running ? (
          <LoaderCircle className="size-3.5 animate-spin motion-reduce:animate-none" />
        ) : failed ? (
          <TriangleAlert className="size-3.5 text-destructive" />
        ) : null}
        <span>
          {count ? `${count} step${count === 1 ? '' : 's'}` : 'Thoughts'}
          {failed ? ` · ${failed} failed` : ''}
        </span>
        <ChevronRight className="size-3.5 transition-transform group-data-[state=open]/steps:rotate-90 motion-reduce:transition-none" />
      </CollapsibleTrigger>
      <CollapsibleContent className="ml-3 grid w-[calc(100%-12px)] min-w-0 gap-2.5 border-l pt-3 pb-1.5 pl-3">
        {children}
      </CollapsibleContent>
    </Collapsible>
  );
}

const groupBy = groupPartByType({
  reasoning: ['group-steps'],
  'tool-call': ['group-steps'],
  'tool-call:hitl_ask': [],
  'tool-call:hitl_request': [],
});
const tools = agentToolRenderers as {
  by_name: Record<string, ToolCallMessagePartComponent>;
  Fallback: ToolCallMessagePartComponent;
};

export function AgentMessageParts({ Text }: { Text: ComponentType<{ text: string }> }) {
  return (
    <MessagePrimitive.GroupedParts groupBy={groupBy} indicator="never">
      {({ part, children }) => {
        switch (part.type) {
          case 'group-steps':
            return (
              <AgentSteps indices={part.indices} running={part.status.type === 'running'}>
                {children}
              </AgentSteps>
            );
          case 'reasoning':
            return <AgentReasoning text={part.text} streaming={part.status.type === 'running'} />;
          case 'tool-call': {
            const Tool = tools.by_name[part.toolName] ?? tools.Fallback;
            return <Tool {...part} />;
          }
          case 'text':
            return <Text text={part.text} />;
          default:
            return null;
        }
      }}
    </MessagePrimitive.GroupedParts>
  );
}
