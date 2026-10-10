"""Deterministic intent router: plain-language question -> one tool call. Works with no LLM, no network and no API key.
It only chooses a tool and extracts simple arguments; it never touches data and never builds queries."""
from __future__ import annotations

import re
from dataclasses import dataclass

from src.assistant.tools import _STOP, _alpha

WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_NUM = r"(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten)"


@dataclass(frozen=True)
class Route:
    tool: str | None
    args: dict
    clarify: str | None = None          # a question to ask the user instead of calling a tool
    options: tuple[str, ...] = ()


def to_int(token: str) -> int:
    return int(token) if token.isdigit() else WORDS[token]


def find_subject_mention(text: str, subjects: list[dict]) -> tuple[str | None, list[dict]]:
    """(subject_code, ambiguous candidates) for a subject the user mentions by code, full name or a distinctive name word."""
    t = text.lower()
    exact = [s for s in subjects if re.search(rf"(?<![a-z0-9]){re.escape(str(s['subject_code']).lower())}(?![a-z0-9])", t)
             or re.search(rf"(?<![a-z0-9]){re.escape(str(s['name']).lower())}(?![a-z0-9])", t)]
    if len(exact) == 1:
        return exact[0]["subject_code"], []
    if len(exact) > 1:
        return None, exact
    tokens = set(re.findall(r"[a-z0-9]+", t))
    loose = []
    for s in subjects:
        pool = {w for w in re.findall(r"[a-z0-9]+", f"{s['name']} {s['subject_code']} {_alpha(s['subject_code'])}".lower()) if w not in _STOP and len(w) >= 3}
        if tokens & pool:
            loose.append(s)
    if len(loose) == 1:
        return loose[0]["subject_code"], []
    return None, loose


def _pct(text: str) -> float | None:
    m = re.search(r"(\d{1,3}(?:\.\d+)?)\s*(?:%|percent|per cent)", text)
    return float(m.group(1)) if m else None


def route(question: str, role: str, subjects: list[dict]) -> Route:
    q = " ".join(question.lower().split())
    code, ambiguous = find_subject_mention(q, subjects)
    subj = {"subject": code} if code else {}

    def need_subject(tool: str, args: dict) -> Route:
        if code:
            return Route(tool, {**args, **subj})
        if ambiguous:
            return Route(None, {}, "Which subject do you mean?", tuple(f"{s['name']} ({s['subject_code']})" for s in ambiguous[:6]))
        return Route(None, {}, "Which subject do you mean?", tuple(f"{s['name']} ({s['subject_code']})" for s in subjects[:6]))

    if role == "STUDENT":
        if re.search(r"\b(can|could|may|will|am i able to|is it ok(?:ay)? (?:if i|to))\b.*\b(miss|skip|bunk|be absent|take leave)\b", q) or re.search(r"\bmiss\b.*\bmore\b", q):
            m = re.search(rf"\b{_NUM}\s+(?:more\s+|extra\s+|other\s+)?(?:[a-z0-9]+\s+)?(?:class|classes|lecture|lectures|session|sessions)\b", q) or re.search(rf"\bmiss\s+{_NUM}\b", q)
            return need_subject("can_i_miss", {"classes": max(1, min(50, to_int(m.group(1)))) if m else 1})
        if re.search(r"\b(how many|how much|what)\b.*\b(need|have to|must|should)\b.*\b(attend|go|reach|get|hit|recover)|\breach\b.*\d+\s*%|\bget (?:back )?to\b.*\d+\s*%", q):
            args = {"target": min(100.0, max(1.0, _pct(q)))} if _pct(q) else {}
            return Route("classes_needed", {**args, **subj}) if (code or not ambiguous) else need_subject("classes_needed", args)
        if re.search(r"\b(forecast|predict|expect|projection|next month|will i (?:fall|drop|be below|end))\b", q):
            return Route("my_forecast", subj)
        if re.search(r"\b(at risk|risky|danger|in trouble|shortage|falling behind|below (?:the )?(?:target|limit)|which subjects?)\b", q):
            return Route("my_risk_subjects", {})
        if re.search(r"\b(attendance|percentage|percent|how am i doing|how many classes|present|attended|my record)\b", q):
            return Route("get_my_attendance", subj) if (code or not ambiguous) else need_subject("get_my_attendance", {})
        return Route(None, {}, None)

    if role == "TEACHER":
        m = re.search(rf"\b(?:missed|skipped|absent (?:from|in|for))\b.*\blast\s+{_NUM}\b", q) or re.search(rf"\blast\s+{_NUM}\s+(?:class|classes|session|sessions|lectures?)\b.*\b(?:missed|absent)", q)
        if m:
            return Route("students_missed_last", {"classes": max(1, min(10, to_int(m.group(1)))), **subj})
        m = re.search(r"\b(?:below|under|less than|lower than|fewer than)\s+(\d{1,3}(?:\.\d+)?)\s*(?:%|percent)?", q)
        if m:
            return Route("students_below", {"threshold": min(100.0, max(1.0, float(m.group(1)))), **subj})
        if re.search(r"\b(summar(?:y|ize|ise)|today|today's)\b", q):
            return Route("todays_summary", {})
        if re.search(r"\b(at.?risk|risky|struggling|need attention|worried)\b", q):
            return Route("at_risk_students", subj)
        if re.search(r"\b(attendance|how is|how's|show)\b", q):
            period = "this_month" if re.search(r"\b(this month|month)\b", q) else "this_week" if re.search(r"\b(this week|week)\b", q) else "all"
            return need_subject("subject_attendance", {"period": period})
        return Route(None, {}, None)
    return Route(None, {}, None)


HELP = {
    "STUDENT": ["What is my attendance?", "Can I miss 2 more DSA classes?", "Which subjects am I at risk in?",
                "How many classes do I need to attend to reach 80%?", "What is my forecast for next month?"],
    "TEACHER": ["Which students are below 75%?", "Show attendance for DSA this month.", "Which students have missed the last 3 classes?",
                "Summarize today's attendance.", "Who is at risk in DSA?"],
}
