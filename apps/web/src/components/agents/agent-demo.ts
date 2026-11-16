import type { InputItem } from '@/lib/agent-api';
import type { ThreadMessageLike } from '@assistant-ui/react';
import { previewFiles } from './agent-preview';

import type { DemoItem, DemoToolResult } from '@/lib/agent-presentation';
export type { DemoItem, DemoToolResult } from '@/lib/agent-presentation';

type Json = string | number | boolean | null | Json[] | { [key: string]: Json };
const call = (
  id: string,
  toolName: string,
  args: Record<string, Json>,
  result: DemoToolResult,
) => ({
  type: 'tool-call' as const,
  toolCallId: id,
  toolName,
  args,
  result,
  isError: result.exitCode !== undefined && result.exitCode !== 0,
});
const text = (value: string) => ({ type: 'text' as const, text: value });
const reasoning = (value: string) => ({ type: 'reasoning' as const, text: value });
const user = (id: string, content: string): ThreadMessageLike => ({ id, role: 'user', content });
const answer = (id: string, content: ThreadMessageLike['content']): ThreadMessageLike => ({
  id,
  role: 'assistant',
  content,
  status: { type: 'complete', reason: 'stop' },
});
const owner = '10000000-0000-4000-8000-000000000001';
const scheduleId = '20000000-0000-4000-8000-000000000001';
const requestId = '30000000-0000-4000-8000-000000000001';
const members: DemoItem[] = [
  {
    title: 'Ninh',
    detail: 'Workspace owner · receives launch decisions',
    meta: 'Owner',
    status: 'Active',
  },
  {
    title: 'Linh',
    detail: 'Reviews announcement copy and channel budget',
    meta: 'Member',
    status: 'Active',
  },
];
const reviewers: DemoItem[] = [
  {
    title: 'Scout',
    detail: 'Check research sources and report unsupported claims.',
    meta: 'Representative',
    status: 'Done',
  },
  {
    title: 'Forge',
    detail: 'Check links, file paths and the release configuration.',
    meta: 'Reviewer',
    status: 'Done',
  },
];
const schedule = {
  title: 'Friday briefing',
  content:
    'Read the launch plan, summarize open blockers and send a short briefing. Ask before publishing anything.',
  when: { day: 'FRI', time: '09:00' },
  timing: 'Every Friday at 09:00',
  timezone: 'Asia/Ho_Chi_Minh',
  target: 'Pulse',
  status: 'Active',
  upcoming: ['Fri, Nov 20 · 09:00', 'Fri, Nov 27 · 09:00', 'Fri, Dec 4 · 09:00'],
};

