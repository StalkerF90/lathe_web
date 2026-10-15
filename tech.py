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
    "C":    ("Колпак",                                  ["nut"], None),
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

def parse_gauge_name(name: str) -> dict:
    """«Резьбовой калибр-пробка 7/8-20 UNEF-2B ПР» → kind=plug, spec=UN:7/8-20, cls=2B, side=ПР."""
    n = (name or "").replace(" ", " ")
    up = n.translate(_LOOKALIKE).upper()
    g = {"kind": "ring" if "КОЛЬЦО" in n.upper() else "plug" if "ПРОБКА" in n.upper() else None,
         "side": None, "spec": None, "cls": None, "smooth": "ГЛАДК" in n.upper()}
    if re.search(r"\bР-Г\b", n) or "P-Г" in n:
        g["side"] = "Р-Г"
    elif re.search(r"\bНЕ\b", n):
        g["side"] = "НЕ"
    elif re.search(r"\bПР\b", n):
        g["side"] = "ПР"
    if m := re.search(r"(\d+(?:/\d+)?)\s*-\s*(\d+)\s*(UNEF|UNF|UNC|UN)\s*-?\s*(\d[AB])", up):
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
        if slot == "tube":
            req.append({"what": f"резьба корпуса под гайку {te.get('body_thread')}", "spec": un, "kind": "ring"})
            if te.get("bore"):
                req.append({"what": f"отверстие под трубку Ø{te['bore']}", "spec": f"BORE:{te['bore']}", "kind": "plug",
                            "smooth": True})
        req.append({"what": f"резьба гайки под фитинг {te.get('nut_thread')}", "spec": un, "kind": "plug",
                    "for_nut": slot == "tube"})
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
    m = re.search(r"(\d+(?:/\d+)?)\s*-\s*(\d+)", thread)
    return f"UN:{m.group(1)}-{m.group(2)}" if m else None


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
        xs = [g for g in graded if g.get("side") == side]
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
    """)


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    import calendar
    day = min(d.day, calendar.monthrange(d.year + y, m + 1)[1])
    return date(d.year + y, m + 1, day)


# ═══════════════════════════════════════════════════════════════════════════
#  ИСТОРИЯ ВЫПУСКА
# ═══════════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════════
#  СТРАНИЦА
# ═══════════════════════════════════════════════════════════════════════════

_ICON = {"ok": "✅", "warn": "⚠️", "bad": "❌"}


def page_tech(q, tx, audit):
    if st.session_state.get("role") != "admin":
        st.error("⛔ Технологический модуль доступен только администратору.")
        st.stop()
    st.title("🛠 Технология")
    t_an, t_g, t_m, t_f, t_a, t_e = st.tabs(
        ["🔍 Анализ артикула", "📏 Калибры", "🔩 Металл", "🧱 Поковки", "📚 Артикулы", "🔧 Торцы"])
    with t_an:
        _tab_analysis(q, tx, audit)
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
    stats = pd.DataFrame()
    if h.empty:
        st.info(f"Артикул {key} ранее не выпускался.")
    else:
        b = (h.groupby("batch_number").agg(
            name=("name", "first"), first=("date", "min"), last=("date", "max"),
            plan=("total_qty", "max"), machines=("machine", lambda s: ", ".join(sorted(set(s)))))
             .reset_index().sort_values("first"))
        b["дней"] = (pd.to_datetime(b["last"]) - pd.to_datetime(b["first"])).dt.days + 1
        st.dataframe(b.rename(columns={"batch_number": "Партия", "name": "Название", "first": "Начало",
                                       "last": "Конец", "plan": "План, шт", "machines": "Станки / РЦ"}),
                     use_container_width=True, hide_index=True)
        stats = machine_stats(h)
        if not stats.empty:
            st.dataframe(stats.rename(columns={
                "machine": "Станок", "batches": "Партий", "setup_med_h": "Наладка на партию, ч (медиана)",
                "min_per_pc_med": "Мин/шт (медиана)", "stages": "Этапы", "outliers": "Исключено (наладка > 24 ч)"}),
                use_container_width=True, hide_index=True,
                column_config={"Наладка на партию, ч (медиана)": st.column_config.NumberColumn(format="%.2f"),
                               "Мин/шт (медиана)": st.column_config.NumberColumn(format="%.2f")})

    # ── 3. Оценка партии ───────────────────────────────────────────────
    st.markdown(f"### 3. Оценка партии {n_pcs:,} шт (только станки)")
    approx = False
    if stats.empty and not hist.empty:
        compression = p["prefix"] in ("FN", "D")
        same = [k for k, v in parsed_all.items()
                if v.get("key") and v.get("key") != key and v.get("type_code") == p["type_code"]
                and (v.get("prefix") in ("FN", "D")) == compression
                and v.get("ends") and p.get("ends")
                and v["ends"][0].get("code") == p["ends"][0].get("code")]
        similar = hist[hist["name"].isin(same)]
        if not similar.empty:
            stats = machine_stats(similar)
            approx = True
            st.caption("Оценка ориентировочная — по похожим артикулам того же типа и размера: "
                       + ", ".join(sorted({parsed_all[n]['key'] for n in same})))
    if stats.empty:
        st.info("Нет данных для оценки: артикул и похожие на него (тот же тип и размер трубки) не выпускались.")
    else:
        est = stats.copy()
        est["setup_med_h"] = est["setup_med_h"].fillna(0)
        est["Часы"] = est["setup_med_h"] + n_pcs * est["min_per_pc_med"].fillna(0) / 60
        est["Смен (8 ч)"] = est["Часы"] / 8
        est["Сутки (2 смены)"] = est["Часы"] / SHIFT_HOURS_PER_DAY
        st.dataframe(est[["machine", "setup_med_h", "min_per_pc_med", "Часы", "Смен (8 ч)", "Сутки (2 смены)"]]
                     .rename(columns={"machine": "Станок", "setup_med_h": "Наладка, ч", "min_per_pc_med": "Мин/шт"}),
                     use_container_width=True, hide_index=True,
                     column_config={c: st.column_config.NumberColumn(format="%.1f")
                                    for c in ["Наладка, ч", "Мин/шт", "Часы", "Смен (8 ч)", "Сутки (2 смены)"]})
        tot = est["Часы"].sum()
        st.metric("Итого станко-часов" + (" (ориентировочно)" if approx else ""), f"{tot:,.1f} ч",
                  help=f"Если станки работают последовательно: ≈ {tot / SHIFT_HOURS_PER_DAY:.1f} сут "
                       f"при {SHIFT_HOURS_PER_DAY:g} ч в сутки (2 смены по 8 ч минус пересменка).")
        st.caption(f"Последовательно на станках ≈ **{tot / SHIFT_HOURS_PER_DAY:.1f} сут** "
                   f"({SHIFT_HOURS_PER_DAY:g} ч/сут: 2 смены по 8 ч минус 30 мин пересменки). "
                   "Медианы по прошлым партиям; партии с наладкой > 24 ч исключены как ошибки ввода.")

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
            found = "; ".join(f"{g['side'] or '?'} №{g['serial'] or '—'}"
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
