import { MessageCircleQuestion, ShieldCheck } from 'lucide-react';
import type { ToolResult } from '@/lib/agent-presentation';

function RequestSummary({
  type,
  inline,
  result,
}: {
  type: 'ask' | 'approval';
  inline: boolean;
  result?: unknown;
}) {
  const request = (result as ToolResult | undefined)?.request;
  const Icon = type === 'ask' ? MessageCircleQuestion : ShieldCheck;
  return (
    <section
      data-tool={inline ? undefined : type === 'ask' ? 'hitl_ask' : 'hitl_request'}
      className={inline ? 'min-w-0' : 'w-120 max-w-full rounded-xl border p-4'}
    >
      <div className="flex items-start gap-3">
        <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0">
          <p className="text-sm font-medium">
            {request?.title ?? (type === 'ask' ? 'Questions sent' : 'Access requested')}
          </p>
          <p className="mt-1 text-caption text-muted-foreground">
            {request?.status === 'pending'
              ? 'Waiting for the addressed person'
              : (request?.status ?? 'Pending')}
          </p>
          {request?.response?.answers && (
            <dl className="mt-4 space-y-3">
              {request.payload.questions?.map((q) => (
                <div key={q.id}>
                  <dt className="text-caption text-muted-foreground">{q.text}</dt>
                  <dd className="mt-1 text-sm">
                    {request.response?.answers?.[q.id]?.text ??
                      (q.options
                        ?.filter(
                          (o) =>
                            request.response?.answers?.[q.id]?.option_id === o.id ||
                            request.response?.answers?.[q.id]?.option_ids?.includes(o.id),
                        )
                        .map((o) => o.label)
                        .join(', ') ||
                        'No answer')}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      </div>
    </section>
  );
}
export function AskCard({ inline = false, result }: { inline?: boolean; result?: unknown }) {
  return <RequestSummary type="ask" inline={inline} result={result} />;
}
export function AccessRequestCard({
  inline = false,
  result,
}: {
  inline?: boolean;
  result?: unknown;
}) {
  return <RequestSummary type="approval" inline={inline} result={result} />;
}