const atlas: ThreadMessageLike[] = [
  user(
    'atlas-start',
    'We launch on Friday. Check last week’s decisions, split the review work and put together a launch plan. Do not publish anything yet.',
  ),
  answer('atlas-context', [
    reasoning('I’ll check the workspace context before looking up the launch decisions.'),
    call(
      'atlas-workspace',
      'workspace_get',
      {},
      {
        title: 'Atlas',
        home: '~',
        summary: 'Agent context',
        items: [{ title: 'Ninh', detail: 'Workspace owner', status: 'Active' }],
      },
    ),
    reasoning(
      'The workspace is confirmed. I’ll now check the recorded decisions and their source.',
    ),
    call(
      'atlas-history-search',
      'history_search',
      { query: 'launch Friday' },
      {
        items: [
          {
            title: 'Friday launch review',
            detail:
              'Keep the launch to three channels. The first announcement goes to workspace owners; broader rollout follows after feedback.',
            meta: 'Entry 184 · Nov 13 · 16:42',
          },
          {
            title: 'Budget and ownership',
            detail: 'The initial budget is capped at $300. Every channel needs a named owner.',
            meta: 'Entry 171 · Nov 12 · 11:08',
          },
        ],
      },
    ),
    call(
      'atlas-history-read',
      'history_read',
      { entry: 184, start_line: 1, limit: 40 },
      {
        title: 'Friday launch review',
        content:
          'Decision: the first announcement goes to workspace owners.\n\nUse the blog, newsletter and social posts. Keep the total budget under $300. The announcement must not imply the public rollout has already happened.\n\nPending: final copy approval and newsletter send time.',
        lineRange: 'Lines 1–7',
        summary: 'Entry 184 · Nov 13 · 16:42',
      },
    ),
    text(
      'Last week’s decisions are clear: **three channels, a $300 cap and an owners-first launch**. I’ll keep publishing separate from preparation.',
    ),
  ]),
  user(
    'atlas-delegate-user',
    'Have a small team review the plan. I want one person responsible for bringing their findings back.',
  ),
  answer('atlas-delegate', [
    call('atlas-members', 'workspace_member_list', {}, { items: members }),
    call(
      'atlas-box-list',
      'box_list',
      {},
      {
        items: [
          {
            title: 'copy-review-old',
            detail: 'An earlier wording experiment; no active work.',
            meta: '1 member',
            status: 'Active',
          },
        ],
      },
    ),
    call(
      'atlas-box-create',
      'box_create',
      {
        name: 'launch-review',
        description: 'Check the Friday launch before owner approval.',
        letis: [
          {
            name: 'Scout',
            description: 'Research reviewer',
            system_prompt:
              'Check source material. Report evidence and unresolved questions to Forge.',
          },
          {
            name: 'Forge',
            description: 'Release reviewer',
            system_prompt: 'Check files and release configuration. Coordinate with Scout.',
          },
        ],
        edges: [['Scout', 'Forge']],
        representative: 'Scout',
      },
      {
        title: 'launch-review',
        summary: 'Review team created',
        home: '~/.boxes/launch-review/',
        representative: 'Scout',
        items: reviewers.map((item) => ({ ...item, status: 'Ready' })),
        edges: [['Scout', 'Forge']],
        status: 'Active',
      },
    ),
    call(
      'atlas-inbox-send',
      'inbox_send',
      {
        to: 'launch-review',
        content:
          'Check sources, release files and channel ownership. Return a short list of blockers to me. Do not publish or schedule anything.',
      },
      {
        target: 'launch-review',
        status: 'Delivered',
        summary: 'Scout is the team representative.',
      },
    ),
    text(
      'The review team is ready. **Scout is responsible for reporting back**, with Forge checking the release details. Their work stays in a shared team directory.',
    ),
  ]),
  user('atlas-check-user', 'What came back? Please separate blockers from improvements.'),
  answer('atlas-review-results', [
    call(
      'atlas-inbox-list',
      'inbox_list',
      { unread_only: true },
      {
        items: [
          {
            title: 'launch-review',
            sender: 'Scout',
            detail: 'Two blockers found. The source notes and file checks are ready.',
            meta: '09:18 · 2 unread',
            status: 'Unread',
          },
        ],
      },
    ),
    call(
      'atlas-inbox-read',
      'inbox_read',
      { message: 42, unread_only: true },
      {
        items: [
          {
            title: 'Source review',
            sender: 'Scout',
            detail:
              'Three interviews support the storage and ownership claims. The draft says “available to everyone”; change that to “available to workspace owners”.',
            meta: '09:17',
          },
          {
            title: 'Release check',
            sender: 'Forge',
            detail:
              'Newsletter was missing from the release configuration. I have prepared the fix and a validation script. Budget is $250 / $300.',
            meta: '09:18',
          },
        ],
      },
    ),
    call(
      'atlas-box-get',
      'box_get',
      { box: 'launch-review', include_prompts: false },
      {
        title: 'launch-review',
        home: '~/.boxes/launch-review/',
        representative: 'Scout',
        items: reviewers,
        edges: [['Scout', 'Forge']],
        status: 'Active',
        summary: 'Both reviewers have completed their checks.',
      },
    ),
    text(
      '## Review findings\n\n| Priority | Finding | Owner |\n| --- | --- | --- |\n| Blocker | Announcement overstates the launch audience | Scout |\n| Blocker | Newsletter missing from release configuration | Forge |\n| Improvement | Shorten the opening paragraph | Linh |\n\nThe **$250 budget is within the $300 cap**. Neither blocker requires increasing spend.',
    ),
  ]),
  user(
    'atlas-plan-user',
    'Write the plan and give me the decisions I need to make. Clean up the old copy experiment too.',
  ),
  answer('atlas-plan-files', [
    call(
      'atlas-write-plan',
      'file_write',
      { path: '~/Launch plan.md', content: previewFiles[0].content },
      {
        fileId: 'launch-plan',
        summary: 'Created the launch plan',
        lineRange: `${previewFiles[0].content.trimEnd().split('\n').length} lines`,
      },
    ),
    call(
      'atlas-write-budget',
      'file_write',
      { path: '~/Launch budget.csv', content: previewFiles[3].content },
      { fileId: 'budget', summary: 'Created the channel budget', lineRange: '5 rows · $250 total' },
    ),
    call(
      'atlas-box-delete',
      'box_delete',
      { box: 'copy-review-old' },
      {
        title: 'copy-review-old',
        status: 'Archived',
        summary: 'Stopped the old team and moved its work directory to Trash.',
      },
    ),
    text(
      'The plan and budget are ready to review.\n\n- Scout corrects the audience wording.\n- Forge includes newsletter and reruns the file checks.\n- Pulse prepares the briefing after your choice of channels.\n\n**Nothing has been published.** I need your choices below before the next step.',
    ),
  ]),
  answer('atlas-sample-assistant', [
    call(
      'atlas-ask',
      'hitl_ask',
      {
        recipient_user_id: owner,
        title: 'Launch decisions',
        questions: [
          {
            text: 'Who should receive the launch announcement?',
            options: ['Everyone in the workspace', 'Workspace owners', 'Invited reviewers'],
          },
          {
            text: 'Which channels should the launch use?',
            multiple: true,
            options: ['Blog and changelog', 'Newsletter', 'Social posts'],
          },
          { text: 'Anything else I should keep in mind?' },
        ],
      },
      { status: 'Pending', title: 'Launch decisions' },
    ),
  ]),
];

