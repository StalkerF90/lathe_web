"""
=============================================================================
  СИСТЕМА КОНТРОЛЯ ТОКАРНЫХ СТАНКОВ — Streamlit Web App
  Роли: admin (полный доступ), user (просмотр + ввод выпуска)
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

# ── CSS ───────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Основной фон */
    [data-testid="stAppViewContainer"] { background: #0f1117; }
    [data-testid="stSidebar"] { background: #1a1d27; }
    [data-testid="stSidebar"] .stMarkdown { color: #c8c8e0; }

    /* Заголовки */
    h1, h2, h3 { color: #e0e0f0 !important; }
    .stDataFrame { border-radius: 8px; }

    /* Метрики */
    [data-testid="metric-container"] {
        background: #1e2130;
        border: 1px solid #2e3150;
        border-radius: 10px;
        padding: 12px 16px;
    }
    [data-testid="metric-container"] label { color: #8888aa !important; }
    [data-testid="metric-container"] [data-testid="stMetricValue"] {
        color: #7c6af7 !important; font-size: 2rem !important;
    }

    /* Статусные бейджи */
    .badge-busy   { background:#f94144; color:#fff; padding:3px 10px;
                    border-radius:12px; font-size:12px; font-weight:600; }
    .badge-free   { background:#43c59e; color:#000; padding:3px 10px;
                    border-radius:12px; font-size:12px; font-weight:600; }
    .badge-setup  { background:#f9c74f; color:#000; padding:3px 10px;
                    border-radius:12px; font-size:12px; font-weight:600; }
    .badge-idle   { background:#6c6c8a; color:#fff; padding:3px 10px;
                    border-radius:12px; font-size:12px; font-weight:600; }

    /* Карточки */
    .info-card {
        background: #1e2130; border: 1px solid #2e3150;
        border-radius: 10px; padding: 16px; margin-bottom: 12px;
    }
    .section-title {
        color: #56cfe1; font-size: 1.1rem;
        font-weight: 700; margin-bottom: 8px;
    }
    /* Убираем лишние отступы кнопок */
    .stButton button {
        border-radius: 6px; font-weight: 600;
    }
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
    if st.session_state.get("role") != "admin":
        st.error("⛔ Доступ запрещён. Требуются права администратора.")
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

STATUS_LABELS = {
    "busy":  "🔴 Занят",
    "free":  "🟢 Свободен",
    "setup": "🟡 Наладка",
    "idle":  "⚫ Простой",
}
STATUS_COLORS = {
    "busy": "#f94144", "free": "#43c59e",
    "setup": "#f9c74f", "idle": "#6c6c8a",
}

# ═══════════════════════════════════════════════════════════════════════════
#  СТРАНИЦЫ
# ═══════════════════════════════════════════════════════════════════════════

def page_machines(role):
    st.title("⚙️ Станки — текущее состояние")

    machines = q("""
        SELECT m.id, m.name, m.model, m.productivity, m.status, m.notes
        FROM machines m ORDER BY m.id
    """)

    if not machines:
        st.warning("Станки не найдены.")
        return

    # ── Статистика ─────────────────────────────────────────────────────
    counts = {s: 0 for s in STATUS_LABELS}
    for m in machines:
        counts[m["status"]] = counts.get(m["status"], 0) + 1

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🔴 Занят",    counts["busy"])
    c2.metric("🟢 Свободен", counts["free"])
    c3.metric("🟡 Наладка",  counts["setup"])
    c4.metric("⚫ Простой",  counts["idle"])

    st.divider()

    # ── Таблица станков ────────────────────────────────────────────────
    operators = q("SELECT id, name FROM operators ORDER BY name")
    op_map    = {0: "—"} | {o["id"]: o["name"] for o in operators}

    # Последний выпуск для каждого станка
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
            "ID":           m["id"],
            "Станок":       m["name"],
            "Модель":       m["model"],
            "Статус":       STATUS_LABELS.get(m["status"], m["status"]),
            "Партия":       lp.get("batch", "—"),
            "№ партии":     lp.get("batch_number", "—"),
            "Оператор":     lp.get("operator", "—"),
            "Наладка (ч)":  lp.get("setup_time", "—"),
            "Произв.д/ч":   m["productivity"],
            "Посл. дата":   lp.get("date", "—"),
            "Примечание":   m["notes"],
        })

    df = pd.DataFrame(df_rows)
    st.dataframe(df, use_container_width=True, hide_index=True,
                 column_config={
                     "Статус": st.column_config.TextColumn(width="small"),
                     "Произв.д/ч": st.column_config.NumberColumn(format="%.1f"),
                 })

    st.divider()

    # ── Ввод выпуска (User + Admin) ────────────────────────────────────
    st.markdown("### ➕ Внести выпуск")
    with st.form("production_form", clear_on_submit=True):
        cols = st.columns([2, 2, 1, 2, 1, 1, 1])
        sel_machine  = cols[0].selectbox("Станок*",
            options=[m["id"] for m in machines],
            format_func=lambda x: next(m["name"] for m in machines if m["id"] == x))
        sel_operator = cols[1].selectbox("Оператор",
            options=[0] + [o["id"] for o in operators],
            format_func=lambda x: op_map[x])
        prod_date    = cols[2].date_input("Дата*", value=date.today())
        batch_name   = cols[3].text_input("Название партии")
        batch_no     = cols[3].text_input("№ партии")
        setup_time   = cols[4].number_input("Наладка (ч)", min_value=0.0, step=0.25)
        produced_qty = cols[5].number_input("Выпущено*", min_value=0, step=1)
        notes_prod   = cols[6].text_input("Примечание")

        submitted = st.form_submit_button("✔ Записать", type="primary",
                                          use_container_width=True)
        if submitted:
            if produced_qty <= 0:
                st.error("Укажите количество выпущенных деталей.")
            else:
                sel_m = next(m for m in machines if m["id"] == sel_machine)
                actual = round(produced_qty / sel_m["productivity"], 3)
                exec_sql("""
                    INSERT INTO production
                    (date, machine_id, operator_id, batch, batch_number,
                     setup_time, produced_qty, actual_time, notes)
                    VALUES (?,?,?,?,?,?,?,?,?)
                """, (prod_date.isoformat(),
                      sel_machine,
                      sel_operator if sel_operator else None,
                      batch_name, batch_no,
                      setup_time, produced_qty, actual, notes_prod))
                st.success(f"✅ Записано: {produced_qty} шт  |  Факт. время: {actual:.2f} ч")
                st.rerun()

    # ── Admin: CRUD статусов ───────────────────────────────────────────
    if role == "admin":
        st.divider()
        st.markdown("### 🔧 Изменить статус станка")
        with st.form("status_form", clear_on_submit=True):
            sc1, sc2, sc3 = st.columns([3, 2, 1])
            ch_machine = sc1.selectbox("Станок",
                options=[m["id"] for m in machines],
                format_func=lambda x: next(m["name"] for m in machines if m["id"] == x))
            ch_status  = sc2.selectbox("Новый статус",
                options=list(STATUS_LABELS.keys()),
                format_func=lambda x: STATUS_LABELS[x])
            ch_notes   = sc3.text_input("Примечание")
            if st.form_submit_button("Обновить статус", use_container_width=True):
                exec_sql("UPDATE machines SET status=?, notes=? WHERE id=?",
                         (ch_status, ch_notes, ch_machine))
                st.success("✅ Статус обновлён")
                st.rerun()


def page_history(role):
    st.title("📋 История выпуска")

    # ── Кнопка «Очистить всю историю» — только для admin ──────────────
    if role == "admin":
        # Состояние диалога подтверждения хранится в session_state
        if "confirm_clear_history" not in st.session_state:
            st.session_state["confirm_clear_history"] = False

        total_count = q("SELECT COUNT(*) AS cnt FROM production", fetch="one")
        total_cnt   = total_count["cnt"] if total_count else 0

        col_title, col_btn = st.columns([8, 2])
        with col_btn:
            if not st.session_state["confirm_clear_history"]:
                if st.button("🗑 Очистить всю историю", type="primary",
                             use_container_width=True,
                             disabled=(total_cnt == 0)):
                    st.session_state["confirm_clear_history"] = True
                    st.rerun()
            else:
                # Диалог подтверждения
                st.warning(
                    "⚠️ **Вы уверены?**\n\n"
                    "Вы хотите удалить **ВСЮ** историю выпуска "
                    f"({total_cnt} записей). Это действие **невозможно отменить**."
                )
                yes_col, no_col = st.columns(2)
                with yes_col:
                    if st.button("✔ Да, удалить всё", type="primary",
                                 use_container_width=True):
                        exec_sql("DELETE FROM production")
                        st.session_state["confirm_clear_history"] = False
                        st.success("✅ Вся история выпуска удалена.")
                        st.rerun()
                with no_col:
                    if st.button("✘ Отмена", use_container_width=True):
                        st.session_state["confirm_clear_history"] = False
                        st.rerun()

    # ── Фильтры ────────────────────────────────────────────────────────
    with st.expander("🔍 Фильтры", expanded=True):
        fc1, fc2, fc3, fc4 = st.columns(4)
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

    sql = """
        SELECT p.id, p.date, m.name AS machine, o.name AS operator,
               p.batch, p.batch_number,
               p.setup_time, p.produced_qty, p.actual_time, p.notes
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
    sql += " ORDER BY p.date DESC, p.id DESC"

    rows = q(sql, params)

    # ── Нулевое состояние: пустая таблица — просто сообщение ──────────
    if not rows:
        any_records = q("SELECT COUNT(*) AS cnt FROM production", fetch="one")
        if any_records and any_records["cnt"] == 0:
            st.info("📭 Записей пока нет. Используйте форму «Внести выпуск» на странице «Станки».")
        else:
            st.info("Нет записей, соответствующих выбранным фильтрам.")
        return

    df = pd.DataFrame(rows)
    df.columns = ["ID", "Дата", "Станок", "Оператор", "Партия", "№ партии",
                  "Наладка (ч)", "Выпущено", "Факт. время (ч)", "Примечание"]

    # Итоги
    total_qty  = df["Выпущено"].sum()
    total_time = df["Факт. время (ч)"].sum()
    m1, m2, m3 = st.columns(3)
    m1.metric("Записей",        len(df))
    m2.metric("Всего выпущено", f"{total_qty:,} шт")
    m3.metric("Суммарно часов", f"{total_time:.1f} ч")

    st.divider()

    # Таблица
    if role == "admin":
        st.markdown("*Для удаления одной записи — введите её ID в форме ниже*")

    st.dataframe(df.drop(columns=["ID"] if role != "admin" else []),
                 use_container_width=True, hide_index=True,
                 column_config={
                     "Выпущено":        st.column_config.NumberColumn(format="%d шт"),
                     "Факт. время (ч)": st.column_config.NumberColumn(format="%.2f"),
                 })

    if role == "admin":
        st.divider()
        with st.form("delete_prod", clear_on_submit=True):
            del_id = st.number_input("ID записи для удаления", min_value=1, step=1)
            if st.form_submit_button("🗑 Удалить запись", type="primary"):
                exec_sql("DELETE FROM production WHERE id=?", (del_id,))
                st.success(f"Запись #{del_id} удалена.")
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
            df_m.columns = ["ID", "Название", "Модель", "Произв.д/ч",
                             "Статус", "Примечание"]
            df_m["Статус"] = df_m["Статус"].map(STATUS_LABELS)
            st.dataframe(df_m, use_container_width=True, hide_index=True)

        st.markdown("#### ➕ Добавить станок")
        with st.form("add_machine", clear_on_submit=True):
            mc1, mc2, mc3, mc4 = st.columns([3, 2, 1, 2])
            m_name  = mc1.text_input("Название*")
            m_model = mc2.text_input("Модель")
            m_prod  = mc3.number_input("Произв.д/ч", min_value=0.1, value=10.0, step=0.5)
            m_notes = mc4.text_input("Примечание")
            if st.form_submit_button("Добавить", type="primary"):
                if not m_name:
                    st.error("Укажите название станка.")
                else:
                    exec_sql("INSERT INTO machines (name,model,productivity,notes) VALUES (?,?,?,?)",
                             (m_name, m_model, m_prod, m_notes))
                    st.success(f"Станок «{m_name}» добавлен.")
                    st.rerun()

        st.markdown("#### ✏️ Редактировать станок")
        with st.form("edit_machine", clear_on_submit=True):
            machines_now = q("SELECT id, name FROM machines ORDER BY id")
            em1, em2, em3, em4, em5 = st.columns([2, 3, 2, 1, 2])
            e_id    = em1.selectbox("Станок",
                options=[m["id"] for m in machines_now],
                format_func=lambda x: f"#{x} {next(m['name'] for m in machines_now if m['id']==x)}")
            e_name  = em2.text_input("Новое название")
            e_model = em3.text_input("Модель")
            e_prod  = em4.number_input("Произв.", min_value=0.1, value=10.0, step=0.5)
            e_notes = em5.text_input("Примечание")
            e_status = st.selectbox("Статус",
                options=list(STATUS_LABELS.keys()),
                format_func=lambda x: STATUS_LABELS[x])
            if st.form_submit_button("Сохранить изменения"):
                updates, vals = [], []
                if e_name:  updates.append("name=?");         vals.append(e_name)
                if e_model: updates.append("model=?");        vals.append(e_model)
                updates.append("productivity=?"); vals.append(e_prod)
                updates.append("status=?");       vals.append(e_status)
                updates.append("notes=?");        vals.append(e_notes)
                vals.append(e_id)
                exec_sql(f"UPDATE machines SET {', '.join(updates)} WHERE id=?", vals)
                st.success("✅ Станок обновлён.")
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
            new_role  = uu4.selectbox("Роль", ["user", "admin"])
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
    require_admin()
    st.title("📊 Графики и аналитика")

    col_ctrl1, col_ctrl2 = st.columns([1, 3])
    days = col_ctrl1.slider("Период (дней)", 7, 90, 14)
    since = (date.today() - timedelta(days=days)).isoformat()

    data = q("""
        SELECT p.date, m.name AS machine, m.productivity,
               o.name AS operator,
               p.produced_qty, p.actual_time, p.setup_time
        FROM production p
        LEFT JOIN machines  m ON m.id = p.machine_id
        LEFT JOIN operators o ON o.id = p.operator_id
        WHERE p.date >= ?
        ORDER BY p.date
    """, (since,))

    if not data:
        st.warning("Нет данных за выбранный период.")
        return

    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"])

    tab1, tab2, tab3, tab4 = st.tabs([
        "📈 Загрузка по дням",
        "🏭 Выпуск по станкам",
        "👤 По операторам",
        "⚡ Производительность",
    ])

    # ── График 1: Загрузка по дням ─────────────────────────────────
    with tab1:
        daily = df.groupby(["date", "machine"])["produced_qty"].sum().reset_index()
        fig = px.bar(daily, x="date", y="produced_qty", color="machine",
                     barmode="group", title=f"Загрузка станков по дням ({days} дней)",
                     labels={"date": "Дата", "produced_qty": "Выпущено (шт)",
                             "machine": "Станок"},
                     template="plotly_dark",
                     color_discrete_sequence=px.colors.qualitative.Bold)
        fig.update_layout(
            plot_bgcolor="#1e2130", paper_bgcolor="#0f1117",
            font_color="#e0e0f0", legend_title_text="Станок",
            xaxis=dict(tickformat="%d.%m"),
        )
        st.plotly_chart(fig, use_container_width=True)

        # Тепловая карта
        pivot = daily.pivot_table(
            index="machine", columns=df["date"].dt.strftime("%d.%m").unique()[:len(daily["date"].unique())],
            values="produced_qty", fill_value=0, aggfunc="sum"
        )
        if not pivot.empty:
            pivot2 = daily.pivot_table(index="machine", columns="date",
                                       values="produced_qty", fill_value=0, aggfunc="sum")
            pivot2.columns = pivot2.columns.strftime("%d.%m")
            fig_hm = px.imshow(pivot2, title="Тепловая карта загрузки",
                               template="plotly_dark",
                               color_continuous_scale="Blues",
                               labels=dict(color="Шт."))
            fig_hm.update_layout(paper_bgcolor="#0f1117", font_color="#e0e0f0")
            st.plotly_chart(fig_hm, use_container_width=True)

    # ── График 2: Выпуск по станкам ────────────────────────────────
    with tab2:
        by_machine = df.groupby("machine")["produced_qty"].sum().reset_index()
        by_machine.columns = ["Станок", "Выпущено"]
        by_machine = by_machine.sort_values("Выпущено", ascending=False)

        c1, c2 = st.columns(2)
        with c1:
            fig_bar = px.bar(by_machine, x="Станок", y="Выпущено",
                             title="Суммарный выпуск",
                             template="plotly_dark",
                             color="Выпущено",
                             color_continuous_scale="Viridis",
                             text="Выпущено")
            fig_bar.update_traces(textposition="outside")
            fig_bar.update_layout(paper_bgcolor="#0f1117", plot_bgcolor="#1e2130",
                                  font_color="#e0e0f0", showlegend=False)
            st.plotly_chart(fig_bar, use_container_width=True)
        with c2:
            fig_pie = px.pie(by_machine, names="Станок", values="Выпущено",
                             title="Доля выпуска",
                             template="plotly_dark",
                             hole=0.4)
            fig_pie.update_layout(paper_bgcolor="#0f1117", font_color="#e0e0f0")
            st.plotly_chart(fig_pie, use_container_width=True)

        # Суммарное время наладки
        setup_total = df.groupby("machine")["setup_time"].sum().reset_index()
        setup_total.columns = ["Станок", "Время наладки (ч)"]
        fig_setup = px.bar(setup_total.sort_values("Время наладки (ч)", ascending=False),
                           x="Станок", y="Время наладки (ч)",
                           title="Суммарное время наладки",
                           template="plotly_dark",
                           color_discrete_sequence=["#f9c74f"])
        fig_setup.update_layout(paper_bgcolor="#0f1117", plot_bgcolor="#1e2130",
                                font_color="#e0e0f0")
        st.plotly_chart(fig_setup, use_container_width=True)

    # ── График 3: По операторам ────────────────────────────────────
    with tab3:
        df_op = df[df["operator"].notna()]
        if df_op.empty:
            st.info("Нет данных по операторам.")
        else:
            by_op = df_op.groupby("operator")["produced_qty"].sum().reset_index()
            by_op.columns = ["Оператор", "Выпущено"]
            by_op = by_op.sort_values("Выпущено", ascending=True)

            fig_op = px.bar(by_op, y="Оператор", x="Выпущено",
                            orientation="h", title="Выпуск по операторам",
                            template="plotly_dark",
                            color="Выпущено",
                            color_continuous_scale="Sunset",
                            text="Выпущено")
            fig_op.update_traces(textposition="outside")
            fig_op.update_layout(paper_bgcolor="#0f1117", plot_bgcolor="#1e2130",
                                 font_color="#e0e0f0", showlegend=False,
                                 height=max(300, len(by_op) * 60))
            st.plotly_chart(fig_op, use_container_width=True)

            # Динамика по операторам
            op_daily = df_op.groupby(["date", "operator"])["produced_qty"].sum().reset_index()
            fig_op2 = px.line(op_daily, x="date", y="produced_qty", color="operator",
                              title="Динамика выпуска по операторам",
                              template="plotly_dark",
                              labels={"date": "Дата", "produced_qty": "Выпущено",
                                      "operator": "Оператор"},
                              markers=True)
            fig_op2.update_layout(paper_bgcolor="#0f1117", plot_bgcolor="#1e2130",
                                  font_color="#e0e0f0",
                                  xaxis=dict(tickformat="%d.%m"))
            st.plotly_chart(fig_op2, use_container_width=True)

    # ── График 4: Производительность ──────────────────────────────
    with tab4:
        machines_all = q("SELECT id, name, productivity FROM machines ORDER BY id")
        if not machines_all:
            st.info("Нет данных.")
        else:
            # Фактическая производительность = выпущено / фактическое_время
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
                title="Производительность: норма vs факт (ср. за период)",
                barmode="group", template="plotly_dark",
                paper_bgcolor="#0f1117", plot_bgcolor="#1e2130",
                font_color="#e0e0f0", legend=dict(bgcolor="#1e2130"))
            st.plotly_chart(fig_cmp, use_container_width=True)

            # КПИ эффективности
            df_cmp["Эффективность %"] = (
                df_cmp["Факт д/ч"] / df_cmp["Норма д/ч"] * 100
            ).round(1).fillna(0)
            df_cmp_show = df_cmp[["Станок", "Норма д/ч", "Факт д/ч", "Эффективность %"]]
            st.dataframe(
                df_cmp_show.style.background_gradient(
                    subset=["Эффективность %"], cmap="RdYlGn", vmin=0, vmax=120),
                use_container_width=True, hide_index=True)


