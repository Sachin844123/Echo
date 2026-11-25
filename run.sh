#!/bin/sh
set -eu

usage() {
    printf '%s\n' 'Usage: bash run.sh [--build]'
}

if [ "$#" -gt 1 ]; then
    usage >&2
    exit 2
fi
case "${1:-}" in
    ''|--build) ;;
    -h|--help)
        usage
        exit 0
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac

root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python="$root/.venv/bin/python"
if [ ! -x "$python" ]; then
    printf '%s\n' 'ECHO is not set up. Run bash setup.sh from the ECHO folder first.' >&2
    exit 1
fi

if [ "${1:-}" = '--build' ] || [ ! -f "$root/frontend/dist/index.html" ]; then
    if ! command -v npm >/dev/null 2>&1; then
        printf '%s\n' 'Install Node.js 22.12 or newer with npm to build the ECHO dashboard.' >&2
        exit 1
    fi
    (
        cd -- "$root/frontend"
        if [ ! -x node_modules/.bin/vite ]; then
            npm ci --include=dev --no-audit --no-fund
        fi
        npm run build
    )
fi

cd -- "$root/backend"
exec "$python" -m app launch
