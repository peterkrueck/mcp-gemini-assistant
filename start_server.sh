#!/bin/bash
cd "$(dirname "$0")"

# Load environment variables from .env file if it exists
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Check if GEMINI_API_KEY is set
if [ -z "$GEMINI_API_KEY" ]; then
    echo "Error: GEMINI_API_KEY environment variable must be set" >&2
    echo "Please set it in .env file or as environment variable" >&2
    exit 1
fi

exec ./venv/bin/python gemini_mcp.py