"""Structured human forms; question type determines the permitted answer fields."""

from typing import Annotated, Literal

from pydantic import Field, JsonValue, model_validator

from leta.domain import ID, Input


class PersonalResource(Input):
    type: Literal["personal_scope"]
    user_id: ID


class PersonalScopeResource(PersonalResource):
    scope_id: ID


class QuestionOption(Input):
    id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=4000)


class QuestionText(Input):
    id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=10_000)


class ChoiceQuestion(QuestionText):
    options: list[QuestionOption] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_options(self):
        if len({option.id for option in self.options}) != len(self.options):
            raise ValueError("duplicate option ID")
        return self


class SingleChoiceQuestion(ChoiceQuestion):
    type: Literal["single_choice"]


class MultipleChoiceQuestion(ChoiceQuestion):
    type: Literal["multiple_choice"]


class TextQuestion(QuestionText):
    type: Literal["text"]


Question = Annotated[
    SingleChoiceQuestion | MultipleChoiceQuestion | TextQuestion,
    Field(discriminator="type"),
]


class AskForm(Input):
    questions: list[Question] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_questions(self):
        if len({question.id for question in self.questions}) != len(self.questions):
            raise ValueError("duplicate question ID")
        return self


class SingleChoiceAnswer(Input):
    option_id: str | None
    note: str = Field(default="", max_length=100_000)


class MultipleChoiceAnswer(Input):
    option_ids: list[str]
    note: str = Field(default="", max_length=100_000)


class TextAnswer(Input):
    text: str = Field(max_length=100_000)


def normalize_answers(form: AskForm, answers: dict[str, JsonValue]) -> dict:
    if answers.keys() != {question.id for question in form.questions}:
        raise ValueError("answer every question exactly once with no unknown IDs")
    result = {}
    for question in form.questions:
        raw = answers[question.id]
        if isinstance(question, SingleChoiceQuestion):
            answer = SingleChoiceAnswer.model_validate(raw)
            selected = [] if answer.option_id is None else [answer.option_id]
        elif isinstance(question, MultipleChoiceQuestion):
            answer = MultipleChoiceAnswer.model_validate(raw)
            selected = answer.option_ids
            if len(set(selected)) != len(selected):
                raise ValueError("duplicate selected option ID")
        else:
            answer = TextAnswer.model_validate(raw)
            selected = []
        if selected and not set(selected) <= {option.id for option in question.options}:
            raise ValueError("unknown selected option ID")
        result[question.id] = answer.model_dump(mode="json")
    return result


class RequestResolution(Input):
    leta_id: ID
    request_id: ID
    action: Literal["answer", "accept", "deny", "cancel", "expire"]
    actor_user_id: ID | None = None
    requester_agent_id: ID | None = None
    answers: dict[str, JsonValue] | None = None
    reason: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def validate_actor_and_answer(self):
        actors = int(self.actor_user_id is not None) + int(
            self.requester_agent_id is not None
        )
        if actors != (0 if self.action == "expire" else 1):
            raise ValueError("resolution requires exactly one authenticated actor")
        if self.action in {"answer", "accept", "deny"} and self.actor_user_id is None:
            raise ValueError("only a human may answer a request")
        if (self.action == "answer") != (self.answers is not None):
            raise ValueError("only an answer supplies form responses")
        return self
