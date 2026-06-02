#!/bin/bash
set -e
mkdir -p /home/runner/workspace/.venv 2>/dev/null || true
export UV_PROJECT_ENVIRONMENT="/home/runner/workspace/.venv"
export VIRTUAL_ENV="/home/runner/workspace/.venv"
export UV_NO_SYNC=1

npm run build

pnpm --filter @workspace/api-server run build
pnpm --filter @workspace/web run build
