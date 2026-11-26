import { expect, test } from '@playwright/test';
import { activityToolResult } from '../src/lib/agent-presentation.js';
import { reduceActivityStream, type StreamingItem } from '../src/lib/agent-stream.js';
import { scheduleTiming } from '../src/lib/schedule-presentation.js';
import type { ActivityEntry, LiveEvent } from '../src/lib/agent-api.js';

test('activity adapters render structured snapshots and tool errors', () => {
  const entry: ActivityEntry = {
    id: 'entry',
    agent_id: 'root',
    run_id: 'run',
    seq: 1,
    kind: 'tool_result',
    created_at: '2026-11-16T00:00:00Z',
    payload: { name: 'file_read', text: 'File not found', status: 'error' },
  };
  expect(activityToolResult(entry)).toBe('File not found');
  const adapt = (name: string, data: NonNullable<ActivityEntry['payload']['ui']>['data']) =>
    activityToolResult({ ...entry, payload: { name, ui: { version: 1, kind: name, data } } });
  expect(
    adapt('file_write', { path: '~/report.txt', storage_id: 'storage', node_id: 'node' }),
  ).toMatchObject({ file: { storage_id: 'storage', node_id: 'node', label: '~/report.txt' } });
  expect(
    adapt('send_message', {
      messages: [
        { content: 'The report is ready.', file_refs: [] },
        {
          content: '',
          file_refs: [
            { storage_id: 'storage', node_id: 'folder', label: 'Research', kind: 'folder' },
          ],
        },
      ],
    }),
  ).toMatchObject({
    messages: [
      { content: 'The report is ready.', fileRefs: [] },
      {
        content: '',
        fileRefs: [{ storage_id: 'storage', node_id: 'folder', label: 'Research', kind: 'folder' }],
      },
    ],
  });
  expect(adapt('file_read', { path: '~/report.txt', content: 'snapshot' })).toMatchObject({
    content: 'snapshot',
    file: undefined,
  });
  expect(
    adapt('glob', {
      items: [
        { path: '~/report.txt', kind: 'file', storage_id: 'storage', node_id: 'node' },
        { path: '~/folder', kind: 'directory', storage_id: 'storage', node_id: 'folder' },
      ],
    }),
  ).toMatchObject({
    items: [{ file: { storage_id: 'storage', node_id: 'node' } }, { file: undefined }],
  });
  expect(
    adapt('schedule_update', {
      spec: { every_seconds: 900, timezone: 'UTC' },
      previous_spec: { every_seconds: 600 },
      paused: true,
      content: 'Review files',
    }),
  ).toMatchObject({
    timing: 'Every 15 minutes',
    previousTiming: 'Every 10 minutes',
    status: 'Paused',
    content: 'Review files',
  });
  expect(
    adapt('hitl_ask', {
      title: 'Historical question',
      status: 'pending',
      payload: { questions: [{ id: 'q1', type: 'text', text: 'When?' }] },
    }),
  ).toMatchObject({
    request: {
      title: 'Historical question',
      status: 'pending',
      payload: { questions: [{ text: 'When?' }] },
    },
  });
  const items = [
    { source_kind: 'schedule', content: 'Run the report', schedule_title: 'Daily report' },
  ];
  expect(
    activityToolResult({
      ...entry,
      payload: { name: 'read_messages', ui: { version: 1, kind: 'messages', items } },
    }),
  ).toMatchObject({ inputItems: items });
  expect(
    adapt('inbox_history', {
      conversation: 'user:ethan',
      items: [
        {
          id: 'm1',
          direction: 'in',
          sender_name: 'Ethan Brooks#ethan',
          content: 'Please review Q4',
          created_at: '2026-11-25T09:41:00+00:00',
          file_refs: [{ storage_id: 's1', node_id: 'n1', label: 'q4.pdf' }],
          sources: [{ kind: 'web', title: 'Spec', url: 'https://example.com' }],
          reactions: [{ actor_kind: 'agent', actor_id: 'root', emoji: '👍' }],
          reply: { seq: 1, direction: 'out', content: 'Draft ready' },
        },
      ],
    }),
  ).toMatchObject({
    items: [
      {
        title: 'Replying to “Draft ready”',
        sender: 'Ethan Brooks#ethan',
        detail: 'Please review Q4',
        meta: '2026-11-25T09:41:00+00:00 · 👍',
        fileRefs: [{ storage_id: 's1', node_id: 'n1', label: 'q4.pdf' }],
        sources: [{ kind: 'web', title: 'Spec', url: 'https://example.com' }],
      },
    ],
  });
  expect(adapt('react_message', { emoji: '👍', content: 'Approved' })).toMatchObject({
    reaction: { emoji: '👍', content: 'Approved' },
  });
  expect(adapt('react_message', { emoji: null, content: 'Approved' })).toMatchObject({
    reaction: { emoji: null, content: 'Approved' },
  });
});

test('schedule timing uses supplied calendar fields and interval precision', () => {
  expect(scheduleTiming({ calendar: { day_of_week: [1, 5], hour: [9], minute: [30] } })).toBe(
    'Mon, Fri at 09:30',
  );
  expect(scheduleTiming({ every_seconds: 90 })).toBe('Every 90 seconds');
  expect(scheduleTiming({})).toBe('Timing unavailable');
});

