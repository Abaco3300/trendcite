"""Deterministic text features: tokenisation, light stemming and term extraction.

Topic features are computed from a *feature view* of each item (:func:`item_text`):
title plus excerpt head with URLs, bare domains and feed boilerplate removed. The
stored evidence text is never modified; only this derived view is cleaned.
"""

from __future__ import annotations

import re

from .lexicon import COMMON_WORDS
from .models import EvidenceItem

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_APOSTROPHE_RE = re.compile(r"(?<=[a-z])['’](?=[a-z])")
EXCERPT_CHARS_FOR_TERMS = 120

_TLDS = (
    "com|org|net|io|dev|ai|app|co|me|sh|xyz|info|so|ly|gg|tv|fm|us|uk|de|fr|eu|ca|au|in|jp|cn"
    "|ru|nl|se|ch|edu|gov|biz|tech|site|blog|page|news|pdf|html?|php|aspx?"
)
# Feed and aggregator boilerplate that says nothing about the topic of an item.
_BOILERPLATE_RES = (
    re.compile(r"(?i)\b(?:https?://|www\.)\S+"),  # URLs
    re.compile(rf"(?i)\b[\w-]+(?:\.[\w-]+)*\.(?:{_TLDS})\b(?:/\S*)?"),  # bare domains/files
    re.compile(r"(?i)\b(?:article|comments?)\s+url\s*:?"),  # hnrss.org item bodies
    re.compile(r"(?i)(?:#\s*)?\b(?:points|comments)\s*:\s*\d+"),
    re.compile(r"(?i)\bsubmitted\s+by\b"),  # Reddit feed footer
    re.compile(r"(?i)\[\s*(?:link|comments)\s*\]"),
    re.compile(r"(?i)(?<![\w/])/?(?:u|r|user)/[\w-]+"),  # /u/name, r/sub
    re.compile(r"(?i)\bthe\s+post\s+.{0,200}?\s+appeared\s+first\s+on\b"),  # WordPress footer
    re.compile(r"(?i)\b(?:read\s+more|continue\s+reading|permalink)\b"),
)


def _words(block: str) -> list[str]:
    return block.split()


# Words ending in "s" that are not plurals (or whose singular would be misleading).
NO_STEM = frozenset(
    _words(
        """
        kubernetes news series species analytics ethics physics economics windows express aws ios
        macos https devops mlops llmops finops gitops postgres redis jenkins always perhaps
        """
    )
)


def stem(token: str) -> str:
    """Very light, deterministic plural folding ("servers" -> "server")."""
    if token in NO_STEM:
        return token
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is", "aas")):
        return token[:-1]
    return token


def _stemmed_set(block: str) -> frozenset[str]:
    words = _words(block)
    return frozenset(words) | frozenset(stem(w) for w in words)


# Function words: they break phrases and never appear in terms.
STOPWORDS = _stemmed_set(
    """
    a about above after again against all almost also am an and any are around as at be because
    been before being below between both but by can could did do does doing done down during each
    either else ever every few for from further get gets got had has have having he her here hers
    him his how i if in into is it its itself just let like made make makes many may me might
    more most much must my no nor not now of off on once only or other our ours out over own per
    really same she should so some such than that the their theirs them then there these they this
    those through to too under until up us very via was we were what when where which while who
    whom why will with within without would yet you your yours
    dont doesnt didnt isnt arent wasnt cant couldnt wont wouldnt shouldnt im ive youre youve
    theyre weve thats whats lets heres theres
    ask hn show tell launch launching today yesterday week weeks year years day days anyone else
    thread vs
    """
)

# Everyday English words. They may appear inside a two-word phrase ("language model") but
# are too ambiguous to seed a topic on their own ("model", "human", "run").
GENERIC = _stemmed_set(
    """
    ai new first good best better real way ways thing things time using use used users user app apps
    tool tools data open source code system systems build building built work working team teams
    company companies product products people post posts blog update updates guide finally went
    actually learned need needs based want release released version one two three four five ten
    general human humans model models run running runs ship shipping shipped write writing written
    read reading think thinking know knowing see seeing look looking find finding try trying help
    helping start starting stop go going gone come coming take taking give giving keep put set
    say says said call called ask asked turn move play still back big small large fast slow free
    easy hard high low long short full old young next last early late right left top bottom open
    close part case lot level line point place end home job life world hour hours minute minutes
    number numbers percent million billion dollar money price cost problem problems question
    questions idea ideas fact reason way story stories news article paper report study research
    result results change changes feature features service services platform platforms business
    market markets customer customers developer developers engineer engineers engineering software
    computer internet web online video image images language languages file files project projects
    private public power energy light water food car city state states country government law
    world man men woman women child children family friend friends person group community member
    today night morning week weeks month months year years day days old new more less many much
    great little own different important possible available making made makes getting got using
    via across without inside outside behind against among instead ever never always sometimes
    whole every another such own quite rather almost enough simple simpler smart better worse
    quick quickly slowly ago generate generated generating generation self note notes thought
    thoughts lesson lessons
    """
    # Format and genre words describe the *kind* of content, not its topic
    # ("curated list", "complete guide", "cheat sheet", "deep dive").
    """
    list lists curated curate awesome collection collections tutorial tutorials roadmap
    cheatsheet cheat sheet resource resources tip tips trick tricks template templates example
    examples introduction intro overview walkthrough deep dive beginner beginners complete
    ultimate step steps series collection handbook primer summary recap roundup digest
    """
)


