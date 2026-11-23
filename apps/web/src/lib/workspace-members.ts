import { useQuery } from '@tanstack/react-query';
import type { Account } from './account';
import { useBackend } from './backend';

type Member = { user: Account; role: string };

export function useWorkspaceMembers(workspace: string, enabled = true) {
  const { api, actorId } = useBackend();
  return useQuery({
    queryKey: ['workspace-members', actorId, workspace],
    enabled: !!api && enabled,
    staleTime: 60_000,
    queryFn: async () => {
      const members: Member[] = [];
      let token = '';
      do {
        const page = await api!<{ members?: Member[]; nextPageToken?: string }>(
          `/v1/workspaces/${workspace}/members?` +
            new URLSearchParams({ page_size: '100', page_token: token }),
        );
        members.push(...(page.members ?? []));
        token = page.nextPageToken ?? '';
      } while (token);
      return members;
    },
  });
}
