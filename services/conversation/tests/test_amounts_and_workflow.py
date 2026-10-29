"""The two pure modules: amount parsing and the state machine."""
from __future__ import annotations

import pytest
from conversation_service.amounts import parse_amount, parse_tenure
from conversation_service.workflow import Event, State, TransitionNotAllowed, next_state


@pytest.mark.parametrize(
    "message,expected",
    [
        ("I need 5 lakh", 500_000),
        ("give me 2.5 lakh rupees", 250_000),
        ("50000", None),  # no unit, no loan-intent word: refuse to guess
        ("I need 50000 please, ok?", 50_000),  # the old parser returned 5,00,00,000 here
        ("ok 40000", None),
        ("my pincode is 411001", None),  # the old parser returned a 4,11,001 loan
        ("₹3,00,000 for 24 months", 300_000),
        ("need 75k", 75_000),
        ("1.5 crore", 15_000_000),
        ("what is my limit", None),
        ("hello", None),
    ],
)
def test_amount_parsing_never_guesses(message, expected):
    parsed = parse_amount(message)
    assert (parsed.rupees if parsed else None) == expected


def test_the_letter_k_no_longer_multiplies_by_a_thousand():
    """Regression: any message containing 'k' used to scale the amount by 1000."""
    assert parse_amount("I need 50000 thanks").rupees == 50_000
    assert parse_amount("I need 50000, kya kar sakte ho").rupees == 50_000


def test_tenure_parsing():
    assert parse_tenure("for 36 months") == 36
    assert parse_tenure("2 years") == 24
    assert parse_tenure("as soon as possible") is None


def test_illegal_transitions_are_impossible():
    """The whole point: you cannot jump from a fresh session to a decision."""
    for event in (Event.OUTCOME_APPROVED, Event.OUTCOME_REJECTED, Event.DOCUMENT_RECEIVED):
        with pytest.raises(TransitionNotAllowed):
            next_state(State.NEW, event)


def test_legal_transitions():
    assert next_state(State.NEW, Event.GREETING) is State.AWAITING_AMOUNT
    assert next_state(State.AWAITING_AMOUNT, Event.OUTCOME_APPROVED) is State.SANCTIONED
    assert next_state(State.AWAITING_AMOUNT, Event.OUTCOME_DOCUMENT_REQUIRED) is State.AWAITING_DOCUMENT
    assert next_state(State.AWAITING_DOCUMENT, Event.DOCUMENT_RECEIVED) is State.ASSESSING
    # A document can turn a pending application into a decision.
    assert next_state(State.AWAITING_DOCUMENT, Event.OUTCOME_APPROVED) is State.SANCTIONED


def test_smalltalk_never_moves_the_state():
    for state in (State.NEW, State.AWAITING_AMOUNT, State.SANCTIONED, State.REJECTED):
        assert next_state(state, Event.SMALLTALK) is state
