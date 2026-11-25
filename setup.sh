#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -x "$root/.venv/bin/python" ]; then
    exec "$root/.venv/bin/python" "$root/scripts/setup_echo.py" "$@"
fi

for python in python3.12 python3 python; do
    if "$python" -c 'import sys; sys.exit(sys.version_info < (3, 11))' >/dev/null 2>&1; then
        exec "$python" "$root/scripts/setup_echo.py" "$@"
    fi
done

echo 'Install Python 3.11 or newer, then run bash setup.sh again. Python 3.12 is recommended.' >&2
exit 1
