import { Bot, Network, UserRound } from 'lucide-react';
import { AgentAvatar } from '@/components/agent-avatar';
import { useBackend } from '@/lib/backend';
import { cn } from '@/lib/utils';
import { useWorkspaceMembers } from '@/lib/workspace-members';
import { useAgentPreview } from './agent-preview';

type IdentityProps = {
  kind: 'agent' | 'user' | 'box';
  address?: string;
  name?: string;
  className?: string;
};

function PersonIdentity({ address, name, className }: IdentityProps) {
  const { workspace } = useAgentPreview();
  const { account } = useBackend();
  const { data } = useWorkspaceMembers(workspace.id, !!address);
  const member = address
    ? (data?.find(({ user }) => user.id === address || user.handle === address)?.user ??
      (account?.id === address || account?.handle === address ? account : undefined))
    : undefined;
  const label = member?.displayName || name || 'Workspace member';
  return (
    <span className={cn('inline-flex min-w-0 max-w-full items-center gap-1.5', className)}>
      {member || name ? (
        <AgentAvatar name={label} appearance={member?.appearance} className="size-5 shrink-0" />
      ) : (
        <UserRound aria-hidden className="size-4 shrink-0 text-muted-foreground" />
      )}
      <span className="min-w-0 wrap-anywhere">{label}</span>
    </span>
  );
}

export function ActivityIdentity({ kind, address, name, className }: IdentityProps) {
  const p = useAgentPreview();
  if (kind === 'user')
    return <PersonIdentity kind={kind} address={address} name={name} className={className} />;

  const agent =
    kind === 'agent' && address
      ? (p.graph.agents.find((agent) => agent.id === address || agent.handle === address) ??
        p.workspace.agents.find((agent) => agent.id === address))
      : undefined;
  const box =
    kind === 'box' && address
      ? p.graph.boxes.find((box) => box.id === address || box.handle === address)
      : undefined;
  const label = agent?.name || box?.name || name || (kind === 'box' ? 'Agent team' : 'Agent');
  const Icon = kind === 'box' ? Network : Bot;
  return (
    <span className={cn('inline-flex min-w-0 max-w-full items-center gap-1.5', className)}>
      {kind === 'agent' && (agent || name) ? (
        <AgentAvatar name={label} agentId={agent?.id} className="size-5 shrink-0" />
      ) : (
        <Icon aria-hidden className="size-4 shrink-0 text-muted-foreground" />
      )}
      <span className="min-w-0 wrap-anywhere">{label}</span>
    </span>
  );
}