const forge: ThreadMessageLike[] = [
  user(
    'forge-start',
    'Please check the launch files. Newsletter needs to be included, and the budget must stay under $300. Show me what changed.',
  ),
  answer('forge-inspect', [
    call(
      'forge-list',
      'file_list',
      { path: '~', depth: 2 },
      {
        summary: '6 files · 1 folder',
        items: [
          { title: 'drafts', detail: 'Working copies', kind: 'folder', meta: '2 files' },
          ...previewFiles.map((file) => ({
            title: file.name,
            detail: `~/${file.name}`,
            fileId: file.id,
            kind: 'file' as const,
            meta: `${new TextEncoder().encode(file.content).length} B`,
          })),
        ],
      },
    ),
    call(
      'forge-read',
      'file_read',
      { path: '~/release.ts', start_line: 1, limit: 80 },
      {
        fileId: 'release',
        content:
          'export const release = {\n  title: "A shared place for your work",\n  scheduledAt: "2026-11-20T10:00:00+07:00",\n  channels: ["blog"],\n};',
        lineRange: 'Lines 1–5',
        summary: 'typescript',
      },
    ),
    text(
      'The release file currently includes only the blog. I’ll add newsletter, then validate the budget and owners before calling this ready.',
    ),
  ]),
  user('forge-fix-user', 'Go ahead. Include the check output, including anything that fails.'),
  answer('forge-fix', [
    call(
      'forge-edit',
      'file_edit',
      {
        path: '~/release.ts',
        old_text: "channels: ['blog']",
        new_text: "channels: ['blog', 'newsletter']",
      },
      { fileId: 'release', summary: '1 replacement · 1 line added, 1 line removed' },
    ),
    call(
      'forge-write-check',
      'file_write',
      { path: '~/check_release.py', content: previewFiles[5].content },
      {
        fileId: 'check-release',
        summary: 'Created a validation script',
        lineRange: `${previewFiles[5].content.trimEnd().split('\n').length} lines`,
      },
    ),
    call(
      'forge-failed-check',
      'execute',
      { command: 'python check_release.py', cwd: '~' },
      {
        output:
          'Loading Launch budget.csv\nChecking UTF-8 input... OK\nChecking required columns... OK\nChecking owners... OK\n  Blog          Forge     $0\n  Newsletter    Pulse     $220\n  Social posts  Scout     $80\n  Contingency   Atlas     $50\nBudget: $350 / $300\nERROR: Budget exceeds limit: 350',
        exitCode: 1,
        duration: '0.18s',
      },
    ),
    text(
      'The first check failed: the newsletter line was still using an old **$220 estimate**, taking the total to $350. The approved amount in the launch notes is $120. I’ll correct that specific cell and rerun the same check.',
    ),
  ]),
  user('forge-recheck-user', 'Use the approved $120 figure. Keep the contingency allocation.'),
  answer('forge-recheck', [
    call(
      'forge-edit-budget',
      'file_edit',
      {
        path: '~/Launch budget.csv',
        old_text: 'Newsletter,Pulse,220,In review',
        new_text: 'Newsletter,Pulse,120,In review',
      },
      { fileId: 'budget', summary: 'Newsletter budget corrected · contingency retained' },
    ),
    call(
      'forge-success-check',
      'execute',
      { command: 'python check_release.py', cwd: '~' },
      {
        output:
          'Loading Launch budget.csv\nChecking UTF-8 input... OK\nChecking required columns... OK\nChecking owners... OK\n  Blog          Forge     $0\n  Newsletter    Pulse     $120\n  Social posts  Scout     $80\n  Contingency   Atlas     $50\nBudget: $250 / $300\nRemaining headroom: $50\nValidated 4 budget rows\nAll checks passed.',
        exitCode: 0,
        duration: '0.12s',
      },
    ),
    text(
      '## Ready for review\n\nNewsletter is now included and the budget check passes.\n\n| Check | Result |\n| --- | --- |\n| Channel owners | All assigned |\n| Budget | $250 / $300 |\n| Contingency | $50 retained |\n| Publishing | Still waiting for approval |\n\nOpen the files below to inspect or edit the final versions.',
    ),
  ]),
  answer('forge-sample-assistant', [
    text('Updated release.ts. All checks passed. **No publishing action was taken.**'),
  ]),
];

