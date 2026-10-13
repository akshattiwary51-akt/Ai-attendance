#!/usr/bin/env python
"""Measure face or voice identification on YOUR labelled data and suggest a threshold.

    python scripts/evaluate_models.py face  --data DIR [--enrol 2] [--holdout 3] [--max-far 0.01] [--out report.md]
    python scripts/evaluate_models.py voice --data DIR ...

DIR holds one sub-folder per person with several photos (face) or recordings (voice).
``--holdout N`` keeps the last N people (alphabetically) OUT of the gallery as impostors; or name them with
``--unknown alice,bob``. Without held-out people the false-accept rate cannot be measured, and the report says so.
Nothing here is a claim about the app's accuracy until you run it on representative data.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.evaluation import datasets, identification as ident  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("modality", choices=["face", "voice"])
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--enrol", type=int, default=2, help="samples per person used as the gallery (default 2)")
    ap.add_argument("--holdout", type=int, default=0, help="number of people kept out as impostors")
    ap.add_argument("--unknown", default="", help="comma-separated person folders to hold out")
    ap.add_argument("--max-far", type=float, default=0.01, help="target false-accept rate for the suggestion")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    if not args.data.is_dir():
        ap.error(f"{args.data} is not a directory")

    from src.config.settings import get_settings
    from src.services import recognition_service as rs

    if args.modality == "face":
        engine = rs.current_engine()
        emb, skipped = datasets.face_embeddings(args.data, engine)
        policy, title = rs.policy_for(engine), f"Face identification ({engine.model_id})"
    else:
        from src.pipelines import voice_quality
        from src.pipelines.voice_pipeline import default_backend
        s, backend = get_settings(), default_backend()
        emb, skipped = datasets.voice_embeddings(args.data, backend, lambda w: voice_quality.assess(w, s.voice_enrol_seconds, s.voice_min_snr_db))
        policy, title = rs.voice_policy(), f"Voice identification ({backend.model_id})"

    people = sorted(emb)
    hold = {x.strip() for x in args.unknown.split(",") if x.strip()} | set(people[len(people) - args.holdout:] if args.holdout > 0 else [])
    ds = ident.build_dataset(emb, enrol=args.enrol, holdout=sorted(hold))
    rows = ident.sweep(ds, policy, ident.default_thresholds(policy.metric))
    report = ident.to_markdown(title, ds, policy, rows, args.max_far)
    if skipped:
        report += "\nFiles not used: " + ", ".join(f"{k}={v}" for k, v in sorted(skipped.items())) + "\n"
    print(report)
    if args.out:
        args.out.write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
