#!/usr/bin/env bash
set -euo pipefail

BATTERIES="${BATTERIES:-}"
NOSYSTEM="${NOSYSTEM:-false}"
TARGET_USER="${_REMOTE_USER:-root}"
TARGET_HOME="${_REMOTE_USER_HOME:-}"

if [ -z "$TARGET_HOME" ]; then
  if [ "$TARGET_USER" = "root" ]; then
    TARGET_HOME="/root"
  else
    TARGET_HOME="/home/$TARGET_USER"
  fi
fi

if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y --no-install-recommends ca-certificates curl tar
fi

ARGS=("--yes" "--all-agents")
if [ -n "$BATTERIES" ]; then
  ARGS+=("--batteries" "$BATTERIES")
fi
if [ "$NOSYSTEM" = "true" ]; then
  ARGS+=("--no-system")
fi

INSTALL_URL="https://raw.githubusercontent.com/rupeshbharambe24/unienv-ai/main/install.sh"

if [ "$TARGET_USER" != "root" ] && command -v su >/dev/null 2>&1; then
  su - "$TARGET_USER" -c "curl -fsSL '$INSTALL_URL' | bash -s -- ${ARGS[*]}"
else
  HOME="$TARGET_HOME" UNIENV_HOME="$TARGET_HOME/.unienv" \
    bash -c "curl -fsSL '$INSTALL_URL' | bash -s -- ${ARGS[*]}"
fi