const scout: ThreadMessageLike[] = [
  user(
    'scout-start',
    'Review the launch announcement against our research. I need evidence for each claim, not a generic summary.',
  ),
  answer('scout-research', [
    call(
      'scout-search',
      'file_semantic_search',
      { query: 'shared files agent ownership context switching', paths: ['~'] },
      {
        items: [
          {
            title: 'Research notes.md',
            fileId: 'research',
            detail:
              '“I lose time finding which file an agent used. A shared place with clear ownership would help.” — Interview P03',
            meta: 'Section 2',
          },
          {
            title: 'Launch plan.md',
            fileId: 'launch-plan',
            detail:
              'The first release targets workspace owners. It does not promise general availability or dedicated computers.',
            meta: 'Lines 5–8',
          },
        ],
      },
    ),
    call(
      'scout-no-results',
      'file_semantic_search',
      { query: 'verified productivity improvement percentage', paths: ['~'] },
      { items: [], summary: 'No evidence for a measured productivity improvement.' },
    ),
    call(
      'scout-read-notes',
      'file_read',
      { path: '~/Research notes.md', start_line: 1, limit: 80 },
      {
        fileId: 'research',
        content: previewFiles[1].content,
        lineRange: `Lines 1–${previewFiles[1].content.trimEnd().split('\n').length}`,
        summary: 'markdown',
      },
    ),
    text(
      'Two claims are supported: **shared files** and **clear ownership**. I found no measured productivity result, so I would remove any percentage claim.\n\nThe original interview transcript is in your Personal storage. I need read-only access to verify the exact quotation.',
    ),
  ]),
  user(
    'scout-access-user',
    'Ask for read-only access. Do not request permission to edit my source documents.',
  ),
  answer('scout-request', [
    call(
      'scout-access',
      'hitl_request',
      {
        user_id: owner,
        role: 'viewer',
        reason: 'Verify the interview quotation used in the launch announcement.',
      },
      { status: 'Pending', title: 'Storage access request' },
    ),
  ]),
  user(
    'scout-copy-user',
    'Prepare the safer wording while we wait, and cancel the older duplicate request.',
  ),
  answer('scout-status', [
    call(
      'scout-hitl-list',
      'hitl_list',
      {},
      {
        items: [
          {
            title: 'Verify research sources',
            detail: 'Personal storage · read only',
            status: 'Pending',
            meta: 'Requested at 09:26',
          },
          {
            title: 'Earlier research access',
            detail: 'Duplicate request from the previous draft',
            status: 'Pending',
            meta: 'Requested at 08:40',
          },
        ],
      },
    ),
    call(
      'scout-hitl-get',
      'hitl_get',
      { request_id: requestId },
      {
        title: 'Verify research sources',
        status: 'Pending',
        target: 'Ninh',
        content: 'Read-only access to Personal storage to check the interview quotation.',
        summary: 'Waiting for a decision. No access has been granted.',
      },
    ),
    call(
      'scout-hitl-cancel',
      'hitl_cancel',
      {
        request_id: '30000000-0000-4000-8000-000000000002',
        reason: 'Duplicate request; the new one is limited to source verification.',
      },
      {
        title: 'Earlier research access',
        status: 'Cancelled',
        summary: 'Duplicate request cancelled. Existing grants are unchanged.',
      },
    ),
    call(
      'scout-write',
      'file_write',
      { path: '~/Announcement.md', content: previewFiles[4].content },
      {
        fileId: 'announcement',
        summary: 'Created the revised announcement',
        lineRange: `${previewFiles[4].content.trimEnd().split('\n').length} lines`,
      },
    ),
    text(
      '## Suggested wording\n\n> Your files, decisions and agents can now live in the same workspace.\n\nThis describes the capability without inventing a measured outcome or promising a wider launch. The quotation remains excluded until the source is verified.\n\nThe older duplicate access request is cancelled; the current read-only request is still waiting for your decision.',
    ),
  ]),
  answer('scout-sample-assistant', [
    text(
      'The announcement draft is ready. The only remaining research dependency is verification of the original interview quotation.',
    ),
  ]),
];

