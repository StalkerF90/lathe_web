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
import html
import json
import os
import re
import uuid
from datetime import date, datetime, time, timedelta

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import tech
import workcal
import xlsxlite

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
        CREATE TABLE IF NOT EXISTS plan_orders (       -- заказы на план (импорт из Excel / вручную)
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_number TEXT NOT NULL,
            qty          INTEGER,
            route        TEXT DEFAULT '',          -- как указано в файле (название маршрута или станки)
            not_before   TEXT,                     -- YYYY-MM-DD HH:MM — не начинать раньше
            due_date     TEXT,                     -- YYYY-MM-DD — срок
            priority     INTEGER,                  -- 1 — самый срочный; пусто — после всех
            min_pc       TEXT DEFAULT '',          -- норма мин/шт: число или «Lathe 235=0.5; Lathe 2100=0.2»
            notes        TEXT DEFAULT '',
            source       TEXT DEFAULT '',          -- файл импорта
            created_by   TEXT DEFAULT '',
            created_at   TEXT
        );
    """)
    cols = [r[1] for r in c.execute("PRAGMA table_info(plan_items)")]
    if "order_id" not in cols:
        c.execute("ALTER TABLE plan_items ADD COLUMN order_id INTEGER")
    if "due_date" not in cols:
        c.execute("ALTER TABLE plan_items ADD COLUMN due_date TEXT")
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


def _d_ru(iso: str | None) -> str:
    """2026-10-31 → 31.10.2026."""
    if not iso:
        return ""
    try:
        return date.fromisoformat(str(iso)[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return str(iso)


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


def item_progress(items: list[dict], fact: list[dict]) -> dict:
    """Факт выпуска по позициям плана: {id: {'done', 'pct', 'last'}}.
    fact — записи выпуска станков {batch_number, machine, date, stage, fin, qty}. На станке считаем
    финальный выпуск, если он есть, иначе — самый продвинутый этап (записи идут по этапам, сумма этапов
    дала бы 200 % для двух установов на одном станке). Учитываются записи не раньше даты начала позиции
    или даты её постановки в план (что раньше) — выпуск до планирования остатка партии не засчитывается.
    Несколько позиций одной партии на станке заполняются по порядку."""
    by_key = {}
    for f in fact:
        by_key.setdefault((f["batch_number"], f["machine"]), []).append(f)
    out = {}
    groups = {}
    for it in items:
        if it["kind"] == "партия" and it.get("id"):
            groups.setdefault((it["batch_number"], it["machine"]), []).append(it)
    for key, lst in groups.items():
        lst = sorted(lst, key=lambda i: (i["start"], i["id"]))
        cut = min(min(i["start"][:10], (i.get("created_at") or i["start"])[:10]) for i in lst)
        recs = [f for f in by_key.get(key, []) if str(f["date"] or "")[:10] >= cut]
        fin = [f for f in recs if f["fin"]]
        if fin:
            done = sum(int(f["qty"] or 0) for f in fin)
        else:
            per_stage = {}
            for f in recs:
                per_stage[f["stage"]] = per_stage.get(f["stage"], 0) + int(f["qty"] or 0)
            done = max(per_stage.values()) if per_stage else 0
        last = max((str(f["date"])[:10] for f in recs), default="")
        first = min((str(f["date"])[:10] for f in recs), default="")
        for i in lst:
            qty = int(i.get("qty") or 0)
            got = min(done, qty) if qty else 0
            done -= got
            out[i["id"]] = {"done": got, "pct": round(100 * got / qty) if qty else 0, "last": last, "first": first}
    return out


def _day_bounds(day: date, ctx) -> tuple[datetime, datetime]:
    """Начало и конец рабочего дня (если день нерабочий — по режиму ближайшего рабочего дня недели)."""
    p = workcal.day_periods(day, ctx["shifts"], ctx["cal"]) or workcal.day_periods(day, ctx["shifts"], {day.isoformat(): "рабочий"})
    if not p:
        return datetime.combine(day, time(7, 0)), datetime.combine(day, time(23, 30))
    return p[0]["start"], p[-1]["end"]


def fact_shift(items: list[dict], prog: dict, ctx, now: datetime, only_ids=None) -> tuple[list[dict], list[str]]:
    """«Сдвинуть по факту»: начало позиции (связки — общее) = начало рабочего дня первой записи выпуска.
    Выполненная позиция растягивается до конца дня последней записи; начатая — длительность по прогнозу:
    отработано с начала + оставшаяся доля плановых часов (если это больше плана).
    Возвращает (изменённый план, описания изменений)."""
    new = [dict(i) for i in items]
    notes = []
    for u in units_of([i for i in new if i["kind"] == "партия"]):
        if only_ids is not None and not any(i["id"] in only_ids for i in u):
            continue
        firsts = [prog[i["id"]]["first"] for i in u if prog.get(i["id"], {}).get("first") and prog[i["id"]]["done"]]
        if not firsts:
            continue
        start = _day_bounds(date.fromisoformat(min(firsts)), ctx)[0]
        moved = False
        for i in u:
            pr = prog.get(i["id"], {})
            if _s(start) != i["start"]:
                i["start"] = _s(start)
                moved = True
            planned = item_hours(i) if i.get("hours_manual") is None else float(i["hours_manual"])
            if pr.get("done") and pr["pct"] >= 100:
                end = _day_bounds(date.fromisoformat(pr["last"]), ctx)[1]
                h = _minutes_h(workcal.work_hours_between(start, end, ctx["shifts"], ctx["cal"]))
                if h > 0 and abs(h - planned) > 1e-6:
                    i["hours_manual"] = h
                    moved = True
            elif pr.get("done"):
                worked = workcal.work_hours_between(start, now, ctx["shifts"], ctx["cal"])
                forecast = worked + item_hours(dict(i, hours_manual=None)) * (1 - pr["pct"] / 100)
                if forecast > planned + 1e-6:
                    i["hours_manual"] = _minutes_h(forecast)
                    moved = True
        if moved:
            notes.append(f"№{u[0]['batch_number']} ({', '.join(i['machine'] for i in u)}): с {_s(start)}")
    return new, notes


def load_fact(q, items: list[dict]) -> list[dict]:
    bns = sorted({i["batch_number"] for i in items if i["kind"] == "партия" and i.get("batch_number")})
    if not bns:
        return []
    return q(f"""
        SELECT p.batch_number, m.name AS machine, p.date, COALESCE(p.stage_name,'') AS stage,
               COALESCE(p.is_final_release,0) AS fin, COALESCE(p.produced_qty,0) AS qty
        FROM production p JOIN machines m ON m.id = p.machine_id
        WHERE COALESCE(p.record_type,'production')='production' AND p.batch_number IN ({','.join('?' * len(bns))})""",
             tuple(bns))


def _shade(hex_color: str, k: float = 0.5) -> str:
    """Темнее на долю k (для выполненной части полосы)."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02x%02x%02x" % (int(r * (1 - k)), int(g * (1 - k)), int(b * (1 - k)))


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
            "min_pc", "run_h", "hours_manual", "notes", "order_id", "due_date"]
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
    t_g, t_o, t_l, t_s, t_c = st.tabs(["🗓 График", "📥 Заказы и импорт из Excel", "📋 Список и факт", "⏱ Режим смен",
                                       "📆 Праздники и выходные"])
    with t_g:
        _tab_gantt(q, tx, audit, all_batches, batch_is_archived)
    with t_o:
        _tab_orders(q, tx, audit, all_batches, batch_is_archived)
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
    prog = item_progress(items, load_fact(q, items))
    now_s = _s(datetime.now())
    e = html.escape
    vis_items = []
    for it in items:
        if it["kind"] == "партия":
            hrs = item_hours(it)
            pr = prog.get(it["id"], {"done": 0, "pct": 0, "last": ""})
            name = e(f"№{it['batch_number']} {names.get(it['batch_number'], '')}")
            late = it["end"] < now_s and pr["pct"] < 100
            due_late = bool(it.get("due_date")) and it["end"][:10] > it["due_date"] and pr["pct"] < 100
            content = (f"{name} · {it['qty'] or 0} шт" + (f" · {pr['pct']}%" if pr["done"] else "")
                       + (" ✔" if pr["pct"] >= 100 else "") + (" ✋" if it.get("hours_manual") is not None else ""))
            title = (f"{name}<br>{it['qty'] or 0} шт · {e(it['route'] or '')}<br>"
                     f"{it['start']} → {it['end']}<br>наладка {it['setup_h'] or 0:g} ч ({e(it['setup_why'] or '')}), "
                     f"выпуск {it['run_h'] or 0:.1f} ч" + (f"<br>длительность задана вручную: {hrs:.1f} ч"
                                                         if it.get("hours_manual") is not None else "")
                     + f"<br><b>Факт: {pr['done']} из {it['qty'] or 0} шт ({pr['pct']}%)</b>"
                     + (f", последняя запись {pr['last']}" if pr["last"] else "")
                     + ("<br>⚠️ срок по плану прошёл, партия не закончена" if late else "")
                     + (f"<br>Срок заказа: {_d_ru(it['due_date'])}" if it.get("due_date") else "")
                     + ("<br>⏰ по плану не успевает к сроку" if due_late else ""))
            col, p = _color(it["batch_number"]), max(0, min(pr["pct"], 100))
            bg = (f"linear-gradient(90deg, {_shade(col)} 0%, {_shade(col)} {p}%, {col} {p}%, {col} 100%)" if p else col)
            vis_items.append({"id": it["id"], "group": it["machine"], "start": it["start"], "end": it["end"],
                              "title": title, "updateGroup": False,
                              "className": "batch" + (" late" if late or due_late else ""),
                              "content": content + (" ⏰" if due_late else ""),
                              "style": f"background:{bg};border-color:{'#ff4b4b' if late else '#ffa421' if due_late else '#444'};"})
        else:
            vis_items.append({"id": it["id"], "group": it["machine"], "start": it["start"], "end": it["end"],
                              "content": f"🔧 {e(it['kind'])}" + (f": {e(it['notes'])}" if it.get("notes") else ""),
                              "title": f"{e(it['kind'])}<br>{it['start']} → {it['end']}<br>{e(it.get('notes') or '')}",
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

    started = [i for i in items if prog.get(i["id"], {}).get("done")]
    if started and st.button(f"⏩ Сдвинуть по факту все начатые партии ({len({i.get('grp') or i['id'] for i in started})})",
                             key="plan_fact_all",
                             help="Начало — с рабочего дня первой записи выпуска; выполненные — до конца дня последней записи; "
                                  "начатые — прогноз: отработано + оставшаяся доля плановых часов. Остальные позиции "
                                  "сдвигаются, если пересекутся."):
        new, notes = fact_shift(items, prog, ctx, datetime.now())
        if not notes:
            st.session_state["plan_flash"] = (True, "План уже совпадает с фактом.")
        else:
            ok, msg = apply_change(q, tx, audit, ctx, items, arts, made, changed=new)
            st.session_state["plan_flash"] = (ok, (msg + " По факту: " + "; ".join(notes)) if ok else msg)
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
    prog = item_progress(items, load_fact(q, items)) if it["kind"] == "партия" else {}
    rows = [{"Станок": i["machine"], "Начало": i["start"], "Окончание": i["end"], "Кол-во": i.get("qty"),
             "Факт, шт": prog.get(i["id"], {}).get("done", 0), "Факт, %": prog.get(i["id"], {}).get("pct", 0),
             "Наладка, ч": i.get("setup_h"), "Почему такая наладка": i.get("setup_why") or "",
             "Мин/шт": i.get("min_pc"), "Выпуск, ч": None if i.get("run_h") is None else round(i["run_h"], 2),
             "Вручную, ч": i.get("hours_manual")} for i in unit]
    if it["kind"] != "партия":
        rows = [{"Станок": it["machine"], "Начало": it["start"], "Окончание": it["end"], "Примечание": it.get("notes") or ""}]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    c1, c2, c3, c4, c5 = st.columns(5)
    if it["kind"] == "партия":
        if any(prog.get(i["id"], {}).get("done") for i in unit) and c5.button("⏩ Сдвинуть по факту", key=f"plan_fact_{it['id']}"):
            new, notes = fact_shift(items, prog, ctx, datetime.now(), only_ids={i["id"] for i in unit})
            if not notes:
                st.session_state["plan_flash"] = (True, "Позиция уже совпадает с фактом.")
            else:
                ok, msg = apply_change(q, tx, audit, ctx, items, arts, made, changed=new,
                                       anchor_grp=it.get("grp") if it.get("linked") else None, anchor_id=it["id"])
                st.session_state["plan_flash"] = (ok, (msg + " По факту: " + "; ".join(notes)) if ok else msg)
            st.rerun()
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


def route_options(q, ctx, p: dict) -> list[dict]:
    """Маршруты для артикула: из «🛠 Технология → Маршруты» (сначала своего вида — прямой / из поковки)
    плюс отдельные станки плана, для которых нет одностаночного маршрута (АПТ, MILL …)."""
    family = "forging" if p.get("forging") else "straight"
    out = []
    for r in sorted(q("SELECT * FROM tech_routes ORDER BY is_default DESC, id"), key=lambda r: r["family"] != family):
        ms = tech.parse_machines(r["machines"])
        if not ms:
            continue
        par = bool(r["parallel"]) and len(ms) > 1
        out.append({"key": f"r{r['id']}", "name": r["name"], "machines": ms, "parallel": par,
                    "label": r["name"] + (" · связка, старт одновременно" if par else "")
                             + ("" if r["family"] == family else " · (маршрут другого вида)")})
    singles = {o["machines"][0] for o in out if len(o["machines"]) == 1}
    for m in ctx["machines"]:
        if m not in singles:
            out.append({"key": f"m:{m}", "name": m, "machines": (m,), "parallel": False, "label": f"{m} (один станок)"})
    return out


def resolve_route(text: str, options: list[dict], all_machines) -> dict | None:
    """Маршрут по тексту из файла: название маршрута или станки («235+2100», «Lathe 2105», «MILL»)."""
    t = (text or "").strip().lower()
    if not t:
        return None
    for o in options:
        if o["name"].strip().lower() == t:
            return o
    ms = set()
    for tok in re.split(r"[+,;/&]| и ", t):
        tok = tok.strip()
        if not tok:
            continue
        hit = [m for m in all_machines if m.lower() == tok or m.lower().endswith(" " + tok)]
        if len(hit) != 1:
            return None
        ms.add(hit[0])
    for o in options:
        if set(o["machines"]) == ms:
            return o
    return None


def parse_min_pc(text, machines) -> tuple[dict, str]:
    """Норма из файла: «0.53» (на все станки маршрута) или «235=0.53; 2100=0.2». → ({станок: мин/шт}, ошибка)."""
    s = str(text if text is not None else "").strip().replace(",", ".")
    if not s:
        return {}, ""
    try:
        v = float(s)
        return ({m: v for m in machines}, "") if v >= 0 else ({}, "норма меньше нуля")
    except ValueError:
        pass
    out = {}
    for part in re.split(r"[;\n]", s):
        if not part.strip():
            continue
        if "=" not in part and ":" not in part:
            return {}, f"не понял норму «{part.strip()}»"
        k, v = re.split(r"[=:]", part, maxsplit=1)
        hit = [m for m in machines if m.lower() == k.strip().lower() or m.lower().endswith(" " + k.strip().lower())]
        try:
            val = float(v.strip())
        except ValueError:
            return {}, f"не понял норму «{part.strip()}»"
        if len(hit) != 1:
            return {}, f"станка «{k.strip()}» нет в маршруте"
        out[hit[0]] = val
    return out, ""


def batch_norms(hist: pd.DataFrame, p: dict, machines) -> list[dict]:
    """Нормы мин/шт по станкам маршрута: история артикула → похожий артикул → нет."""
    if not p.get("type_code"):
        return [{"machine": m, "min_pc": None, "src": "артикул не распознан"} for m in machines]
    key = p.get("key")
    if hist.empty:
        h = hist
    else:
        h = hist[hist["key"] == key] if key else hist.iloc[0:0]
    return tech.route_norms(p, key, h, hist, hist.attrs.get("parsed", {}) if not hist.empty else {}, machines)


def new_batch_items(bn: str, qty: int, route: dict, mpc: dict, note: str, start: datetime,
                    order_id=None, due=None) -> list[dict]:
    """Позиции новой постановки партии по маршруту (время уточнит раскладка)."""
    grp = uuid.uuid4().hex[:12]
    linked = 1 if route["parallel"] else 0
    return [{"kind": "партия", "batch_number": bn, "qty": int(qty), "machine": m, "grp": grp, "linked": linked,
             "route": route["name"], "start": _s(start), "end": _s(start), "setup_h": None, "setup_why": "",
             "min_pc": float(mpc[m]), "run_h": int(qty) * float(mpc[m]) / 60, "hours_manual": None, "notes": note,
             "order_id": order_id, "due_date": due, "id": None, "_tmp": f"{grp}:{k}"}
            for k, m in enumerate(route["machines"])]


def place_new(work: list[dict], new: list[dict], ctx, arts, made) -> list[dict]:
    """Ставит новую постановку в рабочий план (новая — якорь; связка — общий старт;
    маршрут без связки — станки друг за другом)."""
    res = work + [dict(n) for n in new]
    grp = new[0]["grp"]
    if new[0]["linked"] or len(new) == 1:
        return reflow(res, ctx, arts, made, anchor_grp=grp)
    for k in range(len(new)):
        res = reflow(res, ctx, arts, made, anchor_grp=grp)
        if k + 1 < len(new):
            end_k = next(r["end"] for r in res if r.get("_tmp") == new[k]["_tmp"])
            for r in res:
                if r.get("_tmp") == new[k + 1]["_tmp"] and _dt(r["start"]) < _dt(end_k):
                    r["start"] = end_k
    return res


def queue_end(work: list[dict], machines, not_before: datetime | None = None) -> datetime:
    """Конец очереди станков (не раньше «сейчас» и не раньше not_before)."""
    ends = [_dt(i["end"]) for i in work if i["machine"] in machines]
    return max(ends + [datetime.now().replace(second=0, microsecond=0)] + ([not_before] if not_before else []))


def save_result(tx, audit, items: list[dict], res: list[dict]):
    """Сохраняет результат раскладки с новыми позициями (_tmp) одной транзакцией."""
    save_items(tx, audit, items, [r for r in res if r.get("id")], new_items=[r for r in res if r.get("_tmp")])


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
    p = (arts.get(bn) or {}).get("parsed") or {}
    if not p.get("key"):
        st.warning("Артикул в названии партии не распознан — нормы из истории не подтянутся, введите мин/шт вручную. "
                   + (p.get("error") or ""))
    opts = route_options(q, ctx, p)
    if not opts:
        st.error("Не задано ни одного маршрута («🛠 Технология» → «🛣 Маршруты») и нет станков плана.")
        return
    rl = {o["key"]: o["label"] for o in opts}
    c1, c2 = st.columns([3, 1])
    rkey = c1.selectbox("Маршрут", list(rl), format_func=rl.get, key=f"plan_add_route_{bn}")
    route = next(o for o in opts if o["key"] == rkey)
    ms = route["machines"]
    default_qty = left(b) or int(b.get("total_qty") or 0) or 1
    qty = c2.number_input("Количество, шт", min_value=1, value=default_qty, step=10, key=f"plan_add_qty_{bn}",
                          help="Можно поставить часть партии, а остаток — на другой маршрут.")
    unknown = [m for m in ms if m not in ctx["machines"]]
    if unknown:
        st.warning(f"Станков {', '.join(unknown)} нет в списке станков плана — они появятся отдельной строкой.")
    norms = batch_norms(hist, p, ms)
    ed = st.data_editor(pd.DataFrame([{"Станок": n["machine"], "Мин/шт": n["min_pc"], "Откуда норма": n["src"]} for n in norms]),
                        hide_index=True, use_container_width=True, disabled=["Станок", "Откуда норма"],
                        key=f"plan_add_norms_{bn}_{rkey}",
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
        earliest = queue_end(items, ms)
    note = st.text_input("Примечание", key="plan_add_note")
    mpc = {r["Станок"]: r["Мин/шт"] for r in ed.to_dict("records")}
    missing = [m for m, v in mpc.items() if v is None or pd.isna(v)]
    if missing:
        st.warning("Введите норму мин/шт для: " + ", ".join(missing))
        return
    if not route["parallel"] and len(ms) > 1:
        st.caption("Маршрут без связки: станки ставятся друг за другом.")
    new = new_batch_items(bn, qty, route, mpc, note, earliest)
    res = place_new([dict(i) for i in items], new, ctx, arts, made)
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
        save_result(tx, audit, items, res)
        st.session_state["plan_flash"] = (True, f"Партия №{bn} поставлена: {mine[0]['start']} → {max(r['end'] for r in mine)}.")
        st.rerun()


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
    prog = item_progress(items, load_fact(q, items))
    names = {r["batch_number"]: r["batch_name"] for r in q("SELECT batch_number, batch_name FROM batches")}
    rows = []
    for it in items:
        pr = prog.get(it["id"], {"done": 0, "pct": 0, "last": ""})
        made_q = pr["done"]
        late = _dt(it["end"]) < datetime.now()
        status = "" if it["kind"] != "партия" else (
            "выполнено" if it.get("qty") and made_q >= it["qty"] else
            ("в работе, срок прошёл" if late else "в работе") if made_q else
            "просрочено" if late else "не начато")
        rows.append({"ID": it["id"], "Вид": it["kind"], "Станок": it["machine"],
                     "Партия": it["batch_number"] or "", "Название": names.get(it["batch_number"], ""),
                     "Кол-во": it.get("qty"), "Начало": it["start"], "Окончание": it["end"],
                     "Часы": round(item_hours(it), 2) if it["kind"] == "партия" else None,
                     "Наладка, ч": it.get("setup_h"), "Факт, шт": made_q if it["kind"] == "партия" else None,
                     "Факт, %": pr["pct"] if it["kind"] == "партия" else None,
                     "Последняя запись": pr["last"], "Статус": status,
                     "Примечание": it.get("notes") or ""})
    df = pd.DataFrame(rows)
    flt = st.selectbox("Станок", ["все"] + sorted(df["Станок"].unique()), key="plan_list_m")
    if flt != "все":
        df = df[df["Станок"] == flt]
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption("Факт — выпуск партии на этом станке по истории выпуска: финальный выпуск, а если его нет — самый "
               "продвинутый этап. Считаются записи не раньше начала позиции или даты постановки в план (что раньше); "
               "если партия стоит на станке несколько раз, факт заполняет позиции по порядку.")


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


# ═══════════════════════════════════════════════════════════════════════════
#  ЗАКАЗЫ И ИМПОРТ ИЗ EXCEL
# ═══════════════════════════════════════════════════════════════════════════

# (поле, заголовок в шаблоне, синонимы заголовка, ширина столбца)
ORDER_FIELDS = [
    ("batch_number", "№ партии*", ("№ партии", "номер партии", "партия", "№", "n партии"), 12),
    ("batch_name", "Название (для новой партии)", ("название", "наименование", "артикул", "название партии"), 30),
    ("qty", "Количество, шт", ("количество", "кол-во", "кол во", "шт"), 14),
    ("route", "Маршрут / станок", ("маршрут", "станок", "станки", "маршрут / станок"), 26),
    ("not_before", "Не раньше", ("не раньше", "начало", "старт", "начать с"), 18),
    ("due_date", "Срок", ("срок", "срок готовности", "дата готовности", "готовность"), 12),
    ("priority", "Приоритет", ("приоритет",), 10),
    ("min_pc", "Мин/шт", ("мин/шт", "норма", "норма мин/шт", "мин на шт"), 24),
    ("notes", "Примечание", ("примечание", "комментарий"), 30),
]


def _norm_header(h) -> str:
    return re.sub(r"\s+", " ", str(h or "").replace("*", "").split(",")[0]).strip().lower()


def _header_map(row) -> dict:
    """{поле: индекс столбца} по строке заголовков."""
    out = {}
    for ci, h in enumerate(row):
        hn = _norm_header(h)
        for f, title, aliases, _w in ORDER_FIELDS:
            if f not in out and (hn == _norm_header(title) or hn in aliases):
                out[f] = ci
    return out


def _as_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else repr(v)
    if isinstance(v, datetime):
        return v.strftime("%d.%m.%Y")
    return str(v).strip()


def _as_dt(v, default_time=time(7, 0)) -> tuple[datetime | None, str]:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None, ""
    if isinstance(v, datetime):
        return (v if (v.hour or v.minute) else datetime.combine(v.date(), default_time)), ""
    if isinstance(v, float):
        return None, f"«{_as_text(v)}» — не дата (ожидается ДД.ММ.ГГГГ)"
    s = str(v).strip()
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y", "%d.%m.%y %H:%M", "%d.%m.%y", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            d = datetime.strptime(s, fmt)
            return (d if "%H" in fmt else datetime.combine(d.date(), default_time)), ""
        except ValueError:
            continue
    return None, f"«{s}» — не дата (ожидается ДД.ММ.ГГГГ или ДД.ММ.ГГГГ ЧЧ:ММ)"


def _as_int(v) -> tuple[int | None, str]:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None, ""
    try:
        f = float(str(v).replace(",", ".").replace(" ", "")) if not isinstance(v, (int, float)) else float(v)
    except ValueError:
        return None, f"«{v}» — не число"
    if not f.is_integer():
        return None, f"«{_as_text(v)}» — нужно целое число"
    return int(f), ""


def parse_orders(rows: list[list], batches: list[dict], routes_for, machines, existing: list[dict],
                 create_missing: bool) -> list[dict]:
    """Строки листа → заказы с проверкой. routes_for(parsed) → варианты маршрутов (route_options).
    Каждый результат: {row, поля…, route_opt, errors[], warnings[], create, status: ok | error | skip}."""
    hdr_i = next((i for i, r in enumerate(rows[:15]) if "batch_number" in _header_map(r)), None)
    if hdr_i is None:
        return [{"row": 0, "errors": ["не найдена строка заголовков со столбцом «№ партии»"], "warnings": [],
                 "status": "error"}]
    hm = _header_map(rows[hdr_i])
    by_bn = {b["batch_number"]: b for b in batches}
    seen = {(o["batch_number"], o.get("qty"), (o.get("due_date") or "")[:10]) for o in existing}
    in_file = set()
    out = []
    for ri in range(hdr_i + 1, len(rows)):
        r = rows[ri]
        get = lambda f: r[hm[f]] if f in hm and hm[f] < len(r) else None
        if all(_as_text(get(f)) == "" for f, *_ in ORDER_FIELDS):
            continue
        o = {"row": ri + 1, "errors": [], "warnings": [], "create": False}
        bn = _as_text(get("batch_number"))
        o["batch_number"] = bn
        o["batch_name"] = _as_text(get("batch_name"))
        o["notes"] = _as_text(get("notes"))
        qty, e1 = _as_int(get("qty"))
        prio, e2 = _as_int(get("priority"))
        nb, e3 = _as_dt(get("not_before"))
        due, e4 = _as_dt(get("due_date"))
        for e, f in ((e1, "Количество"), (e2, "Приоритет"), (e3, "Не раньше"), (e4, "Срок")):
            if e:
                o["errors"].append(f"{f}: {e}")
        if qty is not None and qty <= 0:
            o["errors"].append("Количество должно быть больше нуля")
        if prio is not None and prio < 1:
            o["errors"].append("Приоритет — 1 и больше (1 — самый срочный)")
        o.update(qty=qty, priority=prio, not_before=_s(nb) if nb else None, due_date=due.date().isoformat() if due else None)
        b = by_bn.get(bn)
        if not bn:
            o["errors"].append("не указан № партии")
        elif not b:
            if create_missing and o["batch_name"] and qty:
                o["create"] = True
                o["warnings"].append("партии нет во вкладке «Партии» — будет создана")
            else:
                o["errors"].append("нет такой партии во вкладке «Партии»"
                                   + ("" if create_missing else " (можно включить «создавать отсутствующие партии»)")
                                   + ("" if not create_missing or (o["batch_name"] and qty) else ": для новой нужны название и количество"))
        name = (b or {}).get("batch_name") or o["batch_name"]
        p = tech.parse_article(name) if name else {}
        opts = routes_for(p)
        rtext = _as_text(get("route"))
        ropt = resolve_route(rtext, opts, machines) if rtext else (opts[0] if opts else None)
        if rtext and not ropt:
            o["errors"].append(f"маршрут «{rtext}» не найден (название маршрута или станки: 235+2100, 2105, MILL)")
        elif not ropt:
            o["errors"].append("нет ни одного маршрута")
        o["route_opt"] = ropt
        o["route"] = ropt["name"] if ropt else rtext
        o["route_auto"] = bool(ropt) and not rtext
        mpc, e5 = parse_min_pc(get("min_pc"), ropt["machines"] if ropt else ())
        if e5:
            o["errors"].append(f"Мин/шт: {e5}")
        o["min_pc"] = _as_text(get("min_pc"))
        o["mpc"] = mpc
        o["name"] = name
        o["parsed"] = p
        if b and qty and b.get("total_qty") and qty > int(b["total_qty"]):
            o["warnings"].append(f"количество больше плана партии ({b['total_qty']} шт)")
        if due and nb and due.date() < nb.date():
            o["errors"].append("срок раньше даты «Не раньше»")
        key = (bn, qty, o["due_date"] or "")
        if bn and key in seen:
            o["warnings"].append("такой заказ уже загружен — строка будет пропущена")
            o["status"] = "skip"
        elif bn and key in in_file:
            o["warnings"].append("повтор строки в файле — будет пропущена")
            o["status"] = "skip"
        in_file.add(key)
        o.setdefault("status", "error" if o["errors"] else "ok")
        out.append(o)
    return out


def load_orders(tx, audit, good: list[dict], source: str, user: str) -> int:
    """Записывает проверенные заказы (и при необходимости создаёт партии) одной транзакцией. → создано партий."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    n_new = 0
    with tx() as conn:
        for o in good:
            if o["create"]:
                cur = conn.execute("INSERT OR IGNORE INTO batches (batch_number, batch_name, total_qty, notes, created_at) "
                                   "VALUES (?,?,?,?,?)", (o["batch_number"], o["batch_name"], int(o["qty"]),
                                                          f"создана импортом плана ({source})", now))
                if cur.rowcount:
                    n_new += 1
                    audit(conn, "insert", "batches", cur.lastrowid, None,
                          {"batch_number": o["batch_number"], "batch_name": o["batch_name"], "total_qty": o["qty"],
                           "source": "импорт плана"})
            row = {"batch_number": o["batch_number"], "qty": o["qty"], "route": "" if o["route_auto"] else o["route"],
                   "not_before": o["not_before"], "due_date": o["due_date"], "priority": o["priority"],
                   "min_pc": o["min_pc"], "notes": o["notes"], "source": source, "created_by": user, "created_at": now}
            cur = conn.execute(f"INSERT INTO plan_orders ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                               tuple(row.values()))
            audit(conn, "insert", "plan_orders", cur.lastrowid, None, row)
    return n_new


def order_planned(items: list[dict]) -> dict:
    """{order_id: штук в плане} (связка считается один раз)."""
    seen, out = set(), {}
    for it in items:
        oid = it.get("order_id")
        if oid and it["kind"] == "партия":
            g = (oid, it.get("grp") or it["id"])
            if g not in seen:
                seen.add(g)
                out[oid] = out.get(oid, 0) + int(it.get("qty") or 0)
    return out


def _order_sort_key(o):
    return (o.get("priority") is None, o.get("priority") or 0, o.get("due_date") is None, o.get("due_date") or "", o["id"])


def place_orders(q, ctx, items: list[dict], orders: list[dict], batches: list[dict], arts: dict, made: set,
                 hist: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    """Ставит заказы в план по порядку (приоритет → срок → порядок загрузки), каждый — в конец очереди своих
    станков, не раньше «Не раньше». Уже стоящие позиции не двигаются. → (новый план, отчёт по заказам)."""
    work = [dict(i) for i in items]
    planned = order_planned(items)
    by_bn = {b["batch_number"]: b for b in batches}
    report = []
    for o in sorted(orders, key=_order_sort_key):
        r = {"Заказ": o["id"], "Партия": o["batch_number"], "Итог": "", "Начало": "", "Окончание": ""}
        report.append(r)
        b = by_bn.get(o["batch_number"])
        left = int(o.get("qty") or (b or {}).get("total_qty") or 0) - planned.get(o["id"], 0)
        if not b:
            r["Итог"] = "❌ партии нет во вкладке «Партии»"
            continue
        if left <= 0:
            r["Итог"] = "уже в плане"
            continue
        p = (arts.get(o["batch_number"]) or {}).get("parsed") or tech.parse_article(b.get("batch_name") or "")
        opts = route_options(q, ctx, p)
        route = resolve_route(o.get("route") or "", opts, ctx["machines"]) if o.get("route") else (opts[0] if opts else None)
        if not route:
            r["Итог"] = f"❌ маршрут «{o.get('route')}» не найден"
            continue
        mpc, err = parse_min_pc(o.get("min_pc"), route["machines"])
        if err:
            r["Итог"] = f"❌ Мин/шт: {err}"
            continue
        for n in batch_norms(hist, p, route["machines"]):
            if n["machine"] not in mpc and n["min_pc"] is not None:
                mpc[n["machine"]] = n["min_pc"]
        miss = [m for m in route["machines"] if m not in mpc]
        if miss:
            r["Итог"] = "❌ нет нормы мин/шт для " + ", ".join(miss) + " — укажите в столбце «Мин/шт»"
            continue
        nb = _dt(o["not_before"]) if o.get("not_before") else None
        new = new_batch_items(o["batch_number"], left, route, mpc, o.get("notes") or "", queue_end(work, route["machines"], nb),
                              order_id=o["id"], due=o.get("due_date"))
        work = place_new(work, new, ctx, arts, made)
        mine = [w for w in work if w.get("_tmp") in {n["_tmp"] for n in new}]
        end = max(w["end"] for w in mine)
        r.update({"Начало": min(w["start"] for w in mine), "Окончание": end,
                  "Итог": f"✅ {left} шт · {route['name']}" + (f" · ⏰ не успевает к сроку {_d_ru(o['due_date'])}"
                                                               if o.get("due_date") and end[:10] > o["due_date"] else "")})
    return work, report


def template_xlsx(q, ctx) -> bytes:
    """Шаблон загрузки плана: лист «План», «Справка» и «Маршруты»."""
    head = [title for _f, title, _a, _w in ORDER_FIELDS]
    widths = [w for *_x, w in ORDER_FIELDS]
    help_rows = [
        ["Столбец", "Что писать", "Пример"],
        ["№ партии*", "Номер партии как во вкладке «Партии». Обязательно. Столбец текстовый — номер 311.10 не превратится в 311,1.", "317.4"],
        ["Название (для новой партии)", "Нужно, только если партии ещё нет и при загрузке включено «создавать отсутствующие партии».", "FNMC12M-8N-SA"],
        ["Количество, шт", "Сколько поставить в план. Пусто — план партии.", "400"],
        ["Маршрут / станок", "Название маршрута из технологии или станки: 235+2100, 2105, 2100, АПТ, MILL. Пусто — маршрут по умолчанию для вида фитинга.", "235+2100"],
        ["Не раньше", "Не начинать раньше этой даты (и времени). Пусто — сразу в конец очереди станков.", "20.10.2026 07:00"],
        ["Срок", "Срок готовности. В графике партия, которая не успевает к сроку, отмечается ⏰.", "31.10.2026"],
        ["Приоритет", "1 — самый срочный. Заказы ставятся по приоритету, затем по сроку, затем по порядку строк. Пусто — после всех.", "1"],
        ["Мин/шт", "Норма времени, если нет истории: одно число на все станки маршрута или по станкам через «;».", "235=0.53; 2100=0.2"],
        ["Примечание", "Любой текст — попадёт в позицию плана.", "срочно для заказчика"],
        [],
        ["Заголовки можно не менять; порядок столбцов любой, лишние столбцы игнорируются. Пустые строки пропускаются."],
        ["Повторная загрузка того же заказа (партия + количество + срок) пропускается."],
    ]
    route_rows = [["Маршрут", "Станки", "Связка (старт одновременно)"]]
    for o in route_options(q, ctx, {}):
        route_rows.append([o["name"], " + ".join(o["machines"]), "да" if o["parallel"] else ""])
    return xlsxlite.write_xlsx([("План", [head], widths, {0}), ("Справка", help_rows, [28, 90, 24]),
                                ("Маршруты", route_rows, [36, 36, 26])])


def _tab_orders(q, tx, audit, all_batches, batch_is_archived):
    ctx = load_ctx(q)
    _flash("plan_orders_flash")
    st.markdown("#### Загрузка плана из Excel")
    st.caption("Скачайте шаблон, заполните лист «План» (по строке на партию) и загрузите. Система проверит каждую строку; "
               "загруженные заказы появятся в таблице ниже, откуда их можно поставить в план — по приоритету и сроку, "
               "в конец очереди станков маршрута.")
    st.download_button("⬇️ Скачать шаблон Excel", template_xlsx(q, ctx), file_name="шаблон_план_станков.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="plan_tpl")
    up = st.file_uploader("Файл плана (.xlsx)", type=["xlsx"], key="plan_upload")
    create_missing = st.checkbox("Создавать отсутствующие партии во вкладке «Партии» (нужны название и количество)",
                                 key="plan_create_missing")
    batches = all_batches()
    orders = q("SELECT * FROM plan_orders ORDER BY id")
    if up is not None:
        try:
            book = xlsxlite.read_xlsx(up.getvalue())
        except Exception as ex:                      # битый файл — показываем понятную ошибку, а не трассировку
            st.error(f"Не удалось прочитать файл: {ex}")
            book = None
        if book:
            names = list(book)
            sheet = "План" if "План" in book else names[0]
            if len(names) > 1:
                sheet = st.selectbox("Лист", names, index=names.index(sheet), key="plan_upload_sheet")
            parsed = parse_orders(book[sheet], batches, lambda p: route_options(q, ctx, p), ctx["machines"], orders,
                                  create_missing)
            arch = {b["batch_number"] for b in batches
                    if batch_is_archived(b.get("archive_state"), b.get("total_qty"), b.get("final_opta"))}
            for o in parsed:
                if o.get("batch_number") in arch:
                    o["warnings"].append("партия в архиве")
            pv = pd.DataFrame([{"Строка": o["row"], "Партия": o.get("batch_number", ""), "Название": o.get("name", ""),
                                "Кол-во": o.get("qty"), "Маршрут": (o.get("route") or "") + (" (по умолчанию)" if o.get("route_auto") else ""),
                                "Не раньше": o.get("not_before") or "", "Срок": _d_ru(o.get("due_date")),
                                "Приоритет": o.get("priority"), "Мин/шт": o.get("min_pc", ""),
                                "Итог": {"ok": "✅", "skip": "⏭ пропуск", "error": "❌"}[o["status"]],
                                "Ошибки / замечания": "; ".join(o["errors"] + o["warnings"])} for o in parsed])
            st.dataframe(pv, use_container_width=True, hide_index=True)
            good = [o for o in parsed if o["status"] == "ok"]
            n_err = sum(o["status"] == "error" for o in parsed)
            st.caption(f"Строк: {len(parsed)} · к загрузке: {len(good)} · с ошибками: {n_err} · пропуск: "
                       f"{sum(o['status'] == 'skip' for o in parsed)}. Строки с ошибками не загружаются — исправьте файл и загрузите снова.")
            if good and st.button(f"📥 Загрузить заказы ({len(good)})", type="primary", key="plan_upload_go"):
                n_new = load_orders(tx, audit, good, up.name, st.session_state.get("username") or "")
                st.session_state["plan_orders_flash"] = (True, f"Загружено заказов: {len(good)}" +
                                                         (f", создано партий: {n_new}" if n_new else "") + ".")
                st.rerun()

    st.markdown("#### Заказы")
    if not orders:
        st.info("Заказов нет. Загрузите файл выше.")
        return
    items = load_items(q)
    planned = order_planned(items)
    names = {b["batch_number"]: b.get("batch_name") or "" for b in batches}
    df = pd.DataFrame([{"Выбрать": False, "ID": o["id"], "Партия": o["batch_number"], "Название": names.get(o["batch_number"], "—"),
                        "Кол-во": o["qty"], "В плане, шт": planned.get(o["id"], 0),
                        "Статус": ("в плане" if o["qty"] and planned.get(o["id"], 0) >= o["qty"] else
                                   "частично" if planned.get(o["id"]) else "не в плане"),
                        "Маршрут": o["route"] or "по умолчанию", "Не раньше": o["not_before"] or "",
                        "Срок": _d_ru(o["due_date"]), "Приоритет": o["priority"], "Мин/шт": o["min_pc"] or "",
                        "Примечание": o["notes"] or "", "Файл": o["source"] or ""} for o in sorted(orders, key=_order_sort_key)])
    ed = st.data_editor(df, hide_index=True, use_container_width=True, key=f"plan_orders_ed_{len(orders)}",
                        disabled=[c for c in df.columns if c != "Выбрать"],
                        column_config={"Выбрать": st.column_config.CheckboxColumn(width="small")})
    sel = [int(r["ID"]) for r in ed.to_dict("records") if r["Выбрать"]]
    todo = [o for o in orders if not (o["qty"] and planned.get(o["id"], 0) >= o["qty"])]
    c1, c2, c3 = st.columns(3)
    go_sel = c1.button(f"📌 Поставить выбранные в план ({len(sel)})", disabled=not sel, key="plan_orders_place_sel")
    go_all = c2.button(f"📌 Поставить все непоставленные ({len(todo)})", disabled=not todo, key="plan_orders_place_all",
                       type="primary")
    with c3.popover(f"🗑 Удалить выбранные заказы ({len(sel)})", disabled=not sel):
        st.write("Удаляются только строки заказов. Уже поставленные в план позиции остаются в графике.")
        if st.button("Да, удалить", key="plan_orders_del", type="primary"):
            with tx() as conn:
                for oid in sel:
                    old = conn.execute("SELECT * FROM plan_orders WHERE id=?", (oid,)).fetchone()
                    conn.execute("DELETE FROM plan_orders WHERE id=?", (oid,))
                    audit(conn, "delete", "plan_orders", oid, dict(old) if old else None)
            st.session_state["plan_orders_flash"] = (True, f"Удалено заказов: {len(sel)}.")
            st.rerun()
    if go_sel or go_all:
        chosen = [o for o in orders if o["id"] in set(sel)] if go_sel else todo
        arts = article_info(q, batches)
        hist = tech.load_history(q)
        res, report = place_orders(q, ctx, items, chosen, batches, arts, made_from_history(hist), hist)
        bad = conflicts(res)
        if bad:
            st.session_state["plan_orders_flash"] = (False, "План не сохранён: " + "; ".join(bad[:3]))
        elif any(r.get("_tmp") for r in res):
            save_result(tx, audit, items, res)
            st.session_state["plan_orders_flash"] = (True, "Заказы поставлены в план — см. отчёт ниже и вкладку «🗓 График».")
        else:
            st.session_state["plan_orders_flash"] = (False, "Ничего не поставлено — см. отчёт ниже.")
        st.session_state["plan_orders_report"] = report
        st.rerun()
    rep = st.session_state.pop("plan_orders_report", None)
    if rep:
        st.markdown("**Отчёт о постановке**")
        st.dataframe(pd.DataFrame(rep), use_container_width=True, hide_index=True)
