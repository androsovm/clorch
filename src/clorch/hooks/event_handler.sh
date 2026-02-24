#!/usr/bin/env bash
# event_handler.sh - Claude Code hook event handler for clorch
# Handles: SessionStart, PreToolUse, PostToolUse, PostToolUseFailure, Stop, SessionEnd,
#          PermissionRequest, UserPromptSubmit, SubagentStart, SubagentStop,
#          PreCompact, TeammateIdle, TaskCompleted
#
# Receives JSON on stdin from Claude Code hooks.
# Writes/updates state files in /tmp/clorch/state/<session_id>.json
#
# The event type is read from the CLORCH_EVENT environment variable.
# Configure in settings.json as:
#   "command": "CLORCH_EVENT=PreToolUse /path/to/event_handler.sh"
#
# chmod +x event_handler.sh

set -euo pipefail

# Escape a string for embedding inside AppleScript double-quoted strings.
_escape_applescript() {
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    printf '%s' "$s"
}

STATE_DIR="${CLORCH_STATE_DIR:-/tmp/clorch/state}"
mkdir -p "$STATE_DIR"

# Read JSON from stdin
INPUT_JSON="$(cat)"

# Extract session_id — bail out if missing
SESSION_ID="$(echo "$INPUT_JSON" | jq -r '.session_id // empty')"
if [[ -z "$SESSION_ID" ]]; then
    exit 0
fi

STATE_FILE="${STATE_DIR}/${SESSION_ID}.json"
NOW="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

# Determine event type from env var, fall back to detection from JSON structure
EVENT="${CLORCH_EVENT:-}"
if [[ -z "$EVENT" ]]; then
    # Detect event from JSON structure
    HAS_TOOL_NAME="$(echo "$INPUT_JSON" | jq -r 'has("tool_name")')"
    HAS_TOOL_RESPONSE="$(echo "$INPUT_JSON" | jq -r 'has("tool_response")')"
    HAS_STOP="$(echo "$INPUT_JSON" | jq -r 'has("stop_hook_active")')"

    if [[ "$HAS_TOOL_NAME" == "true" && "$HAS_TOOL_RESPONSE" == "true" ]]; then
        EVENT="PostToolUse"
    elif [[ "$HAS_TOOL_NAME" == "true" ]]; then
        EVENT="PreToolUse"
    elif [[ "$HAS_STOP" == "true" ]]; then
        EVENT="Stop"
    else
        # If state file does not exist, assume SessionStart; otherwise SessionEnd
        if [[ ! -f "$STATE_FILE" ]]; then
            EVENT="SessionStart"
        else
            EVENT="SessionEnd"
        fi
    fi
fi

# Read existing state or initialize empty object
if [[ -f "$STATE_FILE" ]]; then
    CURRENT_STATE="$(cat "$STATE_FILE")"
else
    CURRENT_STATE='{}'
fi

# Bootstrap: ensure identity fields are always present.
# When hooks are installed on an already-running session, the first event
# won't be SessionStart, so session_id/cwd/project_name would be missing.
# PPID is the Claude Code process — stored so the TUI can detect dead sessions.
# TMUX is set when running inside a tmux pane — detect the window name.
CWD_FROM_INPUT="$(echo "$INPUT_JSON" | jq -r '.cwd // empty')"
TMUX_WINDOW=""
# Detect tmux window ONLY if Claude Code's tty is actually inside a tmux pane.
# Plain `tmux display-message` returns whatever the last client sees, which is
# wrong when the agent runs in an iTerm tab while a tmux server is up.
_CLAUDE_TTY="$(ps -p "$PPID" -o tty= 2>/dev/null | tr -d ' ')"
if [[ -n "$_CLAUDE_TTY" && "$_CLAUDE_TTY" != "??" ]]; then
    TMUX_WINDOW="$(tmux list-panes -a -F '#{pane_tty} #{window_name}' 2>/dev/null \
        | awk -v tty="/dev/$_CLAUDE_TTY" '$1 == tty { print $2; exit }')"
