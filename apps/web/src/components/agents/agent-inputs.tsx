import {
  CalendarClock,
  Inbox,
  Bell,
  MessageCircleQuestion,
  ShieldCheck,
  SmilePlus,
  BellOff,
} from 'lucide-react';
import { Bubble, BubbleContent } from '@/components/ui/bubble';
import type { InputItem, Json } from '@/lib/agent-api';
import { MessagePreview } from './message-preview';
import { MessageFiles } from './message-files';
import { AgentMarkdown } from './agent-rich-content';
import { MessageReactions } from './message-reactions';
import { useAgentPreview } from './agent-preview';
import { ActivityIdentity } from './activity-identity';

function record(value: Json | undefined): Record<string, Json> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function PersonInput({ item }: { item: InputItem }) {
  const p = useAgentPreview();
  return (
    <article
      data-input={item.preview ? 'notification' : 'message'}
      className="flex min-w-0 gap-2 py-1"
    >
      <div className="min-w-0 flex-1">
        <div className="mb-1.5 flex items-center gap-2 text-caption">
          <ActivityIdentity
            kind={item.source_kind === 'user' ? 'user' : 'agent'}
            address={item.source_id ?? item.source_handle}
            name={item.source_name}
            className="font-medium"
          />
          {item.preview && (
            <Bell aria-label="Notification" className="size-3 text-muted-foreground" />
          )}
          {item.presented === false && (
            <span className="text-xs text-muted-foreground">Superseded</span>
          )}
        </div>
        <div
          className={
            item.preview
              ? 'text-caption leading-relaxed text-muted-foreground'
              : 'text-sm leading-relaxed'
          }
        >
          <AgentMarkdown text={item.content} sources={item.sources} />
          {!item.preview && <MessageFiles references={item.file_refs} />}
          <MessageReactions reactions={item.reactions} actorId={p.actorId} inline />
        </div>
      </div>
    </article>
  );
}