# Link/markup tokens that survive boilerplate stripping (e.g. "link" in running text).
# They never become or join a topic term.
BOILERPLATE = _stemmed_set(
    """
    http https www url urls uri href link links permalink com org net html htm php amp nbsp
    utm rss atom submitted
    """
)

# Words that are neither function words, generic, boilerplate nor common English.
# Common words need a second shared term before they can link items (see cluster.py).
COMMON = frozenset(COMMON_WORDS) | frozenset(stem(w) for w in COMMON_WORDS)


#: Words that mark a piece of evidence as critical or cautionary about its own topic.
#: Shared so a brief's counterpoints and a signal's counterevidence never disagree.
CRITICAL_RE = re.compile(
    r"(?i)\b(risk|risks|worried|concern|problem|broken|breaking|nitpick|nitpicks|churn|fail"
    r"|fails|failure|overhyped|backlash|vulnerab\w*|drowning|harder)\b"
)


def tokenize(text: str) -> list[str]:
    lowered = _APOSTROPHE_RE.sub("", text.lower())
    return [stem(t) for t in _TOKEN_RE.findall(lowered)]


def strip_boilerplate(text: str) -> str:
    """Remove URLs, bare domains and feed boilerplate from a feature-extraction view."""
    for pattern in _BOILERPLATE_RES:
        text = pattern.sub(" ", text)
    return text


def feature_text(source: str, title: str, excerpt: str) -> str:
    """Feature view used for topic terms, labels and niche matching.

    Title plus the head of the excerpt, with boilerplate removed *before* the head is
    taken so feed footers cannot use up the budget. GitHub owner names are excluded to
    avoid owner clusters. The captured text itself is never modified.

    Takes plain fields rather than a record, so the observation layer and the display
    layer derive the same feature view from the same function.
    """
    if source == "github" and "/" in title:
        title = title.split("/", 1)[1]
    body = " ".join(strip_boilerplate(excerpt).split())
    return strip_boilerplate(f"{title} {body[:EXCERPT_CHARS_FOR_TERMS]}")


def item_text(item: EvidenceItem) -> str:
    """Feature view of one evidence item. See :func:`feature_text`."""
    return feature_text(item.source, item.title, item.excerpt)


def extract_terms(text: str) -> set[str]:
    """Return candidate topic terms: unigrams and adjacent-word bigrams (no stopwords)."""
    terms: set[str] = set()
    run: list[str] = []

    def flush() -> None:
        for i, tok in enumerate(run):
            terms.add(tok)
            if i + 1 < len(run):
                terms.add(f"{tok} {run[i + 1]}")
        run.clear()

    for tok in tokenize(text):
        if tok in STOPWORDS or tok in BOILERPLATE or len(tok) < 2 or tok.isdigit():
            flush()
        else:
            run.append(tok)
    flush()
    return terms


def is_seed_candidate(term: str) -> bool:
    words = term.split()
    if any(w in BOILERPLATE for w in words):
        return False
    if len(words) == 1:
        word = words[0]
        return word not in GENERIC and len(word) >= 3
    return not all(w in GENERIC for w in words)


def base_forms(word: str) -> set[str]:
    """The word plus plausible uninflected forms ("testing" -> "test", "making" -> "make").

    Only used to look words up in the reference word lists, which hold base forms.
    """
    forms = {word}
    for suffix in ("ing", "ed", "er", "ly"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            root = word[: -len(suffix)]
            forms |= {root, root + "e"}
            if len(root) > 2 and root[-1] == root[-2]:  # running -> run
                forms.add(root[:-1])
            if suffix == "ed" and root.endswith("i"):  # tried -> try
                forms.add(root[:-1] + "y")
    return forms


def is_specific(word: str) -> bool:
    """True for a distinctive single word: not a stopword, generic, boilerplate or common."""
    if len(word) < 3 or word.isdigit() or word in STOPWORDS or word in BOILERPLATE:
        return False
    return not any(f in GENERIC or f in COMMON for f in base_forms(word))


def specificity(term: str) -> int:
    """Agreement strength of a shared term: phrase 2, specific word 1, anything else 0.

    Cluster members must share terms worth >= 2 in total (see cluster.py).
    """
    words = term.split()
    if not any(is_specific(w) for w in words):
        return 0
    return 2 if len(words) > 1 else 1


def agreement_terms(terms: set[str], seed: str) -> set[str]:
    """Terms that can show two items agree on more than the seed itself.

    A term with at least one specific word that either shares no word with the seed,
    or is a longer phrase extending the seed with a non-generic word ("mcp server" for
    "mcp"). "decision model" is no agreement for "decision": its other word is generic
    and neither word is specific.
    """
    seed_words = set(seed.split())
    out: set[str] = set()
    for t in terms:
        words = t.split()
        if t == seed or not any(is_specific(w) for w in words):
            continue
        shared = seed_words & set(words)
        if not shared or (
            len(words) > 1 and any(w not in seed_words and w not in GENERIC for w in words)
        ):
            out.add(t)
    return out


def phrase_in(phrase: str, text_tokens: list[str]) -> bool:
    """True if the (stemmed) phrase occurs as a contiguous token sequence."""
    target = tokenize(phrase)
    if not target:
        return False
    n = len(target)
    return any(text_tokens[i : i + n] == target for i in range(len(text_tokens) - n + 1))
