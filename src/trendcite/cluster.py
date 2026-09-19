"""Deterministic topic clustering by shared key terms, with a coherence gate.

Algorithm (greedy, fully deterministic):

1. Extract unigram and bigram terms from each item's *feature view* (title + excerpt
   head with URLs, domains and feed boilerplate removed; see ``text.item_text``).
2. A term is a *seed candidate* if it is not generic or boilerplate and occurs in items
   with >= ``min_items`` distinct underlying URLs (``EvidenceItem.story_key``).
3. Coherence gate. The items a seed may claim depend on how distinctive the seed is:

   - phrase (two words, at least one not generic): every item containing it. A shared
     multi-word phrase is itself strong lexical agreement.
   - specific word (not in the common-English reference lexicon ``lexicon.py``, e.g.
     "mcp", "kubernetes"): every item containing it if they are cohesive
     (``scoring.evidence_is_cohesive``: every URL shares a further specific term or
     phrase with more than half of the other URLs).
   - otherwise (a common word such as "decision", "agent", "memory", or a specific
     word that failed the cohesion check): only the items that also share the seed's
     best co-occurring *agreement terms* (``text.agreement_terms``). Uniform
     principle: members must share terms worth >= 2 in total, where a phrase counts
     2, a specific word 1 and a common word 0 (``text.specificity``). So "gpt" +
     "astra" is enough, while "agent" needs a shared phrase or two more specific
     words. The label names the extra terms. Inflected forms are checked against the
     lexicon too ("testing" counts as "test").
   - last resort, specific word from a single independent source: all its items form
     a *candidate* cluster that claims no corroboration. The pipeline only publishes
     clusters whose evidence is cohesive, so such a candidate is reported as
     suppressed rather than turned into a brief.

   The claimed set must still cover >= ``min_items`` distinct underlying URLs, so the
   same link mirrored through two channels can never form a cluster by itself.
4. Repeatedly pick the candidate whose claimed set has the most independent sources
   (sources that each contribute a different underlying URL), then the most unique
   URLs, then the most items, preferring phrases, then seeds that needed no extra
   term, then alphabetical order.
5. Stop when no candidate qualifies.

Tradeoffs: the gate trades recall for precision. Items that share only a common word
plus one other word are never clustered, even when they happen to be related; a
specific word with two senses can still merge unrelated items when they also share a
second specific term. Every brief keeps a counterpoint telling the reader to check
the evidence.

Items that never join a cluster are not turned into briefs: a single uncorroborated
item is not treated as a trend.
"""

from __future__ import annotations

from collections import Counter
from itertools import combinations

from .models import EvidenceItem, TopicCluster
from .scoring import evidence_is_cohesive, independent_sources
from .text import (
    STOPWORDS,
    agreement_terms,
    extract_terms,
    is_seed_candidate,
    is_specific,
    item_text,
    specificity,
    tokenize,
)

DISPLAY_WORDS = {
    "ai": "AI",
    "mcp": "MCP",
    "ci": "CI",
    "crdt": "CRDT",
    "sqlite": "SQLite",
    "api": "API",
    "llm": "LLM",
    "saas": "SaaS",
    "hn": "HN",
    "github": "GitHub",
    "gpt": "GPT",
    "rag": "RAG",
    "rl": "RL",
    "ui": "UI",
    "ux": "UX",
    "css": "CSS",
    "sql": "SQL",
}


def display_label(term: str) -> str:
    label = " ".join(DISPLAY_WORDS.get(w, w) for w in term.split())
    return label[:1].upper() + label[1:]


