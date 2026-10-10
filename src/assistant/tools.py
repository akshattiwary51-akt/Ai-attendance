"""The assistant's ONLY way to read data: a fixed set of read-only, role-scoped, validated functions.

Security properties (each is covered by a test):
  * the model/user never supplies an identity: student/teacher ids come from the logged-in principal;
  * a tool is callable only by its declared roles (a student cannot call a teacher tool even if the model asks);
  * arguments are validated against the tool's schema (types, ranges, enums, no unknown keys) before anything runs;
  * tools call the normal services, so Postgres RLS still decides what rows exist for this user;
  * there is no SQL, no write, no file or network access anywhere in this package;
  * names coming from the database are sanitised before they are returned (they may reach an LLM as data)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from src.analytics import attendance_math as am
from src.security.principal import Principal, require_principal
from src.services import analytics_service, dashboard_service, subject_service
from src.utils.errors import AppError, AuthorizationError, ValidationError
from src.utils.timefmt import local_tz

MAX_ROWS = 25
_CTRL = re.compile(r"[\x00-\x1f\x7f<>`]")


def clean(text: Any, limit: int = 80) -> str:
    """Make database text safe to hand to a model or a chat bubble: no control characters, angle brackets or backticks; bounded length."""
    return " ".join(_CTRL.sub(" ", str(text)).split())[:limit].strip()


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict                      # JSON-schema subset: object with typed properties
    roles: frozenset[str]
    func: Callable[[Principal, dict], dict]

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.schema}


def validate(schema: dict, args: Any) -> dict:
    """Strict validation of a tool call's arguments against the JSON-schema subset used here."""
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ValidationError("args not object", user_message="That request could not be understood.")
    props = schema.get("properties", {})
    extra = set(args) - set(props)
    if extra:
        raise ValidationError(f"unknown args {sorted(extra)}", user_message="That request could not be understood.")
    for req in schema.get("required", []):
        if req not in args:
            raise ValidationError(f"missing {req}", user_message="That request is missing some details.")
    out = {}
    for k, v in args.items():
        spec = props[k]
        t = spec["type"]
        if t == "string":
            if not isinstance(v, str) or len(v) > spec.get("maxLength", 80):
                raise ValidationError(f"bad {k}", user_message="That request could not be understood.")
            if "enum" in spec and v not in spec["enum"]:
                raise ValidationError(f"bad enum {k}", user_message="That request could not be understood.")
        elif t in ("integer", "number"):
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or (t == "integer" and int(v) != v):
                raise ValidationError(f"bad {k}", user_message="That request could not be understood.")
            if not spec.get("minimum", float("-inf")) <= v <= spec.get("maximum", float("inf")):
                raise ValidationError(f"range {k}", user_message=f"That number is out of range ({spec.get('minimum')}-{spec.get('maximum')}).")
            v = int(v) if t == "integer" else float(v)
        else:
            raise ValidationError(f"unsupported type {t}", user_message="That request could not be understood.")
        out[k] = v
    return out


# ───────────────────────── subject resolution ─────────────────────────
_STOP = frozenset({"class", "classes", "attendance", "the", "and", "for", "course", "subject", "lecture", "lectures", "intro", "introduction", "to", "of"})


def _alpha(code: str) -> str:
    """'DSA1' -> 'DSA': people say the course letters, not the section/number suffix."""
    return re.sub(r"\d+$", "", str(code))


def resolve_subject(query: str | None, subjects: list[dict]) -> tuple[dict | None, list[dict]]:
    """(match, candidates). match is set only when exactly one of the user's OWN subjects fits; otherwise candidates lists the ambiguity
    (empty list = nothing matched). Priority: exact code, exact name, then unique word match on code/name."""
    if not query or not query.strip():
        return None, []
    q = query.strip().lower()
    for key in ("subject_code", "name"):
        hits = [s for s in subjects if str(s[key]).lower() == q]
        if len(hits) == 1:
            return hits[0], []
        if len(hits) > 1:
            return None, hits
    words = {w for w in re.findall(r"[a-z0-9]+", q) if w not in _STOP and len(w) >= 2}
    hits = []
    for s in subjects:
        pool = set(re.findall(r"[a-z0-9]+", f"{s['subject_code']} {s['name']} {_alpha(s['subject_code'])}".lower())) - _STOP
        if words & pool or any(w and pool_w.startswith(w) and len(w) >= 3 for w in words for pool_w in pool):
            hits.append(s)
    return (hits[0], []) if len(hits) == 1 else (None, hits)


def _need_one(query: str | None, subjects: list[dict]) -> tuple[dict | None, dict | None]:
    sub, cands = resolve_subject(query, subjects)
    if sub:
        return sub, None
    if cands:
        return None, {"error": "ambiguous_subject", "message": "Which subject do you mean?", "options": [clean(c["name"]) + f" ({clean(c['subject_code'])})" for c in cands[:6]]}
    return None, {"error": "subject_not_found", "message": "I could not find that subject among yours.", "options": []}


