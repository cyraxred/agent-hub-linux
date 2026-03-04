"""Token-based fuzzy scoring ported from Swift SearchScoring.swift."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MatchResult:
    """Result of a scoring match."""

    score: int
    position: int


# Scoring tier thresholds
_SCORE_EXACT_PHRASE: int = 100
_SCORE_ALL_TOKENS_FULL_WORD: int = 70
_SCORE_ALL_TOKENS_PREFIX: int = 40
_SCORE_ANY_TOKEN: int = 10
_POSITION_BONUS_MAX: int = 20

_WORD_BOUNDARY_RE = re.compile(r"\b", re.UNICODE)


def _position_bonus(text_lower: str, token: str) -> int:
    """Calculate position bonus (earlier match = higher bonus, max 20)."""
    idx = text_lower.find(token)
    if idx < 0:
        return 0
    # Bonus decreases as position increases, max 20 for position 0
    return max(0, _POSITION_BONUS_MAX - idx)


def _tokenize(query: str) -> list[str]:
    """Split query into lowercase non-empty tokens."""
    return [t for t in query.lower().split() if t]


def score(query: str, against: str) -> MatchResult | None:
    """Score a query against a text string.

    Returns a MatchResult with score and position, or None if no match.

    Scoring tiers:
    1. Exact phrase match: 100+ (+ position bonus 0-20)
    2. All tokens present as full words: 70+ (+ position bonus)
    3. All tokens match as word prefixes: 40+ (+ position bonus)
    4. Any single token matches: 10+ (+ position bonus)
    """
    if not query.strip() or not against.strip():
        return None

    query_lower = query.lower().strip()
    text_lower = against.lower().strip()
    tokens = _tokenize(query)

    if not tokens:
        return None

    # Tier 1: Exact phrase match
    exact_pos = text_lower.find(query_lower)
    if exact_pos >= 0:
        bonus = max(0, _POSITION_BONUS_MAX - exact_pos)
        return MatchResult(score=_SCORE_EXACT_PHRASE + bonus, position=exact_pos)

    # Build word list for word-boundary matching
    words = re.findall(r"\w+", text_lower)

    # Tier 2: All tokens present as full words
    all_full_word = True
    first_pos = len(text_lower)
    for token in tokens:
        found = False
        for word in words:
            if word == token:
                pos = text_lower.find(word)
                first_pos = min(first_pos, pos)
                found = True
                break
        if not found:
            all_full_word = False
            break

    if all_full_word:
        bonus = max(0, _POSITION_BONUS_MAX - first_pos)
        return MatchResult(score=_SCORE_ALL_TOKENS_FULL_WORD + bonus, position=first_pos)

    # Tier 3: All tokens match as word prefixes
    all_prefix = True
    first_pos = len(text_lower)
    for token in tokens:
        found = False
        for word in words:
            if word.startswith(token):
                pos = text_lower.find(word)
                first_pos = min(first_pos, pos)
                found = True
                break
        if not found:
            all_prefix = False
            break

    if all_prefix:
        bonus = max(0, _POSITION_BONUS_MAX - first_pos)
        return MatchResult(score=_SCORE_ALL_TOKENS_PREFIX + bonus, position=first_pos)

    # Tier 4: Any single token matches
    best_score = 0
    best_pos = len(text_lower)
    for token in tokens:
        pos = text_lower.find(token)
        if pos >= 0:
            bonus = max(0, _POSITION_BONUS_MAX - pos)
            token_score = _SCORE_ANY_TOKEN + bonus
            if token_score > best_score:
                best_score = token_score
                best_pos = pos

    if best_score > 0:
        return MatchResult(score=best_score, position=best_pos)

    return None