test('activity deltas are root/run scoped, bounded and cleared on run.finished', () => {
  const event = (
    type: string,
    delta = 'Hello',
    run = 'run',
    agent = 'root',
    toolCallId?: string,
  ): LiveEvent => ({
    type,
    data: {
      agent_id: agent,
      run_id: run,
      delta,
      ...(toolCallId ? { tool_call_id: toolCallId } : {}),
    },
  });
  let items: StreamingItem[] = [];
  items = reduceActivityStream(items, event('stream.text_delta', 'Hello', 'run', 'child'), 'root');
  expect(items).toEqual([]);
  items = reduceActivityStream(items, event('stream.text_delta', 'Hello'), 'root');
  expect(items[0].text).toBe('Hello');
  items = reduceActivityStream(items, event('stream.text_delta', ' world'), 'root');
  expect(items[0].text).toBe('Hello world');
  const huge = event('stream.text_delta', 'x'.repeat(300000));
  expect(reduceActivityStream(items, huge, 'root')[0].text).toHaveLength(262144);
  for (let index = 0; index < 50; index++)
    items = reduceActivityStream(
      items,
      event('stream.tool_args_delta', '{}', 'run', 'root', String(index)),
      'root',
    );
  expect(items).toHaveLength(40);
  expect(items[0].id).toBe('10');
  expect(
    reduceActivityStream(
      items,
      { type: 'run.finished', data: { agent_id: 'root', run_id: 'run' } },
      'root',
    ),
  ).toEqual([]);
});

test('reasoning and text streams in the same run stay separate', () => {
  const event = (type: string, delta: string): LiveEvent => ({
    type,
    data: { agent_id: 'root', run_id: 'run', delta },
  });
  let items = reduceActivityStream([], event('stream.thinking_delta', 'Plan'), 'root');
  items = reduceActivityStream(items, event('stream.text_delta', 'Answer'), 'root');
  expect(items.map(({ kind, text }) => ({ kind, text }))).toEqual([
    { kind: 'reasoning', text: 'Plan' },
    { kind: 'text', text: 'Answer' },
  ]);
});

test('live activity keeps interleaved model parts in one turn with results and detail IDs', async () => {
  const { activityMessages } = await import('../src/lib/agent-activity-messages.js');
  const entry = (
    id: string,
    kind: ActivityEntry['kind'],
    payload: ActivityEntry['payload'],
    run_id = 'run',
  ): ActivityEntry => ({
    id,
    kind,
    payload,
    run_id,
    agent_id: 'root',
    seq: 1,
    created_at: '2026-11-16T00:00:00Z',
  });
  const entries = [
    entry('input', 'inbox_input', { text: 'Check files' }),
    entry('thought1', 'assistant', { reasoning: 'Find sources' }),
    entry('call1', 'tool_call', {
      tool_call_id: 'tool1',
      name: 'file_read',
      args: { path: '~/notes.md' },
    }),
    entry('result1', 'tool_result', {
      tool_call_id: 'tool1',
      name: 'file_read',
      text: 'Source',
      status: 'error',
    }),
    entry('thought2', 'assistant', { reasoning: 'Check another source' }),
    entry('call2', 'tool_call', { tool_call_id: 'tool2', name: 'file_read' }),
    entry('final', 'final_note', { reasoning: 'Conclude', text: 'Done' }),
    entry('compaction', 'compaction', { text: 'Summary' }),
    entry('next', 'assistant', { reasoning: 'New run' }, 'next-run'),
  ];
  const messages = activityMessages(entries);
  expect(messages.map((message) => message.id)).toEqual([
    'input',
    'thought1',
    'compaction',
    'next',
  ]);
  expect(messages[1].content).toMatchObject([
    { type: 'reasoning', text: 'Find sources' },
    { type: 'tool-call', toolCallId: 'tool1', result: 'Source', isError: true },
    { type: 'reasoning', text: 'Check another source' },
    { type: 'tool-call', toolCallId: 'tool2' },
    { type: 'reasoning', text: 'Conclude' },
    { type: 'text', text: 'Done' },
  ]);
  expect(messages[1].metadata?.custom?.entryIds).toEqual([
    'thought1',
    'call1',
    'result1',
    'thought2',
    'call2',
    'final',
  ]);
  const stream: StreamingItem[] = [
    { id: 'thought2', kind: 'reasoning', text: 'Duplicate', agent: 'root', run: 'run' },
    { id: 'tool2', kind: 'tool', text: '{}', name: 'file_read', agent: 'root', run: 'run' },
    { id: 'thought3', kind: 'reasoning', text: 'Live thought', agent: 'root', run: 'run' },
    { id: 'tool3', kind: 'tool', text: '{', name: 'file_read', agent: 'root', run: 'run' },
  ];
  const live = activityMessages(entries.slice(0, 6), stream);
  expect(live).toHaveLength(2);
  expect(live[1].status).toEqual({ type: 'running' });
  expect(live[1].id).toBe('thought1');
  expect(live[1].content).toMatchObject([
    { type: 'reasoning', text: 'Find sources' },
    { type: 'tool-call', toolCallId: 'tool1' },
    { type: 'reasoning', text: 'Check another source' },
    { type: 'tool-call', toolCallId: 'tool2' },
    { type: 'reasoning', text: 'Live thought' },
    { type: 'tool-call', toolCallId: 'tool3', argsText: '{' },
  ]);
  expect(
    activityMessages([
      entry('a', 'assistant', { reasoning: 'A' }),
      entry('b', 'assistant', { reasoning: 'B' }, 'other'),
    ]),
  ).toHaveLength(2);
});
