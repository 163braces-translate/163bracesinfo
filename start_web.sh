#!/bin/sh
# 在本機啟動 163braces 資訊站：./start_web.sh
# 開好後瀏覽器打開 http://127.0.0.1:8163 ，後台在 http://127.0.0.1:8163/admin/ ；要關掉就在這個終端機按 Ctrl+C。
#
# 用 8163 port，不用 8000：承銷統計網站（TW Underwriting 的 start_web.sh）佔 8000，兩個可以同時開。
# 改了 app/ 底下的程式會自動重新載入，不用重開。
#
# 資料庫是這個資料夾裡的 site.sqlite3；還沒有的話，先從舊站資料庫轉一份：
#   ./.venv/bin/python -m tools.convert_wagtail db.sqlite3 site.sqlite3
# 忘記後台密碼：
#   ./.venv/bin/python -m tools.manage_users set-password 帳號
cd "$(dirname "$0")" || exit 1
if [ ! -x ./.venv/bin/uvicorn ]; then
  echo "找不到 .venv，先建立："
  echo "  python3 -m venv .venv && ./.venv/bin/pip install fastapi uvicorn jinja2 python-multipart Pillow"
  exit 1
fi
exec ./.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8163 --reload --reload-dir app "$@"
