"""
=============================================================================
  НТА-Контроль — система производственного учёта
  Streamlit Web App
  Роли: admin (полный доступ), user (ввод выпуска + статусы), viewer (только просмотр)
=============================================================================
"""

import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import yaml
import tech
import plan
import io
import os
import csv
import html
import json
from contextlib import contextmanager
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
    page_title="НТА-Контроль",
    page_icon="🏭",
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
/* кнопки по data-testid: кнопка с подсказкой (help=) обёрнута в tooltip-div, и «.stButton > button» её не ловит */
button[data-testid="baseButton-secondary"],
button[data-testid="baseButton-secondaryFormSubmit"] {
    background: #252840 !important;
    color: #e0e0f5 !important;
    border: 1px solid #3a3d5c !important;
    border-radius: 6px !important;
    font-weight: 600 !important;
}
button[data-testid="baseButton-secondary"] p,
button[data-testid="baseButton-secondaryFormSubmit"] p { color: #e0e0f5 !important; }
button[data-testid="baseButton-primary"],
button[data-testid="baseButton-primaryFormSubmit"] {
    background: #7c6af7 !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 6px !important;
    font-weight: 600 !important;
}
button[data-testid="baseButton-primary"] p,
button[data-testid="baseButton-primaryFormSubmit"] p { color: #ffffff !important; }
button[data-testid^="baseButton"]:disabled { opacity: 0.45 !important; }
/* всплывающие меню (st.popover) и кнопки форм: без правил были светлыми с белым текстом — невидимы */
[data-testid="stPopover"] button,
.stFormSubmitButton > button:not([kind="primaryFormSubmit"]) {
    background: #252840 !important;
    color: #e0e0f5 !important;
    border: 1px solid #3a3d5c !important;
    border-radius: 6px !important;
    font-weight: 600 !important;
}
[data-testid="stPopover"] button p,
[data-testid="stPopover"] button span,
.stFormSubmitButton > button p { color: #e0e0f5 !important; }
.stFormSubmitButton > button[kind="primaryFormSubmit"] {
    background: #7c6af7 !important; color: #ffffff !important; border: none !important;
    border-radius: 6px !important; font-weight: 600 !important;
}
.stFormSubmitButton > button[kind="primaryFormSubmit"] p { color: #ffffff !important; }
[data-testid="stPopoverBody"] {
    background: #1a1d2e !important;
    border: 1px solid #3a3d5c !important;
}
[data-testid="stPopoverBody"] > div { background: transparent !important; }   /* внутренняя светлая подложка */
[data-testid="stPopoverBody"] p, [data-testid="stPopoverBody"] label { color: #e0e0f5 !important; }
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
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn

@contextmanager
def tx():
    """Одна транзакция на несколько запросов: commit при успехе, rollback при ошибке."""
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def audit(conn, action: str, table: str, record_id, old=None, new=None):
    """Пишет запись в журнал изменений (кто, когда, что было и что стало)."""
    conn.execute("""
        INSERT INTO audit_log (changed_at, username, action, table_name, record_id, old_data, new_data)
        VALUES (?,?,?,?,?,?,?)
    """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
          st.session_state.get("username", ""), action, table, record_id,
          json.dumps(old, ensure_ascii=False, default=str) if old is not None else None,
          json.dumps(new, ensure_ascii=False, default=str) if new is not None else None))

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
    # end_key — какой торец фитинга делался на этом установе (tube:12M, male:8N …); для статистики по торцам
    if "end_key" not in existing_cols:
        c.execute("ALTER TABLE production ADD COLUMN end_key TEXT DEFAULT NULL")

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
    # archive_state — ручная отметка архива: NULL = авто, 'archived' / 'active' = вручную
    if "archive_state" not in batches_cols:
        c.execute("ALTER TABLE batches ADD COLUMN archive_state TEXT DEFAULT NULL")
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

    # ── Динамические журналы ──────────────────────────────────────────
    # journals          — метаданные журнала
    # journal_columns   — описание колонок (тип, порядок, настройки)
    # journal_entries   — строки записей
    # journal_entry_values — значения по колонкам (EAV-схема)
    c.execute("""
        CREATE TABLE IF NOT EXISTS journals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            description TEXT DEFAULT '',
            created_by  TEXT DEFAULT '',
            created_at  TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS journal_columns (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            journal_id   INTEGER NOT NULL,
            col_order    INTEGER NOT NULL DEFAULT 0,
            col_name     TEXT NOT NULL,
            col_type     TEXT NOT NULL,
            col_options  TEXT DEFAULT '',
            col_unit     TEXT DEFAULT '',
            FOREIGN KEY (journal_id) REFERENCES journals(id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS journal_entries (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            journal_id  INTEGER NOT NULL,
            created_by  TEXT DEFAULT '',
            created_at  TEXT NOT NULL,
            FOREIGN KEY (journal_id) REFERENCES journals(id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS journal_entry_values (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id   INTEGER NOT NULL,
            column_id  INTEGER NOT NULL,
            value_text TEXT DEFAULT '',
            FOREIGN KEY (entry_id)  REFERENCES journal_entries(id),
            FOREIGN KEY (column_id) REFERENCES journal_columns(id)
        )
    """)

    # Журнал изменений: правки и удаления записей (old_data/new_data — JSON)
    c.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            changed_at  TEXT NOT NULL,
            username    TEXT DEFAULT '',
            action      TEXT NOT NULL,
            table_name  TEXT NOT NULL,
            record_id   INTEGER,
            old_data    TEXT,
            new_data    TEXT
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

    # Таблицы технологического модуля (справочники и журналы tech_*)
    tech.init_tables(c)
    # План загрузки станков (plan_*): режим смен, календарь, позиции плана
    plan.init_tables(c)

    conn.commit()
    conn.close()

@st.cache_resource
def init_db_once():
    """Миграции и проверка схемы — один раз на процесс, а не на каждый клик."""
    init_db()
    return True

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

# ── Права доступа ──────────────────────────────────────────────────────────
# Роль — набор прав по умолчанию; master может задать пользователю свой набор (config.yml → perms).
# master всегда имеет все права (защита от потери доступа к управлению пользователями).
PERM_GROUPS = [
    ("Страницы", [
        ("page:machines", "⚙️ Станки"), ("page:history", "📋 История"), ("page:batches", "📋 Партии"),
        ("page:batch", "📦 Прогресс партии"), ("page:journals", "📓 Журналы"),
        ("page:crud", "👥 Персонал / Станки"), ("page:charts", "📊 Графики"), ("page:export", "💾 Экспорт CSV"),
        ("page:tech", "🛠 Технология"), ("page:plan", "📅 План станков"),
    ]),
    ("Действия", [
        ("records.add", "Вносить выпуск и ремонт, менять статус станков"),
        ("records.edit", "Редактировать и удалять записи выпуска"),
        ("batches.manage", "Создавать, редактировать, архивировать партии"),
        ("journals.add", "Добавлять записи в журналы"),
        ("journals.manage", "Создавать журналы, менять их структуру, удалять записи"),
        ("users.manage", "Пользователи и права (только master)"),
    ]),
]
ALL_PERMS = [k for _g, items in PERM_GROUPS for k, _l in items]
PERM_LABEL = {k: l for _g, items in PERM_GROUPS for k, l in items}
_BASE_PAGES = {"page:machines", "page:history", "page:batches", "page:batch", "page:journals"}
ROLE_PRESETS = {
    "viewer": _BASE_PAGES | {"page:charts", "page:export"},
    "user":   _BASE_PAGES | {"records.add", "journals.add"},
    "admin":  set(ALL_PERMS) - {"users.manage"},
    "master": set(ALL_PERMS),
}
ROLE_LABELS = {"master": "Мастер (суперадмин)", "admin": "Администратор", "user": "Оператор", "viewer": "Наблюдатель"}


def user_perms(user: dict) -> set:
    """Права пользователя из config.yml: свой набор (perms) или права роли; master — всегда все."""
    role = (user or {}).get("role", "user")
    if role == "master":
        return set(ALL_PERMS)
    own = (user or {}).get("perms")
    perms = set(own) if isinstance(own, list) else set(ROLE_PRESETS.get(role, ROLE_PRESETS["user"]))
    return {p for p in perms if p in ALL_PERMS and p != "users.manage"}


def can(perm: str) -> bool:
    """Есть ли право у текущего пользователя (без загруженных прав — по роли, как раньше)."""
    perms = st.session_state.get("perms")
    if perms is None:
        perms = ROLE_PRESETS.get(st.session_state.get("role", "user"), set())
    return perm in perms


def require_perm(perm: str):
    if not can(perm):
        st.error(f"⛔ Доступ запрещён: нужно право «{PERM_LABEL.get(perm, perm)}».")
        st.stop()


def require_admin():
    """Останавливает выполнение без права на страницу «Персонал / Станки» (раньше — роль admin)."""
    require_perm("page:crud")

def require_not_viewer():
    """Останавливает выполнение без права вносить данные (раньше — роль viewer)."""
    if not (can("records.add") or can("records.edit") or can("batches.manage")):
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
    with tx() as conn:
        cur = conn.execute("""
            INSERT OR IGNORE INTO batches (batch_number, batch_name, total_qty, notes, created_at)
            VALUES (?,?,?,?,?)
        """, (batch_number.strip(), batch_name.strip(), int(total_qty), notes.strip(), now_str))
        # rowcount == 0 → партию с таким номером успели создать параллельно
        return cur.rowcount == 1

def update_batch(batch_id: int, batch_name: str, total_qty: int, notes: str):
    """Обновляет название, количество и примечание партии. Номер не меняется."""
    with tx() as conn:
        old = conn.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
        conn.execute("""
            UPDATE batches SET batch_name=?, total_qty=?, notes=? WHERE id=?
        """, (batch_name.strip(), int(total_qty), notes.strip(), batch_id))
        audit(conn, "update", "batches", batch_id, dict(old) if old else None,
              {"batch_name": batch_name.strip(), "total_qty": int(total_qty), "notes": notes.strip()})

def delete_batch_safe(batch_number: str):
    """
    Удаляет партию, если по ней нет записей выпуска.
    Возвращает (True, '') при успехе или (False, причина) при ошибке.
    """
    with tx() as conn:
        cnt = conn.execute("SELECT COUNT(*) FROM production WHERE batch_number=?",
                           (batch_number,)).fetchone()[0]
        if cnt > 0:
            return False, f"Нельзя удалить партию: по ней существует {cnt} записей выпуска."
        old = conn.execute("SELECT * FROM batches WHERE batch_number=?", (batch_number,)).fetchone()
        conn.execute("DELETE FROM batches WHERE batch_number=?", (batch_number,))
        if old:
            audit(conn, "delete", "batches", old["id"], dict(old))
    return True, ""

def all_batch_numbers():
    """Возвращает все номера партий из таблицы batches, отсортированные."""
    rows = q("SELECT batch_number FROM batches ORDER BY batch_number")
    return [r["batch_number"] for r in rows]

def all_batches():
    """Возвращает все партии с краткой статистикой выпуска."""
    return q("""
        SELECT b.id, b.batch_number, b.batch_name, b.total_qty, b.notes, b.created_at,
               b.archive_state,
               COALESCE(SUM(CASE WHEN p.is_final_release=1 AND COALESCE(m.is_work_center,0)=0
                                 THEN p.produced_qty ELSE 0 END), 0) AS final_lathe,
               COALESCE(SUM(CASE WHEN p.is_final_release=1 AND COALESCE(m.is_work_center,0)=1
                                 THEN p.produced_qty ELSE 0 END), 0) AS final_opta,
               COUNT(p.id) AS record_count
        FROM batches b
        LEFT JOIN production p ON p.batch_number = b.batch_number
                               AND COALESCE(p.record_type,'production') = 'production'
        LEFT JOIN machines m ON m.id = p.machine_id
        GROUP BY b.id, b.batch_number, b.batch_name, b.total_qty, b.notes, b.created_at,
                 b.archive_state
        ORDER BY b.created_at DESC
    """)

# ── Архив партий ───────────────────────────────────────────────────────────
# Автоправило: партия закрыта, когда финальный выпуск ОПТА достиг плана.
# batches.archive_state хранит только ручное отклонение от автоправила:
#   NULL — авто, 'archived' — в архиве вручную (например, партия без ОПТА),
#   'active' — в работе вручную, хотя по автоправилу закрыта.

def batch_auto_closed(total_qty, final_opta) -> bool:
    return (total_qty or 0) > 0 and (final_opta or 0) >= total_qty

def batch_is_archived(archive_state, total_qty, final_opta) -> bool:
    if archive_state == "archived":
        return True
    if archive_state == "active":
        return False
    return batch_auto_closed(total_qty, final_opta)

def set_batch_archived(batch_number: str, archived: bool, auto_closed: bool):
    """Архивирует / возвращает партию. Если желаемое совпадает с автоправилом,
    ручная отметка снимается (NULL), чтобы партия снова следовала правилу."""
    if archived:
        state = None if auto_closed else "archived"
    else:
        state = "active" if auto_closed else None
    with tx() as conn:
        old = conn.execute("SELECT id, archive_state FROM batches WHERE batch_number=?",
                           (batch_number,)).fetchone()
        conn.execute("UPDATE batches SET archive_state=? WHERE batch_number=?",
                     (state, batch_number))
        if old:
            audit(conn, "archive" if archived else "unarchive", "batches", old["id"],
                  {"archive_state": old["archive_state"]}, {"archive_state": state})

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

# ── Фильтр «гайки» ─────────────────────────────────────────────────────────
# Партия считается гайками, если её название начинается с одного из префиксов
# (FNN-12M-S, DN-8-S, FNUBN-10M-S, …). Пополняйте список здесь.
NUT_PREFIXES = ("FNN", "DN", "FNUBN", "DUBN")
NUT_MODES = {"all": "Все", "no_nuts": "Без гаек", "only_nuts": "Только гайки"}

# 1, если запись относится к партии-гайке. Название берётся из batches,
# иначе из копии в production.batch. Нужен LEFT JOIN batches b ON b.batch_number = p.batch_number.
NUT_SQL = "(" + " OR ".join(
    f"UPPER(LTRIM(COALESCE(NULLIF(b.batch_name, ''), p.batch, ''))) LIKE '{px}%'"
    for px in NUT_PREFIXES) + ")"

def nut_filter_sql(mode: str) -> str:
    """Условие WHERE для режима фильтра. Ремонты к гайкам не относятся."""
    is_nut = f"(COALESCE(p.record_type, 'production') = 'production' AND {NUT_SQL})"
    if mode == "no_nuts":
        return f" AND NOT {is_nut}"
    if mode == "only_nuts":
        return f" AND {is_nut}"
    return ""

def nut_filter_widget(container, key: str) -> str:
    """Переключатель «Все / Без гаек / Только гайки». Выбор общий для страниц.

    Начальное значение задаётся через session_state, а не через index=:
    в Streamlit 1.35 смена параметра виджета меняет его id и сбрасывает выбор.
    """
    if key not in st.session_state:
        st.session_state[key] = st.session_state.get("nut_mode", "all")
    mode = container.radio(
        f"🔩 Гайки ({' / '.join(NUT_PREFIXES)})", list(NUT_MODES),
        format_func=NUT_MODES.get, horizontal=True, key=key,
        help="По названию партии: начинается с " + " или ".join(NUT_PREFIXES) +
             ". Действует на станки и рабочие центры.")
    st.session_state["nut_mode"] = mode
    return mode

def nut_summary(mode: str, date_from: str, date_to: str):
    """Сводка: какие партии-гайки попали в период и что с ними делает фильтр."""
    rows = q(f"""
        SELECT p.batch_number AS "№ партии",
               COALESCE(NULLIF(b.batch_name, ''), p.batch, '') AS "Название",
               SUM(p.produced_qty) AS "Выпущено (шт)"
        FROM production p
        LEFT JOIN batches b ON b.batch_number = p.batch_number
        WHERE p.date BETWEEN ? AND ?
          AND COALESCE(p.record_type, 'production') = 'production'
          AND {NUT_SQL}
        GROUP BY p.batch_number
        ORDER BY 3 DESC
    """, (date_from, date_to))
    action = {"all": "учитываются", "no_nuts": "исключены",
              "only_nuts": "показаны только они"}[mode]
    total = sum(r["Выпущено (шт)"] or 0 for r in rows)
    with st.expander(f"🔩 Гайки за период: {len(rows)} партий, {total:,} шт — {action}"):
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.caption("За выбранный период выпуска гаек нет.")

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
    if not can("records.add"):
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
                with tx() as conn:
                    conn.execute("UPDATE machines SET status=?, notes=? WHERE id=?",
                                 (ch_status, ch_notes, ch_machine))
                    conn.execute("""
                        INSERT INTO machine_status_log (machine_id, status, changed_by, changed_at)
                        VALUES (?,?,?,?)
                    """, (ch_machine, ch_status, username, now_str))
                st.success(f"✅ Статус обновлён на «{STATUS_LABELS.get(ch_status, ch_status)}»")
                st.rerun()

    st.divider()

    # ── Внести запись (Выпуск или Ремонт) — User + Admin ──────────────
    if not can("records.add"):
        st.info("👁 Режим просмотра — внесение записей недоступно.")
        return

    st.markdown("### ➕ Внести запись")

    # Сообщение об успешной записи переживает st.rerun() после сохранения
    _flash = st.session_state.pop("pf_flash", None)
    if _flash:
        st.success(_flash)

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

        # ═══════════════════════════════════════════════════════════════
        #  ФОРМА ВНЕСЕНИЯ ВЫПУСКА — реализована на обычных виджетах
        #  (без st.form), что позволяет реактивно менять поле «Этап»
        #  и показывать подтверждение ДО нажатия кнопки сохранения.
        #
        #  Ключи session_state используют префикс PF = "pf<поколение>_".
        #  После успешного INSERT поколение увеличивается: виджеты получают
        #  новые ключи и создаются пустыми. (Простое удаление ключей из
        #  session_state в Streamlit 1.35 не очищает значения в браузере.)
        # ═══════════════════════════════════════════════════════════════
        # Выбрали другую партию — форма с нуля (станок, оператор, количество… переносятся только
        # между записями одной партии, см. сброс после сохранения)
        _gen = st.session_state.setdefault("pf_gen", 0)
        _prev_bn = st.session_state.get("pf_batch_prev")
        if _prev_bn and _prev_bn != batch_no_stripped:  # была выбрана другая партия (не «пусто → партия»)
            for _k in [k for k in st.session_state if k.startswith(f"pf{_gen}_")]:
                del st.session_state[_k]
            st.session_state["pf_gen"] = _gen + 1
        st.session_state["pf_batch_prev"] = batch_no_stripped
        PF = f"pf{st.session_state['pf_gen']}_"

        def normalize_stage(s: str) -> str:
            import re as _re
            return _re.sub(r"\s+", " ", s.strip())

        # ── Строка 1: Станок, Оператор, Дата, Выпущено ─────────────────
        r1c1, r1c2, r1c3, r1c4 = st.columns([3, 3, 2, 2])
        sel_machine = r1c1.selectbox(
            "Станок / РЦ*",
            options=[m["id"] for m in machines_full],
            format_func=machine_label,
            key=f"{PF}machine",
        )
        sel_operator = r1c2.selectbox(
            "Оператор",
            options=[0] + [o["id"] for o in operators],
            format_func=lambda x: op_map[x],
            key=f"{PF}operator",
        )
        # дата могла быть перенесена из прошлой записи (см. сброс после сохранения) — тогда без value=,
        # иначе Streamlit предупреждает о двойном задании значения
        prod_date    = r1c3.date_input("Дата*", key=f"{PF}date",
                                       **({} if f"{PF}date" in st.session_state else {"value": date.today()}))
        produced_qty = r1c4.number_input(
            "Выпущено (шт)", min_value=0, step=1, key=f"{PF}qty",
            help="0 = наладка без выпуска / тестовый прогон")

        # ── Строка 2: Наладка, Фактическое время ───────────────────────
        r2c1, r2c2 = st.columns([2, 3])
        setup_time     = r2c1.number_input(
            "Наладка (ч)", min_value=0.0, step=0.25, key=f"{PF}setup")
        actual_dur_min = r2c2.number_input(
            "Факт. время выпуска (мин)", min_value=0.0, step=1.0, value=0.0,
            key=f"{PF}act_min",
            help="Реально потраченное время в минутах. 0 — не заполнено.")

        # ── Тип выбранного оборудования (реактивно, текущий выбор) ────
        # selectbox выше уже обновил session_state[f"{PF}machine"] в этом rerun.
        sel_m_obj  = next((m for m in machines_full if m["id"] == sel_machine), None)
        is_wc      = bool(sel_m_obj["is_work_center"]) if sel_m_obj else False
        machine_nm = sel_m_obj["name"].strip() if sel_m_obj else ""

        # ── Поле «Этап» — полностью реактивное, ДО кнопки сохранения ──
        #
        #  Ключи session_state для поля этапа инициализируются ОДИН РАЗ:
        #  - при первом рендере формы (ключа нет в session_state);
        #  - при смене станка (is_wc изменился или изменилось machine_nm).
        #  После этого значение живёт в session_state и НЕ перезаписывается
        #  при rerun, вызванных чекбоксом «Финальный выпуск» или другими виджетами.
        #
        #  Почему раньше был баг:
        #  text_input без явного key опирался на позицию виджета в дереве.
        #  При клике на чекбокс Streamlit делал rerun, и если браузер не успел
        #  зафиксировать буферизованное значение поля — оно читалось как пустое.
        #  Теперь значение зеркалируется в session_state через key, и rerun
        #  не может его потерять: виджет восстанавливает значение из session_state.

        _stage_lathe_key  = f"{PF}stage_lathe"
        _stage_opta_key   = f"{PF}stage_opta"
        _machine_prev_key = f"{PF}machine_prev"

        # Определяем, сменился ли станок (нужно сбросить этап)
        _machine_prev = st.session_state.get(_machine_prev_key)
        _machine_changed = (_machine_prev is not None) and (_machine_prev != sel_machine)
        st.session_state[_machine_prev_key] = sel_machine

        if _machine_changed:
            # Станок сменился — сбрасываем поля этапа и флаги
            st.session_state.pop(_stage_lathe_key, None)
            st.session_state.pop(_stage_opta_key,  None)
            st.session_state.pop(f"{PF}stage_override", None)
            st.session_state.pop(f"{PF}stage_choice",   None)

        # Инициализируем значение поля для ОПТА только если ключ ещё не существует
        # (первый рендер или только что сменился станок).
        # Это гарантирует, что ввод пользователя не затирается при rerun чекбокса.
        if is_wc and _stage_opta_key not in st.session_state:
            st.session_state[_stage_opta_key] = machine_nm

        stage_confirmed = True    # разрешает/блокирует кнопку «Записать»
        confirmed_stage = ""      # итоговое значение этапа для INSERT
        end_choice = ""           # торец установа (235 / 2100), "" — не указан

        if not is_wc:
            # ── Станок ──────────────────────────────────────────────────
            sc1, _ = st.columns([3, 4])
            stage_input = sc1.text_input(
                "Этап / операция *",
                placeholder="1 установ, 2 установ…",
                key=_stage_lathe_key,
                help="⚠️ Обязательно для обычных станков.",
            )
            confirmed_stage = normalize_stage(stage_input)
            # Сброс ОПТА-флагов если переключились на станок
            st.session_state.pop(f"{PF}stage_choice", None)
            # Какой торец делается на этом установе — на станках, где фитинг делается по торцам (235, 2100)
            if machine_nm in tech.per_end_machines(q) and batch_no_stripped:
                _bname = (bm_record or {}).get("batch_name") or new_batch_name_val
                _ends = [e for e in (tech.parse_article(_bname).get("ends") or []) if e.get("kind")] if _bname else []
                if _ends:
                    _labels = {tech.end_key(e): tech.end_label(e) for e in _ends}
                    _opts = [""] + list(_labels)
                    _ek = f"{PF}end_{batch_no_stripped}_{sel_machine}"
                    if _ek not in st.session_state:  # по умолчанию — торец прошлой записи этой партии на этом станке
                        _prev = q("SELECT end_key FROM production WHERE batch_number=? AND machine_id=? "
                                  "AND COALESCE(end_key,'')<>'' ORDER BY id DESC LIMIT 1",
                                  (batch_no_stripped, sel_machine), fetch="one")
                        if _prev and _prev["end_key"] in _opts:
                            st.session_state[_ek] = _prev["end_key"]
                    ec1, _ = st.columns([3, 4])
                    end_choice = ec1.selectbox(
                        "Торец на этом установе", _opts, key=_ek,
                        format_func=lambda x: "— не указано —" if x == "" else _labels.get(x, x),
                        help="Какой торец фитинга обрабатывается в этом установе. По записям с указанным торцом "
                             "копится статистика «мин/шт на торец» — по ней оцениваются новые фитинги.")
        else:
            # ── ОПТА ────────────────────────────────────────────────────
            auto_stage = machine_nm  # эталон из БД

            override = st.checkbox(
                "✏️ Изменить этап вручную",
                key=f"{PF}stage_override",
                help="По умолчанию этап = название рабочего центра.",
            )

            if not override:
                # Авторежим: показываем этап, всё готово к сохранению
                st.info(f"🏭 Этап определён автоматически: **«{auto_stage}»**")
                confirmed_stage = auto_stage
                stage_confirmed = True
                st.session_state.pop(f"{PF}stage_choice", None)
            else:
                # Ручной режим: text_input с key=_stage_opta_key.
                # Значение уже инициализировано выше (machine_nm) при первом входе.
                # При последующих rerun Streamlit восстанавливает значение из session_state
                # — ввод пользователя не теряется при клике на «Финальный выпуск».
                oc1, _ = st.columns([3, 4])
                stage_input = oc1.text_input(
                    "Этап / операция (ручной)",
                    key=_stage_opta_key,
                    help="Изменено вручную. По умолчанию = название РЦ.",
                )
                # Если поле пустое — берём авто
                candidate = normalize_stage(stage_input) if stage_input.strip() else auto_stage

                if candidate == auto_stage:
                    # Совпадает с авто — подтверждение не нужно
                    st.session_state.pop(f"{PF}stage_choice", None)
                    confirmed_stage = auto_stage
                    stage_confirmed = True
                else:
                    # Отличается — предупреждение + выбор ПРЯМО ЗДЕСЬ,
                    # до кнопки «Записать выпуск»
                    st.warning(
                        f"⚠️ Введённый этап **«{candidate}»** "
                        f"отличается от названия РЦ **«{auto_stage}»**."
                    )
                    choice = st.radio(
                        "Какой этап сохранить?",
                        options=["auto", "manual"],
                        format_func=lambda x: (
                            f"↩ Авто: «{auto_stage}»" if x == "auto"
                            else f"✏️ Ручной: «{candidate}»"
                        ),
                        key=f"{PF}stage_choice",
                        horizontal=True,
                    )
                    if choice == "auto":
                        confirmed_stage = auto_stage
                        stage_confirmed = True
                    else:
                        confirmed_stage = candidate
                        stage_confirmed = True

        # ── Примечание и финальный выпуск ───────────────────────────────
        fc1, fc2 = st.columns([5, 2])
        notes_prod = fc1.text_input("Примечание", key=f"{PF}notes")
        is_final   = fc2.checkbox(
            "✅ Финальный выпуск",
            key=f"{PF}is_final",
            help="Для станков — финал станочного этапа. "
                 "Для ОПТА — финал всей партии (учитывается в progress bar).")

        # ── Кнопка «Записать выпуск» ─────────────────────────────────────
        # Блокируется только если для станка не введён этап
        # (для ОПТА всегда есть confirmed_stage — либо авто, либо выбранный вариант).
        btn_disabled = (not is_wc) and (not confirmed_stage.strip())
        if btn_disabled:
            st.caption("⬆ Укажите этап / операцию для сохранения записи.")

        if st.button(
            "✔ Записать выпуск",
            type="primary",
            use_container_width=True,
            key=f"{PF}submit",
            disabled=btn_disabled,
        ):
            require_not_viewer()

            # ── Валидация партии ────────────────────────────────────────
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

            # ── Финальная проверка этапа для станков ───────────────────
            if not is_wc and not confirmed_stage.strip():
                st.error("Укажите этап / операцию для обычного станка.")
                st.stop()

            # ── INSERT ──────────────────────────────────────────────────
            sel_m_prod = next(m for m in machines if m["id"] == sel_machine)
            plan_h   = round(produced_qty / sel_m_prod["productivity"], 3) \
                       if produced_qty > 0 else 0.0
            fact_min = float(actual_dur_min) if actual_dur_min > 0 else None

            exec_sql("""
                INSERT INTO production
                (date, machine_id, operator_id, batch, batch_number,
                 setup_time, produced_qty, actual_time,
                 actual_duration_minutes, record_type, is_final_release,
                 stage_name, notes, end_key)
                VALUES (?,?,?,?,?,?,?,?,?,'production',?,?,?,?)
            """, (prod_date.isoformat(), sel_machine,
                  sel_operator if sel_operator else None,
                  used_batch_name, batch_no_stripped,
                  setup_time, produced_qty, plan_h, fact_min,
                  1 if is_final else 0,
                  confirmed_stage or None,
                  notes_prod, (end_choice or None) if not is_wc else None))

            # ── Сообщение об успехе ─────────────────────────────────────
            stage_lbl = f" | этап «{confirmed_stage}»" if confirmed_stage else ""
            if produced_qty == 0:
                msg = f"✅ Установ записан: 0 шт (наладка / прогон){stage_lbl}"
            elif is_wc:
                msg = f"✅ Выпуск ОПТА: {produced_qty} шт{stage_lbl}"
                if is_final:
                    msg += " | 🏁 Финальный выпуск ОПТА"
            else:
                msg = f"✅ Выпуск: {produced_qty} шт | план {plan_h:.2f} ч{stage_lbl}"
                if is_final:
                    msg += " | 🏁 Финальный выпуск (станок)"
                if fact_min:
                    msg += f" | факт {fact_min:.0f} мин"
            # ── Сброс полей формы: новое поколение ключей ───────────────
            # Наладка, время, примечание и «финальный» очищаются; станок, оператор, дата, этап и количество
            # переносятся в новую форму — следующую запись (на том же станке или следующий этап партии,
            # например пассивацию того же количества) вносят без повторного ввода.
            st.session_state["pf_flash"] = msg
            keep = {"machine": sel_machine, "operator": sel_operator, "date": prod_date,
                    "machine_prev": sel_machine, "qty": produced_qty}
            if not is_wc and confirmed_stage:
                keep["stage_lathe"] = confirmed_stage
            for _k in [k for k in st.session_state if k.startswith(PF)]:
                del st.session_state[_k]
            st.session_state["pf_gen"] += 1
            NEW_PF = f"pf{st.session_state['pf_gen']}_"
            for _f, _v in keep.items():
                st.session_state[f"{NEW_PF}{_f}"] = _v
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
        nut_mode = nut_filter_widget(st, key="nut_mode_history")

    nut_summary(nut_mode, date_from.isoformat(), date_to.isoformat())

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
        LEFT JOIN batches   b ON b.batch_number = p.batch_number
        WHERE p.date BETWEEN ? AND ?
    """ + nut_filter_sql(nut_mode)
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
    if can("records.edit"):
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

    if can("records.edit"):
        st.divider()
        # ══════════════════════════════════════════════════════════════
        # ФОРМА УДАЛЕНИЯ ЗАПИСИ
        # ══════════════════════════════════════════════════════════════
        with st.expander("🗑 Удалить запись"):
            with st.form("delete_prod", clear_on_submit=True):
                del_id = st.number_input("ID записи для удаления", min_value=1, step=1)
                if st.form_submit_button("🗑 Удалить запись", type="primary"):
                    require_not_viewer()
                    with tx() as conn:
                        old = conn.execute("SELECT * FROM production WHERE id=?",
                                           (del_id,)).fetchone()
                        if old:
                            conn.execute("DELETE FROM production WHERE id=?", (del_id,))
                            audit(conn, "delete", "production", del_id, dict(old))
                    if old:
                        st.success(f"Запись #{del_id} удалена.")
                        st.rerun()
                    else:
                        st.error(f"Запись #{del_id} не найдена.")

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
        _render_edit_record_form()


def _render_edit_record_form():
    """Шаги 2–3 редактирования записи выпуска/ремонта (запись — в session_state["edit_record"]).
    Используется в «Истории» и в «Прогрессе партии». Только для admin."""
    _flash = st.session_state.pop("edit_flash", None)
    if _flash:
        st.success(_flash)
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
            # Торец установа (для станков, где фитинг делается по торцам) — можно дозаполнить в старых записях
            _bn_rec = get_batch(rec.get("batch_number") or "")
            _bname_e = (_bn_rec or {}).get("batch_name") or rec.get("batch") or ""
            _ends_e = [e for e in (tech.parse_article(_bname_e).get("ends") or []) if e.get("kind")] if _bname_e else []
            _lab_e = {tech.end_key(e): tech.end_label(e) for e in _ends_e}
            _cur_end = rec.get("end_key") or ""
            if _cur_end and _cur_end not in _lab_e:
                _lab_e[_cur_end] = _cur_end
            e_end = _cur_end
            if _lab_e:
                _opts_e = [""] + list(_lab_e)
                e_end = st.selectbox("Торец на этом установе (235 / 2100)", _opts_e, index=_opts_e.index(_cur_end),
                                     format_func=lambda x: "— не указано —" if x == "" else _lab_e.get(x, x),
                                     help="По записям с указанным торцом копится статистика «мин/шт на торец».")

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
                    "end_key":                  e_end or None,
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
                    update_sql = """
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
                            is_final_release         = ?,
                            end_key                  = ?
                        WHERE id = ?
                    """
                    update_params = (
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
                        draft.get("end_key"),
                        draft["id"],
                    )
                    with tx() as conn:
                        old = conn.execute("SELECT * FROM production WHERE id=?",
                                           (draft["id"],)).fetchone()
                        conn.execute(update_sql, update_params)
                        audit(conn, "update", "production", draft["id"],
                              dict(old) if old else None, dict(draft, actual_time=plan_h))
                    st.session_state["edit_flash"] = f"✅ Запись ID {draft['id']} успешно обновлена."
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
                format_func=lambda x, _ms=machines_now: f"{'🏭' if next(m['is_work_center'] for m in _ms if m['id']==x) else '⚙️'} #{x} {next(m['name'] for m in _ms if m['id']==x)}")
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
                format_func=lambda x, _ms=machines_now: f"#{x} {next(m['name'] for m in _ms if m['id']==x)}")
            st.caption("Удалить можно только станок без записей выпуска и ремонтов — "
                       "история не удаляется вместе со станком.")
            confirm = st.checkbox("Подтверждаю удаление станка")
            if st.form_submit_button("Удалить", type="primary"):
                if not confirm:
                    st.warning("Поставьте галочку для подтверждения.")
                else:
                    with tx() as conn:
                        cnt = conn.execute("SELECT COUNT(*) FROM production WHERE machine_id=?",
                                           (d_id,)).fetchone()[0]
                        if cnt == 0:
                            old = conn.execute("SELECT * FROM machines WHERE id=?",
                                               (d_id,)).fetchone()
                            conn.execute("DELETE FROM machines WHERE id=?", (d_id,))
                            audit(conn, "delete", "machines", d_id, dict(old) if old else None)
                    if cnt:
                        st.error(f"❌ Нельзя удалить станок: по нему {cnt} записей в истории. "
                                 "Чтобы убрать станок из работы, смените ему статус.")
                    else:
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

        st.markdown("#### ✏️ Редактировать оператора")
        _op_flash = st.session_state.pop("op_edit_flash", None)
        if _op_flash:
            (st.success if _op_flash[0] else st.error)(_op_flash[1])
        if operators:
            _ops = {o["id"]: o for o in operators}
            eo_id = st.selectbox("Оператор", list(_ops), key="op_edit_pick",
                                 format_func=lambda x, _o=_ops: f"#{x} {_o[x]['name']}"
                                                              + (f" ({_o[x]['rank']})" if _o[x].get("rank") else ""))
            with st.form(f"edit_op_{eo_id}"):
                ec1, ec2 = st.columns(2)
                eo_name = ec1.text_input("ФИО*", value=_ops[eo_id]["name"] or "")
                eo_rank = ec2.text_input("Разряд", value=_ops[eo_id].get("rank") or "")
                st.caption("Записи выпуска ссылаются на оператора по номеру — после переименования вся история "
                           "покажет новое имя.")
                if st.form_submit_button("💾 Сохранить", type="primary"):
                    new_name, new_rank = eo_name.strip(), eo_rank.strip()
                    dup = [o for o in operators if o["id"] != eo_id and (o["name"] or "").strip().lower() == new_name.lower()]
                    if not new_name:
                        st.session_state["op_edit_flash"] = (False, "Укажите ФИО.")
                    elif dup:
                        st.session_state["op_edit_flash"] = (False, f"Оператор «{new_name}» уже есть (#{dup[0]['id']}).")
                    elif new_name == (_ops[eo_id]["name"] or "") and new_rank == (_ops[eo_id].get("rank") or ""):
                        st.session_state["op_edit_flash"] = (True, "Изменений нет.")
                    else:
                        with tx() as conn:
                            old = conn.execute("SELECT * FROM operators WHERE id=?", (eo_id,)).fetchone()
                            conn.execute("UPDATE operators SET name=?, rank=? WHERE id=?", (new_name, new_rank, eo_id))
                            audit(conn, "update", "operators", eo_id, dict(old) if old else None,
                                  {"name": new_name, "rank": new_rank})
                        st.session_state["op_edit_flash"] = (True, f"✅ Оператор #{eo_id} сохранён: «{new_name}».")
                    st.rerun()

        st.markdown("#### 🗑 Удалить оператора")
        with st.form("del_op", clear_on_submit=True):
            ops_now = q("SELECT id, name FROM operators ORDER BY id")
            if ops_now:
                do_id = st.selectbox("Оператор",
                    options=[o["id"] for o in ops_now],
                    format_func=lambda x, _os=ops_now: next(o["name"] for o in _os if o["id"]==x))
                if st.form_submit_button("Удалить оператора", type="primary"):
                    with tx() as conn:
                        old = conn.execute("SELECT * FROM operators WHERE id=?",
                                           (do_id,)).fetchone()
                        # Запоминаем, у каких записей был этот оператор — для восстановления
                        prod_ids = [r[0] for r in conn.execute(
                            "SELECT id FROM production WHERE operator_id=?", (do_id,))]
                        conn.execute("UPDATE production SET operator_id=NULL WHERE operator_id=?",
                                     (do_id,))
                        conn.execute("DELETE FROM operators WHERE id=?", (do_id,))
                        audit(conn, "delete", "operators", do_id,
                              dict(dict(old) if old else {}, production_ids=prod_ids))
                    st.success("Оператор удалён.")
                    st.rerun()

    # ── Пользователи ──────────────────────────────────────────────────
    with tab_u:
        if can("users.manage"):
            _users_master()
        else:
            st.info("🔒 Пользователей, пароли и права меняет только мастер (суперадмин).")
            try:
                users = load_config()["credentials"]["usernames"]
                st.dataframe(pd.DataFrame([{"Логин": u, "Имя": v.get("name", ""), "Роль": ROLE_LABELS.get(v.get("role"), v.get("role")),
                                            "Свои права": "да" if isinstance(v.get("perms"), list) else ""}
                                           for u, v in users.items()]), use_container_width=True, hide_index=True)
            except Exception as e:
                st.error(f"Ошибка чтения config.yml: {e}")


# ── Пользователи и права (master) ──────────────────────────────────────────

def save_users_config(cfg: dict, action: str, login: str, old: dict | None, new: dict | None):
    """Записывает config.yml атомарно, с резервной копией прежнего файла и записью в журнал изменений
    (без хешей паролей)."""
    import shutil
    bdir = os.path.join(os.path.dirname(os.path.abspath(CONFIG_PATH)), "config_backups")
    os.makedirs(bdir, exist_ok=True)
    if os.path.exists(CONFIG_PATH):
        shutil.copy2(CONFIG_PATH, os.path.join(bdir, f"config_{datetime.now():%Y%m%d_%H%M%S_%f}.yml"))
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    os.replace(tmp, CONFIG_PATH)
    strip = lambda d: None if d is None else {k: v for k, v in d.items() if k != "password"}
    with tx() as conn:
        audit(conn, action, "users", None, dict(strip(old) or {}, login=login), dict(strip(new) or {}, login=login))


def _hash_pw(pw: str) -> str:
    import bcrypt as _bcrypt
    return _bcrypt.hashpw(pw.encode(), _bcrypt.gensalt(12)).decode()


def _users_master():
    import re
    me = st.session_state.get("username", "")
    flash = st.session_state.pop("users_flash", None)
    if flash:
        (st.success if flash[0] else st.error)(flash[1])
    cfg = load_config()
    users = cfg["credentials"]["usernames"]
    masters = [u for u, v in users.items() if v.get("role") == "master"]

    # ── обзор: кто что может ──────────────────────────────────────────
    st.markdown("#### 🔐 Кто что может")
    st.caption("Роль задаёт права по умолчанию; у пользователя можно включить или выключить отдельные права "
               "(тогда в колонке «Свои права» — «да»). Мастер всегда может всё.")
    rows = []
    for u, v in users.items():
        pr = user_perms(v)
        rows.append({"Логин": u, "Имя": v.get("name", ""), "Роль": ROLE_LABELS.get(v.get("role"), v.get("role")),
                     "Свои права": "да" if isinstance(v.get("perms"), list) and v.get("role") != "master" else "",
                     **{PERM_LABEL[p]: "✓" if p in pr else "" for p in ALL_PERMS}})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ── редактирование пользователя ───────────────────────────────────
    st.markdown("#### ✏️ Пользователь: роль, права, пароль")
    login = st.selectbox("Пользователь", list(users), format_func=lambda u: f"{u} — {users[u].get('name', '')}",
                         key="um_user")
    u = users[login]
    eff = user_perms(u)
    with st.form(f"um_edit_{login}"):
        c1, c2 = st.columns(2)
        name = c1.text_input("Имя", value=u.get("name", ""))
        roles = list(ROLE_LABELS)
        role = c2.selectbox("Роль", roles, index=roles.index(u.get("role")) if u.get("role") in roles else 2,
                            format_func=ROLE_LABELS.get,
                            help="Роль — набор прав по умолчанию. Мастер может всё, в том числе управлять пользователями.")
        mode = st.radio("Права", ["по роли", "свой набор"], horizontal=True,
                        index=1 if isinstance(u.get("perms"), list) else 0,
                        help="«По роли» — права меняются вместе с ролью. «Свой набор» — галочки ниже.")
        chosen = []
        for gname, items in PERM_GROUPS:
            st.markdown(f"**{gname}**")
            cols = st.columns(3)
            for k, (p, lbl) in enumerate(items):
                if p == "users.manage":
                    continue
                if cols[k % 3].checkbox(lbl, value=p in eff, key=f"um_{login}_{p}"):
                    chosen.append(p)
        st.caption("Галочки применяются, только если выбрано «свой набор». Право «Пользователи и права» есть только у мастера.")
        pw1 = st.text_input("Новый пароль (пусто — не менять)", type="password")
        pw2 = st.text_input("Повторите пароль", type="password")
        go = st.form_submit_button("💾 Сохранить пользователя", type="primary")
    if go:
        err = None
        if login == me and role != "master" and u.get("role") == "master":
            err = "Нельзя снять роль мастера с самого себя."
        elif u.get("role") == "master" and role != "master" and len(masters) <= 1:
            err = "Это последний мастер — сначала назначьте другого."
        elif pw1 and (pw1 != pw2):
            err = "Пароли не совпадают."
        elif pw1 and len(pw1) < 6:
            err = "Пароль — не короче 6 символов."
        if err:
            st.session_state["users_flash"] = (False, err)
        else:
            old = dict(u)
            new = dict(u, name=name.strip() or u.get("name", ""), role=role)
            if mode == "свой набор" and role != "master":
                new["perms"] = sorted(chosen)
            else:
                new.pop("perms", None)
            if pw1:
                new["password"] = _hash_pw(pw1)
            users[login] = new
            save_users_config(cfg, "update", login, old, dict(new, password_changed=bool(pw1)))
            st.session_state["users_flash"] = (True, f"✅ Пользователь «{login}» сохранён"
                                                     + (", пароль изменён" if pw1 else "") + ".")
        st.rerun()

    # ── добавить / удалить ────────────────────────────────────────────
    c1, c2 = st.columns(2)
    with c1.expander("➕ Добавить пользователя"):
        with st.form("um_add", clear_on_submit=True):
            n_login = st.text_input("Логин*")
            n_name = st.text_input("Имя*")
            n_role = st.selectbox("Роль", list(ROLE_LABELS), index=2, format_func=ROLE_LABELS.get)
            n_pw = st.text_input("Пароль* (не короче 6 символов)", type="password")
            if st.form_submit_button("Создать", type="primary"):
                lg = n_login.strip()
                if not lg or not n_name.strip() or len(n_pw) < 6:
                    st.session_state["users_flash"] = (False, "Укажите логин, имя и пароль не короче 6 символов.")
                elif not re.fullmatch(r"[A-Za-z0-9_.-]{2,40}", lg):
                    st.session_state["users_flash"] = (False, "Логин — латиница, цифры, «_ . -», 2–40 символов.")
                elif lg in users:
                    st.session_state["users_flash"] = (False, f"Пользователь «{lg}» уже есть.")
                else:
                    users[lg] = {"name": n_name.strip(), "password": _hash_pw(n_pw), "role": n_role}
                    save_users_config(cfg, "insert", lg, None, users[lg])
                    st.session_state["users_flash"] = (True, f"✅ Пользователь «{lg}» создан.")
                st.rerun()
    with c2.expander("🗑 Удалить пользователя"):
        del_opts = [x for x in users if x != me and not (users[x].get("role") == "master" and len(masters) <= 1)]
        if not del_opts:
            st.caption("Удалять некого.")
        else:
            d_login = st.selectbox("Пользователь", del_opts, key="um_del_user",
                                   format_func=lambda x: f"{x} — {users[x].get('name', '')}")
            sure = st.checkbox(f"Да, удалить «{d_login}»", key=f"um_del_cb_{d_login}")
            if st.button("Удалить", key="um_del_go", disabled=not sure):
                old = users.pop(d_login)
                save_users_config(cfg, "delete", d_login, old, None)
                st.session_state["users_flash"] = (True, f"Пользователь «{d_login}» удалён (копия config.yml сохранена).")
                st.rerun()
    st.caption("Изменения действуют со следующего действия пользователя на сайте (права читаются при каждом обновлении "
               "страницы). Перед каждым изменением сохраняется копия config.yml в /data/config_backups.")


def page_charts():
    role = st.session_state.get("role", "user")
    if not can("page:charts"):
        st.error("⛔ Доступ запрещён. Требуются права администратора или наблюдателя.")
        st.stop()
    st.title("📊 Графики и аналитика")

    col_ctrl1, col_ctrl2 = st.columns([1, 3])
    days  = col_ctrl1.slider("Период (дней)", 7, 90, 14)
    since = (date.today() - timedelta(days=days)).isoformat()
    nut_mode = nut_filter_widget(col_ctrl2, key="nut_mode_charts")
    nut_summary(nut_mode, since, date.today().isoformat())
    if nut_mode != "all":
        st.caption("Фильтр гаек действует на все вкладки, кроме «Статусы станков» "
                   "(она строится по журналу статусов, а не по партиям).")

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
        LEFT JOIN batches   b ON b.batch_number = p.batch_number
        WHERE p.date >= ?
          AND COALESCE(p.record_type, 'production') = 'production'
    """ + nut_filter_sql(nut_mode) + """
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

    tab1, tab2, tab3, tab4, tab5, tab6, tab_opta, tab_month = st.tabs([
        "📈 Загрузка по дням",
        "🏭 Выпуск по станкам",
        "👤 По операторам",
        "⚡ Производительность",
        "🔧 Наладка",
        "🔄 Статусы станков",
        "🏭 ОПТА",
        "📅 По месяцам",
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

    # ── Вкладка 8: По месяцам (свой интервал, не зависит от ползунка периода) ──
    with tab_month:
        _tab_monthly_analytics(nut_mode)


RU_MONTHS = ["янв", "фев", "мар", "апр", "май", "июн",
             "июл", "авг", "сен", "окт", "ноя", "дек"]

def _month_label(month: str) -> str:
    """'2026-08' → 'авг 2026'."""
    y, m = month.split("-")
    return f"{RU_MONTHS[int(m) - 1]} {y}"

def _dark_layout(fig, title: str, height: int = 420):
    fig.update_layout(title=title, template="plotly_dark", height=height,
                      paper_bgcolor="#0f1117", plot_bgcolor="#1e2130", font_color="#ffffff",
                      legend=dict(orientation="h", yanchor="top", y=-0.18, x=0,
                                  font=dict(color="#e0e0f5")),
                      margin=dict(t=60, b=90))
    return fig

def _tab_monthly_analytics(nut_mode: str):
    """
    Помесячная аналитика за выбранный интервал месяцев:
    выпуск станков и финальный выпуск ОПТА с разбивкой гайки / без гаек,
    связь выпуска гаек с остальным выпуском, часы работы станков,
    выпуск по каждому станку и рабочему центру.
    """
    st.markdown("### 📅 Выпуск и загрузка по месяцам")

    df = pd.DataFrame(q(f"""
        SELECT substr(p.date, 1, 7)                     AS month,
               m.name                                   AS machine,
               COALESCE(m.is_work_center, 0)            AS wc,
               COALESCE(p.produced_qty, 0)              AS qty,
               COALESCE(p.is_final_release, 0)          AS fin,
               COALESCE(p.actual_duration_minutes, 0)   AS fact_min,
               COALESCE(p.setup_time, 0)                AS setup_h,
               CASE WHEN {NUT_SQL} THEN 1 ELSE 0 END    AS nut
        FROM production p
        LEFT JOIN machines m ON m.id = p.machine_id
        LEFT JOIN batches  b ON b.batch_number = p.batch_number
        WHERE COALESCE(p.record_type, 'production') = 'production'
          AND p.date IS NOT NULL AND p.date != ''
    """))
    if df.empty:
        st.info("Нет записей выпуска.")
        return

    # ── Интервал месяцев и способ подсчёта ─────────────────────────────
    months = sorted(df["month"].unique())
    c1, c2, c3 = st.columns([2, 2, 4])
    m_from = c1.selectbox("С месяца", months, index=max(0, len(months) - 6),
                          format_func=_month_label, key="mon_from")
    m_to = c2.selectbox("По месяц", months, index=len(months) - 1,
                        format_func=_month_label, key="mon_to")
    if m_from > m_to:
        m_from, m_to = m_to, m_from
    basis = c3.radio(
        "Выпуск станков считать по", ["fin", "all"], horizontal=True, key="mon_basis",
        format_func=lambda x: {"fin": "🏁 финальному выпуску (готовые детали)",
                               "all": "всем установам"}[x],
        help="Финальный выпуск — каждая деталь считается один раз. "
             "Все установы — деталь с тремя установами считается трижды.")

    sel_months = [m for m in months if m_from <= m <= m_to]
    labels = [_month_label(m) for m in sel_months]
    d = df[df["month"].isin(sel_months)]
    if date.today().strftime("%Y-%m") in sel_months:
        st.caption(f"ℹ️ {_month_label(date.today().strftime('%Y-%m'))} — месяц ещё не закончился.")

    lathe = d[d["wc"] == 0]
    lathe_out = lathe[lathe["fin"] == 1] if basis == "fin" else lathe
    opta_fin = d[(d["wc"] == 1) & (d["fin"] == 1)]

    def by_nut(frame):
        """(без гаек, гайки) — суммы qty по месяцам интервала."""
        g = (frame.groupby(["month", "nut"])["qty"].sum().unstack(fill_value=0)
             .reindex(index=sel_months, columns=[0, 1], fill_value=0))
        return g[0], g[1]

    l_other, l_nut = by_nut(lathe_out)
    o_other, o_nut = by_nut(opta_fin)

    # Фильтр гаек со страницы: какие сегменты показывать
    show_other = nut_mode != "only_nuts"
    show_nut = nut_mode != "no_nuts"
    def shown(other, nut):
        return (other if show_other else 0) + (nut if show_nut else 0)

    lathe_hours = lathe if nut_mode == "all" else lathe[lathe["nut"] == (1 if nut_mode == "only_nuts" else 0)]
    hours = (lathe_hours["fact_min"] / 60 + lathe_hours["setup_h"])

    # ── Итоги за интервал ──────────────────────────────────────────────
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("⚙️ Станки, шт" + (" (финал)" if basis == "fin" else " (установы)"),
              f"{int(shown(l_other, l_nut).sum()):,}")
    k2.metric("🏁 Финал ОПТА, шт", f"{int(shown(o_other, o_nut).sum()):,}")
    tot_o = o_other.sum() + o_nut.sum()
    k3.metric("🔩 Доля гаек в финале ОПТА", f"{(o_nut.sum() / tot_o * 100 if tot_o else 0):.1f}%")
    k4.metric("⏱ Часы работы станков", f"{hours.sum():,.0f} ч")

    def stacked(title, other, nut):
        fig = go.Figure()
        if show_other:
            fig.add_bar(name="Без гаек", x=labels, y=other.values, marker_color="#7c6af7")
        if show_nut:
            fig.add_bar(name="Гайки", x=labels, y=nut.values, marker_color="#f9c74f")
        total = shown(other, nut)
        fig.add_scatter(x=labels, y=total.values, mode="text", showlegend=False,
                        text=[f"{int(v):,}" for v in total.values], textposition="top center")
        fig.update_layout(barmode="stack", yaxis_title="шт")
        st.plotly_chart(_dark_layout(fig, title), use_container_width=True)

    g1, g2 = st.columns(2)
    with g1:
        stacked("⚙️ Станки" + (", финал" if basis == "fin" else ", установы"), l_other, l_nut)
    with g2:
        stacked("🏁 Финал ОПТА", o_other, o_nut)

    # ── Гайки против остального выпуска ───────────────────────────────
    st.markdown("#### 🔩 Гайки и остальной выпуск: есть ли вытеснение")
    src = st.radio("Источник", ["opta", "lathe"], horizontal=True, key="mon_corr_src",
                   format_func=lambda x: {"opta": "Финал ОПТА", "lathe": "Станки"}[x])
    other, nut = (o_other, o_nut) if src == "opta" else (l_other, l_nut)
    from plotly.subplots import make_subplots
    fig_c = make_subplots(specs=[[{"secondary_y": True}]])
    fig_c.add_scatter(x=labels, y=other.values, name="Без гаек, шт", mode="lines+markers",
                      line=dict(color="#7c6af7", width=3), secondary_y=False)
    fig_c.add_scatter(x=labels, y=nut.values, name="Гайки, шт (правая ось)", mode="lines+markers",
                      line=dict(color="#f9c74f", width=3), secondary_y=True)
    fig_c.update_yaxes(title_text="без гаек, шт", secondary_y=False)
    fig_c.update_yaxes(title_text="гайки, шт", secondary_y=True, showgrid=False)
    st.plotly_chart(_dark_layout(fig_c, "Гайки и остальной выпуск"),
                    use_container_width=True)

    # Незаконченный текущий месяц занижает обе серии сразу — в расчёт связи не берём
    cur_m = date.today().strftime("%Y-%m")
    both = pd.DataFrame({"other": other.values, "nut": nut.values}, index=sel_months)
    both = both.drop(index=cur_m, errors="ignore")
    if len(both) >= 3 and both["nut"].std() > 0 and both["other"].std() > 0:
        r = both["other"].corr(both["nut"])
        if r <= -0.5:
            verdict = "заметная обратная связь: в месяцы с большим выпуском гаек остальной выпуск ниже"
        elif r <= -0.2:
            verdict = "слабая обратная связь"
        elif r < 0.2:
            verdict = "связи почти нет"
        else:
            verdict = "прямая связь: гайки и остальной выпуск растут и падают вместе (общая загрузка)"
        st.caption(f"Коэффициент корреляции по месяцам: **r = {r:+.2f}** — {verdict}. "
                   f"Месяцев в расчёте: {len(both)}"
                   + (" (текущий незаконченный месяц не учитывается)" if cur_m in sel_months else "")
                   + "; при малом числе месяцев вывод предварительный. "
                   "График показывает обе серии независимо от фильтра гаек.")
    else:
        st.caption("Для оценки связи нужно минимум 3 завершённых месяца с выпуском гаек и без них.")

    # ── Часы работы станков ───────────────────────────────────────────
    st.markdown("#### ⏱ Часы работы станков по месяцам")
    st.caption("Фактическое время выпуска + наладка по записям станков (без рабочих центров)."
               + ("" if nut_mode == "all" else f" Фильтр: {NUT_MODES[nut_mode].lower()}."))
    h = (lathe_hours.assign(hours=hours).groupby(["month", "machine"])["hours"].sum()
         .unstack(fill_value=0).reindex(index=sel_months, fill_value=0))
    fig_h = go.Figure()
    for mach in h.columns:
        fig_h.add_bar(name=mach, x=labels, y=h[mach].round(1).values)
    fig_h.add_scatter(x=labels, y=h.sum(axis=1).values, mode="text", showlegend=False,
                      text=[f"{v:,.0f} ч" for v in h.sum(axis=1).values], textposition="top center")
    fig_h.update_layout(barmode="stack", yaxis_title="часы")
    st.plotly_chart(_dark_layout(fig_h, "Часы по станкам"), use_container_width=True)

    # ── Выпуск по каждому станку / рабочему центру ────────────────────
    st.markdown("#### 🏭 Выпуск по станкам и рабочим центрам по месяцам")
    d_mach = d if nut_mode == "all" else d[d["nut"] == (1 if nut_mode == "only_nuts" else 0)]
    mc0, mc1, mc2 = st.columns([2, 4, 2])
    group = mc0.radio("Группа", ["lathe", "wc", "all"], key="mon_mach_group",
                      format_func=lambda x: {"lathe": "⚙️ Станки", "wc": "🏭 Рабочие центры",
                                             "all": "Все"}[x])
    in_group = d_mach if group == "all" else d_mach[d_mach["wc"] == (1 if group == "wc" else 0)]
    all_mach = (in_group[["machine", "wc"]].drop_duplicates()
                .sort_values(["wc", "machine"])["machine"].tolist())
    # default зависит от группы: при смене группы выбор сбрасывается на все её объекты
    sel_mach = mc1.multiselect("Станки / РЦ", all_mach, default=all_mach, key=f"mon_machines_{group}")
    only_fin = mc2.radio("Записи", ["all", "fin"], key="mon_mach_fin",
                         format_func=lambda x: {"all": "все", "fin": "только финальные"}[x])
    dm = d_mach[d_mach["machine"].isin(sel_mach)]
    if only_fin == "fin":
        dm = dm[dm["fin"] == 1]
    if dm.empty:
        st.info("Нет данных для выбранных станков / РЦ.")
        return
    pm = (dm.groupby(["month", "machine"])["qty"].sum().unstack(fill_value=0)
          .reindex(index=sel_months, fill_value=0))
    pm = pm[[c for c in all_mach if c in pm.columns]]
    wc_names = set(d[d["wc"] == 1]["machine"])
    fig_m = go.Figure()
    for mach in pm.columns:
        fig_m.add_scatter(x=labels, y=pm[mach].values, mode="lines+markers",
                          name=("🏭 " if mach in wc_names else "⚙️ ") + mach)
    fig_m.update_layout(yaxis_title="шт")
    st.plotly_chart(_dark_layout(fig_m, "Выпуск по месяцам", height=480), use_container_width=True)

    table = pm.T.copy()
    table.columns = labels
    table["Итого"] = table.sum(axis=1)
    table.index.name = "Станок / РЦ"
    st.dataframe(table, use_container_width=True)
    st.download_button("⬇ CSV: выпуск по месяцам", table.to_csv().encode("utf-8-sig"),
                       f"monthly_by_machine_{m_from}_{m_to}.csv", "text/csv",
                       key="dl_monthly_by_machine")


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
    if not can("page:export"):
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
    bn_options = [b["batch_number"] for b in batches]

    # ── А) Создание новой партии — СВЕРХУ для удобного доступа ──────────
    if can("batches.manage"):
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

    # ── Б) Список партий ──────────────────────────────────────────────
    st.markdown("### Список партий")

    # В архиве: финал ОПТА достиг плана (автоматически) или партия архивирована вручную
    # на странице «Прогресс партии».
    def is_closed(b):
        return batch_is_archived(b["archive_state"], b["total_qty"], b["final_opta"])

    active   = [b for b in batches if not is_closed(b)]
    archived = [b for b in batches if is_closed(b)]

    if not batches:
        st.info("Партий пока нет. Создайте первую партию с помощью формы выше.")
    else:
        if not active:
            st.info("Активных партий нет — все партии находятся в архиве.")
        else:
            # Заголовок таблицы
            hc = st.columns([2, 3, 2, 2, 2, 2, 1])
            for col, lbl in zip(hc, ["№ партии", "Название", "Всего (шт)",
                                      "Финал станки", "Финал ОПТА ★", "Создана", ""]):
                col.markdown(f"**{lbl}**")
            st.divider()

        for b in active:
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
            if rc[6].button("📦", key=f"goto_bp_{b['batch_number']}",
                            help=f"Открыть прогресс партии «{b['batch_number']}»"):
                st.session_state["batch_progress_select"] = b["batch_number"]
                st.session_state["nav_goto"] = "batch"
                st.rerun()

        st.caption("★ Финал ОПТА = общий прогресс завершения партии  |  📦 = открыть прогресс партии"
                   "  |  архивировать вручную — на странице прогресса партии")

        # ── Архив: закрытые партии — рисуются только по запросу ─────────
        if archived:
            st.divider()
            if st.toggle(f"🗄 Показать архив — закрытые партии ({len(archived)})",
                         key="show_batch_archive"):
                df_arch = pd.DataFrame([{
                    "№ партии":      b["batch_number"],
                    "Название":      b["batch_name"] or "—",
                    "Всего (шт)":    b["total_qty"],
                    "Финал станки":  b["final_lathe"],
                    "Финал ОПТА ★":  b["final_opta"],
                    "В архиве":      "вручную" if b["archive_state"] == "archived" else "100% ОПТА",
                    "Создана":       (b["created_at"] or "")[:10],
                } for b in archived])
                st.dataframe(df_arch, use_container_width=True, hide_index=True)
                ac1, ac2 = st.columns([3, 1])
                arch_bn = ac1.selectbox("Партия из архива",
                                        options=[b["batch_number"] for b in archived],
                                        key="archive_batch_sel")
                ac2.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                if ac2.button("📦 Открыть прогресс", key="archive_goto_bp",
                              use_container_width=True):
                    st.session_state["batch_progress_select"] = arch_bn
                    st.session_state["nav_goto"] = "batch"
                    st.rerun()

    if not can("batches.manage"):
        st.info("👁 Создание, редактирование и удаление партий доступно только администратору.")
        return

    if not batches:
        return

    st.divider()

    # ── В) Редактирование партии ──────────────────────────────────────
    with st.expander("✏️ Редактировать партию"):
        st.caption(
            "Номер партии изменить нельзя (если по ней есть записи выпуска). "
            "Можно изменить: название, количество, примечание."
        )
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

    # Значение берётся из session_state по key; index= не передаём — иначе
    # Streamlit выводит предупреждение о конфликте и меняет id виджета.
    sel_bn = st.selectbox(
        "Выберите номер партии",
        options=options,
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
    📦 Партия: <b>{html.escape(sel_bn)}</b>
  </div>
  <div style="color:#e0e0f5;font-size:0.95rem;line-height:1.7;">
    {'<b>Название:</b> ' + html.escape(batch_name) + ' &nbsp;|&nbsp; ' if batch_name else ''}
    <b>Всего в партии:</b> {f'{total_qty:,} шт' if total_qty else '—'} &nbsp;|&nbsp;
    <b>Создана:</b> {html.escape(created)}
    {'<br><b>Примечание:</b> ' + html.escape(batch_notes) if batch_notes else ''}
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

    # ── Архив: состояние и ручное управление ──────────────────────────
    _flash = st.session_state.pop("bp_archive_flash", None)
    if _flash:
        st.success(_flash)
    if bm:
        state       = bm.get("archive_state")
        auto_closed = batch_auto_closed(total_qty, opta_final)
        archived    = batch_is_archived(state, total_qty, opta_final)
        if archived:
            why = "вручную" if state == "archived" else "финал ОПТА достиг плана"
            st.info(f"🗄 Партия в архиве ({why}) — в списке активных партий не показывается.")
        elif state == "active" and auto_closed:
            st.info("📤 Партия вручную оставлена в работе, хотя финал ОПТА достиг плана.")
        if can("batches.manage"):
            label = "📤 Вернуть в работу" if archived else "🗄 Отправить в архив"
            if st.button(label, key=f"bp_archive_toggle_{sel_bn}"):
                set_batch_archived(sel_bn, not archived, auto_closed)
                st.session_state["bp_archive_flash"] = (
                    f"✅ Партия «{sel_bn}» возвращена в работу." if archived
                    else f"✅ Партия «{sel_bn}» отправлена в архив.")
                st.rerun()

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
            "ID":               r["id"],
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
                     "ID":            st.column_config.NumberColumn(width="small", format="%d",
                                                                    help="Номер записи — для редактирования"),
                     "Выпущено (шт)": st.column_config.NumberColumn(format="%d шт"),
                 })

    # ── Редактирование записи партии прямо здесь (admin) ──────────────
    if can("records.edit"):
        _flash = st.session_state.pop("edit_flash", None)   # после сохранения — вне свёрнутого блока
        if _flash:
            st.success(_flash)
        cur = st.session_state.get("edit_record")
        editing_here = bool(cur) and cur.get("batch_number") == sel_bn
        with st.expander("✏️ Редактировать запись этой партии", expanded=editing_here):
            rec_by_id = {r["id"]: r for r in rows}
            pc1, pc2 = st.columns([4, 1])
            pick = pc1.selectbox(
                "Запись", options=list(rec_by_id),
                format_func=lambda i: (f"#{i} — {rec_by_id[i]['date']} — "
                                       f"{rec_by_id[i]['stage_name'] or '—'} — "
                                       f"{rec_by_id[i]['machine'] or '—'} — "
                                       f"{rec_by_id[i]['produced_qty']} шт"),
                key=f"bp_edit_pick_{sel_bn}")
            pc2.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            if pc2.button("✏️ Загрузить", key=f"bp_edit_load_{sel_bn}", use_container_width=True):
                rec = q("SELECT * FROM production WHERE id=?", (pick,), fetch="one")
                st.session_state["edit_record"]  = dict(rec) if rec else None
                st.session_state["edit_pending"] = False
                st.rerun()
            # Форма показывается только для записи этой партии; без загруженной
            # записи функция лишь выводит сообщение об успешном сохранении.
            if editing_here or not cur:
                _render_edit_record_form()

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

    # ── Д) Фактическое время по центрам ───────────────────────────────
    st.markdown("### ⏱ Фактическое время по станкам и рабочим центрам")
    st.caption(
        "Учитывается: фактическое время выпуска (мин) + наладка (ч → мин). "
        "Записи с некорректными данными пропускаются без ошибки."
    )

    # Запрашиваем все записи с временными полями
    time_rows = q("""
        SELECT
            COALESCE(m.is_work_center, 0) AS is_work_center,
            m.name                        AS center_name,
            p.actual_duration_minutes     AS fact_min,
            p.setup_time                  AS setup_h
        FROM production p
        LEFT JOIN machines m ON m.id = p.machine_id
        WHERE p.batch_number = ?
          AND COALESCE(p.record_type, 'production') = 'production'
    """, (sel_bn,))

    time_lathe, time_opta = {}, {}
    skipped = 0
    for tr in time_rows:
        try:
            mins = 0.0
            if tr["fact_min"] is not None:
                v = float(tr["fact_min"])
                if v > 0:
                    mins += v
            if tr["setup_h"] is not None:
                v = float(tr["setup_h"])
                if v > 0:
                    mins += v * 60.0
            # Пропускаем нулевые строки (наладка=0, время=0)
            if mins <= 0:
                continue
            cname = (tr["center_name"] or "—").strip()
            if tr["is_work_center"] == 1:
                time_opta[cname]  = time_opta.get(cname, 0.0)  + mins
            else:
                time_lathe[cname] = time_lathe.get(cname, 0.0) + mins
        except Exception:
            skipped += 1

    if skipped:
        st.caption(f"⚠️ Пропущено записей с некорректными данными времени: {skipped}")

    has_time_data = bool(time_lathe or time_opta)

    if not has_time_data:
        st.info("Данные по фактическому времени для этой партии отсутствуют.")
    else:
        tc1, tc2 = st.columns(2)

        with tc1:
            st.markdown("**⚙️ Блок ЦМО / Станки**")
            if time_lathe:
                df_tl = pd.DataFrame([
                    {"Станок": k, "Итого (мин)": round(v), "Итого (ч)": round(v/60, 2)}
                    for k, v in sorted(time_lathe.items())
                ])
                st.dataframe(df_tl, use_container_width=True, hide_index=True)
                st.caption(f"Итого по блоку: **{round(sum(time_lathe.values())):,} мин "
                           f"({round(sum(time_lathe.values())/60, 1)} ч)**")
            else:
                st.info("Нет данных по станкам.")

        with tc2:
            st.markdown("**🏭 Блок ОПТА / Рабочие центры**")
            if time_opta:
                df_to = pd.DataFrame([
                    {"Рабочий центр": k, "Итого (мин)": round(v), "Итого (ч)": round(v/60, 2)}
                    for k, v in sorted(time_opta.items())
                ])
                st.dataframe(df_to, use_container_width=True, hide_index=True)
                st.caption(f"Итого по блоку: **{round(sum(time_opta.values())):,} мин "
                           f"({round(sum(time_opta.values())/60, 1)} ч)**")
            else:
                st.info("Нет данных по ОПТА.")

        # ── CSV выгрузка таблицы времени ──────────────────────────────
        time_csv_rows = []
        for cname, mins in sorted(time_lathe.items()):
            time_csv_rows.append({
                "batch_number":  sel_bn,
                "center_group":  "Станки",
                "center_name":   cname,
                "total_minutes": round(mins),
                "total_hours":   round(mins / 60, 2),
            })
        for cname, mins in sorted(time_opta.items()):
            time_csv_rows.append({
                "batch_number":  sel_bn,
                "center_group":  "ОПТА",
                "center_name":   cname,
                "total_minutes": round(mins),
                "total_hours":   round(mins / 60, 2),
            })
        if time_csv_rows:
            csv_bytes = pd.DataFrame(time_csv_rows).to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                label="💾 Скачать таблицу времени (CSV)",
                data=csv_bytes,
                file_name=f"time_{sel_bn}.csv",
                mime="text/csv",
                key="dl_time_csv",
            )

    st.divider()

    # ── Е) Графики по этапам ──────────────────────────────────────────
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
#  ЖУРНАЛЫ
# ═══════════════════════════════════════════════════════════════════════════

# Поддерживаемые типы колонок журнала и их метки для UI
JOURNAL_COL_TYPES = {
    "text":      "Текст (строка)",
    "textarea":  "Большое текстовое поле",
    "number":    "Число",
    "date":      "Дата",
    "datetime":  "Дата и время",
    "operator":  "Оператор (из справочника)",
    "machine":   "Станок / РЦ (из справочника)",
    "select":    "Список значений (select)",
    "bool":      "Флаг / чекбокс",
}


def _j_get_journals():
    return q("SELECT * FROM journals ORDER BY created_at DESC")

def _j_get_columns(journal_id: int):
    return q("SELECT * FROM journal_columns WHERE journal_id=? ORDER BY col_order",
             (journal_id,))

def _j_get_entries(journal_id: int):
    return q("""
        SELECT je.id, je.created_by, je.created_at
        FROM journal_entries je
        WHERE je.journal_id=?
        ORDER BY je.created_at DESC
    """, (journal_id,))

def _j_get_entry_values(entry_id: int):
    """Возвращает dict {column_id: value_text}."""
    rows = q("SELECT column_id, value_text FROM journal_entry_values WHERE entry_id=?",
             (entry_id,))
    return {r["column_id"]: r["value_text"] for r in rows}

def _j_create_journal(name: str, desc: str, username: str) -> int:
    with tx() as conn:
        cur = conn.execute("""
            INSERT INTO journals (name, description, created_by, created_at)
            VALUES (?,?,?,?)
        """, (name.strip(), desc.strip(), username,
              datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        return cur.lastrowid

def _j_save_columns(journal_id: int, cols: list):
    """
    Сохраняет структуру журнала, обновляя колонки на месте.
    ID существующих колонок не меняются, поэтому значения записей
    (journal_entry_values.column_id) остаются привязанными.
    Колонки, убранные из структуры, удаляются только из journal_columns —
    их значения остаются в БД.
    """
    with tx() as conn:
        existing_ids = {r[0] for r in conn.execute(
            "SELECT id FROM journal_columns WHERE journal_id=?", (journal_id,))}
        kept = set()
        for i, c in enumerate(cols):
            fields = (i, c["col_name"], c["col_type"],
                      c.get("col_options", ""), c.get("col_unit", ""))
            if c.get("id") in existing_ids:
                conn.execute("""
                    UPDATE journal_columns
                    SET col_order=?, col_name=?, col_type=?, col_options=?, col_unit=?
                    WHERE id=?
                """, fields + (c["id"],))
                kept.add(c["id"])
            else:
                conn.execute("""
                    INSERT INTO journal_columns
                    (journal_id, col_order, col_name, col_type, col_options, col_unit)
                    VALUES (?,?,?,?,?,?)
                """, (journal_id,) + fields)
        for col_id in existing_ids - kept:
            conn.execute("DELETE FROM journal_columns WHERE id=?", (col_id,))

def _j_delete_journal(journal_id: int):
    """Каскадное удаление журнала и всех его данных (одной транзакцией)."""
    with tx() as conn:
        old = conn.execute("SELECT * FROM journals WHERE id=?", (journal_id,)).fetchone()
        n_entries = conn.execute("SELECT COUNT(*) FROM journal_entries WHERE journal_id=?",
                                 (journal_id,)).fetchone()[0]
        conn.execute("""
            DELETE FROM journal_entry_values
            WHERE entry_id IN (SELECT id FROM journal_entries WHERE journal_id=?)
        """, (journal_id,))
        conn.execute("DELETE FROM journal_entries WHERE journal_id=?", (journal_id,))
        conn.execute("DELETE FROM journal_columns WHERE journal_id=?", (journal_id,))
        conn.execute("DELETE FROM journals WHERE id=?", (journal_id,))
        audit(conn, "delete", "journals", journal_id,
              dict(dict(old) if old else {}, entries_deleted=n_entries))

def _j_save_entry(journal_id: int, col_values: dict, username: str):
    """Сохраняет запись: INSERT journal_entries + journal_entry_values."""
    now_s = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with tx() as conn:
        entry_id = conn.execute("""
            INSERT INTO journal_entries (journal_id, created_by, created_at)
            VALUES (?,?,?)
        """, (journal_id, username, now_s)).lastrowid
        conn.executemany("""
            INSERT INTO journal_entry_values (entry_id, column_id, value_text)
            VALUES (?,?,?)
        """, [(entry_id, col_id, str(val) if val is not None else "")
              for col_id, val in col_values.items()])

def _j_delete_entry(entry_id: int):
    with tx() as conn:
        old = conn.execute("SELECT * FROM journal_entries WHERE id=?", (entry_id,)).fetchone()
        values = {r[0]: r[1] for r in conn.execute(
            "SELECT column_id, value_text FROM journal_entry_values WHERE entry_id=?",
            (entry_id,))}
        conn.execute("DELETE FROM journal_entry_values WHERE entry_id=?", (entry_id,))
        conn.execute("DELETE FROM journal_entries WHERE id=?", (entry_id,))
        audit(conn, "delete", "journal_entries", entry_id,
              dict(dict(old) if old else {}, values=values))


def _j_render_input(col, key_prefix: str, operators_list, machines_list):
    """
    Рендерит один виджет ввода по типу колонки.
    Возвращает строковое значение для сохранения.
    """
    ctype   = col["col_type"]
    cname   = col["col_name"]
    cunit   = col["col_unit"] or ""
    copts   = col["col_options"] or ""
    widget_key = f"{key_prefix}_{col['id']}"
    label   = f"{cname}" + (f" ({cunit})" if cunit else "")

    if ctype == "text":
        return st.text_input(label, key=widget_key)
    elif ctype == "textarea":
        return st.text_area(label, key=widget_key, height=80)
    elif ctype == "number":
        val = st.number_input(label, step=0.01, key=widget_key)
        return str(val)
    elif ctype == "date":
        d = st.date_input(label, value=date.today(), key=widget_key)
        return d.isoformat() if d else ""
    elif ctype == "datetime":
        d = st.date_input(label + " (дата)", value=date.today(), key=widget_key + "_d")
        t = st.time_input(label + " (время)", key=widget_key + "_t")
        return f"{d.isoformat()} {t}" if d else ""
    elif ctype == "operator":
        opts_list = [f"{o['id']}:{o['name']}" for o in operators_list]
        labels    = ["—"] + [o["name"] for o in operators_list]
        ids       = [0]   + [o["id"]   for o in operators_list]
        chosen = st.selectbox(label, options=ids,
                              format_func=lambda x: next(
                                  (o["name"] for o in operators_list if o["id"] == x), "—"
                              ) if x else "—",
                              key=widget_key)
        return str(chosen) if chosen else ""
    elif ctype == "machine":
        all_m = machines_list
        ids   = [0] + [m["id"] for m in all_m]
        chosen = st.selectbox(label, options=ids,
                              format_func=lambda x: next(
                                  (m["name"] for m in all_m if m["id"] == x), "—"
                              ) if x else "—",
                              key=widget_key)
        return str(chosen) if chosen else ""
    elif ctype == "select":
        options_list = [o.strip() for o in copts.split(",") if o.strip()]
        if not options_list:
            return st.text_input(label + " (нет вариантов)", key=widget_key)
        chosen = st.selectbox(label, options=[""] + options_list, key=widget_key)
        return chosen
    elif ctype == "bool":
        checked = st.checkbox(label, key=widget_key)
        return "1" if checked else "0"
    else:
        return st.text_input(label, key=widget_key)


def _j_format_value(col, raw_val: str, operators_list, machines_list) -> str:
    """Форматирует сохранённое строковое значение для отображения в таблице."""
    if raw_val is None:
        return ""
    ctype = col["col_type"]
    try:
        if ctype == "bool":
            return "✅" if raw_val == "1" else "☐"
        elif ctype == "operator":
            oid = int(raw_val) if raw_val else 0
            op  = next((o for o in operators_list if o["id"] == oid), None)
            return op["name"] if op else raw_val
        elif ctype == "machine":
            mid = int(raw_val) if raw_val else 0
            m   = next((m for m in machines_list if m["id"] == mid), None)
            return m["name"] if m else raw_val
        else:
            return raw_val
    except Exception:
        return raw_val


def page_journals(role, username):
    """
    Страница «📓 Журналы» — динамические журналы с настраиваемыми колонками.

    Права:
    - admin:  создание/редактирование/удаление журналов, просмотр и удаление записей
    - user:   добавление записей в журналы, просмотр
    - viewer: только просмотр
    """
    st.title("📓 Журналы")

    journals = _j_get_journals()
    operators_list = q("SELECT id, name FROM operators ORDER BY name")
    machines_list  = q("SELECT id, name, is_work_center FROM machines ORDER BY name")

    # ── А) Список журналов ────────────────────────────────────────────
    jcol_left, jcol_right = st.columns([3, 2])

    with jcol_left:
        st.markdown("### Доступные журналы")
        if not journals:
            st.info("Журналов пока нет. Администратор может создать журнал.")
        else:
            for j in journals:
                cols = _j_get_columns(j["id"])
                entries = _j_get_entries(j["id"])
                badge = f"**{j['name']}**  ({len(entries)} записей)"
                if j["description"]:
                    badge += f"  \n_{j['description']}_"
                st.markdown(badge)

    with jcol_right:
        if can("journals.manage"):
            with st.expander("➕ Создать новый журнал"):
                with st.form("create_journal_form", clear_on_submit=True):
                    jname = st.text_input("Название журнала *")
                    jdesc = st.text_area("Описание", height=60)
                    if st.form_submit_button("Создать", type="primary"):
                        if not jname.strip():
                            st.error("Укажите название журнала.")
                        else:
                            _j_create_journal(jname, jdesc, username)
                            st.success(f"✅ Журнал «{jname}» создан.")
                            st.rerun()

    if not journals:
        return

    st.divider()

    # ── Б) Выбор журнала ──────────────────────────────────────────────
    j_opts   = {j["name"]: j for j in journals}
    sel_jname = st.selectbox("Открыть журнал", options=list(j_opts.keys()),
                             key="journals_sel")
    sel_j    = j_opts[sel_jname]
    j_id     = sel_j["id"]
    j_cols   = _j_get_columns(j_id)

    tab_entries, tab_add, tab_cfg = st.tabs(
        ["📋 Записи", "➕ Добавить запись", "⚙️ Структура журнала"]
        if can("journals.add") else
        ["📋 Записи", "➕ Добавить запись (нет доступа)", "⚙️ Структура журнала"]
    )

    # ── В) Просмотр записей ───────────────────────────────────────────
    with tab_entries:
        entries = _j_get_entries(j_id)
        if not entries:
            st.info("Записей пока нет.")
        else:
            if not j_cols:
                st.warning("Структура журнала не настроена.")
            else:
                # Собираем таблицу
                table_rows = []
                for e in entries:
                    ev = _j_get_entry_values(e["id"])
                    row = {"Дата записи": e["created_at"][:16], "Внёс": e["created_by"]}
                    for col in j_cols:
                        raw = ev.get(col["id"], "")
                        row[col["col_name"]] = _j_format_value(
                            col, raw, operators_list, machines_list)
                    table_rows.append(row)
                df_j = pd.DataFrame(table_rows)
                st.dataframe(df_j, use_container_width=True, hide_index=True)

                # CSV экспорт
                csv_bytes = df_j.to_csv(index=False).encode("utf-8-sig")
                st.download_button(
                    "💾 Скачать журнал (CSV)", csv_bytes,
                    file_name=f"journal_{sel_jname.replace(' ','_')}.csv",
                    mime="text/csv", key="dl_journal_csv")

                # Удаление записей (только admin)
                if can("journals.manage"):
                    with st.expander("🗑 Удалить запись"):
                        del_entry_id = st.selectbox(
                            "Запись (ID — Дата)",
                            options=[e["id"] for e in entries],
                            format_func=lambda x: f"#{x} — " + next(
                                e["created_at"][:16] for e in entries if e["id"] == x),
                            key="del_journal_entry_sel")
                        if st.button("🗑 Удалить", key="del_journal_entry_btn", type="primary"):
                            _j_delete_entry(del_entry_id)
                            st.success("Запись удалена.")
                            st.rerun()

    # ── Г) Добавление записи ─────────────────────────────────────────
    with tab_add:
        if not can("journals.add"):
            st.info("👁 Добавление записей доступно только операторам и администраторам.")
        elif not j_cols:
            st.warning("Структура журнала не настроена. Попросите администратора добавить колонки.")
        else:
            st.markdown(f"#### Новая запись в журнал «{sel_jname}»")
            entry_vals = {}
            # Рендерим виджеты для каждой колонки
            for col in j_cols:
                val = _j_render_input(col,
                                      key_prefix=f"jentry_{j_id}",
                                      operators_list=operators_list,
                                      machines_list=machines_list)
                entry_vals[col["id"]] = val

            if st.button("💾 Сохранить запись", type="primary", key="save_journal_entry"):
                _j_save_entry(j_id, entry_vals, username)
                # Очищаем ключи виджетов этого журнала
                for col in j_cols:
                    st.session_state.pop(f"jentry_{j_id}_{col['id']}", None)
                    st.session_state.pop(f"jentry_{j_id}_{col['id']}_d", None)
                    st.session_state.pop(f"jentry_{j_id}_{col['id']}_t", None)
                st.success("✅ Запись сохранена.")
                st.rerun()

    # ── Д) Управление структурой (только admin) ──────────────────────
    with tab_cfg:
        if not can("journals.manage"):
            st.info("👁 Настройка структуры журнала доступна только администраторам.")
        else:
            st.markdown(f"#### Структура журнала «{sel_jname}»")

            # Текущие колонки
            if j_cols:
                cur_df = pd.DataFrame([{
                    "Порядок": c["col_order"],
                    "Название": c["col_name"],
                    "Тип": JOURNAL_COL_TYPES.get(c["col_type"], c["col_type"]),
                    "Варианты (для select)": c["col_options"],
                    "Единица": c["col_unit"],
                } for c in j_cols])
                st.dataframe(cur_df, use_container_width=True, hide_index=True)
            else:
                st.info("Колонки ещё не заданы.")

            st.markdown("---")
            st.markdown("**Добавить / переопределить колонки**")
            st.caption(
                "Существующие колонки обновляются на месте — значения записей сохраняются. "
                "Если уменьшить количество колонок, последние колонки скрываются из журнала, "
                "но их значения остаются в базе."
            )

            # Число колонок
            n_cols = st.number_input(
                "Количество колонок", min_value=1, max_value=20, step=1,
                value=max(1, len(j_cols)), key=f"jcfg_ncols_{j_id}")

            new_cols = []
            for i in range(int(n_cols)):
                existing = j_cols[i] if i < len(j_cols) else None
                st.markdown(f"**Колонка {i+1}**")
                cc1, cc2, cc3, cc4 = st.columns([3, 2, 3, 2])
                cname = cc1.text_input("Название",
                    value=existing["col_name"] if existing else "",
                    key=f"jcfg_name_{j_id}_{i}")
                ctype = cc2.selectbox("Тип",
                    options=list(JOURNAL_COL_TYPES.keys()),
                    format_func=lambda x: JOURNAL_COL_TYPES[x],
                    index=list(JOURNAL_COL_TYPES.keys()).index(existing["col_type"])
                          if existing and existing["col_type"] in JOURNAL_COL_TYPES else 0,
                    key=f"jcfg_type_{j_id}_{i}")
                copts = cc3.text_input("Варианты (через запятую, для select)",
                    value=existing["col_options"] if existing else "",
                    key=f"jcfg_opts_{j_id}_{i}")
                cunit = cc4.text_input("Единица",
                    value=existing["col_unit"] if existing else "",
                    key=f"jcfg_unit_{j_id}_{i}")
                new_cols.append({"id": existing["id"] if existing else None,
                                 "col_name": cname, "col_type": ctype,
                                 "col_options": copts, "col_unit": cunit})

            if st.button("💾 Сохранить структуру", type="primary", key=f"jcfg_save_{j_id}"):
                if any(not c["col_name"].strip() for c in new_cols):
                    st.error("Все колонки должны иметь название.")
                else:
                    _j_save_columns(j_id, new_cols)
                    st.success("✅ Структура журнала сохранена.")
                    st.rerun()

            st.divider()
            with st.expander("🗑 Удалить этот журнал"):
                st.warning(f"Удалить журнал **«{sel_jname}»** и все его записи? Действие необратимо.")
                if st.button("🗑 Подтвердить удаление журнала", type="primary",
                             key=f"del_journal_{j_id}"):
                    _j_delete_journal(j_id)
                    st.success(f"✅ Журнал «{sel_jname}» удалён.")
                    st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    init_db_once()

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
    st.session_state["perms"] = user_perms(cfg["credentials"]["usernames"].get(username, {}))

    # ── Sidebar ───────────────────────────────────────────────────────
    with st.sidebar:
        role_label = ROLE_LABELS.get(role, role)
        if role != "master" and isinstance(cfg["credentials"]["usernames"].get(username, {}).get("perms"), list):
            role_label += " · свои права"
        st.markdown(f"""
<div style="background:#2a2d40; border-radius:10px; padding:14px; margin-bottom:16px;">
  <div style="color:#56cfe1; font-weight:700; font-size:1.1rem;">🏭 НТА-Контроль</div>
  <div style="color:#8888aa; font-size:0.85rem; margin-top:4px;">
    👤 {html.escape(str(st.session_state.get('name') or username))}<br>
    🔑 {html.escape(role_label)}
  </div>
</div>
""", unsafe_allow_html=True)

        pages_order = {
            "⚙️ Станки":            "machines",
            "📋 История":           "history",
            "📋 Партии":            "batches",
            "📦 Прогресс партии":   "batch",
            "📓 Журналы":           "journals",
            "👥 Персонал / Станки": "crud",
            "📊 Графики":           "charts",
            "💾 Экспорт CSV":       "export",
            "🛠 Технология":        "tech",
            "📅 План станков":      "plan",
        }
        # страницы — по правам пользователя (роль задаёт права по умолчанию, master может изменить)
        all_pages = {k: v for k, v in pages_order.items() if can(f"page:{v}")}
        if not all_pages:
            st.warning("Нет доступа ни к одной странице — обратитесь к администратору.")
            authenticator.logout("🚪 Выйти", "sidebar")
            st.stop()

        page_keys = list(all_pages.keys())
        page_vals = list(all_pages.values())

        # ── Инициализация текущей страницы ─────────────────────────────
        # Единственный источник истины — session_state["_nav_page"].
        # st.radio управляется через этот ключ напрямую (key=).
        # Программные переходы (кнопки внутри страниц) пишут в тот же ключ
        # и вызывают st.rerun() — radio само встаёт на нужный пункт.
        #
        # Почему раньше был баг двойного клика:
        #   st.radio получал key="_sidebar_radio" И index=page_keys.index(_default_page).
        #   При ручном клике Streamlit записывал новый выбор в session_state["_sidebar_radio"],
        #   но код ниже сразу перезаписывал session_state["_sidebar_page"] и передавал
        #   старое значение в index= при следующем rerun — radio «возвращалось» назад.
        #   Со второго клика _sidebar_page уже успевал обновиться, поэтому переход срабатывал.

        if "_nav_page" not in st.session_state:
            st.session_state["_nav_page"] = page_keys[0]

        # Программный переход (nav_goto): пишем сразу в ключ radio
        _goto = st.session_state.pop("nav_goto", None)
        if _goto and _goto in page_vals:
            st.session_state["_nav_page"] = page_keys[page_vals.index(_goto)]

        # Если сохранённая страница недоступна для текущей роли — сбрасываем
        if st.session_state["_nav_page"] not in page_keys:
            st.session_state["_nav_page"] = page_keys[0]

        # st.radio читает и пишет session_state["_nav_page"] через key=.
        # index= НЕ используется — это исключает конфликт с ручным выбором.
        st.radio(
            "Навигация",
            page_keys,
            label_visibility="collapsed",
            key="_nav_page",
        )
        # Текущая страница — прямо из session_state (то, что выбрал radio или программный переход)
        page = st.session_state["_nav_page"]

        st.divider()
        if can("page:charts"):
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
    elif page_key == "journals":
        page_journals(role, username)
    elif page_key == "crud":
        page_admin_crud()
    elif page_key == "charts":
        page_charts()
    elif page_key == "export":
        page_export()
    elif page_key == "tech":
        tech.page_tech(q, tx, audit)
    elif page_key == "plan":
        plan.page_plan(q, tx, audit, all_batches, batch_is_archived)


if __name__ == "__main__":
    main()
