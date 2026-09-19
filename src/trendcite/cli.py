"""Command-line interface: ``trendcite demo | live | sources``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .config import Config, ConfigError, load_config
from .llm import LLMError, enhance_briefs, provider_from_env
from .models import Report
from .pipeline import make_adapters, run_demo, run_live
from .render import to_json, to_markdown
from .security import configure_logging, redact


def _split(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--format", choices=["markdown", "json"], default="markdown")
    p.add_argument("--out", type=Path, help="write the report to this file instead of stdout")
    p.add_argument("--top", type=int, default=None, help="number of briefs, clamped to 3-5")
    p.add_argument("--niche", help="comma-separated niche phrases, e.g. 'ai agents,pricing'")
    p.add_argument(
        "--llm",
        action="store_true",
        help="refine angles/outlines with the provider set in TRENDCITE_LLM_PROVIDER",
    )
    p.add_argument("-v", "--verbose", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trendcite",
        description="Evidence-first trend intelligence: traceable content opportunity briefs.",
    )
    parser.add_argument("--version", action="version", version=f"trendcite {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="offline demo on bundled synthetic fixtures (no network)")
    _add_common(demo)

    live = sub.add_parser("live", help="collect from public read-only sources and build briefs")
    _add_common(live)
    live.add_argument("--config", type=Path, help="path to trendcite.toml")
    live.add_argument("--sources", help="comma-separated: hackernews,github,rss,reddit,x")
    live.add_argument("--feeds", help="comma-separated RSS/Atom URLs (replaces configured feeds)")
    live.add_argument("--subreddits", help="comma-separated subreddit names")
    live.add_argument("--github-queries", help="comma-separated GitHub search queries")

    sub.add_parser("sources", help="list source adapters and their status requirements")
    return parser


def _emit(text: str, out: Path | None) -> None:
    if out is None:
        sys.stdout.write(text)
        return
    out.write_text(text, encoding="utf-8")
    sys.stderr.write(f"trendcite: wrote {out}\n")


def _maybe_llm(report: Report, enabled: bool) -> None:
    if not enabled:
        return
    try:
        provider = provider_from_env()
    except LLMError as exc:
        report.notes.append(f"LLM synthesis disabled: {redact(str(exc))}")
        return
    if provider is None:
        report.notes.append(
            "--llm given but TRENDCITE_LLM_PROVIDER is not set; deterministic output only."
        )
        return
    report.notes.extend(enhance_briefs(report.briefs, provider))


def _live_config(args: argparse.Namespace) -> Config:
    cfg = load_config(args.config)
    for attr, value in (
        ("sources", _split(args.sources)),
        ("feeds", _split(args.feeds)),
        ("subreddits", _split(args.subreddits)),
        ("github_queries", _split(args.github_queries)),
        ("niche", _split(args.niche)),
    ):
        if value is not None:
            setattr(cfg, attr, value)
    if args.top is not None:
        cfg.top = args.top
    return cfg


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    configure_logging(getattr(args, "verbose", False))
    try:
        if args.command == "sources":
            for adapter in make_adapters(
                Config(sources=["hackernews", "github", "rss", "reddit", "x"])
            ):
                print(f"{adapter.name:<11} {adapter.description}")
            return 0
        if args.command == "demo":
            report = run_demo(top=args.top or 5, niche=_split(args.niche))
        else:
            report = run_live(_live_config(args))
        _maybe_llm(report, args.llm)
        rendered = to_json(report) if args.format == "json" else to_markdown(report)
        _emit(rendered, args.out)
        if args.command == "live" and not any(s.ok for s in report.source_status):
            sys.stderr.write("trendcite: no source was reachable; see the source table.\n")
            return 2
        return 0
    except (ConfigError, ValueError) as exc:
        sys.stderr.write(f"trendcite: error: {redact(str(exc))}\n")
        return 2