const pulse: ThreadMessageLike[] = [
  user(
    'pulse-start',
    'Set up a Friday briefing for the launch. First check what is already scheduled so we do not send it twice.',
  ),
  answer('pulse-audit', [
    call(
      'pulse-list',
      'schedule_list',
      {},
      {
        items: [
          {
            title: 'Friday briefing',
            time: '08:30',
            detail: 'Every Friday at 08:30 · Asia/Ho_Chi_Minh',
            status: 'Paused',
            meta: 'Pulse',
          },
          {
            title: 'Launch reminder test',
            time: '17:00',
            detail: 'One-time · Thu, Nov 19 at 17:00',
            status: 'Active',
            meta: 'Pulse',
          },
        ],
      },
    ),
    call(
      'pulse-get',
      'schedule_get',
      { schedule_id: scheduleId },
      {
        ...schedule,
        when: { day: 'FRI', time: '08:30' },
        timing: 'Every Friday at 08:30',
        status: 'Paused',
        upcoming: [],
      },
    ),
    text(
      'There is a paused briefing at **08:30**, plus a one-time test reminder. I’ll update the existing briefing rather than create a duplicate. What time should the real briefing run?',
    ),
  ]),
  user(
    'pulse-time-user',
    'Use 09:00 Vietnam time, every Friday. Include blockers and the budget. Delete the test reminder.',
  ),
  answer('pulse-change', [
    call(
      'pulse-update',
      'schedule_update',
      {
        schedule_id: scheduleId,
        paused: false,
        calendar: { day_of_week: [5], hour: [9], minute: [0] },
        timezone: 'Asia/Ho_Chi_Minh',
        content: schedule.content,
      },
      {
        ...schedule,
        previousTiming: 'Every Friday at 08:30 · paused',
        summary: 'Resumed and moved 30 minutes later',
      },
    ),
    call(
      'pulse-delete',
      'schedule_delete',
      { schedule_id: '20000000-0000-4000-8000-000000000002' },
      {
        title: 'Launch reminder test',
        status: 'Deleted',
        summary: 'Future test reminders stopped. Previously delivered messages remain.',
      },
    ),
    text(
      'The Friday briefing now runs at **09:00, Asia/Ho_Chi_Minh**. The test reminder is deleted. The briefing will report blockers and the current budget; it will not publish the announcement.',
    ),
  ]),
  user(
    'pulse-followup-user',
    'Also remind me to approve the announcement Thursday at 16:00. Just once.',
  ),
  answer('pulse-create', [
    call(
      'pulse-create-once',
      'schedule_create',
      {
        title: 'Approve launch announcement',
        content:
          'Ask the workspace owner to review Announcement.md and confirm the audience before Friday.',
        at: '2026-11-19T16:00:00+07:00',
        timezone: 'Asia/Ho_Chi_Minh',
      },
      {
        title: 'Approve launch announcement',
        when: { day: '19 NOV', time: '16:00' },
        timing: 'Once · Thu, Nov 19 at 16:00',
        timezone: 'Asia/Ho_Chi_Minh',
        target: 'Pulse',
        status: 'Active',
        content: 'Ask you to review Announcement.md and confirm the audience before Friday.',
        upcoming: ['Thu, Nov 19 · 16:00'],
        summary: 'One-time reminder created',
      },
    ),
    call(
      'pulse-empty-history',
      'history_search',
      { query: 'announcement already published' },
      {
        items: [],
        summary: 'No matching activity. There is no publication recorded in this conversation.',
      },
    ),
    text(
      'You now have two different reminders:\n\n| When | Purpose | Repeats |\n| --- | --- | --- |\n| Thursday, 16:00 | Approve the announcement | Once |\n| Friday, 09:00 | Review blockers and budget | Weekly |\n\nBoth use Vietnam time. The one-time reminder will not repeat next week.',
    ),
  ]),
  answer('pulse-sample-assistant', [
    text(
      'Your Friday briefing is scheduled. The Thursday approval reminder is separate, and the duplicate test reminder has been removed.',
    ),
  ]),
];

