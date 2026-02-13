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

log "=============================================="
log "Daily Briefing Pipeline — Starting"
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
    log "       Required keys: GEMINI_API_KEY, OPENAI_API_KEY, RESEND_API_KEY, EMAIL_TO, YOUTUBE_API_KEY"
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
    exit 0
else
    log "Pipeline finished with warnings/errors. Check log: ${LOG_FILE}"
    exit 1
fi
