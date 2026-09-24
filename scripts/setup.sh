#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
project_root="$PWD"
uv venv --python 3.12.14 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -m playwright install chromium
mkdir -p research
if [ ! -d research/sqlcipher/.git ]; then
  git clone --depth 1 --branch v4.6.1 https://github.com/sqlcipher/sqlcipher.git research/sqlcipher
fi
actual_commit="$(git -C research/sqlcipher rev-parse HEAD)"
[ "$actual_commit" = c5bd336ece77922433aaf6d6fe8cf203b0c299d5 ]
cd research/sqlcipher
./configure --with-crypto-lib=commoncrypto --disable-tcl --enable-tempstore=yes CFLAGS='-DSQLITE_HAS_CODEC -DSQLITE_THREADSAFE=1 -O2' --prefix="$project_root/.local"
make -j4 LIBS='-framework Security -framework CoreFoundation'
make install LIBS='-framework Security -framework CoreFoundation'
cd "$project_root"
mkdir -p .local/bin
swiftc scripts/ocr_image.swift -O -o .local/bin/wechat-image-ocr
