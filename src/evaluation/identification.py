"""Offline evaluation of face / voice identification on a labelled dataset (pure numpy; no models, no database).

Protocol (open-set identification, the same matcher the app uses):
  * every *enrolled* person contributes their first ``enrol`` samples to the gallery;
  * their remaining samples are **genuine probes** (the right answer is that person);
  * every sample of a *held-out* person (never enrolled) is an **impostor probe** (the right answer is "nobody").

Definitions (rates are None when their denominator is 0, never silently 0):
  FAR  false-accept rate  = impostor probes recognised as *someone* / impostor probes
  FRR  false-reject rate  = genuine probes answered UNKNOWN or AMBIGUOUS / genuine probes
  misid                   = genuine probes recognised as the *wrong* enrolled person / genuine probes
  precision = correct identifications / all RECOGNIZED answers;  recall = correct identifications / genuine probes
  accuracy  = (correct identifications + impostors answered UNKNOWN/AMBIGUOUS) / all probes
Every rate carries a 95% Wilson interval: with small datasets the interval is the honest statement of what was measured.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np

from src.pipelines.face_matching import AMBIGUOUS, RECOGNIZED, MatchPolicy, match_face

MIN_IMPOSTORS_FOR_FAR = 100   # below this a FAR of ~1% cannot be resolved; reports say so


@dataclass(frozen=True)
class Probe:
    person: str
    embedding: Sequence[float]
    enrolled: bool          # False = impostor (held out)


@dataclass
class Dataset:
    gallery: dict[str, list[list[float]]]
    probes: list[Probe]
    skipped: list[str] = field(default_factory=list)   # people without enough samples


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n <= 0:
        return None
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def build_dataset(samples: Mapping[str, Sequence[Sequence[float]]], *, enrol: int = 2, holdout: Sequence[str] = ()) -> Dataset:
    """Split per-person embeddings into a gallery and probes. People with <= ``enrol`` samples cannot be genuine probes and are skipped."""
    if enrol < 1:
        raise ValueError("enrol must be >= 1")
    hold = set(holdout)
    ds = Dataset({}, [])
    for person in sorted(samples):
        embs = [list(map(float, e)) for e in samples[person]]
        if person in hold:
            ds.probes += [Probe(person, e, False) for e in embs]
        elif len(embs) <= enrol:
            ds.skipped.append(person)
        else:
            ds.gallery[person] = embs[:enrol]
            ds.probes += [Probe(person, e, True) for e in embs[enrol:]]
    return ds


@dataclass(frozen=True)
class Metrics:
    threshold: float
    genuine: int
    impostor: int
    correct: int
    misidentified: int
    false_rejected: int
    false_accepted: int
    correct_rejected: int
    far: float | None
    frr: float | None
    misid: float | None
    precision: float | None
    recall: float | None
    accuracy: float | None
    far_ci: tuple[float, float] | None
    frr_ci: tuple[float, float] | None


def _rate(k: int, n: int) -> float | None:
    return k / n if n else None


def evaluate(ds: Dataset, policy: MatchPolicy) -> Metrics:
    correct = mis = fr = fa = cr = 0
    for p in ds.probes:
        r = match_face(p.embedding, ds.gallery, policy)
        recognised = r.status == RECOGNIZED
        if p.enrolled:
            if recognised and r.student_id == p.person:
                correct += 1
            elif recognised:
                mis += 1
            else:
                fr += 1
        elif recognised:
            fa += 1
        else:
            cr += 1
    genuine, impostor = correct + mis + fr, fa + cr
    recognised_total = correct + mis + fa
    total = genuine + impostor
    return Metrics(policy.threshold, genuine, impostor, correct, mis, fr, fa, cr,
                   _rate(fa, impostor), _rate(fr, genuine), _rate(mis, genuine),
                   _rate(correct, recognised_total), _rate(correct, genuine), _rate(correct + cr, total),
                   wilson(fa, impostor), wilson(fr, genuine))


def sweep(ds: Dataset, base: MatchPolicy, thresholds: Sequence[float]) -> list[Metrics]:
    return [evaluate(ds, MatchPolicy(base.metric, float(t), base.margin, base.top_k)) for t in thresholds]


def default_thresholds(metric: str) -> list[float]:
    return [round(x, 2) for x in (np.arange(0.30, 0.801, 0.02) if metric == "euclidean" else np.arange(0.30, 0.951, 0.025))]


def suggest_threshold(rows: Sequence[Metrics], max_far: float = 0.01) -> Metrics | None:
    """Lowest-FRR row whose measured FAR is <= max_far (ties: lower FAR). None if FAR was not measurable or never met."""
    ok = [r for r in rows if r.far is not None and r.far <= max_far and r.frr is not None]
    if not ok:
        return None
    return min(ok, key=lambda r: (r.frr, r.far))


def score_distributions(ds: Dataset, policy: MatchPolicy) -> dict[str, dict[str, float] | None]:
    """Summary of the normalised best-match score for genuine vs impostor probes (a view of how separable they are)."""
    g: list[float] = []
    i: list[float] = []
    for p in ds.probes:
        r = match_face(p.embedding, ds.gallery, MatchPolicy(policy.metric, policy.threshold, 0.0, policy.top_k))
        (g if p.enrolled else i).append(r.score)

    def summary(v: list[float]):
        if not v:
            return None
        a = np.asarray(v)
        return {"n": len(a), "min": float(a.min()), "p5": float(np.percentile(a, 5)), "median": float(np.median(a)),
                "p95": float(np.percentile(a, 95)), "max": float(a.max())}
    return {"genuine": summary(g), "impostor": summary(i)}


def warnings_for(ds: Dataset, rows: Sequence[Metrics]) -> list[str]:
    out: list[str] = []
    genuine = sum(1 for p in ds.probes if p.enrolled)
    impostor = len(ds.probes) - genuine
    if not ds.gallery:
        out.append("No person had enough samples to enrol; nothing was evaluated.")
    if impostor == 0:
        out.append("No held-out people: FAR could not be measured. Provide people who are not enrolled.")
    elif impostor < MIN_IMPOSTORS_FOR_FAR:
        out.append(f"Only {impostor} impostor probes: false-accept rates below about {100 / impostor:.1f}% cannot be resolved.")
    if genuine < MIN_IMPOSTORS_FOR_FAR:
        out.append(f"Only {genuine} genuine probes: treat FRR as indicative, see the confidence intervals.")
    if ds.skipped:
        out.append(f"{len(ds.skipped)} people had too few samples and were skipped.")
    out.append("Results describe THIS dataset only; classroom lighting, cameras and demographics may differ.")
    return out


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _ci(ci) -> str:
    return "" if ci is None else f" ({100 * ci[0]:.1f}–{100 * ci[1]:.1f}%)"


def to_markdown(title: str, ds: Dataset, policy: MatchPolicy, rows: Sequence[Metrics], max_far: float) -> str:
    cur = evaluate(ds, policy)
    sug = suggest_threshold(rows, max_far)
    lines = [f"# {title}", "",
             f"People enrolled: {len(ds.gallery)} · genuine probes: {cur.genuine} · impostor probes: {cur.impostor}", "",
             f"## At the configured threshold ({policy.threshold}, margin {policy.margin}, metric {policy.metric})", "",
             "| Measure | Value |", "|---|---|",
             f"| FAR | {_pct(cur.far)}{_ci(cur.far_ci)} |", f"| FRR | {_pct(cur.frr)}{_ci(cur.frr_ci)} |",
             f"| Misidentified | {_pct(cur.misid)} |", f"| Precision | {_pct(cur.precision)} |",
             f"| Recall | {_pct(cur.recall)} |", f"| Accuracy | {_pct(cur.accuracy)} |", "",
             "## Threshold sweep", "", "| Threshold | FAR | FRR | Misid | Precision | Recall | Accuracy |", "|---|---|---|---|---|---|---|"]
    lines += [f"| {r.threshold} | {_pct(r.far)} | {_pct(r.frr)} | {_pct(r.misid)} | {_pct(r.precision)} | {_pct(r.recall)} | {_pct(r.accuracy)} |" for r in rows]
    lines += ["", f"## Suggested threshold (FAR ≤ {100 * max_far:g}%)", ""]
    lines.append(f"{sug.threshold} (FAR {_pct(sug.far)}, FRR {_pct(sug.frr)} on this dataset)" if sug
                 else "None: no threshold met the FAR target on this dataset (or FAR was not measurable).")
    d = score_distributions(ds, policy)
    lines += ["", "## Score distributions (normalised 0–1, higher = more similar)", "", "| Probes | n | min | p5 | median | p95 | max |", "|---|---|---|---|---|---|---|"]
    for k in ("genuine", "impostor"):
        s = d[k]
        lines.append(f"| {k} | " + (" | ".join([str(s['n'])] + [f"{s[x]:.3f}" for x in ('min', 'p5', 'median', 'p95', 'max')]) if s else "0 | – | – | – | – | –") + " |")
    lines += ["", "## Caveats", ""] + [f"- {w}" for w in warnings_for(ds, rows)]
    return "\n".join(lines) + "\n"
