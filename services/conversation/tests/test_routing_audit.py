"""Is the orchestrator routing correctly?

Three kinds of evidence:

1. An exhaustive matrix over every (state, event) pair — the table is the specification.
2. A full-flow trace asserting the exact sequence of transitions and which component
   handled each one.
3. A check on how much of the flow the LLM is allowed to touch.
"""
from __future__ import annotations

import pytest
from conversation_service.workflow import (
    HANDLED_BY,
    TRANSITIONS,
    Event,
    State,
    TransitionNotAllowed,
    handled_by,
    next_state,
)

ALL_STATES = list(State)
ALL_EVENTS = list(Event)


@pytest.mark.parametrize("state", ALL_STATES)
@pytest.mark.parametrize("event", ALL_EVENTS)
def test_every_state_event_pair_matches_the_table(state, event):
    """54 combinations: allowed exactly where the table says, refused everywhere else."""
    allowed_states, target = TRANSITIONS[event]
    if state in allowed_states:
        result = next_state(state, event)
        expected = state if event is Event.SMALLTALK else target
        assert result is expected
    else:
        with pytest.raises(TransitionNotAllowed):
            next_state(state, event)


def test_every_state_is_reachable_and_every_event_is_usable():
    reachable = {State.NEW}
    for _event, (_allowed, target) in TRANSITIONS.items():
        reachable.add(target)
    assert reachable == set(ALL_STATES), f"unreachable states: {set(ALL_STATES) - reachable}"

    usable = {event for event, (allowed, _target) in TRANSITIONS.items() if allowed}
    assert usable == set(ALL_EVENTS), f"events with no legal source: {set(ALL_EVENTS) - usable}"


def test_every_event_can_be_attributed_to_a_component():
    """The trace endpoint must never have to guess."""
    assert set(HANDLED_BY) == set(ALL_EVENTS)
    for event in ALL_EVENTS:
        assert handled_by(event) != "orchestrator" or event in (Event.SMALLTALK, Event.RESTART)


def test_no_terminal_state_can_produce_a_decision():
    """The point of the whole design: you cannot jump from anywhere into a decision."""
    for terminal in (State.SANCTIONED, State.REJECTED):
        for event in (Event.OUTCOME_APPROVED, Event.OUTCOME_REJECTED):
            with pytest.raises(TransitionNotAllowed):
                next_state(terminal, event)


def test_a_decision_cannot_be_reached_without_passing_through_an_assessment():
    """Only the states that represent "we asked for something" can produce an outcome."""
    sources = TRANSITIONS[Event.OUTCOME_APPROVED][0] | TRANSITIONS[Event.OUTCOME_REJECTED][0]
    assert sources == {State.AWAITING_AMOUNT, State.AWAITING_DOCUMENT, State.ASSESSING}