fi
CURRENT_STATE="$(echo "$CURRENT_STATE" | jq \
    --arg sid "$SESSION_ID" \
    --arg cwd "${CWD_FROM_INPUT:-}" \
    --arg now "$NOW" \
    --argjson pid "$PPID" \
    --arg tmux_win "${TMUX_WINDOW:-}" \
    '
    if .session_id == null or .session_id == "" then .session_id = $sid else . end |
    if (.cwd == null or .cwd == "") and $cwd != "" then .cwd = $cwd else . end |
    if (.project_name == null or .project_name == "") and $cwd != "" then .project_name = ($cwd | split("/") | last) else . end |
    if .started_at == null or .started_at == "" then .started_at = $now else . end |
    if .tool_count == null then .tool_count = 0 else . end |
    if .error_count == null then .error_count = 0 else . end |
    if .activity_history == null then .activity_history = [0,0,0,0,0,0,0,0,0,0] else . end |
    .pid = $pid |
    .tmux_window = $tmux_win
    '
)"

# Temp file for atomic write
TEMP_FILE="$(mktemp "${STATE_DIR}/.tmp.XXXXXX")"
trap 'rm -f "$TEMP_FILE"' EXIT

case "$EVENT" in
    SessionStart)
        CWD="$(echo "$INPUT_JSON" | jq -r '.cwd // ""')"
        PROJECT_NAME="$(basename "$CWD")"
        MODEL="$(echo "$INPUT_JSON" | jq -r '.model // "unknown"')"

        jq -n \
            --arg sid "$SESSION_ID" \
            --arg status "WORKING" \
            --arg cwd "$CWD" \
            --arg started_at "$NOW" \
            --arg project_name "$PROJECT_NAME" \
            --arg model "$MODEL" \
            --arg last_event "SessionStart" \
            --arg last_event_time "$NOW" \
            '{
                session_id: $sid,
                status: $status,
                cwd: $cwd,
                started_at: $started_at,
                project_name: $project_name,
                model: $model,
                last_event: $last_event,
                last_event_time: $last_event_time,
                last_tool: null,
                tool_count: 0,
                error_count: 0,
                activity_history: [0,0,0,0,0,0,0,0,0,0]
            }' > "$TEMP_FILE"
        mv "$TEMP_FILE" "$STATE_FILE"
        ;;

    PreToolUse)
        TOOL_NAME="$(echo "$INPUT_JSON" | jq -r '.tool_name // "unknown"')"

        echo "$CURRENT_STATE" | jq \
            --arg status "WORKING" \
            --arg tool "$TOOL_NAME" \
            --arg last_event "PreToolUse" \
            --arg last_event_time "$NOW" \
            '
            .status = $status |
            .last_tool = $tool |
            .last_event = $last_event |
            .last_event_time = $last_event_time |
            .tool_count = ((.tool_count // 0) + 1) |
            .activity_history = (
                (.activity_history // [0,0,0,0,0,0,0,0,0,0]) |
                .[1:] + [((if .[-1] == null then 0 else .[-1] end) + 1)]
            )
            ' > "$TEMP_FILE"
        mv "$TEMP_FILE" "$STATE_FILE"
        ;;

    PostToolUse)
        echo "$CURRENT_STATE" | jq \
            --arg status "WORKING" \
            --arg last_event "PostToolUse" \
            --arg last_event_time "$NOW" \
            '
            .status = $status |
            .last_event = $last_event |
            .last_event_time = $last_event_time
            ' > "$TEMP_FILE"
        mv "$TEMP_FILE" "$STATE_FILE"
        ;;

    PostToolUseFailure)
        echo "$CURRENT_STATE" | jq \
            --arg status "ERROR" \
            --arg last_event "PostToolUseFailure" \
            --arg last_event_time "$NOW" \
            '
            .status = $status |
            .last_event = $last_event |
            .last_event_time = $last_event_time |
            .error_count = ((.error_count // 0) + 1)
            ' > "$TEMP_FILE"
        mv "$TEMP_FILE" "$STATE_FILE"
        ;;

    Stop)
        echo "$CURRENT_STATE" | jq \
            --arg status "IDLE" \
            --arg last_event "Stop" \
            --arg last_event_time "$NOW" \
            '
            .status = $status |
            .last_event = $last_event |
            .last_event_time = $last_event_time
            ' > "$TEMP_FILE"
        mv "$TEMP_FILE" "$STATE_FILE"
        ;;

    PermissionRequest)
        TOOL_NAME="$(echo "$INPUT_JSON" | jq -r '.tool_name // "unknown"')"

        echo "$CURRENT_STATE" | jq \
            --arg status "WAITING_PERMISSION" \
            --arg tool "$TOOL_NAME" \
            --arg last_event "PermissionRequest" \
            --arg last_event_time "$NOW" \
            '
            .status = $status |
            .last_tool = $tool |
            .last_event = $last_event |
            .last_event_time = $last_event_time
            ' > "$TEMP_FILE"
        mv "$TEMP_FILE" "$STATE_FILE"
        ;;

    UserPromptSubmit)
        echo "$CURRENT_STATE" | jq \
            --arg status "WORKING" \
            --arg last_event "UserPromptSubmit" \
            --arg last_event_time "$NOW" \
            '
            .status = $status |
            .last_event = $last_event |
            .last_event_time = $last_event_time
            ' > "$TEMP_FILE"
        mv "$TEMP_FILE" "$STATE_FILE"
        ;;

    SubagentStart)
        echo "$CURRENT_STATE" | jq \
            --arg last_event "SubagentStart" \
            --arg last_event_time "$NOW" \
            '
            .last_event = $last_event |
            .last_event_time = $last_event_time |
            .subagent_count = ((.subagent_count // 0) + 1)
            ' > "$TEMP_FILE"
        mv "$TEMP_FILE" "$STATE_FILE"
        ;;

    SubagentStop)
        echo "$CURRENT_STATE" | jq \
            --arg last_event "SubagentStop" \
            --arg last_event_time "$NOW" \
            '
            .last_event = $last_event |
            .last_event_time = $last_event_time |
            .subagent_count = ([0, ((.subagent_count // 0) - 1)] | max)
            ' > "$TEMP_FILE"
        mv "$TEMP_FILE" "$STATE_FILE"
        ;;

    PreCompact)
        echo "$CURRENT_STATE" | jq \
            --arg last_event "PreCompact" \
            --arg last_event_time "$NOW" \
            '
            .last_event = $last_event |
            .last_event_time = $last_event_time |
            .compact_count = ((.compact_count // 0) + 1) |
            .last_compact_time = $last_event_time
            ' > "$TEMP_FILE"
        mv "$TEMP_FILE" "$STATE_FILE"

        # Context compaction is worth notifying about
        printf '\a'
        SESSION_SHORT="${SESSION_ID:0:8}"
        COMPACT_NUM="$(echo "$CURRENT_STATE" | jq '(.compact_count // 0) + 1')"
        osascript -e "display notification \"$(_escape_applescript "Context compaction #${COMPACT_NUM}")\" with title \"Clorch\" subtitle \"$(_escape_applescript "Session ${SESSION_SHORT}…")\"" 2>/dev/null || true
        ;;

    TaskCompleted)
        echo "$CURRENT_STATE" | jq \
            --arg last_event "TaskCompleted" \
            --arg last_event_time "$NOW" \
            '
            .last_event = $last_event |
            .last_event_time = $last_event_time |
            .task_completed_count = ((.task_completed_count // 0) + 1)
            ' > "$TEMP_FILE"
        mv "$TEMP_FILE" "$STATE_FILE"
        ;;

    TeammateIdle)
        echo "$CURRENT_STATE" | jq \
            --arg last_event "TeammateIdle" \
            --arg last_event_time "$NOW" \
            '
            .last_event = $last_event |
            .last_event_time = $last_event_time
            ' > "$TEMP_FILE"
        mv "$TEMP_FILE" "$STATE_FILE"
        ;;

    SessionEnd)
        rm -f "$STATE_FILE"
        ;;

    *)
        # Unknown event — ignore silently
        ;;
esac
