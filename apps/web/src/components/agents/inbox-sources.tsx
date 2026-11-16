import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Field, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import type { HumanRequest, Json } from '@/lib/agent-api';
import { scheduleTiming } from '@/lib/schedule-presentation';
import { useAgentPreview } from './agent-preview';

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
  const [title, setTitle] = useState(schedule.title);
  const [content, setContent] = useState(schedule.content);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const detail = useQuery({
    queryKey: [...p.live.scope, 'inbox', 'schedule', schedule.id],
    queryFn: () => p.live.api!<ScheduleRecord>(`${p.live.path}/schedules/${schedule.id}`),
  });
  const value = detail.data ?? schedule;
  async function save(patch: Record<string, Json>) {
    setBusy(true);
    setError('');
    try {
      await p.live.api!(`${p.live.path}/schedules/${schedule.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ request_id: crypto.randomUUID(), ...patch }),
      });
      await p.live.refresh();
      await detail.refetch();
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Could not update schedule.');
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="space-y-5 p-3">
      <div>
        <h3 className="text-base font-medium">{value.title || 'Scheduled instruction'}</h3>
        <p className="mt-1 text-caption text-muted-foreground">
          {value.deleted_at ? 'Deleted' : value.paused ? 'Paused' : 'Active'} · {value.type}
        </p>
      </div>
      {(error || detail.error) && (
        <p role="alert" className="text-sm text-destructive">
          {error || detail.error?.message}
        </p>
      )}
      <dl className="space-y-3 text-sm">
        <div>
          <dt className="text-caption text-muted-foreground">Timing</dt>
          <dd className="mt-1 wrap-anywhere">{scheduleTiming(value.spec)}</dd>
        </div>
        {typeof value.spec.timezone === 'string' && (
          <div>
            <dt className="text-caption text-muted-foreground">Timezone</dt>
            <dd className="mt-1">{value.spec.timezone}</dd>
          </div>
        )}
        {value.target && (
          <div>
            <dt className="text-caption text-muted-foreground">Send to</dt>
            <dd className="mt-1">{value.target}</dd>
          </div>
        )}
        {(['starts_at', 'ends_at'] as const).map(
          (key) =>
            typeof value.spec[key] === 'string' && (
              <div key={key}>
                <dt className="text-caption text-muted-foreground">
                  {key === 'starts_at' ? 'Starts' : 'Ends'}
                </dt>
                <dd className="mt-1 tabular-nums">{new Date(value.spec[key]).toLocaleString()}</dd>
              </div>
            ),
        )}
      </dl>
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          void save({ title, content });
        }}
      >
        <Field>
          <FieldLabel htmlFor={`schedule-${schedule.id}`}>Title</FieldLabel>
          <Input
            id={`schedule-${schedule.id}`}
            maxLength={255}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </Field>
        <Field>
          <FieldLabel htmlFor={`instruction-${schedule.id}`}>Instruction</FieldLabel>
          <Textarea
            id={`instruction-${schedule.id}`}
            maxLength={32000}
            rows={6}
            value={content}
            onChange={(e) => setContent(e.target.value)}
          />
        </Field>
        <div className="flex flex-wrap gap-2">
          <Button
            type="submit"
            size="sm"
            disabled={
              busy ||
              !!value.deleted_at ||
              !content.trim() ||
              (title === value.title && content === value.content)
            }
          >
            Save schedule
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={busy || !!value.deleted_at}
            onClick={() => void save({ paused: !value.paused })}
          >
            {value.paused ? 'Resume schedule' : 'Pause schedule'}
          </Button>
        </div>
      </form>
      {!!value.upcoming?.length && (
        <div>
          <p className="mb-2 text-caption text-muted-foreground">Upcoming runs</p>
          <ol className="space-y-2 text-sm tabular-nums">
            {value.upcoming.map((time) => (
              <li key={time}>{new Date(time).toLocaleString()}</li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
export function RequestInspector({ request }: { request: HumanRequest }) {
  const p = useAgentPreview();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const detail = useQuery({
    queryKey: [...p.live.scope, 'inbox', 'request', request.id],
    queryFn: () => p.live.api!<HumanRequest>(`${p.live.path}/hitl-requests/${request.id}`),
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
      <p className="text-xs text-muted-foreground wrap-anywhere">
        Recipient: {value.recipient_user_id}
      </p>
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
