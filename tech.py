"""
=============================================================================
  НТА-Контроль — технологический модуль (только admin)
  Разбор артикула, история выпуска, оценка партии, торцы, калибры, металл,
  поковки. Справочники и журналы — таблицы tech_* в той же SQLite.
=============================================================================
Разбор артикула — по схеме каталога НТА-Пром:
  [префикс FN|D (обжимной, D = DK-LOK) | TFN|G (резьбовой)] [тип] [размеры через «-»] [-исполнение]
  FNMC12M-8N-SA → FN · MC · трубка 12 мм · наружная резьба 1/2" NPT · S (316L) + A (в сборе)
"""

import re
from datetime import date, datetime

import pandas as pd
import streamlit as st

import workcal

# ═══════════════════════════════════════════════════════════════════════════
#  РАЗБОР АРТИКУЛА (чистая логика, без БД)
# ═══════════════════════════════════════════════════════════════════════════

# Кириллица, внешне неотличимая от латиницы (встречается в названиях партий: «8М», «SА»)
_LOOKALIKE = str.maketrans("АВЕКМНОРСТХУЅІаеокрсхуі", "ABEKMHOPCTXYSIaeokpcxyi")

# Слоты торцов: tube — обжимной торец под трубку; male/female — наружная/внутренняя резьба;
# stub — трубный хвостовик (вставляется в другой фитинг); weld — патрубок под приварку;
# nut — гайка (внутренняя резьба обжимного соединения под трубку).
# forging: L / T / X — делается из поковки.
COMPRESSION_TYPES = {
    "U":    ("Проходная муфта",                         ["tube", "tube"], None),
    "L":    ("Проходной угольник",                      ["tube", "tube"], "L"),
    "T":    ("Проходной тройник",                       ["tube", "tube", "tube"], "T"),
    "X":    ("Проходная крестовина",                    ["tube", "tube", "tube", "tube"], "X"),
    "UB":   ("Муфта с монтажной гайкой",                ["tube", "tube"], None),
    "BL":   ("Проходной угольник с монтажной гайкой",   ["tube", "tube"], "L"),
    "UR":   ("Переходная муфта",                        ["tube", "tube"], None),
    "LR":   ("Переходной угольник",                     ["tube", "tube"], "L"),
    "XR":   ("Переходная крестовина",                   ["tube", "tube", "tube", "tube"], "X"),
    "TR":   ("Переходной тройник",                      ["tube", "tube", "tube"], "T"),
    "MC":   ("Штуцер с наружной резьбой",               ["tube", "male"], None),
    "MCT":  ("Полнопроходной штуцер под термопару",     ["tube", "male"], None),
    "MCB":  ("Штуцер с наружной резьбой и монтажной гайкой", ["tube", "male"], None),
    "MCS":  ("Неповоротный штуцер с цилиндрической резьбой SAE/MS", ["tube", "male"], None),
    "LBM":  ("Ввертной угольник 45°",                   ["tube", "male"], "L"),
    "LM":   ("Ввертной угольник",                       ["tube", "male"], "L"),
    "TRM":  ("Ввертной тройник с боковым отводом",      ["tube", "tube", "male"], "T"),
    "TBM":  ("Ввертной тройник",                        ["tube", "male", "tube"], "T"),
    "CF":   ("Штуцер с внутренней резьбой",             ["tube", "female"], None),
    "CBF":  ("Штуцер с внутренней резьбой и монтажной гайкой", ["tube", "female"], None),
    "LF":   ("Навертной угольник",                      ["tube", "female"], "L"),
    "TRF":  ("Навертной тройник с боковым отводом",     ["tube", "tube", "female"], "T"),
    "TBF":  ("Навертной тройник",                       ["tube", "female", "tube"], "T"),
    "R":    ("Переходник",                              ["tube", "stub"], None),
    "AB":   ("Переходник с монтажной гайкой",           ["stub", "male"], None),
    "AM":   ("Переходник с наружной резьбой",           ["stub", "male"], None),
    "AF":   ("Переходник с внутренней резьбой",         ["stub", "female"], None),
    "LA":   ("Переходной угольник",                     ["tube", "stub"], "L"),
    "TRA":  ("Переходной тройник с боковым отводом",    ["tube", "tube", "stub"], "T"),
    "TBA":  ("Симметричный переходной тройник",         ["tube", "stub", "tube"], "T"),
    "LS":   ("Поворотный ввертной угольник SAE/MS",     ["tube", "male"], "L"),
    "LBS":  ("Поворотный ввертной угольник 45° SAE/MS", ["tube", "male"], "L"),
    "TRS":  ("Поворотный ввертной тройник с боковым отводом SAE/MS", ["tube", "tube", "male"], "T"),
    "TBS":  ("Поворотный ввертной тройник SAE/MS",      ["tube", "male", "tube"], "T"),
    "CW":   ("Приварное соединение встык",              ["tube", "weld"], None),
    "LW":   ("Угольник для приварки встык",             ["tube", "weld"], "L"),
    "CSW":  ("Соединитель для приварки враструб",       ["tube", "weld"], None),
    "LSW":  ("Угольник для приварки враструб",          ["tube", "weld"], "L"),
    "BUW":  ("Проходная муфта под приварку",            ["tube", "weld"], None),
    "P":    ("Заглушка",                                ["stub"], None),
    "C":    ("Колпак",                                  ["tube"], None),   # выточенный колпак + гайка и кольца
    "N":    ("Гайка",                                   ["nut"], None),
    "UBN":  ("Монтажная гайка",                         ["nut"], None),
    "CP":   ("Соединение для проходного канала",        ["tube", "tube"], None),
    "CRP":  ("Переходник для проходного канала",        ["tube", "tube"], None),
    "UA":   ("Муфта стандарта AN",                      ["tube", "tube"], None),
    "UBA":  ("Муфта с монтажной гайкой стандарта AN",   ["tube", "tube"], None),
    "EU":   ("Фитинг с диэлектрической вставкой",       ["tube", "tube"], None),
}
THREADED_TYPES = {
    "NH":   ("Ниппель под ключ",                        ["male", "male"], None),
    "NR":   ("Переходной ниппель под ключ",             ["male", "male"], None),
    "NL":   ("Длинный ниппель",                         ["male", "male"], None),
    "HB":   ("Переходная втулка",                       ["male", "female"], None),
    "C":    ("Колпак",                                  ["female"], None),
    "P":    ("Заглушка",                                ["male"], None),
    "CG":   ("Шестигранная муфта",                      ["female", "female"], None),
    "CGR":  ("Шестигранная переходная муфта",           ["female", "female"], None),
    "CS":   ("Переходник NPT — цилиндрическая",         ["male", "female"], None),
    "CSMF": ("Корпус разборного соединения",            ["male", "female"], None),
    "CSN":  ("Накидная гайка разборного соединения",    ["male"], None),
    "L":    ("Угольник",                                ["female", "female"], "L"),
    "LM":   ("Угольник с внешними резьбами",            ["male", "male"], "L"),
    "LS":   ("Угольник внутренняя — внешняя",           ["female", "male"], "L"),
    "LSR":  ("Переходной угольник",                     ["female", "male"], "L"),
    "T":    ("Тройник",                                 ["female", "female", "female"], "T"),
    "TM":   ("Тройник с внешней резьбой",               ["male", "male", "male"], "T"),
    "TB":   ("Тройник с отводом",                       ["female", "female", "male"], "T"),
    "TR":   ("Переходной тройник",                      ["female", "female", "female"], "T"),
    "X":    ("Крестовина",                              ["female", "female", "female", "female"], "X"),
    "AMF":  ("Переходник внешняя — внутренняя",         ["male", "female"], None),
    "ABMF": ("Переходник внешняя — внутренняя",         ["male", "female"], None),
    "AAMF": ("Переходник внешняя — внутренняя",         ["male", "female"], None),
    "SLMC": ("Штуцер с наружной резьбой",               ["male", "male"], None),
    "CFSW": ("Соединитель с внутренней резьбой под приварку", ["weld", "female"], None),
    "LMSW": ("Угольник под приварку с внешней резьбой", ["weld", "male"], "L"),
    "LFSW": ("Угольник под приварку с внутренней резьбой", ["weld", "female"], "L"),
}

PIPE_SIZE = {1: '1/16"', 2: '1/8"', 3: '3/16"', 4: '1/4"', 5: '5/16"', 6: '3/8"', 8: '1/2"',
             10: '5/8"', 12: '3/4"', 14: '7/8"', 16: '1"', 20: '1-1/4"', 24: '1-1/2"', 32: '2"'}
THREAD_TYPES = {  # код из таблицы 3 каталога → (обозначение, коническая?)
    "N": ("NPT", True), "R": ("BSPT (R)", True),
    "G": ("BSPP (G)", False), "GB": ("BSPP (G)", False), "GP": ("BSPP (G)", False),
    "GG": ("BSPP (G)", False), "GR": ("BSPP (G)", False), "GY": ("BSPP (G)", False),
    "U": ("UNF", False), "UO": ("UNF", False), "UP": ("UNF", False), "NO": ("NPT", True),
}
MATERIALS = {"S": "316/316L", "B": "латунь", "C": "углеродистая сталь", "D": "дуплекс",
             "SD": "супер-дуплекс", "HC": "Hastelloy C276", "M": "сплав 400 (монель)",
             "IN": "сплав 600", "TI": "титан", "PE": "ПТФЭ"}
FAMILY = {"FN": "обжимной", "D": "обжимной (DK-LOK)", "TFN": "резьбовой", "G": "резьбовой (DK-LOK)"}


def tube_label(code: str) -> str:
    if code.endswith("M"):
        return f"Ø{code[:-1]} мм"
    n = int(code)
    return f"Ø{PIPE_SIZE.get(n, f'{n}/16' + chr(34))}"


def _classify(seg: str):
    """Сегмент размера → (kind, data). kind: tube | pipe | metric | weld | length | unknown."""
    if m := re.fullmatch(r"(\d+)L", seg):
        return "length", {"mm": int(m.group(1)), "label": f"длина {m.group(1)} мм"}
    if re.fullmatch(r"\d+\.\d+", seg):
        return "length", {"label": f"длина {seg}\""}
    if m := re.fullmatch(r"(\d+)M(\d{2})([A-Z]*)", seg):
        d, p = int(m.group(1)), int(m.group(2)) / 10
        p_s = f"{p:g}".replace(".", ",")
        return "metric", {"key": f"M{d}x{p:g}", "label": f"M{d}×{p_s}" + (f" (уплотнение {m.group(3)})" if m.group(3) else "")}
    if m := re.fullmatch(r"(\d+)(M?)", seg):
        code = m.group(1) + m.group(2)
        return "tube", {"code": code, "label": tube_label(code)}
    if m := re.fullmatch(r"(\d+)P", seg):
        return "weld", {"code": seg, "label": f"патрубок под приварку {PIPE_SIZE.get(int(m.group(1)), m.group(1))}"}
    if m := re.fullmatch(r"(\d+)(NO|N|R|GB|GP|GG|GR|GY|G|UO|UP|U)", seg):
        n, t = int(m.group(1)), m.group(2)
        name, taper = THREAD_TYPES[t]
        return "pipe", {"code": seg, "size": PIPE_SIZE.get(n, f"{n}/16\""), "type": t, "taper": taper,
                        "label": f"{PIPE_SIZE.get(n, f'{n}/16')} {name}" + (" (коническая)" if taper else "")}
    return "unknown", {"label": seg}


