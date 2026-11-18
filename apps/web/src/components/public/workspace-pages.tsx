import { useRef, useState } from 'react';
import { Link, useNavigate, useSearch } from '@tanstack/react-router';
import { useQueryClient } from '@tanstack/react-query';
import { ArrowRight, LoaderCircle, Users } from 'lucide-react';
import { BackendProvider, useBackend } from '@/lib/backend';
import { Button } from '@/components/ui/button';
import { siteAction } from './public-layout';
import { TransactionalPage } from './page-state';

export { WorkspacesPage } from '../workspace-manager';

export function JoinPage() {
  const { token } = useSearch({ from: '/join' });
  if (!token)
    return (
      <TransactionalPage
        title="Invitation missing"
        description="Open the full invitation link shared by your workspace owner."
      >
        <Button asChild className={`${siteAction} mt-7`}>
          <Link to="/workspaces">
            Your workspaces
            <ArrowRight />
          </Link>
        </Button>
      </TransactionalPage>
    );
  return (
    <BackendProvider>
      <AcceptInvitation token={token} />
    </BackendProvider>
  );
}
function AcceptInvitation({ token }: { token: string }) {
  const { api, actorId } = useBackend();
  const client = useQueryClient();
  const navigate = useNavigate();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const busy = useRef(false);
  return (
    <TransactionalPage
      title="Join your team"
      description="Accept this invitation to access the workspace. Sign in with the email address that received the invitation."
    >
      <div className="mt-7 space-y-4">
        {error && (
          <p role="alert" className="text-sm leading-6 text-destructive">
            {error}
          </p>
        )}
        <Button
          className={siteAction}
          disabled={pending}
          onClick={async () => {
            if (busy.current) return;
            busy.current = true;
            setPending(true);
            setError('');
            try {
              const member = await api!<{ workspaceId?: string }>('/v1/invitations:accept', {
                method: 'POST',
                body: JSON.stringify({ token }),
              });
              await client.invalidateQueries({ queryKey: ['workspaces', actorId] });
              if (member.workspaceId)
                await navigate({
                  to: '/app/$workspaceId',
                  params: { workspaceId: member.workspaceId },
                  replace: true,
                });
              else await navigate({ to: '/workspaces', replace: true });
            } catch {
              setError(
                'This invitation could not be accepted. Check that you’re using the invited email, or ask the workspace owner for a new link.',
              );
            } finally {
              busy.current = false;
              setPending(false);
            }
          }}
        >
          {pending ? (
            <LoaderCircle className="size-4 animate-spin" />
          ) : (
            <Users className="size-4" />
          )}
          {pending ? 'Joining…' : 'Accept invitation'}
        </Button>
        <p>
          <Link
            to="/workspaces"
            className="text-xs text-muted-foreground underline underline-offset-4"
          >
            Your workspaces
          </Link>
        </p>
      </div>
    </TransactionalPage>
  );
}
