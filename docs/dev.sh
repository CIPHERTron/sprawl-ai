#!/usr/bin/env bash
#
# Robust launcher for the Mintlify docs dev server.
#
# Works around a known Mintlify CLI bug (mintlify/docs#5624) where the npm-bundled
# `tar` silently drops the client's `.next/` directory during extraction on macOS,
# causing `mint dev` to fail with "Client not built". This script pre-seeds the
# client cache using the system `tar` (which extracts `.next/` correctly) and only
# re-fetches when the cached client is missing or out of date.
#
# Usage: ./dev.sh   (or `make docs-dev` from the repo root)
set -euo pipefail

PORT="${PORT:-3333}"
RELEASES_URL="https://releases.mintlify.com"
DOT_MINTLIFY="$HOME/.mintlify"
MINT_DIR="$DOT_MINTLIFY/mint"
NEXT_MARKER="$MINT_DIR/apps/client/.next/required-server-files.json"
VERSION_FILE="$MINT_DIR/mint-version.txt"

# ── 1. Ensure Node 20+ (Mintlify requires >= 20.17) ───────────────────────────
ensure_node20() {
  local major
  major="$(node -v 2>/dev/null | sed 's/v\([0-9]*\).*/\1/' || echo 0)"
  if [ "$major" -ge 20 ] 2>/dev/null; then
    return 0
  fi
  # Try nvm
  if [ -s "$HOME/.nvm/nvm.sh" ]; then
    # shellcheck disable=SC1091
    . "$HOME/.nvm/nvm.sh"
    nvm use 20 >/dev/null 2>&1 || nvm use --lts >/dev/null 2>&1 || true
    major="$(node -v 2>/dev/null | sed 's/v\([0-9]*\).*/\1/' || echo 0)"
  fi
  if [ "$major" -lt 20 ] 2>/dev/null; then
    echo "ERROR: Node 20+ is required (found $(node -v 2>/dev/null || echo none))." >&2
    echo "       Install/select Node 20, e.g.  nvm install 20 && nvm use 20" >&2
    exit 1
  fi
}

# ── 2. Ensure the `mint` CLI is available ─────────────────────────────────────
ensure_mint() {
  if command -v mint >/dev/null 2>&1; then
    return 0
  fi
  echo "Installing Mintlify CLI (mint)..."
  npm install -g mint@latest
}

# ── 3. Repair the client cache if `.next/` was dropped by the buggy tar ───────
repair_client() {
  local latest
  latest="$(curl -fsSL "$RELEASES_URL/mint-version.txt" 2>/dev/null || true)"
  [ -z "$latest" ] && return 0   # offline: let mint use whatever it has

  local current=""
  [ -f "$VERSION_FILE" ] && current="$(tr -d '[:space:]' < "$VERSION_FILE")"

  # Healthy if the marker exists AND the cached version matches latest
  if [ -f "$NEXT_MARKER" ] && [ "$current" = "$latest" ]; then
    return 0
  fi

  echo "Repairing Mintlify client cache (version $latest) with system tar..."
  local tarball="/tmp/mint-client-${latest}.tar.gz"
  curl -fsSL -o "$tarball" "$RELEASES_URL/mint-${latest}.tar.gz"
  rm -rf "$MINT_DIR" "$DOT_MINTLIFY/mint-last"
  mkdir -p "$DOT_MINTLIFY"
  tar -xzf "$tarball" -C "$DOT_MINTLIFY"
  printf "%s" "$latest" > "$VERSION_FILE"
  rm -f "$tarball"

  if [ ! -f "$NEXT_MARKER" ]; then
    echo "ERROR: client repair failed (.next still missing)." >&2
    exit 1
  fi
}

ensure_node20
ensure_mint
repair_client

cd "$(dirname "$0")"
exec mint dev --port "$PORT" "$@"
