"""Canonical first-party paths. Import this instead of hardcoding filenames.

Every generator / audit that reads the mechanics sheet should use
``REFERENCE_DOC`` so a rename only has to change one place.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REFERENCE_DOC = ROOT / "docs" / "reference" / "balatro-mechanics.md"
VENDOR_RL = ROOT / "vendor" / "balatro-rl"
VENDOR_RS = ROOT / "vendor" / "balatro-rs"
TOOLS = ROOT / "tools"
BENCH = ROOT / "bench"
