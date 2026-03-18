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

# Extract session_id — bail out if missing or invalid
SESSION_ID="$(echo "$INPUT_JSON" | jq -r '.session_id // empty')"
if [[ -z "$SESSION_ID" ]]; then
    exit 0
fi
# Guard against path traversal: only allow alphanumeric, hyphens, underscores
if [[ ! "$SESSION_ID" =~ ^[a-zA-Z0-9_-]+$ ]]; then
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
# Detect VS Code when TERM_PROGRAM is not set (extension runs outside a terminal).
# Check env vars first, then fall back to parent process path (.vscode/extensions/).
if [[ -z "${TERM_PROGRAM:-}" ]]; then
    if [[ -n "${VSCODE_PID:-}" || -n "${VSCODE_IPC_HOOK_CLI:-}" ]]; then
        TERM_PROGRAM="vscode"
    elif ps -p "$PPID" -o command= 2>/dev/null | grep -q '\.vscode/extensions/'; then
        TERM_PROGRAM="vscode"
    fi
fi
TMUX_WINDOW=""
TMUX_PANE=""
TMUX_SESSION=""
TMUX_WINDOW_INDEX=""
# Detect tmux window AND pane ONLY if Claude Code's tty is actually inside a tmux pane.
# Plain `tmux display-message` returns whatever the last client sees, which is
# wrong when the agent runs in an iTerm tab while a tmux server is up.
_CLAUDE_TTY="$(ps -p "$PPID" -o tty= 2>/dev/null | tr -d ' ')"
if [[ -n "$_CLAUDE_TTY" && "$_CLAUDE_TTY" != "??" ]]; then
    _TMUX_INFO="$(tmux list-panes -a -F '#{pane_tty}|||#{window_name}|||#{pane_index}|||#{session_name}|||#{window_index}' 2>/dev/null \
        | awk -v tty="/dev/$_CLAUDE_TTY" -F '\\|\\|\\|' '$1 == tty { print $2; print $3; print $4; print $5; exit }')" || true
    if [[ -n "$_TMUX_INFO" ]]; then
        { read -r TMUX_WINDOW; read -r TMUX_PANE; read -r TMUX_SESSION; read -r TMUX_WINDOW_INDEX; } <<< "$_TMUX_INFO"
    fi
fi
# Collect git data from CWD (branch name and dirty file count)
GIT_BRANCH=""
GIT_DIRTY=0
_EFFECTIVE_CWD="${CWD_FROM_INPUT:-}"
if [[ -z "$_EFFECTIVE_CWD" ]]; then
    _EFFECTIVE_CWD="$(echo "$CURRENT_STATE" | jq -r '.cwd // empty')"
fi
if [[ -n "$_EFFECTIVE_CWD" && -d "$_EFFECTIVE_CWD" ]]; then
    GIT_BRANCH="$(cd "$_EFFECTIVE_CWD" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
    if [[ -n "$GIT_BRANCH" ]]; then
        GIT_DIRTY="$(cd "$_EFFECTIVE_CWD" && git status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
    fi
fi

