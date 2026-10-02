from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vendor" / "balatro-rl"))

from balatro_sim.blind_dataset import DatasetWriter, SPLIT_VERSION, VERSION, action_key
from balatro_sim.eval_encoder import schema, _HAND_TYPE_ORDER


def upgrade_joker_row(joker: list[float]) -> list[float]:
    if len(joker) == 283:
        return joker
    if len(joker) != 264:
        raise ValueError(f"expected joker_dim 264 or 283, got {len(joker)}")
    extra = [0.0, 0.0, 0.0, 0.0, 1.0] + [0.0] * len(_HAND_TYPE_ORDER) + [1.0, 0.0]
    return joker + extra


def compute_surplus(trial: dict, ante: int) -> float | None:
    if trial.get("censored", False) or trial.get("clear") is None:
        return None
    score = trial.get("score")
    target = trial.get("target")
    clear = trial.get("clear")
    if score is None or target is None or not math.isfinite(score) or not math.isfinite(target):
        return None
    target = max(1.0, float(target))
    score = max(0.0, float(score))

    if clear:
        ratio = min(4.0, score / target)
        hands_left = 0.0
        dollars_delta = 0.0
        state = trial.get("state")
        if state and "context" in state and len(state["context"]) > 5:
            hands_left = float(state["context"][5])
        return math.log2(1.0 + ratio) + 0.25 * hands_left + 0.10 * dollars_delta
    else:
        ratio = min(1.0, score / target)
        return -(1.0 - ratio)


def migrate_dataset(input_path: Path, output_path: Path, max_rows: int | None = None) -> None:
    current_schema = schema()
    with input_path.open(encoding="utf-8") as fin:
        header = json.loads(fin.readline())
    header["schema"] = current_schema
    header["version"] = VERSION
    header["split_version"] = SPLIT_VERSION
    if output_path.exists():
        output_path.unlink()
    writer = DatasetWriter(output_path, header, resume=False)

    current_seed = None
    current_rows = []
    current_summary = {}
    rows_written = 0

    with input_path.open(encoding="utf-8") as fin:
        fin.readline()  # Skip header
        for line in fin:
            data = json.loads(line)
            if data.get("type") == "seed_complete":
                summary = data.get("summary", {})
                seed = data.get("seed")
                if current_seed is not None and current_seed == seed:
                    writer.write_seed(current_seed, current_rows, summary)
                    rows_written += len(current_rows)
                    current_seed = None
                    current_rows = []
                    current_summary = {}
                    if max_rows is not None and rows_written >= max_rows:
                        break
            else:
                seed = data.get("seed")
                if current_seed is not None and current_seed != seed:
                    writer.write_seed(current_seed, current_rows, current_summary)
                    rows_written += len(current_rows)
                    current_rows = []
                    if max_rows is not None and rows_written >= max_rows:
                        break
                current_seed = seed
                ante = data.get("ante", 1)
                for arm in data.get("arms", []):
                    for trial in arm.get("trials", []):
                        if "state" in trial and trial["state"] is not None:
                            jokers = trial["state"].get("jokers", [])
                            trial["state"]["jokers"] = [upgrade_joker_row(j) for j in jokers]
                        if "surplus" not in trial:
                            s = compute_surplus(trial, ante)
                            if s is not None:
                                trial["surplus"] = s
                current_rows.append(data)

        if current_seed is not None and current_rows:
            writer.write_seed(current_seed, current_rows, current_summary)
            rows_written += len(current_rows)

    print(f"Successfully migrated {rows_written} rows across {len(writer.completed)} seeds from {input_path} to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Migrate legacy decision datasets to 283-dim schema + surplus.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-rows", type=int, default=None)
    args = parser.parse_args()
    migrate_dataset(args.input, args.output, args.max_rows)


if __name__ == "__main__":
    main()
