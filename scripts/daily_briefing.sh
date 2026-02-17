#!/bin/bash
# =============================================================================
# Daily Briefing Tool — Automated Pipeline Runner
# =============================================================================
#
# Runs the full daily briefing pipeline:
#   1. Fetch new content from all sources (since yesterday)
#   2. Process pending items through LLM summarization
#   3. Compose briefing, send email, and mark items delivered
#
# Designed to be triggered by macOS launchd every morning.
#
# INSTALL:
#   cp com.sukrit.daily-briefing.plist ~/Library/LaunchAgents/
#   launchctl load ~/Library/LaunchAgents/com.sukrit.daily-briefing.plist
#
# UNINSTALL:
#   launchctl unload ~/Library/LaunchAgents/com.sukrit.daily-briefing.plist
#   rm ~/Library/LaunchAgents/com.sukrit.daily-briefing.plist
#
# TEST NOW:
#   launchctl start com.sukrit.daily-briefing
#
# CHECK STATUS:
#   launchctl list | grep daily-briefing
#
# VIEW LOGS:
#   tail -f data/logs/briefing_$(date +%Y-%m-%d).log
#
# =============================================================================

set -o pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROJECT_DIR="/Users/sukritandvandana/Documents/Projects/daily-briefing-tool"
VENV_DIR="${PROJECT_DIR}/venv"
LOG_DIR="${PROJECT_DIR}/data/logs"
TODAY=$(date +%Y-%m-%d)
YESTERDAY=$(date -v-1d +%Y-%m-%d)
LOG_FILE="${LOG_DIR}/briefing_${TODAY}.log"

# PID file to prevent overlapping pipeline instances
PID_FILE="${LOG_DIR}/pipeline.pid"

# Ensure unbuffered Python output for real-time logging
export PYTHONUNBUFFERED=1

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

# Create log directory if it doesn't exist
mkdir -p "${LOG_DIR}"

# Redirect all stdout and stderr to the log file
exec >> "${LOG_FILE}" 2>&1

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# ---------------------------------------------------------------------------
# PID file — prevent overlapping pipeline instances
# ---------------------------------------------------------------------------
# launchd kills the shell script after its timeout, but child Python processes
# may keep running. The next morning's pipeline would start while yesterday's
# Python process is still alive, causing SQLite SQLITE_BUSY errors.

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        log "WARNING: Killing stale pipeline process (PID: ${OLD_PID}) from previous run"
        # Kill the process group (parent + children) to clean up lingering Python processes
        pkill -P "$OLD_PID" 2>/dev/null
        kill "$OLD_PID" 2>/dev/null
        sleep 2
    else
        log "Removing stale PID file (process ${OLD_PID} no longer running)"
    fi
    rm -f "$PID_FILE"
fi

echo $$ > "$PID_FILE"

# Remove PID file on any exit (success, failure, or signal)
trap 'rm -f "$PID_FILE"' EXIT

log "=============================================="
log "Daily Briefing Pipeline — Starting (PID: $$)"
log "  Project: ${PROJECT_DIR}"
log "  Date:    ${TODAY}"
log "  Since:   ${YESTERDAY}"
log "=============================================="

# ---------------------------------------------------------------------------
# Activate virtual environment
# ---------------------------------------------------------------------------
if [ ! -f "${VENV_DIR}/bin/activate" ]; then
    log "ERROR: Virtual environment not found at ${VENV_DIR}"
    log "       Run: python3 -m venv ${VENV_DIR} && pip install -r requirements.txt"
    exit 1
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
log "Activated venv: $(which python) ($(python --version 2>&1))"

# Change to project directory so relative paths in the app work correctly
cd "${PROJECT_DIR}" || {
    log "ERROR: Cannot cd to ${PROJECT_DIR}"
    exit 1
}

# Verify .env exists (python-dotenv loads it, but let's catch it early)
if [ ! -f ".env" ]; then
    log "ERROR: .env file not found at ${PROJECT_DIR}/.env"
    log "       Required keys: GEMINI_API_KEY, OPENAI_API_KEY, SMTP_USER, SMTP_APP_PASSWORD, EMAIL_FROM, EMAIL_TO, YOUTUBE_API_KEY"
    exit 1
fi

# Track pipeline status
PIPELINE_OK=true
FETCH_STATUS="skipped"
PROCESS_STATUS="skipped"
SEND_STATUS="skipped"

# ---------------------------------------------------------------------------
# Step 1: Fetch new content from all sources
# ---------------------------------------------------------------------------
log ""
log "----------------------------------------------"
log "STEP 1/3: Fetching content (since ${YESTERDAY})"
log "----------------------------------------------"

if python -m src.cli fetch --all --since "${YESTERDAY}"; then
    FETCH_STATUS="success"
    log "Fetch completed successfully."
else
    FETCH_STATUS="partial_failure"
    PIPELINE_OK=false
    log "WARNING: Fetch encountered errors (continuing pipeline — partial results may exist)."
fi

# ---------------------------------------------------------------------------
# Step 2: Process all pending items through LLM
# ---------------------------------------------------------------------------
log ""
log "----------------------------------------------"
log "STEP 2/3: Processing pending items (delay: 3s)"
log "----------------------------------------------"

if python -m src.cli process --all --delay 3; then
    PROCESS_STATUS="success"
    log "Processing completed successfully."
else
    PROCESS_STATUS="partial_failure"
    PIPELINE_OK=false
    log "WARNING: Processing encountered errors (continuing to compose briefing with available items)."
fi

# ---------------------------------------------------------------------------
# Step 3: Compose and send the briefing email
# ---------------------------------------------------------------------------
log ""
log "----------------------------------------------"
log "STEP 3/3: Composing and sending briefing"
log "----------------------------------------------"

if python -m src.cli send-briefing; then
    SEND_STATUS="success"
    log "Briefing sent successfully."
else
    SEND_STATUS="failure"
    PIPELINE_OK=false
    log "ERROR: send-briefing failed."
fi

# ---------------------------------------------------------------------------
# Cleanup — remove old logs (keep 30 days)
# ---------------------------------------------------------------------------
find "${LOG_DIR}" -name "briefing_*.log" -mtime +30 -delete 2>/dev/null

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
log ""
log "=============================================="
log "Pipeline Complete"
log "  Fetch:   ${FETCH_STATUS}"
log "  Process: ${PROCESS_STATUS}"
log "  Send:    ${SEND_STATUS}"
log "=============================================="

# Print final stats for the log
log ""
log "Database stats:"
python -m src.cli stats

if [ "${PIPELINE_OK}" = true ]; then
    log "Pipeline finished successfully."
    # macOS notification — success (subtle, no sound)
    osascript -e 'display notification "Briefing sent successfully." with title "Daily Briefing"' 2>/dev/null || true
    exit 0
else
    log "Pipeline finished with warnings/errors. Check log: ${LOG_FILE}"
    # macOS notification — failure (audible alert)
    osascript -e 'display notification "Check log for details. Fetch: '"${FETCH_STATUS}"', Process: '"${PROCESS_STATUS}"', Send: '"${SEND_STATUS}"'" with title "Daily Briefing Failed" sound name "Basso"' 2>/dev/null || true
    exit 1
fi
