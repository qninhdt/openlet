import type { LiveEvent } from './agent-api.js';

export type StreamingItem = {
  id: string;
  agent: string;
  run: string;
  kind: 'text' | 'tool' | 'reasoning';
  name?: string;
  text: string;
};
export function reduceActivityStream(
  items: StreamingItem[],
  event: LiveEvent,
  root: string,
): StreamingItem[] {
  const agent = event.metadata?.openlet?.agentId;
  const run = event.metadata?.openlet?.runId;
  if (agent !== root || !run) return items;
  const text = event.type.startsWith('TEXT_MESSAGE_');
  const reasoning = event.type.startsWith('REASONING_MESSAGE_');
  const kind: StreamingItem['kind'] = reasoning ? 'reasoning' : text ? 'text' : 'tool';
  const id = text || reasoning ? event.messageId : event.toolCallId;
  if (!id) return items;
  if (
    event.type === 'TEXT_MESSAGE_START' ||
    event.type === 'REASONING_MESSAGE_START' ||
    event.type === 'TOOL_CALL_START'
  ) {
    if (items.some((item) => item.id === id && item.run === run && item.kind === kind))
      return items;
    return [
      ...items,
      {
        id,
        agent,
        run,
        kind,
        name: event.toolCallName,
        text: '',
      },
    ].slice(-40);
  }
  // A reconnect may begin inside a delta sequence; wait for canonical history.
  if (
    event.type === 'TEXT_MESSAGE_CONTENT' ||
    event.type === 'REASONING_MESSAGE_CONTENT' ||
    event.type === 'TOOL_CALL_ARGS'
  )
    return items.map((item) =>
      item.id === id && item.run === run && item.kind === kind
        ? { ...item, text: (item.text + (event.delta ?? '')).slice(0, 262144) }
        : item,
    );
  return items;
}
