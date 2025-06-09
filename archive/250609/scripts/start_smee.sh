#!/usr/bin/env bash
#set -e

echo "Generating new Smee channel URL…"
exit 1
SMEE_URL=$(curl -sI https://smee.io/new \
  | grep -i '^Location:' \
  | awk '{print $2}' \
  | tr -d '\r')
export SMEE_URL
echo "SMEE_URL=$SMEE_URL"

echo "Launching tmuxp session 'gitman'…"
tmuxp load #tmuxp.yaml

