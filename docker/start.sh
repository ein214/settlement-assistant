#!/bin/sh
# 컨테이너마다 가상 데이터로 DB를 새로 만든 뒤 앱을 실행한다
set -e
echo "[drill] 필수 설정 DATABASE_URL이 없습니다" >&2
exit 1
python -m settlement.db.seed
exec "$@"