CURRENT_STATE="$(echo "$CURRENT_STATE" | jq \
    --arg sid "$SESSION_ID" \
    --arg cwd "${CWD_FROM_INPUT:-}" \
    --arg now "$NOW" \
    --argjson pid "$PPID" \
    --arg tmux_win "${TMUX_WINDOW:-}" \
    --arg tmux_pane "${TMUX_PANE:-}" \
    --arg tmux_sess "${TMUX_SESSION:-}" \
    --arg tmux_widx "${TMUX_WINDOW_INDEX:-}" \
    --arg term_prog "${TERM_PROGRAM:-}" \
    --arg git_branch "$GIT_BRANCH" \
    --argjson git_dirty "${GIT_DIRTY:-0}" \
    '
    if .session_id == null or .session_id == "" then .session_id = $sid else . end |
    if (.cwd == null or .cwd == "") and $cwd != "" then .cwd = $cwd else . end |
    if (.project_name == null or .project_name == "") and $cwd != "" then .project_name = ($cwd | split("/") | last) else . end |
    if .started_at == null or .started_at == "" then .started_at = $now else . end |
    if .tool_count == null then .tool_count = 0 else . end |
    if .error_count == null then .error_count = 0 else . end |
    if .activity_history == null then .activity_history = [0,0,0,0,0,0,0,0,0,0] else . end |
    .pid = $pid |
    if $tmux_win != "" then .tmux_window = $tmux_win else . end |
    if $tmux_pane != "" then .tmux_pane = $tmux_pane else . end |
    if $tmux_sess != "" then .tmux_session = $tmux_sess else . end |
    if $tmux_widx != "" then .tmux_window_index = $tmux_widx else . end |
    if .term_program == null or .term_program == "" then .term_program = $term_prog else . end |
    if (.git_branch == null or .git_branch == "") and $git_branch != "" then .git_branch = $git_branch else . end |
    if (.git_dirty_count == null) and $git_branch != "" then .git_dirty_count = $git_dirty else . end |
    if $git_branch != "" then .git_dirty_count = $git_dirty else . end
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
            --arg status "IDLE" \
            --arg cwd "$CWD" \
            --arg started_at "$NOW" \
            --arg project_name "$PROJECT_NAME" \
            --arg model "$MODEL" \
            --arg last_event "SessionStart" \
            --arg last_event_time "$NOW" \
            --argjson pid "$PPID" \
            --arg tmux_win "${TMUX_WINDOW:-}" \
            --arg tmux_pane "${TMUX_PANE:-}" \
            --arg tmux_sess "${TMUX_SESSION:-}" \
            --arg tmux_widx "${TMUX_WINDOW_INDEX:-}" \
            --arg term_prog "${TERM_PROGRAM:-}" \
            --arg git_branch "$GIT_BRANCH" \
            --argjson git_dirty "${GIT_DIRTY:-0}" \
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
                activity_history: [0,0,0,0,0,0,0,0,0,0],
                pid: $pid,
                tmux_window: $tmux_win,
                tmux_pane: $tmux_pane,
                tmux_session: $tmux_sess,
                tmux_window_index: $tmux_widx,
                term_program: $term_prog,
                git_branch: $git_branch,
                git_dirty_count: $git_dirty
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
            .notification_message = null |
            .tool_request_summary = null |
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
            .last_event_time = $last_event_time |
            .notification_message = null |
            .tool_request_summary = null
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
            .error_count = ((.error_count // 0) + 1) |
            .tool_request_summary = null
            ' > "$TEMP_FILE"
        mv "$TEMP_FILE" "$STATE_FILE"
        ;;

    Stop)
        # Don't downgrade WAITING_ANSWER to IDLE — the Notification
        # handler already set it and Stop fires right after (before the
        # user types their answer).
        # WAITING_PERMISSION is NOT preserved: permission requests block
        # the turn, so by the time Stop fires the user has already
        # approved or denied — the status should go back to IDLE.
        CURRENT_STATUS="$(echo "$CURRENT_STATE" | jq -r '.status // "IDLE"')"
        if [[ "$CURRENT_STATUS" == "WAITING_ANSWER" ]]; then
            STOP_STATUS="$CURRENT_STATUS"
        else
            STOP_STATUS="IDLE"
        fi

        echo "$CURRENT_STATE" | jq \
            --arg status "$STOP_STATUS" \
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

        # Build tool_request_summary from tool_input for TUI detail view
        TOOL_SUMMARY="$(echo "$INPUT_JSON" | jq -r --arg tool "$TOOL_NAME" '
            .tool_input as $inp |
            if $inp == null then "" else
            (if $tool == "Bash" then
                "$ " + (($inp.command // "") | .[0:300])
            elif $tool == "Edit" then
                (($inp.file_path // "") + "\n" +
                 (($inp.old_string // "") | split("\n") | .[0:3] | map("- " + .) | join("\n")) + "\n" +
                 (($inp.new_string // "") | split("\n") | .[0:3] | map("+ " + .) | join("\n")))
            elif $tool == "Write" then
                (($inp.file_path // "") + " (" + (($inp.content // "") | split("\n") | length | tostring) + " lines)\n" +
                 (($inp.content // "") | split("\n") | .[0:3] | join("\n")))
            elif $tool == "Read" then
                ($inp.file_path // "")
            elif $tool == "WebFetch" then
                ($inp.url // "")
            elif $tool == "Task" then
                "[" + ($inp.subagent_type // "?") + "] " + ($inp.description // "")
            elif $tool == "Grep" then
                ($inp.pattern // "") + (if $inp.path then " in " + $inp.path else "" end)
            elif $tool == "Glob" then
                ($inp.pattern // "") + (if $inp.path then " in " + $inp.path else "" end)
            else
                ($inp | tostring | .[0:300])
            end) | .[0:500]
            end
        ')"

        echo "$CURRENT_STATE" | jq \
            --arg status "WAITING_PERMISSION" \
            --arg tool "$TOOL_NAME" \
            --arg last_event "PermissionRequest" \
            --arg last_event_time "$NOW" \
            --arg summary "$TOOL_SUMMARY" \
            '
            .status = $status |
            .last_tool = $tool |
            .last_event = $last_event |
            .last_event_time = $last_event_time |
            .tool_request_summary = (if $summary == "" then null else $summary end)
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
            .last_event_time = $last_event_time |
            .notification_message = null |
            .tool_request_summary = null
            ' > "$TEMP_FILE"
        mv "$TEMP_FILE" "$STATE_FILE"
        ;;

    SubagentStart)
        AGENT_ID="$(echo "$INPUT_JSON" | jq -r '.agent_id // empty')"
        if [[ -n "$AGENT_ID" && ! "$AGENT_ID" =~ ^[a-zA-Z0-9_-]+$ ]]; then
            AGENT_ID=""
        fi
        AGENT_TYPE="$(echo "$INPUT_JSON" | jq -r '.agent_type // "unknown"')"

        echo "$CURRENT_STATE" | jq \
            --arg last_event "SubagentStart" \
            --arg last_event_time "$NOW" \
            --arg agent_id "$AGENT_ID" \
            --arg agent_type "$AGENT_TYPE" \
            --arg now "$NOW" \
            '
            .last_event = $last_event |
            .last_event_time = $last_event_time |
            .subagents = ((.subagents // {}) |
                if $agent_id != "" then
                    .[$agent_id] = {
                        agent_id: $agent_id,
                        agent_type: $agent_type,
                        status: "running",
                        started_at: $now
                    }
                else . end)
            ' > "$TEMP_FILE"
        mv "$TEMP_FILE" "$STATE_FILE"
        ;;

    SubagentStop)
        AGENT_ID="$(echo "$INPUT_JSON" | jq -r '.agent_id // empty')"
        if [[ -n "$AGENT_ID" && ! "$AGENT_ID" =~ ^[a-zA-Z0-9_-]+$ ]]; then
            AGENT_ID=""
        fi
        LAST_MSG="$(echo "$INPUT_JSON" | jq -r '.last_assistant_message // "" | .[0:200]')"
        TRANSCRIPT="$(echo "$INPUT_JSON" | jq -r '.agent_transcript_path // ""')"

        echo "$CURRENT_STATE" | jq \
            --arg last_event "SubagentStop" \
            --arg last_event_time "$NOW" \
            --arg agent_id "$AGENT_ID" \
            --arg last_msg "$LAST_MSG" \
            --arg transcript "$TRANSCRIPT" \
            --arg now "$NOW" \
            '
            .last_event = $last_event |
            .last_event_time = $last_event_time |
            .subagents = ((.subagents // {}) |
                if $agent_id != "" then
                    if .[$agent_id] then
                        .[$agent_id].status = "completed" |
                        .[$agent_id].completed_at = $now |
                        .[$agent_id].last_message = $last_msg |
                        .[$agent_id].transcript_path = $transcript
                    else
                        .[$agent_id] = {
                            agent_id: $agent_id,
                            agent_type: "unknown",
                            status: "completed",
                            started_at: $now,
                            completed_at: $now,
                            last_message: $last_msg,
                            transcript_path: $transcript
                        }
                    end
                else . end)
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
