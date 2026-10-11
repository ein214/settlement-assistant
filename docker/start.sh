#!/bin/sh
# 컨테이너마다 가상 데이터로 DB를 새로 만든 뒤 앱을 실행한다
set -e
python -m settlement.db.seed
exec "$@"
