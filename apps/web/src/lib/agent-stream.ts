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
  // Support new Centrifugo leta:activity:{leta_id} stream.* & run.finished envelopes.
  if (event.type === 'run.finished') {
    const data = event.data ?? {};
    const agent = typeof data.agent_id === 'string' ? data.agent_id : '';
    const run = typeof data.run_id === 'string' ? data.run_id : '';
    if (agent !== root || !run) return items;
    return items.filter((item) => item.run !== run);
  }
  if (
    event.type === 'stream.thinking_delta' ||
    event.type === 'stream.text_delta' ||
    event.type === 'stream.tool_args_delta'
  ) {
    const data = event.data ?? {};
    const agent = typeof data.agent_id === 'string' ? data.agent_id : '';
    const run = typeof data.run_id === 'string' ? data.run_id : '';
    const delta = typeof data.delta === 'string' ? data.delta : '';
    if (agent !== root || !run || !delta) return items;
    const kind: StreamingItem['kind'] =
      event.type === 'stream.thinking_delta'
        ? 'reasoning'
        : event.type === 'stream.text_delta'
          ? 'text'
          : 'tool';
    const id =
      kind === 'tool'
        ? typeof data.tool_call_id === 'string' && data.tool_call_id
          ? data.tool_call_id
          : `tool:${run}`
        : `${kind}:${run}`;
    const exists = items.some((item) => item.id === id && item.run === run && item.kind === kind);
    if (!exists) {
      return [
        ...items,
        {
          id,
          agent,
          run,
          kind,
          name: typeof data.name === 'string' ? data.name : undefined,
          text: delta.slice(0, 262144),
        },
      ].slice(-40);
    }
    return items.map((item) =>
      item.id === id && item.run === run && item.kind === kind
        ? { ...item, text: (item.text + delta).slice(0, 262144) }
        : item,
    );
  }

  // Backward-compatible AG-UI stream reducer (used by unit tests & preview fixtures).
  const agent = event.metadata?.openlet?.agentId;
  const run = event.metadata?.openlet?.runId;
  if (agent !== root || !run) return items;
  if (event.type === 'RUN_FINISHED' || event.type === 'RUN_ERROR')
    return items.filter((item) => item.run !== run);
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
