"""
=============================================================================
  СИСТЕМА КОНТРОЛЯ ТОКАРНЫХ СТАНКОВ — Streamlit Web App
  Роли: admin (полный доступ), user (ввод выпуска + статусы), viewer (только просмотр)
=============================================================================
"""

import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import yaml
import io
import os
import csv
from datetime import date, timedelta, datetime
from pathlib import Path

# ── streamlit-authenticator ────────────────────────────────────────────────
try:
    import streamlit_authenticator as stauth
    HAS_AUTH = True
except ImportError:
    HAS_AUTH = False

# ── Конфиг ────────────────────────────────────────────────────────────────
DB_PATH     = os.environ.get("DB_PATH", "app.db")
CONFIG_PATH = os.environ.get("CONFIG_PATH", "config.yml")

st.set_page_config(
    page_title="Контроль станков",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS — тёмная тема, точечные правила без агрессивного перекрашивания ──
st.markdown("""
<style>
/* ═══════════════════════════════════════════════════════════════════════════
   ФОНЫ
═══════════════════════════════════════════════════════════════════════════ */
[data-testid="stAppViewContainer"],
[data-testid="stApp"],
.main .block-container    { background: #0f1117 !important; }
[data-testid="stSidebar"] { background: #1a1d27 !important; }
[data-testid="stHeader"]  { background: #0f1117 !important; }

/* ═══════════════════════════════════════════════════════════════════════════
   ОСНОВНОЙ ТЕКСТ — только на тёмном фоне страницы
   (НЕ применяем * или div глобально — это ломает selectbox/dropdown)
═══════════════════════════════════════════════════════════════════════════ */
.main .block-container p,
.main .block-container li,
.main .block-container h1,
.main .block-container h2,
.main .block-container h3,
.main .block-container h4,
.main .block-container h5,
.main .block-container h6,
.main .stMarkdown p,
.main .stMarkdown li     { color: #f0f0f0 !important; }

/* ── Заголовки ──────────────────────────────────────────────────────────── */
h1, h2, h3, h4           { color: #ffffff !important; }

/* ── Сайдбар ────────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] label { color: #e0e0f5 !important; }

/* ═══════════════════════════════════════════════════════════════════════════
   ПОДПИСИ ПОЛЕЙ ФОРМ — только label внутри конкретных компонентов
═══════════════════════════════════════════════════════════════════════════ */
[data-testid="stTextInput"]   > label,
[data-testid="stNumberInput"] > label,
[data-testid="stDateInput"]   > label,
[data-testid="stSelectbox"]   > label,
[data-testid="stMultiSelect"] > label,
[data-testid="stCheckbox"]    > label,
[data-testid="stRadio"]       > label,
[data-testid="stSlider"]      > label,
[data-testid="stTextArea"]    > label,
[data-testid="stExpander"] summary,
[data-testid="stForm"] > div > label  { color: #e0e0f5 !important; }

/* ═══════════════════════════════════════════════════════════════════════════
   ПОЛЯ ВВОДА: тёмный фон, белый текст, видимый курсор
═══════════════════════════════════════════════════════════════════════════ */
[data-testid="stTextInput"]   input,
[data-testid="stNumberInput"] input,
[data-testid="stDateInput"]   input,
[data-testid="stTextArea"]    textarea {
    color: #f0f0f0 !important;
    background-color: #1e2130 !important;
    border: 1px solid #3a3d5c !important;
    caret-color: #a0a8ff !important;   /* яркий видимый курсор */
}
[data-testid="stTextInput"]   input::placeholder,
[data-testid="stNumberInput"] input::placeholder,
[data-testid="stTextArea"]    textarea::placeholder {
    color: #7070a0 !important;
}

/* ═══════════════════════════════════════════════════════════════════════════
   SELECTBOX — выбранное значение внутри поля (тёмный фон, светлый текст)
   НЕ трогаем выпадающий список — BaseWeb сам управляет контрастом
═══════════════════════════════════════════════════════════════════════════ */
[data-testid="stSelectbox"] [data-baseweb="select"] > div:first-child {
    background-color: #1e2130 !important;
    border-color: #3a3d5c !important;
}
[data-testid="stSelectbox"] [data-baseweb="select"] [data-baseweb="select-placeholder"],
[data-testid="stSelectbox"] [data-baseweb="select"] [role="option"],
[data-testid="stSelectbox"] [data-baseweb="select"] span {
    color: #f0f0f0 !important;
}

/* ── Выпадающий список BaseWeb — светлый фон, чёрный текст ─────────────── */
[data-baseweb="popover"] [role="listbox"],
[data-baseweb="menu"]    [role="option"],
[data-baseweb="popover"] ul,
[data-baseweb="popover"] li {
    background-color: #ffffff !important;
    color: #111111 !important;
}
[data-baseweb="menu"] [role="option"]:hover,
[data-baseweb="popover"] li:hover {
    background-color: #e8eaf0 !important;
    color: #111111 !important;
}
/* выбранный пункт */
[data-baseweb="menu"] [aria-selected="true"] {
    background-color: #d8daff !important;
    color: #111111 !important;
}

/* ═══════════════════════════════════════════════════════════════════════════
   ВКЛАДКИ (tabs)
═══════════════════════════════════════════════════════════════════════════ */
[data-testid="stTabs"] [role="tab"]                { color: #b0b0d0 !important; }
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    color: #ffffff !important;
    border-bottom-color: #7c6af7 !important;
}

/* ═══════════════════════════════════════════════════════════════════════════
   КНОПКИ: разные режимы без принудительного белого на светлом фоне
═══════════════════════════════════════════════════════════════════════════ */
.stButton > button {
    border-radius: 6px !important;
    font-weight: 600 !important;
    color: #ffffff !important;          /* по умолчанию белый */
}
/* primary — фиолетовый фон → белый текст */
.stButton > button[kind="primary"] {
    background: #7c6af7 !important;
    color: #ffffff !important;
    border: none !important;
}
/* secondary — тёмный фон → белый текст */
.stButton > button[kind="secondary"],
.stButton > button:not([kind]) {
    background: #252840 !important;
    color: #e0e0f5 !important;
    border: 1px solid #3a3d5c !important;
}
.stDownloadButton > button {
    background: #252840 !important;
    color: #e0e0f5 !important;
    border: 1px solid #3a3d5c !important;
    border-radius: 6px !important;
    font-weight: 600 !important;
}

/* ═══════════════════════════════════════════════════════════════════════════
   МЕТРИКИ
═══════════════════════════════════════════════════════════════════════════ */
[data-testid="metric-container"] {
    background: #1e2130 !important;
    border: 1px solid #2e3150;
    border-radius: 10px;
    padding: 12px 16px;
}
[data-testid="metric-container"] label    { color: #9090bb !important; }
[data-testid="stMetricValue"]             { color: #7c6af7 !important; font-size: 2rem !important; }
[data-testid="stMetricDelta"]             { color: #43c59e !important; }

/* ═══════════════════════════════════════════════════════════════════════════
   ТАБЛИЦЫ DATAFRAME
═══════════════════════════════════════════════════════════════════════════ */
.stDataFrame                { border-radius: 8px; }
[data-testid="stDataFrame"] th,
.dvn-scroller th            { color: #56cfe1 !important; background: #1e2130 !important; }
[data-testid="stDataFrame"] td,
.dvn-scroller td            { color: #e8e8f8 !important; background: #141624 !important; }

/* ═══════════════════════════════════════════════════════════════════════════
   EXPANDER
═══════════════════════════════════════════════════════════════════════════ */
[data-testid="stExpander"] {
    background: #1a1d2e !important;
    border: 1px solid #2e3150 !important;
    border-radius: 8px;
}
[data-testid="stExpander"] summary span { color: #c8c8e8 !important; }

/* ═══════════════════════════════════════════════════════════════════════════
   INFO / WARNING / ERROR / SUCCESS
═══════════════════════════════════════════════════════════════════════════ */
[data-testid="stAlert"] p,
[data-testid="stAlert"] span { color: #ffffff !important; }

/* ═══════════════════════════════════════════════════════════════════════════
   RADIO
═══════════════════════════════════════════════════════════════════════════ */
[data-testid="stRadio"] > label                  { color: #e0e0f5 !important; }
[data-testid="stRadio"] [role="radiogroup"] label { color: #e0e0f5 !important; }

/* ═══════════════════════════════════════════════════════════════════════════
   CHECKBOX
═══════════════════════════════════════════════════════════════════════════ */
[data-testid="stCheckbox"] label span { color: #e0e0f5 !important; }

/* ═══════════════════════════════════════════════════════════════════════════
   DIVIDER / SCROLLBAR / CODE
═══════════════════════════════════════════════════════════════════════════ */
hr                     { border-color: #2e3150 !important; }
::-webkit-scrollbar             { width: 6px; height: 6px; }
::-webkit-scrollbar-track       { background: #1a1d27; }
::-webkit-scrollbar-thumb       { background: #3a3d5c; border-radius: 3px; }
code, pre              { color: #a8e6cf !important; background: #1a1d2e !important; }

/* ═══════════════════════════════════════════════════════════════════════════
   БЕЙДЖИ И КАРТОЧКИ
═══════════════════════════════════════════════════════════════════════════ */
.badge-busy  { background:#f94144; color:#fff; padding:3px 10px;
               border-radius:12px; font-size:12px; font-weight:600; }
.badge-free  { background:#43c59e; color:#000; padding:3px 10px;
               border-radius:12px; font-size:12px; font-weight:600; }
.badge-setup { background:#f9c74f; color:#000; padding:3px 10px;
               border-radius:12px; font-size:12px; font-weight:600; }
.badge-idle  { background:#6c6c8a; color:#fff; padding:3px 10px;
               border-radius:12px; font-size:12px; font-weight:600; }
.badge-repair{ background:#ff8c42; color:#fff; padding:3px 10px;
               border-radius:12px; font-size:12px; font-weight:600; }
.info-card {
    background: #1e2130; border: 1px solid #2e3150;
    border-radius: 10px; padding: 16px; margin-bottom: 12px;
}
.section-title { color: #56cfe1 !important; font-size: 1.1rem;
                 font-weight: 700; margin-bottom: 8px; }
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════
#  DATABASE
# ═══════════════════════════════════════════════════════════════════════════

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS machines (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            model       TEXT    DEFAULT '',
            productivity REAL   DEFAULT 10.0,
            status      TEXT    DEFAULT 'free',
            notes       TEXT    DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS operators (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            rank TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS production (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            date         TEXT    NOT NULL,
            machine_id   INTEGER NOT NULL,
            operator_id  INTEGER,
            batch        TEXT    DEFAULT '',
            batch_number TEXT    DEFAULT '',
            setup_time   REAL    DEFAULT 0.0,
            produced_qty INTEGER DEFAULT 0,
            actual_time  REAL    DEFAULT 0.0,
            notes        TEXT    DEFAULT '',
            FOREIGN KEY (machine_id)  REFERENCES machines(id),
            FOREIGN KEY (operator_id) REFERENCES operators(id)
        );
    """)

    # ── Миграции: добавляем новые колонки/таблицы в существующую БД без удаления данных ─
    # actual_duration_minutes — фактическое время выпуска, введённое оператором вручную
    existing_cols = [row[1] for row in
                     c.execute("PRAGMA table_info(production)").fetchall()]
    if "actual_duration_minutes" not in existing_cols:
        c.execute("ALTER TABLE production ADD COLUMN actual_duration_minutes REAL DEFAULT NULL")
    # record_type — тип записи: 'production' (выпуск) или 'repair' (ремонт)
    if "record_type" not in existing_cols:
        c.execute("ALTER TABLE production ADD COLUMN record_type TEXT DEFAULT 'production'")
    # repair_duration_hours — длительность ремонта в часах (только для record_type='repair')
    if "repair_duration_hours" not in existing_cols:
        c.execute("ALTER TABLE production ADD COLUMN repair_duration_hours REAL DEFAULT NULL")
    # is_final_release — финальный выпуск (готовое изделие): 1 = да, 0 = нет
    if "is_final_release" not in existing_cols:
        c.execute("ALTER TABLE production ADD COLUMN is_final_release INTEGER DEFAULT 0")

    # ── Миграция таблицы machines ──────────────────────────────────────
    # is_work_center — признак «Рабочий центр» (например, ОПТА); обычные станки = 0
    existing_m_cols = [row[1] for row in
                       c.execute("PRAGMA table_info(machines)").fetchall()]
    if "is_work_center" not in existing_m_cols:
        c.execute("ALTER TABLE machines ADD COLUMN is_work_center INTEGER DEFAULT 0")

    # ── Миграция production: добавить поле этапа ──────────────────────
    # stage_name — название этапа/операции (например «1 установ», «маркировка»)
    if "stage_name" not in existing_cols:
        c.execute("ALTER TABLE production ADD COLUMN stage_name TEXT DEFAULT NULL")

    # ── Таблица партий (batches) ──────────────────────────────────────
    # Полноценная управляемая сущность партий.
    # batch_number — уникальный номер партии (строка, неизменяем при наличии выпуска)
    # batch_name   — наименование детали / партии
    # total_qty    — плановое общее количество деталей в партии
    # notes        — примечание к партии
    # created_at   — дата/время создания записи
    c.execute("""
        CREATE TABLE IF NOT EXISTS batches (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_number TEXT UNIQUE NOT NULL,
            batch_name   TEXT DEFAULT '',
            total_qty    INTEGER NOT NULL DEFAULT 0,
            notes        TEXT DEFAULT '',
            created_at   TEXT NOT NULL
        )
    """)
    # ── Миграция: переносим данные из batch_master → batches (если batch_master существует) ──
    bm_exists = c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='batch_master'"
    ).fetchone()
    if bm_exists:
        old_rows = c.execute("SELECT * FROM batch_master").fetchall()
        for row in old_rows:
            try:
                c.execute("""
                    INSERT OR IGNORE INTO batches (batch_number, batch_name, total_qty, created_at)
                    VALUES (?, ?, ?, ?)
                """, (row["batch_number"], row["part_name"] or "", row["total_qty"], row["created_at"]))
            except Exception:
                pass
        c.execute("DROP TABLE IF EXISTS batch_master")
    # ── Миграция: добавляем недостающие колонки в batches ─────────────
    batches_cols = [row[1] for row in c.execute("PRAGMA table_info(batches)").fetchall()]
    if "notes" not in batches_cols:
        c.execute("ALTER TABLE batches ADD COLUMN notes TEXT DEFAULT ''")
    if "batch_name" not in batches_cols:
        c.execute("ALTER TABLE batches ADD COLUMN batch_name TEXT DEFAULT ''")
    # ── Перенос партий из production в batches (для записей без явной партии в batches) ─
    orphan_batches = c.execute("""
        SELECT DISTINCT p.batch_number, p.batch
        FROM production p
        WHERE p.batch_number IS NOT NULL AND p.batch_number != ''
          AND NOT EXISTS (SELECT 1 FROM batches b WHERE b.batch_number = p.batch_number)
    """).fetchall()
    for ob in orphan_batches:
        try:
            c.execute("""
                INSERT OR IGNORE INTO batches (batch_number, batch_name, total_qty, created_at)
                VALUES (?, ?, 0, ?)
            """, (ob["batch_number"], ob["batch"] or "", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        except Exception:
            pass

    # Журнал смены статусов станков
    c.execute("""
        CREATE TABLE IF NOT EXISTS machine_status_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_id  INTEGER NOT NULL,
            status      TEXT    NOT NULL,
            changed_by  TEXT    DEFAULT '',
            changed_at  TEXT    NOT NULL,
            FOREIGN KEY (machine_id) REFERENCES machines(id)
        )
    """)

    # ── Начальные данные: только при самом первом запуске (таблицы только что созданы).
    # После явного удаления пользователем через UI реестры остаются пустыми — не пересоздаём.
    # Маркер первого запуска — таблица db_meta с флагом seeded.
    c.execute("""
        CREATE TABLE IF NOT EXISTS db_meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    already_seeded = c.execute(
        "SELECT value FROM db_meta WHERE key='seeded'"
    ).fetchone()

    if not already_seeded:
        # Станки (6 шт.)
        machines_data = [
            ("Токарный ЧПУ №1",           "16К20",       12.0, "busy",  ""),
            ("Токарный ЧПУ №2",           "16К20",       10.0, "free",  ""),
            ("Токарный универсальный №3",  "1К62",         8.0, "setup", "Замена инструмента"),
            ("Токарный ЧПУ №4",           "HAAS ST-20",  15.0, "idle",  "Плановое ТО"),
            ("Токарный ЧПУ №5",           "HAAS ST-20",  15.0, "busy",  ""),
            ("Токарный прецизионный №6",   "Mori Seiki",  18.0, "free",  ""),
        ]
        c.executemany(
            "INSERT INTO machines (name, model, productivity, status, notes) VALUES (?,?,?,?,?)",
            machines_data
        )

        # Операторы (5 чел.)
        operators_data = [
            ("Петров Иван Алексеевич",    "5-й разряд"),
            ("Сидоров Василий Петрович",  "4-й разряд"),
            ("Козлов Дмитрий Михайлович", "5-й разряд"),
            ("Иванов Андрей Андреевич",   "3-й разряд"),
            ("Новиков Сергей Викторович", "6-й разряд"),
        ]
        c.executemany(
            "INSERT INTO operators (name, rank) VALUES (?,?)",
            operators_data
        )

        # Демо-история за 10 дней (только при первом старте)
        import random
        random.seed(42)
        machines_rows = c.execute("SELECT id, productivity FROM machines").fetchall()
        operators_rows = c.execute("SELECT id FROM operators").fetchall()
        for delta in range(10, 0, -1):
            d = (date.today() - timedelta(days=delta)).isoformat()
            for m in machines_rows:
                if random.random() < 0.75:
                    op = random.choice(operators_rows)
                    qty = random.randint(int(m["productivity"] * 4),
                                        int(m["productivity"] * 9))
                    at  = round(qty / m["productivity"], 2)
                    c.execute("""
                        INSERT INTO production
                        (date, machine_id, operator_id, batch, batch_number,
                         setup_time, produced_qty, actual_time)
                        VALUES (?,?,?,?,?,?,?,?)
                    """, (d, m["id"], op["id"],
                          random.choice(["Вал ступенчатый", "Фланец опорный",
                                         "Шестерня привода", "Втулка направляющая",
                                         "Корпус подшипника"]),
                          f"П-{delta:03d}-{m['id']}",
                          round(random.uniform(0.25, 1.5), 2),
                          qty, at))

        # Ставим флаг — больше не инициализируем
        c.execute("INSERT INTO db_meta (key, value) VALUES ('seeded', '1')")

    conn.commit()
    conn.close()

# ═══════════════════════════════════════════════════════════════════════════
#  CONFIG & AUTH
# ═══════════════════════════════════════════════════════════════════════════

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def get_role(username: str) -> str:
    """Возвращает роль текущего пользователя из config.yml"""
    try:
        cfg = load_config()
        return cfg["credentials"]["usernames"].get(username, {}).get("role", "user")
    except Exception:
        return "user"

def require_admin():
    """Останавливает выполнение, если роль не admin."""
    if st.session_state.get("role") != "admin":
        st.error("⛔ Доступ запрещён. Требуются права администратора.")
        st.stop()

def require_not_viewer():
    """Останавливает выполнение, если роль viewer — запрет любых изменений данных."""
    if st.session_state.get("role") == "viewer":
        st.error("⛔ Недостаточно прав для изменения данных. "
                 "Роль «Наблюдатель» предназначена только для просмотра.")
        st.stop()

# ═══════════════════════════════════════════════════════════════════════════
#  DATA HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def q(sql, params=(), fetch="all"):
    conn = get_conn()
    c = conn.cursor()
    c.execute(sql, params)
    if fetch == "all":
        result = [dict(r) for r in c.fetchall()]
    elif fetch == "one":
        row = c.fetchone()
        result = dict(row) if row else None
    else:
        result = None
    conn.commit()
    conn.close()
    return result

def exec_sql(sql, params=()):
    conn = get_conn()
    c = conn.cursor()
    c.execute(sql, params)
    lid = c.lastrowid
    conn.commit()
    conn.close()
    return lid

# ── Хелперы партий ─────────────────────────────────────────────────────────

def get_batch(batch_number: str):
    """Возвращает запись batches по номеру партии или None."""
    if not batch_number or not batch_number.strip():
        return None
    return q("SELECT * FROM batches WHERE batch_number=?",
             (batch_number.strip(),), fetch="one")

def create_batch(batch_number: str, batch_name: str, total_qty: int, notes: str = ""):
    """Создаёт новую партию. Возвращает True при успехе, False если дублируется номер."""
    if get_batch(batch_number):
        return False
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    exec_sql("""
        INSERT OR IGNORE INTO batches (batch_number, batch_name, total_qty, notes, created_at)
        VALUES (?,?,?,?,?)
    """, (batch_number.strip(), batch_name.strip(), int(total_qty), notes.strip(), now_str))
    return True

def update_batch(batch_id: int, batch_name: str, total_qty: int, notes: str):
    """Обновляет название, количество и примечание партии. Номер не меняется."""
    exec_sql("""
        UPDATE batches SET batch_name=?, total_qty=?, notes=? WHERE id=?
    """, (batch_name.strip(), int(total_qty), notes.strip(), batch_id))

def delete_batch_safe(batch_number: str):
    """
    Удаляет партию, если по ней нет записей выпуска.
    Возвращает (True, '') при успехе или (False, причина) при ошибке.
    """
    cnt = q("SELECT COUNT(*) AS c FROM production WHERE batch_number=?",
            (batch_number,), fetch="one")
    if cnt and cnt["c"] > 0:
        return False, f"Нельзя удалить партию: по ней существует {cnt['c']} записей выпуска."
    exec_sql("DELETE FROM batches WHERE batch_number=?", (batch_number,))
    return True, ""

def all_batch_numbers():
    """Возвращает все номера партий из таблицы batches, отсортированные."""
    rows = q("SELECT batch_number FROM batches ORDER BY batch_number")
    return [r["batch_number"] for r in rows]

def all_batches():
    """Возвращает все партии с краткой статистикой выпуска."""
    return q("""
        SELECT b.id, b.batch_number, b.batch_name, b.total_qty, b.notes, b.created_at,
               COALESCE(SUM(CASE WHEN p.is_final_release=1 AND COALESCE(m.is_work_center,0)=0
                                 THEN p.produced_qty ELSE 0 END), 0) AS final_lathe,
               COALESCE(SUM(CASE WHEN p.is_final_release=1 AND COALESCE(m.is_work_center,0)=1
                                 THEN p.produced_qty ELSE 0 END), 0) AS final_opta,
               COUNT(p.id) AS record_count
        FROM batches b
        LEFT JOIN production p ON p.batch_number = b.batch_number
                               AND COALESCE(p.record_type,'production') = 'production'
        LEFT JOIN machines m ON m.id = p.machine_id
        GROUP BY b.id, b.batch_number, b.batch_name, b.total_qty, b.notes, b.created_at
        ORDER BY b.created_at DESC
    """)

STATUS_LABELS = {
    "busy":     "🔴 Занят",
    "free":     "🟢 Свободен",
    "setup":    "🟡 Наладка",
    "idle":     "⚫ Простой",
    "waiting":  "🔵 Ожидание материала",
    "repair":   "🟠 Ремонт / ТО",
    "break":    "⬜ Перерыв",
}
STATUS_COLORS = {
    "busy":    "#f94144",
    "free":    "#43c59e",
    "setup":   "#f9c74f",
    "idle":    "#6c6c8a",
    "waiting": "#56cfe1",
    "repair":  "#ff8c42",
    "break":   "#aaaacc",
}
# Полный упорядоченный список — пополняйте здесь при необходимости
MACHINE_STATUSES = list(STATUS_LABELS.keys())

# ═══════════════════════════════════════════════════════════════════════════
#  СТРАНИЦЫ
# ═══════════════════════════════════════════════════════════════════════════

def page_machines(role):
    st.title("⚙️ Станки и рабочие центры — текущее состояние")

    machines = q("""
        SELECT m.id, m.name, m.model, m.productivity, m.status, m.notes,
               COALESCE(m.is_work_center, 0) AS is_work_center
        FROM machines m ORDER BY m.id
    """)

    if not machines:
        st.warning("Станки не найдены.")
        return

    # ── Статистика ─────────────────────────────────────────────────────
    counts = {s: 0 for s in STATUS_LABELS}
    for m in machines:
        counts[m["status"]] = counts.get(m["status"], 0) + 1

    stat_cols = st.columns(len(STATUS_LABELS))
    for col, (sk, slabel) in zip(stat_cols, STATUS_LABELS.items()):
        col.metric(slabel, counts.get(sk, 0))

    st.divider()

    # ── Таблица станков ────────────────────────────────────────────────
    operators = q("SELECT id, name FROM operators ORDER BY name")
    op_map    = {0: "—"} | {o["id"]: o["name"] for o in operators}

    last_prod = q("""
        SELECT p.machine_id,
               p.batch, p.batch_number,
               o.name AS operator,
               p.setup_time,
               p.produced_qty,
               p.date
        FROM production p
        LEFT JOIN operators o ON o.id = p.operator_id
        WHERE p.id IN (
            SELECT MAX(id) FROM production GROUP BY machine_id
        )
    """)
    last_map = {r["machine_id"]: r for r in last_prod}

    df_rows = []
    for m in machines:
        lp = last_map.get(m["id"], {})
        df_rows.append({
            "ID":            m["id"],
            "Станок / РЦ":   m["name"],
            "Тип":           "🏭 Рабочий центр" if m["is_work_center"] else "⚙️ Станок",
            "Модель":        m["model"],
            "Статус":        STATUS_LABELS.get(m["status"], m["status"]),
            "Партия":        lp.get("batch", "—"),
            "№ партии":      lp.get("batch_number", "—"),
            "Оператор":      lp.get("operator", "—"),
            "Наладка (ч)":   lp.get("setup_time", "—"),
            "Произв.д/ч":    m["productivity"],
            "Посл. дата":    lp.get("date", "—"),
            "Примечание":    m["notes"],
        })

    df = pd.DataFrame(df_rows)
    st.dataframe(df, use_container_width=True, hide_index=True,
                 column_config={
                     "Тип":         st.column_config.TextColumn(width="small"),
                     "Статус":      st.column_config.TextColumn(width="small"),
                     "Произв.д/ч":  st.column_config.NumberColumn(format="%.1f"),
                 })

    st.divider()

    # ── Смена статуса (доступна user и admin, не viewer) ───────────────
    if st.session_state.get("role") == "viewer":
        st.info("👁 Режим просмотра — изменение статусов недоступно.")
    else:
        st.markdown("### 🔄 Изменить статус станка")
        with st.form("status_form", clear_on_submit=True):
            sc1, sc2, sc3 = st.columns([3, 2, 2])
            ch_machine = sc1.selectbox("Станок",
                options=[m["id"] for m in machines],
                format_func=lambda x: next(m["name"] for m in machines if m["id"] == x))
            ch_status  = sc2.selectbox("Новый статус",
                options=MACHINE_STATUSES,
                format_func=lambda x: STATUS_LABELS.get(x, x))
            ch_notes   = sc3.text_input("Примечание")
            if st.form_submit_button("Обновить статус", use_container_width=True):
                require_not_viewer()
                now_str  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                username = st.session_state.get("username", "")
                exec_sql("UPDATE machines SET status=?, notes=? WHERE id=?",
                         (ch_status, ch_notes, ch_machine))
                exec_sql("""
                    INSERT INTO machine_status_log (machine_id, status, changed_by, changed_at)
                    VALUES (?,?,?,?)
                """, (ch_machine, ch_status, username, now_str))
                st.success(f"✅ Статус обновлён на «{STATUS_LABELS.get(ch_status, ch_status)}»")
                st.rerun()

    st.divider()

    # ── Внести запись (Выпуск или Ремонт) — User + Admin ──────────────
    if st.session_state.get("role") == "viewer":
        st.info("👁 Режим просмотра — внесение записей недоступно.")
        return

    st.markdown("### ➕ Внести запись")

    # Тип записи выбирается ВНЕ формы, чтобы динамически менять поля
    rec_type = st.radio(
        "Тип записи",
        options=["production", "repair"],
        format_func=lambda x: "🟢 Выпуск / Установ" if x == "production" else "🔧 Ремонт",
        horizontal=True,
        key="rec_type_radio",
    )

    # Машины с признаком is_work_center
    machines_full = q("""
        SELECT id, name, COALESCE(is_work_center,0) AS is_work_center
        FROM machines ORDER BY is_work_center, name
    """)
    wc_ids = {m["id"] for m in machines_full if m["is_work_center"]}

    def machine_label(mid):
        m = next((x for x in machines_full if x["id"] == mid), None)
        if not m:
            return str(mid)
        prefix = "🏭" if m["is_work_center"] else "⚙️"
        return f"{prefix} {m['name']}"

    if rec_type == "production":
        # ── Выбор / поиск партии (вне формы — для реактивного отображения) ──
        st.markdown("##### 📦 Партия")
        all_bns = all_batch_numbers()

        bc1, bc2 = st.columns([2, 4])
        # Выбор существующей партии ИЛИ ввод нового номера
        if all_bns:
            batch_no_input = bc1.selectbox(
                "№ партии",
                options=[""] + all_bns,
                format_func=lambda x: "— выберите или введите —" if x == "" else x,
                key="prod_batch_no_sel",
            )
            # Возможность набрать вручную (не из списка)
            batch_no_manual = bc1.text_input(
                "...или введите новый №",
                key="prod_batch_no_manual",
                placeholder="Новый номер партии",
            )
            batch_no_stripped = (batch_no_manual.strip()
                                 if batch_no_manual.strip()
                                 else batch_no_input.strip())
        else:
            batch_no_stripped = bc1.text_input(
                "№ партии",
                key="prod_batch_no",
                placeholder="Введите номер партии",
            ).strip()

        bm_record  = get_batch(batch_no_stripped) if batch_no_stripped else None
        is_new_batch = (batch_no_stripped != "") and (bm_record is None)

        if not batch_no_stripped:
            bc2.info("Введите или выберите № партии")
        elif bm_record:
            bc2.success(
                f"✅ **{bm_record['batch_number']}** | {bm_record['batch_name'] or '—'} "
                f"| Всего: **{bm_record['total_qty']:,} шт**"
                + (f" | 📝 {bm_record['notes']}" if bm_record['notes'] else "")
            )
        else:
            bc2.warning(
                "🆕 Партия не найдена. Создайте партию заранее на странице «📋 Партии» "
                "или введите данные новой партии ниже."
            )

        # Мини-форма создания новой партии прямо на месте
        new_batch_total_qty = 0
        new_batch_name_val  = ""
        new_batch_notes_val = ""
        if is_new_batch:
            with st.expander("➕ Создать новую партию", expanded=True):
                nb1, nb2, nb3 = st.columns([3, 2, 3])
                new_batch_name_val  = nb1.text_input("Название партии*", key="new_batch_pname")
                new_batch_total_qty = nb2.number_input(
                    "Всего в партии (шт)*", min_value=1, step=1, key="new_batch_total")
                new_batch_notes_val = nb3.text_input("Примечание", key="new_batch_notes")

        st.markdown("---")

        # Определяем тип выбранного станка ДО формы — нужно для условного отображения этапа
        # (selectbox внутри формы ещё не выбран, поэтому берём первый станок как default)
        first_machine_id = machines_full[0]["id"] if machines_full else None
        # Используем session_state key если уже был выбор, иначе — первый
        _sel_m_id_key  = st.session_state.get("_prod_machine_sel", first_machine_id)
        _sel_m_preview = next((m for m in machines_full if m["id"] == _sel_m_id_key), None)
        _preview_is_wc = _sel_m_preview["is_work_center"] if _sel_m_preview else False

        with st.form("production_form", clear_on_submit=True):
            r1c1, r1c2, r1c3, r1c4 = st.columns([3, 3, 2, 2])
            sel_machine  = r1c1.selectbox("Станок / РЦ*",
                options=[m["id"] for m in machines_full],
                format_func=machine_label,
                key="_prod_machine_sel")
            sel_operator = r1c2.selectbox("Оператор",
                options=[0] + [o["id"] for o in operators],
                format_func=lambda x: op_map[x])
            prod_date    = r1c3.date_input("Дата*", value=date.today())
            produced_qty = r1c4.number_input("Выпущено (шт)", min_value=0, step=1,
                                              help="0 = наладка без выпуска / тестовый прогон")

            r2c1, r2c2 = st.columns([2, 3])
            setup_time     = r2c1.number_input("Наладка (ч)", min_value=0.0, step=0.25)
            actual_dur_min = r2c2.number_input(
                "Факт. время выпуска (мин)",
                min_value=0.0, step=1.0, value=0.0,
                help="Реально потраченное время в минутах. 0 — не заполнено.")

            # ── Логика поля «Этап» ─────────────────────────────────────
            # Для ОПТА: этап = название рабочего центра (авто, поле скрыто)
            # Для станка: этап обязателен, ввод вручную
            sel_m_obj = next((m for m in machines_full if m["id"] == sel_machine), None)
            is_wc_selected = sel_m_obj["is_work_center"] if sel_m_obj else False

            if is_wc_selected:
                # Этап = название РЦ, поле не показываем, но показываем информер
                auto_stage = sel_m_obj["name"] if sel_m_obj else ""
                st.info(f"🏭 Рабочий центр — этап установлен автоматически: **«{auto_stage}»**")
                stage_name = auto_stage
                # Пустой placeholder для выравнивания
                stage_name_manual = ""
            else:
                # Станок — этап вручную (обязателен)
                stage_col, _ = st.columns([3, 4])
                stage_name_manual = stage_col.text_input(
                    "Этап / операция *",
                    placeholder="1 установ, 2 установ…",
                    help="⚠️ Обязательно для обычных станков. Укажите номер установа или операцию.")
                stage_name = stage_name_manual
                auto_stage = ""

            fc1, fc2 = st.columns([5, 2])
            notes_prod = fc1.text_input("Примечание")
            is_final   = fc2.checkbox(
                "✅ Финальный выпуск",
                help="Для станков — финал станочного этапа. "
                     "Для ОПТА — финал всей партии (учитывается в progress bar).")

            if st.form_submit_button("✔ Записать выпуск", type="primary",
                                     use_container_width=True):
                require_not_viewer()

                # ── Валидация партии ──────────────────────────────────
                if not batch_no_stripped:
                    st.error("Укажите № партии.")
                    st.stop()

                if is_new_batch:
                    if new_batch_total_qty < 1:
                        st.error("Для новой партии укажите общее количество (≥ 1 шт).")
                        st.stop()
                    if not new_batch_name_val.strip():
                        st.error("Укажите название для новой партии.")
                        st.stop()
                    ok = create_batch(batch_no_stripped, new_batch_name_val,
                                      new_batch_total_qty, new_batch_notes_val)
                    if not ok:
                        st.error(f"Партия «{batch_no_stripped}» уже существует.")
                        st.stop()
                    used_batch_name = new_batch_name_val
                else:
                    used_batch_name = bm_record["batch_name"] if bm_record else ""

                # ── Валидация этапа для станков ────────────────────────
                sel_m_obj2 = next((m for m in machines_full if m["id"] == sel_machine), None)
                is_wc2 = sel_m_obj2["is_work_center"] if sel_m_obj2 else False
                if not is_wc2 and not stage_name_manual.strip():
                    st.error("Укажите этап / операцию для обычного станка.")
                    st.stop()
                final_stage = sel_m_obj2["name"] if is_wc2 else stage_name_manual.strip()

                sel_m_prod = next(m for m in machines if m["id"] == sel_machine)
                plan_h = round(produced_qty / sel_m_prod["productivity"], 3) \
                         if produced_qty > 0 else 0.0
                fact_min = float(actual_dur_min) if actual_dur_min > 0 else None
                exec_sql("""
                    INSERT INTO production
                    (date, machine_id, operator_id, batch, batch_number,
                     setup_time, produced_qty, actual_time,
                     actual_duration_minutes, record_type, is_final_release,
                     stage_name, notes)
                    VALUES (?,?,?,?,?,?,?,?,?,'production',?,?,?)
                """, (prod_date.isoformat(), sel_machine,
                      sel_operator if sel_operator else None,
                      used_batch_name, batch_no_stripped,
                      setup_time, produced_qty, plan_h, fact_min,
                      1 if is_final else 0,
                      final_stage or None,
                      notes_prod))

                stage_lbl = f" | этап «{final_stage}»" if final_stage else ""
                if produced_qty == 0:
                    msg = f"✅ Установ записан: 0 шт (наладка / прогон){stage_lbl}"
                elif is_wc2:
                    msg = f"✅ Выпуск ОПТА: {produced_qty} шт{stage_lbl}"
                    if is_final:
                        msg += " | 🏁 Финальный выпуск ОПТА"
                else:
                    msg = f"✅ Выпуск: {produced_qty} шт | план {plan_h:.2f} ч{stage_lbl}"
                    if is_final:
                        msg += " | 🏁 Финальный выпуск (станок)"
                    if fact_min:
                        msg += f" | факт {fact_min:.0f} мин"
                st.success(msg)
                st.rerun()

    else:  # repair
        with st.form("repair_form", clear_on_submit=True):
            rr1, rr2, rr3 = st.columns([3, 3, 2])
            sel_machine_r  = rr1.selectbox("Станок / РЦ*",
                options=[m["id"] for m in machines_full],
                format_func=machine_label,
                key="repair_machine")
            sel_operator_r = rr2.selectbox("Ответственный",
                options=[0] + [o["id"] for o in operators],
                format_func=lambda x: op_map[x],
                key="repair_operator")
            repair_date    = rr3.date_input("Дата*", value=date.today(), key="repair_date")

            rd1, rd2 = st.columns([2, 5])
            repair_hours = rd1.number_input(
                "Длительность ремонта (ч)*",
                min_value=0.0, step=0.5, value=1.0,
                help="Введите фактическую длительность ремонта в часах (например 1.5 = 1ч 30мин)")
            repair_notes = rd2.text_input(
                "Причина / комментарий*",
                placeholder="Замена подшипника, выход из строя шпинделя…")

            if st.form_submit_button("🔧 Записать ремонт", type="primary",
                                     use_container_width=True):
                require_not_viewer()
                if repair_hours <= 0:
                    st.error("Укажите длительность ремонта.")
                elif not repair_notes.strip():
                    st.error("Укажите причину ремонта.")
                else:
                    exec_sql("""
                        INSERT INTO production
                        (date, machine_id, operator_id,
                         batch, batch_number, setup_time,
                         produced_qty, actual_time,
                         repair_duration_hours, record_type, notes)
                        VALUES (?,?,?,
                                '','',0,
                                0,0,
                                ?,'repair',?)
                    """, (repair_date.isoformat(), sel_machine_r,
                          sel_operator_r if sel_operator_r else None,
                          float(repair_hours), repair_notes.strip()))
                    st.success(f"🔧 Ремонт записан: {repair_hours:.1f} ч — {repair_notes}")
                    st.rerun()


def page_history(role):
    st.title("📋 История выпуска и ремонтов")

    # Массовое удаление всей истории ОТКЛЮЧЕНО намеренно.
    # Удаление отдельных записей по ID доступно только администратору (форма ниже).

    # ── Фильтры ────────────────────────────────────────────────────────
    with st.expander("🔍 Фильтры", expanded=True):
        fc1, fc2, fc3, fc4, fc5 = st.columns(5)
        machines  = q("SELECT id, name FROM machines ORDER BY name")
        operators = q("SELECT id, name FROM operators ORDER BY name")
        date_from = fc1.date_input("Дата от", value=date.today() - timedelta(days=14))
        date_to   = fc2.date_input("Дата до", value=date.today())
        sel_m_f   = fc3.selectbox("Станок",
            options=[0] + [m["id"] for m in machines],
            format_func=lambda x: "Все" if x == 0
                else next(m["name"] for m in machines if m["id"] == x))
        sel_o_f   = fc4.selectbox("Оператор",
            options=[0] + [o["id"] for o in operators],
            format_func=lambda x: "Все" if x == 0
                else next(o["name"] for o in operators if o["id"] == x))
        sel_type  = fc5.selectbox("Тип записи",
            options=["all", "production", "repair"],
            format_func=lambda x: {"all": "Все", "production": "🟢 Выпуск",
                                    "repair": "🔧 Ремонт"}[x])

    sql = """
        SELECT p.id,
               COALESCE(p.record_type, 'production') AS record_type,
               p.date,
               m.name  AS machine,
               COALESCE(m.is_work_center, 0)         AS is_work_center,
               o.name  AS operator,
               p.batch, p.batch_number,
               p.setup_time,
               p.produced_qty,
               p.actual_time,
               p.actual_duration_minutes,
               p.repair_duration_hours,
               COALESCE(p.is_final_release, 0)       AS is_final_release,
               p.stage_name,
               p.notes
        FROM production p
        LEFT JOIN machines  m ON m.id = p.machine_id
        LEFT JOIN operators o ON o.id = p.operator_id
        WHERE p.date BETWEEN ? AND ?
    """
    params = [date_from.isoformat(), date_to.isoformat()]
    if sel_m_f:
        sql += " AND p.machine_id = ?"
        params.append(sel_m_f)
    if sel_o_f:
        sql += " AND p.operator_id = ?"
        params.append(sel_o_f)
    if sel_type != "all":
        sql += " AND COALESCE(p.record_type,'production') = ?"
        params.append(sel_type)
    sql += " ORDER BY p.date DESC, p.id DESC"

    rows = q(sql, params)

    # ── Нулевое состояние ─────────────────────────────────────────────
    if not rows:
        any_records = q("SELECT COUNT(*) AS cnt FROM production", fetch="one")
        if any_records and any_records["cnt"] == 0:
            st.info("📭 Записей пока нет. Используйте форму «Внести запись» на странице «Станки».")
        else:
            st.info("Нет записей, соответствующих выбранным фильтрам.")
        return

    df = pd.DataFrame(rows)
    df["record_type"]      = df["record_type"].fillna("production")
    df["is_final_release"] = df["is_final_release"].fillna(0).astype(int)
    df["is_work_center"]   = df["is_work_center"].fillna(0).astype(int)

    # ── Разбивка данных ────────────────────────────────────────────────
    df_prod   = df[df["record_type"] == "production"]
    df_repair = df[df["record_type"] == "repair"]
    # Обычные станки
    df_lathes = df_prod[df_prod["is_work_center"] == 0]
    # Рабочие центры (ОПТА)
    df_wc     = df_prod[df_prod["is_work_center"] == 1]

    total_repair_h = df_repair["repair_duration_hours"].fillna(0).sum()
    installs_qty   = df_lathes["produced_qty"].sum()
    final_qty      = df_lathes[df_lathes["is_final_release"] == 1]["produced_qty"].sum()
    opta_qty       = df_wc["produced_qty"].sum()
    opta_final_qty = df_wc[df_wc["is_final_release"] == 1]["produced_qty"].sum()

    # ── Метрики ────────────────────────────────────────────────────────
    st.markdown("**⚙️ Станки**")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Записей выпуска",      len(df_lathes))
    m2.metric("Установов (шт)",       f"{int(installs_qty):,}")
    m3.metric("🏁 Финальный выпуск",  f"{int(final_qty):,}",
              help="Шт по записям «Финальный выпуск» для обычных станков")
    m4.metric("Ремонтов",             len(df_repair))
    m5.metric("Ремонт (ч)",           f"{total_repair_h:.1f}")

    st.markdown("**🏭 Рабочие центры (ОПТА)**")
    o1, o2, o3, _ = st.columns(4)
    o1.metric("Записей ОПТА",         len(df_wc))
    o2.metric("Выпуск ОПТА (шт)",     f"{int(opta_qty):,}")
    o3.metric("🏁 Финальный ОПТА",    f"{int(opta_final_qty):,}",
              help="Шт по записям «Финальный выпуск» для рабочих центров")

    st.divider()

    # ── Формируем отображаемый DataFrame ─────────────────────────────
    display_rows = []
    for _, r in df.iterrows():
        wc_tag = " 🏭" if r["is_work_center"] else ""
        if r["record_type"] == "repair":
            display_rows.append({
                "ID":              r["id"],
                "Тип":             "🔧 Ремонт",
                "Объект":          (r["machine"] or "—") + wc_tag,
                "Фин. выпуск":     "—",
                "Этап":            "—",
                "Дата":            r["date"],
                "Оператор":        r["operator"] or "—",
                "Партия":          "—",
                "№ партии":        "—",
                "Наладка (ч)":     None,
                "Выпущено":        None,
                "План. время (ч)": None,
                "Факт. мин":       None,
                "Ремонт (ч)":      r["repair_duration_hours"],
                "Δ план/факт":     None,
                "Примечание":      r["notes"] or "",
            })
        else:
            plan_h   = r["actual_time"]
            fact_min = r["actual_duration_minutes"]
            delta    = round(float(fact_min) - float(plan_h) * 60, 1) \
                       if pd.notna(fact_min) and fact_min and float(fact_min) > 0 else None
            tип = "🏭 Выпуск ОПТА" if r["is_work_center"] else "🟢 Выпуск"
            display_rows.append({
                "ID":              r["id"],
                "Тип":             tип,
                "Объект":          (r["machine"] or "—") + wc_tag,
                "Фин. выпуск":     "✅ Да" if r["is_final_release"] else "—",
                "Этап":            r.get("stage_name") or "—",
                "Дата":            r["date"],
                "Оператор":        r["operator"] or "—",
                "Партия":          r["batch"] or "—",
                "№ партии":        r["batch_number"] or "—",
                "Наладка (ч)":     r["setup_time"],
                "Выпущено":        r["produced_qty"],
                "План. время (ч)": plan_h,
                "Факт. мин":       fact_min,
                "Ремонт (ч)":      None,
                "Δ план/факт":     delta,
                "Примечание":      r["notes"] or "",
            })

    df_show = pd.DataFrame(display_rows)
    base_cols = ["Тип", "Объект", "Фин. выпуск", "Этап", "Дата", "Оператор",
                 "Партия", "№ партии", "Наладка (ч)", "Выпущено",
                 "План. время (ч)", "Факт. мин", "Ремонт (ч)", "Δ план/факт", "Примечание"]
    if role == "admin":
        base_cols = ["ID"] + base_cols
        st.markdown("*Для удаления или редактирования — укажите ID записи в формах ниже*")

    st.dataframe(
        df_show[base_cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            "Тип":             st.column_config.TextColumn(width="small"),
            "Объект":          st.column_config.TextColumn(width="medium"),
            "Фин. выпуск":     st.column_config.TextColumn(
                width="small", help="✅ Да = финальный выпуск готовой детали"),
            "Выпущено":        st.column_config.NumberColumn(format="%d шт"),
            "План. время (ч)": st.column_config.NumberColumn(format="%.2f"),
            "Факт. мин":       st.column_config.NumberColumn(
                format="%.0f мин",
                help="Фактическое время, введённое оператором. Пусто = нет данных."),
            "Ремонт (ч)":      st.column_config.NumberColumn(
                format="%.2f ч",
                help="Длительность ремонта в часах."),
            "Δ план/факт":     st.column_config.NumberColumn(
                format="%.1f мин",
                help="> 0 — перерасход; < 0 — опережение графика."),
        }
    )

    if role == "admin":
        st.divider()
        # ══════════════════════════════════════════════════════════════
        # ФОРМА УДАЛЕНИЯ ЗАПИСИ
        # ══════════════════════════════════════════════════════════════
        with st.expander("🗑 Удалить запись"):
            with st.form("delete_prod", clear_on_submit=True):
                del_id = st.number_input("ID записи для удаления", min_value=1, step=1)
                if st.form_submit_button("🗑 Удалить запись", type="primary"):
                    require_not_viewer()
                    exec_sql("DELETE FROM production WHERE id=?", (del_id,))
                    st.success(f"Запись #{del_id} удалена.")
                    st.rerun()

        # ══════════════════════════════════════════════════════════════
        # ФОРМА РЕДАКТИРОВАНИЯ ЗАПИСИ
        # ══════════════════════════════════════════════════════════════
        st.markdown("---")
        st.markdown("#### ✏️ Редактировать запись")

        # Шаг 1: выбор ID
        edit_id_input = st.number_input("ID записи для редактирования",
                                        min_value=1, step=1, key="edit_id_input")
        if st.button("🔍 Загрузить запись", key="load_edit_btn"):
            rec = q("SELECT * FROM production WHERE id=?", (edit_id_input,), fetch="one")
            if rec is None:
                st.error(f"Запись с ID {edit_id_input} не найдена.")
            else:
                st.session_state["edit_record"]  = dict(rec)
                st.session_state["edit_pending"] = False

        # Шаг 2: показываем форму редактирования
        if "edit_record" in st.session_state and st.session_state["edit_record"]:
            rec = st.session_state["edit_record"]
            st.info(f"Редактируется запись **ID {rec['id']}** "
                    f"| Дата: {rec['date']} "
                    f"| Тип: {rec.get('record_type','production')}")

            all_machines = q("""
                SELECT id, name, COALESCE(is_work_center,0) AS is_work_center
                FROM machines ORDER BY is_work_center, name
            """)
            all_operators = q("SELECT id, name FROM operators ORDER BY name")
            op_map_e = {0: "—"} | {o["id"]: o["name"] for o in all_operators}

            def mach_lbl_e(mid):
                m = next((x for x in all_machines if x["id"] == mid), None)
                if not m: return str(mid)
                return ("🏭 " if m["is_work_center"] else "⚙️ ") + m["name"]

            with st.form("edit_record_form"):
                ec1, ec2, ec3 = st.columns([2, 3, 3])

                # Тип записи
                cur_rtype = rec.get("record_type") or "production"
                e_rtype = ec1.selectbox(
                    "Тип записи",
                    options=["production", "repair"],
                    index=0 if cur_rtype == "production" else 1,
                    format_func=lambda x: "🟢 Выпуск" if x == "production" else "🔧 Ремонт")

                # Машина
                mach_ids = [m["id"] for m in all_machines]
                cur_mid  = rec.get("machine_id") or (mach_ids[0] if mach_ids else 1)
                e_mid = ec2.selectbox(
                    "Станок / РЦ*",
                    options=mach_ids,
                    index=mach_ids.index(cur_mid) if cur_mid in mach_ids else 0,
                    format_func=mach_lbl_e)

                # Оператор
                op_ids  = [0] + [o["id"] for o in all_operators]
                cur_oid = rec.get("operator_id") or 0
                if cur_oid not in op_ids: cur_oid = 0
                e_oid = ec3.selectbox(
                    "Оператор",
                    options=op_ids,
                    index=op_ids.index(cur_oid),
                    format_func=lambda x: op_map_e[x] if x in op_map_e else str(x))

                ec4, ec5, ec6 = st.columns([2, 3, 3])
                try:
                    cur_date = date.fromisoformat(rec["date"])
                except Exception:
                    cur_date = date.today()
                e_date     = ec4.date_input("Дата*", value=cur_date)
                e_batch    = ec5.text_input("Партия",    value=rec.get("batch") or "")
                e_batch_no = ec6.text_input("№ партии",  value=rec.get("batch_number") or "")

                ec7, ec8, ec9, ec10 = st.columns([2, 2, 2, 3])
                e_setup = ec7.number_input(
                    "Наладка (ч)", min_value=0.0, step=0.25,
                    value=float(rec.get("setup_time") or 0.0))
                e_qty   = ec8.number_input(
                    "Выпущено (шт)", min_value=0, step=1,
                    value=int(rec.get("produced_qty") or 0))
                e_fact  = ec9.number_input(
                    "Факт. время (мин)", min_value=0.0, step=1.0,
                    value=float(rec.get("actual_duration_minutes") or 0.0))
                e_repair_h = ec10.number_input(
                    "Длит. ремонта (ч)", min_value=0.0, step=0.5,
                    value=float(rec.get("repair_duration_hours") or 0.0))

                ef1, ef2, ef3 = st.columns([3, 3, 2])
                e_stage  = ef1.text_input("Этап / операция",
                                          value=rec.get("stage_name") or "",
                                          placeholder="1 установ, маркировка…")
                e_notes  = ef2.text_input("Примечание", value=rec.get("notes") or "")
                e_final  = ef3.checkbox(
                    "✅ Финальный выпуск",
                    value=bool(rec.get("is_final_release") or False))

                submitted = st.form_submit_button("📋 Подготовить изменение", type="primary",
                                                   use_container_width=True)
                if submitted:
                    # Сохраняем черновик изменений в session_state
                    st.session_state["edit_pending"] = True
                    st.session_state["edit_draft"] = {
                        "id":                       rec["id"],
                        "record_type":              e_rtype,
                        "machine_id":               e_mid,
                        "operator_id":              e_oid if e_oid else None,
                        "date":                     e_date.isoformat(),
                        "batch":                    e_batch,
                        "batch_number":             e_batch_no,
                        "setup_time":               e_setup,
                        "produced_qty":             e_qty,
                        "actual_duration_minutes":  e_fact if e_fact > 0 else None,
                        "repair_duration_hours":    e_repair_h if e_repair_h > 0 else None,
                        "stage_name":               e_stage.strip() or None,
                        "notes":                    e_notes,
                        "is_final_release":         1 if e_final else 0,
                    }

            # Шаг 3: подтверждение
            if st.session_state.get("edit_pending") and "edit_draft" in st.session_state:
                draft = st.session_state["edit_draft"]
                st.warning(
                    f"⚠️ **Вы уверены, что хотите изменить запись ID {draft['id']}?**\n\n"
                    f"Тип: `{draft['record_type']}` | Дата: `{draft['date']}` | "
                    f"Выпущено: `{draft['produced_qty']} шт` | "
                    f"Наладка: `{draft['setup_time']} ч`\n\n"
                    "Изменения будут сохранены в базе данных."
                )
                conf_col, cancel_col = st.columns(2)
                with conf_col:
                    if st.button("✔ Подтвердить изменение", type="primary",
                                 use_container_width=True, key="confirm_edit_btn"):
                        require_not_viewer()
                        # Вычисляем plan_h
                        qty = draft["produced_qty"]
                        m_row = q("SELECT productivity FROM machines WHERE id=?",
                                  (draft["machine_id"],), fetch="one")
                        prod_val = m_row["productivity"] if m_row else 1.0
                        plan_h = round(qty / prod_val, 3) if qty > 0 else 0.0
                        exec_sql("""
                            UPDATE production SET
                                record_type              = ?,
                                machine_id               = ?,
                                operator_id              = ?,
                                date                     = ?,
                                batch                    = ?,
                                batch_number             = ?,
                                setup_time               = ?,
                                produced_qty             = ?,
                                actual_time              = ?,
                                actual_duration_minutes  = ?,
                                repair_duration_hours    = ?,
                                stage_name               = ?,
                                notes                    = ?,
                                is_final_release         = ?
                            WHERE id = ?
                        """, (
                            draft["record_type"],
                            draft["machine_id"],
                            draft["operator_id"],
                            draft["date"],
                            draft["batch"],
                            draft["batch_number"],
                            draft["setup_time"],
                            draft["produced_qty"],
                            plan_h,
                            draft["actual_duration_minutes"],
                            draft["repair_duration_hours"],
                            draft["stage_name"],
                            draft["notes"],
                            draft["is_final_release"],
                            draft["id"],
                        ))
                        st.success(f"✅ Запись ID {draft['id']} успешно обновлена.")
                        # Сбрасываем состояние редактирования
                        del st.session_state["edit_record"]
                        del st.session_state["edit_draft"]
                        st.session_state["edit_pending"] = False
                        st.rerun()
                with cancel_col:
                    if st.button("✘ Отмена", use_container_width=True,
                                 key="cancel_edit_btn"):
                        st.session_state["edit_pending"] = False
                        st.rerun()


def page_admin_crud():
    require_admin()
    st.title("👥 Управление станками и персоналом")

    tab_m, tab_o, tab_u = st.tabs(["⚙ Станки", "👤 Операторы", "🔑 Пользователи"])

    # ── Станки ────────────────────────────────────────────────────────
    with tab_m:
        machines = q("SELECT * FROM machines ORDER BY id")
        df_m = pd.DataFrame(machines)
        if not df_m.empty:
            # Подстраиваем столбцы в зависимости от того, есть ли поле is_work_center
            if "is_work_center" in df_m.columns:
                df_m["Тип"] = df_m["is_work_center"].apply(
                    lambda x: "🏭 Рабочий центр" if x else "⚙️ Станок")
                show_cols = ["id","name","model","productivity","status","notes","Тип"]
                df_show_m = df_m[show_cols].copy()
                df_show_m.columns = ["ID","Название","Модель","Произв.д/ч","Статус","Примечание","Тип"]
            else:
                df_show_m = df_m.copy()
                df_show_m.columns = ["ID","Название","Модель","Произв.д/ч","Статус","Примечание"]
            df_show_m["Статус"] = df_show_m["Статус"].map(STATUS_LABELS)
            st.dataframe(df_show_m, use_container_width=True, hide_index=True)

        st.markdown("#### ➕ Добавить станок / рабочий центр")
        with st.form("add_machine", clear_on_submit=True):
            mc1, mc2, mc3, mc4 = st.columns([3, 2, 1, 2])
            m_name    = mc1.text_input("Название*")
            m_model   = mc2.text_input("Модель")
            m_prod    = mc3.number_input("Произв.д/ч", min_value=0.1, value=10.0, step=0.5)
            m_notes   = mc4.text_input("Примечание")
            m_is_wc   = st.checkbox("🏭 Рабочий центр (ОПТА)",
                                    help="Установите, если это рабочий центр. "
                                         "Его выпуск будет отражаться в статистике ОПТА, "
                                         "а не в установах станков.")
            if st.form_submit_button("Добавить", type="primary"):
                if not m_name:
                    st.error("Укажите название станка.")
                else:
                    exec_sql("INSERT INTO machines (name,model,productivity,notes,is_work_center) VALUES (?,?,?,?,?)",
                             (m_name, m_model, m_prod, m_notes, 1 if m_is_wc else 0))
                    kind = "Рабочий центр" if m_is_wc else "Станок"
                    st.success(f"{kind} «{m_name}» добавлен.")
                    st.rerun()

        st.markdown("#### ✏️ Редактировать станок / рабочий центр")
        with st.form("edit_machine", clear_on_submit=True):
            machines_now = q("SELECT id, name, COALESCE(is_work_center,0) AS is_work_center FROM machines ORDER BY id")
            em1, em2, em3, em4, em5 = st.columns([2, 3, 2, 1, 2])
            e_id    = em1.selectbox("Станок / РЦ",
                options=[m["id"] for m in machines_now],
                format_func=lambda x: f"{'🏭' if next(m['is_work_center'] for m in machines_now if m['id']==x) else '⚙️'} #{x} {next(m['name'] for m in machines_now if m['id']==x)}")
            e_name  = em2.text_input("Новое название")
            e_model = em3.text_input("Модель")
            e_prod  = em4.number_input("Произв.", min_value=0.1, value=10.0, step=0.5)
            e_notes = em5.text_input("Примечание")
            e_status = st.selectbox("Статус",
                options=list(STATUS_LABELS.keys()),
                format_func=lambda x: STATUS_LABELS[x])
            e_is_wc = st.checkbox("🏭 Рабочий центр (ОПТА)",
                                  help="Включите, чтобы перевести этот объект в категорию ОПТА.")
            if st.form_submit_button("Сохранить изменения"):
                updates, vals = [], []
                if e_name:  updates.append("name=?");         vals.append(e_name)
                if e_model: updates.append("model=?");        vals.append(e_model)
                updates.append("productivity=?"); vals.append(e_prod)
                updates.append("status=?");       vals.append(e_status)
                updates.append("notes=?");        vals.append(e_notes)
                updates.append("is_work_center=?"); vals.append(1 if e_is_wc else 0)
                vals.append(e_id)
                exec_sql(f"UPDATE machines SET {', '.join(updates)} WHERE id=?", vals)
                st.success("✅ Станок / рабочий центр обновлён.")
                st.rerun()

        st.markdown("#### 🗑 Удалить станок")
        with st.form("del_machine", clear_on_submit=True):
            machines_now = q("SELECT id, name FROM machines ORDER BY id")
            d_id = st.selectbox("Выберите станок для удаления",
                options=[m["id"] for m in machines_now],
                format_func=lambda x: f"#{x} {next(m['name'] for m in machines_now if m['id']==x)}")
            confirm = st.checkbox("Подтверждаю удаление станка и его истории")
            if st.form_submit_button("Удалить", type="primary"):
                if not confirm:
                    st.warning("Поставьте галочку для подтверждения.")
                else:
                    exec_sql("DELETE FROM production WHERE machine_id=?", (d_id,))
                    exec_sql("DELETE FROM machines WHERE id=?", (d_id,))
                    st.success("Станок удалён.")
                    st.rerun()

    # ── Операторы ─────────────────────────────────────────────────────
    with tab_o:
        operators = q("SELECT * FROM operators ORDER BY id")
        df_o = pd.DataFrame(operators)
        if not df_o.empty:
            df_o.columns = ["ID", "ФИО", "Разряд"]
            st.dataframe(df_o, use_container_width=True, hide_index=True)

        st.markdown("#### ➕ Добавить оператора")
        with st.form("add_op", clear_on_submit=True):
            oc1, oc2 = st.columns(2)
            o_name = oc1.text_input("ФИО*")
            o_rank = oc2.text_input("Разряд")
            if st.form_submit_button("Добавить", type="primary"):
                if not o_name:
                    st.error("Укажите ФИО.")
                else:
                    exec_sql("INSERT INTO operators (name, rank) VALUES (?,?)", (o_name, o_rank))
                    st.success(f"Оператор «{o_name}» добавлен.")
                    st.rerun()

        st.markdown("#### 🗑 Удалить оператора")
        with st.form("del_op", clear_on_submit=True):
            ops_now = q("SELECT id, name FROM operators ORDER BY id")
            if ops_now:
                do_id = st.selectbox("Оператор",
                    options=[o["id"] for o in ops_now],
                    format_func=lambda x: next(o["name"] for o in ops_now if o["id"]==x))
                if st.form_submit_button("Удалить оператора", type="primary"):
                    exec_sql("UPDATE production SET operator_id=NULL WHERE operator_id=?", (do_id,))
                    exec_sql("DELETE FROM operators WHERE id=?", (do_id,))
                    st.success("Оператор удалён.")
                    st.rerun()

    # ── Пользователи ──────────────────────────────────────────────────
    with tab_u:
        st.markdown("#### 🔑 Управление пользователями (config.yml)")
        st.info("""
Пользователи хранятся в **config.yml** (bcrypt-хеши).
Для добавления нового пользователя используйте скрипт ниже или отредактируйте файл вручную.
        """)
        with st.expander("📋 Текущие пользователи"):
            try:
                cfg = load_config()
                users = cfg["credentials"]["usernames"]
                user_data = [
                    {"Логин": u, "Имя": v.get("name", ""), "Роль": v.get("role", "user")}
                    for u, v in users.items()
                ]
                st.dataframe(pd.DataFrame(user_data), use_container_width=True, hide_index=True)
            except Exception as e:
                st.error(f"Ошибка чтения config.yml: {e}")

        st.markdown("#### ➕ Добавить пользователя")
        st.markdown("Выполните команду в контейнере:")
        st.code("""docker exec -it lathe_app python manage_users.py add <login> <password> <name> <role>
# Пример:
docker exec -it lathe_app python manage_users.py add operator2 pass456 "Смирнов А.В." user""", language="bash")

        with st.form("add_user_form", clear_on_submit=True):
            uu1, uu2, uu3, uu4 = st.columns([2, 2, 2, 1])
            new_login = uu1.text_input("Логин*")
            new_pass  = uu2.text_input("Пароль*", type="password")
            new_name  = uu3.text_input("Полное имя*")
            new_role  = uu4.selectbox("Роль", ["user", "viewer", "admin"],
                                       help="user = ввод данных; viewer = только просмотр; admin = полный доступ")
            if st.form_submit_button("Создать пользователя", type="primary"):
                if not all([new_login, new_pass, new_name]):
                    st.error("Заполните все обязательные поля.")
                else:
                    try:
                        import bcrypt as _bcrypt
                        hashed = _bcrypt.hashpw(
                            new_pass.encode(), _bcrypt.gensalt(12)
                        ).decode()
                        cfg = load_config()
                        if new_login in cfg["credentials"]["usernames"]:
                            st.error(f"Пользователь «{new_login}» уже существует.")
                        else:
                            cfg["credentials"]["usernames"][new_login] = {
                                "name": new_name,
                                "password": hashed,
                                "role": new_role,
                            }
                            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                                yaml.dump(cfg, f, allow_unicode=True)
                            st.success(f"✅ Пользователь «{new_login}» создан. Перезапустите приложение для применения.")
                    except ImportError:
                        st.error("bcrypt не установлен. Используйте скрипт manage_users.py в контейнере.")


def page_charts():
    role = st.session_state.get("role", "user")
    if role not in ("admin", "viewer"):
        st.error("⛔ Доступ запрещён. Требуются права администратора или наблюдателя.")
        st.stop()
    st.title("📊 Графики и аналитика")

    col_ctrl1, _ = st.columns([1, 3])
    days  = col_ctrl1.slider("Период (дней)", 7, 90, 14)
    since = (date.today() - timedelta(days=days)).isoformat()

    # ── Все записи типа "выпуск" с признаком рабочего центра ──────────
    data_all = q("""
        SELECT p.date, m.name AS machine, m.productivity,
               COALESCE(m.is_work_center, 0) AS is_work_center,
               o.name AS operator,
               p.produced_qty, p.actual_time, p.setup_time,
               COALESCE(p.is_final_release, 0) AS is_final_release
        FROM production p
        LEFT JOIN machines  m ON m.id = p.machine_id
        LEFT JOIN operators o ON o.id = p.operator_id
        WHERE p.date >= ?
          AND COALESCE(p.record_type, 'production') = 'production'
        ORDER BY p.date
    """, (since,))

    # Разделяем
    data      = [r for r in data_all if not r["is_work_center"]]   # обычные станки
    data_opta = [r for r in data_all if r["is_work_center"]]        # рабочие центры

    # ── Данные по ремонтам ─────────────────────────────────────────────
    repair_data = q("""
        SELECT p.date, m.name AS machine, o.name AS operator,
               p.repair_duration_hours, p.notes
        FROM production p
        LEFT JOIN machines  m ON m.id = p.machine_id
        LEFT JOIN operators o ON o.id = p.operator_id
        WHERE p.date >= ?
          AND p.record_type = 'repair'
        ORDER BY p.date
    """, (since,))

    tab1, tab2, tab3, tab4, tab5, tab6, tab_opta = st.tabs([
        "📈 Загрузка по дням",
        "🏭 Выпуск по станкам",
        "👤 По операторам",
        "⚡ Производительность",
        "🔧 Наладка",
        "🔄 Статусы станков",
        "🏭 ОПТА",
    ])

    # ── График 1: Загрузка по дням ─────────────────────────────────────
    with tab1:
        if not data:
            st.info("Нет данных за выбранный период.")
        else:
            df = pd.DataFrame(data)
            df["date"] = pd.to_datetime(df["date"])
            df["is_final_release"] = df["is_final_release"].fillna(0).astype(int)

            # Метрики вверху
            total_inst  = df["produced_qty"].sum()
            total_final = df[df["is_final_release"] == 1]["produced_qty"].sum()
            ma1, ma2 = st.columns(2)
            ma1.metric("Установов (шт, всего)", f"{int(total_inst):,}")
            ma2.metric("🏁 Финальный выпуск (шт)", f"{int(total_final):,}")

            daily = df.groupby(["date", "machine"])["produced_qty"].sum().reset_index()

            fig = px.bar(daily, x="date", y="produced_qty", color="machine",
                         barmode="group",
                         title=f"Установы по дням ({days} дней)",
                         labels={"date": "Дата", "produced_qty": "Установов (шт)",
                                 "machine": "Станок"},
                         template="plotly_dark",
                         color_discrete_sequence=px.colors.qualitative.Bold)
            fig.update_layout(
                plot_bgcolor="#1e2130", paper_bgcolor="#0f1117",
                font_color="#ffffff", legend_title_text="Станок",
                xaxis=dict(tickformat="%d.%m", color="#ffffff"),
                yaxis=dict(color="#ffffff"),
            )
            st.plotly_chart(fig, use_container_width=True)

            # График финального выпуска по дням
            df_fin = df[df["is_final_release"] == 1]
            if not df_fin.empty:
                daily_fin = df_fin.groupby("date")["produced_qty"].sum().reset_index()
                fig_fin = px.bar(daily_fin, x="date", y="produced_qty",
                                 title="Финальный выпуск по дням",
                                 labels={"date": "Дата", "produced_qty": "Готовых деталей (шт)"},
                                 template="plotly_dark",
                                 color_discrete_sequence=["#43c59e"])
                fig_fin.update_layout(plot_bgcolor="#1e2130", paper_bgcolor="#0f1117",
                                      font_color="#ffffff",
                                      xaxis=dict(tickformat="%d.%m"))
                st.plotly_chart(fig_fin, use_container_width=True)
            else:
                st.info("Нет записей с галочкой «Финальный выпуск» за период.")

            if not daily.empty:
                daily_hm = daily.copy()
                daily_hm["date_lbl"] = daily_hm["date"].dt.strftime("%d.%m")
                try:
                    pivot2 = daily_hm.pivot_table(
                        index="machine", columns="date_lbl",
                        values="produced_qty", fill_value=0, aggfunc="sum")
                    if not pivot2.empty:
                        fig_hm = px.imshow(pivot2, title="Тепловая карта установов",
                                           template="plotly_dark",
                                           color_continuous_scale="Blues",
                                           labels=dict(color="Шт."))
                        fig_hm.update_layout(paper_bgcolor="#0f1117", font_color="#ffffff")
                        st.plotly_chart(fig_hm, use_container_width=True)
                except Exception as e:
                    st.info(f"Не удалось построить тепловую карту: {e}")

    # ── График 2: Выпуск по станкам ────────────────────────────────────
    with tab2:
        if not data:
            st.info("Нет данных за выбранный период.")
        else:
            df = pd.DataFrame(data)
            df["date"] = pd.to_datetime(df["date"])
            df["is_final_release"] = df["is_final_release"].fillna(0).astype(int)

            # Установы по станкам (все)
            by_machine = df.groupby("machine")["produced_qty"].sum().reset_index()
            by_machine.columns = ["Станок", "Установов (шт)"]
            # Финальный выпуск по станкам
            by_machine_fin = (df[df["is_final_release"] == 1]
                              .groupby("machine")["produced_qty"].sum().reset_index())
            by_machine_fin.columns = ["Станок", "Финальный выпуск (шт)"]
            bm = by_machine.merge(by_machine_fin, on="Станок", how="left").fillna(0)
            bm = bm.sort_values("Установов (шт)", ascending=False)

            c1, c2 = st.columns(2)
            with c1:
                fig_bar = px.bar(bm, x="Станок", y="Установов (шт)",
                                 title="Установов по станкам",
                                 template="plotly_dark",
                                 color="Установов (шт)", color_continuous_scale="Viridis",
                                 text="Установов (шт)")
                fig_bar.update_traces(textposition="outside")
                fig_bar.update_layout(paper_bgcolor="#0f1117", plot_bgcolor="#1e2130",
                                      font_color="#ffffff", showlegend=False)
                st.plotly_chart(fig_bar, use_container_width=True)
            with c2:
                fig_fin = px.bar(bm, x="Станок", y="Финальный выпуск (шт)",
                                 title="🏁 Финальный выпуск по станкам",
                                 template="plotly_dark",
                                 color="Финальный выпуск (шт)", color_continuous_scale="Teal",
                                 text="Финальный выпуск (шт)")
                fig_fin.update_traces(textposition="outside")
                fig_fin.update_layout(paper_bgcolor="#0f1117", plot_bgcolor="#1e2130",
                                      font_color="#ffffff", showlegend=False)
                st.plotly_chart(fig_fin, use_container_width=True)

            # Сводная таблица
            st.markdown("#### Установы vs Финальный выпуск")
            bm["% финальных"] = (
                bm["Финальный выпуск (шт)"] / bm["Установов (шт)"].replace(0, float("nan")) * 100
            ).round(1).fillna(0)
            st.dataframe(bm[["Станок", "Установов (шт)", "Финальный выпуск (шт)", "% финальных"]],
                         use_container_width=True, hide_index=True)

    # ── График 3: По операторам ────────────────────────────────────────
    with tab3:
        if not data:
            st.info("Нет данных за выбранный период.")
        else:
            df = pd.DataFrame(data)
            df["date"] = pd.to_datetime(df["date"])
            df["is_final_release"] = df["is_final_release"].fillna(0).astype(int)
            df_op = df[df["operator"].notna() & (df["operator"] != "")]
            if df_op.empty:
                st.info("Нет данных по операторам.")
            else:
                # Установы по операторам
                by_op = df_op.groupby("operator")["produced_qty"].sum().reset_index()
                by_op.columns = ["Оператор", "Установов (шт)"]
                # Финальный выпуск по операторам
                by_op_fin = (df_op[df_op["is_final_release"] == 1]
                             .groupby("operator")["produced_qty"].sum().reset_index())
                by_op_fin.columns = ["Оператор", "Финальный выпуск (шт)"]
                by_op = by_op.merge(by_op_fin, on="Оператор", how="left").fillna(0)
                by_op = by_op.sort_values("Установов (шт)", ascending=True)

                # Grouped bar: установы + финальный выпуск
                fig_op = go.Figure()
                fig_op.add_trace(go.Bar(
                    name="Установов (шт)", y=by_op["Оператор"],
                    x=by_op["Установов (шт)"],
                    orientation="h", marker_color="#7c6af7",
                    text=by_op["Установов (шт)"], textposition="outside"))
                fig_op.add_trace(go.Bar(
                    name="Финальный выпуск", y=by_op["Оператор"],
                    x=by_op["Финальный выпуск (шт)"],
                    orientation="h", marker_color="#43c59e",
                    text=by_op["Финальный выпуск (шт)"], textposition="outside"))
                fig_op.update_layout(
                    barmode="group",
                    title="Установы и финальный выпуск по операторам",
                    template="plotly_dark",
                    paper_bgcolor="#0f1117", plot_bgcolor="#1e2130",
                    font_color="#ffffff", showlegend=True,
                    height=max(300, len(by_op) * 70),
                    legend=dict(bgcolor="#1e2130"))
                st.plotly_chart(fig_op, use_container_width=True)

                op_daily = df_op.groupby(["date", "operator"])["produced_qty"].sum().reset_index()
                fig_op2 = px.line(op_daily, x="date", y="produced_qty", color="operator",
                                  title="Динамика установов по операторам",
                                  template="plotly_dark",
                                  labels={"date": "Дата", "produced_qty": "Установов",
                                          "operator": "Оператор"}, markers=True)
                fig_op2.update_layout(paper_bgcolor="#0f1117", plot_bgcolor="#1e2130",
                                      font_color="#ffffff", xaxis=dict(tickformat="%d.%m"))
                st.plotly_chart(fig_op2, use_container_width=True)

    # ── График 4: Производительность ──────────────────────────────────
    with tab4:
        machines_all = q("SELECT id, name, productivity FROM machines WHERE COALESCE(is_work_center,0)=0 ORDER BY id")
        if not machines_all or not data:
            st.info("Нет данных для сравнения производительности.")
        else:
            df = pd.DataFrame(data)
            df["date"] = pd.to_datetime(df["date"])

            fact_prod = df[df["actual_time"] > 0].copy()
            fact_prod["fact_prod"] = fact_prod["produced_qty"] / fact_prod["actual_time"]
            avg_fact = fact_prod.groupby("machine")["fact_prod"].mean().reset_index()
            avg_fact.columns = ["Станок", "Факт д/ч"]

            df_nom = pd.DataFrame([{"Станок": m["name"], "Норма д/ч": m["productivity"]}
                                   for m in machines_all])
            df_cmp = df_nom.merge(avg_fact, on="Станок", how="left").fillna(0)

            fig_cmp = go.Figure()
            fig_cmp.add_trace(go.Bar(
                name="Норма", x=df_cmp["Станок"], y=df_cmp["Норма д/ч"],
                marker_color="#7c6af7", text=df_cmp["Норма д/ч"].round(1),
                textposition="outside"))
            fig_cmp.add_trace(go.Bar(
                name="Факт (ср.)", x=df_cmp["Станок"], y=df_cmp["Факт д/ч"].round(1),
                marker_color="#43c59e", text=df_cmp["Факт д/ч"].round(1),
                textposition="outside"))
            fig_cmp.update_layout(
                title="Производительность: норма vs факт",
                barmode="group", template="plotly_dark",
                paper_bgcolor="#0f1117", plot_bgcolor="#1e2130",
                font_color="#ffffff", legend=dict(bgcolor="#1e2130"))
            st.plotly_chart(fig_cmp, use_container_width=True)

            df_cmp["Эффективность %"] = (
                df_cmp["Факт д/ч"] / df_cmp["Норма д/ч"].replace(0, float("nan")) * 100
            ).round(1).fillna(0)
            st.dataframe(
                df_cmp[["Станок", "Норма д/ч", "Факт д/ч", "Эффективность %"]]
                .style.background_gradient(subset=["Эффективность %"],
                                           cmap="RdYlGn", vmin=0, vmax=120),
                use_container_width=True, hide_index=True)

    # ── Вкладка 5: Наладка ────────────────────────────────────────────
    with tab5:
        _tab_setup_analytics(data, days)

    # ── Вкладка 6: Статусы станков ─────────────────────────────────────
    with tab6:
        _tab_status_analytics(days, since)

    # ── Вкладка 7: ОПТА (рабочие центры) ─────────────────────────────
    with tab_opta:
        _tab_opta_analytics(data_opta, days)


def _tab_setup_analytics(data: list, days: int):
    """Аналитика по времени наладки на основе записей выпуска."""
    st.markdown("### 🔧 Аналитика по времени наладки")

    if not data:
        st.info("Нет данных для анализа наладки за выбранный период.")
        return

    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"])

    # Оставляем только строки с setup_time > 0
    df["setup_time"] = pd.to_numeric(df["setup_time"], errors="coerce").fillna(0)
    df_s = df[df["setup_time"] > 0].copy()

    if df_s.empty:
        st.info("Нет данных для анализа наладки — поле «Наладка (ч)» не заполнено ни в одной записи.")
        return

    # ── Сводная таблица по станкам ─────────────────────────────────────
    st.markdown("#### 📋 Сводная таблица по станкам")
    setup_agg = df_s.groupby("machine")["setup_time"].agg(
        total="sum", mean="mean", count="count"
    ).reset_index()
    setup_agg.columns = ["Станок", "Суммарно (ч)", "Среднее (ч)", "Операций с наладкой"]
    setup_agg["Суммарно (ч)"] = setup_agg["Суммарно (ч)"].round(2)
    setup_agg["Среднее (ч)"]  = setup_agg["Среднее (ч)"].round(2)
    setup_agg = setup_agg.sort_values("Суммарно (ч)", ascending=False)
    st.dataframe(setup_agg, use_container_width=True, hide_index=True)

    # ── По операторам ─────────────────────────────────────────────────
    df_op_s = df_s[df_s["operator"].notna() & (df_s["operator"] != "")]
    if not df_op_s.empty:
        setup_op = df_op_s.groupby("operator")["setup_time"].agg(
            total="sum", mean="mean", count="count"
        ).reset_index()
        setup_op.columns = ["Оператор", "Суммарно (ч)", "Среднее (ч)", "Операций"]
        setup_op["Суммарно (ч)"] = setup_op["Суммарно (ч)"].round(2)
        setup_op["Среднее (ч)"]  = setup_op["Среднее (ч)"].round(2)
        with st.expander("👤 Сводная таблица по операторам"):
            st.dataframe(setup_op.sort_values("Суммарно (ч)", ascending=False),
                         use_container_width=True, hide_index=True)

    c1, c2 = st.columns(2)

    # ── Bar chart: суммарное время наладки по станкам ─────────────────
    with c1:
        fig_bar = px.bar(
            setup_agg,
            x="Станок", y="Суммарно (ч)",
            title="Суммарное время наладки по станкам",
            template="plotly_dark",
            color="Суммарно (ч)",
            color_continuous_scale="YlOrRd",
            text=setup_agg["Суммарно (ч)"].round(2),
        )
        fig_bar.update_traces(textposition="outside")
        fig_bar.update_layout(
            paper_bgcolor="#0f1117", plot_bgcolor="#1e2130",
            font_color="#ffffff", showlegend=False)
        st.plotly_chart(fig_bar, use_container_width=True)

    # ── Bar chart: среднее время наладки по станкам ───────────────────
    with c2:
        fig_avg = px.bar(
            setup_agg.sort_values("Среднее (ч)", ascending=False),
            x="Станок", y="Среднее (ч)",
            title="Среднее время наладки за операцию",
            template="plotly_dark",
            color="Среднее (ч)",
            color_continuous_scale="Purp",
            text=setup_agg.sort_values("Среднее (ч)", ascending=False)["Среднее (ч)"].round(2),
        )
        fig_avg.update_traces(textposition="outside")
        fig_avg.update_layout(
            paper_bgcolor="#0f1117", plot_bgcolor="#1e2130",
            font_color="#ffffff", showlegend=False)
        st.plotly_chart(fig_avg, use_container_width=True)

    # ── Line/bar chart: динамика наладки по дням ──────────────────────
    daily_setup = df_s.groupby("date")["setup_time"].sum().reset_index()
    daily_setup.columns = ["Дата", "Суммарно (ч)"]

    fig_line = px.bar(
        daily_setup, x="Дата", y="Суммарно (ч)",
        title=f"Динамика суммарной наладки по дням ({days} дней)",
        template="plotly_dark",
        color_discrete_sequence=["#f9c74f"],
        text=daily_setup["Суммарно (ч)"].round(2),
    )
    fig_line.update_traces(textposition="outside")
    fig_line.update_layout(
        paper_bgcolor="#0f1117", plot_bgcolor="#1e2130",
        font_color="#ffffff",
        xaxis=dict(tickformat="%d.%m", color="#ffffff"),
        yaxis=dict(title="Часов наладки", color="#ffffff"),
    )
    st.plotly_chart(fig_line, use_container_width=True)

    # ── Line chart: наладка по дням и станкам ─────────────────────────
    if df_s["machine"].nunique() > 1:
        daily_m = df_s.groupby(["date", "machine"])["setup_time"].sum().reset_index()
        fig_line2 = px.line(
            daily_m, x="date", y="setup_time", color="machine",
            title="Динамика наладки по дням (по станкам)",
            template="plotly_dark",
            labels={"date": "Дата", "setup_time": "Наладка (ч)", "machine": "Станок"},
            markers=True,
        )
        fig_line2.update_layout(
            paper_bgcolor="#0f1117", plot_bgcolor="#1e2130",
            font_color="#ffffff",
            xaxis=dict(tickformat="%d.%m"),
        )
        st.plotly_chart(fig_line2, use_container_width=True)


def _tab_opta_analytics(data_opta: list, days: int):
    """Аналитика по рабочим центрам (ОПТА)."""
    st.markdown("### 🏭 Аналитика рабочих центров (ОПТА)")

    if not data_opta:
        st.info("📭 Нет данных по рабочим центрам за выбранный период. "
                "Добавьте объект с признаком «Рабочий центр» и внесите записи выпуска.")
        return

    df = pd.DataFrame(data_opta)
    df["date"]             = pd.to_datetime(df["date"])
    df["is_final_release"] = df["is_final_release"].fillna(0).astype(int)

    # ── Метрики ────────────────────────────────────────────────────────
    total_opta  = df["produced_qty"].sum()
    final_opta  = df[df["is_final_release"] == 1]["produced_qty"].sum()
    oa1, oa2, oa3 = st.columns(3)
    oa1.metric("Выпуск ОПТА (шт)",        f"{int(total_opta):,}")
    oa2.metric("🏁 Финальный выпуск ОПТА", f"{int(final_opta):,}")
    oa3.metric("Записей ОПТА",             len(df))

    st.divider()

    # ── Выпуск по рабочим центрам ──────────────────────────────────────
    by_wc = df.groupby("machine")["produced_qty"].sum().reset_index()
    by_wc.columns = ["Рабочий центр", "Выпуск ОПТА (шт)"]
    by_wc_fin = (df[df["is_final_release"] == 1]
                 .groupby("machine")["produced_qty"].sum().reset_index())
    by_wc_fin.columns = ["Рабочий центр", "Финальный выпуск ОПТА (шт)"]
    bwc = by_wc.merge(by_wc_fin, on="Рабочий центр", how="left").fillna(0)
    bwc = bwc.sort_values("Выпуск ОПТА (шт)", ascending=False)

    c1, c2 = st.columns(2)
    with c1:
        fig_o1 = px.bar(bwc, x="Рабочий центр", y="Выпуск ОПТА (шт)",
                        title="Выпуск ОПТА по рабочим центрам",
                        template="plotly_dark",
                        color="Выпуск ОПТА (шт)", color_continuous_scale="Teal",
                        text="Выпуск ОПТА (шт)")
        fig_o1.update_traces(textposition="outside")
        fig_o1.update_layout(paper_bgcolor="#0f1117", plot_bgcolor="#1e2130",
                             font_color="#ffffff", showlegend=False)
        st.plotly_chart(fig_o1, use_container_width=True)
    with c2:
        fig_o2 = px.bar(bwc, x="Рабочий центр", y="Финальный выпуск ОПТА (шт)",
                        title="🏁 Финальный выпуск ОПТА",
                        template="plotly_dark",
                        color="Финальный выпуск ОПТА (шт)", color_continuous_scale="Purp",
                        text="Финальный выпуск ОПТА (шт)")
        fig_o2.update_traces(textposition="outside")
        fig_o2.update_layout(paper_bgcolor="#0f1117", plot_bgcolor="#1e2130",
                             font_color="#ffffff", showlegend=False)
        st.plotly_chart(fig_o2, use_container_width=True)

    # ── Динамика выпуска ОПТА по дням ─────────────────────────────────
    daily_opta = df.groupby(["date", "machine"])["produced_qty"].sum().reset_index()
    if not daily_opta.empty:
        fig_dyn = px.bar(daily_opta, x="date", y="produced_qty", color="machine",
                         barmode="group",
                         title=f"Выпуск ОПТА по дням ({days} дней)",
                         labels={"date": "Дата", "produced_qty": "Выпуск (шт)",
                                 "machine": "Рабочий центр"},
                         template="plotly_dark",
                         color_discrete_sequence=px.colors.qualitative.Pastel)
        fig_dyn.update_layout(plot_bgcolor="#1e2130", paper_bgcolor="#0f1117",
                              font_color="#ffffff",
                              xaxis=dict(tickformat="%d.%m"))
        st.plotly_chart(fig_dyn, use_container_width=True)

    # ── Операторы ОПТА ────────────────────────────────────────────────
    st.markdown("#### 👤 Операторы ОПТА")
    df_op = df[df["operator"].notna() & (df["operator"] != "")]
    if df_op.empty:
        st.info("Нет данных по операторам ОПТА.")
    else:
        by_op_o = df_op.groupby("operator")["produced_qty"].sum().reset_index()
        by_op_o.columns = ["Оператор ОПТА", "Выпуск ОПТА (шт)"]
        by_op_o_fin = (df_op[df_op["is_final_release"] == 1]
                       .groupby("operator")["produced_qty"].sum().reset_index())
        by_op_o_fin.columns = ["Оператор ОПТА", "Финальный ОПТА (шт)"]
        by_op_o = by_op_o.merge(by_op_o_fin, on="Оператор ОПТА", how="left").fillna(0)
        by_op_o = by_op_o.sort_values("Выпуск ОПТА (шт)", ascending=True)

        fig_op_o = go.Figure()
        fig_op_o.add_trace(go.Bar(
            name="Выпуск ОПТА", y=by_op_o["Оператор ОПТА"],
            x=by_op_o["Выпуск ОПТА (шт)"],
            orientation="h", marker_color="#56cfe1",
            text=by_op_o["Выпуск ОПТА (шт)"], textposition="outside"))
        fig_op_o.add_trace(go.Bar(
            name="Финальный ОПТА", y=by_op_o["Оператор ОПТА"],
            x=by_op_o["Финальный ОПТА (шт)"],
            orientation="h", marker_color="#f9c74f",
            text=by_op_o["Финальный ОПТА (шт)"], textposition="outside"))
        fig_op_o.update_layout(
            barmode="group",
            title="Выпуск и финальный выпуск ОПТА по операторам",
            template="plotly_dark",
            paper_bgcolor="#0f1117", plot_bgcolor="#1e2130",
            font_color="#ffffff", showlegend=True,
            height=max(300, len(by_op_o) * 70),
            legend=dict(bgcolor="#1e2130"))
        st.plotly_chart(fig_op_o, use_container_width=True)

        st.markdown("#### Сводная таблица операторов ОПТА")
        st.dataframe(by_op_o.sort_values("Выпуск ОПТА (шт)", ascending=False),
                     use_container_width=True, hide_index=True)

    # ── Итоговая таблица по РЦ ────────────────────────────────────────
    st.markdown("#### Сводная таблица по рабочим центрам")
    bwc["% финальных"] = (
        bwc["Финальный выпуск ОПТА (шт)"] /
        bwc["Выпуск ОПТА (шт)"].replace(0, float("nan")) * 100
    ).round(1).fillna(0)
    st.dataframe(bwc, use_container_width=True, hide_index=True)


def _tab_status_analytics(days: int, since: str):
    """Аналитика по времени в статусах на основе machine_status_log."""
    st.markdown("### 🔄 Время станков в каждом статусе")

    machines_all = q("SELECT id, name FROM machines ORDER BY id")
    if not machines_all:
        st.info("Нет данков.")
        return

    # Фильтры
    flt1, flt2, flt3 = st.columns(3)
    sel_m = flt1.selectbox("Станок (фильтр)",
        options=[0] + [m["id"] for m in machines_all],
        format_func=lambda x: "Все" if x == 0
            else next(m["name"] for m in machines_all if m["id"] == x),
        key="status_filter_m")
    flt_from = flt2.date_input("Дата от", value=date.today() - timedelta(days=days),
                                key="status_flt_from")
    flt_to   = flt3.date_input("Дата до", value=date.today(), key="status_flt_to")

    # Загружаем журнал событий
    log_sql = """
        SELECT sl.machine_id, m.name AS machine, sl.status,
               sl.changed_by, sl.changed_at
        FROM machine_status_log sl
        JOIN machines m ON m.id = sl.machine_id
        WHERE DATE(sl.changed_at) BETWEEN ? AND ?
    """
    log_params = [flt_from.isoformat(), flt_to.isoformat()]
    if sel_m:
        log_sql += " AND sl.machine_id = ?"
        log_params.append(sel_m)
    log_sql += " ORDER BY sl.machine_id, sl.changed_at"

    log_rows = q(log_sql, log_params)

    if not log_rows:
        st.info("📭 Нет записей изменений статусов за выбранный период.")
        st.markdown("Статусы фиксируются автоматически при каждом изменении "
                    "через форму «Изменить статус станка».")
        return

    # ── Расчёт интервалов ────────────────────────────────────────────
    # Для каждого станка: список событий по времени.
    # Время статуса = changed_at[i+1] - changed_at[i].
    # Для последнего события в выборке конец = min(now, flt_to + 1 day).
    from collections import defaultdict
    machine_events: dict = defaultdict(list)
    for row in log_rows:
        machine_events[row["machine_id"]].append(row)

    now_cap = datetime.combine(flt_to + timedelta(days=1), datetime.min.time())

    interval_rows = []
    for mid, events in machine_events.items():
        for i, ev in enumerate(events):
            t_start = datetime.fromisoformat(ev["changed_at"])
            if i + 1 < len(events):
                t_end = datetime.fromisoformat(events[i + 1]["changed_at"])
            else:
                t_end = min(datetime.now(), now_cap)
            duration_h = max(0.0, (t_end - t_start).total_seconds() / 3600)
            interval_rows.append({
                "machine":    ev["machine"],
                "machine_id": mid,
                "status":     ev["status"],
                "status_lbl": STATUS_LABELS.get(ev["status"], ev["status"]),
                "duration_h": round(duration_h, 3),
                "changed_at": ev["changed_at"],
                "changed_by": ev["changed_by"],
            })

    if not interval_rows:
        st.info("Нет данных для построения графиков.")
        return

    df_int = pd.DataFrame(interval_rows)

    # ── Агрегация: суммарное время по станку × статус ─────────────────
    agg = df_int.groupby(["machine", "status_lbl"])["duration_h"].sum().reset_index()
    agg.columns = ["Станок", "Статус", "Часов"]
    agg["Часов"] = agg["Часов"].round(2)

    # Stacked bar по станкам
    color_map = {STATUS_LABELS.get(k, k): v for k, v in STATUS_COLORS.items()}
    fig_stack = px.bar(agg, x="Станок", y="Часов", color="Статус",
                       barmode="stack",
                       title=f"Распределение времени по статусам (часов)",
                       template="plotly_dark",
                       color_discrete_map=color_map)
    fig_stack.update_layout(paper_bgcolor="#0f1117", plot_bgcolor="#1e2130",
                            font_color="#e0e0f0")
    st.plotly_chart(fig_stack, use_container_width=True)

    # Bar по статусам суммарно
    agg_status = df_int.groupby("status_lbl")["duration_h"].sum().reset_index()
    agg_status.columns = ["Статус", "Часов"]
    agg_status = agg_status.sort_values("Часов", ascending=False)
    fig_tot = px.bar(agg_status, x="Статус", y="Часов",
                     title="Суммарное время по статусам (все станки)",
                     template="plotly_dark",
                     color="Статус", color_discrete_map=color_map,
                     text=agg_status["Часов"].round(1))
    fig_tot.update_traces(textposition="outside")
    fig_tot.update_layout(paper_bgcolor="#0f1117", plot_bgcolor="#1e2130",
                          font_color="#e0e0f0", showlegend=False)
    st.plotly_chart(fig_tot, use_container_width=True)

    # Сводная таблица
    st.markdown("#### Сводная таблица (часов в статусе)")
    try:
        pivot_tbl = agg.pivot_table(index="Станок", columns="Статус",
                                    values="Часов", fill_value=0, aggfunc="sum")
        pivot_tbl["Итого"] = pivot_tbl.sum(axis=1)
        st.dataframe(pivot_tbl.round(2), use_container_width=True)
    except Exception:
        st.dataframe(agg, use_container_width=True, hide_index=True)

    # Лог событий
    with st.expander("📋 Журнал событий статусов"):
        df_log = pd.DataFrame(interval_rows)[
            ["changed_at", "machine", "status_lbl", "duration_h", "changed_by"]]
        df_log.columns = ["Время события", "Станок", "Статус", "Длит. (ч)", "Кто изменил"]
        st.dataframe(df_log, use_container_width=True, hide_index=True)


def page_export():
    role = st.session_state.get("role", "user")
    if role not in ("admin", "viewer"):
        st.error("⛔ Доступ запрещён.")
        st.stop()
    st.title("💾 Экспорт данных")

    machines  = q("SELECT * FROM machines ORDER BY id")
    operators = q("SELECT * FROM operators ORDER BY id")
    production = q("""
        SELECT p.id,
               COALESCE(p.record_type,'production') AS record_type,
               COALESCE(p.is_final_release, 0)      AS is_final_release,
               p.stage_name,
               p.date, m.name AS machine, o.name AS operator,
               p.batch, p.batch_number, p.setup_time,
               p.produced_qty, p.actual_time,
               p.actual_duration_minutes,
               p.repair_duration_hours,
               p.notes
        FROM production p
        LEFT JOIN machines  m ON m.id = p.machine_id
        LEFT JOIN operators o ON o.id = p.operator_id
        ORDER BY p.date DESC, p.id DESC
    """)

    def to_csv(rows, columns):
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({c: row.get(c, "") for c in columns})
        return buf.getvalue().encode("utf-8-sig")

    st.markdown("### 📦 Экспорт таблиц")
    c1, c2, c3 = st.columns(3)

    with c1:
        st.markdown("**⚙ Станки**")
        st.dataframe(pd.DataFrame(machines), use_container_width=True, hide_index=True)
        csv_m = to_csv(machines, ["id","name","model","productivity","status","notes"])
        st.download_button("⬇ CSV: Станки", csv_m,
                           f"machines_{date.today()}.csv", "text/csv",
                           use_container_width=True)

    with c2:
        st.markdown("**👤 Операторы**")
        st.dataframe(pd.DataFrame(operators), use_container_width=True, hide_index=True)
        csv_o = to_csv(operators, ["id","name","rank"])
        st.download_button("⬇ CSV: Операторы", csv_o,
                           f"operators_{date.today()}.csv", "text/csv",
                           use_container_width=True)

    with c3:
        st.markdown(f"**📋 История ({len(production)} записей)**")
        csv_p = to_csv(production,
                       ["id","record_type","is_final_release","stage_name",
                        "date","machine","operator",
                        "batch","batch_number","setup_time","produced_qty","actual_time",
                        "actual_duration_minutes","repair_duration_hours","notes"])
        st.download_button("⬇ CSV: История", csv_p,
                           f"production_{date.today()}.csv", "text/csv",
                           use_container_width=True)

    st.divider()
    st.markdown("### 📊 Сводный отчёт по станкам (только выпуск)")
    summary = q("""
        SELECT m.name AS Станок,
               CASE WHEN COALESCE(m.is_work_center,0)=1 THEN '🏭 Рабочий центр'
                    ELSE '⚙️ Станок' END AS Тип,
               COUNT(CASE WHEN COALESCE(p.record_type,'production')='production' THEN 1 END)
                   AS "Записей (установов/ОПТА)",
               SUM(CASE WHEN COALESCE(p.record_type,'production')='production'
                        THEN p.produced_qty ELSE 0 END)          AS "Выпущено (шт)",
               SUM(CASE WHEN COALESCE(p.record_type,'production')='production'
                         AND COALESCE(p.is_final_release,0)=1
                        THEN p.produced_qty ELSE 0 END)          AS "Финальный выпуск (шт)",
               ROUND(SUM(CASE WHEN COALESCE(p.record_type,'production')='production'
                               THEN p.actual_time ELSE 0 END),2) AS "План. часов",
               ROUND(SUM(CASE WHEN COALESCE(p.record_type,'production')='production'
                               THEN p.setup_time ELSE 0 END),2)  AS "Наладка (ч)",
               COUNT(CASE WHEN p.record_type='repair' THEN 1 END)          AS "Ремонтов",
               ROUND(SUM(CASE WHEN p.record_type='repair'
                               THEN COALESCE(p.repair_duration_hours,0) ELSE 0 END),2) AS "Ремонт (ч)"
        FROM machines m
        LEFT JOIN production p ON p.machine_id = m.id
        GROUP BY m.id
        ORDER BY COALESCE(m.is_work_center,0), m.id
    """)
    df_sum = pd.DataFrame(summary)
    st.dataframe(df_sum, use_container_width=True, hide_index=True)
    csv_s = to_csv(summary, list(df_sum.columns))
    st.download_button("⬇ CSV: Сводный отчёт", csv_s,
                       f"summary_{date.today()}.csv", "text/csv")

def page_batches(role):
    """
    Страница «📋 Партии» — полноценное управление сущностью «партия».

    Права:
    - admin: создание, редактирование, удаление партий + просмотр
    - user:  только просмотр списка (не может изменять партии)
    - viewer: только просмотр
    """
    st.title("📋 Партии")

    batches = all_batches()

    # ── А) Список партий ──────────────────────────────────────────────
    st.markdown("### Список партий")

    if not batches:
        st.info("Партий пока нет. Создайте первую партию с помощью формы ниже.")
    else:
        # Заголовок таблицы
        hc = st.columns([2, 3, 2, 2, 2, 2, 1])
        for col, lbl in zip(hc, ["№ партии", "Название", "Всего (шт)",
                                  "Финал станки", "Финал ОПТА ★", "Создана", ""]):
            col.markdown(f"**{lbl}**")
        st.divider()

        for b in batches:
            tq  = b["total_qty"]
            fl  = b["final_lathe"]
            fo  = b["final_opta"]
            pct_l = f"{fl/tq*100:.0f}%" if tq > 0 else "—"
            pct_o = f"{fo/tq*100:.0f}%" if tq > 0 else "—"
            rc = st.columns([2, 3, 2, 2, 2, 2, 1])
            rc[0].markdown(f"`{b['batch_number']}`")
            rc[1].markdown(b["batch_name"] or "—")
            rc[2].markdown(f"{tq:,}" if tq else "—")
            rc[3].markdown(f"{fl:,} шт ({pct_l})")
            rc[4].markdown(f"{fo:,} шт ({pct_o})")
            rc[5].markdown((b["created_at"] or "")[:10])
            # Кнопка перехода к прогрессу
            if rc[6].button("📦", key=f"goto_bp_{b['batch_number']}",
                            help=f"Открыть прогресс партии «{b['batch_number']}»"):
                st.session_state["batch_progress_select"] = b["batch_number"]
                st.session_state["nav_goto"] = "batch"
                st.rerun()

        st.caption("★ Финал ОПТА = общий прогресс завершения партии  |  📦 = открыть прогресс партии")

    st.divider()

    if role not in ("admin",):
        st.info("👁 Создание, редактирование и удаление партий доступно только администратору.")
        return

    # ── Б) Создание новой партии ──────────────────────────────────────
    with st.expander("➕ Создать новую партию", expanded=not batches):
        with st.form("create_batch_form", clear_on_submit=True):
            cb1, cb2, cb3 = st.columns([2, 3, 2])
            new_bn    = cb1.text_input("№ партии *")
            new_name  = cb2.text_input("Название партии *")
            new_total = cb3.number_input("Всего в партии (шт) *", min_value=1, step=1)
            new_notes = st.text_input("Примечание")
            if st.form_submit_button("Создать партию", type="primary"):
                require_not_viewer()
                if not new_bn.strip():
                    st.error("Укажите номер партии.")
                elif not new_name.strip():
                    st.error("Укажите название партии.")
                else:
                    ok = create_batch(new_bn.strip(), new_name, int(new_total), new_notes)
                    if ok:
                        st.success(f"✅ Партия «{new_bn.strip()}» создана.")
                        st.rerun()
                    else:
                        st.error(f"Партия с номером «{new_bn.strip()}» уже существует.")

    st.divider()

    if not batches:
        return

    # ── В) Редактирование партии ──────────────────────────────────────
    with st.expander("✏️ Редактировать партию"):
        st.caption(
            "Номер партии изменить нельзя (если по ней есть записи выпуска). "
            "Можно изменить: название, количество, примечание."
        )
        bn_options = [b["batch_number"] for b in batches]
        edit_bn = st.selectbox("Выберите партию для редактирования",
                               options=bn_options, key="edit_batch_sel")
        edit_b  = next((b for b in batches if b["batch_number"] == edit_bn), None)
        if edit_b:
            has_records = edit_b["record_count"] > 0
            with st.form("edit_batch_form", clear_on_submit=False):
                ec1, ec2, ec3 = st.columns([3, 2, 3])
                e_name  = ec1.text_input("Название партии", value=edit_b["batch_name"] or "")
                e_total = ec2.number_input("Всего (шт)", min_value=1, step=1,
                                           value=max(1, edit_b["total_qty"] or 1))
                e_notes = ec3.text_input("Примечание", value=edit_b["notes"] or "")
                if has_records:
                    st.info(f"ℹ️ По партии «{edit_bn}» есть {edit_b['record_count']} записей выпуска — "
                            "номер партии изменить нельзя.")
                if st.form_submit_button("💾 Сохранить изменения", type="primary"):
                    require_not_viewer()
                    update_batch(edit_b["id"], e_name, int(e_total), e_notes)
                    st.success(f"✅ Партия «{edit_bn}» обновлена.")
                    st.rerun()

    st.divider()

    # ── Г) Удаление партии ────────────────────────────────────────────
    with st.expander("🗑 Удалить партию"):
        st.caption("Удаление возможно только если по партии НЕТ записей выпуска.")
        del_bn = st.selectbox("Выберите партию для удаления",
                              options=bn_options, key="del_batch_sel")
        del_b  = next((b for b in batches if b["batch_number"] == del_bn), None)
        if del_b:
            if del_b["record_count"] > 0:
                st.error(
                    f"❌ Нельзя удалить партию «{del_bn}»: "
                    f"по ней существует {del_b['record_count']} записей выпуска. "
                    "Сначала удалите все связанные записи в «📋 Истории»."
                )
            else:
                with st.form("delete_batch_form", clear_on_submit=True):
                    st.warning(f"⚠️ Удалить партию **«{del_bn}»**? Действие необратимо.")
                    if st.form_submit_button("🗑 Подтвердить удаление", type="primary"):
                        require_not_viewer()
                        ok, msg = delete_batch_safe(del_bn)
                        if ok:
                            st.success(f"✅ Партия «{del_bn}» удалена.")
                            st.rerun()
                        else:
                            st.error(msg)


def page_batch_progress():
    """
    Страница «Прогресс партии».

    Бизнес-логика прогресса:
    ─────────────────────────
    Этапы партии идут ПОСЛЕДОВАТЕЛЬНО:
      1. Выпуск на обычных станках (установы)
      2. Финальный выпуск станков (завершение станочного этапа)
      3. Выпуск через рабочие центры ОПТА
      4. Финальный выпуск ОПТА — окончательное завершение партии

    Поэтому НЕЛЬЗЯ суммировать финал станков + финал ОПТА в один прогресс.
    Общий progress bar считается ТОЛЬКО по «финальный выпуск ОПТА» (is_work_center=1, is_final_release=1).
    Финал станков показывается отдельно как промежуточный показатель.
    """
    st.title("📦 Прогресс партии")

    batch_numbers = all_batch_numbers()
    if not batch_numbers:
        st.info("📭 Нет партий. Создайте партию на странице «📋 Партии» или внесите выпуск с номером партии.")
        return

    # Кнопка возврата к списку партий
    if st.button("← К списку партий", key="back_to_batches"):
        st.session_state["nav_goto"] = "batches"
        st.rerun()

    # ── Автовыбор партии из session_state (переход с кнопки «📦» в «Партиях») ──
    # session_state["batch_progress_select"] устанавливается кнопкой на стр. «Партии».
    # st.selectbox с этим key подхватывает значение автоматически.
    preselect = st.session_state.get("batch_progress_select", "")
    # Проверяем валидность — партия может быть удалена после перехода
    if preselect and preselect not in batch_numbers:
        st.warning(f"⚠️ Партия «{preselect}» не найдена или была удалена.")
        st.session_state["batch_progress_select"] = ""
        preselect = ""

    options    = [""] + batch_numbers
    sel_index  = options.index(preselect) if preselect in options else 0

    sel_bn = st.selectbox(
        "Выберите номер партии",
        options=options,
        index=sel_index,
        format_func=lambda x: "— выберите партию —" if x == "" else x,
        key="batch_progress_select",
    )
    if not sel_bn:
        st.info("Выберите партию из списка для просмотра прогресса.")
        return

    # ── Данные партии из batches ───────────────────────────────────────
    bm = get_batch(sel_bn)
    total_qty  = bm["total_qty"]  if bm else 0
    batch_name = bm["batch_name"] if bm else ""
    batch_notes= bm["notes"]      if bm else ""
    created    = bm["created_at"][:10] if bm and bm["created_at"] else "—"

    # ── Записи выпуска по партии ───────────────────────────────────────
    rows = q("""
        SELECT p.id, p.date,
               COALESCE(p.stage_name, '—') AS stage_name,
               p.produced_qty,
               COALESCE(p.is_final_release, 0) AS is_final_release,
               COALESCE(m.is_work_center, 0)   AS is_work_center,
               m.name  AS machine,
               o.name  AS operator,
               p.notes
        FROM production p
        LEFT JOIN machines  m ON m.id = p.machine_id
        LEFT JOIN operators o ON o.id = p.operator_id
        WHERE p.batch_number = ?
          AND COALESCE(p.record_type, 'production') = 'production'
        ORDER BY p.date, p.id
    """, (sel_bn,))

    # ── Агрегаты (раздельно, не суммируются) ──────────────────────────
    lathe_rows       = [r for r in rows if r["is_work_center"] == 0]
    opta_rows        = [r for r in rows if r["is_work_center"] == 1]

    lathe_total      = sum(r["produced_qty"] for r in lathe_rows)
    lathe_final      = sum(r["produced_qty"] for r in lathe_rows if r["is_final_release"] == 1)
    opta_total       = sum(r["produced_qty"] for r in opta_rows)
    opta_final       = sum(r["produced_qty"] for r in opta_rows  if r["is_final_release"] == 1)

    # Прогресс партии = только финальный ОПТА
    progress_qty     = opta_final
    remainder        = max(0, total_qty - progress_qty) if total_qty > 0 else None

    # ── А) Карточка партии ─────────────────────────────────────────────
    st.markdown(f"""
<div style="background:#1e2130;border:1px solid #2e3150;border-radius:12px;padding:18px 22px;margin-bottom:16px;">
  <div style="color:#56cfe1;font-size:1.2rem;font-weight:700;margin-bottom:8px;">
    📦 Партия: <b>{sel_bn}</b>
  </div>
  <div style="color:#e0e0f5;font-size:0.95rem;line-height:1.7;">
    {'<b>Название:</b> ' + batch_name + ' &nbsp;|&nbsp; ' if batch_name else ''}
    <b>Всего в партии:</b> {f'{total_qty:,} шт' if total_qty else '—'} &nbsp;|&nbsp;
    <b>Создана:</b> {created}
    {'<br><b>Примечание:</b> ' + batch_notes if batch_notes else ''}
  </div>
</div>
""", unsafe_allow_html=True)

    # Метрики — четыре карточки
    ka, kb, kc, kd = st.columns(4)
    ka.metric("Всего в партии",              f"{total_qty:,} шт" if total_qty else "—")
    kb.metric("🏁 Финал станков",
              f"{lathe_final:,} шт",
              f"{lathe_final/total_qty*100:.1f}%" if total_qty > 0 else None,
              help="Выпуск с галочкой «Финальный» на обычных станках — завершение станочного этапа")
    kc.metric("🏁 Финал ОПТА",
              f"{opta_final:,} шт",
              f"{opta_final/total_qty*100:.1f}%" if total_qty > 0 else None,
              help="Выпуск с галочкой «Финальный» на рабочих центрах — окончательное завершение партии")
    kd.metric("Остаток (по ОПТА)",
              f"{remainder:,} шт" if remainder is not None else "н/д",
              help="Остаток = Всего − Финал ОПТА")

    # Progress bar — ТОЛЬКО по финальному ОПТА
    st.markdown("#### 🔄 Общий прогресс партии (по финальному выпуску ОПТА)")
    if total_qty > 0:
        pct_done = min(100.0, opta_final / total_qty * 100)
        st.progress(pct_done / 100,
                    text=f"Финал ОПТА: {opta_final:,} / {total_qty:,} шт = {pct_done:.1f}%")
        if opta_final == 0 and lathe_final > 0:
            st.info(
                f"ℹ️ Станочный этап завершён ({lathe_final:,} шт), "
                "но финальный выпуск ОПТА ещё не зафиксирован.")
    else:
        st.warning("Общее количество партии не задано — прогресс недоступен.")

    if not rows:
        st.info("По данной партии записей выпуска пока нет.")
        return

    st.divider()

    # ── Б) Таблица этапов ─────────────────────────────────────────────
    st.markdown("### 📊 Этапы партии")
    st.caption(
        "Каждая строка — одна запись выпуска. "
        "Этапы идут последовательно: станки → ОПТА. "
        "Проценты считаются от общего количества партии."
    )

    stage_rows = []
    for r in rows:
        pct = round(r["produced_qty"] / total_qty * 100, 1) if total_qty > 0 else None
        fin_lbl = "✅ Финал" if r["is_final_release"] else "—"
        ctype   = "🏭 ОПТА" if r["is_work_center"] else "⚙️ Станок"
        stage_rows.append({
            "Дата":             r["date"],
            "Центр":            ctype,
            "Этап / операция":  r["stage_name"] or "—",
            "Станок / РЦ":      r["machine"] or "—",
            "Выпущено (шт)":    r["produced_qty"],
            "% от партии":      f"{pct}%" if pct is not None else "—",
            "Финальный":        fin_lbl,
            "Оператор":         r["operator"] or "—",
            "Примечание":       r["notes"] or "",
        })

    st.dataframe(pd.DataFrame(stage_rows), use_container_width=True, hide_index=True,
                 column_config={
                     "Выпущено (шт)": st.column_config.NumberColumn(format="%d шт"),
                 })

    st.divider()

    # ── В) Сводные показатели (раздельно, без суммирования) ───────────
    st.markdown("### 📋 Сводные показатели")

    def pct_lbl(qty):
        if total_qty > 0:
            return f"{qty:,} шт  ({qty/total_qty*100:.1f}%)"
        return f"{qty:,} шт"

    agg_data = [
        {"Этап":     "⚙️ Станки — всего выпущено",        "Кол-во": pct_lbl(lathe_total)},
        {"Этап":     "⚙️ Станки — 🏁 финальный выпуск",   "Кол-во": pct_lbl(lathe_final)},
        {"Этап":     "🏭 ОПТА — всего выпущено",           "Кол-во": pct_lbl(opta_total)},
        {"Этап":     "🏭 ОПТА — 🏁 финальный выпуск",      "Кол-во": pct_lbl(opta_final)},
    ]
    st.caption("⚠️ Финал станков и финал ОПТА НЕ суммируются — это последовательные этапы одной партии.")
    st.dataframe(pd.DataFrame(agg_data), use_container_width=True, hide_index=True)

    st.divider()

    # ── Г) Графики по этапам ──────────────────────────────────────────
    st.markdown("### 📈 Графики по этапам")

    agg_map: dict = {}
    for r in rows:
        key = (
            r["stage_name"] or "—",
            "ОПТА" if r["is_work_center"] else "Станок",
            bool(r["is_final_release"]),
        )
        agg_map[key] = agg_map.get(key, 0) + r["produced_qty"]

    chart_rows = []
    for (stage, ctype, fin), qty in sorted(agg_map.items(), key=lambda x: x[0][0]):
        fin_tag = " ★фин." if fin else ""
        chart_rows.append({
            "Этап":        f"{stage}{fin_tag}",
            "Штук":        qty,
            "% от партии": round(qty / total_qty * 100, 1) if total_qty > 0 else 0,
            "Тип":         ctype,
            "Финальный":   fin,
        })
    df_chart = pd.DataFrame(chart_rows)

    if df_chart.empty:
        st.info("Нет данных для графиков.")
        return

    color_map = {"Станок": "#7c6af7", "ОПТА": "#56cfe1"}
    gc1, gc2 = st.columns(2)
    with gc1:
        fig1 = px.bar(df_chart, x="Этап", y="Штук", color="Тип",
                      title="Выпуск по этапам (штук)",
                      template="plotly_dark", color_discrete_map=color_map,
                      text="Штук", barmode="group")
        fig1.update_traces(textposition="outside")
        fig1.update_layout(paper_bgcolor="#0f1117", plot_bgcolor="#1e2130",
                           font_color="#ffffff", xaxis=dict(tickangle=-30))
        st.plotly_chart(fig1, use_container_width=True)
    with gc2:
        fig2 = px.bar(df_chart, x="Этап", y="% от партии", color="Тип",
                      title="Выпуск по этапам (% от партии)",
                      template="plotly_dark", color_discrete_map=color_map,
                      text="% от партии", barmode="group")
        fig2.update_traces(textposition="outside", texttemplate="%{text}%")
        fig2.update_layout(paper_bgcolor="#0f1117", plot_bgcolor="#1e2130",
                           font_color="#ffffff", xaxis=dict(tickangle=-30),
                           yaxis=dict(ticksuffix="%"))
        st.plotly_chart(fig2, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    init_db()

    if not HAS_AUTH:
        st.error("❌ streamlit-authenticator не установлен. Установите зависимости из requirements.txt.")
        st.stop()

    if not Path(CONFIG_PATH).exists():
        st.error(f"❌ Файл {CONFIG_PATH} не найден. Убедитесь, что он примонтирован в контейнер.")
        st.stop()

    cfg = load_config()

    # Инициализируем аутентификатор
    authenticator = stauth.Authenticate(
        cfg["credentials"],
        cfg["cookie"]["name"],
        cfg["cookie"]["key"],
        cfg["cookie"]["expiry_days"],
    )

    # Форма входа
    try:
        authenticator.login()
    except Exception as e:
        st.error(f"Ошибка аутентификации: {e}")
        st.stop()

    auth_status = st.session_state.get("authentication_status")
    username    = st.session_state.get("username", "")

    if auth_status is False:
        st.error("❌ Неверный логин или пароль.")
        st.stop()
    elif auth_status is None:
        st.warning("⚠️ Введите логин и пароль.")
        st.stop()

    # Авторизован
    role = get_role(username)
    st.session_state["role"] = role

    # ── Sidebar ───────────────────────────────────────────────────────
    with st.sidebar:
        role_label = {"admin": "Администратор", "user": "Оператор", "viewer": "Наблюдатель"}.get(role, role)
        st.markdown(f"""
<div style="background:#2a2d40; border-radius:10px; padding:14px; margin-bottom:16px;">
  <div style="color:#56cfe1; font-weight:700; font-size:1.1rem;">⚙️ НТА-Контроль</div>
  <div style="color:#8888aa; font-size:0.85rem; margin-top:4px;">
    👤 {st.session_state.get('name', username)}<br>
    🔑 {role_label}
  </div>
</div>
""", unsafe_allow_html=True)

        pages_all = {
            "⚙️ Станки":            "machines",
            "📋 История":           "history",
            "📋 Партии":            "batches",
            "📦 Прогресс партии":   "batch",
        }
        pages_admin = {
            "👥 Персонал / Станки": "crud",
            "📊 Графики":           "charts",
            "💾 Экспорт CSV":       "export",
        }
        pages_viewer = {
            "📊 Графики":           "charts",
            "💾 Экспорт CSV":       "export",
        }

        all_pages = dict(pages_all)
        if role == "admin":
            all_pages.update(pages_admin)
        elif role == "viewer":
            all_pages.update(pages_viewer)

        # ── Навигация через session_state (поддерживает программный переход) ──
        # При нажатии «Открыть прогресс» на странице «Партии» устанавливается
        # st.session_state["nav_goto"] = "batch"  и вызывается st.rerun().
        # Здесь мы синхронизируем st.radio с этим флагом.
        page_keys  = list(all_pages.keys())
        page_vals  = list(all_pages.values())

        # Если был программный переход — применяем его
        _goto = st.session_state.pop("nav_goto", None)
        if _goto and _goto in page_vals:
            target_label = page_keys[page_vals.index(_goto)]
            st.session_state["_sidebar_page"] = target_label

        # Гарантируем, что текущее значение radio валидно
        _default_page = st.session_state.get("_sidebar_page", page_keys[0])
        if _default_page not in page_keys:
            _default_page = page_keys[0]

        page = st.radio(
            "Навигация",
            page_keys,
            index=page_keys.index(_default_page),
            label_visibility="collapsed",
            key="_sidebar_radio",
        )
        # Сохраняем выбор пользователя
        st.session_state["_sidebar_page"] = page

        st.divider()
        if role in ("admin", "viewer"):
            st.markdown("**Быстрая статистика**")
            stats = q("""
                SELECT status, COUNT(*) as cnt FROM machines GROUP BY status
            """)
            for s in stats:
                label = STATUS_LABELS.get(s["status"], s["status"])
                st.markdown(f"{label}: **{s['cnt']}**")
            st.divider()

        authenticator.logout("🚪 Выйти", "sidebar")

    # ── Роутинг ───────────────────────────────────────────────────────
    page_key = all_pages[page]
    if page_key == "machines":
        page_machines(role)
    elif page_key == "history":
        page_history(role)
    elif page_key == "batches":
        page_batches(role)
    elif page_key == "batch":
        page_batch_progress()
    elif page_key == "crud":
        page_admin_crud()
    elif page_key == "charts":
        page_charts()
    elif page_key == "export":
        page_export()


if __name__ == "__main__":
    main()
