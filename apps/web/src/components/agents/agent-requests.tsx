import { useState } from 'react';
import { ChevronUp, MessageCircleQuestion, ShieldCheck, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Popover, PopoverTrigger, PopoverContent } from '@/components/ui/popover';
import {
  Drawer,
  DrawerTrigger,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerDescription,
} from '@/components/ui/drawer';
import {
  Questionnaire,
  QuestionnaireProgress,
  QuestionnaireItem,
  QuestionnaireTitle,
  QuestionnaireDescription,
  QuestionnaireChoices,
  QuestionnaireChoice,
  QuestionnaireInput,
  QuestionnaireActions,
  QuestionnairePrevious,
  QuestionnaireNext,
  QuestionnaireSubmit,
} from '@/components/ui/questionnaire';
import { useIsMobile } from '@/hooks/use-mobile';
import type { HumanRequest } from '@/lib/agent-api';
import { useAgentPreview } from './agent-preview';

export function RequestForm({
  request,
  close,
  draft,
  onDraft,
  onAnswer,
  onRefresh,
}: {
  request: HumanRequest;
  close: () => void;
  draft: Record<string, string[]>;
  onDraft: (draft: Record<string, string[]>) => void;
  onAnswer: (
    request: HumanRequest,
    status: 'answered' | 'accepted' | 'denied',
    response?: HumanRequest['response'],
  ) => Promise<void>;
  onRefresh: () => Promise<unknown>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const questions = request.payload.questions ?? [];
  function update(id: string, values: string[]) {
    onDraft({ ...draft, [id]: values });
  }
  async function submit(status: 'answered' | 'accepted' | 'denied') {
    setBusy(true);
    setError('');
    try {
      const response =
        status === 'answered'
          ? {
              answers: Object.fromEntries(
                questions.map((q) => [
                  q.id,
                  q.type === 'text'
                    ? { text: draft[q.id]?.[0] ?? '' }
                    : q.type === 'single_choice'
                      ? { option_id: draft[q.id]?.[0] ?? null }
                      : { option_ids: draft[q.id] ?? [] },
                ]),
              ),
            }
          : undefined;
      await onAnswer(request, status, response);
      close();
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Could not submit. Try again.');
      await onRefresh();
    } finally {
      setBusy(false);
    }
  }
  if (request.status !== 'pending')
    return (
      <div className="space-y-4">
        <p role="status" className="text-sm capitalize">
          {request.status}
          {request.status === 'accepted'
            ? ` · ${request.outcome?.status ?? 'Applying access…'}`
            : ''}
        </p>
        {questions.map((q) => (
          <div key={q.id}>
            <p className="text-caption text-muted-foreground">{q.text}</p>
            <p className="mt-1 text-sm">
              {request.response?.answers?.[q.id]?.text ??
                (q.options
                  ?.filter(
                    (o) =>
                      o.id === request.response?.answers?.[q.id]?.option_id ||
                      request.response?.answers?.[q.id]?.option_ids?.includes(o.id),
                  )
                  .map((o) => o.label)
                  .join(', ') ||
                  'No answer')}
            </p>
          </div>
        ))}
        <Button variant="outline" size="sm" onClick={close}>
          Close
        </Button>
      </div>
    );
  return (
    <div className="space-y-4">
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {request.type === 'ask' ? (
        <Questionnaire
          key={request.id}
          items={questions.map((q) => ({
            name: q.id,
            choices: q.options?.map((o) => ({ value: o.id })),
          }))}
          onSubmit={(event) => {
            event.preventDefault();
            void submit('answered');
          }}
        >
          <QuestionnaireProgress />
          {questions.map((q) => (
            <QuestionnaireItem
              key={q.id}
              name={q.id}
              multiple={q.type === 'multiple_choice'}
              disabled={busy}
            >
              <QuestionnaireTitle>{q.text}</QuestionnaireTitle>
              <QuestionnaireDescription>
                {q.type === 'multiple_choice'
                  ? 'Select any that apply.'
                  : q.type === 'single_choice'
                    ? 'Choose one, or leave unanswered.'
                    : 'An empty answer is allowed.'}
              </QuestionnaireDescription>
              {q.type === 'text' ? (
                <QuestionnaireInput
                  aria-label={q.text}
                  value={draft[q.id]?.[0] ?? ''}
                  onChange={(e) => update(q.id, [e.target.value])}
                  placeholder="Write your answer…"
                />
              ) : (
                <QuestionnaireChoices>
                  {q.options?.map((o) => (
                    <QuestionnaireChoice
                      key={o.id}
                      value={o.id}
                      checked={draft[q.id]?.includes(o.id) ?? false}
                      onChange={(e) =>
                        update(
                          q.id,
                          q.type === 'single_choice'
                            ? [o.id]
                            : e.target.checked
                              ? [...(draft[q.id] ?? []), o.id]
                              : (draft[q.id] ?? []).filter((id) => id !== o.id),
                        )
                      }
                    >
                      {o.label}
                    </QuestionnaireChoice>
                  ))}
                </QuestionnaireChoices>
              )}
            </QuestionnaireItem>
          ))}
          <QuestionnaireActions>
            <QuestionnairePrevious size="sm" variant="ghost">
              Back
            </QuestionnairePrevious>
            <QuestionnaireNext size="sm">Next</QuestionnaireNext>
            <QuestionnaireSubmit size="sm" disabled={busy}>
              {busy ? 'Sending…' : 'Send answers'}
            </QuestionnaireSubmit>
          </QuestionnaireActions>
        </Questionnaire>
      ) : (
        <div className="space-y-5">
          <p className="text-sm leading-relaxed">{request.payload.reason}</p>
          <dl className="divide-y text-sm">
            <div className="flex justify-between gap-4 py-3">
              <dt className="text-muted-foreground">Storage</dt>
              <dd className="max-w-60 truncate">{request.payload.storage_id}</dd>
            </div>
            <div className="flex justify-between py-3">
              <dt className="text-muted-foreground">Permission</dt>
              <dd>{request.payload.role === 'editor' ? 'Read and write' : 'Read only'}</dd>
            </div>
          </dl>
          <div className="flex justify-end gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => void submit('denied')}
            >
              Decline
            </Button>
            <Button size="sm" disabled={busy} onClick={() => void submit('accepted')}>
              {busy ? 'Sending…' : 'Allow access'}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
export function PendingRequests() {
  const p = useAgentPreview();
  const mobile = useIsMobile(721);
  const pending = p.requests.filter((r) => r.status === 'pending');
  const selected = p.requests.find((r) => r.id === p.session.requestOpen) ?? pending[0];
  const open = !!p.session.requestOpen;
  const close = () => p.updateSession({ requestOpen: null });
  if (!p.pendingRequests && !open) return null;
  const trigger = (
    <Button
      type="button"
      variant="ghost"
      className="h-auto w-full justify-start rounded-t-[calc(var(--radius-3xl)-1px)] rounded-b-none border-b px-4 py-2.5 text-caption font-normal"
    >
      <MessageCircleQuestion className="size-4" />
      <span>
        {pending.filter((r) => r.type === 'ask').length} questions ·{' '}
        {pending.filter((r) => r.type === 'approval').length} requests
      </span>
      <ChevronUp className="ml-auto size-3.5" />
    </Button>
  );
  const body = (
    <div className="flex min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b px-4 py-3">
        <span className="flex-1 text-sm font-medium">Questions & requests</span>
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          aria-label="Close requests"
          onClick={close}
        >
          <X />
        </Button>
      </div>
      <div className="min-h-0 overflow-y-auto overscroll-contain p-4">
        {p.requests.length > 1 && (
          <div className="mb-5 flex flex-col gap-1" aria-label="Choose request">
            {p.requests.map((r) => (
              <Button
                key={r.id}
                type="button"
                variant={selected?.id === r.id ? 'secondary' : 'ghost'}
                size="sm"
                className="justify-start font-normal"
                onClick={() => p.updateSession({ requestOpen: r.id })}
              >
                {r.type === 'ask' ? <MessageCircleQuestion /> : <ShieldCheck />}
                <span className="truncate">{r.title}</span>
                <span className="ml-auto text-xs text-muted-foreground">
                  {r.status === 'pending' ? 'Pending' : r.status}
                </span>
              </Button>
            ))}
          </div>
        )}
        {selected ? (
          <>
            <h3 className="mb-4 text-sm font-medium">{selected.title}</h3>
            <RequestForm
              key={selected.id}
              request={selected}
              close={close}
              draft={p.session.requestDrafts[selected.id] ?? {}}
              onDraft={(draft) =>
                p.updateSession({
                  requestDrafts: { ...p.session.requestDrafts, [selected.id]: draft },
                })
              }
              onAnswer={p.answerRequest}
              onRefresh={p.live.refresh}
            />
          </>
        ) : (
          <p className="text-sm text-muted-foreground">Loading requests…</p>
        )}
        {p.live.enabled && p.live.requests.hasNextPage && (
          <Button
            className="mt-4"
            size="sm"
            variant="ghost"
            onClick={() => void p.live.requests.fetchNextPage()}
          >
            Load earlier requests
          </Button>
        )}
      </div>
    </div>
  );
  const change = (value: boolean) =>
    p.updateSession({ requestOpen: value ? (selected?.id ?? 'pending') : null });
  return mobile ? (
    <Drawer open={open} onOpenChange={change}>
      <DrawerTrigger asChild>{trigger}</DrawerTrigger>
      <DrawerContent className="max-h-[85dvh]">
        <DrawerHeader className="sr-only">
          <DrawerTitle>Questions & requests</DrawerTitle>
          <DrawerDescription>
            Answer when you are ready. Your chat draft stays separate.
          </DrawerDescription>
        </DrawerHeader>
        {body}
      </DrawerContent>
    </Drawer>
  ) : (
    <Popover open={open} onOpenChange={change}>
      <PopoverTrigger asChild>{trigger}</PopoverTrigger>
      <PopoverContent
        side="top"
        align="start"
        sideOffset={8}
        onOpenAutoFocus={(event) => event.preventDefault()}
        className="max-h-[min(650px,75dvh)] w-120 max-w-[calc(100vw-24px)] gap-0 overflow-hidden p-0"
      >
        {body}
      </PopoverContent>
    </Popover>
  );
}