def _best_label(seed: str, items: list[EvidenceItem]) -> str:
    """Longest phrase (<= 3 words) containing the seed shared by >= 60% of items."""
    seed_tokens = seed.split()
    threshold = max(2, -(-len(items) * 3 // 5))
    counts: Counter[str] = Counter()
    for item in items:
        toks = tokenize(item_text(item))
        seen: set[str] = set()
        for n in (3, 2):
            for i in range(len(toks) - n + 1):
                gram = toks[i : i + n]
                if gram[0] in STOPWORDS or gram[-1] in STOPWORDS or len(set(gram)) < n:
                    continue  # also skips tag runs like "mcp mcp-server"
                for j in range(n - len(seed_tokens) + 1):
                    if gram[j : j + len(seed_tokens)] == seed_tokens:
                        seen.add(" ".join(gram))
                        break
        counts.update(seen)
    best = seed
    for phrase, count in sorted(
        counts.items(), key=lambda kv: (-len(kv[0].split()), -kv[1], kv[0])
    ):
        if count >= threshold and is_seed_candidate(phrase):
            best = phrase
            break
    return best


def coherent_members(
    seed: str, candidates: set[int], items: list[EvidenceItem], term_sets: list[set[str]]
) -> tuple[list[int], str | None]:
    """Indices (into ``items``) that ``seed`` may claim among ``candidates``.

    Returns ``(members, qualifier)``; ``qualifier`` is the second term the members were
    required to share, or ``None`` when the seed alone was sufficient.
    """
    ids = sorted(candidates)
    if " " in seed:
        return ids, None
    specific = is_specific(seed)
    if specific and evidence_is_cohesive(
        seed, [items[i] for i in ids], [term_sets[i] for i in ids]
    ):
        return ids, None
    # The seed alone is not enough: claim the items that also share the best
    # co-occurring agreement term(s), so members share terms worth >= 2 in total
    # (see ``text.specificity``). A specific seed needs one more term; a common seed
    # needs a shared phrase or two shared specific words.
    needed = 2 - specificity(seed)
    by_term: dict[str, list[int]] = {}
    for i in ids:
        terms = sorted(agreement_terms(term_sets[i], seed))
        for term in terms:
            if specificity(term) >= needed:
                by_term.setdefault(term, []).append(i)
        if needed == 2:
            words = [t for t in terms if specificity(t) == 1]
            for a, b in combinations(words, 2):
                by_term.setdefault(f"{a} + {b}", []).append(i)
    best: tuple[tuple[int, int, int, int, str], list[int]] | None = None
    for term, group in by_term.items():
        members = [items[i] for i in group]
        n_urls = len({m.story_key for m in members})
        if n_urls < 2:
            continue
        rank = (
            -independent_sources(members),
            -n_urls,
            -len(group),
            0 if " " in term else 1,
            term,
        )
        if best is None or rank < best[0]:
            best = (rank, group)
    if best is not None:
        return best[1], best[0][4]
    if specific and independent_sources([items[i] for i in ids]) <= 1:
        # One community using one specific word: kept as a *candidate* (it claims no
        # corroboration), but not published unless its evidence is cohesive.
        return ids, None
    return [], None


def cluster_items(
    items: list[EvidenceItem], min_items: int = 2, max_clusters: int = 25
) -> list[TopicCluster]:
    ordered = sorted(items, key=lambda i: (i.source, i.url, i.title))
    term_sets = [extract_terms(item_text(i)) for i in ordered]
    postings: dict[str, set[int]] = {}
    for idx, terms in enumerate(term_sets):
        for term in terms:
            if is_seed_candidate(term):
                postings.setdefault(term, set()).add(idx)
    postings = {
        t: ids
        for t, ids in postings.items()
        if len({ordered[i].story_key for i in ids}) >= min_items
    }

    assigned: set[int] = set()
    clusters: list[TopicCluster] = []
    while len(clusters) < max_clusters:
        best: tuple[tuple[int, int, int, int, int, str], list[int], str | None] | None = None
        for term, ids in postings.items():
            free = ids - assigned
            if len(free) < min_items:
                continue
            claimed, qualifier = coherent_members(term, free, ordered, term_sets)
            claimed_items = [ordered[i] for i in claimed]
            n_urls = len({i.story_key for i in claimed_items})
            if n_urls < min_items:
                continue
            # More independent sources, then more unique URLs, then more items,
            # then phrases, then seeds that needed no qualifier, then alphabetical.
            rank = (
                -independent_sources(claimed_items),
                -n_urls,
                -len(claimed),
                0 if " " in term else 1,
                0 if qualifier is None else 1,
                term,
            )
            if best is None or rank < best[0]:
                best = (rank, claimed, qualifier)
        if best is None:
            break
        best_term = best[0][5]
        members = best[1]
        assigned.update(members)
        cluster_items_ = [ordered[i] for i in members]
        label = _best_label(best_term, cluster_items_)
        qualifier = best[2]
        if qualifier and not set(qualifier.split()) <= set(label.split()):
            label = f"{label} + {qualifier}"
        label_words = set(label.split())
        related: Counter[str] = Counter()
        for i in members:
            related.update(
                t
                for t in term_sets[i]
                if is_seed_candidate(t) and not set(t.split()) <= label_words
            )
        ranked = sorted(related.items(), key=lambda kv: (-kv[1], kv[0]))
        related_terms = [t for t, c in ranked if c >= 2][:5]
        clusters.append(
            TopicCluster(
                key=best_term,
                label=display_label(label),
                items=cluster_items_,
                related_terms=related_terms,
            )
        )
    return clusters