function ScheduleInput({ item }: { item: InputItem }) {
  const due = item.scheduled_at ? new Date(item.scheduled_at) : null;
  return (
    <article data-input="schedule" className="flex min-w-0 gap-3 py-1">
      <div className="flex w-12 shrink-0 flex-col items-center self-start overflow-hidden rounded-lg border border-current/20 text-center">
        {due ? (
          <>
            <span className="w-full bg-muted py-1 text-[10px] font-medium uppercase">
              {due.toLocaleDateString('en', { month: 'short' })}
            </span>
            <span className="py-1 text-xl font-medium tabular-nums">{due.getDate()}</span>
          </>
        ) : (
          <CalendarClock className="m-3 size-5" />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <h3 className="text-sm font-medium">{item.schedule_title ?? 'Scheduled instruction'}</h3>
        {due && (
          <time dateTime={item.scheduled_at!} className="mt-1 block text-xs text-muted-foreground">
            {due.toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' })}
          </time>
        )}
        <div className="mt-3 text-sm leading-relaxed wrap-anywhere">
          <AgentMarkdown text={item.content} />
        </div>
      </div>
    </article>
  );
}

function DecisionInput({ item }: { item: InputItem }) {
  const ask = item.request_type === 'ask';
  const Icon = ask ? MessageCircleQuestion : ShieldCheck;
  const status = String(item.decision?.status ?? '');
  const answers = record(record(item.decision?.response).answers);
  const outcome = record(item.decision?.outcome);
  return (
    <article data-input={ask ? 'answers' : 'request'} className="min-w-0">
      <header className="flex items-center gap-2 pb-2">
        <Icon className="size-4 shrink-0" />
        <h3 className="min-w-0 flex-1 text-sm font-medium">
          {item.request_title ?? (ask ? 'Answers received' : 'Access request')}
        </h3>
        <span className="text-caption capitalize text-muted-foreground">
          {status === 'denied' ? 'Declined' : status}
        </span>
      </header>
      {ask ? (
        <dl className="divide-y divide-current/15">
          {item.request_payload?.questions?.map((q) => {
            const answer = record(answers[q.id]);
            const selected = Array.isArray(answer.option_ids)
              ? answer.option_ids
              : [answer.option_id];
            return (
              <div key={q.id} className="py-3">
                <dt className="text-caption text-muted-foreground">{q.text}</dt>
                <dd className="mt-1.5 text-sm">
                  {typeof answer.text === 'string'
                    ? answer.text || 'No answer'
                    : q.options
                        ?.filter((o) => selected.includes(o.id))
                        .map((o) => o.label)
                        .join(', ') || 'No selection'}
                </dd>
                {typeof answer.note === 'string' && answer.note && (
                  <dd className="mt-1 text-caption">{answer.note}</dd>
                )}
              </div>
            );
          })}
        </dl>
      ) : (
        <div className="space-y-2 pt-1 text-sm">
          <p>
            {item.request_payload?.role === 'editor' ? 'Read and write' : 'Read only'}
            {item.request_payload?.storage_id && <> · {item.request_payload.storage_id}</>}
          </p>
          {status === 'accepted' && (
            <p className="text-caption text-muted-foreground">
              {outcome.status === 'granted'
                ? 'Access granted'
                : outcome.status === 'skipped'
                  ? `Access not granted${outcome.reason ? `: ${String(outcome.reason).replaceAll('_', ' ')}` : ''}`
                  : 'Applying access…'}
            </p>
          )}
          {item.request_payload?.reason && (
            <p className="leading-relaxed">{item.request_payload.reason}</p>
          )}
        </div>
      )}
    </article>
  );
}

export function InputMessage({ item }: { item: InputItem }) {
  return item.input_type === 'reaction' && item.input_payload ? (
    <article data-input="reaction" className="flex min-w-0 gap-3 py-1">
      <span className="grid size-8 shrink-0 place-items-center rounded-full bg-muted text-xl">
        {item.input_payload.emoji ?? <SmilePlus className="size-4 text-muted-foreground" />}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-caption">
          <ActivityIdentity
            kind={item.source_kind === 'user' ? 'user' : 'agent'}
            address={item.source_id ?? item.source_handle}
            name={item.source_name}
            className="font-medium"
          />
          <span className="text-muted-foreground">
            {item.input_payload.emoji ? 'reacted' : 'removed a reaction'}
          </span>
          <BellOff className="size-3 shrink-0 text-muted-foreground" aria-label="Silent feedback" />
        </div>
        <blockquote className="mt-2 border-l-2 pl-3 text-sm leading-relaxed text-muted-foreground wrap-anywhere">
          <MessagePreview text={item.input_payload.target.content} />
        </blockquote>
        {item.presented === false && (
          <span className="mt-1 block text-xs text-muted-foreground">Superseded</span>
        )}
      </div>
    </article>
  ) : item.source_kind === 'schedule' ? (
    <ScheduleInput item={item} />
  ) : item.source_kind === 'hitl' ? (
    <DecisionInput item={item} />
  ) : (
    <PersonInput item={item} />
  );
}

export function InputItems({ items }: { items: InputItem[] }) {
  const content = (
    <div className="flex min-w-0 flex-col gap-3">
      {items.map((item, index) => (
        <InputMessage key={item.id ?? index} item={item} />
      ))}
    </div>
  );
  return (
    <Bubble variant="agent-outline" align="end" className="max-w-full">
      <BubbleContent>
        {items.length > 1 ? (
          <div data-input="batch">
            <div className="flex items-center gap-2 py-1 text-caption">
              <Inbox className="size-3.5" />
              {items.length} inputs
            </div>
            <div className="pt-3">{content}</div>
          </div>
        ) : (
          content
        )}
      </BubbleContent>
    </Bubble>
  );
}

export function Compaction({ text }: { text: string }) {
  return (
    <div data-input="compaction" className="my-4 w-full min-w-0">
      <div className="flex items-center gap-3">
        <span className="h-px flex-1 bg-border" />
        <span className="shrink-0 px-1 py-1 text-xs text-muted-foreground">Compacted</span>
        <span className="h-px flex-1 bg-border" />
      </div>
      <div className="mx-auto max-w-3xl pt-3 text-sm text-muted-foreground">
        <AgentMarkdown text={text} />
      </div>
    </div>
  );
}
