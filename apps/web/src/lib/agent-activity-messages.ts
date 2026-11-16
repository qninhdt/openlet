import type { ThreadMessageLike } from '@assistant-ui/react';
import type { ActivityEntry } from './agent-api.js';
import type { StreamingItem } from './agent-stream.js';
import { activityToolResult } from './agent-presentation.js';

type Part = Exclude<ThreadMessageLike['content'], string>[number];

// History stores model output and tool calls separately; the UI needs an ordered assistant turn.
export function activityMessages(
  entries: ActivityEntry[],
  streaming: StreamingItem[] = [],
): ThreadMessageLike[] {
  const messages: ThreadMessageLike[] = [];
  const results = new Map(
    entries
      .filter((entry) => entry.kind === 'tool_result')
      .map((entry) => [entry.payload.tool_call_id, entry]),
  );
  let current:
    | {
        id: string;
        run: string;
        agent: string;
        parts: Part[];
        entryIds: string[];
        streaming: boolean;
      }
    | undefined;
  function flush() {
    if (!current) return;
    messages.push({
      id: current.id,
      role: 'assistant',
      content: current.parts,
      status: current.streaming ? { type: 'running' } : { type: 'complete', reason: 'stop' },
      metadata: { runId: current.run, custom: { entryIds: current.entryIds } },
    });
    current = undefined;
  }
  for (const entry of entries) {
    if (entry.kind === 'tool_result') continue;
    const boundary = entry.kind === 'inbox_input' || entry.kind === 'compaction';
    if (boundary || current?.run !== entry.run_id || current?.agent !== entry.agent_id) flush();
    current ??= {
      id: entry.id,
      run: entry.run_id,
      agent: entry.agent_id,
      parts: [],
      entryIds: [],
      streaming: false,
    };
    current.entryIds.push(entry.id);
    if (entry.payload.reasoning)
      current.parts.push({ type: 'reasoning', text: entry.payload.reasoning });
    if (entry.kind === 'tool_call') {
      const result = results.get(entry.payload.tool_call_id);
      if (result) current.entryIds.push(result.id);
      current.parts.push({
        type: 'tool-call',
        toolCallId: entry.payload.tool_call_id ?? entry.id,
        toolName: entry.payload.name ?? 'unknown',
        args: entry.payload.args ?? {},
        ...(result
          ? { result: activityToolResult(result), isError: result.payload.status === 'error' }
          : {}),
      });
    } else if (entry.payload.text) current.parts.push({ type: 'text', text: entry.payload.text });
    if (boundary || entry.kind === 'final_note') flush();
  }
  const committed = new Set(entries.flatMap((entry) => [entry.id, entry.payload.tool_call_id]));
  for (const item of streaming) {
    if (committed.has(item.id)) continue;
    if (current?.run !== item.run || current?.agent !== item.agent) flush();
    current ??= {
      id: `${item.kind}:${item.id}`,
      run: item.run,
      agent: item.agent,
      parts: [],
      entryIds: [],
      streaming: true,
    };
    current.streaming = true;
    current.parts.push(
      item.kind === 'tool'
        ? {
            type: 'tool-call',
            toolCallId: item.id,
            toolName: item.name ?? 'unknown',
            args: {},
            argsText: item.text,
          }
        : { type: item.kind === 'reasoning' ? 'reasoning' : 'text', text: item.text },
    );
  }
  flush();
  return messages;
}
