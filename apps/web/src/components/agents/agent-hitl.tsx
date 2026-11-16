import { Check, ShieldCheck, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { AgentAvatar } from '@/components/agent-avatar';
import {
  Questionnaire,
  QuestionnaireActions,
  QuestionnaireChoice,
  QuestionnaireChoices,
  QuestionnaireDescription,
  QuestionnaireError,
  QuestionnaireInput,
  QuestionnaireItem,
  QuestionnaireNext,
  QuestionnairePrevious,
  QuestionnaireProgress,
  QuestionnaireSubmit,
  QuestionnaireTitle,
} from '@/components/ui/questionnaire';
import { useAgentPreview } from './agent-preview';

const questions = [
  {
    name: 'audience',
    choices: [
      { value: 'Everyone in the workspace' },
      { value: 'Workspace owners' },
      { value: 'Invited reviewers' },
    ],
    required: true,
  },
  {
    name: 'channels',
    choices: [{ value: 'Blog and changelog' }, { value: 'Newsletter' }, { value: 'Social posts' }],
    required: true,
  },
  { name: 'notes' },
];

export function AskCard({ inline = false }: { inline?: boolean }) {
  const p = useAgentPreview();
  if (p.session.answers)
    return (
      <section
        aria-label="Answered questions"
        data-tool={inline ? undefined : 'hitl_ask'}
        className={inline ? 'min-w-0' : 'w-135 max-w-full rounded-[22px] bg-muted p-4'}
      >
        <div className="mb-3 flex items-center gap-2 text-caption text-muted-foreground">
          <Check className="size-4" />
          You answered
        </div>
        <dl className="flex flex-col gap-3">
          {Object.entries(p.session.answers).map(([key, values]) => (
            <div key={key}>
              <dt className="text-caption text-muted-foreground">
                {key === 'audience' ? 'Audience' : key === 'channels' ? 'Channels' : 'Notes'}
              </dt>
              <dd className="mt-0.5 text-sm">
                {values.filter(Boolean).join(', ') || 'No additional notes'}
              </dd>
            </div>
          ))}
        </dl>
      </section>
    );
  return (
    <section
      aria-label="Agent questions"
      data-tool={inline ? undefined : 'hitl_ask'}
      className={inline ? 'min-w-0' : 'w-135 max-w-full rounded-[22px] bg-muted p-4'}
    >
      <Questionnaire
        items={questions}
        defaultItem="audience"
        shortcuts="letters"
        onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          p.updateSession({
            answers: Object.fromEntries(
              questions.map((question) => [question.name, data.getAll(question.name).map(String)]),
            ),
          });
        }}
      >
        <QuestionnaireProgress />
        <QuestionnaireItem name="audience" required>
          <QuestionnaireTitle>Who should receive the launch announcement?</QuestionnaireTitle>
          <QuestionnaireDescription>Choose one audience.</QuestionnaireDescription>
          <QuestionnaireChoices>
            {questions[0].choices!.map(({ value }, index) => (
              <QuestionnaireChoice
                variant="chat"
                key={value}
                value={value}
                shortcut={String.fromCharCode(65 + index)}
              >
                {value}
              </QuestionnaireChoice>
            ))}
          </QuestionnaireChoices>
          <QuestionnaireError />
        </QuestionnaireItem>
        <QuestionnaireItem name="channels" multiple required>
          <QuestionnaireTitle>Which channels should the launch use?</QuestionnaireTitle>
          <QuestionnaireDescription>Select all that apply.</QuestionnaireDescription>
          <QuestionnaireChoices>
            {questions[1].choices!.map(({ value }, index) => (
              <QuestionnaireChoice
                variant="chat"
                key={value}
                value={value}
                shortcut={String.fromCharCode(65 + index)}
              >
                {value}
              </QuestionnaireChoice>
            ))}
          </QuestionnaireChoices>
          <QuestionnaireError />
        </QuestionnaireItem>
        <QuestionnaireItem name="notes">
          <QuestionnaireTitle>Anything else I should keep in mind?</QuestionnaireTitle>
          <QuestionnaireDescription>Add a note, or submit without one.</QuestionnaireDescription>
          <QuestionnaireInput
            aria-label="Additional launch notes"
            placeholder="Write your answer…"
          />
        </QuestionnaireItem>
        <QuestionnaireActions>
          <QuestionnairePrevious size="sm" variant="ghost">
            Back
          </QuestionnairePrevious>
          <QuestionnaireNext size="sm">Next</QuestionnaireNext>
          <QuestionnaireSubmit size="sm">Send answers</QuestionnaireSubmit>
        </QuestionnaireActions>
      </Questionnaire>
    </section>
  );
}

export function AccessRequestCard({ inline = false }: { inline?: boolean }) {
  const p = useAgentPreview();
  return (
    <section
      aria-label="Storage access request"
      data-tool={inline ? undefined : 'hitl_request'}
      className={inline ? 'min-w-0' : 'w-135 max-w-full overflow-hidden rounded-[22px] border'}
    >
      <div className={inline ? 'sr-only' : 'flex items-center gap-3 p-4'}>
        <ShieldCheck className="size-5 shrink-0 text-muted-foreground" />
        <h3 className="text-sm font-medium">Access to your Personal storage</h3>
      </div>
      <div className={inline ? 'flex flex-col gap-4' : 'flex flex-col gap-4 px-4 pb-4'}>
        <p className="text-sm leading-relaxed">
          I’d like to read your research documents so I can check the sources and finish the
          summary.
        </p>
        <div className="flex items-center gap-2 text-caption">
          <AgentAvatar name={p.fixture.name} className="size-6" />
          <span>{p.profile.name} and its Leti agents</span>
        </div>
        <div className="flex items-center justify-between gap-2 rounded-lg bg-muted px-3 py-2 text-sm">
          <span className="text-muted-foreground">Requested permission</span>
          <span>Read only</span>
        </div>
        {p.session.approval ? (
          <p role="status" className="flex items-center gap-2 text-sm">
            {p.session.approval === 'accepted' ? (
              <Check className="size-4" />
            ) : (
              <X className="size-4" />
            )}
            {p.session.approval === 'accepted'
              ? 'Allowed in this preview · Read only'
              : 'Request declined'}
          </p>
        ) : (
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => p.updateSession({ approval: 'denied' })}
            >
              <X />
              Decline
            </Button>
            <Button size="sm" onClick={() => p.updateSession({ approval: 'accepted' })}>
              Allow access
            </Button>
          </div>
        )}
      </div>
    </section>
  );
}