# ───────────────────────── student tools ─────────────────────────
def _student_rows(p: Principal):
    ov = dashboard_service.student_overview(p.student_id)
    return ov, [{**s, "_standing": st} for s, st in ov.subjects]


def _row(s: dict) -> dict:
    st = s["_standing"]
    return {"subject": clean(s["name"]), "code": clean(s["subject_code"]), "attended": st.attended, "conducted": st.conducted,
            "percentage": st.percentage, "target": st.target, "can_miss": st.can_miss, "risk": st.risk}


def get_my_attendance(p: Principal, a: dict) -> dict:
    ov, rows = _student_rows(p)
    if a.get("subject"):
        sub, err = _need_one(a["subject"], rows)
        return err or {"subjects": [_row(sub)]}
    return {"overall_percentage": ov.overall_percentage, "attended": ov.attended, "conducted": ov.conducted, "subjects": [_row(r) for r in rows][:MAX_ROWS]}


def can_i_miss(p: Principal, a: dict) -> dict:
    _, rows = _student_rows(p)
    sub, err = _need_one(a["subject"], rows)
    if err:
        return err
    st, n = sub["_standing"], a["classes"]
    after = am.percentage(st.attended, st.conducted + n)
    return {"subject": clean(sub["name"]), "classes": n, "conducted": st.conducted, "attended": st.attended, "target": st.target,
            "max_can_miss": st.can_miss, "allowed": st.conducted > 0 and n <= st.can_miss, "percentage_now": st.percentage, "percentage_after": after,
            "has_data": st.conducted > 0}


def classes_needed(p: Principal, a: dict) -> dict:
    _, rows = _student_rows(p)
    if a.get("subject"):
        sub, err = _need_one(a["subject"], rows)
        if err:
            return err
        rows = [sub]
    out = []
    for r in rows[:MAX_ROWS]:
        st = r["_standing"]
        target = a.get("target", st.target)
        need = am.classes_to_recover(st.attended, st.conducted, target)
        out.append({"subject": clean(r["name"]), "attended": st.attended, "conducted": st.conducted, "target": target,
                    "already_meets": am.meets_target(st.attended, st.conducted, target) if st.conducted else False,
                    "consecutive_classes_needed": need, "has_data": st.conducted > 0})
    return {"subjects": out}


def my_risk_subjects(p: Principal, a: dict) -> dict:
    _, rows = _student_rows(p)
    risky = [r for r in rows if r["_standing"].risk in (am.HIGH, am.MEDIUM)]
    return {"subjects": [{**_row(r), "reasons": [clean(x, 200) for x in r["_standing"].reasons]} for r in risky][:MAX_ROWS], "checked": len(rows)}


def my_forecast(p: Principal, a: dict) -> dict:
    sa = analytics_service.student_analytics(p.student_id)
    items = [(s, f) for s, f in sa.forecasts if f.risk != am.NO_DATA]
    if a.get("subject"):
        sub, err = _need_one(a["subject"], [s for s, _ in items])
        if err:
            return err
        items = [(s, f) for s, f in items if s["subject_id"] == sub["subject_id"]]
    return {"subjects": [{"subject": clean(s["name"]), "chance_below_target": f.prob_below_target, "expected_percentage": f.expected_pct,
                          "likely_range": list(f.interval_pct), "risk": f.risk, "confidence": f.confidence, "reasons": [clean(x, 200) for x in f.reasons]}
                         for s, f in items][:MAX_ROWS]}


# ───────────────────────── teacher tools ─────────────────────────
def _teacher_subjects(p: Principal) -> list[dict]:
    return subject_service.list_teacher_subjects(p.teacher_id)


def students_below(p: Principal, a: dict) -> dict:
    thr = a["threshold"]
    subjects = _teacher_subjects(p)
    if a.get("subject"):
        sub, err = _need_one(a["subject"], subjects)
        if err:
            return err
        d = dashboard_service.subject_detail(p.teacher_id, sub["subject_id"])
        rows = [{"student": clean(s["name"]), "subject": clean(sub["name"]), "percentage": s["standing"].percentage} for s in d["students"]
                if s["standing"].conducted and s["standing"].percentage < thr]
    else:
        rows = [{"student": clean(x["name"]), "subject": "all subjects", "percentage": x["percentage"]} for x in dashboard_service.students_overview(p.teacher_id)
                if x["conducted"] and x["percentage"] < thr]
    rows.sort(key=lambda r: (r["percentage"], r["student"].lower()))
    return {"threshold": thr, "count": len(rows), "students": rows[:MAX_ROWS], "truncated": len(rows) > MAX_ROWS}


def subject_attendance(p: Principal, a: dict) -> dict:
    sub, err = _need_one(a["subject"], _teacher_subjects(p))
    return err or analytics_service.subject_period_summary(p.teacher_id, sub["subject_id"], a.get("period", "all")) | {"subject": clean(sub["name"])}


