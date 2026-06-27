#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# deploy-check.sh — sanity-check that the deployable artifacts exist and are
# self-consistent before pushing to Render / Vercel.
# ---------------------------------------------------------------------------
# Verifies:
#   - render.yaml is syntactically valid (Python YAML fallback if yq absent)
#   - backend/Dockerfile + .dockerignore exist
#   - frontend/vercel.json exists and parses as JSON
#   - render.yaml references a dockerfile that actually exists
#   - vercel.json rewrites every route to /index.html
#   - both required directories have the expected sentinel files
# Exits non-zero on the first failure.
# ---------------------------------------------------------------------------

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

ok()  { printf "  \033[1;32m✔\033[0m %s\n" "$*"; }
bad() { printf "  \033[1;31m✘\033[0m %s\n" "$*" >&2; }
hdr() { printf "\n\033[1;36m== %s ==\033[0m\n" "$*"; }

fail=0

check_file() {
    local path="$1"
    if [[ -f "$REPO_ROOT/$path" ]]; then
        ok "$path"
    else
        bad "$path (missing)"
        fail=$((fail + 1))
    fi
}

yaml_load() {
    # Use yq if available, else fall back to a tiny Python parser.
    if command -v yq >/dev/null 2>&1; then
        yq eval "$1" "$2"
    else
        python -c "
import sys, yaml
with open('$2') as f:
    data = yaml.safe_load(f)
keys = '$1'.split('.')
for k in keys:
    if k.startswith('[') and k.endswith(']'):
        idx = int(k[1:-1])
        data = data[idx]
    else:
        data = data[k]
print(data)
"
    fi
}

hdr "render.yaml"
check_file render.yaml

DOCKERFILE_REL="$(yaml_load 'services.[0].dockerfilePath' "$REPO_ROOT/render.yaml")"
ROOTDIR_REL="$(yaml_load 'services.[0].rootDir' "$REPO_ROOT/render.yaml")"
PLAN="$(yaml_load 'services.[0].plan' "$REPO_ROOT/render.yaml")"

if [[ -f "$REPO_ROOT/$ROOTDIR_REL/$DOCKERFILE_REL" ]]; then
    ok "render.yaml.dockerfilePath resolves: $ROOTDIR_REL/$DOCKERFILE_REL"
else
    bad "render.yaml references $ROOTDIR_REL/$DOCKERFILE_REL but it does not exist"
    fail=$((fail + 1))
fi

if [[ "$PLAN" == "free" ]]; then
    ok "render.yaml.plan == free"
else
    bad "render.yaml.plan is '$PLAN' (expected 'free')"
    fail=$((fail + 1))
fi

hdr "vercel.json"
check_file frontend/vercel.json

if python -c "
import json, sys
data = json.load(open('$REPO_ROOT/frontend/vercel.json'))
assert data.get('framework') == 'vite', 'framework != vite'
rewrites = data.get('rewrites', [])
assert any(r.get('source') == '/(.*)' and r.get('destination') == '/index.html' for r in rewrites), 'no SPA rewrite to /index.html'
print('vercel.json ok')
" ; then
    ok "vercel.json: framework=vite + SPA rewrite → /index.html"
else
    bad "vercel.json failed schema check"
    fail=$((fail + 1))
fi

hdr "backend"
check_file backend/Dockerfile
check_file backend/.dockerignore
check_file backend/requirements.txt
check_file backend/.env.example

hdr "frontend"
check_file frontend/package.json
check_file frontend/vite.config.ts
check_file frontend/.env.example

hdr "evaluation"
check_file evaluation/queries.json
check_file evaluation/eval.py

hdr "summary"
if [[ $fail -eq 0 ]]; then
    printf "\033[1;32mAll deploy checks passed.\033[0m\n"
    exit 0
else
    printf "\033[1;31m%d check(s) failed.\033[0m\n" "$fail" >&2
    exit 1
fi