_ACCEPTS = {"tube": {"tube"}, "stub": {"tube"}, "nut": {"tube"},
            "male": {"pipe", "metric"}, "female": {"pipe", "metric"}, "weld": {"weld", "pipe", "tube"}}
SLOT_LABEL = {"tube": "обжимной торец под трубку", "stub": "трубный хвостовик", "nut": "гайка под трубку",
              "male": "наружная резьба", "female": "внутренняя резьба", "weld": "под приварку"}


def find_article(raw: str):
    """Ищет в названии партии токен, похожий на артикул фитинга. Возвращает (артикул, остаток текста)."""
    s = (raw or "").translate(_LOOKALIKE).upper()
    for tok in re.split(r"[\s/,;_]+", s):
        tok = tok.strip("\"'.()")
        if re.match(r"(?:TFN|FN|D|G)[A-Z]{1,6}(?:\d|-)", tok):
            return tok, s.replace(tok, " ").strip()
    return None, s


def parse_article(raw: str) -> dict:
    """Разбирает артикул. Ничего не угадывает молча: всё нераспознанное — в res['unknown']."""
    res = {"raw": raw, "ok": False, "unknown": [], "notes": []}
    art, rest = find_article(raw)
    if not art:
        res["error"] = "В названии нет артикула фитинга по схеме каталога (FN/D/TFN/G…)."
        return res
    res["article"] = art
    if rest and re.search(r"[A-ZА-Я]", rest):
        res["notes"].append(f"Приписка «{rest.lower()}» не учитывается.")
    m = re.match(r"(TFN|FN|G|D)([A-Z]+)(.*)", art)
    prefix, tcode, tail = m.group(1), m.group(2), m.group(3)
    table = THREADED_TYPES if prefix in ("TFN", "G") else COMPRESSION_TYPES
    res.update(prefix=prefix, family=FAMILY[prefix], type_code=tcode)
    segs = [x for x in tail.split("-") if x]
    material = None
    if segs and (mm := re.fullmatch(r"(SD|HC|IN|TI|PE|S|B|C|D|M)(A?)", segs[-1])):
        material = mm.group(1)
        res["assembled"] = mm.group(2) == "A"
        segs = segs[:-1]
    res["material"] = material
    res["material_label"] = MATERIALS.get(material) if material else None
    if not material:
        res["notes"].append("Исполнение (материал) не указано.")
    sizes, length = [], None
    for sgm in segs:
        kind, data = _classify(sgm)
        if kind == "length":
            length = data
        elif kind == "unknown":
            res["unknown"].append(sgm)
        else:
            sizes.append((kind, data))
    res["length"] = length
    if tcode not in table:
        res["type_name"] = None
        res["error"] = f"Тип «{tcode}» не найден в справочнике типов ({res['family']})."
        res["sizes"] = sizes
        return res
    name, slots, forging = table[tcode]
    res.update(type_name=name, forging=forging)
    ends = [None] * len(slots)
    leftovers = []
    for kind, data in sizes:
        for i, slot in enumerate(slots):
            if ends[i] is None and kind in _ACCEPTS[slot]:
                ends[i] = (slot, kind, data, "указан")
                break
        else:
            leftovers.append(data["label"])
    # незаполненные слоты — тот же размер, что у последнего заполненного слота того же вида
    for i, slot in enumerate(slots):
        if ends[i] is None:
            same = [e for e in ends if e and e[0] == slot] or \
                   [e for e in ends if e and _ACCEPTS[slot] & {e[1]}]
            if same:
                ends[i] = (slot, same[-1][1], same[-1][2], "тот же размер")
    res["unknown"] += leftovers
    res["ends"] = [{"slot": e[0], "slot_label": SLOT_LABEL[e[0]], "kind": e[1], **e[2], "how": e[3]}
                   if e else {"slot": slots[i], "slot_label": SLOT_LABEL[slots[i]], "kind": None,
                              "label": "размер не определён", "how": "—"}
                   for i, e in enumerate(ends)]
    res["ok"] = all(e["kind"] for e in res["ends"]) and not res["unknown"]
    res["key"] = canonical_key(res)
    return res


def canonical_key(p: dict) -> str | None:
    """Ключ фитинга без исполнения: D ≡ FN, G ≡ TFN; FNMC12M-8N-SA и DMC12M-8N-S → FNMC12M-8N."""
    if not p.get("article"):
        return None
    art = p["article"]
    if p.get("material"):
        art = re.sub(r"-(SD|HC|IN|TI|PE|S|B|C|D|M)A?$", "", art)
    # буква формы уплотнения у метрической резьбы на изготовление не влияет: 14M10B ≡ 14M10
    art = re.sub(r"(\d+M\d{2})[A-Z]+(?=-|$)", r"\1", art)
    if p["prefix"] == "D":
        art = "FN" + art[1:]
    elif p["prefix"] == "G":
        art = "TFN" + art[1:]
    return art


def end_key(e: dict) -> str | None:
    """Ключ торца для сравнения «делали ли такой раньше»."""
    if not e.get("kind"):
        return None
    if e["kind"] == "tube":
        return f"{e['slot']}:{e['code']}"
    if e["kind"] == "pipe":
        return f"{e['slot']}:{e['code']}"
    if e["kind"] == "metric":
        return f"{e['slot']}:{e['key']}"
    return f"{e['slot']}:{e.get('code', e['label'])}"


def end_label(e: dict) -> str:
    return f"{e['slot_label']} — {e['label']}"


# ═══════════════════════════════════════════════════════════════════════════
#  КАЛИБРЫ: разбор наименований и требования по торцам
# ═══════════════════════════════════════════════════════════════════════════

def _frac(s: str) -> str:
    return s.replace(" ", "")

# дюймовый размер резьбы: 7/8, 1, 1-1/8, 1-5/16 (смешанная дробь — иначе «1-1/8-20» читается как «1/8-20»)
_UN_SIZE = r"(?<![\d/])(\d+-\d+/\d+|\d+/\d+|\d+)"


def _bore_spec(bore: str | None):
    """«12,15 +0,04» → «BORE:12.15» (сравнение по номинальному диаметру)."""
    m = re.search(r"\d+[.,]?\d*", bore or "")
    return f"BORE:{float(m.group(0).replace(',', '.')):g}" if m else None

def parse_gauge_name(name: str) -> dict:
    """«Резьбовой калибр-пробка 7/8-20 UNEF-2B ПР» → kind=plug, spec=UN:7/8-20, cls=2B, side=ПР."""
    n = (name or "").replace(" ", " ")
    up = n.translate(_LOOKALIKE).upper()
    g = {"kind": "ring" if "КОЛЬЦО" in n.upper() else "plug" if "ПРОБКА" in n.upper() else None,
         "side": None, "spec": None, "cls": None, "smooth": "ГЛАДК" in n.upper()}
    if re.search(r"\bР-Г\b", n) or "P-Г" in n:
        g["side"] = "Р-Г"
    elif re.search(r"ПР\s*[-/]\s*НЕ|GO\s*/\s*NO", n.upper()):   # комплект в одном калибре
        g["side"] = "ПР-НЕ"
    elif re.search(r"\bНЕ\b", n):
        g["side"] = "НЕ"
    elif re.search(r"\bПР\b", n):
        g["side"] = "ПР"
    if g["smooth"] and (m := re.search(r"Ø\s*(\d+[.,]\d+)", n)):           # гладкий калибр отверстия
        g["spec"] = f"BORE:{float(m.group(1).replace(',', '.')):g}"
    elif m := re.search(rf"{_UN_SIZE}\s*-\s*(\d+)\s*(UNEF|UNF|UNC|UN)(?:\s*-?\s*(\d[AB]))?", up):
        g["spec"], g["cls"] = f"UN:{_frac(m.group(1))}-{m.group(2)}", m.group(4)
    elif m := re.search(r"\bM(\d+)\s*[XХ×]\s*(\d+(?:[,.]\d+)?)\s*-?\s*(\d[GHgh])?", up):
        pitch = float(m.group(2).replace(",", "."))
        g["spec"], g["cls"] = f"M:{int(m.group(1))}x{pitch:g}", m.group(3)
    elif m := re.search(r"\b(R|K)\s*(\d+(?:/\d+)?)\"", up):
        g["spec"] = f"{'R' if m.group(1) == 'R' else 'K'}:{m.group(2)}\""
    elif m := re.search(r"(?:КОЛЬЦО|ПРОБКА)\s+(\d+(?:/\d+)?)\"", n.upper()):   # без транслита: слова кириллицей
        g["spec"] = f"?:{m.group(1)}\""
    return g


def gauge_requirements(end: dict, tube_ends: dict) -> list[dict]:
    """Какие калибры нужны для торца. tube_ends: {'12M': {'body_thread', 'nut_thread', 'bore'}}."""
    req = []
    k, slot = end.get("kind"), end["slot"]
    if k == "tube" and slot in ("tube", "nut"):
        te = tube_ends.get(end["code"])
        if not te:
            return [{"what": f"торец {end['label']}", "spec": None, "kind": None,
                     "missing_ref": f"нет данных о торце {end['code']} в справочнике торцов"}]
        un = _un_spec(te.get("body_thread") or te.get("nut_thread"))
        no_thr = None if un else f"резьба для торца {end['code']} не указана в справочнике торцов"
        if slot == "tube":
            req.append({"what": f"резьба корпуса под гайку {te.get('body_thread') or '—'}", "spec": un, "kind": "ring",
                        "missing_ref": no_thr})
            if te.get("bore"):
                req.append({"what": f"отверстие под трубку Ø{te['bore']}", "spec": _bore_spec(te["bore"]), "kind": "plug",
                            "smooth": True})
        req.append({"what": f"резьба гайки под фитинг {te.get('nut_thread') or '—'}", "spec": un, "kind": "plug",
                    "for_nut": slot == "tube", "missing_ref": no_thr})
    elif k in ("pipe", "metric") and slot in ("male", "female"):
        kind = "ring" if slot == "male" else "plug"
        if k == "metric":
            req.append({"what": f"резьба {end['label']}", "spec": f"M:{end['key'][1:]}", "kind": kind})
        else:
            letter = {"N": "K", "NO": "K", "R": "R"}.get(end["type"])
            if letter:
                req.append({"what": f"коническая резьба {end['label']} (резьбовой ПР-НЕ + гладкий)",
                            "spec": f"{letter}:{end['size']}", "kind": kind, "taper": True})
            elif end["type"].startswith("G"):
                req.append({"what": f"резьба {end['label']}", "spec": f"G:{end['size']}", "kind": kind})
            else:
                req.append({"what": f"резьба {end['label']}", "spec": None, "kind": kind,
                            "missing_ref": "для этого типа резьбы правило калибров не задано"})
    return req


