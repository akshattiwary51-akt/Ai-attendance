"""Entry point of the attendance assistant: validate -> route (rules) or converse (LLM) -> answer. Read-only; nothing is ever written."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.assistant import llm, responder, router, tools as T
from src.assistant.limits import RateLimiter
from src.config.settings import get_settings
from src.security.principal import require_principal
from src.services import enrollment_service, subject_service
from src.utils.errors import AIError, AppError, AuthorizationError, ConfigurationError, ValidationError
from src.utils.logging import get_logger, log_event

log = get_logger(__name__)
MAX_QUESTION = 400
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


@dataclass(frozen=True)
class Answer:
    text: str
    tools: list[str] = field(default_factory=list)
    mode: str = "rules"


def clean_question(q: str) -> str:
    q = _CONTROL.sub(" ", q or "").strip()
    if not q:
        raise ValidationError("empty", user_message="Please type a question.")
    if len(q) > MAX_QUESTION:
        raise ValidationError("long", user_message=f"Please keep your question under {MAX_QUESTION} characters.")
    return q


def _my_subjects(p) -> list[dict]:
    if p.role == "STUDENT":
        return enrollment_service.student_subjects(p.student_id)
    return subject_service.list_teacher_subjects(p.teacher_id)


def limiter_for_session() -> RateLimiter:
    return RateLimiter(get_settings().assistant_rate_per_hour)


def ask(question: str, limiter: RateLimiter | None = None, client: llm.LLMClient | None = None) -> Answer:
    p = require_principal()
    if p.role not in ("STUDENT", "TEACHER"):
        raise AuthorizationError("assistant not for this role", user_message="The assistant is available to students and teachers.")
    q = clean_question(question)
    if limiter is not None and not limiter.allow():
        raise ValidationError("rate", user_message="You are asking a lot of questions. Please wait a little and try again.")
    mode = get_settings().assistant_mode
    if mode == "llm":
        try:
            text, used = llm.converse(q, p, client or llm.AnthropicClient())
            log_event(log, "assistant_answered", role=p.role, mode="llm", tools=",".join(used))
            return Answer(text, used, "llm")
        except (ConfigurationError, AIError) as exc:
            log.warning("assistant_llm_unavailable detail=%s - falling back to rules", type(exc).__name__)
    route = router.route(q, p.role, _my_subjects(p))
    if route.tool is None:
        text = route.clarify or "I can help with attendance questions, for example:\n" + "\n".join("- " + e for e in router.HELP[p.role])
        if route.options:
            text += " Options: " + ", ".join(route.options) + "."
        return Answer(text, [], "rules")
    try:
        result = T.run_tool(route.tool, route.args, p)
    except ValidationError as exc:
        return Answer(exc.user_message, [], "rules")
    log_event(log, "assistant_answered", role=p.role, mode="rules", tools=route.tool)
    return Answer(responder.render(route.tool, result), [route.tool], "rules")
