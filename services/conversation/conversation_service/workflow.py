"""The workflow state machine.

States are derived from the session record on the server. A request cannot name a
state, and every handler declares the state it must be in before it will run — so the
"skip KYC, jump to sanction" path that existed before is not expressible here.
"""
from __future__ import annotations

from enum import Enum


class State(str, Enum):
    NEW = "new"
    AWAITING_AMOUNT = "awaiting_amount"
    AWAITING_DOCUMENT = "awaiting_document"
    ASSESSING = "assessing"
    SANCTIONED = "sanctioned"
    REJECTED = "rejected"


class Event(str, Enum):
    GREETING = "greeting"
    AMOUNT_PROVIDED = "amount_provided"
    AMOUNT_MISSING = "amount_missing"
    OUTCOME_APPROVED = "outcome_approved"
    OUTCOME_REJECTED = "outcome_rejected"
    OUTCOME_DOCUMENT_REQUIRED = "outcome_document_required"
    DOCUMENT_RECEIVED = "document_received"
    DOCUMENT_PENDING = "document_pending"
    RESTART = "restart"
    SMALLTALK = "smalltalk"


# event -> (allowed_from_states, to_state)
TRANSITIONS: dict[Event, tuple[frozenset[State], State]] = {
    Event.GREETING: (frozenset({State.NEW}), State.AWAITING_AMOUNT),
    Event.AMOUNT_PROVIDED: (
        frozenset({State.NEW, State.AWAITING_AMOUNT, State.AWAITING_DOCUMENT}),
        State.AWAITING_AMOUNT,
    ),
    Event.AMOUNT_MISSING: (
        frozenset({State.NEW, State.AWAITING_AMOUNT}),
        State.AWAITING_AMOUNT,
    ),
    # A decision can land while we are collecting an amount, or after a document was
    # supplied and the application was re-assessed.
    Event.OUTCOME_APPROVED: (
        frozenset({State.AWAITING_AMOUNT, State.AWAITING_DOCUMENT, State.ASSESSING}),
        State.SANCTIONED,
    ),
    Event.OUTCOME_REJECTED: (
        frozenset({State.AWAITING_AMOUNT, State.AWAITING_DOCUMENT, State.ASSESSING}),
        State.REJECTED,
    ),
    Event.OUTCOME_DOCUMENT_REQUIRED: (
        frozenset({State.AWAITING_AMOUNT, State.AWAITING_DOCUMENT, State.ASSESSING}),
        State.AWAITING_DOCUMENT,
    ),
    # A usable document moves the session into assessment; that step is visible in the
    # trace instead of being silently folded into the decision.
    Event.DOCUMENT_RECEIVED: (frozenset({State.AWAITING_DOCUMENT}), State.ASSESSING),
    Event.DOCUMENT_PENDING: (frozenset({State.AWAITING_DOCUMENT}), State.AWAITING_DOCUMENT),
    Event.RESTART: (
        frozenset({State.SANCTIONED, State.REJECTED, State.AWAITING_DOCUMENT}),
        State.AWAITING_AMOUNT,
    ),
    Event.SMALLTALK: (
        frozenset(
            {
                State.NEW,
                State.AWAITING_AMOUNT,
                State.AWAITING_DOCUMENT,
                State.ASSESSING,
                State.SANCTIONED,
                State.REJECTED,
            }
        ),
        State.AWAITING_AMOUNT,  # value replaced by the current state in `advance`
    ),
}


class TransitionNotAllowed(Exception):
    def __init__(self, state: State, event: Event) -> None:
        super().__init__(f"event {event.value} is not allowed in state {state.value}")
        self.state = state
        self.event = event


def next_state(current: State, event: Event) -> State:
    allowed, target = TRANSITIONS[event]
    if current not in allowed:
        raise TransitionNotAllowed(current, event)
    if event is Event.SMALLTALK:
        return current  # a side comment never moves the workflow
    return target


def preconditions_met(state: State, event: Event) -> bool:
    return state in TRANSITIONS[event][0]


# Which component did the work behind each event. Derived from the event rather than
# stored, so the trace needs no extra column and cannot drift from the code.
HANDLED_BY: dict[Event, str] = {
    Event.GREETING: "conversation-service · greeting",
    Event.AMOUNT_MISSING: "conversation-service · amount parser",
    Event.AMOUNT_PROVIDED: "orchestrator → core-service · applications",
    Event.OUTCOME_APPROVED: "core-service · policy + sanction",
    Event.OUTCOME_REJECTED: "core-service · policy",
    Event.OUTCOME_DOCUMENT_REQUIRED: "core-service · policy",
    Event.DOCUMENT_RECEIVED: "core-service · extraction",
    Event.DOCUMENT_PENDING: "conversation-service · awaiting upload",
    Event.RESTART: "conversation-service · orchestrator",
    Event.SMALLTALK: "conversation-service · orchestrator",
}


def handled_by(event: Event) -> str:
    return HANDLED_BY.get(event, "orchestrator")
