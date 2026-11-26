import type { Json } from '@/lib/agent-api';
import { fileLink } from '@/lib/file-refs';
import { campaignReport } from './landing-demo-report';

export const channelCSV =
  'Channel,Visits,Signups,Activated,Spend\nBlog,1840,276,174,400\nNewsletter,1120,246,164,300\nSocial,2360,118,41,1200\n';
export const research = `# Launch research · Thursday review

## What we heard

| Interview | Role | Observation |
| --- | --- | --- |
| INT-014 | Operations lead | “I want one place to see which client approvals are still waiting.” |
| INT-019 | Studio owner | “The files need to stay with the conversation. I lose the thread when they are elsewhere.” |
| INT-023 | Product manager | “I need to review the right version, even if I come back a few days later.” |

## Recommendation

Lead with one project link for files, feedback and approvals. Show a studio owner handing a deliverable to a client; keep technical setup out of the opening message.

## Evidence

Interview notes INT-014, INT-019 and INT-023; channel data from the last campaign. These are sample records in this demo workspace.
`;
export const brief = `# Friday launch · review draft

**Owner:** Atlas · **Review:** Thursday 16:00 UTC · **Launch:** Friday 10:00 UTC

## Decision

Prioritise the newsletter and the blog. Hold the additional social budget until the activation issue is understood.

## Last campaign

| Channel | Visits | Signups | Activated | Cost / activation |
| --- | ---: | ---: | ---: | ---: |
| Blog | 1,840 | 276 | 174 | $2.30 |
| Newsletter | 1,120 | 246 | 164 | $1.83 |
| Social | 2,360 | 118 | 41 | $29.27 |
| **Total** | **5,320** | **640** | **379** | **$5.01** |

Newsletter activation is 66.7% of signups. Social brings the most traffic but only 10.8% of activated users.

## Release checklist

- [x] Scout: validate channel data and customer interviews
- [x] Nova: check conversion calculations
- [x] Forge: draft announcement and newsletter
- [ ] You: choose launch channels
- [ ] Atlas: publish after review

## Risks and follow-up

Do not increase social spend on traffic alone. Track activation 24 hours after launch and ask the team to review any channel below 50%.
`;
export const announcement = `# Your next client handoff, without the chase

The deliverable is ready. The approval is somewhere in a message thread. The latest file is in somebody’s inbox. Sound familiar?

Morrow gives your clients one place for project files, feedback and approvals. Share a project, invite the client, and keep the next decision beside the work.

## Three things to try

1. **Share one project link.** Files, delivery dates and the next approval stay together.
2. **Get feedback on the right version.** Comments stay attached to the work your client is reviewing.
3. **Know what is waiting.** See which deliverables are approved and which decision comes next.

## Newsletter subject options

- Your next client handoff, without the chase
- One project link. Fewer follow-up emails.
- Meet Morrow: a calmer way to work with clients

**Recommended:** Your next client handoff, without the chase

CTA: Create your first client project.
`;
const file = (node_id: string, label: string) => fileLink({ storage_id: 'team', node_id, label });
export const demoScenes: Record<
  string,
  {
    input: string;
    reasoning: string;
    progress: string;
    answer: string;
    tools: {
      at: number;
      duration?: number;
      name: string;
      args: Record<string, Json>;
      data: Json;
    }[];
  }
