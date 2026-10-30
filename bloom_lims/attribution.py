"""Explicit verified initiators for native TapDB 11 transactions."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import uuid4

from daylily_tapdb.security_context import Attribution, invocation_attribution


@dataclass
class RequestIdentity:
    request_id: str
    attribution: Attribution | None = None
    revision_conflict: str | None = None
    conflicted_sessions: list = field(default_factory=list)


_identity: ContextVar[RequestIdentity | None] = ContextVar("bloom_write_identity", default=None)


def begin_request():
    return _identity.set(RequestIdentity(str(uuid4())))


def end_request(token):
    _identity.reset(token)


def current_attribution():
    state = _identity.get()
    return state.attribution if state is not None else invocation_attribution()


def verified_actor(*, kind: str, issuer: str, subject: str):
    from bloom_lims.config import get_settings
    state = _identity.get()
    if state is None:
        raise RuntimeError("Bloom authenticated writes require request identity scope")
    state.attribution = Attribution(kind, issuer, subject, get_settings().tapdb.owner_repo_name,
                                    state.request_id, state.request_id)
    return state.attribution


def verified_session(request):
    from daylily_auth_cognito.browser.session import load_session_principal
    from bloom_lims.config import get_settings
    principal = load_session_principal(request)
    if principal is None:
        raise ValueError("Bloom write identity requires a verified session")
    auth = get_settings().auth
    if principal.auth_mode == "external_broker":
        issuer = auth.external_broker.login_url
    elif principal.auth_mode == "cognito":
        issuer = f"https://cognito-idp.{auth.cognito_region}.amazonaws.com/{auth.cognito_user_pool_id}"
    else:
        raise ValueError("Unsupported authenticated writer mode")
    return verified_actor(kind="human", issuer=issuer, subject=principal.user_sub)


def verified_token(token_id: str):
    from bloom_lims.gui.web_session import build_bloom_web_session_config
    issuer = build_bloom_web_session_config().public_base_url.rstrip("/") + "/auth/api-token"
    # This authenticates a delegated credential, not an asserted upstream human.
    return verified_actor(kind="service", issuer=issuer, subject=token_id)


@contextmanager
def explicit_attribution(value: Attribution | None):
    """Snapshot one task's initiator; never inherit a reused executor's actor."""
    token = _identity.set(RequestIdentity(value.request_id if value else str(uuid4()), value))
    try:
        yield
    finally:
        _identity.reset(token)


def record_revision_conflict(message: str, session=None) -> None:
    state = _identity.get()
    if state is not None:
        state.revision_conflict = message
        if session is not None and session not in state.conflicted_sessions:
            state.conflicted_sessions.append(session)


def current_revision_conflict() -> str | None:
    state = _identity.get()
    return state.revision_conflict if state is not None else None


def rollback_conflicted_sessions() -> None:
    """Called after ORM execution unwinds, before returning a conflict response."""
    state = _identity.get()
    if state is not None:
        while state.conflicted_sessions:
            state.conflicted_sessions.pop().rollback()
