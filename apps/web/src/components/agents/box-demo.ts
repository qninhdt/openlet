import type { Workspace } from '@/lib/workspace-directory';
import type { BoxGraph, BoxAgent } from '@/lib/box-api';
import { agentAppearance } from '@/components/agent-appearance';

export function demoBoxGraph(workspace: Workspace): BoxGraph {
  const graph: BoxGraph = { agents: [], boxes: [], edges: [], schedules: [], roots: [] };
  workspace.agents.forEach((root, i) => {
    graph.roots.push(root.id);
    graph.agents.push({
      id: root.id,
      leta_id: root.id,
      box_id: null,
      name: root.name,
      title: root.role,
      appearance: root.appearance ?? agentAppearance(root.name),
      description: 'Coordinates the work and brings decisions back to you.',
      model_id: 'Claude Sonnet 4.5',
      status: i === 0 ? 'working' : 'idle',
    });
    if (i > 1) return;
    const box = `${root.id}-research`;
    const members: BoxAgent[] = [
      {
        id: `${box}-iris`,
        name: 'Iris',
        title: 'Reporter',
        status: 'working',
        tool_name: 'file_write',
        appearance: { shape: 'goutte', color: 'violet' },
      },
      {
        id: `${box}-milo`,
        name: 'Milo',
        title: 'Researcher',
        status: 'working',
        tool_name: 'file_search',
        appearance: { shape: 'galet', color: 'bleu' },
      },
      {
        id: `${box}-nova`,
        name: 'Nova',
        title: 'Researcher',
        status: i === 0 ? 'queued' : 'idle',
        appearance: { shape: 'triangle', color: 'turquoise' },
      },
    ].map(
      (member) =>
        ({
          ...member,
          leta_id: root.id,
          box_id: box,
          description: 'Checks source material and shares findings with the team.',
          model_id: 'Claude Sonnet 4.5',
          started_at: new Date(Date.now() - 42000).toISOString(),
          activity_kind: member.status === 'working' ? 'tool_call' : undefined,
        }) as BoxAgent,
    );
    graph.agents.push(...members);
    graph.boxes.push({
      id: box,
      leta_id: root.id,
      name: 'Market research',
      description: 'Compare the evidence and prepare a sourced launch briefing.',
      representative_agent_id: members[0].id,
      state: 'active',
    });
    graph.edges.push(
      ...members
        .slice(1)
        .map((m) => ({ box_id: box, agent_low_id: members[0].id, agent_high_id: m.id })),
    );
    graph.schedules.push({
      id: `${root.id}-briefing`,
      leta_id: root.id,
      creator_agent_id: root.id,
      target_agent_id: members[0].id,
      title: 'Morning briefing',
      content:
        'Review the shared research, check new sources and send the representative’s briefing to the parent agent.',
      type: 'calendar',
      spec: {
        timezone: 'Asia/Ho_Chi_Minh',
        calendar: { day_of_week: [1, 2, 3, 4, 5], hour: [9], minute: [0] },
      },
      paused: false,
    });
    if (i === 0) {
      const delivery = `${root.id}-delivery`;
      const id = `${delivery}-otto`;
      graph.boxes.push({
        id: delivery,
        leta_id: root.id,
        name: 'Release checks',
        description: 'Validate the release files before the launch.',
        representative_agent_id: id,
        state: 'active',
      });
      graph.agents.push({
        id,
        leta_id: root.id,
        box_id: delivery,
        name: 'Otto',
        title: 'Reviewer',
        appearance: { shape: 'capsule', color: 'orange' },
        description: 'Checks release files and reports any missing inputs.',
        model_id: 'GPT-5.4',
        status: 'error',
      });
      graph.schedules.push({
        id: `${root.id}-release`,
        leta_id: root.id,
        creator_agent_id: id,
        target_agent_id: id,
        title: 'Release check',
        content:
          'Validate the release configuration and shared budget. Report missing files to the representative.',
        type: 'interval',
        spec: { every_seconds: 3600, timezone: 'UTC' },
        paused: true,
      });
    }
  });
  return graph;
}
