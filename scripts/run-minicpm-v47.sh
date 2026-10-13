#!/bin/sh
# Opt in to one MiniCPM-V 4.7 checkpoint for both Planner and OCR requests.
# Credentials must come from the process environment; never source .env here.
set -eu

if [ -z "${TEXADA_OPENAI_API_KEY:-}" ]; then
    printf '%s\n' 'Set TEXADA_OPENAI_API_KEY in your environment before starting the MiniCPM-V 4.7 profile.' >&2
    printf '%s\n' 'For an unauthenticated local server, set it to a non-secret placeholder such as local-no-key.' >&2
    exit 2
fi

case "${TEXADA_OPENAI_MODEL_NAME:-}" in
    ''|MiniCPM-V-4.7-1B) ;;
    *)
        printf '%s\n' 'TEXADA_OPENAI_MODEL_NAME must be MiniCPM-V-4.7-1B for this single-checkpoint profile.' >&2
        exit 2
        ;;
esac
case "${TEXADA_OPENAI_VISION_MODEL_NAME:-}" in
    ''|MiniCPM-V-4.7-1B) ;;
    *)
        printf '%s\n' 'TEXADA_OPENAI_VISION_MODEL_NAME must be MiniCPM-V-4.7-1B for this single-checkpoint profile.' >&2
        exit 2
        ;;
esac

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_dir"

export TEXADA_BACKEND=openai_compatible
export TEXADA_OPENAI_BASE_URL="${TEXADA_OPENAI_BASE_URL:-https://api.modelbest.cn/v1}"
export TEXADA_OPENAI_MODEL_NAME=MiniCPM-V-4.7-1B
export TEXADA_OPENAI_VISION_MODEL_NAME=MiniCPM-V-4.7-1B
export TEXADA_NL_CANDIDATE_FIRST=true
export TEXADA_OCR_PREPROCESSING=raw

if ! command -v uv >/dev/null 2>&1; then
    printf '%s\n' 'The MiniCPM-V 4.7 launcher requires uv; install uv and run uv sync --extra dev in this checkout first.' >&2
    exit 127
fi

exec uv run --no-sync texada serve "$@"
