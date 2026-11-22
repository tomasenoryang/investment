#!/bin/sh
# 项目直接依赖：akshare。所有传递依赖均随 .venv 一并清除。
# 新增直接依赖时更新此清单，并将依赖安装在本项目的 .venv 内。
# 已安装的软件包（含传递依赖和环境工具）
#   akshare==1.20.65
#   beautifulsoup4==4.15.0
#   certifi==2026.11.20
#   cffi==2.1.1
#   charset-normalizer==3.5.2
#   curl_cffi==0.17.0
#   et_xmlfile==2.0.0
#   html5lib==1.1
#   idna==3.20
#   lxml==6.1.3
#   mini-racer==0.14.1
#   numpy==2.5.5
#   openpyxl==3.1.5
#   pandas==3.1.1
#   pip==26.1
#   pycparser==3.12
#   python-dateutil==4.0.0
#   requests==2.34.2
#   six==1.17.0
#   soupsieve==4.1.3
#   tqdm==4.70.1
#   typing_extensions==4.16.0
#   tzdata==2026.6
#   urllib3==2.8.0
#   webencodings==0.6.1
#   xlrd==2.0.2
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
environment="$project_dir/.venv"

if [ -L "$environment" ]; then
    printf '%s\n' '检测到 .venv 是符号链接，未执行清理。' >&2
    exit 1
fi
if [ ! -e "$environment" ]; then
    printf '%s\n' '项目依赖环境已清除。'
    exit 0
fi
if [ ! -f "$environment/pyvenv.cfg" ]; then
    printf '%s\n' '.venv 缺少 Python 虚拟环境标记，未执行清理。' >&2
    exit 1
fi

rm -rf -- "$environment"
printf '%s\n' '已清除项目虚拟环境和其中的全部依赖。'
