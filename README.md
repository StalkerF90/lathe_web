# ⚙️ Система контроля токарных станков

Веб-приложение на **Streamlit** для мониторинга загрузки токарных станков с ролевым доступом, SQLite-базой данных и Docker-развёртыванием.

---

## 🚀 Быстрый старт

```bash
git clone <repo_url>
cd lathe_web
docker-compose up -d
```

Откройте в браузере: **http://localhost:8501**

### Учётные записи по умолчанию

| Логин   | Пароль   | Роль          |
|---------|----------|---------------|
| admin   | admin123 | Администратор |
| user1   | user123  | Оператор      |

> ⚠️ **Измените пароли** после первого входа в продакшен-среде!

---

## 📋 Требования

- Docker 20.10+
- Docker Compose 2.0+

Или для локального запуска без Docker:
- Python 3.11+

---

## 🗂️ Структура проекта

```
lathe_web/
├── app.py                  # Главное Streamlit-приложение
├── manage_users.py         # CLI-утилита управления пользователями
├── generate_config.py      # Генератор config.yml с bcrypt-хешами
├── docker-entrypoint.sh    # Точка входа контейнера
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md

# Создаётся автоматически в volume /data:
#   app.db       — SQLite база данных
#   config.yml   — Пользователи и хеши паролей
```

---

## 🔐 Роли и права доступа

### Администратор (`admin`)
| Функция                     | Доступ |
|-----------------------------|--------|
| Просмотр всех станков       | ✅ |
| Внести выпуск               | ✅ |
| Изменить статус станка      | ✅ |
| CRUD станков                | ✅ |
| CRUD операторов             | ✅ |
| Управление пользователями   | ✅ |
| История (просмотр + удаление) | ✅ |
| Графики и аналитика         | ✅ |
| Экспорт CSV                 | ✅ |

### Оператор (`user`)
| Функция                     | Доступ |
|-----------------------------|--------|
| Просмотр всех станков       | ✅ |
| Внести выпуск               | ✅ |
| История (только просмотр)   | ✅ |
| CRUD, Графики, Экспорт      | ❌ |

---

## 🗄️ Схема базы данных (SQLite)

```sql
-- Станки
CREATE TABLE machines (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL,
    model        TEXT    DEFAULT '',
    productivity REAL    DEFAULT 10.0,   -- деталей/час
    status       TEXT    DEFAULT 'free', -- busy|free|setup|idle
    notes        TEXT    DEFAULT ''
);

-- Операторы
CREATE TABLE operators (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    rank TEXT DEFAULT ''
);

-- Журнал производства
CREATE TABLE production (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    date         TEXT    NOT NULL,          -- YYYY-MM-DD
    machine_id   INTEGER NOT NULL,
    operator_id  INTEGER,
    batch        TEXT    DEFAULT '',        -- название партии
    batch_number TEXT    DEFAULT '',        -- номер партии
    setup_time   REAL    DEFAULT 0.0,       -- часы наладки
    produced_qty INTEGER DEFAULT 0,         -- выпущено деталей
    actual_time  REAL    DEFAULT 0.0,       -- рассчитано авто
    notes        TEXT    DEFAULT '',
    FOREIGN KEY (machine_id)  REFERENCES machines(id),
    FOREIGN KEY (operator_id) REFERENCES operators(id)
);
```

**Расчёт фактического времени:**
```
actual_time (ч) = produced_qty / productivity (дет/ч)
```

---

## 👥 Управление пользователями

### Через CLI (рекомендуется)

```bash
# Добавить пользователя
docker exec -it lathe_app python manage_users.py add operator2 pass456 "Смирнов А.В." user

# Список пользователей
docker exec -it lathe_app python manage_users.py list

# Сменить пароль
docker exec -it lathe_app python manage_users.py passwd admin newSecurePass123

# Удалить пользователя
docker exec -it lathe_app python manage_users.py remove operator2

# Сгенерировать хеш для ручного редактирования config.yml
docker exec -it lathe_app python manage_users.py hash "mypassword"
```

### Через интерфейс

Страница **Персонал / Станки → вкладка Пользователи** (только Admin).

---

## 🔧 Управление контейнером

```bash
# Запуск
docker-compose up -d

# Остановка
docker-compose down

# Просмотр логов
docker-compose logs -f lathe_app

# Перезапуск
docker-compose restart lathe_app

# Пересборка после изменений в коде
docker-compose up -d --build

# Проверка статуса
docker-compose ps
docker-compose exec lathe_app curl -f http://localhost:8501/_stcore/health
```

---

## 💾 Резервное копирование

```bash
# Копия базы данных
docker cp lathe_app:/data/app.db ./backup_$(date +%Y%m%d).db

# Копия конфига пользователей
docker cp lathe_app:/data/config.yml ./config_backup_$(date +%Y%m%d).yml

# Восстановление
docker cp ./backup_20240115.db lathe_app:/data/app.db
docker-compose restart lathe_app
```

---

## 🌐 Production-развёртывание

### С Nginx (reverse proxy)

```nginx
server {
    listen 80;
    server_name lathe.yourcompany.com;

    location / {
        proxy_pass http://localhost:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }
}
```

### Смените секреты в docker-compose.yml

```yaml
environment:
  - COOKIE_SECRET=your_very_long_random_secret_here_64_chars
```

---

## 🛠️ Локальный запуск (без Docker)

```bash
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate         # Windows

pip install -r requirements.txt

# Генерация config.yml
python generate_config.py

# Запуск
streamlit run app.py
```

---

## 🐛 Устранение неполадок

| Проблема | Решение |
|----------|---------|
| Белый экран при входе | Очистите кеш браузера / Ctrl+Shift+R |
| `config.yml не найден` | Убедитесь что volume примонтирован: `docker-compose down -v && docker-compose up -d` |
| Ошибка `bcrypt` | `docker-compose up -d --build` |
| База данных повреждена | Восстановите из резервной копии или удалите `app.db` для сброса |
| Порт 8501 занят | Измените `"8501:8501"` на `"8502:8501"` в docker-compose.yml |

---

## 📊 Начальные данные

При первом запуске автоматически создаются:
- **6 станков**: ЧПУ, универсальные, HAAS, Mori Seiki
- **5 операторов** с разрядами
- **История за 10 дней** (демо-данные для проверки графиков)
