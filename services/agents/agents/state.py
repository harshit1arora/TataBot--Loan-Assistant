"""Graph state.

`results`, `steps` and `citations` are written by branches that may run in parallel, so
they carry reducers — that is what makes a fan-out to several workers safe.
"""
from __future__ import annotations

import operator
from typing import Annotated, NotRequired, TypedDict


def merge_dicts(left: dict, right: dict) -> dict:
    return {**left, **right}


class AgentState(TypedDict):
    question: str
    customer_id: NotRequired[str]
    document_id: NotRequired[str]
    # Which workers the router chose, and why.
    route: list[str]
    route_reason: str
    # worker name -> its structured result
    results: Annotated[dict, merge_dicts]
    # Human-readable trace of what ran, in order.
    steps: Annotated[list, operator.add]
    citations: Annotated[list, operator.add]
    answer: str
    needs_input: list[str]


def new_state(
    question: str,
    customer_id: str | None = None,
    document_id: str | None = None,
) -> AgentState:
    state: AgentState = {
        "question": question,
        "route": [],
        "route_reason": "",
        "results": {},
        "steps": [],
        "citations": [],
        "answer": "",
        "needs_input": [],
    }
    if customer_id:
        state["customer_id"] = customer_id
    if document_id:
        state["document_id"] = document_id
    return state
