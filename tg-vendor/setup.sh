#!/bin/bash
set -e

echo "=== 패키지 설치 ==="
pip3 install -e .
pip3 install LOLZTEAM  # pyproject.toml로 안 잡힐 경우 대비

echo "=== .env 파일 확인 ==="
if [ ! -f .env ]; then
  cp .env.example .env
  echo "⚠️  .env 파일을 생성했습니다. 값을 채워주세요: nano .env"
  exit 1
fi

echo "=== DB 초기화 ==="
python3 -c "import asyncio; from core.db import init_db; asyncio.run(init_db())"

echo "✅ 완료. 이제 실행하세요:"
echo "  pm2 start ecosystem.config.js"
echo "  pm2 save"
echo "  pm2 startup  (서버 재시작 후 자동 실행 등록)"
