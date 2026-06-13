#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
source strem_switcher/bin/activate
export PYTHONPATH=.
exec python -m src.main