export const demoAttachments: Record<string, string[]> = {
  'atlas-plan-files': ['launch-plan', 'budget'],
  'forge-recheck': ['release', 'budget', 'check-release'],
  'scout-status': ['announcement', 'research'],
};
export function sampleMessages(id: string): ThreadMessageLike[] {
  const conversation =
    id === 'forge' ? forge : id === 'scout' ? scout : id === 'pulse' ? pulse : atlas;
  return [
    ...conversation,
    user(`${id}-batch`, 'New messages from Linh and Scout.'),
    answer(`${id}-batch-note`, [
      reasoning(
        'I’ll acknowledge the approved wording and keep the source link with the quotation. Publishing still needs the workspace owner’s approval.',
      ),
      call(
        `${id}-react`,
        'inbox_react',
        { message: 18, emoji: '👍' },
        {
          reaction: {
            emoji: '👍',
            content:
              'The revised intro is approved. Keep the launch limited to workspace owners and include the source link below the quotation.',
          },
        },
      ),
      text(
        'Linh has approved the wording. Scout found the original quotation; I’ll retain its source link and keep the source document unchanged.',
      ),
    ]),
    answer(`${id}-compaction`, [
      text(
        'Launch context retained: $300 cap, $250 planned spend, owners-first audience. Newsletter configuration corrected. Original research stays read-only. Audience and channel questions remain open; publishing is on hold.',
      ),
    ]),
    user(`${id}-scheduled`, 'Prepare the Friday briefing.'),
    answer(`${id}-briefing`, [
      reasoning(
        'I’ll bring the latest budget and release checks into one briefing, and keep the unanswered questions visible as pending decisions.',
      ),
      text(
        '## Friday briefing\n\nThe copy and release checks are ready. Newsletter is **$120** and the total remains **$250**.\n\nPublishing is still on hold until the audience and channels are confirmed. I’ll include any new review notes in the next briefing.',
      ),
    ]),
    user(`${id}-decision`, 'Read-only source access declined.'),
    answer(`${id}-decision-note`, [
      reasoning(
        'The source access request was declined. I’ll omit the unverified quotation and use the research already shared in this workspace.',
      ),
      text(
        'I’ll use only the research already shared with the workspace. I’ve left the unverified quotation out of the announcement.',
      ),
    ]),
  ];
}

export function demoActivityInputs(agent: string): Record<string, InputItem[]> {
  return {
    [`${agent}-batch`]: [
      {
        id: 'user-reaction',
        source_kind: 'user',
        source_name: 'You',
        input_type: 'reaction',
        silent: true,
        content: 'Reacted 🎉',
        input_payload: {
          actor: { kind: 'user', id: 'demo-owner' },
          target: {
            message_id: `${agent}-chat-2`,
            kind: 'outgoing',
            content: 'The budget is $250 of $300. Nothing has been published.',
          },
          previous_emoji: null,
          emoji: '🎉',
        },
      },
      {
        id: 'linh-preview',
        source_kind: 'user',
        source_name: 'Linh',
        content: 'Please use the revised intro…',
        preview: true,
        presented: false,
      },
      {
        id: 'linh-message',
        source_kind: 'user',
        source_name: 'Linh',
        content:
          'The revised intro is approved. Keep the launch limited to workspace owners and include the source link below the quotation.',
        preview: true,
        reactions: [{ actor_kind: 'agent', actor_id: agent, emoji: '👍' }],
      },
      {
        id: 'scout-message',
        source_kind: 'agent',
        source_name: 'Scout',
        content:
          'Verified the quotation in Research notes.md. The interview supports shared files and clear ownership. No source supports a productivity percentage.',
        preview: true,
      },
    ],
    [`${agent}-scheduled`]: [
      {
        source_kind: 'schedule',
        schedule_title: 'Friday launch briefing',
        scheduled_at: '2026-11-20T02:00:00Z',
        content:
          'Prepare the Friday briefing: summarize completed reviews, remaining decisions and the approved budget. Do not publish or send anything to external recipients.',
      },
    ],
    [`${agent}-decision`]: [
      {
        source_kind: 'hitl',
        request_title: 'Read your research documents',
        request_type: 'approval',
        content: 'Read-only access declined.',
        decision: { status: 'denied' },
        request_payload: { role: 'reader', storage_id: 'Personal storage' },
      },
    ],
  };
}

