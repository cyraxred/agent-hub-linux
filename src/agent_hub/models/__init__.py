"""AgentHub models -- re-exports all public types."""

from __future__ import annotations

# session.py
from agent_hub.models.session import (
    CLILoadingState,
    CLILoadingStateAddingRepository,
    CLILoadingStateDetectingWorktrees,
    CLILoadingStateIdle,
    CLILoadingStateRefreshing,
    CLILoadingStateRestoringMonitoredSessions,
    CLILoadingStateRestoringRepositories,
    CLILoadingStateScanningSessionsState,
    CLISession,
    CLISessionGroup,
    CLISessionSourceType,
    HistoryEntry,
    SelectedRepository,
    WorktreeBranch,
)

# monitor_state.py
from agent_hub.models.monitor_state import (
    ActivityEntry,
    ActivityType,
    ActivityTypeAssistantMessage,
    ActivityTypeThinking,
    ActivityTypeToolResult,
    ActivityTypeToolUse,
    ActivityTypeUserMessage,
    CodeChangeInput,
    CodeChangeToolType,
    ConsolidatedFileChange,
    CostBreakdown,
    CostCalculator,
    EditEntry,
    FileOperation,
    MermaidDiagramInfo,
    PendingToolUse,
    PlanInfo,
    SessionMonitorState,
    SessionStatus,
    SessionStatusAwaitingApproval,
    SessionStatusExecutingTool,
    SessionStatusIdle,
    SessionStatusThinking,
    SessionStatusWaitingForUser,
)

# stats.py
from agent_hub.models.stats import (
    DailyActivity,
    DailyModelTokens,
    GlobalStatsCache,
    LongestSession,
    ModelUsage,
)

# search.py
from agent_hub.models.search import (
    SearchMatchField,
    SessionIndexEntry,
    SessionSearchResult,
)

# ws_messages.py
from agent_hub.models.ws_messages import (
    ClientMessage,
    ClientMessageRefreshSessions,
    ClientMessageSubscribeSession,
    ClientMessageTerminalInput,
    ClientMessageTerminalResize,
    ClientMessageUnsubscribeSession,
    ServerMessage,
    ServerMessageError,
    ServerMessageSearchResults,
    ServerMessageSessionsUpdated,
    ServerMessageSessionStateUpdate,
    ServerMessageStatsUpdated,
    ServerMessageTerminalOutput,
)

# git_diff.py
from agent_hub.models.git_diff import (
    DiffMode,
    GitDiffFileEntry,
    GitDiffState,
    ParsedFileDiff,
)

# plan.py
from agent_hub.models.plan import PlanState

# orchestration.py
from agent_hub.models.orchestration import (
    OrchestrationPlan,
    OrchestrationSession,
    OrchestrationStatus,
)

# dev_server.py
from agent_hub.models.dev_server import (
    DetectedProject,
    DevServerState,
    DevServerStateDetecting,
    DevServerStateFailed,
    DevServerStateIdle,
    DevServerStateReady,
    DevServerStateStarting,
    DevServerStateStopping,
    DevServerStateWaitingForReady,
    ProjectFramework,
)

# diff_comment.py
from agent_hub.models.diff_comment import DiffComment

# worktree.py
from agent_hub.models.worktree import (
    RemoteBranch,
    WorktreeCreationProgress,
    WorktreeCreationProgressCompleted,
    WorktreeCreationProgressFailed,
    WorktreeCreationProgressIdle,
    WorktreeCreationProgressPreparing,
    WorktreeCreationProgressUpdatingFiles,
)

# pending_session.py
from agent_hub.models.pending_session import PendingHubSession

# metadata.py (ORM models)
from agent_hub.models.metadata import (
    Base,
    SessionMetadataRow,
    SessionRepoMappingRow,
)

__all__ = [
    # session
    "CLILoadingState",
    "CLILoadingStateAddingRepository",
    "CLILoadingStateDetectingWorktrees",
    "CLILoadingStateIdle",
    "CLILoadingStateRefreshing",
    "CLILoadingStateRestoringMonitoredSessions",
    "CLILoadingStateRestoringRepositories",
    "CLILoadingStateScanningSessionsState",
    "CLISession",
    "CLISessionGroup",
    "CLISessionSourceType",
    "HistoryEntry",
    "SelectedRepository",
    "WorktreeBranch",
    # monitor_state
    "ActivityEntry",
    "ActivityType",
    "ActivityTypeAssistantMessage",
    "ActivityTypeThinking",
    "ActivityTypeToolResult",
    "ActivityTypeToolUse",
    "ActivityTypeUserMessage",
    "CodeChangeInput",
    "CodeChangeToolType",
    "ConsolidatedFileChange",
    "CostBreakdown",
    "CostCalculator",
    "EditEntry",
    "FileOperation",
    "MermaidDiagramInfo",
    "PendingToolUse",
    "PlanInfo",
    "SessionMonitorState",
    "SessionStatus",
    "SessionStatusAwaitingApproval",
    "SessionStatusExecutingTool",
    "SessionStatusIdle",
    "SessionStatusThinking",
    "SessionStatusWaitingForUser",
    # stats
    "DailyActivity",
    "DailyModelTokens",
    "GlobalStatsCache",
    "LongestSession",
    "ModelUsage",
    # search
    "SearchMatchField",
    "SessionIndexEntry",
    "SessionSearchResult",
    # ws_messages
    "ClientMessage",
    "ClientMessageRefreshSessions",
    "ClientMessageSubscribeSession",
    "ClientMessageTerminalInput",
    "ClientMessageTerminalResize",
    "ClientMessageUnsubscribeSession",
    "ServerMessage",
    "ServerMessageError",
    "ServerMessageSearchResults",
    "ServerMessageSessionsUpdated",
    "ServerMessageSessionStateUpdate",
    "ServerMessageStatsUpdated",
    "ServerMessageTerminalOutput",
    # git_diff
    "DiffMode",
    "GitDiffFileEntry",
    "GitDiffState",
    "ParsedFileDiff",
    # plan
    "PlanState",
    # orchestration
    "OrchestrationPlan",
    "OrchestrationSession",
    "OrchestrationStatus",
    # dev_server
    "DetectedProject",
    "DevServerState",
    "DevServerStateDetecting",
    "DevServerStateFailed",
    "DevServerStateIdle",
    "DevServerStateReady",
    "DevServerStateStarting",
    "DevServerStateStopping",
    "DevServerStateWaitingForReady",
    "ProjectFramework",
    # diff_comment
    "DiffComment",
    # worktree
    "RemoteBranch",
    "WorktreeCreationProgress",
    "WorktreeCreationProgressCompleted",
    "WorktreeCreationProgressFailed",
    "WorktreeCreationProgressIdle",
    "WorktreeCreationProgressPreparing",
    "WorktreeCreationProgressUpdatingFiles",
    # pending_session
    "PendingHubSession",
    # metadata
    "Base",
    "SessionMetadataRow",
    "SessionRepoMappingRow",
]
