"""
=============================================================================
  НТА-Контроль — рабочее время завода (смены, обеды, выходные, праздники)
  Чистая логика без Streamlit: используют планирование и себестоимость.
=============================================================================
Режим смен — записи с датой начала действия: на дату действуют все смены
с наибольшей valid_from ≤ даты. Смена: начало, конец, обед (начало, минуты).
Рабочая неделя — пн–пт все смены режима, суббота — по умолчанию 1 смена (настройка), воскресенье — выходной.
Исключения — календарём {день: 'выходной' | '1 смена' | 'рабочий' (все смены режима)}; число смен в субботу
по умолчанию передаётся в том же словаре ключом SAT_KEY.
"""
from datetime import date, datetime, time, timedelta

WORK_WEEKDAYS = {0, 1, 2, 3, 4, 5}          # пн–сб — рабочие дни
SATURDAY = 5
SAT_KEY = "__saturday_shifts__"             # в календаре: сколько смен в субботу по умолчанию (0 — выходной)
DEFAULT_SAT_SHIFTS = 1
DAY_KINDS = ("выходной", "1 смена", "рабочий")   # отметки календаря; «рабочий» — все смены режима
DEFAULT_SHIFTS = [                           # действует, пока в регистре нет записей
    {"valid_from": "2000-01-01", "shift_no": 1, "start": "07:00", "end": "15:30", "lunch_start": "11:00", "lunch_min": 30},
    {"valid_from": "2000-01-01", "shift_no": 2, "start": "15:00", "end": "23:30", "lunch_start": "19:00", "lunch_min": 30},
]


def _t(s: str) -> time:
    h, m = str(s).strip().replace(".", ":").split(":")[:2]
    return time(int(h), int(m))


def norm_shift(r: dict) -> dict:
    """Строка регистра plan_shifts (shift_start / shift_end) → {start, end, …}."""
    if "start" in r:
        return r
    return dict(r, start=(r.get("shift_start") or "").strip(), end=(r.get("shift_end") or "").strip())


def _ok_time(s) -> bool:
    try:
        _t(s)
        return True
    except (ValueError, AttributeError):
        return False


def shifts_for(day: date, shift_rows: list[dict]) -> list[dict]:
    """Смены, действующие на день (вся группа с наибольшей valid_from ≤ дня). Строки с неверным временем пропускаются."""
    rows = [r for r in map(norm_shift, shift_rows or []) if str(r.get("valid_from") or "")[:10] <= day.isoformat()
            and _ok_time(r.get("start")) and _ok_time(r.get("end"))]
    if not rows:
        return [r for r in DEFAULT_SHIFTS]
    vf = max(str(r["valid_from"])[:10] for r in rows)
    return sorted([r for r in rows if str(r["valid_from"])[:10] == vf], key=lambda r: int(r.get("shift_no") or 0))


def shift_limit(day: date, calendar: dict) -> int | None:
    """Сколько смен режима работает в день: 0 — выходной, None — все, 1 — только первая."""
    cal = calendar or {}
    kind = cal.get(day.isoformat())
    if kind == "выходной":
        return 0
    if kind == "1 смена":
        return 1
    if kind == "рабочий":
        return None
    wd = day.weekday()
    if wd == SATURDAY:
        n = cal.get(SAT_KEY, DEFAULT_SAT_SHIFTS)
        n = DEFAULT_SAT_SHIFTS if n is None else int(n)
        return None if n >= 9 else n                 # 9+ — «все смены»
    return None if wd in WORK_WEEKDAYS else 0


def default_kind(day: date, calendar: dict) -> str:
    """Отметка дня без исключения в календаре (для показа и сохранения только отличий)."""
    n = shift_limit(day, {SAT_KEY: (calendar or {}).get(SAT_KEY, DEFAULT_SAT_SHIFTS)})
    return "выходной" if n == 0 else "1 смена" if n == 1 else "рабочий"


def is_working_day(day: date, calendar: dict) -> bool:
    return shift_limit(day, calendar) != 0


