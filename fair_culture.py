"""
Fair Culture (GEMR) behavioural-outcome classification.

The LLM only ever answers individual yes/no questions from
config.FAIR_CULTURE_QUESTIONS about the unsafe act; the final outcome is
derived by plain Python if/else over the collected answers, so the result is
auditable and cannot be hallucinated. Questions are walked in order and a
question is asked only when every condition in its `depends_on` dict is
already satisfied by prior answers.
"""

import config
from azure_client import chat_json


class FairCultureError(RuntimeError):
    """Raised when an LLM answer fails validation or the tree can't resolve."""


def _coerce_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "yes"}:
            return True
        if text in {"false", "no"}:
            return False
    return None


def answer_fair_culture_question(question_text, unsafe_act_text, incident_id=None):
    """Ask the LLM ONE yes/no question about the unsafe act.

    Returns {"answer": bool, "justification": str}, validated.
    """
    parsed = chat_json(
        config.build_fair_culture_question_system_prompt(question_text),
        unsafe_act_text,
        incident_id=incident_id,
        purpose="fair_culture_question",
    )

    if "answer" not in parsed:
        raise FairCultureError(
            f"[{incident_id}] Fair-culture response is missing the 'answer' "
            f"key for question {question_text!r}: {parsed!r}"
        )
    answer = _coerce_bool(parsed["answer"])
    if answer is None:
        raise FairCultureError(
            f"[{incident_id}] Fair-culture 'answer' is not a boolean for "
            f"question {question_text!r}: {parsed['answer']!r}"
        )
    return {"answer": answer, "justification": str(parsed.get("justification", ""))}


def _map_answers_to_outcome(answers):
    """Deterministic mapping from the collected answers to one outcome label.

    Mirrors the GEMR flowchart as encoded in config.FAIR_CULTURE_QUESTIONS
    (including its terminal comments and `terminal_if_no` marker). No LLM.
    """
    if answers.get("deliberate"):
        # Deliberate-harm branch: the split is on intent.
        if answers.get("well_intentioned") is False:
            return "Sabotage, malicious intention"
        return "Reckless contravention"

    # Not deliberate.
    if answers.get("informed_about_procedures"):
        if answers.get("procedures_clear_and_workable") is False:
            return "Mistake caused by system"
        # Procedures were clear/workable but not followed: the
        # contravention_or_mistake question chose between the two named
        # alternatives (True = first alternative = Contravention).
        if answers.get("contravention_or_mistake"):
            return "Contravention"
        return "Slip/lapse"

    # Not informed about procedures.
    if answers.get("would_others_have_done_the_same"):
        if answers.get("history_of_contravening_procedures"):
            return "Routine error - personal history"
        return "Routine error - different people"

    # Others would NOT have done the same. Per config's terminal_if_no on
    # adequate_selection_training_experience: No -> Poor judgement. If
    # selection/training WAS adequate, the failure to inform the person about
    # procedures is a system failure.
    if answers.get("adequate_selection_training_experience") is False:
        return "Poor judgement"
    return "Mistake caused by system"


def classify_behavioural_outcome(unsafe_act_text, incident_id=None):
    """Walk the fair-culture decision tree for one unsafe act.

    Returns {"outcome": <one of config.FAIR_CULTURE_OUTCOMES>,
             "answers": {question_id: bool},
             "trail": [per-question dicts with justifications]}.
    """
    answers = {}
    trail = []

    for question in config.FAIR_CULTURE_QUESTIONS:
        depends_on = question.get("depends_on", {})
        if not all(answers.get(key) == value for key, value in depends_on.items()):
            continue

        result = answer_fair_culture_question(
            question["question"], unsafe_act_text, incident_id=incident_id
        )
        answers[question["id"]] = result["answer"]
        trail.append(
            {
                "id": question["id"],
                "question": question["question"],
                "answer": result["answer"],
                "justification": result["justification"],
            }
        )

    outcome = _map_answers_to_outcome(answers)
    if outcome not in config.FAIR_CULTURE_OUTCOMES:
        raise FairCultureError(
            f"[{incident_id}] Derived outcome {outcome!r} is not in "
            "config.FAIR_CULTURE_OUTCOMES - check the decision tree."
        )
    return {"outcome": outcome, "answers": answers, "trail": trail}