export function letiMessages(id: string, recipient = 'root'): ThreadMessageLike[] {
  return [
    user(
      `${id}-assignment`,
      'Check the launch evidence and share the findings with the representative.',
    ),
    answer(`${id}-research`, [
      reasoning(
        'I’ll check the shared notes first, verify which claims have evidence, and keep source references with the findings.',
      ),
      call(
        `${id}-search`,
        'file_semantic_search',
        { query: 'shared file ownership', paths: ['~'] },
        {
          items: [
            {
              title: 'Research notes.md',
              fileId: 'research',
              detail:
                '“I lose time finding which file an agent used. A shared place with clear ownership would help.” — Interview P03',
              meta: 'Shared files and ownership',
            },
            {
              title: 'Launch plan.md',
              fileId: 'launch-plan',
              detail:
                'The first release targets workspace owners. Broader availability is a separate decision.',
              meta: 'Audience',
            },
          ],
        },
      ),
      reasoning(
        'The search found the relevant notes. I’ll read the original passage before summarizing it.',
      ),
      call(
        `${id}-read`,
        'file_read',
        { path: '~/Research notes.md' },
        { fileId: 'research', content: previewFiles[1].content, summary: 'markdown' },
      ),
      text(
        'Shared files and clear ownership are supported by the notes. There is no measured productivity improvement; percentage claims should be omitted.',
      ),
    ]),
    user(
      `${id}-teammate`,
      'Keep the announcement limited to workspace owners. The budget is $250 of the $300 cap.',
    ),
    answer(`${id}-draft`, [
      reasoning(
        'The audience and budget are clear. I can now send a sourced summary without waiting for publication approval.',
      ),
      call(
        `${id}-write`,
        'file_write',
        { path: '~/Launch plan.md', content: previewFiles[0].content },
        { fileId: 'launch-plan', content: previewFiles[0].content, summary: 'markdown' },
      ),
      call(
        `${id}-send`,
        'inbox_send',
        {
          to: recipient,
          content:
            'The launch evidence is checked. Use shared files and clear ownership; omit percentage claims. Budget stays at $250 and the audience is workspace owners.',
        },
        {
          items: [
            {
              title: recipient,
              detail:
                'The launch evidence is checked. Use shared files and clear ownership; omit percentage claims.',
            },
          ],
        },
      ),
      text(
        'The source references are in the launch plan. I’ve sent the findings to the representative.',
      ),
    ]),
    answer(`${id}-compaction`, [
      text(
        'Evidence review retained: shared files and clear ownership are supported. No measured productivity result. Owners-first audience; $250 budget. Findings sent to the representative.',
      ),
    ]),
    user(`${id}-scheduled`, 'Review new research before the morning briefing.'),
    answer(`${id}-follow-up`, [
      reasoning(
        'I’ll check for new evidence before changing the conclusions, then report only the changes.',
      ),
      text(
        'The shared notes contain no additional interviews. The earlier findings still hold; no new claims were added.',
      ),
    ]),
  ];
}
export function letiInputs(id: string, parent: string, peer = 'Milo'): Record<string, InputItem[]> {
  return {
    [`${id}-assignment`]: [
      {
        id: `${id}-input-1`,
        source_kind: 'agent',
        source_name: parent,
        content: 'Check the launch evidence and share the findings with the representative.',
      },
    ],
    [`${id}-teammate`]: [
      {
        id: `${id}-input-2`,
        source_kind: 'agent',
        source_name: peer,
        content:
          'Keep the announcement limited to workspace owners. The budget is $250 of the $300 cap.',
      },
    ],
    [`${id}-scheduled`]: [
      {
        id: `${id}-input-3`,
        source_kind: 'schedule',
        schedule_title: 'Morning briefing',
        content: 'Review new research before the morning briefing.',
        scheduled_at: '2026-11-16T02:00:00Z',
      },
    ],
  };
}
