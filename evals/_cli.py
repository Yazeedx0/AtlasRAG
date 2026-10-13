import argparse
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from evals.chunking.baselines import (
    FixedTokenChunker,
    FixedTokenConfig,
    HeadingAwareChunker,
    HeadingAwareConfig,
)
from evals.chunking.comparison import compare_chunkers, render_comparison_text
from evals.chunking.metrics import QualityThresholds
from evals.core.reporting import RunProvenance, dump_report
from evals.core.tokenization import (
    CL100K_TOKENIZER,
    DEFAULT_TOKENIZER,
    UNICODE_WORD_TOKENIZER,
    create_tokenizer,
)
from evals.datasets.loader import load_dataset

REPORTS_ROOT = Path(__file__).parent / "reports"


def _git_commit() -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="evals.chunking")
    parser.add_argument(
        "--tokenizer",
        choices=[UNICODE_WORD_TOKENIZER, CL100K_TOKENIZER],
        default=DEFAULT_TOKENIZER,
    )
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--min-tokens", type=int, default=32)
    parser.add_argument("--overlap-ratio", type=float, default=0.15)
    parser.add_argument("--reports-root", type=Path, default=REPORTS_ROOT)
    parser.add_argument("--run-label", default=None)
    parser.add_argument("--stamp-run", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    tokenizer = create_tokenizer(arguments.tokenizer)
    dataset = load_dataset()
    thresholds = QualityThresholds(
        max_tokens=arguments.max_tokens, min_tokens=arguments.min_tokens
    )
    provenance = RunProvenance(
        generated_at=datetime.now(tz=UTC).isoformat() if arguments.stamp_run else None,
        git_commit=_git_commit() if arguments.stamp_run else None,
        run_label=arguments.run_label,
    )

    report = compare_chunkers(
        baseline=FixedTokenChunker(
            tokenizer=tokenizer,
            config=FixedTokenConfig(
                max_tokens=arguments.max_tokens, overlap_ratio=arguments.overlap_ratio
            ),
        ),
        candidates=[
            HeadingAwareChunker(
                tokenizer=tokenizer,
                config=HeadingAwareConfig(max_tokens=arguments.max_tokens),
            )
        ],
        dataset=dataset,
        tokenizer=tokenizer,
        thresholds=thresholds,
        provenance=provenance,
    )

    reports_root: Path = arguments.reports_root
    reports_root.mkdir(parents=True, exist_ok=True)
    destination = reports_root / f"chunking-comparison-{report.fingerprint[:16]}.json"
    destination.write_text(dump_report(report) + "\n", encoding="utf-8")

    if not arguments.quiet:
        print(render_comparison_text(report))
        print(f"report: {destination}")
    return 0


__all__ = ["main"]