def _un_spec(thread: str | None):
    if not thread:
        return None
    m = re.search(rf"{_UN_SIZE}\s*-\s*(\d+)", thread)
    return f"UN:{m.group(1)}-{m.group(2)}" if m else None


def _gauge_ident(g: dict) -> str:
    """Чем назвать калибр в отчёте: заводской №, иначе код из примечания (ZJV-RG-10), иначе ID записи."""
    if g.get("serial"):
        return f"№{g['serial']}"
    if m := re.search(r"код (\S+?);", g.get("notes") or ""):
        return m.group(1)
    return f"ID {g.get('id')}" if g.get("id") else "без номера"


def gauge_valid(g: dict, today: date) -> tuple[str, str]:
    """(уровень, текст): ok | warn | bad."""
    if (g.get("status") or "в работе") != "в работе":
        return "bad", g.get("status")
    nd = g.get("next_date")
    if not nd:
        return "warn", "нет даты поверки"
    try:
        d = date.fromisoformat(str(nd)[:10])
    except ValueError:
        return "warn", f"дата «{nd}» не распознана"
    if d < today:
        return "bad", f"поверка просрочена ({d:%d.%m.%Y})"
    if (d - today).days <= 30:
        return "warn", f"поверка до {d:%d.%m.%Y} — скоро"
    return "ok", f"годен до {d:%d.%m.%Y}"


def match_gauges(req: dict, gauges: list[dict], today: date) -> dict:
    """Ищет калибры под требование; для ПР-НЕ нужны оба, «Р-Г» закрывает коническую резьбу целиком."""
    out = {"found": [], "level": "bad", "text": "не найден"}
    if not req.get("spec"):
        out["text"] = req.get("missing_ref", "правило не задано")
        return out
    cand = [g for g in gauges if g.get("spec") == req["spec"] and g.get("kind") == req["kind"]]
    if req["spec"].startswith(("K:", "R:")):  # «1/2" Р-Г» без указания типа — кандидат с оговоркой
        cand += [g for g in gauges if g.get("spec") == "?:" + req["spec"][2:] and g.get("kind") == req["kind"]]
    if not cand:
        return out
    graded = []
    for g in cand:
        lvl, txt = gauge_valid(g, today)
        graded.append({**g, "level": lvl, "valid_text": txt})
    out["found"] = graded
    rank = {"ok": 0, "warn": 1, "bad": 2}
    def best(side):
        # калибр-комплект «ПР-НЕ» закрывает и ПР, и НЕ
        xs = [g for g in graded if g.get("side") == side or (side in ("ПР", "НЕ") and g.get("side") == "ПР-НЕ")]
        return min((rank[g["level"]] for g in xs), default=None)
    if req.get("taper") and best("Р-Г") is not None:
        lvl = best("Р-Г")
        exact = any(g["spec"] == req["spec"] for g in graded if g.get("side") == "Р-Г")
        out["level"] = ["ok", "warn", "bad"][lvl] if exact else "warn"
        out["text"] = "Р-Г (резьбовой + гладкий)" + ("" if exact else " — тип резьбы в наименовании не указан")
        return out
    pr, ne = best("ПР"), best("НЕ")
    if pr is None or ne is None:
        out["level"] = "bad"
        out["text"] = "есть только " + ("ПР" if pr is not None else "НЕ") + ", нужна пара ПР-НЕ"
        return out
    lvl = max(pr, ne)
    out["level"] = ["ok", "warn", "bad"][lvl]
    out["text"] = {"ok": "ПР и НЕ годны", "warn": "ПР-НЕ есть, но годность не подтверждена",
                   "bad": "ПР-НЕ есть, но не годны"}[out["level"]]
    return out


# ═══════════════════════════════════════════════════════════════════════════
#  МЕТАЛЛ И СМЕНЫ
# ═══════════════════════════════════════════════════════════════════════════

CUT_ALLOWANCE_MM = 3.0          # припуск на штуку (отрезка + подрезка), «вчистую»
DEFAULT_SETUP_H = 4.0           # наладка на маршрут (все установы), если статистики нет
PERSON_HOURS_PER_DAY = 8.0      # ФОТ → ставка в час: ФОТ / (8 ч × рабочие дни)
PRICE_KINDS = ["металл 316L, ₽/кг", "гайка", "кольцо переднее", "кольцо заднее", "поковка"]
DENSITY_316L = 7.98             # г/см³
SHIFT_HOURS_PER_DAY = 2 * 8 - 0.5   # 2 смены по 8 ч минус пересменка 30 мин в сутки


def hex_kg_per_m(s_mm: float) -> float:
    """Масса 1 м шестигранника под ключ S: площадь = √3/2·S²."""
    return (3 ** 0.5 / 2) * s_mm ** 2 * DENSITY_316L / 1000


def metal_need(n_pcs: int, body_len_mm: float, hex_mm: float | None) -> dict:
    per = body_len_mm + CUT_ALLOWANCE_MM
    m = n_pcs * per / 1000
    return {"per_piece_mm": per, "meters": m, "kg": m * hex_kg_per_m(hex_mm) if hex_mm else None}


# ═══════════════════════════════════════════════════════════════════════════
#  БАЗА: таблицы модуля
# ═══════════════════════════════════════════════════════════════════════════

