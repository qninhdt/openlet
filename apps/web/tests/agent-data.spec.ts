import { expect, test } from '@playwright/test';
import { activityToolResult } from '../src/lib/agent-presentation.js';
import { reduceActivityStream, type StreamingItem } from '../src/lib/agent-stream.js';
import { scheduleTiming } from '../src/lib/schedule-presentation.js';
import type { ActivityEntry, LiveEvent } from '../src/lib/agent-api.js';

test('activity adapters preserve actual snapshots and legacy tool text', () => {
  const entry: ActivityEntry = {
    id: 'entry',
    agent_id: 'root',
    run_id: 'run',
    seq: 1,
    kind: 'tool_result',
    created_at: '2026-11-16T00:00:00Z',
    payload: { name: 'file_read', text: 'Legacy file contents' },
  };
  expect(activityToolResult(entry)).toBe('Legacy file contents');
  const adapt = (name: string, data: NonNullable<ActivityEntry['payload']['ui']>['data']) =>
    activityToolResult({ ...entry, payload: { name, ui: { version: 1, kind: name, data } } });
  expect(
    adapt('file_write', { path: '~/report.txt', storage_id: 'storage', node_id: 'node' }),
  ).toMatchObject({ file: { storage_id: 'storage', node_id: 'node', label: '~/report.txt' } });
  expect(
    adapt('inbox_send', {
      content: ':file[Report]{name=storage/node}',
      file_refs: [{ storage_id: 'storage', node_id: 'image', label: 'Photo', mime: 'image/png' }],
    }),
  ).toMatchObject({
    content: ':file[Report]{name=storage/node}',
    fileRefs: [{ storage_id: 'storage', node_id: 'image', label: 'Photo', mime: 'image/png' }],
  });
  expect(adapt('file_read', { path: '~/legacy.txt', content: 'snapshot' })).toMatchObject({
    content: 'snapshot',
    file: undefined,
  });
  expect(
    adapt('file_list', {
      items: [
        { path: '~/report.txt', kind: 'file', storage_id: 'storage', node_id: 'node' },
        { path: '~/folder', kind: 'directory', storage_id: 'storage', node_id: 'folder' },
      ],
    }),
  ).toMatchObject({
    items: [{ file: { storage_id: 'storage', node_id: 'node' } }, { file: undefined }],
  });
  expect(
    adapt('history_search', {
      entries: [{ seq: 4, kind: 'final_note', text_preview: 'Actual note' }],
    }),
  ).toMatchObject({ items: [{ title: '#4 · final note', detail: 'Actual note' }] });
  expect(
    adapt('box_get', {
      name: 'review',
      representative_agent_id: 'scout',
      letis: [
        { id: 'scout', name: 'Scout' },
        { id: 'forge', name: 'Forge' },
      ],
      edges: [{ agent_low_id: 'scout', agent_high_id: 'forge' }],
    }),
  ).toMatchObject({
    home: '~/.boxes/review/',
    representative: 'Scout',
    edges: [['Scout', 'Forge']],
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
      payload: { name: 'inbox_read', ui: { version: 1, kind: 'messages', items } },
    }),
  ).toMatchObject({ inputItems: items });
  expect(adapt('inbox_react', { emoji: '👍', content: 'Approved' })).toMatchObject({
    reaction: { emoji: '👍', content: 'Approved' },
  });
  expect(adapt('inbox_react', { emoji: null, content: 'Approved' })).toMatchObject({
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

test('activity deltas are root/run scoped, bounded and ignore reconnect orphans', () => {
  const event = (type: string, run = 'run', agent = 'root', id = 'message'): LiveEvent => ({
    type,
    messageId: id,
    delta: 'Hello',
    metadata: { openlet: { agentId: agent, runId: run } },
  });
  let items: StreamingItem[] = [];
  expect(reduceActivityStream(items, event('TEXT_MESSAGE_CONTENT'), 'root')).toEqual([]);
  items = reduceActivityStream(items, event('TEXT_MESSAGE_START'), 'root');
  expect(reduceActivityStream(items, event('TEXT_MESSAGE_START'), 'root')).toEqual(items);
  expect(reduceActivityStream(items, event('TEXT_MESSAGE_CONTENT', 'other'), 'root')).toEqual(
    items,
  );
  expect(
    reduceActivityStream(items, event('TEXT_MESSAGE_CONTENT', 'run', 'child'), 'root'),
  ).toEqual(items);
  items = reduceActivityStream(items, event('TEXT_MESSAGE_CONTENT'), 'root');
  expect(items[0].text).toBe('Hello');
  const huge = { ...event('TEXT_MESSAGE_CONTENT'), delta: 'x'.repeat(300000) };
  expect(reduceActivityStream(items, huge, 'root')[0].text).toHaveLength(262144);
  for (let index = 0; index < 50; index++)
    items = reduceActivityStream(
      items,
      event('TEXT_MESSAGE_START', 'run', 'root', String(index)),
      'root',
    );
  expect(items).toHaveLength(40);
  expect(items[0].id).toBe('10');
});

test('reasoning and answer streams with the same message ID stay separate', () => {
  const event = (type: string, delta = ''): LiveEvent => ({
    type,
    messageId: 'message',
    delta,
    metadata: { openlet: { agentId: 'root', runId: 'run' } },
  });
  let items = reduceActivityStream([], event('REASONING_MESSAGE_START'), 'root');
  items = reduceActivityStream(items, event('REASONING_MESSAGE_CONTENT', 'Plan'), 'root');
  items = reduceActivityStream(items, event('TEXT_MESSAGE_START'), 'root');
  items = reduceActivityStream(items, event('TEXT_MESSAGE_CONTENT', 'Answer'), 'root');
  expect(items.map(({ kind, text }) => ({ kind, text }))).toEqual([
    { kind: 'reasoning', text: 'Plan' },
    { kind: 'text', text: 'Answer' },
  ]);
  expect(reduceActivityStream(items, event('REASONING_MESSAGE_START'), 'root')).toEqual(items);
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
