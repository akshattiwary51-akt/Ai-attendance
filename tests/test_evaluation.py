"""Evaluation metrics on synthetic embeddings with known ground truth, plus the folder extraction with fake engines."""
import numpy as np
import pytest
from PIL import Image

from src.evaluation import datasets, identification as ev
from src.pipelines.face_matching import MatchPolicy

rng = np.random.default_rng(3)
CENTRES = {f"p{i}": rng.normal(size=32) for i in range(8)}


def samples(people, n, noise=0.05):
    return {p: [(CENTRES[p] + noise * rng.normal(size=32)).tolist() for _ in range(n)] for p in people}


COS = MatchPolicy("cosine", 0.8, 0.0)


def test_well_separated_identities_are_perfect():
    ds = ev.build_dataset(samples(list(CENTRES), 5), enrol=2, holdout=["p6", "p7"])
    m = ev.evaluate(ds, COS)
    assert (m.genuine, m.impostor) == (6 * 3, 2 * 5)
    assert m.far == 0 and m.frr == 0 and m.misid == 0 and m.accuracy == 1 and m.precision == 1 and m.recall == 1


def test_impossible_threshold_rejects_everyone():
    ds = ev.build_dataset(samples(list(CENTRES), 4), enrol=1, holdout=["p7"])
    m = ev.evaluate(ds, MatchPolicy("cosine", 1.01, 0.0))
    assert m.frr == 1 and m.far == 0 and m.recall == 0 and m.precision is None


def test_zero_threshold_accepts_impostors():
    ds = ev.build_dataset(samples(list(CENTRES), 4), enrol=1, holdout=["p7"])
    m = ev.evaluate(ds, MatchPolicy("cosine", -1.0, 0.0))
    assert m.far == 1 and m.frr == 0


def test_far_is_none_without_impostors_and_reported():
    ds = ev.build_dataset(samples(["p0", "p1"], 4), enrol=2)
    m = ev.evaluate(ds, COS)
    assert m.far is None and m.far_ci is None
    assert any("FAR could not be measured" in w for w in ev.warnings_for(ds, [m]))
    assert ev.suggest_threshold([m]) is None


def test_people_with_too_few_samples_are_skipped():
    s = samples(["p0", "p1"], 4); s["p2"] = samples(["p2"], 2)["p2"]
    ds = ev.build_dataset(s, enrol=2)
    assert ds.skipped == ["p2"] and "p2" not in ds.gallery


def test_wilson_interval_brackets_the_rate_and_is_wide_for_small_n():
    lo, hi = ev.wilson(0, 10)
    assert lo == 0 and 0.2 < hi < 0.4
    lo, hi = ev.wilson(50, 100)
    assert lo < 0.5 < hi
    assert ev.wilson(0, 0) is None


def test_overlapping_identities_show_errors_and_sweep_trades_far_for_frr():
    near = {"a": rng.normal(size=16)}; near["b"] = near["a"] + 0.5 * rng.normal(size=16); near["c"] = rng.normal(size=16)
    s = {k: [(v + 0.4 * rng.normal(size=16)).tolist() for _ in range(30)] for k, v in near.items()}
    ds = ev.build_dataset(s, enrol=3, holdout=["c"])
    rows = ev.sweep(ds, COS, [0.2, 0.5, 0.8, 0.95])
    assert rows[0].far >= rows[-1].far and rows[0].frr <= rows[-1].frr
    pick = ev.suggest_threshold(rows, max_far=0.5)
    assert pick is not None and pick.far <= 0.5


def test_markdown_report_has_sections_and_no_embeddings():
    ds = ev.build_dataset(samples(list(CENTRES), 4), enrol=2, holdout=["p7"])
    md = ev.to_markdown("T", ds, COS, ev.sweep(ds, COS, ev.default_thresholds("cosine")), 0.01)
    for part in ("# T", "Threshold sweep", "Suggested threshold", "Score distributions", "Caveats", "THIS dataset"):
        assert part in md
    assert "0." in md and "[" not in md


class Face:
    def __init__(self, e): self.embedding = np.asarray(e)


class FakeEngine:
    def detect_and_embed(self, arr):
        n = int(arr[0, 0, 0])   # first pixel's red channel = number of faces in the 'photo'
        return [Face(np.ones(4) * (k + 1)) for k in range(n)]


def test_face_folder_extraction_counts_unusable_files(tmp_path):
    for person, counts in {"anna": [1, 1, 0], "ben": [1, 2]}.items():
        d = tmp_path / person; d.mkdir()
        for i, n in enumerate(counts):
            Image.new("RGB", (8, 8), (n, 0, 0)).save(d / f"{i}.png")
    (tmp_path / "anna" / "bad.jpg").write_bytes(b"junk")
    (tmp_path / ".hidden").mkdir()
    emb, skipped = datasets.face_embeddings(tmp_path, FakeEngine())
    assert {p: len(v) for p, v in emb.items()} == {"anna": 2, "ben": 1}
    assert skipped["no_face"] == 1 and skipped["several_faces"] == 1 and skipped["unreadable"] == 1


class FakeVoice:
    def decode(self, b): return np.frombuffer(b, dtype=np.uint8).astype(float)
    def embed(self, w): return w[:4]


def test_voice_folder_extraction_applies_the_quality_gate(tmp_path):
    d = tmp_path / "anna"; d.mkdir()
    (d / "a.wav").write_bytes(bytes([1, 2, 3, 4, 5])); (d / "b.wav").write_bytes(bytes([9, 9, 9, 9, 9]))
    emb, skipped = datasets.voice_embeddings(tmp_path, FakeVoice(), assess=lambda w: type("Q", (), {"ok": w[0] < 5})())
    assert len(emb["anna"]) == 1 and skipped["poor_audio"] == 1


def test_cli_end_to_end_with_fake_engine(tmp_path, monkeypatch, capsys):
    import importlib.util, pathlib
    from src.services import recognition_service as rs

    class Eng:
        model_id = "fake"; metric = "cosine"; default_threshold = 0.8; default_margin = 0.0
        def detect_and_embed(self, arr):
            return [Face(CENTRES[f"p{int(arr[0, 0, 0])}"] + 0.02 * rng.normal(size=32))]

    for i in range(4):
        d = tmp_path / "data" / f"p{i}"; d.mkdir(parents=True)
        for j in range(4):
            Image.new("RGB", (8, 8), (i, 0, 0)).save(d / f"{j}.png")
    monkeypatch.setattr(rs, "current_engine", lambda: Eng())
    spec = importlib.util.spec_from_file_location("evaluate_models", pathlib.Path(__file__).parent.parent / "scripts" / "evaluate_models.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    out = tmp_path / "r.md"
    assert mod.main(["face", "--data", str(tmp_path / "data"), "--holdout", "1", "--out", str(out)]) == 0
    text = out.read_text()
    assert "Face identification (fake)" in text and "| FAR | 0.0%" in text
