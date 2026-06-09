#!/usr/bin/env bash
#
# Deploy / update the folio_libris_rtac stack on the server.
#
# The usual update flow (DEPLOY.md) is: pull the latest code, rebuild the image,
# recreate the container, and wait until it is healthy. This script does that in
# one command and fails loudly (non-zero exit + recent logs) if anything breaks,
# so it is safe to run by hand or from CI/cron.
#
#   scripts/deploy.sh                 # pull, build, recreate, wait for healthy
#   scripts/deploy.sh --validate      # ...then check each library's FOLIO/edge API
#   scripts/deploy.sh --no-pull       # deploy the current working tree as-is
#   scripts/deploy.sh --logs          # follow the container log after deploying
#
# docker needs sudo on the server (the deploy user isn't in the docker group);
# override with DOCKER=docker if your user can reach the daemon directly.
set -euo pipefail

# --- config -----------------------------------------------------------------

DOCKER=${DOCKER:-sudo docker}     # how to invoke docker (sudo by default)
SERVICE=rtac                      # compose service name (== container_name)
WAIT_TIMEOUT=${WAIT_TIMEOUT:-120} # seconds to wait for the container to be healthy

do_pull=1
do_build=1
do_validate=0
do_logs=0
strict=0

usage() {
    cat <<'EOF'
Deploy / update the folio_libris_rtac stack (pull, build, recreate, wait healthy).

Usage: scripts/deploy.sh [options]

  --no-pull    deploy the current working tree (skip git pull)
  --no-build   recreate without rebuilding the image
  --validate   after deploy, check each library via /validate-folio-connection
  --strict     with --validate, exit non-zero if any library check fails
  --logs       follow the container log after a successful deploy
  -h, --help   show this help

docker runs via sudo by default (set DOCKER=docker to override); WAIT_TIMEOUT
overrides the health-wait (default 120s).
EOF
    exit "${1:-0}"
}

while [ $# -gt 0 ]; do
    case "$1" in
        --no-pull)  do_pull=0 ;;
        --no-build) do_build=0 ;;
        --validate) do_validate=1 ;;
        --strict)   strict=1 ;;
        --logs)     do_logs=1 ;;
        -h|--help)  usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 >&2 ;;
    esac
    shift
done

# Run from the repo root regardless of where the script was invoked from, so the
# compose file and libraries/ are found.
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$REPO_ROOT"

log() { printf '\n=> %s\n' "$*"; }

# --- 1. update the code -----------------------------------------------------

if [ "$do_pull" -eq 1 ]; then
    log "Updating code (git pull --ff-only)"
    before=$(git rev-parse --short HEAD)
    if ! git pull --ff-only; then
        echo "git pull --ff-only failed — resolve local changes/divergence and" \
             "retry, or run with --no-pull to deploy the current tree." >&2
        exit 1
    fi
    after=$(git rev-parse --short HEAD)
    if [ "$before" = "$after" ]; then
        echo "Already up to date ($after)."
    else
        echo "Updated $before -> $after."
    fi
else
    log "Skipping git pull (--no-pull); deploying the current working tree"
fi

# --- 2. build + (re)create the container, wait until healthy ----------------

build_flag=()
[ "$do_build" -eq 1 ] && build_flag=(--build)

log "Starting the stack (docker compose up$([ "$do_build" -eq 1 ] && echo ' --build') -d --wait)"
if ! $DOCKER compose up "${build_flag[@]}" -d --wait --wait-timeout "$WAIT_TIMEOUT"; then
    echo "Deploy failed — recent logs:" >&2
    $DOCKER compose logs --tail 50 "$SERVICE" >&2 || true
    exit 1
fi

$DOCKER compose ps

# --- 3. optional per-library API check --------------------------------------

if [ "$do_validate" -eq 1 ]; then
    log "Validating each library's backend API(s) via /validate-folio-connection"

    sigels=()
    for s in libraries/*/settings.json; do
        [ -e "$s" ] || continue
        sigels+=("$(basename "$(dirname "$s")")")
    done

    if [ "${#sigels[@]}" -eq 0 ]; then
        echo "  (no libraries configured under libraries/)"
    else
        failed=0
        for sigel in "${sigels[@]}"; do
            # Run inside the container so we don't depend on the host port (which
            # is optional) or on FOLIO being reachable from the host. The image
            # has python; the sigel is passed as argv (never interpolated into
            # code) and url-encoded.
            if ! $DOCKER compose exec -T "$SERVICE" python -c '
import json, sys, urllib.error, urllib.request
from urllib.parse import quote
sigel = sys.argv[1]
url = "http://localhost:5000/%s/validate-folio-connection" % quote(sigel)
try:
    with urllib.request.urlopen(url, timeout=20) as r:
        code, body = r.status, r.read().decode()
except urllib.error.HTTPError as e:
    code, body = e.code, e.read().decode()
except Exception as e:
    print("  %-12s ERROR %s" % (sigel, e)); sys.exit(1)
try:
    body = json.dumps(json.loads(body))
except ValueError:
    pass
print("  %-12s HTTP %s  %s" % (sigel, code, body))
sys.exit(0 if code == 200 else 1)
' "$sigel"; then
                failed=$((failed + 1))
            fi
        done

        if [ "$failed" -gt 0 ]; then
            echo "  $failed of ${#sigels[@]} library check(s) did not return 200." >&2
            [ "$strict" -eq 1 ] && exit 1
        fi
    fi
fi

# --- 4. done ----------------------------------------------------------------

log "Deploy OK — rtac is healthy."

if [ "$do_logs" -eq 1 ]; then
    log "Following logs (Ctrl-C to stop)"
    exec $DOCKER compose logs -f "$SERVICE"
fi
