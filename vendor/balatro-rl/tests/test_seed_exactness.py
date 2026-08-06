"""test_seed_exactness.py — CI regression gate: seed-mode replay is bit-identical across processes.

Runs the same seed + action sequence through `python -m balatro_sim.replay --sha`
in *separate interpreter instances* under different PYTHONHASHSEED values and asserts
the draw-log sha256 fingerprint and run summary are byte-identical. This proves the
seed-mode draw log has no process-dependent component (hash randomization, dict/set
iteration order, interpreter state), so the replay-diff harness's fingerprint is
stable across CI runs and machines — the invariant the whole byte-exactness strategy
rests on.

The subprocess is a fresh `python -m` invocation from the repo root, so it exercises
the real CLI path (argparse, module import, capture) rather than an in-process helper.

Gate (opt-in; deselected by default via pytest.ini `addopts = -m "not ci_gate"`):

    python -m pytest tests/test_seed_exactness.py -m ci_gate
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE_SEED = "11"
GATE_STEPS = 400

pytestmark = pytest.mark.ci_gate


def _capture(hashseed: str, seed: str = GATE_SEED, steps: int = GATE_STEPS) -> str:
    """Run the replay CLI in a fresh interpreter with a fixed hash seed.

    Returns the single `--sha` output line (fingerprint + run summary).
    """
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = hashseed
    proc = subprocess.run(
        [sys.executable, "-m", "balatro_sim.replay", "--seed", seed,
         "--steps", str(steps), "--sha"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, (
        f"capture failed (exit {proc.returncode}) hashseed={hashseed}:\n{proc.stderr}"
    )
    return proc.stdout.strip()


class TestCrossProcessShaStability:
    """The gate itself: same seed+actions, different interpreter instances."""

    def test_sha_identical_across_processes_and_hashseeds(self):
        # "random" gives the subprocess a fresh, unpredictable hash seed each spawn —
        # the strongest possible probe for iteration-order leakage into the draw log.
        lines = [_capture(hs) for hs in ("0", "1", "42", "random")]
        assert len(set(lines)) == 1, (
            "draw-log sha256 / run summary differs across interpreter instances:\n"
            + "\n".join(lines)
        )

    def test_sha_matches_in_process_reference(self):
        # Sanity: the subprocess fingerprint equals the library's own in-process
        # capture for the same seed+steps, so the gate pins what replay.py computes.
        from balatro_sim.replay import capture_game

        _, summary = capture_game(GATE_SEED, steps=GATE_STEPS)
        assert summary["sha256"] in _capture("7")

    @staticmethod
    def _sha(line: str) -> str:
        # Compare the fingerprint field only, not the seed/steps summary fields —
        # otherwise the discrimination tests would pass even with a constant sha.
        return line.split()[0]

    def test_gate_discriminates_seeds(self):
        # The gate must not be trivially constant: a different seed diverges.
        assert (self._sha(_capture("0", seed=GATE_SEED))
                != self._sha(_capture("0", seed="12")))

    def test_gate_discriminates_steps(self):
        # And a shorter horizon diverges (fewer draws -> different fingerprint).
        # Both horizons must draw (records > 0) so the sha field itself differs.
        short = _capture("0", steps=200)
        assert "records=0" not in short          # the short run must draw too
        assert (self._sha(short)
                != self._sha(_capture("0", steps=GATE_STEPS)))
