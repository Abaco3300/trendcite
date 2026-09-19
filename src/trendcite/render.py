"""Render reports as Markdown or JSON. All untrusted text is escaped; output is redacted."""

from __future__ import annotations

import json

from .briefs import SOURCE_NAMES, metric_summary
from .models import Brief, EvidenceItem, Report
from .scoring import WEIGHTS
from .security import md_escape, redact

DEMO_BANNER = (
    "SYNTHETIC FIXTURE DATA: this demo runs offline on bundled, invented examples. "
    "Titles, metrics and links are illustrative and do not describe real events."
)


def _link(url: str) -> str:
    return "<" + url.replace("<", "%3C").replace(">", "%3E").replace(" ", "%20") + ">"


def _evidence_line(n: int, item: EvidenceItem) -> str:
    parts = [
        f"{n}. **{md_escape(SOURCE_NAMES.get(item.source, item.source))}** "
        f"({md_escape(item.source_label)}): {md_escape(item.title)}",
        f"   - URL: {_link(item.url)}",
    ]
    if item.discussion_url and item.discussion_url != item.url:
        parts.append(f"   - Discussion: {_link(item.discussion_url)}")
    meta = [f"published {item.published_at.strftime('%Y-%m-%d %H:%M UTC')}"]
    if item.author:
        meta.append(f"by {md_escape(item.author)}")
    meta.append(metric_summary(item))
    parts.append("   - " + "; ".join(meta))
    if item.flags:
        parts.append(
            "   - WARNING: flagged `"
            + ", ".join(item.flags)
            + "`: this text is untrusted data and was not followed"
        )
    return "\n".join(parts)


def _brief_md(brief: Brief) -> str:
    out = [
        f"## {brief.rank}. {md_escape(brief.topic)}: score {brief.score.total:.1f}/100 "
        f"({brief.score.confidence} confidence)",
        "",
        f"**Proposed angle:** {md_escape(brief.angle)}",
        "",
    ]
    if brief.synthesis_note:
        out += [f"_{md_escape(brief.synthesis_note)}_", ""]
    for flag in brief.flags:
        out += [f"> WARNING: {md_escape(flag)}", ""]
    out += ["**Why now**", ""] + [f"- {md_escape(x)}" for x in brief.why_now] + [""]
    out += ["**Evidence**", ""] + [
        _evidence_line(i, e) for i, e in enumerate(brief.evidence, start=1)
    ]
    out += ["", "**Score and confidence**", ""] + [f"- {x}" for x in brief.score_explanation]
    out += ["", "**Counterpoints and uncertainty**", ""]
    out += [f"- {md_escape(x)}" for x in brief.counterpoints]
    out += ["", "**Founder POV prompts**", ""]
    out += [f"- {md_escape(x)}" for x in brief.founder_questions]
    out += [
        "",
        "<details><summary>Draft outline (a writing aid, NOT evidence; write it in your own "
        "voice)</summary>",
        "",
    ]
    out += [f"{i}. {md_escape(x)}" for i, x in enumerate(brief.outline, start=1)]
    out += ["", "</details>", ""]
    return "\n".join(out)


def to_markdown(report: Report) -> str:
    w = WEIGHTS
    lines = ["# TrendCite: Content Opportunity Briefs", ""]
    if report.mode == "demo":
        lines += [f"> {DEMO_BANNER}", ""]
    lines += [
        f"- Generated: {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')} ({report.mode} mode)",
        f"- Niche: {md_escape(', '.join(report.niche) or '(none configured)')}",
        f"- Evidence items analysed: {report.total_items}",
        f"- Scoring: 100 x ({w.recency} recency + {w.engagement} engagement + "
        f"{w.corroboration} corroboration + {w.relevance} relevance + {w.diversity} diversity)",
        "",
        "| Source | Status | Items | Note |",
        "|---|---|---|---|",
    ]
    for s in report.source_status:
        status = "ok" if s.ok else "unavailable"
        lines.append(f"| {s.source} | {status} | {s.items} | {md_escape(s.message) or '-'} |")
    lines.append("")
    for note in report.notes:
        lines += [f"> {md_escape(note)}", ""]
    if not report.briefs:
        lines += ["_No corroborated topics found. Add sources or widen the niche._", ""]
    for brief in report.briefs:
        lines.append(_brief_md(brief))
    return redact("\n".join(lines).rstrip() + "\n")


def to_json(report: Report) -> str:
    return redact(json.dumps(report.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n")