def page_export():
    require_admin()
    st.title("💾 Экспорт данных")

    machines  = q("SELECT * FROM machines ORDER BY id")
    operators = q("SELECT * FROM operators ORDER BY id")
    production = q("""
        SELECT p.id, p.date, m.name AS machine, o.name AS operator,
               p.batch, p.batch_number, p.setup_time,
               p.produced_qty, p.actual_time, p.notes
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
                       ["id","date","machine","operator","batch","batch_number",
                        "setup_time","produced_qty","actual_time","notes"])
        st.download_button("⬇ CSV: История", csv_p,
                           f"production_{date.today()}.csv", "text/csv",
                           use_container_width=True)

    st.divider()
    st.markdown("### 📊 Сводный отчёт по станкам")
    summary = q("""
        SELECT m.name AS Станок,
               COUNT(p.id)           AS Записей,
               SUM(p.produced_qty)   AS "Итого выпущено",
               ROUND(SUM(p.actual_time),2) AS "Факт. часов",
               ROUND(AVG(p.produced_qty / NULLIF(p.actual_time,0)),1) AS "Ср. произв. д/ч",
               ROUND(SUM(p.setup_time),2) AS "Суммарная наладка ч"
        FROM machines m
        LEFT JOIN production p ON p.machine_id = m.id
        GROUP BY m.id
        ORDER BY m.id
    """)
    df_sum = pd.DataFrame(summary)
    st.dataframe(df_sum, use_container_width=True, hide_index=True)
    csv_s = to_csv(summary, list(df_sum.columns))
    st.download_button("⬇ CSV: Сводный отчёт", csv_s,
                       f"summary_{date.today()}.csv", "text/csv")

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
        st.markdown(f"""
<div style="background:#2a2d40; border-radius:10px; padding:14px; margin-bottom:16px;">
  <div style="color:#56cfe1; font-weight:700; font-size:1.1rem;">⚙️ НТА Контроль</div>
  <div style="color:#8888aa; font-size:0.85rem; margin-top:4px;">
    👤 {st.session_state.get('name', username)}<br>
    🔑 {'Администратор' if role == 'admin' else 'Оператор'}
  </div>
</div>
""", unsafe_allow_html=True)

        pages_all = {
            "⚙️ Станки":            "machines",
            "📋 История":           "history",
        }
        pages_admin = {
            "👥 Персонал / Станки": "crud",
            "📊 Графики":           "charts",
            "💾 Экспорт CSV":       "export",
        }

        all_pages = dict(pages_all)
        if role == "admin":
            all_pages.update(pages_admin)

        page = st.radio("Навигация", list(all_pages.keys()),
                        label_visibility="collapsed")

        st.divider()
        if role == "admin":
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
    elif page_key == "crud":
        page_admin_crud()
    elif page_key == "charts":
        page_charts()
    elif page_key == "export":
        page_export()


if __name__ == "__main__":
    main()
