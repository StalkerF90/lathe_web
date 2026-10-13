"""
Запуск Streamlit с исправленными настройками WebSocket ping.

Streamlit 1.35 задаёт ping каждую 1 с с таймаутом 30 с, но Tornado >= 6.5
не допускает таймаут больше интервала и молча урезает его до 1 с.
Клиент, чей pong задержался дольше секунды (медленная сеть, тяжёлая страница
вроде «Партий»), отключается, переподключается, страница перерисовывается —
и так по кругу: бесконечный «Running» и сброс введённых данных.

Здесь ping отправляется раз в 10 с, и на ответ даётся 10 с.
Остальные параметры запуска — те же, что в docker-entrypoint.sh.
"""
import os
import sys
from pathlib import Path

from streamlit.web.server import server

server.TORNADO_SETTINGS["websocket_ping_interval"] = 10
server.TORNADO_SETTINGS["websocket_ping_timeout"] = 10

if not Path(os.environ.get("CONFIG_PATH", "config.yml")).exists():
    print("📝 Генерация config.yml (первый запуск)...", flush=True)
    import generate_config  # noqa: F401  — создаёт config.yml при импорте

from streamlit.web import cli

port = os.environ.get("STREAMLIT_SERVER_PORT", "8501")
address = os.environ.get("STREAMLIT_SERVER_ADDRESS", "0.0.0.0")
print(f"📊 Запуск Streamlit на порту {port} (ws ping 10s/10s)...", flush=True)
sys.argv = [
    "streamlit", "run", "app.py",
    f"--server.port={port}",
    f"--server.address={address}",
    "--server.headless=true",
    "--browser.gatherUsageStats=false",
    "--server.enableCORS=false",
    "--server.enableXsrfProtection=true",
]
sys.exit(cli.main())
