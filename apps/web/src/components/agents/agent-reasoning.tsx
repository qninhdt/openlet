import type { ComponentType } from 'react';
import { MessagePrimitive, type ToolCallMessagePartComponent } from '@assistant-ui/react';
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

const tools = agentToolRenderers as {
  by_name: Record<string, ToolCallMessagePartComponent>;
  Fallback: ToolCallMessagePartComponent;
};

export function AgentMessageParts({ Text }: { Text: ComponentType<{ text: string }> }) {
  return (
    <MessagePrimitive.Parts>
      {({ part }) => {
        switch (part.type) {
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
    </MessagePrimitive.Parts>
  );
}
