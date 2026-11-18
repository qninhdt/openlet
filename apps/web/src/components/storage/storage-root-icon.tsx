import { HardDrive, Users, MessageSquare } from 'lucide-react';
import { AgentAvatar } from '@/components/agent-avatar';
import type { StorageRoot } from './storage-context';

export function StorageRootIcon({ root }: { root: StorageRoot }) {
  if (root.isConversation) {
    return <MessageSquare className="size-5 shrink-0" />;
  }
  return root.agent ? (
    <AgentAvatar name={root.agent} className="size-5 shrink-0" />
  ) : root.name === 'Team' ? (
    <Users className="size-5 shrink-0" />
  ) : (
    <HardDrive className="size-5 shrink-0" />
  );
}
