"""
=============================================================================
  НТА-Контроль — план загрузки станков (только администратор)
=============================================================================
Партии из вкладки «Партии» ставятся на станки по маршрутам из модуля технологии;
время = наладка + выпуск (мин/шт по истории / похожему артикулу / вручную),
отсчитывается по рабочему времени (workcal: смены, обеды, выходные, праздники).

Правила раскладки:
  • партия непрерывна (идёт через обеды, ночи и выходные без разрыва, но только в рабочее время);
  • новую партию не начинают, если до конца рабочего дня (последней смены) меньше 2 ч;
  • маршрут-связка (235 + 2100) стартует на обоих станках одновременно;
  • наладка: 4 ч с нуля; 30 мин, если артикул уже делали на этом станке; 2 ч, если у предыдущей
    партии на станке тот же HEX и тот же обжимной торец;
  • ремонт и обслуживание — фиксированные блоки по календарю, партии обходят их;
  • при перетаскивании партия встаёт куда поставили, пересекающиеся сдвигаются вперёд.
"""
import json
import os
import uuid
from datetime import date, datetime, time, timedelta

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import tech
import workcal

KINDS = ["партия", "ремонт", "обслуживание"]
DEFAULT_MACHINES = ["Lathe 235", "Lathe 2100", "Lathe 2105", "АПТ", "MILL"]
SETUP_FULL_H, SETUP_SAME_HEX_END_H, SETUP_MADE_H = 4.0, 2.0, 0.5
MIN_LEFT_H = 2.0
FMT = "%Y-%m-%d %H:%M"

_timeline = components.declare_component(
    "plan_timeline", path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "plan_timeline"))


# ═══════════════════════════════════════════════════════════════════════════
#  БАЗА
# ═══════════════════════════════════════════════════════════════════════════

