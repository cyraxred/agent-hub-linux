"""Typed default constants (namespaced keys)."""

from __future__ import annotations

# Context window defaults
CONTEXT_WINDOW_SIZE: int = 200_000

# Session activity thresholds (seconds)
SESSION_ACTIVE_THRESHOLD: float = 60.0
SESSION_IDLE_TIMEOUT: float = 300.0  # 5 minutes
THINKING_TIMEOUT: float = 30.0
TOOL_RESULT_TIMEOUT: float = 60.0

# Approval detection
DEFAULT_APPROVAL_TIMEOUT_SECONDS: int = 5

# File watcher
STATUS_TIMER_INTERVAL: float = 1.5
STALE_WATCHER_THRESHOLD: float = 5.0
SESSION_FILE_READ_CHUNK: int = 16384  # 16KB for initial session read

# Search scoring tiers
SCORE_EXACT_PHRASE: int = 100
SCORE_ALL_TOKENS_FULL_WORD: int = 70
SCORE_ALL_TOKENS_PREFIX: int = 40
SCORE_ANY_TOKEN: int = 10
SCORE_SEMANTIC_MAX: int = 30
POSITION_BONUS_MAX: int = 20

# Git operations
GIT_COMMAND_TIMEOUT: float = 10.0
GIT_WORKTREE_TIMEOUT: float = 300.0  # 5 minutes
GIT_DIFF_TIMEOUT: float = 30.0

# Dev server
DEV_SERVER_READINESS_TIMEOUT: float = 30.0

# Terminal
MAX_TERMINAL_SCROLLBACK: int = 10000

# Recent activities cap
MAX_RECENT_ACTIVITIES: int = 50

# Cost calculation: per million tokens
PRICING_OPUS_INPUT: float = 15.0
PRICING_OPUS_OUTPUT: float = 75.0
PRICING_OPUS_CACHE_READ: float = 1.50
PRICING_OPUS_CACHE_CREATION: float = 18.75

PRICING_SONNET_INPUT: float = 3.0
PRICING_SONNET_OUTPUT: float = 15.0
PRICING_SONNET_CACHE_READ: float = 0.30
PRICING_SONNET_CACHE_CREATION: float = 3.75

PRICING_HAIKU_INPUT: float = 0.25
PRICING_HAIKU_OUTPUT: float = 1.25
PRICING_HAIKU_CACHE_READ: float = 0.025
PRICING_HAIKU_CACHE_CREATION: float = 0.30
