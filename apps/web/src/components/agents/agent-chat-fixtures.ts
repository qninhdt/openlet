import type { ChatMessage, HumanRequest } from '@/lib/agent-api';

export const demoSidebar: Record<
  string,
  { preview: string; updated_at: string; unread_count: number }
> = {
  atlas: {
    preview: 'Three things need you today: the launch plan, audience, and final approval.',
    updated_at: '2026-11-16T07:21:00Z',
    unread_count: 0,
  },
  scout: {
    preview: 'Two competitors changed their pricing. I’ve added the sources to the comparison.',
    updated_at: '2026-11-16T07:37:00Z',
    unread_count: 1,
  },
  forge: {
    preview: 'Updated release.ts. All checks passed.',
    updated_at: '2026-11-16T07:08:00Z',
    unread_count: 1,
  },
  pulse: {
    preview: 'Your Friday briefing is scheduled.',
    updated_at: '2026-11-16T07:12:00Z',
    unread_count: 1,
  },
};

// Addressed deliveries, deliberately separate from the internal activity fixtures.
export function demoChat(agent: string): ChatMessage[] {
  return [
    {
      id: `${agent}-chat-1`,
      role: 'user',
      content:
        'Can you coordinate Friday’s launch? Check the research and budget, then send me the plan before we publish.',
      created_at: '2026-11-16T09:00:00Z',
      read_at: '2026-11-16T09:00:02Z',
      reactions: [{ actor_kind: 'agent', actor_id: agent, emoji: '👍' }],
    },
    {
      id: `${agent}-chat-2`,
      role: 'assistant',
      content:
        'I’ve checked the research with Scout and the release checklist with Forge. The budget is $250 of $300. Nothing has been published.',
      created_at: '2026-11-16T09:04:00Z',
      reactions: [{ actor_kind: 'user', actor_id: 'demo-owner', emoji: '🎉' }],
    },
    {
      id: `${agent}-chat-3`,
      role: 'assistant',
      content:
        'Here’s the draft launch plan. I have a few questions about the audience and channels, plus a request to verify the original research. You can answer whenever you’re ready.',
      created_at: '2026-11-16T09:05:00Z',
      file_ids: ['launch-plan'],
      reply: {
        id: `${agent}-chat-1`,
        role: 'user',
        content: 'Can you coordinate Friday’s launch?',
      },
    },
    {
      id: `${agent}-chat-4`,
      role: 'user',
      content: 'Thanks. Keep working on the announcement while I check the plan.',
      created_at: '2026-11-16T09:06:00Z',
      read_at: '2026-11-16T09:06:03Z',
    },
    {
      id: `${agent}-chat-5`,
      role: 'assistant',
      content:
        'I’ll prepare the copy and keep publishing on hold. Your questions and access request can stay open while we work.',
      created_at: '2026-11-16T09:07:00Z',
    },
    {
      id: `${agent}-chat-6`,
      role: 'user',
      content:
        'Can we keep newsletter spend below $150? I’d rather leave a little room for the follow-up.',
      created_at: '2026-11-16T09:10:00Z',
      read_at: '2026-11-16T09:10:02Z',
    },
    {
      id: `${agent}-chat-7`,
      role: 'assistant',
      content:
        'Yes. Newsletter is $120, blog production is $80, and contingency is $50. That leaves $50 of the $300 cap unallocated.\n\n| Channel | Budget | Owner |\n| --- | --- | --- |\n| Newsletter | $120 | Linh |\n| Blog + changelog | $80 | Scout |\n| Contingency | $50 | You |',
      file_ids: ['budget'],
      created_at: '2026-11-16T09:12:00Z',
    },
    {
      id: `${agent}-chat-8`,
      role: 'user',
      content: 'Looks good. What did the review turn up?',
      created_at: '2026-11-16T09:14:00Z',
      read_at: '2026-11-16T09:14:02Z',
    },
    {
      id: `${agent}-chat-9`,
      role: 'assistant',
      content:
        'Two things need fixing before release:\n\n- The announcement says “everyone”; the agreed first audience is workspace owners.\n- Newsletter is missing from the release configuration.\n\nScout and Forge are fixing those now. The interview supports shared files and clear ownership, but it doesn’t support a measured productivity percentage.',
      created_at: '2026-11-16T09:16:00Z',
    },
    {
      id: `${agent}-chat-10`,
      role: 'user',
      content:
        'Remove the percentage claim. Please keep the original interview documents unchanged.',
      reply: {
        id: `${agent}-chat-9`,
        role: 'assistant',
        content:
          'The interview supports shared files and clear ownership, but it doesn’t support a measured productivity percentage.',
      },
      created_at: '2026-11-16T09:17:00Z',
      read_at: '2026-11-16T09:17:02Z',
    },
    {
      id: `${agent}-chat-11`,
      role: 'assistant',
      content:
        'Done. The draft now says:\n\n> Keep the conversation and its working files in one place, with a clear owner for the next step.\n\nThe source documents haven’t been edited. The request is for read-only access.',
      file_ids: ['announcement'],
      created_at: '2026-11-16T09:20:00Z',
    },
    {
      id: `${agent}-chat-12`,
      role: 'user',
      content: 'Can you give me a handover I can share with Linh?',
      created_at: '2026-11-16T09:23:00Z',
      read_at: '2026-11-16T09:23:02Z',
    },
    {
      id: `${agent}-chat-13`,
      role: 'assistant',
      content:
        '## Friday handover\n\n**Ready:** draft copy, corrected channel configuration, and the $250 budget.\n\n**Before publishing:** confirm the audience and channels in the questions below; approve the final wording after the quotation is checked.\n\n**Owners:** Linh reviews the announcement, Forge checks release files, and Scout verifies sources. I’ll bring their updates back to you.',
      file_ids: ['launch-plan', 'release'],
      created_at: '2026-11-16T09:25:00Z',
    },
    {
      id: `${agent}-chat-14`,
      role: 'user',
      content: 'The handover is clear. Please don’t send it to anyone until I’ve answered.',
      created_at: '2026-11-16T09:26:00Z',
      read_at: '2026-11-16T09:26:03Z',
    },
    {
      id: `${agent}-chat-15`,
      role: 'assistant',
      content:
        'Understood. I’ll keep the handover here and continue the checks. You can answer the questions whenever you’re ready.',
      created_at: '2026-11-16T09:27:00Z',
    },
  ];
}
export function demoRequests(agent: string): HumanRequest[] {
  return [
    {
      id: `${agent}-ask`,
      type: 'ask',
      title: 'A few decisions for Friday’s launch',
      recipient_user_id: 'demo-owner',
      requester_agent_id: agent,
      status: 'pending',
      created_at: '2026-11-16T09:05:00Z',
      payload: {
        questions: [
          {
            id: 'q1',
            text: 'Who should receive the announcement?',
            type: 'single_choice',
            options: [
              { id: 'o1', label: 'Everyone in the workspace' },
              { id: 'o2', label: 'Workspace owners' },
              { id: 'o3', label: 'Invited reviewers' },
            ],
          },
          {
            id: 'q2',
            text: 'Which channels should we use?',
            type: 'multiple_choice',
            options: [
              { id: 'o1', label: 'Blog and changelog' },
              { id: 'o2', label: 'Newsletter' },
              { id: 'o3', label: 'Social posts' },
            ],
          },
          { id: 'q3', text: 'Anything else I should keep in mind?', type: 'text' },
        ],
      },
    },
    {
      id: `${agent}-access`,
      type: 'approval',
      title: 'Read your research documents',
      recipient_user_id: 'demo-owner',
      requester_agent_id: agent,
      status: 'pending',
      created_at: '2026-11-16T09:05:05Z',
      payload: {
        role: 'reader',
        storage_id: 'Personal storage',
        reason:
          'I’d like to verify the original interview quotation before adding it to the announcement.',
      },
    },
  ];
}