def init_tables(c):
    """Создаёт таблицы плана (вызывается из app.init_db). Только CREATE IF NOT EXISTS."""
    c.executescript("""
        CREATE TABLE IF NOT EXISTS plan_shifts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            valid_from  TEXT NOT NULL,              -- режим действует с этой даты (все смены с этой датой)
            shift_no    INTEGER NOT NULL,
            shift_start TEXT NOT NULL,              -- 07:00
            shift_end   TEXT NOT NULL,              -- 15:30
            lunch_start TEXT DEFAULT '',            -- 11:00
            lunch_min   INTEGER DEFAULT 30,
            notes       TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS plan_calendar (
            day   TEXT PRIMARY KEY,                 -- 2026-11-04
            kind  TEXT NOT NULL,                    -- выходной | рабочий (исключение из пн–сб)
            note  TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS plan_items (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            kind         TEXT NOT NULL DEFAULT 'партия',   -- партия | ремонт | обслуживание
            batch_number TEXT DEFAULT '',
            qty          INTEGER,
            machine      TEXT NOT NULL,
            grp          TEXT DEFAULT '',           -- одна постановка партии (связка 235+2100 — два станка)
            linked       INTEGER DEFAULT 0,         -- 1 = станки группы стартуют одновременно
            route        TEXT DEFAULT '',
            start_at     TEXT NOT NULL,             -- YYYY-MM-DD HH:MM
            end_at       TEXT NOT NULL,
            setup_h      REAL,
            setup_why    TEXT DEFAULT '',
            min_pc       REAL,
            run_h        REAL,
            hours_manual REAL,                      -- длительность, заданная растягиванием (рабочие часы)
            notes        TEXT DEFAULT '',
            created_by   TEXT DEFAULT '',
            created_at   TEXT,
            updated_at   TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_plan_items_machine ON plan_items(machine, start_at);
        CREATE TABLE IF NOT EXISTS plan_settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    c.execute("INSERT OR IGNORE INTO plan_settings (key, value) VALUES ('machines', ?)", (", ".join(DEFAULT_MACHINES),))
    if c.execute("SELECT COUNT(*) FROM plan_shifts").fetchone()[0] == 0:
        c.executemany("INSERT INTO plan_shifts (valid_from, shift_no, shift_start, shift_end, lunch_start, lunch_min, notes) "
                      "VALUES (?,?,?,?,?,?,?)",
                      [("2026-10-01", s["shift_no"], s["start"], s["end"], s["lunch_start"], s["lunch_min"],
                        "2 смены (по умолчанию)") for s in workcal.DEFAULT_SHIFTS])


def _dt(s) -> datetime:
    return s if isinstance(s, datetime) else datetime.strptime(str(s).replace("T", " ")[:16], FMT)


def _rm(d: datetime) -> datetime:
    """Округление до минуты."""
    return (d + timedelta(seconds=30)).replace(second=0, microsecond=0)


def _s(d: datetime) -> str:
    """Время → строка с точностью до минуты (с округлением, а не отбрасыванием секунд)."""
    return _rm(d).strftime(FMT)


def _minutes_h(hours: float) -> float:
    """Часы, округлённые до целых минут."""
    return round(hours * 60) / 60


def load_ctx(q) -> dict:
    """Режим смен, календарь исключений, станки плана."""
    shifts = [workcal.norm_shift(r) for r in q("SELECT * FROM plan_shifts")]
    cal ={r["day"]: r["kind"] for r in q("SELECT day, kind FROM plan_calendar")}
    ms = q("SELECT value FROM plan_settings WHERE key='machines'", fetch="one")
    machines = tech.parse_machines(ms["value"]) if ms and ms.get("value") else tuple(DEFAULT_MACHINES)
    return {"shifts": shifts, "cal": cal, "machines": list(machines)}


def load_items(q) -> list[dict]:
    """Позиции плана; в Python время — ключи start / end (в базе start_at / end_at)."""
    rows = q("SELECT * FROM plan_items ORDER BY start_at, id")
    return [dict({k: v for k, v in r.items() if k not in ("start_at", "end_at")}, start=r["start_at"], end=r["end_at"])
            for r in rows]


# ═══════════════════════════════════════════════════════════════════════════
#  РАСКЛАДКА (чистая логика — без Streamlit и базы)
# ═══════════════════════════════════════════════════════════════════════════

def item_hours(it: dict) -> float:
    """Рабочие часы партии на станке: заданные вручную или наладка + выпуск."""
    if it.get("hours_manual") is not None:
        return float(it["hours_manual"])
    return float(it.get("setup_h") or 0) + float(it.get("run_h") or 0)


def same_hex_end(a: dict | None, b: dict | None) -> bool:
    """Тот же HEX и общий обжимной торец (art: {key, hex, tubes})."""
    if not a or not b or not a.get("hex") or not b.get("hex"):
        return False
    return abs(float(a["hex"]) - float(b["hex"])) < 1e-6 and bool(set(a.get("tubes") or ()) & set(b.get("tubes") or ()))


def setup_rule(machine: str, art: dict | None, prev_art: dict | None, made: set) -> tuple[float, str]:
    """Наладка партии на станке: 30 мин, если артикул тут уже делали; 2 ч, если предыдущая партия
    на станке с тем же HEX и обжимным торцом; иначе 4 ч."""
    key = (art or {}).get("key")
    if key and (machine, key) in made:
        return SETUP_MADE_H, "артикул уже делали на этом станке"
    if same_hex_end(art, prev_art):
        return SETUP_SAME_HEX_END_H, f"предыдущая {prev_art.get('key')}: тот же HEX и обжимной торец"
    return SETUP_FULL_H, "полная наладка"


def units_of(items: list[dict]) -> list[list[dict]]:
    """Постановки: связанные позиции (одна группа, linked) — одна единица, остальные по одной."""
    out, by_grp = [], {}
    for it in items:
        if it.get("kind") == "партия" and it.get("linked") and it.get("grp"):
            if it["grp"] not in by_grp:
                by_grp[it["grp"]] = []
                out.append(by_grp[it["grp"]])
            by_grp[it["grp"]].append(it)
        else:
            out.append([it])
    return out


def _overlap_end(busy: dict, machine: str, s: datetime, e: datetime):
    """Конец самого позднего занятого интервала станка, пересекающего [s, e), или None."""
    hit = [be for bs, be in busy.get(machine, []) if bs < e and be > s]
    return max(hit) if hit else None


def place_unit(unit: list[dict], earliest: datetime, busy: dict, shifts, cal) -> datetime:
    """Первый допустимый старт ≥ earliest: правило 2 ч, общий старт для связки, без пересечений."""
    t = earliest
    for _ in range(2000):
        s = _rm(workcal.first_start(t, shifts, cal, MIN_LEFT_H))
        conflict = None
        for it in unit:
            e = _rm(workcal.add_work_hours(s, item_hours(it), shifts, cal))
            ce = _overlap_end(busy, it["machine"], s, max(e, s + timedelta(minutes=1)))
            if ce is not None and (conflict is None or ce > conflict):
                conflict = ce
        if conflict is None:
            return s
        t = conflict
    return t


def reflow(items: list[dict], ctx: dict, arts: dict, made_hist: set, anchor_grp=None, anchor_id=None) -> list[dict]:
    """Пересчитывает наладку и время всех позиций плана.
    items — копии строк plan_items; arts — {batch_number: {key, hex, tubes}}; made_hist — {(станок, ключ)} из истории.
    Позиция-«якорь» (только что поставленная или перетащенная) стоит, где поставили; остальные сохраняют
    время, если ни с чем не пересекаются, иначе сдвигаются вперёд. Ремонт/обслуживание не двигаются."""
    shifts, cal = ctx["shifts"], ctx["cal"]
    items = [dict(it) for it in items]
    fixed = {}
    for it in items:
        if it["kind"] != "партия":
            fixed.setdefault(it["machine"], []).append((_dt(it["start"]), _dt(it["end"])))
    units = [u for u in units_of(items) if u[0]["kind"] == "партия"]

    def is_anchor(u):
        return any((anchor_grp and it.get("grp") == anchor_grp) or (anchor_id and it.get("id") == anchor_id) for it in u)

    for _ in range(6):                               # наладка зависит от порядка → до стабилизации
        order = sorted(units, key=lambda u: (not is_anchor(u), min(_dt(it["start"]) for it in u), u[0].get("id") or 0))
        busy = {m: list(v) for m, v in fixed.items()}
        for u in order:
            s = place_unit(u, min(_dt(it["start"]) for it in u), busy, shifts, cal)
            for it in u:
                e = _rm(workcal.add_work_hours(s, item_hours(it), shifts, cal))
                it["start"], it["end"] = _s(s), _s(e)
                busy.setdefault(it["machine"], []).append((s, e))
        # наладка по фактическому порядку на станке
        changed = False
        made = set(made_hist)
        prev = {}
        for it in sorted([i for i in items if i["kind"] == "партия"], key=lambda i: (_dt(i["start"]), i.get("id") or 0)):
            art = arts.get(it.get("batch_number"))
            h, why = setup_rule(it["machine"], art, prev.get(it["machine"]), made)
            if it.get("setup_h") is None or abs(float(it["setup_h"]) - h) > 1e-9:
                changed = True
            it["setup_h"], it["setup_why"] = h, why
            prev[it["machine"]] = art
            if art and art.get("key"):
                made.add((it["machine"], art["key"]))
        if not changed:
            break
    return items


def conflicts(items: list[dict]) -> list[str]:
    """Проверка результата: пересечения на станке, связка не в один момент."""
    out = []
    by_m = {}
    for it in items:
        by_m.setdefault(it["machine"], []).append(it)
    for m, lst in by_m.items():
        lst = sorted(lst, key=lambda i: _dt(i["start"]))
        for a, b in zip(lst, lst[1:]):
            if _dt(b["start"]) < _dt(a["end"]):
                out.append(f"{m}: «{label(a)}» и «{label(b)}» пересекаются")
    for u in units_of(items):
        if len(u) > 1 and len({it["start"] for it in u}) > 1:
            out.append(f"связка {label(u[0])}: станки стартуют не одновременно")
    return out


def label(it: dict) -> str:
    if it["kind"] != "партия":
        return f"{it['kind']}" + (f": {it['notes']}" if it.get("notes") else "")
    return f"№{it['batch_number']}"


# ═══════════════════════════════════════════════════════════════════════════
#  ДАННЫЕ ДЛЯ РАСКЛАДКИ
# ═══════════════════════════════════════════════════════════════════════════

def article_info(q, batches: list[dict]) -> dict:
    """{batch_number: {key, hex, tubes, name, parsed}} по названию партии и справочнику артикулов."""
    hexes = {r["article_key"]: r["hex_mm"] for r in q("SELECT article_key, hex_mm FROM tech_articles")}
    out = {}
    for b in batches:
        p = tech.parse_article(b.get("batch_name") or "")
        key = p.get("key")
        tubes = tuple(sorted({e.get("code") for e in p.get("ends", []) if e.get("slot") == "tube" and e.get("code")}))
        out[b["batch_number"]] = {"key": key, "hex": hexes.get(key), "tubes": tubes, "name": b.get("batch_name") or "",
                                  "parsed": p}
    return out


def made_from_history(hist: pd.DataFrame) -> set:
    if hist is None or hist.empty:
        return set()
    lathe = hist[(hist["wc"] == 0) & hist["key"].notna()]
    return set(zip(lathe["machine"], lathe["key"]))


def save_items(tx, audit, before: list[dict], after: list[dict], new_items=(), deleted_ids=()):
    """Записывает изменения плана одной транзакцией (с журналом изменений)."""
    cols = ["kind", "batch_number", "qty", "machine", "grp", "linked", "route", "start", "end", "setup_h", "setup_why",
            "min_pc", "run_h", "hours_manual", "notes"]
    old = {it["id"]: it for it in before if it.get("id")}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    qc = lambda c: {"start": "start_at", "end": "end_at"}.get(c, c)
    ids = {}
    with tx() as conn:
        for rid in deleted_ids:
            o = old.get(rid)
            conn.execute("DELETE FROM plan_items WHERE id=?", (rid,))
            audit(conn, "delete", "plan_items", rid, o)
        for it in after:
            rid = it.get("id")
            if not rid:
                continue
            o = old.get(rid)
            diff = {c: it.get(c) for c in cols if o is None or o.get(c) != it.get(c)}
            if o is not None and diff:
                conn.execute(f"UPDATE plan_items SET {', '.join(qc(c) + '=?' for c in diff)}, updated_at=? WHERE id=?",
                             (*diff.values(), now, rid))
                audit(conn, "update", "plan_items", rid, {c: o.get(c) for c in diff}, diff)
        for it in new_items:
            vals = [it.get(c) for c in cols]
            cur = conn.execute(f"INSERT INTO plan_items ({', '.join(qc(c) for c in cols)}, created_by, created_at, updated_at) "
                               f"VALUES ({', '.join('?' * len(cols))}, ?, ?, ?)",
                               (*vals, st.session_state.get("username") or "", now, now))
            ids[it.get("_tmp")] = cur.lastrowid
            audit(conn, "insert", "plan_items", cur.lastrowid, None, {c: it.get(c) for c in cols})
    return ids


def apply_change(q, tx, audit, ctx, items, arts, made, *, changed=None, anchor_grp=None, anchor_id=None,
                 new_items=(), deleted_ids=()):
    """Пересчитать план с изменением и сохранить. items — план как в базе (до изменения),
    changed — тот же план с правкой пользователя. Возвращает (ok, сообщение)."""
    work = [dict(it) for it in (changed if changed is not None else items) if it["id"] not in set(deleted_ids)]
    anchor_ids = {n.get("grp") for n in new_items}
    if new_items and not anchor_grp:                 # новая позиция — якорь
        anchor_grp = next(iter(anchor_ids))
    tmp = []
    for i, n in enumerate(new_items):
        n = dict(n, _tmp=f"new{i}", id=None)
        tmp.append(n)
        work.append(n)
    res = reflow(work, ctx, arts, made, anchor_grp=anchor_grp, anchor_id=anchor_id)
    bad = conflicts(res)
    if bad:
        return False, "План не сохранён: " + "; ".join(bad[:3])
    by_tmp = {it.get("_tmp"): it for it in res if it.get("_tmp")}
    save_items(tx, audit, items, [it for it in res if it.get("id")],
               new_items=[by_tmp[n["_tmp"]] for n in tmp], deleted_ids=deleted_ids)
    own = {it["id"] for it in items if it["id"] == anchor_id or (anchor_grp and it.get("grp") == anchor_grp)}
    moved = sum(1 for it in res if it.get("id") and it["id"] not in own and any(
        o["id"] == it["id"] and o["start"] != it["start"] for o in items))
    return True, f"План сохранён. Сдвинуто других позиций: {moved}." if moved else "План сохранён."


# ═══════════════════════════════════════════════════════════════════════════
#  СТРАНИЦА
# ═══════════════════════════════════════════════════════════════════════════

_PALETTE = ["#7fb3d5", "#82e0aa", "#f8c471", "#bb8fce", "#76d7c4", "#f1948a", "#aed6f1", "#d7bde2",
            "#a9dfbf", "#fad7a0", "#85c1e9", "#f5b7b1"]


def _color(s: str) -> str:
    return _PALETTE[sum(ord(ch) for ch in str(s)) % len(_PALETTE)]


def page_plan(q, tx, audit, all_batches, batch_is_archived):
    if st.session_state.get("role") != "admin":
        st.error("⛔ План станков доступен только администратору.")
        st.stop()
    st.title("📅 План станков")
    t_g, t_l, t_s, t_c = st.tabs(["🗓 График", "📋 Список и факт", "⏱ Режим смен", "📆 Праздники и выходные"])
    with t_g:
        _tab_gantt(q, tx, audit, all_batches, batch_is_archived)
    with t_l:
        _tab_list(q)
    with t_s:
        _tab_shifts(q, tx, audit)
    with t_c:
        _tab_calendar(q, tx, audit)


def _flash(msg_key="plan_flash"):
    m = st.session_state.pop(msg_key, None)
    if m:
        (st.success if m[0] else st.error)(m[1])


def _background(ctx, d0: date, d1: date) -> list[dict]:
    """Нерабочее время (ночь, выходные, праздники) — фон графика."""
    out, d, prev_end = [], d0, datetime.combine(d0, time(0))
    while d <= d1:
        periods = workcal.day_periods(d, ctx["shifts"], ctx["cal"])
        holiday = ctx["cal"].get(d.isoformat()) == "выходной"
        for p in periods:
            if p["start"] > prev_end:
                out.append((prev_end, p["start"], False))
            prev_end = max(prev_end, p["end"])
        if not periods and holiday:
            out.append((datetime.combine(d, time(0)), datetime.combine(d + timedelta(days=1), time(0)), True))
        d += timedelta(days=1)
    end = datetime.combine(d1 + timedelta(days=1), time(0))
    if prev_end < end:
        out.append((prev_end, end, False))
    res = []
    for i, (s, e, hol) in enumerate(out):
        if e > s:
            res.append({"id": f"bg{i}", "start": _s(s), "end": _s(e), "type": "background",
                        "className": "holiday" if hol else "off", "content": "праздник" if hol else ""})
    return res


def _tab_gantt(q, tx, audit, all_batches, batch_is_archived):
    ctx = load_ctx(q)
    items = load_items(q)
    batches = all_batches()
    arts = article_info(q, batches)
    hist = tech.load_history(q)
    made = made_from_history(hist)
    _flash()

    c1, c2, c3 = st.columns([2, 2, 3])
    today = date.today()
    d0 = c1.date_input("С даты", value=today - timedelta(days=today.weekday()), format="DD.MM.YYYY", key="plan_from")
    span = c2.selectbox("Показать", ["1 неделя", "2 недели", "4 недели"], key="plan_span")
    days = {"1 неделя": 7, "2 недели": 14, "4 недели": 28}[span]
    d1 = d0 + timedelta(days=days - 1)
    c3.caption("Перетаскивайте партии по времени и тяните за край, чтобы растянуть/сжать. "
               "Пересекающиеся партии сдвигаются вперёд, ремонт и обслуживание не двигаются. "
               "Серое — нерабочее время, красное — праздник.")

    groups = [{"id": m, "label": m} for m in ctx["machines"]]
    extra = sorted({it["machine"] for it in items} - set(ctx["machines"]))
    groups += [{"id": m, "label": m + " (нет в списке станков)"} for m in extra]
    names = {b["batch_number"]: b.get("batch_name") or "" for b in batches}
    vis_items = []
    for it in items:
        if it["kind"] == "партия":
            hrs = item_hours(it)
            content = f"№{it['batch_number']} {names.get(it['batch_number'], '')} · {it['qty'] or 0} шт"
            title = (f"№{it['batch_number']} {names.get(it['batch_number'], '')}<br>{it['qty'] or 0} шт · {it['route'] or ''}<br>"
                     f"{it['start']} → {it['end']}<br>наладка {it['setup_h'] or 0:g} ч ({it['setup_why'] or ''}), "
                     f"выпуск {it['run_h'] or 0:.1f} ч" + (f"<br>длительность задана вручную: {hrs:.1f} ч"
                                                         if it.get("hours_manual") is not None else ""))
            vis_items.append({"id": it["id"], "group": it["machine"], "start": it["start"], "end": it["end"],
                              "content": content + (" ✋" if it.get("hours_manual") is not None else ""),
                              "title": title, "style": f"background:{_color(it['batch_number'])};border-color:#444;",
                              "updateGroup": False})
        else:
            vis_items.append({"id": it["id"], "group": it["machine"], "start": it["start"], "end": it["end"],
                              "content": f"🔧 {it['kind']}" + (f": {it['notes']}" if it.get("notes") else ""),
                              "title": f"{it['kind']}<br>{it['start']} → {it['end']}<br>{it.get('notes') or ''}",
                              "className": "kind-repair" if it["kind"] == "ремонт" else "kind-service"})
    vis_items += _background(ctx, d0 - timedelta(days=7), d1 + timedelta(days=21))
    ev = _timeline(groups=groups, items=vis_items,
                   window={"key": f"{d0}|{days}", "start": f"{d0} 00:00", "end": f"{d1 + timedelta(days=1)} 00:00"},
                   selected=st.session_state.get("plan_sel"), key="plan_tl", default=None)

    if ev and ev.get("nonce") != st.session_state.get("plan_nonce"):
        st.session_state["plan_nonce"] = ev.get("nonce")
        if ev.get("action") == "select":
            st.session_state["plan_sel"] = ev.get("id")
            st.rerun()
        elif ev.get("action") == "move":
            ok, msg = _on_move(q, tx, audit, ctx, items, arts, made, ev)
            st.session_state["plan_flash"] = (ok, msg)
            st.session_state["plan_sel"] = ev.get("id")
            st.rerun()

    warn = [it for it in items if it["kind"] == "партия" and it["batch_number"] not in names]
    if warn:
        st.warning("В плане есть партии, которых нет во вкладке «Партии»: " + ", ".join(sorted({w["batch_number"] for w in warn})))
    sel = next((it for it in items if it["id"] == st.session_state.get("plan_sel")), None)
    if sel:
        _selected_panel(q, tx, audit, ctx, items, arts, made, sel, names)
    with st.expander("➕ Поставить партию на станок", expanded=not items):
        _add_batch_form(q, tx, audit, ctx, items, arts, made, hist, batches, batch_is_archived)
    with st.expander("🔧 Ремонт / обслуживание"):
        _add_block_form(q, tx, audit, ctx, items, arts, made)


def _on_move(q, tx, audit, ctx, items, arts, made, ev):
    it = next((i for i in items if i["id"] == ev.get("id")), None)
    if not it:
        return False, "Позиция не найдена (план изменился) — обновите страницу."
    s, e = _dt(ev["start"]), _dt(ev["end"])
    if it["kind"] != "партия":
        upd = dict(it, start=_s(s), end=_s(e), machine=ev.get("group") or it["machine"])
        new = [upd if i["id"] == it["id"] else i for i in items]
        return apply_change(q, tx, audit, ctx, items, arts, made, changed=new, anchor_id=it["id"])
    os_, oe = _dt(it["start"]), _dt(it["end"])
    new = [dict(i) for i in items]
    if s == os_ and e != oe:                         # растянули/сжали за правый край
        hrs = workcal.work_hours_between(os_, e, ctx["shifts"], ctx["cal"])
        if hrs <= 0:
            return False, "Окончание должно быть позже начала в рабочее время."
        for i in new:
            if i["id"] == it["id"]:
                i["hours_manual"] = _minutes_h(hrs)
    else:
        if e - s != oe - os_:                        # потянули за левый край — конец на месте
            hrs = workcal.work_hours_between(s, oe, ctx["shifts"], ctx["cal"])
            if hrs <= 0:
                return False, "Начало должно быть раньше окончания в рабочее время."
            for i in new:
                if i["id"] == it["id"]:
                    i["hours_manual"] = _minutes_h(hrs)
        unit = [i for i in new if (it.get("linked") and i.get("grp") == it.get("grp") and i["kind"] == "партия")
                or i["id"] == it["id"]]
        for i in unit:
            i["start"] = _s(s)
    return apply_change(q, tx, audit, ctx, items, arts, made, changed=new,
                        anchor_grp=it.get("grp") if it.get("linked") else None, anchor_id=it["id"])


def _selected_panel(q, tx, audit, ctx, items, arts, made, it, names):
    st.markdown("#### Выбрано: " + (f"партия №{it['batch_number']} {names.get(it['batch_number'], '')}" if it["kind"] == "партия"
                                    else f"{it['kind']} · {it['machine']}"))
    unit = [i for i in items if it.get("linked") and i.get("grp") == it.get("grp")] or [it]
    rows = [{"Станок": i["machine"], "Начало": i["start"], "Окончание": i["end"], "Кол-во": i.get("qty"),
             "Наладка, ч": i.get("setup_h"), "Почему такая наладка": i.get("setup_why") or "",
             "Мин/шт": i.get("min_pc"), "Выпуск, ч": None if i.get("run_h") is None else round(i["run_h"], 2),
             "Вручную, ч": i.get("hours_manual")} for i in unit]
    if it["kind"] != "партия":
        rows = [{"Станок": it["machine"], "Начало": it["start"], "Окончание": it["end"], "Примечание": it.get("notes") or ""}]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    c1, c2, c3, c4 = st.columns(4)
    if it["kind"] == "партия":
        if any(i.get("hours_manual") is not None for i in unit) and c1.button("↺ Вернуть расчётную длительность", key=f"plan_reset_{it['id']}"):
            new = [dict(i, hours_manual=None) if i in unit else dict(i) for i in items]
            ok, msg = apply_change(q, tx, audit, ctx, items, arts, made, changed=new, anchor_id=it["id"])
            st.session_state["plan_flash"] = (ok, msg)
            st.rerun()
        with c2.popover("✏️ Время начала"):
            d = st.date_input("Дата", value=_dt(it["start"]).date(), format="DD.MM.YYYY", key=f"plan_ed_d_{it['id']}")
            tm = st.time_input("Время", value=_dt(it["start"]).time(), step=900, key=f"plan_ed_t_{it['id']}")
            if st.button("Применить", key=f"plan_ed_ok_{it['id']}"):
                s = _s(datetime.combine(d, tm))
                new = [dict(i, start=s) if i in unit else dict(i) for i in items]
                ok, msg = apply_change(q, tx, audit, ctx, items, arts, made, changed=new,
                                       anchor_grp=it.get("grp") if it.get("linked") else None, anchor_id=it["id"])
                st.session_state["plan_flash"] = (ok, msg)
                st.rerun()
    with c3.popover("🗑 Удалить из плана"):
        st.write("Удалить " + ("связку на станках " + ", ".join(i["machine"] for i in unit) if len(unit) > 1 else "эту позицию")
                 + " из плана? Партия во вкладке «Партии» не меняется.")
        if st.button("Да, удалить", key=f"plan_del_{it['id']}", type="primary"):
            ok, msg = apply_change(q, tx, audit, ctx, items, arts, made, deleted_ids=[i["id"] for i in unit])
            st.session_state["plan_flash"] = (ok, "Удалено из плана." if ok else msg)
            st.session_state.pop("plan_sel", None)
            st.rerun()
    if c4.button("✖ Снять выделение", key=f"plan_unsel_{it['id']}"):
        st.session_state.pop("plan_sel", None)
        st.rerun()


def _planned_qty(items, batch_number) -> int:
    seen, total = set(), 0
    for it in items:
        if it["kind"] == "партия" and it["batch_number"] == batch_number:
            g = it.get("grp") or f"id{it['id']}"
            if g not in seen:
                seen.add(g)
                total += int(it.get("qty") or 0)
    return total


def _add_batch_form(q, tx, audit, ctx, items, arts, made, hist, batches, batch_is_archived):
    active = [b for b in batches if not batch_is_archived(b.get("archive_state"), b.get("total_qty"), b.get("final_opta"))]
    if not active:
        st.info("Нет активных партий во вкладке «Партии».")
        return
    def left(b):
        return max(int(b.get("total_qty") or 0) - int(b.get("final_lathe") or 0) - _planned_qty(items, b["batch_number"]), 0)
    lab = {b["batch_number"]: f"№{b['batch_number']} — {b.get('batch_name') or ''} · план {b.get('total_qty') or 0} шт, "
                              f"выпущено {b.get('final_lathe') or 0}, в плане станков {_planned_qty(items, b['batch_number'])}"
           for b in active}
    bn = st.selectbox("Партия (из вкладки «Партии», активные)", list(lab), format_func=lab.get, key="plan_add_bn")
    b = next(x for x in active if x["batch_number"] == bn)
    info = arts.get(bn) or {}
    p = info.get("parsed") or {}
    if not p.get("key"):
        st.warning("Артикул в названии партии не распознан — нормы из истории не подтянутся, введите мин/шт вручную. "
                   + (p.get("error") or ""))
    family = "forging" if p.get("forging") else "straight"
    routes = q("SELECT * FROM tech_routes ORDER BY is_default DESC, id")
    fit = [r for r in routes if r["family"] == family] or routes
    if not fit:
        st.error("Не задано ни одного маршрута («🛠 Технология» → «🛣 Маршруты»).")
        return
    rl = {r["id"]: r["name"] + (" · связка, старт одновременно" if r["parallel"] and len(tech.parse_machines(r["machines"])) > 1 else "")
          for r in fit}
    c1, c2 = st.columns([3, 1])
    rid = c1.selectbox("Маршрут", list(rl), format_func=rl.get, key=f"plan_add_route_{bn}")
    route = next(r for r in fit if r["id"] == rid)
    ms = tech.parse_machines(route["machines"])
    default_qty = left(b) or int(b.get("total_qty") or 0) or 1
    qty = c2.number_input("Количество, шт", min_value=1, value=default_qty, step=10, key=f"plan_add_qty_{bn}",
                          help="Можно поставить часть партии, а остаток — на другой маршрут.")
    unknown = [m for m in ms if m not in ctx["machines"]]
    if unknown:
        st.warning(f"Станков {', '.join(unknown)} нет в списке станков плана — они появятся отдельной строкой.")

    key = p.get("key")
    h = hist[hist["key"] == key] if key and not hist.empty else hist.iloc[0:0] if not hist.empty else hist
    norms = tech.route_norms(p, key, h, hist, hist.attrs.get("parsed", {}) if not hist.empty else {}, ms) \
        if p.get("type_code") else [{"machine": m, "setup_h": None, "min_pc": None, "src": "артикул не распознан"} for m in ms]
    ed = st.data_editor(pd.DataFrame([{"Станок": n["machine"], "Мин/шт": n["min_pc"], "Откуда норма": n["src"]} for n in norms]),
                        hide_index=True, use_container_width=True, disabled=["Станок", "Откуда норма"],
                        key=f"plan_add_norms_{bn}_{rid}",
                        column_config={"Мин/шт": st.column_config.NumberColumn(min_value=0.0, step=0.1, format="%.2f")})
    st.caption("Наладка в плане считается по правилам: 4 ч с нуля, 2 ч — если предыдущая партия на станке с тем же HEX "
               "и обжимным торцом, 30 мин — если этот артикул на станке уже делали. Норма мин/шт — из истории "
               "(медиана), похожего артикула или вручную.")
    mode = st.radio("Когда", ["В конец очереди станков", "С даты и времени"], horizontal=True, key="plan_add_mode")
    if mode == "С даты и времени":
        c1, c2 = st.columns(2)
        d = c1.date_input("Дата", value=date.today(), format="DD.MM.YYYY", key="plan_add_d")
        tm = c2.time_input("Время", value=time(7, 0), step=900, key="plan_add_t")
        earliest = datetime.combine(d, tm)
    else:
        ends = [_dt(i["end"]) for i in items if i["machine"] in ms]
        earliest = max(ends + [datetime.now().replace(second=0, microsecond=0)])
    note = st.text_input("Примечание", key="plan_add_note")
    mpc = {r["Станок"]: r["Мин/шт"] for r in ed.to_dict("records")}
    missing = [m for m, v in mpc.items() if v is None or pd.isna(v)]
    if missing:
        st.warning("Введите норму мин/шт для: " + ", ".join(missing))
        return
    grp = uuid.uuid4().hex[:12]
    linked = 1 if route["parallel"] and len(ms) > 1 else 0
    new, t = [], earliest
    for m in ms:
        new.append({"kind": "партия", "batch_number": bn, "qty": int(qty), "machine": m, "grp": grp, "linked": linked,
                    "route": route["name"], "start": _s(t), "end": _s(t), "setup_h": None, "setup_why": "",
                    "min_pc": float(mpc[m]), "run_h": int(qty) * float(mpc[m]) / 60, "hours_manual": None, "notes": note})
    if not linked and len(ms) > 1:                   # последовательный маршрут: следующий станок — после предыдущего
        st.caption("Маршрут без связки: станки ставятся друг за другом.")
    # предпросмотр
    work = [dict(i) for i in items] + [dict(n, id=None, _tmp=f"new{k}") for k, n in enumerate(new)]
    if not linked and len(ms) > 1:
        res = _chain_sequential(work, new, ctx, arts, made, grp)
    else:
        res = reflow(work, ctx, arts, made, anchor_grp=grp)
    mine = [r for r in res if r.get("_tmp")]
    pv = pd.DataFrame([{"Станок": r["machine"], "Начало": r["start"], "Окончание": r["end"], "Наладка, ч": r["setup_h"],
                        "Почему": r["setup_why"], "Выпуск, ч": round(r["run_h"], 2)} for r in mine])
    st.markdown("**Предварительно:**")
    st.dataframe(pv, use_container_width=True, hide_index=True)
    moved = sum(1 for r in res if r.get("id") and any(o["id"] == r["id"] and o["start"] != r["start"] for o in items))
    if moved:
        st.caption(f"Будут сдвинуты вперёд другие позиции: {moved}.")
    if st.button("📌 Поставить в план", type="primary", key="plan_add_go"):
        bad = conflicts(res)
        if bad:
            st.error("Не удалось: " + "; ".join(bad[:3]))
            return
        by_tmp = {r["_tmp"]: r for r in mine}
        save_items(tx, audit, items, [r for r in res if r.get("id")],
                   new_items=[by_tmp[f"new{k}"] for k in range(len(new))])
        st.session_state["plan_flash"] = (True, f"Партия №{bn} поставлена: {mine[0]['start']} → {max(r['end'] for r in mine)}.")
        st.rerun()


def _chain_sequential(work, new, ctx, arts, made, grp):
    """Маршрут без связки: каждый следующий станок начинает после окончания предыдущего."""
    res = work
    for k in range(len(new)):
        res = reflow(res, ctx, arts, made, anchor_grp=grp)
        if k + 1 < len(new):
            end_k = next(r["end"] for r in res if r.get("_tmp") == f"new{k}")
            for r in res:
                if r.get("_tmp") == f"new{k + 1}" and _dt(r["start"]) < _dt(end_k):
                    r["start"] = end_k
    return res


def _add_block_form(q, tx, audit, ctx, items, arts, made):
    with st.form("plan_block_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        kind = c1.selectbox("Вид", ["ремонт", "обслуживание"])
        m = c2.selectbox("Станок", ctx["machines"])
        c1, c2, c3, c4 = st.columns(4)
        d0 = c1.date_input("С даты", value=date.today(), format="DD.MM.YYYY")
        t0 = c2.time_input("С", value=time(7, 0), step=900)
        d1 = c3.date_input("По дату", value=date.today(), format="DD.MM.YYYY")
        t1 = c4.time_input("До", value=time(15, 30), step=900)
        note = st.text_input("Что делаем", placeholder="например, замена шпинделя")
        if st.form_submit_button("➕ Добавить", type="primary"):
            s, e = datetime.combine(d0, t0), datetime.combine(d1, t1)
            if e <= s:
                st.error("Окончание должно быть позже начала.")
            else:
                blk = {"kind": kind, "batch_number": "", "qty": None, "machine": m, "grp": uuid.uuid4().hex[:12],
                       "linked": 0, "route": "", "start": _s(s), "end": _s(e), "setup_h": None, "setup_why": "",
                       "min_pc": None, "run_h": None, "hours_manual": None, "notes": note.strip()}
                ok, msg = apply_change(q, tx, audit, ctx, items, arts, made, new_items=[blk])
                st.session_state["plan_flash"] = (ok, f"{kind.capitalize()} добавлен. " + msg if ok else msg)
                st.rerun()
    st.caption("Партии, попавшие на ремонт или обслуживание, сдвигаются после него целиком (партия не разрывается).")


def _tab_list(q):
    items = load_items(q)
    if not items:
        st.info("План пуст.")
        return
    fact = {(r["batch_number"], r["machine"]): r for r in q("""
        SELECT p.batch_number, m.name AS machine, SUM(COALESCE(p.produced_qty,0)) AS made, MIN(p.date) AS first, MAX(p.date) AS last
        FROM production p JOIN machines m ON m.id = p.machine_id
        WHERE COALESCE(p.record_type,'production')='production' GROUP BY p.batch_number, m.name""")}
    names = {r["batch_number"]: r["batch_name"] for r in q("SELECT batch_number, batch_name FROM batches")}
    rows = []
    for it in items:
        f = fact.get((it["batch_number"], it["machine"])) if it["kind"] == "партия" else None
        made_q = (f or {}).get("made") or 0
        status = "" if it["kind"] != "партия" else (
            "выполнено" if it.get("qty") and made_q >= it["qty"] else "в работе" if made_q else
            "просрочено" if _dt(it["end"]) < datetime.now() else "не начато")
        rows.append({"ID": it["id"], "Вид": it["kind"], "Станок": it["machine"],
                     "Партия": it["batch_number"] or "", "Название": names.get(it["batch_number"], ""),
                     "Кол-во": it.get("qty"), "Начало": it["start"], "Окончание": it["end"],
                     "Часы": round(item_hours(it), 2) if it["kind"] == "партия" else None,
                     "Наладка, ч": it.get("setup_h"), "Факт, шт": made_q if it["kind"] == "партия" else None,
                     "Факт: даты": f"{f['first']} … {f['last']}" if f else "", "Статус": status,
                     "Примечание": it.get("notes") or ""})
    df = pd.DataFrame(rows)
    flt = st.selectbox("Станок", ["все"] + sorted(df["Станок"].unique()), key="plan_list_m")
    if flt != "все":
        df = df[df["Станок"] == flt]
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption("Факт — выпуск по записям станка для этой партии (все записи, не только в даты плана).")


def _tab_shifts(q, tx, audit):
    st.caption("Режим работы завода по датам: на каждую дату действуют все смены с наибольшей датой «Действует с» "
               "не позже неё. Например: с 01.10 — смены 1 и 2, с 01.12 — только смена 1 (одна строка с 01.12). "
               "Время — ЧЧ:ММ. Режим используется в плане станков и в себестоимости (часы станка в сутки).")
    tech._journal(q, tx, audit, "plan_shifts", "Режим смен",
                  ["valid_from", "shift_no", "shift_start", "shift_end", "lunch_start", "lunch_min", "notes"],
                  {"valid_from": "Действует с", "shift_no": "Смена №", "shift_start": "Начало", "shift_end": "Окончание",
                   "lunch_start": "Обед с", "lunch_min": "Обед, мин", "notes": "Примечание"},
                  dates=["valid_from"], ints=["shift_no", "lunch_min"])
    raw = q("SELECT * FROM plan_shifts")
    rows = [workcal.norm_shift(r) for r in raw]
    bad = []
    for r in raw:
        for c in ("shift_start", "shift_end", "lunch_start"):
            v = (r.get(c) or "").strip()
            if v and not _is_hhmm(v):
                bad.append(f"{r['valid_from']} смена {r['shift_no']}: «{v}»")
    if bad:
        st.error("Неверное время (нужно ЧЧ:ММ): " + "; ".join(bad) + ". Пока не исправлено, такие строки могут сломать расчёт.")
        return
    vfs = sorted({str(r["valid_from"])[:10] for r in rows if r.get("valid_from")})
    summ = []
    for vf in vfs:
        d = date.fromisoformat(vf)
        summ.append({"Действует с": d.strftime("%d.%m.%Y"), "Смен": len([r for r in rows if str(r["valid_from"])[:10] == vf]),
                     "Часов станка в рабочие сутки": round(workcal.hours_per_day(d, rows), 2)})
    if summ:
        st.markdown("**Итог по режимам**")
        st.dataframe(pd.DataFrame(summ), use_container_width=True, hide_index=True)
    st.caption("Две смены 07:00–15:30 и 15:00–23:30 с обедом по 30 мин дают 15,5 ч станка в сутки "
               "(получасовое перекрытие на пересменке считается один раз).")


def _is_hhmm(v: str) -> bool:
    try:
        h, m = v.split(":")
        return 0 <= int(h) <= 23 and 0 <= int(m) <= 59 and len(m) == 2
    except ValueError:
        return False


_WD = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
_MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]


def _tab_calendar(q, tx, audit):
    st.caption("Рабочая неделя — понедельник–суббота. Снимите галочку у праздника или поставьте у рабочего воскресенья; "
               "сохраняются только отличия от обычной недели.")
    c1, c2 = st.columns(2)
    today = date.today()
    y = c1.number_input("Год", min_value=2024, max_value=2035, value=today.year, step=1, key="plan_cal_y")
    mth = c2.selectbox("Месяц", list(range(1, 13)), index=today.month - 1, format_func=lambda m: _MONTHS[m - 1], key="plan_cal_m")
    ex = {r["day"]: r for r in q("SELECT * FROM plan_calendar WHERE day LIKE ?", (f"{int(y):04d}-{mth:02d}-%",))}
    ctx = load_ctx(q)
    rows, d = [], date(int(y), mth, 1)
    while d.month == mth:
        r = ex.get(d.isoformat())
        rows.append({"Дата": d, "День": _WD[d.weekday()], "Рабочий": workcal.is_working_day(d, ctx["cal"]),
                     "Примечание": (r or {}).get("note") or ""})
        d += timedelta(days=1)
    df = pd.DataFrame(rows)
    ed = st.data_editor(df, hide_index=True, use_container_width=True, disabled=["Дата", "День"],
                        key=f"plan_cal_ed_{int(y)}_{mth}",
                        column_config={"Дата": st.column_config.DateColumn(format="DD.MM.YYYY"),
                                       "Рабочий": st.column_config.CheckboxColumn()})
    wd = int(ed["Рабочий"].sum())
    hrs = sum(workcal.hours_per_day(r["Дата"], ctx["shifts"]) for r in ed.to_dict("records") if r["Рабочий"])
    st.caption(f"Рабочих дней: {wd}; часов станка за месяц по режиму смен: {hrs:,.1f}.")
    if st.button("💾 Сохранить календарь месяца", type="primary", key=f"plan_cal_save_{int(y)}_{mth}"):
        n = 0
        with tx() as conn:
            for r in ed.to_dict("records"):
                day = r["Дата"]
                if isinstance(day, pd.Timestamp):
                    day = day.date()
                iso, normal = day.isoformat(), day.weekday() in workcal.WORK_WEEKDAYS
                note = (r.get("Примечание") or "").strip()
                old = ex.get(iso)
                if bool(r["Рабочий"]) == normal:     # как обычно → исключение не нужно
                    if old:
                        conn.execute("DELETE FROM plan_calendar WHERE day=?", (iso,))
                        audit(conn, "delete", "plan_calendar", None, old)
                        n += 1
                    continue
                new = {"day": iso, "kind": "рабочий" if r["Рабочий"] else "выходной", "note": note}
                if not old or old["kind"] != new["kind"] or (old.get("note") or "") != note:
                    conn.execute("INSERT OR REPLACE INTO plan_calendar (day, kind, note) VALUES (?,?,?)", tuple(new.values()))
                    audit(conn, "update" if old else "insert", "plan_calendar", None, old, new)
                    n += 1
        st.session_state["plan_cal_flash"] = f"✅ Сохранено изменений: {n}. Уже стоящие партии пересчитаются при следующем изменении плана."
        st.rerun()
    m = st.session_state.pop("plan_cal_flash", None)
    if m:
        st.success(m)
