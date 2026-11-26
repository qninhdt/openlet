import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import type { HumanRequest, Json } from '@/lib/agent-api';
import { scheduleTiming } from '@/lib/schedule-presentation';
import { useAgentPreview } from './agent-preview';
import { AgentMarkdown } from './agent-rich-content';
import { ActivityIdentity } from './activity-identity';

export type ScheduleRecord = {
  id: string;
  title: string;
  content: string;
  type: string;
  spec: Record<string, Json>;
  paused: boolean;
  deleted_at: string | null;
  created_at: string;
  upcoming?: string[];
  target?: string;
};
export function ScheduleInspector({ schedule }: { schedule: ScheduleRecord }) {
  const p = useAgentPreview();
  const detail = useQuery({
    queryKey: [...p.live.scope, 'inbox', 'schedule', schedule.id],
    queryFn: () => p.live.api!<ScheduleRecord>(`${p.live.path}/schedules/${schedule.id}`),
  });
  const value = detail.data ?? schedule;
  return (
    <section className="flex flex-col gap-4 p-3">
      <h3 className="text-base font-medium">{value.title || 'Scheduled instruction'}</h3>
      {detail.error && (
        <p role="alert" className="text-sm text-destructive">
          {detail.error.message}
        </p>
      )}
      <p className="text-sm text-muted-foreground">{scheduleTiming(value.spec)}</p>
      <AgentMarkdown text={value.content} />
    </section>
  );
}
export function RequestInspector({ request }: { request: HumanRequest }) {
  const p = useAgentPreview();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const detail = useQuery({
    queryKey: [...p.live.scope, 'inbox', 'request', request.id],
    queryFn: () => p.live.api!<HumanRequest>(`/v1/hitl-requests/${request.id}`),
  });
  const value = detail.data ?? request;
  return (
    <div className="space-y-4 p-3">
      <div>
        <h3 className="text-base font-medium">{value.title}</h3>
        <p className="mt-1 text-caption capitalize text-muted-foreground">
          {value.type === 'ask' ? 'Question' : 'Access request'} · {value.status}
          {value.status === 'accepted' ? ` · ${value.outcome?.status ?? 'Applying access…'}` : ''}
        </p>
      </div>
      <ActivityIdentity kind="user" address={value.recipient_user_id} className="text-caption" />
      {value.payload.questions?.map((q) => (
        <div key={q.id}>
          <p className="text-sm font-medium">{q.text}</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {value.response?.answers?.[q.id]?.text ??
              (q.options
                ?.filter(
                  (o) =>
                    o.id === value.response?.answers?.[q.id]?.option_id ||
                    value.response?.answers?.[q.id]?.option_ids?.includes(o.id),
                )
                .map((o) => o.label)
                .join(', ') ||
                'No answer yet')}
          </p>
        </div>
      ))}
      {value.type === 'approval' && (
        <>
          <p className="text-sm leading-relaxed">{value.payload.reason}</p>
          <p className="text-sm">
            {value.payload.role === 'editor' ? 'Read and write' : 'Read only'} ·{' '}
            {value.payload.storage_id}
          </p>
        </>
      )}
      <p className="text-caption text-muted-foreground">
        Only the addressed person can answer in their chat.
      </p>
      {(error || detail.error) && (
        <p role="alert" className="text-sm text-destructive">
          {error || detail.error?.message}
        </p>
      )}
      {value.status === 'pending' && (
        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setError('');
            try {
              await p.live.api!(`${p.live.path}/hitl-requests/${value.id}/cancel`, {
                method: 'POST',
              });
              await p.live.refresh();
              await detail.refetch();
            } catch (error) {
              setError(error instanceof Error ? error.message : 'Could not cancel request.');
            } finally {
              setBusy(false);
            }
          }}
        >
          Cancel request
        </Button>
      )}
    </div>
  );
}
