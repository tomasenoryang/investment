#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
cd "$project_dir"
url=http://127.0.0.1:8765/
python="$project_dir/.venv/bin/python"

page_is_ready() {
    curl --noproxy '*' -fsS --max-time 1 "$url" 2>/dev/null |
        grep -Fq '<title>A 股估值曲线</title>'
}

if page_is_ready; then
    printf '估值网页已运行：%s\n' "$url"
    open "$url"
    exit 0
fi

if [ ! -x "$python" ] || ! PYTHONDONTWRITEBYTECODE=1 "$python" -c 'import akshare' >/dev/null 2>&1; then
    printf '%s\n' '请先按 README.md 安装项目依赖，再运行 ./run.sh。' >&2
    exit 1
fi

(
    attempts=0
    while [ "$attempts" -lt 10 ]; do
        if page_is_ready; then
            open "$url"
            exit
        fi
        attempts=$((attempts + 1))
        sleep 1
    done
) &
opener=$!
trap 'kill "$opener" 2>/dev/null || :' EXIT
PYTHONDONTWRITEBYTECODE=1 "$python" serve.py
