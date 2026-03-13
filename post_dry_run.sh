#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "Usage: ./post_dry_run.sh <folder_slug>"
  exit 1
fi

FOLDER_SLUG="$1"
conda run -n lila python ./src/mass_production/post_dry_run.py "$FOLDER_SLUG"