> = {
  atlas: {
    input:
      'Can you get Morrow’s Friday launch ready? Use the campaign CSV and customer interviews. Scout should check the evidence, Forge can handle the newsletter. I need a budget recommendation and something I can show Maya, not just notes.',
    reasoning:
      'The decision is where to spend, not which channel had the most visits. I need activation by channel, the cost per activated user, and interview evidence. I’ll ask Scout for the evidence and Forge for the newsletter. Nova will verify the arithmetic independently while Quill builds a visual report. The existing launch brief is an input, not proof that the launch is ready.',
    progress:
      'The channel check found a useful mismatch: social drove 44% of visits but only 11% of activations. I’m checking the recommendation against the interviews before finalising the brief.',
    answer: `## Friday’s launch review is ready

**Put the next campaign behind the newsletter and blog.** Keep social spend flat until its activation problem is understood.

| Channel | Activation / signup | Cost / activation | Decision |
| --- | ---: | ---: | --- |
| Newsletter | 66.7% | $1.83 | Prioritise |
| Blog | 63.0% | $2.30 | Keep investing |
| Social | 34.7% | $29.27 | Hold the increase |

Nova verified the calculations. The announcement leads with **files that stay with the conversation**, reflecting the interview notes.

Read the ${file('team-brief', 'launch review')} and ${file('team-announcement', 'announcement draft')}. The ${file('team-channels', 'source data')} is there if you want to check the numbers.

I made a visual ${file('team-report', 'campaign report')} for Maya, with the source figures beside the recommendation. The Monday check will watch activation after launch.

Choose the channels whenever you’re ready. Nothing has been published.`,
    tools: [
      {
        at: 1100,
        name: 'file_list',
        args: { path: '/mnt/team' },
        data: {
          items: [
            { name: 'Channel performance.csv', kind: 'file' },
            { name: 'Customer interviews.md', kind: 'file' },
            { name: 'Launch brief.md', kind: 'file' },
          ],
        },
      },
      {
        at: 3100,
        duration: 1300,
        name: 'file_read',
        args: { path: '/mnt/team/Channel performance.csv' },
        data: { content: channelCSV, start_line: 1 },
      },
      {
        at: 4900,
        duration: 650,
        name: 'send_message',
        args: {
          conversation: 'Scout',
          messages: [
            {
              content:
                'Verify activation rates and spend per activated user. Flag channels where traffic hides a weak conversion.',
            },
          ],
        },
        data: {
          target_name: 'Scout',
          messages: [
            {
              content:
                'Verify activation rates and spend per activated user. Flag channels where traffic hides a weak conversion.',
            },
          ],
        },
      },
      {
        at: 8200,
        duration: 2400,
        name: 'execute',
        args: {
          command: `python - <<'PY'
import csv
with open('/mnt/team/Channel performance.csv') as source:
    rows = list(csv.DictReader(source))
for row in rows:
    activated, signups, spend = (float(row[key]) for key in ('Activated', 'Signups', 'Spend'))
    print(f"{row['Channel']:<12} {activated / signups:.1%} activation  \u0024{spend / activated:.2f} / activation")
print('Total activated:', sum(int(row['Activated']) for row in rows))
PY`,
        },
        data: {
          content:
            'Blog         63.0% activation  $2.30 / activation\nNewsletter   66.7% activation  $1.83 / activation\nSocial       34.7% activation  $29.27 / activation\nTotal activated: 379',
        },
      },
      {
        at: 11600,
        duration: 1700,
        name: 'semantic_search',
        args: {
          query: 'Where do client files, feedback and approvals get separated?',
          paths: ['/mnt/team'],
        },
        data: {
          groups: [
            {
              path: '/mnt/team/Customer interviews.md',
              hits: [
                {
                  path: 'INT-019 · Studio owner',
                  text: 'The files need to stay with the conversation. I lose the thread when they are elsewhere.',
                },
                {
                  path: 'INT-014 · Operations lead',
                  text: 'I want one place to see which client approvals are still waiting.',
                },
              ],
            },
          ],
        },
      },
      {
        at: 19300,
        duration: 1500,
        name: 'file_write',
        args: { path: '/mnt/team/Launch brief.md', content: brief },
        data: {
          storage_id: 'team',
          node_id: 'team-brief',
          path: '/mnt/team/Launch brief.md',
          content: brief,
        },
      },
      {
        at: 21600,
        duration: 2200,
        name: 'file_write',
        args: { path: '/mnt/team/Campaign review.html', content: campaignReport },
        data: {
          storage_id: 'team',
          node_id: 'team-report',
          path: '/mnt/team/Campaign review.html',
          content: campaignReport,
        },
      },
      {
        at: 25300,
        duration: 900,
        name: 'schedule_create',
        args: {
          title: 'Post-launch channel review',
          content:
            'Compare activation by channel after launch. Flag any channel below 50% before increasing spend.',
          spec: { calendar: { day_of_week: [1], hour: [9], minute: [0] }, timezone: 'UTC' },
        },
        data: {
          title: 'Post-launch channel review',
          spec: { calendar: { day_of_week: [1], hour: [9], minute: [0] }, timezone: 'UTC' },
          target: 'Atlas',
          content:
            'Compare activation by channel after launch. Flag any channel below 50% before increasing spend.',
        },
      },
    ],
  },
  scout: {
    input:
      'Check the launch recommendation against our interview notes and the channel CSV. I need evidence and caveats, not a list of generic growth ideas.',
    reasoning:
      'I’ll separate what the interviews support from what the channel data can prove. The sample is small, so I should not turn three interviews into a claim about every customer. I can still check whether the proposed positioning matches their concrete requests.',
    progress:
      'The interviews support the shared-files message. They do not tell us why social activation is low — that needs a separate onboarding check.',
    answer: `## Evidence check

The recommendation is supported, with one caveat.

- **Newsletter:** 164 of 246 signups activated (66.7%). Strongest cost efficiency at $1.83 per activation.
- **Blog:** 174 of 276 activated (63.0%). Largest absolute activation count.
- **Social:** 41 of 118 activated (34.7%). High traffic alone does not justify more spend.

> “The files need to stay with the conversation. I lose the thread when they are elsewhere.”
> — INT-019, studio owner

**Caveat:** three interviews are directional evidence, not a representative survey. The CSV measures one campaign, so I would recheck the recommendation after the next launch.

I saved the findings with the ${file('team-research', 'interview notes')} and kept the ${file('team-channels', 'channel data')} unchanged.`,
    tools: [
      {
        at: 1100,
        name: 'file_read',
        args: { path: '/mnt/team/Customer interviews.md' },
        data: { content: research, start_line: 1 },
      },
      {
        at: 2800,
        name: 'file_read',
        args: { path: '/mnt/team/Channel performance.csv' },
        data: { content: channelCSV, start_line: 1 },
      },
      {
        at: 4800,
        name: 'semantic_search',
        args: { query: 'client files, feedback, review decisions' },
        data: {
          groups: [
            {
              path: '/mnt/team/Customer interviews.md',
              hits: [
                {
                  path: 'INT-023 · Product manager',
                  text: 'I need to review the right version, even if I come back a few days later.',
                },
              ],
            },
          ],
        },
      },
      {
        at: 8200,
        name: 'send_message',
        args: {
          conversation: 'Atlas',
          messages: [
            {
              content:
                'Newsletter + blog is supported. Three interviews are directional; social onboarding needs a separate check.',
            },
          ],
        },
        data: {
          target_name: 'Atlas',
          messages: [
            {
              content:
                'Newsletter + blog is supported. Three interviews are directional; social onboarding needs a separate check.',
            },
          ],
        },
      },
    ],
  },
  forge: {
    input:
      'Write Morrow’s announcement and newsletter for Friday. Use the interview notes and brand voice. Keep the newsletter below 180 words, lead with the client handoff problem, and give me three subject lines.',
    reasoning:
      'The clearest problem is losing client feedback between messages and files. I’ll make the opening about that, show three concrete actions, and keep infrastructure and usage claims out of the copy. The newsletter should have one clear next step.',
    progress:
      'The draft now opens with the user’s problem, includes three things to try, and ends with one CTA. I’ve also kept three subject lines for review.',
    answer: `## Draft for Friday

### Your next client handoff, without the chase

The deliverable is ready. The approval is somewhere in a message thread. The latest file is in somebody’s inbox. Sound familiar?

Morrow gives your clients one place for project files, feedback and approvals. Share a project, invite the client, and keep the next decision beside the work.

**Three things to try:**
1. Share one link for files, delivery dates and approvals.
2. Get feedback on the version your client is reviewing.
3. See what is waiting and what has been approved.

**CTA:** Create your first client project.

| Subject line | Use |
| --- | --- |
| Your next client handoff, without the chase | Recommended |
| One project link. Fewer follow-up emails. | More outcome-focused |
| Meet Morrow: a calmer way to work with clients | More product-focused |

The full ${file('team-announcement', 'announcement and newsletter')} is ready to edit. I left the launch time and channel selection to Atlas.`,
    tools: [
      {
        at: 1100,
        name: 'file_read',
        args: { path: '/mnt/team/Customer interviews.md' },
        data: { content: research },
      },
      {
        at: 2800,
        name: 'file_read',
        args: { path: '/mnt/team/Launch brief.md' },
        data: { content: brief },
      },
      {
        at: 4800,
        name: 'file_write',
        args: { path: '/mnt/team/Draft announcement.md', content: announcement },
        data: { content: announcement },
      },
      {
        at: 8200,
        name: 'send_message',
        args: {
          conversation: 'Atlas',
          messages: [
            {
              content:
                'Announcement + newsletter ready. Recommended subject: Your next client handoff, without the chase. No infrastructure or usage promises.',
            },
          ],
        },
        data: {
          target_name: 'Atlas',
          messages: [
            {
              content:
                'Announcement + newsletter ready. Recommended subject: Your next client handoff, without the chase.',
            },
          ],
        },
      },
    ],
  },
};