def init_tables(c):
    """Создаёт таблицы модуля (вызывается из app.init_db). Только CREATE IF NOT EXISTS."""
    c.executescript("""
        CREATE TABLE IF NOT EXISTS tech_articles (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            article_key  TEXT UNIQUE NOT NULL,       -- ключ без исполнения, D≡FN (FNMC14M-8R)
            designation  TEXT DEFAULT '',            -- НЛПА8.535.110
            blank_kind   TEXT DEFAULT '',            -- hex | forging | round
            hex_mm       REAL,
            forging      TEXT DEFAULT '',            -- обозначение поковки
            body_len_mm  REAL,                       -- длина корпуса (для расхода металла)
            mass_g       REAL,
            source       TEXT DEFAULT '',            -- чертёж / каталог / вручную
            verified     INTEGER DEFAULT 0,
            notes        TEXT DEFAULT '',
            updated_at   TEXT
        );
        CREATE TABLE IF NOT EXISTS tech_tube_ends (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            tube         TEXT UNIQUE NOT NULL,       -- 12M, 8 …
            body_thread  TEXT DEFAULT '',            -- 3/4-20UNEF-2A
            nut_thread   TEXT DEFAULT '',            -- 3/4-20UNEF-2B
            bore         TEXT DEFAULT '',            -- 12,15 +0,04
            source       TEXT DEFAULT '',
            notes        TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS tech_gauges (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            serial          TEXT DEFAULT '',
            inv_no          TEXT DEFAULT '',
            maker           TEXT DEFAULT '',
            calib_date      TEXT,
            interval_months INTEGER,
            next_date       TEXT,
            status          TEXT DEFAULT 'в работе',   -- в работе | на поверке | списан
            location        TEXT DEFAULT '',
            notes           TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS tech_metal (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            grade      TEXT DEFAULT '316L',
            standard   TEXT DEFAULT '',
            profile    TEXT DEFAULT 'HEX',
            size_mm    REAL,
            length_m   REAL DEFAULT 0,
            heat       TEXT DEFAULT '',
            cert       TEXT DEFAULT '',
            location   TEXT DEFAULT '',
            notes      TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS tech_forgings (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            designation  TEXT UNIQUE NOT NULL,       -- НЛПА8.031.009
            kind         TEXT DEFAULT '',            -- L | T | X
            dn           TEXT DEFAULT '',            -- Ду (трубка), мм
            dims         TEXT DEFAULT '',            -- 35×35×16
            qty          INTEGER,
            fixture      TEXT DEFAULT '',            -- есть | нет | '' (не указано)
            fixture_note TEXT DEFAULT '',
            notes        TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS tech_routes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            family      TEXT NOT NULL,              -- straight (прямые) | forging (из поковки) | other (любые детали)
            machines    TEXT NOT NULL,              -- станки через запятую в порядке установов
            parallel    INTEGER DEFAULT 0,          -- 1 = один оператор ведёт станки маршрута одновременно
            is_default  INTEGER DEFAULT 0,
            notes       TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS tech_prices (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            kind        TEXT NOT NULL,              -- металл 316L, ₽/кг | гайка | кольцо переднее | кольцо заднее | поковка
            size        TEXT DEFAULT '',            -- трубка (12M, 8) или обозначение поковки; для металла пусто
            price       REAL,
            valid_from  TEXT,
            notes       TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS tech_machine_rates (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            machine     TEXT NOT NULL,
            amort_month REAL,
            valid_from  TEXT,
            notes       TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS tech_payroll (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            role        TEXT NOT NULL,              -- наладчик | оператор
            fot_month   REAL,                       -- полный ФОТ в месяц на человека
            valid_from  TEXT,
            notes       TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS tech_settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    c.execute("INSERT OR IGNORE INTO tech_settings (key, value) VALUES ('work_days', '21')")
    if c.execute("SELECT COUNT(*) FROM tech_routes").fetchone()[0] == 0:
        c.executemany("INSERT INTO tech_routes (name, family, machines, parallel, is_default, notes) VALUES (?,?,?,?,?,?)", [
            ("235 + 2100 (1-й и 2-й установ)", "straight", "Lathe 235, Lathe 2100", 1, 1,
             "1-й установ на 235, 2-й на 2100; один оператор ведёт связку"),
            ("2105 (оба установа)", "straight", "Lathe 2105", 0, 0, "оба установа за один"),
            ("2100 (из поковки)", "forging", "Lathe 2100", 0, 1, "угольники, тройники, крестовины — только 2100"),
            ("АПТ (оба установа)", "straight", "АПТ", 0, 0, "оба установа за один (FNP, FNU, FNMC, FNCP …)"),
            ("MILL (фрезерные операции)", "other", "MILL", 0, 0, "корпуса кранов и другие детали; все операции на MILL"),
        ])


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    import calendar
    day = min(d.day, calendar.monthrange(d.year + y, m + 1)[1])
    return date(d.year + y, m + 1, day)


# ═══════════════════════════════════════════════════════════════════════════
#  ИСТОРИЯ ВЫПУСКА
# ═══════════════════════════════════════════════════════════════════════════

_DESIGNATION = re.compile(r"НЛПА\s*(\d+)\.(\d+)\.(\d+)", re.I)


def part_key(name: str, parsed: dict | None = None) -> str | None:
    """Ключ детали для истории и наладки: артикул фитинга, иначе чертёжное обозначение (НЛПА8.034.040 —
    одинаково для «НЛПА8.034.040 / Корпус» и «НЛПА8.034.040_Корпус_VN8B…»), иначе название без регистра и пробелов."""
    p = parsed if parsed is not None else parse_article(name or "")
    if p.get("key"):
        return p["key"]
    m = _DESIGNATION.search(name or "")
    if m:
        return "НЛПА{}.{}.{}".format(*m.groups())
    s = re.sub(r"\s+", " ", (name or "").strip()).upper()
    return s or None


def load_history(q) -> pd.DataFrame:
    """Все записи выпуска станков с распознанным ключом артикула."""
    rows = q("""
        SELECT p.id, p.date, p.batch_number, COALESCE(NULLIF(b.batch_name,''), p.batch, '') AS name,
               b.total_qty, m.name AS machine, COALESCE(m.is_work_center,0) AS wc,
               COALESCE(p.produced_qty,0) AS qty, COALESCE(p.setup_time,0) AS setup_h,
               COALESCE(p.actual_duration_minutes,0) AS fact_min, p.stage_name,
               COALESCE(p.is_final_release,0) AS fin
        FROM production p
        LEFT JOIN machines m ON m.id = p.machine_id
        LEFT JOIN batches  b ON b.batch_number = p.batch_number
        WHERE COALESCE(p.record_type,'production') = 'production'
    """)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    parsed = {n: parse_article(n) for n in df["name"].unique()}
    df["key"] = df["name"].map(lambda n: parsed[n].get("key"))
    pkeys = {n: part_key(n, parsed[n]) for n in parsed}
    df["pkey"] = df["name"].map(pkeys)               # фитинг — артикул, прочие детали — обозначение / название
    df.attrs["parsed"] = parsed
    return df


def machine_stats(h: pd.DataFrame) -> pd.DataFrame:
    """По станкам (без РЦ): медианы наладки на партию и минут на штуку по партиям."""
    lathe = h[h["wc"] == 0]
    if lathe.empty:
        return pd.DataFrame()
    per_batch = lathe.groupby(["machine", "batch_number"]).agg(
        setup_h=("setup_h", "sum"), fact_min=("fact_min", "sum"), qty_max=("qty", "max"),
        total_qty=("total_qty", "max"), records=("id", "count"), stages=("stage_name", lambda s: ", ".join(sorted({str(x) for x in s if x}))))
    # штук в партии: плановое количество партии, иначе максимум по записям станка
    pcs = per_batch["total_qty"].where(per_batch["total_qty"] > 0, per_batch["qty_max"]).fillna(0)
    per_batch["min_per_pc"] = (per_batch["fact_min"] / pcs).where(pcs > 0)
    per_batch["setup_outlier"] = per_batch["setup_h"] > 24
    clean = per_batch[~per_batch["setup_outlier"]]
    stats = clean.groupby("machine").agg(
        batches=("records", "count"), setup_med_h=("setup_h", "median"),
        min_per_pc_med=("min_per_pc", "median"), stages=("stages", lambda s: "; ".join(sorted(set(s)))))
    stats["outliers"] = per_batch.groupby("machine")["setup_outlier"].sum().reindex(stats.index).fillna(0).astype(int)
    return stats.reset_index()


# ── Маршруты ───────────────────────────────────────────────────────────────

def batch_routes(h: pd.DataFrame) -> pd.Series:
    """Партия → набор станков (без РЦ), на которых её делали."""
    lathe = h[h["wc"] == 0] if not h.empty else h
    if lathe.empty:
        return pd.Series(dtype=object)
    return lathe.groupby("batch_number")["machine"].agg(lambda s: frozenset(s))


def route_stats(h: pd.DataFrame, machines) -> pd.DataFrame:
    """Статистика по станкам только для партий, сделанных ровно по этому маршруту."""
    br = batch_routes(h)
    want = frozenset(machines)
    batches = [b for b, ms in br.items() if ms == want]
    return machine_stats(h[h["batch_number"].isin(batches)]) if batches else pd.DataFrame()


def parse_machines(text: str) -> tuple:
    return tuple(m.strip() for m in (text or "").split(",") if m.strip())


def machine_hours_per_day(q, day: date | None = None) -> float:
    """Часы работы станка в рабочие сутки по режиму смен («📅 План станков» → «Режим смен»)."""
    try:
        rows = q("SELECT * FROM plan_shifts")
    except Exception:                                # регистра ещё нет
        return SHIFT_HOURS_PER_DAY
    return workcal.hours_per_day(day or date.today(), rows) or SHIFT_HOURS_PER_DAY


def route_estimate(norms: list[dict], n_pcs: int, parallel: bool, hours_per_day: float = SHIFT_HOURS_PER_DAY) -> dict:
    """norms: [{machine, setup_h, min_pc}] → часы по станкам и календарь.
    parallel: один оператор ведёт станки одновременно (связка) — календарь по самому загруженному."""
    rows, complete = [], True
    for r in norms:
        mpc = r.get("min_pc")
        ok = mpc is not None and not pd.isna(mpc) and mpc >= 0
        complete &= ok
        run_h = n_pcs * mpc / 60 if ok else None
        setup = float(r.get("setup_h") or 0)
        rows.append({"machine": r["machine"], "setup_h": setup, "min_pc": mpc if ok else None,
                     "run_h": run_h, "total_h": setup + run_h if ok else None})
    totals = [r["total_h"] for r in rows if r["total_h"] is not None]
    machine_hours = sum(totals) if totals else 0.0
    wall = (max(totals) if parallel else sum(totals)) if totals else 0.0
    return {"rows": rows, "complete": complete, "machine_hours": machine_hours, "wall_hours": wall,
            "days": wall / hours_per_day, "hours_per_day": hours_per_day, "parallel": parallel}


# ── Себестоимость ──────────────────────────────────────────────────────────

def effective(rows: list[dict], key_field: str, today: date) -> dict:
    """Действующие на дату записи регистра: {ключ: строка с наибольшей valid_from ≤ today}."""
    best = {}
    for r in rows:
        vf = str(r.get("valid_from") or "0000-00-00")[:10]
        if vf > today.isoformat():
            continue
        k = (r.get(key_field) or "").strip()
        if k not in best or vf >= best[k][0]:
            best[k] = (vf, r)
    return {k: v[1] for k, v in best.items()}


def cost_breakdown(p: dict, art: dict | None, n_pcs: int, est: dict, prices: dict, mrates: dict,
                   payroll: dict, work_days: float, with_components: bool | None = None,
                   machine_hours_day: float = SHIFT_HOURS_PER_DAY) -> dict:
    """Себестоимость партии. prices: {(kind, size): row}; mrates: {machine: row}; payroll: {role: row}.
    with_components: комплектовать гайками и кольцами (по умолчанию — исполнение «в сборе», A).
    Статья без данных → amount None (в итог не входит, показывается как «не задано»)."""
    if with_components is None:
        with_components = bool(p.get("assembled"))
    lines = []
    def add(item, how, amount, missing=None):
        lines.append({"item": item, "how": how, "amount": amount, "missing": missing})
    price = lambda kind, size="": (prices.get((kind, size)) or {}).get("price")

    # 1. Материал корпуса
    if p.get("forging"):
        fg = (art or {}).get("forging")
        pr = price("поковка", fg) if fg else None
        if pr is None:
            add("Поковка", f"{n_pcs:,} шт × цена поковки {fg or '(поковка не выбрана)'}", None,
                "нет цены поковки" if fg else "поковка не выбрана")
        else:
            add("Поковка", f"{n_pcs:,} шт × {pr:,.2f} ₽ ({fg})", n_pcs * pr)
    else:
        hex_mm, ln = (art or {}).get("hex_mm"), (art or {}).get("body_len_mm")
        pr = price("металл 316L, ₽/кг")
        if not hex_mm or not ln:
            add("Металл", "нет HEX или длины корпуса в справочнике артикулов", None, "нет данных о заготовке")
        else:
            need = metal_need(n_pcs, ln, hex_mm)
            if pr is None:
                add("Металл", f"{need['kg']:,.2f} кг × цена за кг", None, "нет цены металла")
            else:
                add("Металл", f"{n_pcs:,} × ({ln:g}+{CUT_ALLOWANCE_MM:g}) мм = {need['meters']:,.2f} м · "
                              f"HEX {hex_mm:g} = {need['kg']:,.2f} кг × {pr:,.2f} ₽/кг", need["kg"] * pr)

    # 2. Гайки и кольца (комплектация): на каждый обжимной торец 1 гайка + переднее и заднее кольцо
    if with_components:
        tubes = [e["code"] for e in p.get("ends", []) if e.get("slot") == "tube" and e.get("code")]
        for kind in ("гайка", "кольцо переднее", "кольцо заднее"):
            missing = sorted({t for t in tubes if price(kind, t) is None})
            if not tubes:
                continue
            if missing:
                add(kind.capitalize(), f"{len(tubes)} × {n_pcs:,} шт", None, f"нет цены для трубки {', '.join(missing)}")
            else:
                s = sum(price(kind, t) for t in tubes)
                add(kind.capitalize(), f"{len(tubes)} шт на фитинг × {n_pcs:,} = {len(tubes) * n_pcs:,} шт · "
                                       + ", ".join(f"{t}: {price(kind, t):,.2f} ₽" for t in sorted(set(tubes))), s * n_pcs)

    # 3–5. Работа и амортизация (по выбранному маршруту)
    rate = lambda role: ((payroll.get(role) or {}).get("fot_month") or 0) / (PERSON_HOURS_PER_DAY * work_days) \
        if (payroll.get(role) or {}).get("fot_month") else None
    setup_h = sum(r["setup_h"] for r in est["rows"])
    r_set = rate("наладчик")
    add("Наладка (наладчик)", f"{setup_h:,.2f} ч × " + (f"{r_set:,.2f} ₽/ч" if r_set else "ставка"),
        setup_h * r_set if r_set else None, None if r_set else "нет ФОТ наладчика")
    runs = [r["run_h"] for r in est["rows"] if r["run_h"] is not None]
    if not est["complete"]:
        add("Работа оператора", "нет нормы мин/шт для части станков", None, "нет нормы времени")
    else:
        op_h = (max(runs) if est["parallel"] else sum(runs)) if runs else 0
        r_op = rate("оператор")
        how = (f"связка: по самому загруженному станку {op_h:,.2f} ч" if est["parallel"] and len(runs) > 1
               else f"{op_h:,.2f} ч") + (f" × {r_op:,.2f} ₽/ч" if r_op else "")
        add("Работа оператора", how, op_h * r_op if r_op else None, None if r_op else "нет ФОТ оператора")
    for r in est["rows"]:
        a = (mrates.get(r["machine"]) or {}).get("amort_month")
        hr = a / (machine_hours_day * work_days) if a else None
        if r["total_h"] is None:
            add(f"Амортизация {r['machine']}", "нет нормы времени", None, "нет нормы времени")
        elif hr is None:
            add(f"Амортизация {r['machine']}", f"{r['total_h']:,.2f} ч × ставка", None, "нет амортизации станка")
        else:
            add(f"Амортизация {r['machine']}", f"{r['total_h']:,.2f} ч × {hr:,.2f} ₽/ч", r["total_h"] * hr)
    total = sum(l["amount"] for l in lines if l["amount"] is not None)
    return {"lines": lines, "total": total, "per_piece": total / n_pcs if n_pcs else None,
            "complete": all(l["amount"] is not None for l in lines)}


# ═══════════════════════════════════════════════════════════════════════════
#  СТРАНИЦА
# ═══════════════════════════════════════════════════════════════════════════

_ICON = {"ok": "✅", "warn": "⚠️", "bad": "❌"}


def page_tech(q, tx, audit):
    if st.session_state.get("role") != "admin":
        st.error("⛔ Технологический модуль доступен только администратору.")
        st.stop()
    st.title("🛠 Технология")
    t_an, t_c, t_r, t_g, t_m, t_f, t_a, t_e = st.tabs(
        ["🔍 Анализ артикула", "💰 Цены и ставки", "🛣 Маршруты", "📏 Калибры", "🔩 Металл", "🧱 Поковки",
         "📚 Артикулы", "🔧 Торцы"])
    with t_an:
        _tab_analysis(q, tx, audit)
    with t_c:
        _tab_rates(q, tx, audit)
    with t_r:
        _journal(q, tx, audit, "tech_routes", "Маршруты",
                 ["name", "family", "machines", "parallel", "is_default", "notes"],
                 {"name": "Название", "family": "Вид", "machines": "Станки (через запятую, по установам)",
                  "parallel": "Связка (1 оператор)", "is_default": "По умолчанию", "notes": "Примечание"},
                 help_text="Вид: straight — прямые фитинги из HEX, forging — из поковки (угольники, тройники, крестовины), "
                           "other — для любых деталей (предлагается всегда, например MILL для корпусов кранов). "
                           "Названия станков — как в справочнике станков. «Связка» — один оператор ведёт станки "
                           "одновременно: срок и оплата оператора считаются по самому загруженному станку.",
                 selects={"family": ["straight", "forging", "other"]}, bools=["parallel", "is_default"])
    with t_g:
        _journal(q, tx, audit, "tech_gauges", "Калибры",
                 ["name", "serial", "inv_no", "maker", "calib_date", "interval_months", "next_date",
                  "status", "location", "notes"],
                 {"name": "Наименование", "serial": "Заводской №", "inv_no": "Инв. №", "maker": "Изготовитель",
                  "calib_date": "Дата поверки", "interval_months": "Интервал, мес", "next_date": "Следующая поверка",
                  "status": "Состояние", "location": "Место", "notes": "Примечание"},
                 help_text="Следующая поверка считается сама из даты поверки и интервала при сохранении. "
                           "Калибр без даты поверки в анализе считается неподтверждённым.",
                 selects={"status": ["в работе", "на поверке", "списан"]},
                 dates=["calib_date", "next_date"], ints=["interval_months"])
    with t_m:
        _journal(q, tx, audit, "tech_metal", "Металл на складе",
                 ["grade", "standard", "profile", "size_mm", "length_m", "heat", "cert", "location", "notes"],
                 {"grade": "Марка", "standard": "Стандарт", "profile": "Профиль", "size_mm": "Размер, мм",
                  "length_m": "Остаток, м", "heat": "Плавка", "cert": "Сертификат", "location": "Место",
                  "notes": "Примечание"},
                 help_text="Размер — под ключ для HEX. Остаток в метрах; расход в анализе считается вчистую: "
                           f"длина корпуса + {CUT_ALLOWANCE_MM:g} мм на штуку.",
                 selects={"profile": ["HEX", "круг"]}, nums=["size_mm", "length_m"])
    with t_f:
        _journal(q, tx, audit, "tech_forgings", "Поковки",
                 ["designation", "kind", "dn", "dims", "qty", "fixture", "fixture_note", "notes"],
                 {"designation": "Обозначение", "kind": "Тип", "dn": "Ду (трубка)", "dims": "Габариты",
                  "qty": "На складе, шт", "fixture": "Оснастка", "fixture_note": "Оснастка — описание",
                  "notes": "Примечание"},
                 help_text="Тип: L — угловой корпус, T — тройник, X — крестовина.",
                 selects={"kind": ["L", "T", "X"], "fixture": ["", "есть", "нет"]}, ints=["qty"])
    with t_a:
        _journal(q, tx, audit, "tech_articles", "Справочник артикулов (заготовки)",
                 ["article_key", "designation", "blank_kind", "hex_mm", "forging", "body_len_mm", "mass_g",
                  "source", "verified", "notes"],
                 {"article_key": "Артикул (без исполнения)", "designation": "Чертёж", "blank_kind": "Заготовка",
                  "hex_mm": "HEX, мм", "forging": "Поковка", "body_len_mm": "Длина корпуса, мм",
                  "mass_g": "Масса, г", "source": "Источник", "verified": "Проверено", "notes": "Примечание"},
                 help_text="Ключ — артикул без исполнения, D-артикулы приводятся к FN (DMC12M-8N-S → FNMC12M-8N).",
                 selects={"blank_kind": ["", "hex", "forging", "round"]}, nums=["hex_mm", "body_len_mm", "mass_g"],
                 bools=["verified"])
    with t_e:
        _journal(q, tx, audit, "tech_tube_ends", "Справочник обжимных торцов",
                 ["tube", "body_thread", "nut_thread", "bore", "source", "notes"],
                 {"tube": "Трубка", "body_thread": "Резьба корпуса (2A)", "nut_thread": "Резьба гайки (2B)",
                  "bore": "Отверстие под трубку", "source": "Источник", "notes": "Примечание"},
                 help_text="По этим данным система понимает, какие калибры нужны для обжимного торца. "
                           "FN и D (DK-LOK) совпадают.")


def _tab_analysis(q, tx, audit):
    c1, c2 = st.columns([3, 1])
    raw = c1.text_input("Артикул", key="tech_art", placeholder="например, FNMC12M-8N-SA")
    n_pcs = c2.number_input("Количество, шт", min_value=1, step=50, value=500, key="tech_qty")
    if not raw.strip():
        st.info("Введите артикул. Система разберёт его на торцы, покажет историю выпуска, "
                "оценит партию и проверит калибры, металл и поковку.")
        return
    p = parse_article(raw)
    today = date.today()

    # ── 1. Распознавание ───────────────────────────────────────────────
    st.markdown("### 1. Что распознано")
    if not p.get("article"):
        st.error(p["error"])
        return
    rows = [("Артикул", p["article"]), ("Семейство", f"{p['prefix']} — {p['family']}"),
            ("Тип", f"{p['type_code']} — {p.get('type_name') or 'не найден в справочнике'}")]
    if p.get("material"):
        rows.append(("Исполнение", f"{p['material']} — {p.get('material_label') or '?'}"
                     + (", в сборе (A)" if p.get("assembled") else "")))
    if p.get("length"):
        rows.append(("Длина", p["length"]["label"]))
    if p.get("forging"):
        rows.append(("Заготовка", {"L": "поковка углового корпуса", "T": "поковка тройника",
                                    "X": "поковка крестовины"}[p["forging"]]))
    for i, e in enumerate(p.get("ends", []), 1):
        rows.append((f"Торец {i}", end_label(e) + ("" if e["how"] == "указан" else f" ({e['how']})")))
    st.dataframe(pd.DataFrame(rows, columns=["Параметр", "Значение"]), use_container_width=True, hide_index=True)
    for note in p["notes"]:
        st.caption("ℹ️ " + note)
    if p.get("unknown"):
        st.warning("Не распознано: " + ", ".join(p["unknown"]))
    if p.get("error"):
        st.error(p["error"])
        return
    key = p["key"]

    hist = load_history(q)
    parsed_all = hist.attrs.get("parsed", {}) if not hist.empty else {}
    h = hist[hist["key"] == key] if not hist.empty else hist

    # ── 2. История ─────────────────────────────────────────────────────
    st.markdown("### 2. История выпуска")
    if h.empty:
        st.info(f"Артикул {key} ранее не выпускался.")
    else:
        b = (h.groupby("batch_number").agg(
            name=("name", "first"), first=("date", "min"), last=("date", "max"),
            plan=("total_qty", "max"), machines=("machine", lambda s: ", ".join(sorted(set(s)))))
             .reset_index().sort_values("first"))
        b["дней"] = (pd.to_datetime(b["last"]) - pd.to_datetime(b["first"])).dt.days + 1
        br = batch_routes(h)
        b["route"] = b["batch_number"].map(lambda x: " + ".join(sorted(br.get(x, frozenset()))) or "—")
        st.dataframe(b.rename(columns={"batch_number": "Партия", "name": "Название", "first": "Начало",
                                       "last": "Конец", "plan": "План, шт", "route": "Маршрут (станки)",
                                       "machines": "Станки / РЦ"}),
                     use_container_width=True, hide_index=True)

    # ── 3. Оценка партии по маршруту ───────────────────────────────────
    st.markdown(f"### 3. Оценка партии {n_pcs:,} шт по маршруту")
    est = _route_section(q, p, key, h, hist, parsed_all, n_pcs)

    # ── 4. Торцы ───────────────────────────────────────────────────────
    st.markdown("### 4. Торцы: делали ли такие раньше")
    seen = {}
    for name, v in parsed_all.items():
        for e in v.get("ends") or []:
            k = end_key(e)
            if k:
                seen.setdefault(k, set()).add(v.get("key") or name)
    trows = []
    for i, e in enumerate(p["ends"], 1):
        k = end_key(e)
        arts = sorted(seen.get(k, set()) - {key})
        done = bool(seen.get(k))
        trows.append({"Торец": f"{i}. {end_label(e)}",
                      "Производился": "✅ да" if done else "❌ не производился",
                      "Где встречался": ", ".join(arts[:6]) + (f" и ещё {len(arts) - 6}" if len(arts) > 6 else "")})
    st.dataframe(pd.DataFrame(trows), use_container_width=True, hide_index=True)

    # ── 5. Калибры ─────────────────────────────────────────────────────
    st.markdown("### 5. Калибры")
    tube_ends = {r["tube"]: r for r in q("SELECT * FROM tech_tube_ends")}
    gauges = []
    for g in q("SELECT * FROM tech_gauges"):
        gauges.append({**g, **parse_gauge_name(g["name"])})
    grows, seen_req = [], set()
    for i, e in enumerate(p["ends"], 1):
        for r in gauge_requirements(e, tube_ends):
            sig = (r.get("spec"), r.get("kind"), r["what"])
            if sig in seen_req:
                continue
            seen_req.add(sig)
            mres = match_gauges(r, gauges, today)
            found = "; ".join(f"{g['side'] or '?'} {_gauge_ident(g)}"
                              + (f" (инв. {g['inv_no']})" if g.get("inv_no") else "") + f" — {g['valid_text']}"
                              for g in mres["found"])
            grows.append({"Торец": i, "Итог": f"{_ICON[mres['level']]} {mres['text']}",
                          "Что проверяем": r["what"] + (" — для гайки (исполнение A)" if r.get("for_nut") else ""),
                          "Калибр": {"ring": "кольцо", "plug": "пробка"}.get(r.get("kind"), "—")
                                    + (" гладкий" if r.get("smooth") else ""),
                          "Найдено": found or "—"})
    if grows:
        st.dataframe(pd.DataFrame(grows), use_container_width=True, hide_index=True)
    else:
        st.info("Для торцов этого артикула калибры не требуются или правила не заданы.")

    # ── 6. Металл ──────────────────────────────────────────────────────
    st.markdown("### 6. Металл")
    art = q("SELECT * FROM tech_articles WHERE article_key=?", (key,), fetch="one")
    if p.get("forging"):
        st.caption("Корпус делается из поковки — см. раздел 7.")
    elif not art or not art.get("body_len_mm"):
        st.warning(f"Нет данных о заготовке для {key} (HEX и длина корпуса). "
                   "Добавьте их на вкладке «📚 Артикулы».")
    else:
        need = metal_need(n_pcs, art["body_len_mm"], art.get("hex_mm"))
        stock = q("SELECT COALESCE(SUM(length_m),0) AS m FROM tech_metal "
                  "WHERE profile='HEX' AND size_mm=? AND UPPER(grade) LIKE '%316L%'", (art.get("hex_mm"),), fetch="one")
        m1, m2, m3 = st.columns(3)
        m1.metric(f"HEX {art.get('hex_mm'):g} 316L" if art.get("hex_mm") else "HEX не указан",
                  f"{need['per_piece_mm']:g} мм/шт", help=f"длина корпуса {art['body_len_mm']:g} + {CUT_ALLOWANCE_MM:g} мм")
        m2.metric("Нужно на партию", f"{need['meters']:,.2f} м",
                  f"{need['kg']:,.1f} кг" if need["kg"] else None, delta_color="off")
        have = stock["m"] if stock else 0
        m3.metric("На складе", f"{have:,.2f} м",
                  "хватает" if have >= need["meters"] else f"не хватает {need['meters'] - have:,.2f} м",
                  delta_color="normal" if have >= need["meters"] else "inverse")
        st.caption(f"Источник данных о заготовке: {art.get('source') or '—'}"
                   + ("" if art.get("verified") else " · ⚠️ не отмечено как проверенное"))

    # ── 7. Поковка ─────────────────────────────────────────────────────
    if p.get("forging"):
        st.markdown("### 7. Поковка и оснастка")
        tube = next((e.get("code") for e in p["ends"] if e.get("kind") == "tube"), None)
        dn = tube[:-1] if tube and tube.endswith("M") else None
        chosen = (art or {}).get("forging")
        if chosen:
            f = q("SELECT * FROM tech_forgings WHERE designation=?", (chosen,), fetch="one")
            if not f:
                st.warning(f"Поковка {chosen} указана для артикула, но её нет в журнале поковок.")
            else:
                st.success(f"Поковка **{f['designation']}** ({f['dims']}): на складе "
                           f"{'—' if f['qty'] is None else f['qty']} шт · оснастка: {f['fixture'] or 'не указано'}"
                           + (f" ({f['fixture_note']})" if f.get("fixture_note") else ""))
                if f["qty"] is not None and f["qty"] < n_pcs:
                    st.error(f"Поковок не хватает: нужно {n_pcs:,}, на складе {f['qty']:,}.")
        cands = q("SELECT * FROM tech_forgings WHERE kind=?" + (" AND dn=?" if dn else "") + " ORDER BY designation",
                  (p["forging"], dn) if dn else (p["forging"],))
        if not chosen:
            st.info("Поковка для артикула не выбрана. Подходящие по типу"
                    + (f" и Ду {dn}" if dn else "") + " — выберите вручную:")
        if cands:
            opts = [c["designation"] for c in cands]
            lab = {c["designation"]: f"{c['designation']} — {c['dims']} · склад: "
                   f"{'—' if c['qty'] is None else c['qty']} · оснастка: {c['fixture'] or '?'}" for c in cands}
            fc1, fc2 = st.columns([4, 1])
            pick = fc1.selectbox("Поковка", opts, format_func=lab.get, key=f"tech_forg_{key}")
            fc2.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            if fc2.button("Закрепить", key=f"tech_forg_save_{key}", use_container_width=True):
                _save_article_field(tx, audit, key, {"forging": pick, "blank_kind": "forging"},
                                    source="вручную (выбор поковки)")
                st.rerun()
        elif not chosen:
            st.warning("Подходящих поковок в журнале нет.")

    # ── 8. Себестоимость ───────────────────────────────────────────────
    st.markdown(f"### 8. Себестоимость партии {n_pcs:,} шт")
    if est is None:
        st.info("Себестоимость считается по маршруту из раздела 3 — выберите маршрут.")
        return
    prices = {(r["kind"], (r.get("size") or "").strip()): r
              for r in effective([dict(x, _k=f"{x['kind']}|{(x.get('size') or '').strip()}")
                                  for x in q("SELECT * FROM tech_prices")], "_k", today).values()}
    mrates = effective(q("SELECT * FROM tech_machine_rates"), "machine", today)
    payroll = effective(q("SELECT * FROM tech_payroll"), "role", today)
    wd = q("SELECT value FROM tech_settings WHERE key='work_days'", fetch="one")
    work_days = float(wd["value"]) if wd and wd["value"] else 21.0
    n_tube = sum(1 for e in p.get("ends", []) if e.get("slot") == "tube")
    with_comp = st.checkbox(
        "Комплектовать гайками и кольцами" + (f" ({n_tube} обжимн. соединени{'е' if n_tube == 1 else 'я'})" if n_tube else ""),
        value=bool(p.get("assembled")), key=f"cost_comp_{key}", disabled=not n_tube,
        help="По умолчанию включено для исполнения «в сборе» (A, например -SA). На каждое обжимное соединение — "
             "1 гайка, 1 переднее и 1 заднее кольцо по ценам из регистра.")
    mh_day = machine_hours_per_day(q, today)
    cb = cost_breakdown(p, art, n_pcs, est, prices, mrates, payroll, work_days, with_components=with_comp,
                        machine_hours_day=mh_day)
    df_c = pd.DataFrame([{"Статья": l["item"], "Сумма, ₽": l["amount"], "Нет данных": l["missing"] or "",
                          "Как посчитано": l["how"]} for l in cb["lines"]])
    st.dataframe(df_c, use_container_width=True, hide_index=True,
                 column_config={"Сумма, ₽": st.column_config.NumberColumn(format="%.2f")})
    c1, c2 = st.columns(2)
    c1.metric("Итого на партию" + ("" if cb["complete"] else " (неполная)"), f"{cb['total']:,.2f} ₽")
    c2.metric("На 1 шт" + ("" if cb["complete"] else " (неполная)"), f"{cb['per_piece']:,.2f} ₽")
    if not cb["complete"]:
        st.warning("Себестоимость неполная: часть статей без данных (столбец «Нет данных»). "
                   "Цены, амортизацию и ФОТ можно внести на вкладке «💰 Цены и ставки».")
    st.caption(f"Ставки: амортизация = сумма в месяц ÷ ({mh_day:g} ч по режиму смен × {work_days:g} раб. дн.); "
               f"ФОТ = ФОТ в месяц ÷ ({PERSON_HOURS_PER_DAY:g} ч × {work_days:g} раб. дн.). "
               "Цены и ставки — действующие на сегодня (по дате начала действия).")


def _tab_rates(q, tx, audit):
    """Регистры для себестоимости: цены, амортизация станков, ФОТ, рабочие дни."""
    st.caption("Все значения — с датой начала действия: в расчёте берётся последняя запись с датой не позже сегодняшней. "
               "Старые записи не удаляйте — по ним видно, как менялись цены.")
    wd = q("SELECT value FROM tech_settings WHERE key='work_days'", fetch="one")
    cur = float(wd["value"]) if wd and wd["value"] else 21.0
    c1, c2 = st.columns([1, 3])
    new = c1.number_input("Рабочих дней в месяце", min_value=1.0, max_value=31.0, step=0.5, value=cur, key="tech_wd")
    c2.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    if c2.button("Сохранить рабочие дни", key="tech_wd_save") and new != cur:
        with tx() as conn:
            conn.execute("INSERT OR REPLACE INTO tech_settings (key, value) VALUES ('work_days', ?)", (f"{new:g}",))
            audit(conn, "update", "tech_settings", None, {"work_days": cur}, {"work_days": new})
        st.rerun()
    st.caption(f"Ставка амортизации = сумма в месяц ÷ ({machine_hours_per_day(q):g} ч в сутки по режиму смен × рабочие дни); "
               f"ставка ФОТ = ФОТ в месяц ÷ ({PERSON_HOURS_PER_DAY:g} ч × рабочие дни). "
               "Режим смен задаётся в «📅 План станков» → «Режим смен».")
    _forging_price_form(q, tx, audit)
    _journal(q, tx, audit, "tech_prices", "Цены: металл, гайки, кольца, поковки",
             ["kind", "size", "price", "valid_from", "notes"],
             {"kind": "Что", "size": "Размер / обозначение", "price": "Цена, ₽", "valid_from": "Действует с",
              "notes": "Примечание"},
             help_text="Металл — одна цена за кг на все HEX (размер не заполнять). Гайки и кольца — по размеру трубки "
                       "(12M, 8 …): на каждый обжимной торец исполнения SA — 1 гайка, 1 переднее и 1 заднее кольцо. "
                       "Поковка — по обозначению (НЛПА8.031.009).",
             selects={"kind": PRICE_KINDS}, nums=["price"], dates=["valid_from"])
    machines = [r["name"] for r in q("SELECT name FROM machines WHERE COALESCE(is_work_center,0)=0 ORDER BY name")]
    _journal(q, tx, audit, "tech_machine_rates", "Амортизация станков",
             ["machine", "amort_month", "valid_from", "notes"],
             {"machine": "Станок", "amort_month": "Амортизация в месяц, ₽", "valid_from": "Действует с",
              "notes": "Примечание"},
             selects={"machine": machines}, nums=["amort_month"], dates=["valid_from"])
    _journal(q, tx, audit, "tech_payroll", "ФОТ",
             ["role", "fot_month", "valid_from", "notes"],
             {"role": "Роль", "fot_month": "ФОТ в месяц, ₽", "valid_from": "Действует с", "notes": "Примечание"},
             help_text="Полный ФОТ на одного человека в месяц. Наладка оплачивается наладчику, выпуск — оператору.",
             selects={"role": ["наладчик", "оператор"]}, nums=["fot_month"], dates=["valid_from"])


_FORG_KIND = {"L": "угловой корпус", "T": "тройник", "X": "крестовина"}


def _forging_price_form(q, tx, audit):
    """Цена поковки: выбор из журнала поковок + цена + дата → запись в регистр цен (kind «поковка»)."""
    st.markdown("#### Цена поковки")
    forgings = q("SELECT designation, kind, dn, dims FROM tech_forgings ORDER BY designation")
    if not forgings:
        st.info("Журнал поковок пуст — сначала добавьте поковки на вкладке «🧱 Поковки».")
        return
    today = date.today()
    cur = effective([r for r in q("SELECT * FROM tech_prices WHERE kind='поковка'")], "size", today)
    lab = {f["designation"]: f"{f['designation']} — {_FORG_KIND.get(f['kind'], f['kind'])} Ду{f['dn']} {f['dims']}"
                             + (f" · сейчас {cur[f['designation']]['price']:,.2f} ₽" if f["designation"] in cur else "")
           for f in forgings}
    with st.form("forging_price_form", clear_on_submit=True):
        c1, c2, c3 = st.columns([4, 2, 2])
        pick = c1.selectbox("Поковка", list(lab), format_func=lab.get)
        price = c2.number_input("Цена, ₽ за шт", min_value=0.0, step=10.0, format="%.2f")
        vf = c3.date_input("Действует с", value=today, format="DD.MM.YYYY")
        if st.form_submit_button("➕ Добавить цену", type="primary"):
            if price <= 0:
                st.error("Укажите цену больше нуля.")
            else:
                row = {"kind": "поковка", "size": pick, "price": float(price), "valid_from": vf.isoformat(),
                       "notes": "внесено через форму «Цена поковки»"}
                with tx() as conn:
                    rid = conn.execute("INSERT INTO tech_prices (kind, size, price, valid_from, notes) VALUES (?,?,?,?,?)",
                                       tuple(row.values())).lastrowid
                    audit(conn, "insert", "tech_prices", rid, None, row)
                st.session_state["forg_price_flash"] = f"✅ Цена {price:,.2f} ₽ для {pick} с {vf:%d.%m.%Y} добавлена."
                st.rerun()
    msg = st.session_state.pop("forg_price_flash", None)
    if msg:
        st.success(msg)
    table = [{"Поковка": f["designation"], "Тип": _FORG_KIND.get(f["kind"], f["kind"]), "Ду": f["dn"], "Габариты": f["dims"],
              "Цена сейчас, ₽": cur[f["designation"]]["price"] if f["designation"] in cur else None,
              "Действует с": str(cur[f["designation"]]["valid_from"])[:10] if f["designation"] in cur else ""}
             for f in forgings]
    st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True,
                 column_config={"Цена сейчас, ₽": st.column_config.NumberColumn(format="%.2f")})
    st.caption("Новая цена добавляется строкой с датой начала действия — прежние цены остаются в регистре ниже "
               "(их можно поправить или удалить там же).")


def _route_section(q, p, key, h, hist, parsed_all, n_pcs):
    """Выбор маршрута, нормы по станкам (история / похожий / вручную) и расчёт времени. Возвращает est или None."""
    family = "forging" if p.get("forging") else "straight"
    defined = [r for r in q("SELECT * FROM tech_routes ORDER BY is_default DESC, id") if r["family"] in (family, "other")]
    counts = pd.Series(batch_routes(h).values).value_counts().to_dict() if not h.empty else {}
    options = []
    for r in defined:
        ms = parse_machines(r["machines"])
        n = counts.get(frozenset(ms), 0)
        options.append({"label": r["name"] + (f" · в истории {n} парт." if n else ""), "machines": ms,
                        "parallel": bool(r["parallel"]), "n": n})
    for ms_set, n in counts.items():
        if not any(frozenset(o["machines"]) == ms_set for o in options):
            options.append({"label": f"по истории: {' + '.join(sorted(ms_set))} · {n} парт.",
                            "machines": tuple(sorted(ms_set)), "parallel": False, "n": n})
    if not options:
        st.info("Для этого вида фитинга не задано ни одного маршрута (вкладка «🛣 Маршруты»).")
        return None
    # по умолчанию: самый частый в истории из заданных маршрутов; если по ним не делали — маршрут «по умолчанию»
    with_hist = [i for i in range(len(defined)) if options[i]["n"] > 0]
    best = max(with_hist, key=lambda i: options[i]["n"]) if with_hist else 0
    labels = [o["label"] for o in options]
    sel = options[labels.index(st.selectbox("Маршрут", labels, index=best, key=f"route_{key}"))]
    ms = sel["machines"]
    rows = [{"Станок": r["machine"], "Наладка, ч": r["setup_h"], "Мин/шт": r["min_pc"], "Откуда": r["src"]}
            for r in route_norms(p, key, h, hist, parsed_all, ms)]
    st.caption("Нормы можно поправить прямо в таблице — расчёт и себестоимость пересчитаются.")
    edited = st.data_editor(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                            disabled=["Станок", "Откуда"], key=f"norms_{key}_{'+'.join(ms)}",
                            column_config={"Наладка, ч": st.column_config.NumberColumn(min_value=0.0, step=0.25, format="%.2f"),
                                           "Мин/шт": st.column_config.NumberColumn(min_value=0.0, step=0.1, format="%.2f")})
    if any(str(r["Откуда"]).startswith("оценка по торцам") or r["Мин/шт"] is None for r in rows):
        ee = end_estimate(p, hist, parsed_all, ms)
        if ee and ee.get("ends"):
            with st.expander("📐 Оценка по торцам — как получена", expanded=True):
                st.dataframe(pd.DataFrame([{"Торец": e["end"], "Что взято": e["how"], "Партий": e["n"],
                                            "Мин/шт на торец (медиана)": e["per_end"], "Где встречался": e["examples"]}
                                           for e in ee["ends"]]), use_container_width=True, hide_index=True)
                if ee.get("total"):
                    st.caption(f"По {ee['n_route']} партиям этого маршрута: время на штуку ÷ число торцов фитинга = "
                               "«время на торец»; сумма по торцам ≈ " + f"{ee['total']:g} мин/шт"
                               + ("" if len(ms) == 1 else " — делится между станками в обычной доле маршрута: "
                                  + ", ".join(f"{m} {v:.0%}" for m, v in ee["share"].items()))
                               + ". Это оценка: размер корпуса и сложность не учитываются — поправьте норму, если нужно.")
                else:
                    st.caption("Часть торцов на этом маршруте не делали — оценить нельзя, введите мин/шт вручную.")
    est = route_estimate([{"machine": r["Станок"], "setup_h": r["Наладка, ч"], "min_pc": r["Мин/шт"]}
                          for r in edited.to_dict("records")], n_pcs, sel["parallel"], machine_hours_per_day(q))
    out = pd.DataFrame([{"Станок": r["machine"], "Наладка, ч": r["setup_h"], "Выпуск, ч": r["run_h"],
                         "Всего, ч": r["total_h"]} for r in est["rows"]])
    st.dataframe(out, use_container_width=True, hide_index=True,
                 column_config={c: st.column_config.NumberColumn(format="%.1f") for c in ["Наладка, ч", "Выпуск, ч", "Всего, ч"]})
    c1, c2 = st.columns(2)
    c1.metric("Итого станко-часов", f"{est['machine_hours']:,.1f} ч")
    c2.metric("Календарно", f"≈ {est['days']:.1f} сут",
              help=("связка: станки работают одновременно, срок — по самому загруженному" if est["parallel"] and len(ms) > 1
                    else "станки маршрута последовательно") + f"; {est['hours_per_day']:g} ч в сутки по режиму смен")
    if not est["complete"]:
        st.warning("Для части станков нет нормы мин/шт — введите её в таблице выше.")
    st.caption("Медианы по партиям, сделанным ровно по этому маршруту; партии с наладкой > 24 ч исключены как ошибки ввода.")
    return est


def _end_size_mm(e: dict) -> float | None:
    """Размер торца в мм для поиска ближайшего: трубка 10M → 10, дюймовые коды (8 = 1/2") → n/16", M14×1,5 → 14."""
    if e.get("kind") == "metric":
        m = re.match(r"M(\d+)", e.get("key") or "")
        return float(m.group(1)) if m else None
    m = re.match(r"(\d+)(M?)", e.get("code") or "")
    if not m:
        return None
    return float(m.group(1)) if m.group(2) else int(m.group(1)) * 25.4 / 16


def _end_family(e: dict) -> str:
    """Вид торца для «ближайшего размера»: место (обжим / наружная / внутренняя резьба) + тип резьбы."""
    if e.get("kind") == "pipe":
        return f"{e['slot']}:pipe:{e.get('type')}"
    return f"{e['slot']}:{e.get('kind')}"


def end_estimate(p: dict, hist: pd.DataFrame, parsed_all: dict, machines) -> dict | None:
    """Оценка мин/шт по торцам, когда истории артикула и похожих нет.
    По партиям, сделанным ровно по этому маршруту: время на штуку (сумма станков маршрута) ÷ число торцов
    = «время на торец». Для каждого торца артикула — медиана по партиям с таким же торцом (или ближайшего
    размера того же вида); сумма по торцам — оценка на штуку. Между станками маршрута (235 + 2100) делится
    в обычной для маршрута доле; для 2105 / АПТ (оба установа на одном станке) — целиком на станок.
    → {'rows': [{machine, min_pc}], 'ends': [...], 'n_route': N, 'total': мин/шт} или None."""
    if hist is None or hist.empty or not p.get("ends"):
        return None
    want = frozenset(machines)
    br = batch_routes(hist)
    bns = [b for b, ms in br.items() if ms == want]
    lathe = hist[(hist["wc"] == 0) & hist["batch_number"].isin(bns)]
    if lathe.empty:
        return None
    per = lathe.groupby(["batch_number", "machine"]).agg(fact_min=("fact_min", "sum"), qty_max=("qty", "max"),
                                                       total_qty=("total_qty", "max"), name=("name", "first")).reset_index()
    pcs = per["total_qty"].where(per["total_qty"] > 0, per["qty_max"])
    per["min_pc"] = (per["fact_min"] / pcs).where(pcs > 0)
    per = per[per["min_pc"] > 0]
    tab = per.pivot_table(index="batch_number", columns="machine", values="min_pc", aggfunc="sum")
    tab = tab[[m for m in machines if m in tab.columns]].dropna() if all(m in tab.columns for m in machines) else tab.iloc[0:0]
    if tab.empty:
        return None
    names = per.groupby("batch_number")["name"].first()
    total = tab.sum(axis=1)
    own = p.get("key")
    # сравниваем только с деталями того же класса: из поковки с поковками, прямые с прямыми,
    # гайки — только с гайками того же типа (FNN ≠ монтажная FNUBN)
    def cls(v):
        nut = all(e.get("slot") == "nut" for e in (v.get("ends") or [{}]))
        return bool(v.get("forging")), nut, v.get("type_code") if nut else None
    my_cls = cls(p)
    samples = []                                     # (торец, вид, размер мм, время на торец, партия, артикул)
    for bn, t in total.items():
        v = parsed_all.get(names[bn]) or {}
        ends = [e for e in (v.get("ends") or []) if e.get("kind")]
        if not ends or v.get("key") == own or cls(v) != my_cls:
            continue
        per_end = float(t) / len(ends)
        seen_k = set()
        for e in ends:                               # одна партия — один голос на торец (FNU-12M: оба торца 12M)
            if end_key(e) in seen_k:
                continue
            seen_k.add(end_key(e))
            samples.append((end_key(e), _end_family(e), _end_size_mm(e), per_end, bn, v.get("key")))
    if not samples:
        return None
    rows_e, est = [], 0.0
    for e in p["ends"]:
        if not e.get("kind"):
            rows_e.append({"end": e.get("label"), "how": "размер не определён", "n": 0, "per_end": None, "examples": ""})
            continue
        k = end_key(e)
        hit = [s for s in samples if s[0] == k]
        how = "такой же торец"
        if not hit:                                  # ближайший размер того же вида (не дальше ±60 %)
            sz, fam = _end_size_mm(e), _end_family(e)
            cand = [s for s in samples if s[1] == fam and s[2] and sz and abs(s[2] - sz) <= 0.6 * sz]
            if cand:
                best = min(abs(s[2] - sz) for s in cand)
                hit = [s for s in cand if abs(s[2] - sz) - best < 1e-6]    # равноудалённые размеры — оба
                how = f"ближайший размер ({hit[0][0].split(':', 1)[1]})"
        if not hit:
            rows_e.append({"end": end_label(e), "how": "такой торец на маршруте не делали", "n": 0, "per_end": None,
                           "examples": ""})
            continue
        med = float(pd.Series([s[3] for s in hit]).median())
        est += med
        arts = sorted({s[5] for s in hit if s[5]})
        rows_e.append({"end": end_label(e), "how": how, "n": len({s[4] for s in hit}), "per_end": round(med, 2),
                       "examples": ", ".join(arts[:4]) + (f" и ещё {len(arts) - 4}" if len(arts) > 4 else "")})
    if any(r["per_end"] is None for r in rows_e):
        return {"rows": [], "ends": rows_e, "n_route": len(tab), "total": None}
    share = (tab.div(total, axis=0)).median()
    share = share / share.sum()
    return {"rows": [{"machine": m, "min_pc": round(est * float(share[m]), 2)} for m in machines],
            "ends": rows_e, "n_route": len(tab), "total": round(est, 2),
            "share": {m: round(float(share[m]), 2) for m in machines}}


def route_norms(p, key, h, hist, parsed_all, ms) -> list[dict]:
    """Нормы по станкам маршрута: история артикула → похожий артикул → нет (ввести вручную).
    h — история этого артикула, hist — вся история. Возвращает [{machine, setup_h, min_pc, src}]."""
    # похожие артикулы: тот же тип и размер первого торца, то же семейство (обжимной / резьбовой)
    compression = p["prefix"] in ("FN", "D")
    same_names = [n for n, v in parsed_all.items()
                  if v.get("key") and v.get("key") != key and v.get("type_code") == p["type_code"]
                  and (v.get("prefix") in ("FN", "D")) == compression and v.get("ends") and p.get("ends")
                  and v["ends"][0].get("code") == p["ends"][0].get("code")]
    exact = route_stats(h, ms) if not h.empty else pd.DataFrame()
    similar_h = hist[hist["name"].isin(same_names)] if not hist.empty else hist
    sim = route_stats(similar_h, ms) if not similar_h.empty else pd.DataFrame()
    sim_keys = sorted({parsed_all[n]["key"] for n in same_names
                       if n in set(similar_h["name"])}) if not similar_h.empty else []
    rows = []
    est = None
    for m in ms:
        src, setup, mpc = None, None, None
        for df_, label in ((exact, "история"), (sim, "похожий: " + ", ".join(sim_keys[:3]))):
            if not df_.empty and m in set(df_["machine"]):
                r = df_[df_["machine"] == m].iloc[0]
                if not pd.isna(r["min_per_pc_med"]):
                    src, mpc = f"{label} ({int(r['batches'])} парт.)", float(r["min_per_pc_med"])
                    setup = None if pd.isna(r["setup_med_h"]) else float(r["setup_med_h"])
                    break
        if mpc is None:                              # ни истории, ни похожего — оценка по торцам
            if est is None:
                est = end_estimate(p, hist, parsed_all, ms) or {}
            hit = next((r for r in est.get("rows", []) if r["machine"] == m), None)
            if hit and hit["min_pc"]:
                mpc = hit["min_pc"]
                src = "оценка по торцам: " + "; ".join(
                    f"{e['end'].split(' — ')[-1]} — {e['n']} парт." + ("" if e["how"] == "такой же торец" else f", {e['how']}")
                    for e in est["ends"])
        if setup is None:
            setup = DEFAULT_SETUP_H / len(ms)
            src = (src + "; наладка по умолчанию" if src else f"нет статистики — введите мин/шт; наладка {DEFAULT_SETUP_H:g} ч на маршрут")
        rows.append({"machine": m, "setup_h": round(setup, 2), "min_pc": None if mpc is None else round(mpc, 2),
                     "src": src})
    return rows


def _save_article_field(tx, audit, key, fields: dict, source: str):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with tx() as conn:
        old = conn.execute("SELECT * FROM tech_articles WHERE article_key=?", (key,)).fetchone()
        if old:
            sets = ", ".join(f"{k}=?" for k in fields)
            conn.execute(f"UPDATE tech_articles SET {sets}, updated_at=? WHERE article_key=?",
                         (*fields.values(), now, key))
            audit(conn, "update", "tech_articles", old["id"], dict(old), fields)
        else:
            cols = ["article_key", *fields, "source", "updated_at"]
            cur = conn.execute(f"INSERT INTO tech_articles ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                               (key, *fields.values(), source, now))
            audit(conn, "insert", "tech_articles", cur.lastrowid, None, {"article_key": key, **fields})


# ── Универсальный редактор журнала ─────────────────────────────────────────

_COLS_OK = re.compile(r"^[a-z_]+$")


def _journal(q, tx, audit, table, title, cols, labels, help_text="", selects=None, dates=(), ints=(), nums=(),
             bools=()):
    assert _COLS_OK.match(table) and all(_COLS_OK.match(c) for c in cols)
    selects = selects or {}
    st.markdown(f"#### {title}")
    if help_text:
        st.caption(help_text)
    rows = q(f"SELECT id, {', '.join(cols)} FROM {table} ORDER BY id")
    df = pd.DataFrame(rows, columns=["id", *cols])
    for c in dates:
        df[c] = pd.to_datetime(df[c], errors="coerce").dt.date
    for c in bools:
        df[c] = df[c].fillna(0).astype(bool)
    cfg = {"id": st.column_config.NumberColumn("ID", disabled=True, width="small")}
    for c in cols:
        lab = labels.get(c, c)
        if c in selects:
            cfg[c] = st.column_config.SelectboxColumn(lab, options=selects[c])
        elif c in dates:
            cfg[c] = st.column_config.DateColumn(lab, format="DD.MM.YYYY")
        elif c in ints:
            cfg[c] = st.column_config.NumberColumn(lab, step=1, format="%d")
        elif c in nums:
            cfg[c] = st.column_config.NumberColumn(lab)
        elif c in bools:
            cfg[c] = st.column_config.CheckboxColumn(lab)
        else:
            cfg[c] = st.column_config.TextColumn(lab)
    flt = st.text_input("Поиск", key=f"flt_{table}", placeholder="фильтр по любому полю")
    view = df
    if flt.strip():
        mask = df.astype(str).apply(lambda col: col.str.contains(flt.strip(), case=False, regex=False)).any(axis=1)
        view = df[mask]
    st.caption(f"Записей: {len(df)}" + (f", показано: {len(view)}" if flt.strip() else "")
               + ". Добавляйте строки внизу таблицы; удаление строки — выделить и Delete. "
                 "Изменения применяются кнопкой «Сохранить» и попадают в журнал изменений.")
    edited = st.data_editor(view, column_config=cfg, num_rows="dynamic", hide_index=True,
                            use_container_width=True, key=f"ed_{table}")
    if st.button("💾 Сохранить", key=f"save_{table}", type="primary"):
        changes = _save_journal(tx, audit, table, cols, view, edited, dates, bools, ints)
        st.session_state[f"flash_{table}"] = (f"✅ Сохранено: добавлено {changes[0]}, изменено {changes[1]}, "
                                              f"удалено {changes[2]}.")
        st.rerun()
    msg = st.session_state.pop(f"flash_{table}", None)
    if msg:
        st.success(msg)


def _norm(v, is_date=False, is_bool=False, is_int=False):
    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NaT:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if is_bool:
        return 1 if bool(v) else 0
    if is_date:
        return v.isoformat()[:10] if hasattr(v, "isoformat") else str(v)[:10]
    if is_int:
        return int(v)
    if hasattr(v, "item"):
        v = v.item()
    return v.strip() if isinstance(v, str) else v


def _save_journal(tx, audit, table, cols, before, after, dates, bools, ints):
    norm = lambda row: {c: _norm(row.get(c), c in dates, c in bools, c in ints) for c in cols}
    old_by_id = {int(r["id"]): norm(r) for r in before.to_dict("records")}
    added = changed = removed = 0
    seen_ids = set()
    with tx() as conn:
        for r in after.to_dict("records"):
            vals = norm(r)
            if table == "tech_gauges" and vals.get("calib_date") and vals.get("interval_months"):
                vals["next_date"] = add_months(date.fromisoformat(vals["calib_date"]), int(vals["interval_months"])).isoformat()
            rid = r.get("id")
            if rid is None or (isinstance(rid, float) and pd.isna(rid)):
                if not any(v not in (None, "", 0) for v in vals.values()):
                    continue
                cur = conn.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                   [vals[c] for c in cols])
                audit(conn, "insert", table, cur.lastrowid, None, vals)
                added += 1
                continue
            rid = int(rid)
            seen_ids.add(rid)
            if vals != old_by_id.get(rid):
                conn.execute(f"UPDATE {table} SET {', '.join(c + '=?' for c in cols)} WHERE id=?",
                             [vals[c] for c in cols] + [rid])
                audit(conn, "update", table, rid, old_by_id.get(rid), vals)
                changed += 1
        for rid, old in old_by_id.items():
            if rid not in seen_ids:
                conn.execute(f"DELETE FROM {table} WHERE id=?", (rid,))
                audit(conn, "delete", table, rid, old)
                removed += 1
    return added, changed, removed
