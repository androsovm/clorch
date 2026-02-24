#!/usr/bin/env bash
# notify_handler.sh - Claude Code notification hook handler for clorch
# Handles: Notification events (permission prompts, idle prompts, elicitation dialogs)
#
# Receives JSON on stdin from Claude Code hooks.
# Updates state files in /tmp/clorch/state/<session_id>.json
# Sends terminal bell and macOS notification.
#
# Configure in settings.json as:
#   "command": "CLORCH_EVENT=Notification /path/to/notify_handler.sh"
#
# chmod +x notify_handler.sh

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

# Extract notification message
MESSAGE="$(echo "$INPUT_JSON" | jq -r '.message // ""')"

# Determine new status based on notification message content
NEW_STATUS=""
MESSAGE_LOWER="$(echo "$MESSAGE" | tr '[:upper:]' '[:lower:]')"

if [[ "$MESSAGE_LOWER" == *"permission"* ]]; then
    NEW_STATUS="WAITING_PERMISSION"
elif [[ "$MESSAGE_LOWER" == *"question"* || "$MESSAGE_LOWER" == *"input"* || "$MESSAGE_LOWER" == *"answer"* || "$MESSAGE_LOWER" == *"elicitation"* ]]; then
    NEW_STATUS="WAITING_ANSWER"
fi

# Read existing state or initialize minimal state
if [[ -f "$STATE_FILE" ]]; then
    CURRENT_STATE="$(cat "$STATE_FILE")"
else
    CURRENT_STATE='{}'
fi

# Bootstrap: ensure identity fields are always present.
# Notification may be the first event we see for a running session.
CWD_FROM_INPUT="$(echo "$INPUT_JSON" | jq -r '.cwd // empty')"
CURRENT_STATE="$(echo "$CURRENT_STATE" | jq \
    --arg sid "$SESSION_ID" \
    --arg cwd "${CWD_FROM_INPUT:-}" \
    --arg now "$NOW" \
    '
    if .session_id == null or .session_id == "" then .session_id = $sid else . end |
    if (.cwd == null or .cwd == "") and $cwd != "" then .cwd = $cwd else . end |
    if (.project_name == null or .project_name == "") and $cwd != "" then .project_name = ($cwd | split("/") | last) else . end |
    if .started_at == null or .started_at == "" then .started_at = $now else . end |
    if .status == null or .status == "" then .status = "WORKING" else . end |
    if .tool_count == null then .tool_count = 0 else . end |
    if .error_count == null then .error_count = 0 else . end |
    if .activity_history == null then .activity_history = [0,0,0,0,0,0,0,0,0,0] else . end
    '
)"

# Temp file for atomic write
TEMP_FILE="$(mktemp "${STATE_DIR}/.tmp.XXXXXX")"
trap 'rm -f "$TEMP_FILE"' EXIT

# Update state file
if [[ -n "$NEW_STATUS" ]]; then
    echo "$CURRENT_STATE" | jq \
        --arg status "$NEW_STATUS" \
        --arg last_event "Notification" \
        --arg last_event_time "$NOW" \
        --arg notification_message "$MESSAGE" \
        '
        .status = $status |
        .last_event = $last_event |
        .last_event_time = $last_event_time |
        .notification_message = $notification_message
        ' > "$TEMP_FILE"
else
    echo "$CURRENT_STATE" | jq \
        --arg last_event "Notification" \
        --arg last_event_time "$NOW" \
        --arg notification_message "$MESSAGE" \
        '
        .last_event = $last_event |
        .last_event_time = $last_event_time |
        .notification_message = $notification_message
        ' > "$TEMP_FILE"
fi
mv "$TEMP_FILE" "$STATE_FILE"

# Truncate message for notification display (max 100 chars)
DISPLAY_MSG="$MESSAGE"
if [[ ${#DISPLAY_MSG} -gt 100 ]]; then
    DISPLAY_MSG="${DISPLAY_MSG:0:97}..."
fi

# Derive project name for notification title
PROJECT_NAME="$(echo "$CURRENT_STATE" | jq -r '.project_name // "Claude"')"

# Send terminal bell
printf '\a'

# Send macOS notification
osascript -e "display notification \"$(_escape_applescript "$DISPLAY_MSG")\" with title \"Clorch\" subtitle \"$(_escape_applescript "$PROJECT_NAME")\"" 2>/dev/null || true