def _merge(intervals):
    out = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def day_periods(day: date, shift_rows: list[dict], calendar: dict) -> list[dict]:
    """Непрерывные периоды работы станка за день (смены, перекрывающиеся на пересменке, сливаются).
    Каждый период: {'start','end','work': [(s,e) рабочие интервалы без обедов]}."""
    lim = shift_limit(day, calendar)
    if lim == 0:
        return []
    spans, lunches = [], []
    for r in shifts_for(day, shift_rows)[:lim]:
        s = datetime.combine(day, _t(r["start"]))
        e = datetime.combine(day, _t(r["end"]))
        if e <= s:                                   # смена через полночь
            e += timedelta(days=1)
        spans.append((s, e))
        if _ok_time(r.get("lunch_start")) and int(r.get("lunch_min") or 0) > 0:
            ls = datetime.combine(day, _t(r["lunch_start"]))
            if ls < s:
                ls += timedelta(days=1)
            lunches.append((ls, ls + timedelta(minutes=int(r["lunch_min"]))))
    periods = []
    for ps, pe in _merge(spans):
        work, cur = [], ps
        for ls, le in sorted(lunches):
            if le <= cur or ls >= pe:
                continue
            if ls > cur:
                work.append((cur, ls))
            cur = max(cur, le)
        if cur < pe:
            work.append((cur, pe))
        periods.append({"start": ps, "end": pe, "work": work})
    return periods


def hours_per_day(day: date, shift_rows: list[dict], calendar: dict | None = None, force_working=True) -> float:
    """Рабочие часы станка в обычный рабочий день по режиму на эту дату (для ставок себестоимости)."""
    cal = {} if force_working else (calendar or {})
    d = day
    if force_working:                                # берём ближайший будний день (пн–пт, все смены)
        while d.weekday() >= SATURDAY:
            d += timedelta(days=1)
    return sum((e - s).total_seconds() for p in day_periods(d, shift_rows, cal) for s, e in p["work"]) / 3600


def work_hours_between(a: datetime, b: datetime, shift_rows, calendar) -> float:
    """Рабочие часы в промежутке [a, b)."""
    total, d = 0.0, a.date() - timedelta(days=1)
    while d <= b.date():
        for p in day_periods(d, shift_rows, calendar):
            for s, e in p["work"]:
                lo, hi = max(s, a), min(e, b)
                if hi > lo:
                    total += (hi - lo).total_seconds()
        d += timedelta(days=1)
    return total / 3600


def iter_work(from_dt: datetime, shift_rows, calendar, horizon_days=800):
    """Рабочие интервалы начиная с from_dt: (s, e, period_end, period_work_left_from_s)."""
    d = from_dt.date() - timedelta(days=1)
    end_day = from_dt.date() + timedelta(days=horizon_days)
    while d <= end_day:
        for p in day_periods(d, shift_rows, calendar):
            if p["end"] <= from_dt:
                continue
            for s, e in p["work"]:
                if e <= from_dt:
                    continue
                s2 = max(s, from_dt)
                left = sum((max(min(we, p["end"]), s2) - max(ws, s2)).total_seconds()
                           for ws, we in p["work"] if we > s2) / 3600
                yield s2, e, p["end"], left
        d += timedelta(days=1)


def add_work_hours(start: datetime, hours: float, shift_rows, calendar) -> datetime:
    """Момент, когда будет отработано hours рабочих часов, начиная со start (через обеды, ночи, выходные)."""
    left = hours * 3600
    last = start
    for s, e, _pe, _l in iter_work(start, shift_rows, calendar):
        span = (e - s).total_seconds()
        if span >= left:
            return s + timedelta(seconds=left)
        left -= span
        last = e
    return last


def back_work_hours(t: datetime, hours: float, shift_rows, calendar) -> datetime:
    """Самый поздний момент s ≤ t, от которого до t ровно hours рабочих часов (обратное к add_work_hours)."""
    if hours <= 0:
        return t
    lo, hi = t - timedelta(days=max(3, int(hours / 4) + 10)), t
    while work_hours_between(lo, t, shift_rows, calendar) < hours:
        lo -= timedelta(days=30)
    for _ in range(40):                              # бинарный поиск до секунды
        mid = lo + (hi - lo) / 2
        if work_hours_between(mid, t, shift_rows, calendar) >= hours:
            lo = mid
        else:
            hi = mid
        if (hi - lo).total_seconds() < 1:
            break
    return lo


def first_start(from_dt: datetime, shift_rows, calendar, min_left_h: float = 2.0) -> datetime:
    """Первый момент ≥ from_dt, когда можно начать новую партию: до конца непрерывного периода работы
    (конец последней смены дня) должно оставаться не меньше min_left_h рабочих часов."""
    for s, e, _pe, left in iter_work(from_dt, shift_rows, calendar):
        if left >= min_left_h:
            return s
    return from_dt


def month_work_hours(year: int, month: int, shift_rows, calendar) -> float:
    d, total = date(year, month, 1), 0.0
    while d.month == month:
        total += sum((e - s).total_seconds() for p in day_periods(d, shift_rows, calendar) for s, e in p["work"]) / 3600
        d += timedelta(days=1)
    return total
