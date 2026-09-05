#!/usr/bin/env bash
# Push the agent contracts in this repo into the WSL openclaw runtime.
#
# This repo is the source of truth for what each agent is told and what its
# artifacts must look like: AGENTS.md, schemas, deterministic scripts, tests,
# and skills. The WSL side additionally holds runtime state the repo does not
# own -- memory, dreams, context backups, pipeline outputs -- so those are never
# touched.
#
# Usage: ./sync-to-wsl.sh [workspace ...]     (default: every workspace-*)
set -euo pipefail
export MSYS_NO_PATHCONV=1

root="/home/openclaw/.openclaw"
here="$(cd "$(dirname "$0")" && pwd)"
cd "$here"

workspaces=("$@")
if [ ${#workspaces[@]} -eq 0 ]; then
  mapfile -t workspaces < <(ls -d workspace-* | sed 's:/*$::')
fi

paths=()
for workspace in "${workspaces[@]}"; do
  [ -d "$workspace" ] || { echo "no such workspace: $workspace" >&2; exit 1; }
  while IFS= read -r path; do paths+=("$path"); done < <(
    find "$workspace" \
      \( -name memory -o -name outputs -o -name '__pycache__' \
         -o -name '.context-backups' -o -name '.skill-backups' \
         -o -name '.pipeline-runtime' \) -prune -o \
      -type f ! -name 'DREAMS.md' ! -name '*.bak' ! -name '*.bak.*' -print
  )
done

printf 'syncing %d files into %s\n' "${#paths[@]}" "$root" >&2
tar -cf - "${paths[@]}" | wsl.exe -d OpenClawGateway -- tar -xf - -C "$root"

for workspace in "${workspaces[@]}"; do
  wsl.exe -d OpenClawGateway -- find "$root/$workspace" -name '__pycache__' -prune -exec rm -rf {} +
done
echo "done" >&2
