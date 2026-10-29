"""Conversation orchestration.

The state machine, the amount parser and the reply templates are deterministic. The
LLM may only add a sentence of warmth, and only when the call budget allows. Every
decision, every figure and every transition comes from the core service or from code.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from . import replies
from .agents_client import AgentsClient, AgentsUnavailable
from .amounts import (
    looks_like_greeting,
    looks_like_question,
    looks_like_restart,
    looks_like_support_request,
    looks_like_upload,
    parse_amount,
    parse_tenure,
)
from .clients import CoreClient, CoreServiceError
from .config import Settings
from .errors import NotFoundError
from .llm import LlmClient
from .models import ConversationSession, Message, Transition
from .workflow import Event, State, TransitionNotAllowed, next_state, preconditions_met

logger = logging.getLogger("conversation.orchestrator")

DEFAULT_TENURE_MONTHS = 36


@dataclass
class TurnResult:
    session_id: str
    state: State
    reply: str
    application: dict | None = None
    document: dict | None = None
    sanction_document_id: str | None = None
    suggested_actions: list[str] = field(default_factory=list)
    intent: str | None = None
    agent_route: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "state": self.state.value,
            "reply": self.reply,
            "application": self.application,
            "document": self.document,
            "sanction_document_id": self.sanction_document_id,
            "suggested_actions": self.suggested_actions,
            "intent": self.intent,
            "agent_route": self.agent_route,
            "citations": self.citations,
        }


class Orchestrator:
    def __init__(
        self,
        settings: Settings,
        core: CoreClient,
        llm: LlmClient,
        agents: AgentsClient | None = None,
    ) -> None:
        self.settings = settings
        self.core = core
        self.llm = llm
        self.agents = agents

    # --- session helpers -------------------------------------------------
    def get_or_create_session(
        self, db: Session, customer_id: str, session_id: str | None
    ) -> ConversationSession:
        if session_id:
            session = db.get(ConversationSession, session_id)
            if session is not None:
                if session.customer_id != customer_id:
                    # A session belongs to exactly one customer; never hand it over.
                    # Same response as "no such session" so it is not an oracle.
                    raise NotFoundError("Session not found.")
                return session
        session = ConversationSession(customer_id=customer_id, state=State.NEW.value)
        db.add(session)
        db.flush()
        return session

    def _add_message(self, db: Session, session: ConversationSession, role: str, content: str) -> None:
        db.add(Message(session_id=session.id, role=role, content=content))

    def _advance(self, db: Session, session: ConversationSession, event: Event) -> None:
        current = State(session.state)
        try:
            target = next_state(current, event)
        except TransitionNotAllowed:
            logger.warning(
                "transition refused", extra={"session_id": session.id, "state": current.value, "event": event.value}
            )
            raise
        if target is not current:
            db.add(
                Transition(
                    session_id=session.id,
                    from_state=current.value,
                    to_state=target.value,
                    event=event.value,
                )
            )
            session.state = target.value
        session.version += 1
        db.flush()

    async def _maybe_phrase(
        self,
        db: Session,
        session: ConversationSession,
        *,
        customer_token: str,
        first_name: str,
        band: str,
        message: str,
        fallback: str,
    ) -> str:
        """Optional LLM warmth, capped per session and never carrying a figure.

        The deterministic template is always appended, so the customer still gets the
        correct information even if the model writes something vague.
        """
        if not self.llm.enabled or session.llm_calls >= self.settings.max_llm_calls_per_session:
            return fallback
        session.llm_calls += 1
        db.flush()
        text = await self.llm.phrase(
            first_name=first_name, band=band, state=session.state, message=message
        )
        return f"{text}\n\n{fallback}" if text else fallback

    # --- main entry ------------------------------------------------------
    async def handle_message(
        self,
        db: Session,
        *,
        customer_id: str,
        customer_token: str,
        session_id: str | None,
        message: str,
    ) -> TurnResult:
        session = self.get_or_create_session(db, customer_id, session_id)
        message = (message or "").strip()[: self.settings.max_message_chars]
        self._add_message(db, session, "customer", message)

        state = State(session.state)

        # "Can I talk to someone?" must work in every state, and must never be mistaken
        # for a loan amount or a restart.
        if looks_like_support_request(message):
            return self._on_support(db, session)

        # A question goes to the agent graph: it can explain eligibility, price a loan or
        # answer a policy question without touching the application workflow.
        if self.agents is not None and self.settings.agents_enabled and looks_like_question(message):
            return await self._on_question(db, session, customer_id, message)

        if state is State.NEW:
            return await self._on_new(db, session, customer_token, message)
        # "Start over" only applies where a restart is a legal transition. Mid-collection it
        # is just another message, which the state handler answers normally. Routing it
        # unconditionally used to raise TransitionNotAllowed and surface as a 500.
        if looks_like_restart(message) and preconditions_met(state, Event.RESTART):
            return await self._on_restart(db, session, customer_token)
        if state is State.AWAITING_AMOUNT:
            return await self._on_amount(db, session, customer_token, message)
        if state is State.AWAITING_DOCUMENT:
            return await self._on_awaiting_document(db, session, customer_token, message)
        return await self._on_terminal(db, session, message)

    async def _on_new(self, db, session, customer_token, message) -> TurnResult:
        try:
            profile = await self.core.profile(customer_token=customer_token)
        except CoreServiceError as exc:
            return self._fail(db, session, exc)

        self._advance(db, session, Event.GREETING)
        first_name = profile["name"].split(" ")[0]
        reply = await self._maybe_phrase(
            db,
            session,
            customer_token=customer_token,
            first_name=first_name,
            band=profile.get("credit_score_band", "good"),
            message=message,
            fallback=replies.greeting(
                first_name=first_name,
                limit_paise=profile.get("pre_approved_limit_paise"),
                limit_source=profile.get("limit_source", "offered"),
            ),
        )
        self._add_message(db, session, "assistant", reply)
        return TurnResult(
            session_id=session.id,
            state=State(session.state),
            reply=reply,
            suggested_actions=["I need 2 lakh for 36 months", "What is my pre-approved limit?"],
        )

    async def _on_question(
        self, db, session, customer_id: str, message: str
    ) -> TurnResult:
        """Delegate to the LangGraph orchestrator. Never changes the workflow state."""
        assert self.agents is not None
        self._advance(db, session, Event.SMALLTALK)
        try:
            result = await self.agents.ask(
                message, customer_id, document_id=getattr(session, "last_document_id", None)
            )
        except AgentsUnavailable:
            reply = replies.agents_unavailable()
            self._add_message(db, session, "assistant", reply)
            return TurnResult(
                session_id=session.id,
                state=State(session.state),
                reply=reply,
                intent="agents_unavailable",
            )

        reply = result.get("answer") or replies.agents_unavailable()
        route = result.get("route") or []
        # The worker already asks for anything it is missing (amount, tenure), so do not
        # append a second prompt here — it read as the assistant repeating itself.

        self._add_message(db, session, "assistant", reply)
        return TurnResult(
            session_id=session.id,
            state=State(session.state),
            reply=reply,
            intent="agents",
            agent_route=route,
            citations=result.get("citations") or [],
        )

    def _on_support(self, db, session) -> TurnResult:
        """Support is a side channel: it answers without moving the workflow."""
        self._advance(db, session, Event.SMALLTALK)
        reply = replies.contact_options()
        self._add_message(db, session, "assistant", reply)
        return TurnResult(
            session_id=session.id,
            state=State(session.state),
            reply=reply,
            intent="contact",
            suggested_actions=["Contact support"],
        )

    async def _on_restart(self, db, session, customer_token) -> TurnResult:
        self._advance(db, session, Event.RESTART)
        session.application_id = None
        session.requested_amount_paise = None
        session.tenure_months = None
        db.flush()
        reply = replies.restart()
        self._add_message(db, session, "assistant", reply)
        return TurnResult(session_id=session.id, state=State(session.state), reply=reply)

    async def _on_amount(self, db, session, customer_token, message) -> TurnResult:
        parsed = parse_amount(message)
        if parsed is None:
            if looks_like_greeting(message) or looks_like_upload(message):
                self._advance(db, session, Event.SMALLTALK)
                reply = replies.amount_missing()
            else:
                self._advance(db, session, Event.AMOUNT_MISSING)
                reply = replies.amount_missing()
            self._add_message(db, session, "assistant", reply)
            return TurnResult(session_id=session.id, state=State(session.state), reply=reply)

        tenure = parse_tenure(message) or DEFAULT_TENURE_MONTHS
        session.requested_amount_paise = parsed.rupees * 100
        session.tenure_months = tenure
        db.flush()

        try:
            application = await self.core.create_application(
                customer_token=customer_token,
                amount_rupees=parsed.rupees,
                tenure_months=tenure,
                idempotency_key=f"{session.id}:{parsed.rupees}:{tenure}",
            )
        except CoreServiceError as exc:
            return self._fail(db, session, exc)

        session.application_id = application["application_id"]
        db.flush()
        return await self._apply_outcome(db, session, customer_token, application)

    async def _apply_outcome(self, db, session, customer_token, application) -> TurnResult:
        decision = application.get("decision") or {}
        outcome = decision.get("outcome")
        amount_paise = application["requested_amount_paise"]

        if outcome == "approve":
            self._advance(db, session, Event.OUTCOME_APPROVED)
            sanction = await self.core.issue_sanction(customer_token, application["application_id"])
            reply = replies.approved(
                amount_paise=amount_paise,
                emi_paise=decision["emi_paise"],
                tenure_months=decision["tenure_months"],
                rate=decision["interest_rate_percent"],
            )
            reply = f"{reply}\n\n{replies.sanction_ready(sanction['document_id'], amount_paise)}"
            self._add_message(db, session, "assistant", reply)
            return TurnResult(
                session_id=session.id,
                state=State(session.state),
                reply=reply,
                application=application,
                sanction_document_id=sanction["document_id"],
                suggested_actions=["Start a new application"],
            )

        if outcome == "require_document":
            self._advance(db, session, Event.OUTCOME_DOCUMENT_REQUIRED)
            reply = replies.document_required(amount_paise)
            self._add_message(db, session, "assistant", reply)
            return TurnResult(
                session_id=session.id,
                state=State(session.state),
                reply=reply,
                application=application,
                suggested_actions=["Upload salary slip"],
            )

        # reject
        self._advance(db, session, Event.OUTCOME_REJECTED)
        reply = replies.rejected(decision.get("reason_codes", []))
        self._add_message(db, session, "assistant", reply)
        return TurnResult(
            session_id=session.id,
            state=State(session.state),
            reply=reply,
            application=application,
            suggested_actions=["Start a new application"],
        )

    async def _on_awaiting_document(self, db, session, customer_token, message) -> TurnResult:
        if parse_amount(message):
            # A new request supersedes the pending one.
            self._advance(db, session, Event.AMOUNT_PROVIDED)
            return await self._on_amount(db, session, customer_token, message)
        self._advance(db, session, Event.DOCUMENT_PENDING)
        reply = replies.document_pending()
        self._add_message(db, session, "assistant", reply)
        return TurnResult(
            session_id=session.id,
            state=State(session.state),
            reply=reply,
            suggested_actions=["Upload salary slip"],
        )

    async def _on_terminal(self, db, session, message) -> TurnResult:
        self._advance(db, session, Event.SMALLTALK)
        if State(session.state) is State.SANCTIONED:
            reply = (
                "Your loan is sanctioned and the letter is available in this conversation. "
                "Say \"new application\" if you'd like to apply again."
            )
        elif State(session.state) is State.REJECTED:
            reply = (
                "That application was declined. You can apply for a lower amount, or say "
                "\"new application\" to try again."
            )
        else:
            reply = replies.smalltalk(session.state)
        self._add_message(db, session, "assistant", reply)
        return TurnResult(session_id=session.id, state=State(session.state), reply=reply)

    # --- document upload -------------------------------------------------
    async def handle_upload(
        self,
        db: Session,
        *,
        customer_id: str,
        customer_token: str,
        session_id: str,
        filename: str,
        content: bytes,
        content_type: str,
        doc_type: str = "salary_slip",
    ) -> TurnResult:
        session = self.get_or_create_session(db, customer_id, session_id)
        if State(session.state) is not State.AWAITING_DOCUMENT:
            raise TransitionNotAllowed(State(session.state), Event.DOCUMENT_RECEIVED)

        try:
            document = await self.core.upload_document(
                customer_token,
                filename=filename,
                content=content,
                content_type=content_type,
                doc_type=doc_type,
                application_id=session.application_id,
            )
            document = await self.core.process_document(customer_token, document["document_id"])
        except CoreServiceError as exc:
            return self._fail(db, session, exc)

        self._add_message(db, session, "customer", f"[document uploaded: {doc_type}]")
        reply = replies.document_received(
            document["status"], document.get("requires_review", False), document.get("verified_income_paise")
        )

        if document.get("requires_review") or not document.get("verified_income_paise"):
            self._advance(db, session, Event.DOCUMENT_PENDING)
            self._add_message(db, session, "assistant", reply)
            return TurnResult(
                session_id=session.id, state=State(session.state), reply=reply, document=document
            )

        if session.application_id is None:  # cannot happen in this state, but be explicit
            raise NotFoundError("No application is attached to this conversation.")

        # Record the arrival as its own step, so the trace reads: awaiting_document ->
        # assessing -> sanctioned, rather than jumping straight to a decision.
        self._advance(db, session, Event.DOCUMENT_RECEIVED)
        try:
            application = await self.core.re_evaluate(customer_token, session.application_id)
        except CoreServiceError as exc:
            return self._fail(db, session, exc)

        outcome = await self._apply_outcome(db, session, customer_token, application)
        outcome.reply = f"{reply}\n\n{outcome.reply}"
        outcome.document = document
        return outcome

    # --- status ----------------------------------------------------------
    async def status(self, db: Session, *, customer_token: str, session_id: str) -> dict:
        session = db.get(ConversationSession, session_id)
        if session is None:
            raise LookupError("session not found")
        application = None
        if session.application_id:
            try:
                application = await self.core.application(customer_token, session.application_id)
            except CoreServiceError:
                application = None
        return {
            "session_id": session.id,
            "state": session.state,
            "customer_id": session.customer_id,
            "application": application,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
        }

    def _fail(self, db: Session, session: ConversationSession, exc: CoreServiceError) -> TurnResult:
        logger.warning("core call failed", extra={"session_id": session.id, "code": exc.code})
        # A policy refusal is safe to relay verbatim; a transport failure is not.
        reply = exc.message if exc.status_code == 409 else replies.unavailable()
        self._add_message(db, session, "assistant", reply)
        return TurnResult(session_id=session.id, state=State(session.state), reply=reply)
