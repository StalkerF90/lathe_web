#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  docker-entrypoint.sh
#  1. Генерирует config.yml если его ещё нет (первый запуск)
#  2. Запускает Streamlit
# ─────────────────────────────────────────────────────────────
set -e

echo "🚀 Запуск системы контроля токарных станков..."

# Генерируем config.yml только при первом запуске
if [ ! -f "$CONFIG_PATH" ]; then
    echo "📝 Генерация config.yml (первый запуск)..."
    python generate_config.py
    echo "✅ Пользователи созданы: admin / admin123  |  user1 / user123"
else
    echo "✅ config.yml найден, пропускаем генерацию."
fi

echo "📊 Запуск Streamlit на порту $STREAMLIT_SERVER_PORT..."
exec streamlit run app.py \
    --server.port="$STREAMLIT_SERVER_PORT" \
    --server.address="$STREAMLIT_SERVER_ADDRESS" \
    --server.headless=true \
    --browser.gatherUsageStats=false \
    --server.enableCORS=false \
    --server.enableXsrfProtection=true
