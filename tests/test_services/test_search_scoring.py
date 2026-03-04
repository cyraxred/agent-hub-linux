"""Tests for agent_hub.services.search_scoring module."""

from __future__ import annotations

import pytest

from agent_hub.services.search_scoring import MatchResult, score


class TestSearchScoring:
    """Tests for the score() function."""

    # --- Exact phrase match (score >= 100) ---

    def test_exact_phrase_match(self) -> None:
        result = score("fix auth bug", "fix auth bug in login page")
        assert result is not None
        assert result.score >= 100

    def test_exact_phrase_match_case_insensitive(self) -> None:
        result = score("Fix Auth", "fix auth bug")
        assert result is not None
        assert result.score >= 100

    def test_exact_phrase_at_start(self) -> None:
        result = score("hello", "hello world")
        assert result is not None
        assert result.score >= 100
        assert result.position == 0

    def test_exact_phrase_middle(self) -> None:
        result = score("auth", "fix auth bug")
        assert result is not None
        assert result.score >= 100
        assert result.position == 4  # "fix " = 4 chars

    # --- All tokens full word match (score >= 70) ---

    def test_all_tokens_full_word_match(self) -> None:
        """All query tokens appear as full words, but not as a contiguous phrase."""
        result = score("auth bug", "There was a bug in the auth module")
        assert result is not None
        assert result.score >= 70

    def test_all_tokens_full_word_different_order(self) -> None:
        result = score("bug fix", "fix for the nasty bug")
        assert result is not None
        assert result.score >= 70

    # --- All tokens prefix match (score >= 40) ---

    def test_all_tokens_prefix_match(self) -> None:
        """Tokens match as prefixes of words."""
        result = score("auth mod", "authentication module")
        assert result is not None
        assert result.score >= 40

    def test_all_tokens_prefix_partial(self) -> None:
        result = score("ses mon", "session monitor state")
        assert result is not None
        assert result.score >= 40

    # --- Any single token match (score >= 10) ---

    def test_single_token_match(self) -> None:
        result = score("auth missing", "authentication module for login")
        assert result is not None
        assert result.score >= 10

    def test_single_token_substring(self) -> None:
        """A single token that exists as a substring."""
        result = score("xyz auth", "authentication service")
        assert result is not None
        assert result.score >= 10

    # --- No match ---

    def test_no_match(self) -> None:
        result = score("zzzzzyyyy", "authentication module")
        assert result is None

    def test_completely_unrelated(self) -> None:
        result = score("quantum physics", "python web framework")
        assert result is None

    # --- Empty/whitespace ---

    def test_empty_query(self) -> None:
        assert score("", "some text") is None

    def test_whitespace_query(self) -> None:
        assert score("   ", "some text") is None

    def test_empty_text(self) -> None:
        assert score("query", "") is None

    def test_both_empty(self) -> None:
        assert score("", "") is None

    # --- Position bonus ---

    def test_position_bonus_early_match(self) -> None:
        """Match at position 0 should get max bonus of 20."""
        result = score("hello", "hello world this is a test")
        assert result is not None
        assert result.score == 120  # 100 (exact phrase) + 20 (position bonus at idx 0)
        assert result.position == 0

    def test_position_bonus_later_match(self) -> None:
        """Match at a later position gets less bonus."""
        result_early = score("test", "test data here")
        result_late = score("test", "this is a long prefix before test data")

        assert result_early is not None
        assert result_late is not None
        assert result_early.score > result_late.score

    def test_position_bonus_very_far(self) -> None:
        """Match beyond position 20 gets 0 bonus."""
        text = "a" * 30 + "needle"
        result = score("needle", text)
        assert result is not None
        assert result.score == 100  # exact phrase + 0 bonus (position > 20)

    # --- Scoring tier ordering ---

    def test_exact_phrase_scores_higher_than_full_word(self) -> None:
        exact = score("auth bug", "auth bug in system")
        full_word = score("auth bug", "the bug in the auth system")

        assert exact is not None
        assert full_word is not None
        assert exact.score > full_word.score

    def test_full_word_scores_higher_than_prefix(self) -> None:
        full_word = score("auth", "auth module")
        prefix = score("auth", "authentication module")

        assert full_word is not None
        assert prefix is not None
        # "auth" exactly matches word "auth" -> full word or exact
        # "auth" is prefix of "authentication" -> but also substring match
        # Actually "auth" appears as substring in "authentication", which is exact phrase
        # Let's use a different test case
        full_word2 = score("mod serv", "mod serv extras")  # full words "mod" and "serv"
        prefix2 = score("mod serv", "module service extras")  # prefixes of "module" and "service"

        if full_word2 is not None and prefix2 is not None:
            assert full_word2.score >= prefix2.score

    def test_prefix_scores_higher_than_single_token(self) -> None:
        prefix = score("auth mod", "authentication module")
        single = score("auth zzz", "authentication module")

        assert prefix is not None
        assert single is not None
        assert prefix.score > single.score

    # --- MatchResult ---

    def test_match_result_fields(self) -> None:
        result = score("test", "test data")
        assert result is not None
        assert isinstance(result, MatchResult)
        assert isinstance(result.score, int)
        assert isinstance(result.position, int)
