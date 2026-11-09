from copy import deepcopy

import pytest
from pydantic import ValidationError

from leta.human import AskForm, normalize_answers


@pytest.fixture
def form_payload():
    options = [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]
    return {
        "questions": [
            {
                "id": "one",
                "type": "single_choice",
                "text": "Pick one",
                "options": options,
            },
            {
                "id": "many",
                "type": "multiple_choice",
                "text": "Pick several",
                "options": options,
            },
            {"id": "words", "type": "text", "text": "Explain"},
        ]
    }


@pytest.fixture
def answers():
    return {
        "one": {"option_id": None, "note": "No suitable option"},
        "many": {"option_ids": [], "note": "None"},
        "words": {"text": ""},
    }


def test_mixed_form_allows_blank_choices_notes_and_empty_text(form_payload, answers):
    form = AskForm.model_validate(form_payload)
    assert normalize_answers(form, answers) == answers
    assert AskForm.model_validate_json(form.model_dump_json()) == form


def test_selected_choices_preserve_order_and_normalize_omitted_notes(form_payload):
    answers = {
        "one": {"option_id": "a"},
        "many": {"option_ids": ["b", "a"]},
        "words": {"text": "Details"},
    }
    normalized = normalize_answers(AskForm.model_validate(form_payload), answers)
    assert normalized == {
        "one": {"option_id": "a", "note": ""},
        "many": {"option_ids": ["b", "a"], "note": ""},
        "words": {"text": "Details"},
    }


@pytest.mark.parametrize(
    "change",
    [
        {"one": {"option_id": "unknown"}},
        {"many": {"option_ids": ["a", "unknown"]}},
        {"many": {"option_ids": ["a", "a"]}},
        {"one": {"option_id": None, "other_text": "Other"}},
        {"many": {"option_ids": [], "text": "Other"}},
        {"words": {"text": "Answer", "note": "Extra"}},
        {"words": {"option_ids": []}},
        {"one": {"option_id": ["a"]}},
        {"many": {"option_ids": None}},
        {"one": {"option_id": None, "note": None}},
        {"one": {"option_id": None, "note": "unsafe\0text"}},
    ],
)
def test_answers_reject_wrong_shape_unknown_options_and_other_fields(
    form_payload, answers, change
):
    with pytest.raises((ValueError, ValidationError)):
        normalize_answers(AskForm.model_validate(form_payload), answers | change)


@pytest.mark.parametrize("change", ["missing", "unknown"])
def test_answer_map_matches_entire_form(form_payload, answers, change):
    if change == "missing":
        answers.pop("words")
    else:
        answers["extra"] = {"text": "Unknown"}
    with pytest.raises(ValueError, match="every question"):
        normalize_answers(AskForm.model_validate(form_payload), answers)


@pytest.mark.parametrize(
    "change",
    [
        "empty",
        "duplicate_question",
        "duplicate_option",
        "empty_options",
        "text_options",
        "allow_other",
    ],
)
def test_form_rejects_ambiguous_or_unsupported_definitions(form_payload, change):
    value = deepcopy(form_payload)
    if change == "empty":
        value["questions"] = []
    elif change == "duplicate_question":
        value["questions"].append(value["questions"][0])
    elif change == "duplicate_option":
        value["questions"][0]["options"].append({"id": "a", "label": "Duplicate"})
    elif change == "empty_options":
        value["questions"][0]["options"] = []
    elif change == "text_options":
        value["questions"][2]["options"] = []
    else:
        value["questions"][0]["allow_other"] = True
    with pytest.raises(ValidationError):
        AskForm.model_validate(value)
