"""Track titles in ANCHOR's voice ("Pull Under", "Apex Ascent", "Initiate Mayhem").

Patterns: V = verb, N = noun, A = adjective, PH = a ready-made phrase from the profile.
"""
from __future__ import annotations

import random


def _norm(title: str) -> str:
    return " ".join(title.lower().split())


def make_title(bank: dict, rnd: random.Random, used_titles: list[str],
               recent_titles: list[str], attempts: int = 400) -> str:
    """Pick a fresh title.

    - never repeats any title in ``used_titles`` (whole catalog + titles already on the channel)
    - avoids every word used in ``recent_titles`` (the last ~10 drops) so days feel distinct
    - never doubles a word inside one title ("Iron Iron")
    """
    used = {_norm(t) for t in used_titles}
    recent_words = {w.lower() for t in recent_titles for w in t.split()}
    patterns = [p for p, _ in bank["patterns"]]
    weights = [int(w) for _, w in bank["patterns"]]
    pools = {"V": bank["verbs"], "N": bank["nouns"], "A": bank["adjectives"], "PH": bank.get("phrases", [])}

    for attempt in range(attempts):
        pattern = rnd.choices(patterns, weights=weights, k=1)[0]
        words: list[str] = []
        for slot in pattern.split():
            if not pools[slot]:
                break
            words.extend(rnd.choice(pools[slot]).split())
        if not words:
            continue
        lowered = [w.lower() for w in words]
        if len(set(lowered)) != len(lowered):
            continue
        # relax the recency rule only if the bank is nearly exhausted
        if attempt < attempts // 2 and any(w in recent_words for w in lowered):
            continue
        title = " ".join(words)
        if _norm(title) in used:
            continue
        return title
    raise RuntimeError("title bank exhausted: add words to [titles] in artist/anchor.toml")