def students_missed_last(p: Principal, a: dict) -> dict:
    subjects = _teacher_subjects(p)
    targets = subjects
    if a.get("subject"):
        sub, err = _need_one(a["subject"], subjects)
        if err:
            return err
        targets = [sub]
    results = [analytics_service.students_missed_last(p.teacher_id, s["subject_id"], a["classes"]) for s in targets[:10]]
    return {"classes": a["classes"], "subjects": [{"subject": clean(r["subject"]), "students": [clean(n) for n in r["students"]][:MAX_ROWS],
                                                    "completed_classes": r["completed_classes"]} for r in results]}


def todays_summary(p: Principal, a: dict) -> dict:
    day = datetime.now(local_tz()).date()
    ids = [s["subject_id"] for s in _teacher_subjects(p)]
    names = {s["subject_id"]: clean(s["name"]) for s in _teacher_subjects(p)}
    rows = analytics_service.sessions_on(day, ids)
    return {"date": day.isoformat(), "sessions": [{"subject": names.get(r["subject_id"], "?"), "status": r["status"], "method": r["method"],
                                                    "present": r["present"] + r["late"], "absent": r["absent"], "excused": r["excused"]} for r in rows][:MAX_ROWS]}


def at_risk_students(p: Principal, a: dict) -> dict:
    ov = dashboard_service.teacher_overview(p.teacher_id)
    rows = ov.at_risk
    if a.get("subject"):
        sub, err = _need_one(a["subject"], _teacher_subjects(p))
        if err:
            return err
        rows = [r for r in rows if r["subject"] == sub["name"]]
    return {"count": len(rows), "students": [{"student": clean(r["name"]), "subject": clean(r["subject"]), "percentage": r["percentage"], "risk": r["risk"],
                                              "reason": clean(r["reason"], 200)} for r in rows[:MAX_ROWS]], "truncated": len(rows) > MAX_ROWS}


S, T = frozenset({"STUDENT"}), frozenset({"TEACHER"})
_SUBJ = {"type": "string", "maxLength": 80, "description": "Subject name or code as the user wrote it"}


def _obj(props: dict, required: list[str] = ()) -> dict:
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("get_my_attendance", "The student's own attendance: overall and per subject (attended, conducted, percentage, target).", _obj({"subject": _SUBJ}), S, get_my_attendance),
    Tool("can_i_miss", "Whether the student can miss N more classes of a subject and stay at/above its target, and the percentage afterwards.",
         _obj({"subject": _SUBJ, "classes": {"type": "integer", "minimum": 1, "maximum": 50}}, ["subject", "classes"]), S, can_i_miss),
    Tool("classes_needed", "How many consecutive classes the student must attend to reach a target percentage (default: the subject's target).",
         _obj({"subject": _SUBJ, "target": {"type": "number", "minimum": 1, "maximum": 100}}), S, classes_needed),
    Tool("my_risk_subjects", "The student's subjects at medium or high attendance risk, with reasons.", _obj({}), S, my_risk_subjects),
    Tool("my_forecast", "Forecast of the student's attendance over the next month: chance of ending below target and expected percentage.", _obj({"subject": _SUBJ}), S, my_forecast),
    Tool("students_below", "Students whose attendance is below a percentage, overall or in one subject.",
         _obj({"threshold": {"type": "number", "minimum": 1, "maximum": 100}, "subject": _SUBJ}, ["threshold"]), T, students_below),
    Tool("subject_attendance", "Attendance totals for one subject over a period (all, this_week, this_month).",
         _obj({"subject": _SUBJ, "period": {"type": "string", "enum": ["all", "this_week", "this_month"]}}, ["subject"]), T, subject_attendance),
    Tool("students_missed_last", "Students who missed each of the last N classes, in one subject or all of the teacher's subjects.",
         _obj({"classes": {"type": "integer", "minimum": 1, "maximum": 10}, "subject": _SUBJ}, ["classes"]), T, students_missed_last),
    Tool("todays_summary", "Today's attendance sessions: present / absent / excused counts per subject.", _obj({}), T, todays_summary),
    Tool("at_risk_students", "Students at medium or high attendance risk, overall or in one subject, with reasons.", _obj({"subject": _SUBJ}), T, at_risk_students),
]}


def specs_for(role: str) -> list[dict]:
    return [t.spec() for t in TOOLS.values() if role in t.roles]


def run_tool(name: str, args: Any, principal: Principal | None = None) -> dict:
    """Validate and execute one tool call as the logged-in user. Expected problems come back as {"error": ...} for the model/user to read;
    authorization failures and unknown tools raise."""
    p = principal or require_principal()
    tool = TOOLS.get(name)
    if tool is None:
        raise ValidationError(f"unknown tool {name}", user_message="That request could not be understood.")
    if p.role not in tool.roles:
        raise AuthorizationError(f"role {p.role} may not call {name}")
    clean_args = validate(tool.schema, args)
    try:
        return tool.func(p, clean_args)
    except AppError as exc:
        return {"error": "unavailable", "message": exc.user_message}
