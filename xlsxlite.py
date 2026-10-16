"""
Минимальные чтение и запись .xlsx на стандартной библиотеке (openpyxl в образе нет,
пересобирать образ ради него не хотим).

read_xlsx(data) → {имя листа: [[значение, …], …]}; значения: str | float | bool | datetime | None.
Ячейки с форматом даты/времени возвращаются как datetime (учитывается система дат 1904).
write_xlsx(sheets) → bytes: листы [(имя, строки, ширины столбцов, текстовые столбцы)], первая строка — жирная.
"""
import io
import re
import zipfile
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
       "pr": "http://schemas.openxmlformats.org/package/2006/relationships"}
_BUILTIN_DATE = set(range(14, 23)) | set(range(27, 37)) | set(range(45, 48)) | set(range(50, 59))
MAX_CELLS = 200_000
MAX_UNPACKED = 50 * 1024 * 1024


def _col_index(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def _is_date_format(code: str) -> bool:
    code = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", code or "").lower()
    return bool(re.search(r"[dmyhs]", code)) and "general" not in code


def _excel_dt(v: float, date1904: bool) -> datetime:
    base = datetime(1904, 1, 1) if date1904 else datetime(1899, 12, 30)
    return base + timedelta(days=float(v))


def read_xlsx(data: bytes) -> dict:
    """Все листы книги как списки строк. Ошибка формата → ValueError с понятным текстом."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("Это не файл .xlsx (если это .xls — сохраните в Excel как «Книга Excel (.xlsx)»).")
    names = set(z.namelist())
    if sum(i.file_size for i in z.infolist()) > MAX_UNPACKED:
        raise ValueError("Файл слишком большой в распакованном виде (больше 50 МБ).")
    if "xl/workbook.xml" not in names:
        raise ValueError("В файле нет книги Excel (xl/workbook.xml).")
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    pr = wb.find("m:workbookPr", _NS)
    date1904 = pr is not None and pr.get("date1904") in ("1", "true")
    rels = {}
    if "xl/_rels/workbook.xml.rels" in names:
        for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).findall("pr:Relationship", _NS):
            t = r.get("Target")
            rels[r.get("Id")] = t.lstrip("/") if t.startswith("/") else "xl/" + t
    shared = []
    if "xl/sharedStrings.xml" in names:
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", _NS):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % _NS["m"])))
    date_styles = set()
    if "xl/styles.xml" in names:
        stl = ET.fromstring(z.read("xl/styles.xml"))
        custom = {int(n.get("numFmtId")): n.get("formatCode") for n in stl.findall("m:numFmts/m:numFmt", _NS)}
        for i, xf in enumerate(stl.findall("m:cellXfs/m:xf", _NS)):
            fid = int(xf.get("numFmtId") or 0)
            if fid in _BUILTIN_DATE or (fid in custom and _is_date_format(custom[fid])):
                date_styles.add(i)
    out, total = {}, 0
    for sh in wb.findall("m:sheets/m:sheet", _NS):
        path = rels.get(sh.get("{%s}id" % _NS["r"]))
        if not path or path not in names:
            continue
        rows = {}
        for row in ET.fromstring(z.read(path)).iter("{%s}row" % _NS["m"]):
            r_i = int(row.get("r")) - 1 if row.get("r") else len(rows)
            cells = {}
            for k, c in enumerate(row.findall("m:c", _NS)):
                total += 1
                if total > MAX_CELLS:
                    raise ValueError("Слишком большой файл (больше 200 000 ячеек).")
                ci = _col_index(c.get("r")) if c.get("r") else k
                t, s = c.get("t"), int(c.get("s") or 0)
                v = c.find("m:v", _NS)
                if t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter("{%s}t" % _NS["m"]))
                elif v is None or v.text is None:
                    val = None
                elif t == "s":
                    val = shared[int(v.text)] if int(v.text) < len(shared) else ""
                elif t in ("str", "e"):
                    val = v.text
                elif t == "b":
                    val = v.text == "1"
                else:
                    try:
                        num = float(v.text)
                    except ValueError:
                        val = v.text
                    else:
                        val = _excel_dt(num, date1904) if s in date_styles else num
                cells[ci] = val
            if cells:
                rows[r_i] = [cells.get(i) for i in range(max(cells) + 1)]
        out[sh.get("name")] = [rows.get(i, []) for i in range(max(rows) + 1)] if rows else []
    return out


def _cell(ref: str, v, style: int = 0) -> str:
    s = f' s="{style}"' if style else ""
    if v is None or v == "":
        return f'<c r="{ref}"{s}/>' if style else ""
    if isinstance(v, bool):
        return f'<c r="{ref}" t="b"{s}><v>{int(v)}</v></c>'
    if isinstance(v, (int, float)):
        return f'<c r="{ref}"{s}><v>{v}</v></c>'
    return f'<c r="{ref}" t="inlineStr"{s}><is><t xml:space="preserve">{escape(str(v))}</t></is></c>'


def _ref(ci: int, ri: int) -> str:
    col = ""
    ci += 1
    while ci:
        ci, rem = divmod(ci - 1, 26)
        col = chr(65 + rem) + col
    return f"{col}{ri + 1}"


def write_xlsx(sheets: list[tuple]) -> bytes:
    """sheets: [(имя, строки, [ширины], {текстовые столбцы, 0-based}), …]. Строка 0 — заголовок (жирный).
    Текстовые столбцы размечаются форматом «@» на 300 строк — Excel не превратит «311.10» в число 311,1."""
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
              '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
              '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
              '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
              '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
              '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
              '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
              '<xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>'
              '</styleSheet>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" '
                             'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for i in range(len(sheets)))
                   + "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   "</Relationships>")
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(s[0][:31])}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, s in enumerate(sheets))
                   + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                             f'Target="worksheets/sheet{i + 1}.xml"/>' for i in range(len(sheets)))
                   + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                   "</Relationships>")
        z.writestr("xl/styles.xml", styles)
        for i, sh in enumerate(sheets):
            name, rows, widths = sh[0], sh[1], sh[2] if len(sh) > 2 else []
            text_cols = set(sh[3]) if len(sh) > 3 else set()
            cols = "".join(f'<col min="{k + 1}" max="{k + 1}" width="{w}" customWidth="1"/>' for k, w in enumerate(widths))
            body = []
            n_rows = max(len(rows), 300 if text_cols else 0)
            for ri in range(n_rows):
                row = rows[ri] if ri < len(rows) else []
                n_cols = max(len(row), (max(text_cols) + 1) if text_cols else 0)
                cells = "".join(_cell(_ref(ci, ri), row[ci] if ci < len(row) else None,
                                      1 if ri == 0 else (2 if ci in text_cols else 0)) for ci in range(n_cols))
                if cells:
                    body.append(f'<row r="{ri + 1}">{cells}</row>')
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                       '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
                       + (f"<cols>{cols}</cols>" if cols else "")
                       + f"<sheetData>{''.join(body)}</sheetData></worksheet>")
    return buf.getvalue()
