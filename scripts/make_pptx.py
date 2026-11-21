"""Build the presentation deck slides/airq_iot_sunum.pptx (TALIMAT 12).

    python -m scripts.make_pptx                 # write the deck
    python -m scripts.make_pptx --preview DIR   # also render PNG previews (Pillow) for a visual check
    python -m scripts.make_pptx --check         # fail on unresolved numbers, missing files, overflowing text

Every number on a slide is a `{{nName}}` placeholder replaced by the macro of the same name in
paper/numbers.tex (generated from reports/), exactly as for slides/outline.md. Figures are the
PNG files in reports/figures. Speaker notes are the sections of slides/notes.md.

The slides are described once as a small list of elements (rectangles, text, pictures, tables) with
positions in inches. One function writes them with python-pptx, another draws the same layout with
Pillow so the result can be inspected without PowerPoint; both use the same text measuring, which is
also what the overflow check relies on.
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import make_slides  # noqa: E402

OUT = ROOT / "slides" / "airq_iot_sunum.pptx"
FIG = ROOT / "reports" / "figures"
SHOTS = ROOT / "slides" / "demo_screens"
W, H = 13.333, 7.5
MARGIN = 0.6

# palette: deep teal-navy ground, amber (haze) accent, the figures' own colour-blind-safe hues
INK, INK2 = "0F2A36", "1B4452"
TEXT, MUTED = "1E2B32", "5E6E76"
BG, CARD, LINE = "F3F6F7", "FFFFFF", "D6DEE2"
AMBER, AMBER_BG, AMBER_DK = "E69F00", "FFF4DC", "8A5A00"
TEAL, TEAL_DK, BLUE, RED, PURPLE, SKY = "009E73", "00704F", "0072B2", "D55E00", "CC79A7", "56B4E9"
ON_DARK_MUTED = "A9C3CC"
FONT, MONO = "Calibri", "Consolas"
WIN_FONTS = Path("C:/Windows/Fonts")
LINE_SPACING = 1.22

_VALUES: dict[str, str] | None = None


def num(text: str) -> str:
    """Replace {{nName}} placeholders with the paper's numbers; an unknown name is an error."""
    global _VALUES
    if _VALUES is None:
        _VALUES = make_slides.macros()

    def sub(m: re.Match) -> str:
        if m.group(1) not in _VALUES:  # type: ignore[operator]
            raise KeyError(f"unknown number placeholder {{{{{m.group(1)}}}}}")
        return _VALUES[m.group(1)]  # type: ignore[index]

    return re.sub(r"\{\{(\w+)\}\}", sub, text)


# ---------------------------------------------------------------- text model and measuring


@dataclass
class P:
    """One paragraph. `**bold**` and `code` markup inside the text."""

    text: str
    size: float = 16
    color: str = TEXT
    bold: bool = False
    italic: bool = False
    bullet: bool = False
    align: str = "l"
    after: float = 6  # points
    font: str = FONT


def runs(text: str) -> list[tuple[str, bool, bool]]:
    out = []
    for part in re.split(r"(\*\*.+?\*\*|`.+?`)", text):
        if not part:
            continue
        if part.startswith("**"):
            out.append((part[2:-2], True, False))
        elif part.startswith("`"):
            out.append((part[1:-1], False, True))
        else:
            out.append((part, False, False))
    return out


def font_file(bold: bool, italic: bool, mono: bool) -> str:
    if mono:
        return str(WIN_FONTS / ("consolab.ttf" if bold else "consola.ttf"))
    name = {
        (False, False): "calibri",
        (True, False): "calibrib",
        (False, True): "calibrii",
        (True, True): "calibriz",
    }
    return str(WIN_FONTS / f"{name[(bold, italic)]}.ttf")


_FONT_CACHE: dict[tuple, ImageFont.FreeTypeFont] = {}


def pil_font(px: float, bold: bool, italic: bool, mono: bool) -> ImageFont.FreeTypeFont:
    key = (round(px, 2), bold, italic, mono)
    if key not in _FONT_CACHE:
        try:
            _FONT_CACHE[key] = ImageFont.truetype(font_file(bold, italic, mono), px)
        except OSError:
            _FONT_CACHE[key] = ImageFont.truetype("DejaVuSans.ttf", px)
    return _FONT_CACHE[key]


BULLET_INDENT = 0.24  # inches


def wrap(p: P, width_in: float) -> list[list[tuple[str, bool, bool]]]:
    """Greedy word wrap with real glyph widths. Returns lines of (word, bold, mono) pieces."""
    avail = (width_in - (BULLET_INDENT if p.bullet else 0)) * 72  # points
    scale = 10  # measure at 10x for precision
    lines: list[list[tuple[str, bool, bool]]] = [[]]
    used = 0.0
    for text, bold, mono in runs(num(p.text)):
        bold = bold or p.bold
        f = pil_font(p.size * scale, bold, p.italic, mono)
        for tok in re.findall(r"[ 	]+|[^ 	]+", text):
            wlen = f.getlength(tok) / scale
            if tok.strip(" 	") == "":
                if lines[-1]:
                    lines[-1].append((tok, bold, mono))
                    used += wlen
                continue
            if used + wlen > avail and lines[-1]:
                while lines[-1] and lines[-1][-1][0].strip(" 	") == "":
                    lines[-1].pop()
                lines.append([])
                used = 0.0
            lines[-1].append((tok, bold, mono))
            used += wlen
    return lines


def text_height(paras: list[P], width_in: float) -> float:
    h = 0.0
    for i, p in enumerate(paras):
        n = len(wrap(p, width_in))
        h += n * p.size * LINE_SPACING / 72
        if i < len(paras) - 1:
            h += p.after / 72
    return h


# ---------------------------------------------------------------- slide elements


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float
    fill: str | None = CARD
    line: str | None = None
    radius: float = 0.0
    oval: bool = False


@dataclass
class Text:
    x: float
    y: float
    w: float
    h: float
    paras: list[P]
    anchor: str = "t"  # t | m | b
    name: str = ""


@dataclass
class Pic:
    path: Path
    x: float
    y: float
    w: float
    h: float
    alt: str = ""


@dataclass
class Table:
    x: float
    y: float
    col_w: list[float]
    rows: list[list[str]]  # first row is the header
    size: float = 14
    row_h: list[float] = field(default_factory=list)


@dataclass
class Slide:
    key: str  # id used for notes lookup and messages
    dark: bool = False
    els: list = field(default_factory=list)
    notes: str = ""
    problems: list[str] = field(default_factory=list)

    # --- primitives
    def rect(self, *a, **k):
        self.els.append(Rect(*a, **k))

    def text(self, x, y, w, h, paras, anchor="t", name=""):
        if isinstance(paras, P):
            paras = [paras]
        need = text_height(paras, w)
        if need > h + 0.02:
            self.problems.append(
                f"{self.key}: text needs {need:.2f} in but the box is {h:.2f} in: {num(paras[0].text)[:50]!r}"
            )
        if x < 0 or y < 0 or x + w > W + 0.001 or y + h > H + 0.001:
            self.problems.append(
                f"{self.key}: text box outside the slide: {num(paras[0].text)[:40]!r}"
            )
        self.els.append(Text(x, y, w, h, paras, anchor, name))

    def pic(self, path: Path, x, y, w, h, alt="") -> tuple[float, float, float, float]:
        """Place the picture inside the box (x, y, w, h), keeping its aspect ratio, centred."""
        if not path.exists():
            self.problems.append(f"{self.key}: missing picture {path}")
            return x, y, w, h
        iw, ih = Image.open(path).size
        s = min(w / iw, h / ih)
        pw, ph = iw * s, ih * s
        px, py = x + (w - pw) / 2, y + (h - ph) / 2
        self.els.append(Pic(path, px, py, pw, ph, alt))
        return px, py, pw, ph

    def table(self, x, y, col_w, rows, size=14):
        t = Table(x, y, col_w, rows, size)
        for r in rows:
            cells = [[P(c, size=size, after=0)] for c in r]
            t.row_h.append(
                max(text_height(c, cw - 0.24) for c, cw in zip(cells, col_w, strict=True)) + 0.2
            )
        if y + sum(t.row_h) > 6.95:
            self.problems.append(
                f"{self.key}: table ends at {y + sum(t.row_h):.2f} in (limit 6.95)"
            )
        self.els.append(t)
        return sum(t.row_h)


# ---------------------------------------------------------------- reusable pieces


def frame(key: str, title: str, tag: str | None = None, dark: bool = False) -> Slide:
    s = Slide(key, dark=dark)
    color = "FFFFFF" if dark else INK
    if tag:
        s.rect(
            MARGIN,
            0.38,
            0.35 + 0.095 * len(tag),
            0.3,
            fill=AMBER_BG if not dark else INK2,
            radius=0.15,
        )
        s.text(
            MARGIN,
            0.38,
            0.35 + 0.095 * len(tag),
            0.3,
            P(tag, 12, AMBER_DK if not dark else AMBER, True, align="c", after=0),
            "m",
        )
        top = 0.78
    else:
        top = 0.5
    s.text(MARGIN, top, W - 2 * MARGIN, 0.95, P(title, 26, color, True, after=0), "t", name="title")
    return s


def footer(s: Slide, n: int, total: int) -> None:
    s.text(
        MARGIN,
        7.08,
        6,
        0.25,
        P(
            "airq-iot · IoT tabanlı hava kalitesi izleme",
            11,
            ON_DARK_MUTED if s.dark else MUTED,
            after=0,
        ),
    )
    s.text(
        W - MARGIN - 1.5,
        7.08,
        1.5,
        0.25,
        P(f"{n} / {total}", 11, ON_DARK_MUTED if s.dark else MUTED, align="r", after=0),
    )


def card(s: Slide, x, y, w, h, fill=CARD, line=LINE) -> None:
    s.rect(x, y, w, h, fill=fill, line=line, radius=0.12)


def why_box(s: Slide, x, y, w, h, body: str, size: float = 14) -> None:
    """The 'Neden?' box of TALIMAT 12.1: one or two sentences, a number when there is one."""
    card(s, x, y, w, h, fill=AMBER_BG, line="F2D9A0")
    s.text(x + 0.2, y + 0.14, w - 0.4, 0.28, P("NEDEN?", 12, AMBER_DK, True, after=0))
    s.text(x + 0.2, y + 0.44, w - 0.4, h - 0.56, P(body, size, TEXT, after=0))


def stat(
    s: Slide,
    x,
    y,
    w,
    h,
    value: str,
    label: str,
    color: str = BLUE,
    vsize: float = 34,
    dark: bool = False,
    lsize: float = 13,
) -> None:
    card(s, x, y, w, h, fill=INK2 if dark else CARD, line=INK2 if dark else LINE)
    s.text(
        x + 0.12,
        y + 0.12,
        w - 0.24,
        vsize * 1.25 / 72 + 0.02,
        P(value, vsize, color, True, align="l", after=0),
        "t",
    )
    top = y + 0.12 + vsize * 1.25 / 72 + 0.04
    s.text(
        x + 0.12,
        top,
        w - 0.24,
        y + h - top - 0.08,
        P(label, lsize, ON_DARK_MUTED if dark else MUTED, after=0),
        "t",
    )


def chip(
    s: Slide,
    x,
    y,
    label: str,
    fill: str,
    color: str = "FFFFFF",
    w: float | None = None,
    h: float = 0.32,
    size=12,
) -> float:
    w = w or (0.3 + 0.1 * len(label))
    s.rect(x, y, w, h, fill=fill, radius=h / 2)
    s.text(x, y, w, h, P(label, size, color, True, align="c", after=0), "m")
    return w


def figure(s: Slide, path: Path, x, y, w, h, alt: str, caption: str | None = None) -> None:
    card(s, x, y, w, h)
    ch = 0.3 if caption else 0
    s.pic(path, x + 0.12, y + 0.12, w - 0.24, h - 0.24 - ch, alt)
    if caption:
        s.text(x + 0.2, y + h - 0.36, w - 0.4, 0.26, P(caption, 11, MUTED, italic=True, after=0))


# ---------------------------------------------------------------- the deck


def build() -> list[Slide]:
    sl: list[Slide] = []

    # 1 ----------------------------------------------------------- title
    s = Slide("1", dark=True)
    s.text(
        0.8,
        0.8,
        8,
        0.35,
        P("Nesnelerin İnterneti · İstanbul Medeniyet Üniversitesi", 15, AMBER, True, after=0),
    )
    s.text(
        0.8,
        1.55,
        7.6,
        1.9,
        P("IoT tabanlı hava kalitesi izleme", 46, "FFFFFF", True, after=0),
        name="title",
    )
    s.text(
        0.8,
        3.55,
        7.4,
        1.2,
        P(
            "PM2.5 tahmini ve erken uyarı: ağ ve veri kalitesi bozulduğunda ne olur?",
            22,
            "CFE3EA",
            after=0,
        ),
    )
    s.text(0.8, 5.3, 7, 0.4, P("Orhan Akbaba · Furkan Topçu", 20, "FFFFFF", True, after=0))
    s.text(0.8, 5.75, 7, 0.35, P("Bilgisayar Mühendisliği", 15, ON_DARK_MUTED, after=0))
    s.text(0.8, 6.6, 7, 0.3, P("github.com/furkantopcuu/airq-iot", 14, ON_DARK_MUTED, after=0))
    for i, (v, lab) in enumerate(
        [
            ("{{nDataStations}}", "istasyon, sanal cihaz olarak"),
            ("{{nDataHours}}", "saatlik gerçek ölçüm (Pekin)"),
            ("4", "araştırma sorusu"),
        ]
    ):
        stat(s, 9.0, 1.15 + i * 1.95, 3.7, 1.7, v, lab, AMBER, 44, dark=True, lsize=16)
    sl.append(s)

    # 2 ----------------------------------------------------------- problem
    s = frame("2", "PM2.5'i önceden bilmek, ölçümün ağdan sağlıklı gelmesine bağlıdır")
    rows = [
        (
            "1",
            BLUE,
            "Düşük maliyetli sensör ağları",
            "PM2.5 izlemesi giderek bu ağlara dayanıyor [R4][R1]",
        ),
        ("2", TEAL_DK, "Tahmin ve erken uyarı", "Maruziyeti azaltan kararlar için gerekli [R3]"),
        (
            "3",
            RED,
            "Hat bozulur",
            "Sensörler kayar, takılır, sıçrar [R22][R21]; mesajlar kaybolur, gecikir, bir cihaz susar",
        ),
        (
            "4",
            PURPLE,
            "Ölçülmeyen halka",
            "Çoğu çalışma temiz, arşivlenmiş veride model karşılaştırır; ölçümü taşıyan IoT hattı ölçülmez",
        ),
    ]
    for i, (n, col, head, body) in enumerate(rows):
        y = 1.8 + i * 1.28
        card(s, MARGIN, y, 7.5, 1.12)
        s.rect(MARGIN + 0.22, y + 0.26, 0.6, 0.6, fill=col, oval=True)
        s.text(MARGIN + 0.22, y + 0.26, 0.6, 0.6, P(n, 22, "FFFFFF", True, align="c", after=0), "m")
        s.text(MARGIN + 1.05, y + 0.12, 6.3, 0.34, P(head, 18, INK, True, after=0))
        s.text(MARGIN + 1.05, y + 0.48, 6.3, 0.6, P(body, 14, TEXT, after=0))
    s.rect(8.5, 1.8, 4.23, 4.96, fill=INK, radius=0.12)
    s.text(
        8.85,
        2.1,
        3.55,
        2.6,
        P("Model iyi olsa bile hat bozulursa uyarı çalışır mı?", 30, "FFFFFF", True, after=0),
        "t",
    )
    s.text(
        8.85,
        5.0,
        3.55,
        1.5,
        P(
            "Taramamızda bunu tahmin metrikleriyle aynı düzenekte ölçen bir hava kalitesi çalışması bulamadık.",
            14,
            ON_DARK_MUTED,
            after=0,
        ),
    )
    sl.append(s)

    # 3 ----------------------------------------------------------- RQ and contributions
    s = frame("3", "Dört soru, üç katkı: tahmini ve IoT hattını aynı düzenekte ölçtük")
    rqs = [
        (
            "RQ1",
            "Tahmin",
            BLUE,
            "Komşu istasyonlar 1, 6 ve 24 saatte tahmine ne kadar yardım eder?",
        ),
        ("RQ2", "Erken uyarı", TEAL_DK, "Uyarı ne kadar önceden ve ne doğrulukla çalışır?"),
        (
            "RQ3",
            "Dayanıklılık",
            RED,
            "Kayıp, gecikme, kopan cihaz ve hatalı girdi tahmini ne kadar bozar? Edge filtresi ne kadar engeller?",
        ),
        ("RQ4", "Belirsizlik", PURPLE, "Tahmin aralıkları kalibre mi?"),
    ]
    for i, (tag, head, col, body) in enumerate(rqs):
        x = MARGIN + (i % 2) * 3.95
        y = 1.8 + (i // 2) * 2.5
        card(s, x, y, 3.75, 2.3)
        chip(s, x + 0.2, y + 0.2, tag, col)
        s.text(x + 1.15, y + 0.2, 2.4, 0.32, P(head, 18, INK, True, after=0), "m")
        s.text(x + 0.2, y + 0.7, 3.35, 1.5, P(body, 17, TEXT, after=0))
    s.rect(8.65, 1.8, 4.08, 4.8, fill=INK, radius=0.12)
    s.text(8.95, 2.0, 3.5, 0.4, P("Katkılar", 20, AMBER, True, after=0))
    ks = [
        ("K1", "Sızıntısız çok ufuklu tahmin ve komşu ablasyonu"),
        ("K2", "Tahmin tabanlı erken uyarı ve öncül süre"),
        ("K3", "Ağ ve veri kalitesinin tahmine etkisi"),
    ]
    for i, (k, body) in enumerate(ks):
        y = 2.65 + i * 1.3
        chip(s, 8.95, y, k, AMBER, INK, w=0.6)
        s.text(9.75, y - 0.02, 2.8, 1.15, P(body, 16, "FFFFFF", after=0))
    sl.append(s)

    # 4 ----------------------------------------------------------- architecture
    s = frame(
        "4",
        "{{nDataStations}} sanal cihaz gerçek ölçümleri MQTT ile akıtır; kenarda doğrulanır, tahmine ve uyarıya dönüşür",
    )
    figure(
        s,
        FIG / "architecture.png",
        MARGIN,
        1.75,
        7.9,
        4.95,
        "Sistem mimarisi: sanal sensörler, edge, MQTT broker, ingest, tahmin, SQLite, API ve pano",
    )
    s.text(
        8.8,
        1.75,
        3.93,
        2.7,
        [
            P(
                "**Veri yolu:** cihaz → broker → edge doğrulama → ingest (SQLite) → tahmin + uyarı → API → pano",
                14,
                bullet=True,
            ),
            P(
                "**Kontrol yolu:** `cmd`/`ack` aynı MQTT hattından cihazı, ağı ve edge filtresini canlı değiştirir",
                14,
                bullet=True,
            ),
            P("Her bileşen ayrı bir süreç", 14, bullet=True, after=0),
        ],
    )
    why_box(
        s,
        8.8,
        4.55,
        3.93,
        2.15,
        "Fiziksel sensörümüz yok ama gerçek haze olayları var: gerçek kayıtlı ölçümleri sanal cihazlarla yeniden oynatıyoruz. Bu saha çalışması değil, iz sürümlü emülasyon.",
        14,
    )
    sl.append(s)

    # 5 ----------------------------------------------------------- MQTT, QoS, edge
    s = frame(
        "5",
        "QoS 1 ve idempotent kayıt: mesaj kaybolmaz, tekrar zararsız (ölçülen tekrar oranı {{nDupRateMax}})",
    )
    cards5 = [
        (
            "MQTT",
            BLUE,
            "Sensör için hafif yayın-abone protokolü; yayıncı ile abone birbirini tanımaz [R7]",
        ),
        ("QoS 1", TEAL_DK, "“En az bir kez” teslim: kayıpta mesaj gitmez, tekrar gelebilir"),
        ("Idempotent kayıt", RED, "`(istasyon, ts)` anahtarı: aynı mesaj ikinci satır eklemez"),
        (
            "LWT + retained",
            PURPLE,
            "Cihaz çökerse broker `offline` duyurur; yeni abone son durumu görür",
        ),
    ]
    for i, (head, col, body) in enumerate(cards5):
        x = MARGIN + i * 3.06
        card(s, x, 1.75, 2.9, 2.1)
        chip(s, x + 0.18, 1.93, head, col, w=min(2.55, 0.35 + 0.105 * len(head)))
        s.text(x + 0.18, 2.4, 2.55, 1.4, P(body, 15, TEXT, after=0))
    card(s, MARGIN, 4.03, 8.9, 1.3)
    s.text(MARGIN + 0.2, 4.1, 4, 0.3, P("Edge: 5 kural", 16, INK, True, after=0))
    for i, lab in enumerate(
        ["eksik değer", "aralık dışı", "ani sıçrama", "takılı kalma", "PM2.5 ≤ PM10"]
    ):
        chip(s, MARGIN + 0.2 + i * 1.7, 4.48, lab, INK2, w=1.58, h=0.34)
    s.text(
        MARGIN + 0.2,
        4.95,
        8.5,
        0.28,
        P("Filtre açıkken güvenilmez değer `null` olur [R21][R22]", 12, MUTED, after=0),
    )
    stat(s, 9.7, 4.03, 3.03, 1.3, "{{nDupRateMax}}", "ölçülen tekrar oranı", TEAL_DK, 32)
    why_box(
        s,
        MARGIN,
        5.5,
        W - 2 * MARGIN,
        1.35,
        "QoS 0'da ağ kaybında mesaj sessizce gider ve tahmin eksik veriyle çalışır. QoS 1'in bedeli olan tekrar, kayıt anında zararsız: tüm koşularda tekrar oranı {{nDupRateMax}}.",
        15,
    )
    sl.append(s)

    # 6 ----------------------------------------------------------- data, leakage
    s = frame(
        "6",
        "Kronolojik bölme ve sızıntı önlemleri: R² 1 saatte {{nRTwoMtwobHOne}}, 24 saatte {{nRTwoMtwobHTwentyFour}}",
    )
    total_w = W - 2 * MARGIN
    seg = [
        (29, "Eğitim", "{{nTrainStart}} → {{nTrainEnd}}", BLUE),
        (6, "Doğrulama", "{{nValStart}} → {{nValEnd}}", AMBER),
        (12, "Test", "{{nTestStart}} → {{nTestEnd}}", TEAL_DK),
    ]
    x = MARGIN
    for months, name, dates, col in seg:
        w = total_w * months / 47
        s.rect(x, 1.8, w - 0.04, 0.62, fill=col, radius=0.08)
        s.text(
            x,
            1.8,
            w - 0.04,
            0.62,
            P(name, 16, "FFFFFF" if col != AMBER else INK, True, align="c", after=0),
            "m",
        )
        s.text(x, 2.47, w - 0.04, 0.28, P(dates, 12, MUTED, align="c", after=0))
        x += w
    s.text(
        MARGIN,
        2.95,
        7.3,
        2.6,
        [
            P(
                "“R² = 0,99” şüphelidir: rastgele bölme ve tüm veride ölçekleme sızıntısı sonucu şişirir [R13][R17][R16]",
                16,
                bullet=True,
            ),
            P(
                "Uydurma ve ölçekleme yalnızca eğitimde; model ve eşik seçimi yalnızca doğrulamada",
                16,
                bullet=True,
            ),
            P(
                "Eksik doldurma yalnızca geçmişe bakar (en çok {{nFfillLimit}} saat); gelecekteki PM10 kullanılmaz",
                16,
                bullet=True,
            ),
            P("Önlemler birim testleriyle denetlenir", 16, bullet=True, after=0),
        ],
    )
    stat(s, 8.35, 2.95, 2.1, 1.5, "{{nRTwoMtwobHOne}}", "R², 1 saat sonrası", BLUE, 36)
    stat(s, 10.63, 2.95, 2.1, 1.5, "{{nRTwoMtwobHTwentyFour}}", "R², 24 saat sonrası", RED, 36)
    s.text(
        8.35,
        4.58,
        4.38,
        0.9,
        P(
            "Ufuk uzadıkça R² düşer: dürüst bir sonuç. Persistence 24 saatte R² {{nRTwoPersistHTwentyFour}}.",
            13,
            MUTED,
            after=0,
        ),
    )
    why_box(
        s,
        MARGIN,
        5.6,
        W - 2 * MARGIN,
        1.25,
        "Gerçek sistem geleceği bilmez. Test dönemi her protokol için bir kez değerlendirildi; tek istisna makalede açıkça yazılı (yeniden üretilebilirlik düzeltmesi).",
        15,
    )
    sl.append(s)

    # 7, 8 --------------------------------------------------------- what and why
    hdr = ["Bileşen", "Neden seçtik", "Alternatif ve neden seçmedik"]
    cw = [2.35, 5.2, 4.58]
    tsize = 16
    s = frame("6a-1", "Neyi neden kullandık (1/2): IoT katmanı", "Neyi neden")
    s.table(
        MARGIN,
        1.7,
        cw,
        [
            hdr,
            [
                "**MQTT**",
                "Sensör için hafif yayın-abone; QoS, LWT ve retained hazır; cihaz kopmasını kendisi bildirir [R7]",
                "HTTP: istek-yanıt, kopmayı bildirmez. CoAP: UDP tabanlı, ekosistemi dar",
            ],
            [
                "**QoS 1 + idempotent kayıt**",
                "Kayıpta mesaj gitmez; tekrar `(istasyon, ts)` anahtarıyla zararsız. Ölçülen tekrar oranı {{nDupRateMax}}",
                "QoS 0: kayıp sessiz. QoS 2: saatlik veri için gereksiz yük",
            ],
            [
                "**LWT + retained durum**",
                "Çöken cihazı broker duyurur; yeni abone son durumu hemen görür",
                "Yalnızca heartbeat zaman aşımı: yavaş ve belirsiz",
            ],
            [
                "**Edge veri kalitesi**",
                "Bozuk değer tahmini bozar; kaynakta 5 kuralla işaretle [R21][R22]",
                "Yalnızca sunucuda doğrulama: hatalı veri ağdan geçer",
            ],
            [
                "**SQLite (WAL)**",
                "Saatte {{nDataStations}} satırlık yük; kurulum yok, tek yazıcı yeter",
                "PostgreSQL/TimescaleDB: bu ölçekte fayda yok; binlerce cihazda gerekir",
            ],
        ],
        size=tsize,
    )
    sl.append(s)
    s = frame("6a-2", "Neyi neden kullandık (2/2): tahmin ve değerlendirme", "Neyi neden")
    s.table(
        MARGIN,
        1.7,
        cw,
        [
            hdr,
            [
                "**LightGBM**",
                "Tabloda hızlı, eksik değeri işler, SHAP ile açıklanabilir; ağaç modelleri güçlü [R13][R14]",
                "LSTM/GNN: daha çok ayar, koordinat yok; karşılaştırmayı yapmadık",
            ],
            [
                "**Komşu özellikleri**",
                "Kirlilik şehirde yayılır; varsaymadık, ablasyonla ölçtük (1 sa %{{nAblKelevenHOne}}, 6 sa %{{nAblKelevenHSix}})",
                "GNN: koordinat ve süre maliyeti",
            ],
            [
                "**Kronolojik bölme**",
                "Gelecek sızıntısı olmasın; gerçek kullanımı taklit eder",
                "Rastgele K-fold: sonucu şişirir [R13][R17]",
            ],
            [
                "**F2 ve δ payı**",
                "Olay kaçırmak (sağlık riski) yanlış alarmdan pahalı; δ, tepelerin küçük tahminini telafi eder",
                "F1: iki hatayı eşit sayar. Sabit eşik (δ=0): telafi yok",
            ],
            [
                "**Optuna (TPE)**",
                "Az denemede iyi ayar; {{nOptunaTrials}} deneme yeterli (10→20 kazanç %{{nTuneGainTenTwenty}})",
                "Izgara: pahalı. Elle ayar: tekrar edilemez",
            ],
        ],
        size=tsize,
    )
    sl.append(s)

    # 9 ----------------------------------------------------------- live demo
    s = frame("7", "Canlı demo: tek komut, planlı akış yaklaşık 3 dakika")
    s.rect(MARGIN, 1.75, 4.4, 0.5, fill=INK, radius=0.1)
    s.text(
        MARGIN + 0.2,
        1.75,
        4.1,
        0.5,
        P("`python -m scripts.demo`", 16, "FFFFFF", True, font=MONO, after=0),
        "m",
    )
    s.text(
        MARGIN + 4.6,
        1.75,
        2.3,
        0.5,
        P("broker, edge, ingest, tahmin, API, pano", 12, MUTED, after=0),
        "m",
    )
    steps = [
        ("1", "gercek_haze_replay", "Uyarı haze epizodundan {{nScnHazeLead}} saat önce çıkar"),
        ("2", "sensor_takilmasi", "Edge önce kapalı, sonra açık: filtrenin farkı"),
        ("3", "cihaz_kopmasi", "LWT devreye girer, kartlar offline olur"),
        ("4", "ag_bozulmasi", "Teslim oranı {{nScnDelivery}}, p95 gecikme {{nScnLatencyP}} ms"),
    ]
    for i, (n, name, body) in enumerate(steps):
        y = 2.4 + i * 0.78
        card(s, MARGIN, y, 6.9, 0.68)
        s.rect(MARGIN + 0.15, y + 0.11, 0.46, 0.46, fill=[BLUE, TEAL_DK, RED, PURPLE][i], oval=True)
        s.text(
            MARGIN + 0.15, y + 0.11, 0.46, 0.46, P(n, 16, "FFFFFF", True, align="c", after=0), "m"
        )
        s.text(
            MARGIN + 0.8,
            y + 0.04,
            2.75,
            0.6,
            P(f"`{name}`", 14, INK, True, font=MONO, after=0),
            "m",
        )
        s.text(MARGIN + 3.5, y + 0.04, 3.3, 0.6, P(body, 14, TEXT, after=0), "m")
    s.text(
        MARGIN,
        5.45,
        6.9,
        0.5,
        P(
            "**Serbest test:** jüri istasyon ve değer seçer; geçersiz değer reddedilir; “Sıfırla” temiz duruma döner.",
            14,
            after=0,
        ),
    )
    figure(
        s,
        SHOTS / "01_canli_izleme.jpg",
        7.75,
        1.75,
        4.98,
        2.4,
        "Canlı izleme panosu: 12 istasyon kartı",
    )
    card(s, 7.75, 4.3, 4.98, 1.4)
    s.text(7.95, 4.4, 4.6, 0.3, P("Yedek plan", 14, INK, True, after=0))
    s.text(
        7.95,
        4.75,
        4.6,
        0.9,
        P(
            "`--offline` kayıtlı koşu · demo GIF · ekran görüntüleri · yedek video",
            14,
            MUTED,
            after=0,
        ),
    )
    why_box(
        s,
        MARGIN,
        6.05,
        W - 2 * MARGIN,
        0.92,
        "Komut MQTT'den gider: kontrol yolu da IoT'nin kendi kanalı; her senaryonun hipotezi önceden yazıldı.",
        13,
    )
    sl.append(s)

    # 10 ---------------------------------------------------------- RQ1
    s = frame(
        "8",
        "Komşu istasyonlar 1 ve 6 saatte RMSE'yi %{{nAblKelevenHOne}} ve %{{nAblKelevenHSix}} düşürür, 24 saatte işe yaramaz",
        "RQ1",
    )
    figure(
        s,
        FIG / "rq1_horizon.png",
        MARGIN,
        1.95,
        7.9,
        3.45,
        "RMSE ufuğa göre ve persistence'a göre kazanç",
    )
    card(s, MARGIN, 5.55, 7.9, 1.3, fill="FBE9DF", line="F0C9B3")
    s.text(MARGIN + 0.2, 5.63, 7.5, 0.28, P("OLUMSUZ SONUÇ", 12, RED, True, after=0))
    s.text(
        MARGIN + 0.2,
        5.93,
        7.5,
        0.9,
        P(
            "Aşırı olaylarda (> {{nExtPNinetyFive}} µg/m³) model düşük tahmin eder ve 24 saatte persistence'ın gerisinde kalır: RMSE {{nExtRmseMtwobHTwentyFour}} karşı {{nExtRmsePersistHTwentyFour}}.",
            14,
            after=0,
        ),
    )
    s.text(
        8.8,
        1.95,
        3.93,
        0.3,
        P("Persistence'a göre RMSE iyileşmesi (M2b)", 12, MUTED, True, after=0),
    )
    for i, (v, lab, col) in enumerate(
        [
            ("%{{nImprMtwobHOne}}", "1 sa", BLUE),
            ("%{{nImprMtwobHSix}}", "6 sa", TEAL_DK),
            ("%{{nImprMtwobHTwentyFour}}", "24 sa", RED),
        ]
    ):
        stat(s, 8.8 + i * 1.34, 2.3, 1.25, 1.25, v, lab, col, 24)
    s.text(
        8.8,
        3.7,
        3.93,
        0.8,
        P(
            "Görülmemiş istasyonda (LOSO) iyileşme %{{nLosoMeanHOne}}; istasyon eğitimdeyken %{{nLosoInSampleHOne}}: genelleme korunuyor.",
            13,
            after=0,
        ),
    )
    why_box(
        s,
        8.8,
        4.62,
        3.93,
        2.23,
        "Kirlilik dalgası şehirde istasyondan istasyona yayılır. Bunu iddia etmedik, ablasyonla ölçtük: kısa ufukta anlamlı kazanç, 24 saatte yok.",
        14,
    )
    sl.append(s)

    # 11 ---------------------------------------------------------- RQ2
    s = frame(
        "9",
        "Uyarı 1 ve 6 saatte işe yarar (F2 {{nWarnFtwoMtwobHOne}} ve {{nWarnFtwoMtwobHSix}}), 24 saatte persistence'ın gerisinde",
        "RQ2",
    )
    figure(
        s,
        FIG / "rq2_haze_example.png",
        MARGIN,
        1.95,
        7.9,
        3.55,
        "Gerçek bir haze epizodunda tahmin ve uyarı zamanı",
    )
    card(s, MARGIN, 5.65, 7.9, 1.2)
    s.text(
        MARGIN + 0.2,
        5.75,
        7.5,
        1.05,
        [
            P(
                "**Kural:** tahmin > eşik − δ; δ doğrulamada F2'yi (β={{nBeta}}) en büyük yapacak şekilde seçilir; uyarı sonrası {{nCooldownH}} saat soğuma.",
                14,
                after=4,
            ),
            P(
                "**q90 ile uyarı** (24 sa): recall {{nQwRecMtwobHTwentyFour}} → {{nQwRecQnineHTwentyFour}}, yanlış alarm {{nQwFaMtwobHTwentyFour}} → {{nQwFaQnineHTwentyFour}}.",
                14,
                after=0,
            ),
        ],
    )
    stat(s, 8.8, 1.95, 1.9, 1.3, "{{nWarnFtwoMtwobHOne}}", "F2, 1 saat", BLUE, 28)
    stat(s, 10.83, 1.95, 1.9, 1.3, "{{nWarnFtwoMtwobHSix}}", "F2, 6 saat", TEAL_DK, 28)
    s.text(
        8.8,
        3.4,
        3.93,
        1.1,
        P(
            "Test yılında {{nEventsHundred}} aşım olayı ve {{nEventsHaze}} bölgesel haze epizodu; 24 saatte M2b {{nHazeCaughtMtwobHTwentyFour}}, persistence {{nHazeCaughtPersistHTwentyFour}} epizodu yakalar.",
            13,
            after=0,
        ),
    )
    why_box(
        s,
        8.8,
        4.62,
        3.93,
        2.23,
        "Olay kaçırmak (sağlık riski) yanlış alarmdan pahalı: F2 duyarlılığa ağırlık verir. δ payı, modelin tepeleri küçük tahmin etmesini telafi eder ve yalnızca doğrulamada seçilir.",
        14,
    )
    sl.append(s)

    # 12 ---------------------------------------------------------- RQ3
    s = frame(
        "10",
        "%20 kayıpta 1 saatlik hata +{{nDmgTwenty}} µg/m³; edge filtresi hatalı girdinin zararının %{{nRobRecPersistHOne}} ve %{{nRobRecMtwobHOne}}'ini geri alır",
        "RQ3",
    )
    figure(
        s,
        FIG / "rq3a_system.png",
        MARGIN,
        1.95,
        6.0,
        2.55,
        "Mesaj kaybının tahmine ve sisteme etkisi",
    )
    figure(
        s,
        FIG / "rq3b_damage.png",
        MARGIN + 6.13,
        1.95,
        6.0,
        2.55,
        "Hatalı girdinin zararı ve edge filtresinin geri aldığı kısım",
    )
    stat(
        s,
        MARGIN,
        4.65,
        3.9,
        1.2,
        "+{{nDmgTwenty}} µg/m³",
        "%20 kayıpta 1 saatlik hata artışı; teslim oranı {{nPdrTwenty}}",
        RED,
        26,
    )
    stat(
        s,
        MARGIN + 4.12,
        4.65,
        3.9,
        1.2,
        "{{nBehindTwenty}} / {{nRunsTwenty}}",
        "koşuda {{nSpeedSlow}}× hızda servis geride (medyan gecikme {{nWarnLatBehind}} s)",
        BLUE,
        26,
    )
    stat(
        s,
        MARGIN + 8.24,
        4.65,
        3.89,
        1.2,
        "%{{nRobRecPersistHOne}} / %{{nRobRecMtwobHOne}}",
        "edge filtresinin geri aldığı zarar (persistence / M2b)",
        TEAL_DK,
        26,
    )
    why_box(
        s,
        MARGIN,
        5.98,
        W - 2 * MARGIN,
        0.9,
        "Ağ bozulması uygulama katmanında emüle edildi (kontrollü, tohumlu, tekrarlanabilir); tüm {{nRunsTotal}} koşu ayrı süreçlerle ve ayrı Mosquitto ile alındı.",
        14,
    )
    sl.append(s)

    # 13 ---------------------------------------------------------- measurement found a flaw
    s = frame(
        "10a",
        "Ölçüm bir tasarım kusurunu buldu: çevrimdışı cihaz beklemesi {{nOffLatOneBefore}} s'den {{nOffLatOneAfter}} s'ye indi",
        "K3",
    )
    stat(
        s,
        MARGIN,
        1.95,
        3.6,
        1.9,
        "{{nOffLatOneBefore}} s",
        "ÖNCE: kalıcı çevrimdışı cihaz her saat boşa bekletiyordu",
        RED,
        48,
    )
    s.text(4.35, 2.5, 0.8, 0.8, P("→", 44, MUTED, True, align="c", after=0), "m")
    stat(
        s,
        5.3,
        1.95,
        3.6,
        1.9,
        "{{nOffLatOneAfter}} s",
        "SONRA: retained `offline` görülünce bekleme biter",
        TEAL_DK,
        48,
    )
    card(s, 9.2, 1.95, 3.53, 1.9)
    s.text(
        9.4,
        2.07,
        3.15,
        1.7,
        [
            P(
                "**Neden:** tahmin servisi eksik bir istasyonu {{nWaitMs}} ms bekliyordu",
                13,
                after=4,
            ),
            P("Tam ağda gecikme {{nOffLatFullAfter}} s: değişmedi", 13, after=0),
        ],
    )
    rows13 = [
        (
            "Düzeltme",
            "Servis retained `offline` durumunu görünce kısa bir ek süreden sonra beklemeyi bırakır; hiçbir koşu geride kalmadı.",
        ),
        ("Sınır", "Düzeltme mesaj kaybında yardımcı olmaz: kaybolan mesaj hiçbir şey duyurmaz."),
    ]
    for i, (head, body) in enumerate(rows13):
        y = 4.05 + i * 0.85
        card(s, MARGIN, y, 12.13, 0.72)
        s.text(MARGIN + 0.2, y, 1.4, 0.72, P(head, 15, INK, True, after=0), "m")
        s.text(MARGIN + 1.7, y, 10.2, 0.72, P(body, 14, TEXT, after=0), "m")
    why_box(
        s,
        MARGIN,
        5.85,
        W - 2 * MARGIN,
        1.0,
        "Sistemi ağ koşullarıyla birlikte ölçmeden bu kusur görünmezdi: bu çalışmanın K3 katkısının somut örneği.",
        15,
    )
    sl.append(s)

    # 14 ---------------------------------------------------------- limitations
    s = frame(
        "11", "Sınırlamalar: emülasyon, referans veri, sentetik hata, tek şehir, güvenlik yok"
    )
    lims = [
        (
            "İz sürümlü emülasyon",
            "Saha çalışması değil; ağ bozulması uygulama katmanında, tek makinede emüle edildi.",
            BLUE,
        ),
        (
            "Referans veri",
            "Referans istasyon verisi kullandık; düşük maliyetli sensör verisi değil.",
            TEAL_DK,
        ),
        ("Sentetik hata", "Hatalı girdi sentetik; hata tespiti başarısı iddia edilmiyor.", RED),
        (
            "Tek şehir, tek test yılı",
            "Pekin, {{nDataStations}} istasyon; başka şehre genelleme ölçülmedi.",
            PURPLE,
        ),
        (
            "Güvenlik",
            "Komut kanalı kimlik doğrulamasız ve yalnızca yerel; gerçek dağıtım TLS ve erişim denetimi ister.",
            AMBER_DK,
        ),
        (
            "Küçük örneklem",
            "Canlı senaryolar birer kez, eşleştirilmiş koşular {{nAbSpikeWindows}} pencere: istatistik değil, gösterim.",
            INK2,
        ),
    ]
    for i, (head, body, col) in enumerate(lims):
        x = MARGIN + (i % 3) * 4.1
        y = 1.85 + (i // 3) * 2.55
        card(s, x, y, 3.93, 2.35)
        s.rect(x + 0.22, y + 0.22, 0.42, 0.42, fill=col, oval=True)
        s.text(x + 0.22, y + 0.22, 0.42, 0.42, P("!", 18, "FFFFFF", True, align="c", after=0), "m")
        s.text(x + 0.8, y + 0.2, 3.0, 0.5, P(head, 17, INK, True, after=0), "m")
        s.text(x + 0.22, y + 0.9, 3.5, 1.35, P(body, 17, TEXT, after=0))
    sl.append(s)

    # 15 ---------------------------------------------------------- conclusion
    s = frame(
        "12",
        "Sonuç: tahmin ve uyarı IoT hattıyla birlikte ölçülür; 1-6 saatte işe yarar, uzun ufukta ve aşırı olaylarda yetersizdir",
        dark=True,
    )
    big = [
        (
            "%{{nImprMtwobHOne}} · %{{nImprMtwobHSix}} · %{{nImprMtwobHTwentyFour}}",
            "LightGBM + komşu: persistence'a göre RMSE iyileşmesi (1/6/24 sa)",
        ),
        (
            "F2 {{nWarnFtwoMtwobHOne}} · {{nWarnFtwoMtwobHSix}}",
            "Erken uyarı 1 ve 6 saatte işe yarar; 24 saatte yetersiz",
        ),
        (
            "{{nOffLatOneBefore}} → {{nOffLatOneAfter}} s",
            "Ölçüm bir kusuru buldu ve düzelttirdi: kayıp ve çevrimdışı cihaz gerçek zaman davranışını belirler",
        ),
    ]
    for i, (v, lab) in enumerate(big):
        stat(s, MARGIN + i * 4.1, 2.0, 3.93, 2.1, v, lab, AMBER, 24, dark=True, lsize=16)
    s.text(
        MARGIN,
        4.4,
        7.6,
        2.4,
        [
            P("Gelecek çalışma", 18, AMBER, True, after=6),
            P(
                "Gerçek düşük maliyetli sensörlerle saha testi (PMS5003 + ESP32) [R20][R1]",
                14,
                "FFFFFF",
                bullet=True,
            ),
            P("TLS ve erişim denetimi; GNN karşılaştırması [R12]", 14, "FFFFFF", bullet=True),
            P(
                "Aşırı olaylar için asimetrik amaç; anomali tespiti",
                14,
                "FFFFFF",
                bullet=True,
                after=0,
            ),
        ],
    )
    s.rect(8.6, 4.4, 4.13, 1.9, fill=INK2, radius=0.12)
    s.text(8.8, 4.55, 3.75, 0.3, P("Kod, sonuçlar, makale", 14, ON_DARK_MUTED, True, after=0))
    s.text(8.8, 4.95, 3.75, 0.7, P("github.com/furkantopcuu/airq-iot", 16, "FFFFFF", True, after=0))
    s.text(8.8, 5.65, 3.75, 0.5, P("sürüm v0.3.0", 13, ON_DARK_MUTED, after=0))
    sl.append(s)

    # 16 ---------------------------------------------------------- questions
    s = Slide("13", dark=True)
    s.text(0.8, 2.2, 8, 1.3, P("Sorular", 54, "FFFFFF", True, after=0), name="title")
    s.text(0.8, 3.6, 7.2, 0.5, P("Teşekkürler", 22, AMBER, True, after=0))
    s.rect(8.6, 1.3, 4.13, 5.0, fill=INK2, radius=0.12)
    s.text(8.85, 1.5, 3.6, 0.4, P("Yedek slaytlar", 18, AMBER, True, after=0))
    s.text(
        8.85,
        2.05,
        3.65,
        4.1,
        [
            P(t, 15, "FFFFFF", after=8)
            for t in [
                "B1 · Hiperparametreler",
                "B2 · Aşırı olaylar",
                "B3 · LOSO",
                "B4 · RQ4 belirsizlik",
                "B5 · Literatür",
                "B6 · Senaryo Kontrol",
                "B7 · Güvenlik",
            ]
        ],
    )
    s.text(0.8, 6.6, 7, 0.3, P("github.com/furkantopcuu/airq-iot", 14, ON_DARK_MUTED, after=0))
    sl.append(s)

    # ---------------------------------------------------------- backups
    s = frame(
        "B1",
        "Hiperparametreler: {{nOptunaTrials}} Optuna denemesi yeterli (10. ile 20. deneme arası ortalama kazanç %{{nTuneGainTenTwenty}})",
        "Yedek B1",
    )
    stat(s, MARGIN, 1.95, 3.9, 1.7, "{{nOptunaTrials}}", "deneme: Optuna (TPE) bütçesi", BLUE, 44)
    stat(
        s,
        MARGIN + 4.12,
        1.95,
        3.9,
        1.7,
        "%{{nTuneGainTenTwenty}}",
        "10. ile 20. deneme arası ortalama kazanç",
        TEAL_DK,
        44,
    )
    stat(
        s,
        MARGIN + 8.24,
        1.95,
        3.89,
        1.7,
        "yalnızca doğrulama",
        "seçim doğrulamada; test'e bakılmadı",
        AMBER_DK,
        26,
    )
    s.text(
        MARGIN,
        4.0,
        12.1,
        1.6,
        [
            P(
                "Tablolar: `reports/tables/rq1_tuning.csv`, `reports/tables/rq1_tuning_convergence.csv`",
                17,
                bullet=True,
            ),
            P(
                "20 deneme sonrası ek kazanç küçük: daha fazla deneme maliyeti haklı çıkarmaz",
                17,
                bullet=True,
                after=0,
            ),
        ],
    )
    sl.append(s)

    s = frame(
        "B2",
        "Aşırı olay tablosu: hedef > {{nExtPNinetyFive}} µg/m³ iken model düşük tahmin eder",
        "Yedek B2",
    )
    stat(
        s,
        MARGIN,
        1.95,
        3.9,
        1.7,
        "{{nExtRmseMtwobHTwentyFour}}",
        "M2b RMSE, 24 saat, aşırı olaylar",
        RED,
        44,
    )
    stat(
        s,
        MARGIN + 4.12,
        1.95,
        3.9,
        1.7,
        "{{nExtRmsePersistHTwentyFour}}",
        "persistence RMSE, aynı olaylar",
        TEAL_DK,
        44,
    )
    stat(
        s,
        MARGIN + 8.24,
        1.95,
        3.89,
        1.7,
        "{{nExtBiasMtwobHTwentyFour}} µg/m³",
        "ortalama hata (gerçek eksi tahmin): düşük tahmin",
        BLUE,
        32,
    )
    s.text(
        MARGIN,
        4.0,
        12.1,
        2.4,
        [
            P(
                "Karesel hata amacı ortalamaya çeker; eğitimde aşırı değerler azdır. Nedenini ayrıca izole etmedik.",
                17,
                bullet=True,
            ),
            P(
                "Hafifletme: q90 tabanlı uyarı recall'u {{nQwRecMtwobHTwentyFour}}'den {{nQwRecQnineHTwentyFour}}'e çıkarır; bedeli yanlış alarm.",
                17,
                bullet=True,
            ),
            P("Tablo: `paper/tables/rq1_extreme.md`", 17, bullet=True, after=0),
        ],
    )
    sl.append(s)

    s = frame(
        "B3",
        "LOSO: model {{nLosoStations}} istasyonun {{nLosoBetterHOne}} / {{nLosoBetterHSix}} / {{nLosoBetterHTwentyFour}}'inde görülmeden de persistence'ı geçer (1/6/24 sa)",
        "Yedek B3",
    )
    figure(
        s,
        FIG / "rq1_ablation_loso.png",
        MARGIN,
        1.95,
        8.2,
        3.5,
        "Komşu ablasyonu ve LOSO sonuçları",
    )
    stat(
        s,
        9.1,
        1.95,
        3.63,
        1.6,
        "%{{nLosoMeanHOne}}",
        "görülmemiş istasyonda 1 saatlik iyileşme",
        BLUE,
        34,
    )
    stat(s, 9.1, 3.75, 3.63, 1.6, "%{{nLosoInSampleHOne}}", "istasyon eğitimdeyken", TEAL_DK, 34)
    s.text(
        MARGIN,
        5.7,
        12.1,
        0.8,
        P(
            "Leave-one-station-out: bir istasyon eğitimden çıkarılır, o istasyonda test edilir. Tablo: `paper/tables/rq1_loso.md`",
            14,
            after=0,
        ),
    )
    sl.append(s)

    s = frame(
        "B4",
        "RQ4: ham aralık kapsaması {{nCovRawHOne}}, kalibre {{nCovCalHOne}} (1 sa); aşırı hedeflerde 24 saatte yalnızca {{nCovExtCalHTwentyFour}}",
        "Yedek B4",
    )
    figure(s, FIG / "rq4_uncertainty.png", MARGIN, 1.95, 8.2, 3.5, "Tahmin aralıklarının kapsaması")
    stat(
        s,
        9.1,
        1.95,
        3.63,
        1.6,
        "{{nCovRawHOne}} → {{nCovCalHOne}}",
        "ham → kalibre kapsama (1 saat; hedef 0.80)",
        BLUE,
        28,
    )
    stat(
        s,
        9.1,
        3.75,
        3.63,
        1.6,
        "{{nCovExtCalHTwentyFour}}",
        "aşırı hedeflerde kalibre kapsama (24 saat)",
        RED,
        34,
    )
    s.text(
        MARGIN,
        5.7,
        12.1,
        0.8,
        P(
            "Aralıklar ortalama durumda kalibre edilebilir; aşırı olaylarda güvenilmez. Tablo: `paper/tables/rq4_coverage.md`",
            14,
            after=0,
        ),
    )
    sl.append(s)

    s = frame(
        "B5",
        "Literatür karşılaştırması: ağ ve veri kalitesi etkisini tahminle birlikte ölçen çalışma bulamadık (taramamızda)",
        "Yedek B5",
    )
    s.table(
        MARGIN,
        1.95,
        [1.0, 3.5, 2.4, 2.3, 2.93],
        [
            ["Çalışma", "Mimari / protokol", "Yöntem", "Görev", "Ağ / veri kalitesi → tahmin"],
            ["[R5]", "Kenar-IoT, EC sensör", "Kenarda işleme", "İzleme", "Yok"],
            ["[R6]", "RPi4 kenar, MQTT", "Kenarda ML", "AQI tahmini", "Yok"],
            ["[R18]", "MQTT, kenar broker, InfluxDB/Grafana", "İzleme", "İzleme", "Yok"],
            ["[R13]", "—", "Ridge/EN/XGB, persistence", "0/1/6/24 sa", "Yok"],
            ["[R14]", "—", "RF/XGB/LGBM/CatBoost", "1/6/24 sa", "Yok"],
            [
                "**Bu çalışma**",
                "Sanal cihaz, MQTT QoS 1/LWT, edge, FastAPI",
                "LightGBM, erken uyarı",
                "1/6/24 sa + uyarı",
                "**Var (RQ3)**",
            ],
        ],
        size=15,
    )
    s.text(
        MARGIN,
        6.35,
        12.1,
        0.5,
        P(
            "Çalışmaların bildirdiği özelliklere göre; tam tablo makalede (Tablo I).",
            12,
            MUTED,
            italic=True,
            after=0,
        ),
    )
    sl.append(s)

    s = frame(
        "B6",
        "Senaryo Kontrol: {{nScnConfirmed}} / {{nScnTotal}} hipotez doğrulandı, {{nScnRefuted}} çürütüldü",
        "Yedek B6",
    )
    figure(s, FIG / "scenarios_ab.png", MARGIN, 1.95, 6.0, 2.6, "Senaryo A/B sonuçları")
    figure(
        s, FIG / "scenarios_edge.png", MARGIN + 6.13, 1.95, 6.0, 2.6, "Edge filtresi senaryoları"
    )
    stat(
        s,
        MARGIN,
        4.75,
        3.9,
        1.3,
        "{{nScnConfirmed}} / {{nScnTotal}}",
        "hipotez doğrulandı",
        TEAL_DK,
        34,
    )
    stat(
        s,
        MARGIN + 4.12,
        4.75,
        3.9,
        1.3,
        "{{nScnRefuted}}",
        "hipotez çürütüldü ve olduğu gibi raporlandı",
        RED,
        34,
    )
    s.text(
        MARGIN + 8.3,
        4.8,
        3.8,
        1.3,
        P(
            "Her senaryonun hipotezi çalıştırmadan önce yazıldı. Tablo: `paper/tables/scenarios.md`",
            13,
            after=0,
        ),
    )
    sl.append(s)

    s = frame("B7", "Güvenlik: yalnızca yerel; üç açık bulundu ve düzeltildi", "Yedek B7")
    for i, (head, body) in enumerate(
        [
            ("HTML enjeksiyonu", "Panoda HTML enjeksiyonu bulundu; HTML kaçışlama eklendi."),
            (
                "Ağa açık pano",
                "Pano ağa açıktı; yalnızca loopback (yerel makine) bağlantılara açıldı.",
            ),
            ("Host/Origin denetimi", "API'de Host/Origin denetimi yoktu; denetim eklendi."),
        ]
    ):
        x = MARGIN + i * 4.1
        card(s, x, 1.95, 3.93, 2.2)
        chip(s, x + 0.2, 2.15, head, RED, w=min(3.5, 0.4 + 0.1 * len(head)))
        s.text(x + 0.2, 2.65, 3.55, 1.4, P(body, 17, after=0))
    s.text(
        MARGIN,
        4.45,
        12.1,
        1.8,
        [
            P(
                "Testle korunuyor: `tests/unit/test_security.py`; sınırlar `SECURITY.md` dosyasında yazılı",
                17,
                bullet=True,
            ),
            P(
                "Komut kanalı kimlik doğrulamasız ve yalnızca yerel; gerçek dağıtım TLS ve MQTT erişim denetimi ister",
                17,
                bullet=True,
                after=0,
            ),
        ],
    )
    sl.append(s)

    return sl


# ---------------------------------------------------------------- notes


def load_notes() -> dict[str, str]:
    text = (ROOT / "slides" / "notes.md").read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for part in re.split(r"^## ", text, flags=re.M)[1:]:
        head, _, body = part.partition("\n")
        m = re.match(r"(\w+a?)\.", head)
        key = m.group(1) if m else ("backups" if head.startswith("Yedek") else head)
        out[key] = (head + "\n" + body).strip()
    return out


def attach(slides: list[Slide]) -> None:
    notes = load_notes()
    alias = {"6a-1": "6a", "6a-2": "6a"}
    for s in slides:
        key = alias.get(s.key, s.key)
        s.notes = notes.get(key, notes["backups"] if s.key.startswith("B") else "")
        if not s.notes:
            s.problems.append(f"{s.key}: no speaker notes")


# ---------------------------------------------------------------- writers


def emu(v: float) -> int:
    return int(round(v * 914400))


def rgb(hexstr: str):
    from pptx.dml.color import RGBColor

    return RGBColor.from_string(hexstr)


def write_pptx(slides: list[Slide], path: Path) -> None:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.oxml.ns import qn
    from pptx.util import Pt

    prs = Presentation()
    prs.slide_width, prs.slide_height = emu(W), emu(H)
    prs.core_properties.title = "IoT tabanlı hava kalitesi izleme: tahmin ve erken uyarı"
    prs.core_properties.author = "Orhan Akbaba, Furkan Topçu"
    prs.core_properties.subject = "Nesnelerin İnterneti dersi sunumu"
    blank = prs.slide_layouts[6]
    anchors = {"t": MSO_ANCHOR.TOP, "m": MSO_ANCHOR.MIDDLE, "b": MSO_ANCHOR.BOTTOM}
    aligns = {"l": PP_ALIGN.LEFT, "c": PP_ALIGN.CENTER, "r": PP_ALIGN.RIGHT}

    def fill_runs(par, p: P) -> None:
        for text, bold, mono in runs(num(p.text)):
            r = par.add_run()
            r.text = text
            f = r.font
            f.name = MONO if (mono or p.font == MONO) else p.font
            f.size = Pt(p.size)
            f.bold = bold or p.bold
            f.italic = p.italic
            f.color.rgb = rgb(p.color)

    def style_par(par, p: P, last: bool) -> None:
        par.alignment = aligns[p.align]
        par.space_after = Pt(0 if last else p.after)
        par.space_before = Pt(0)
        par.line_spacing = 1.0
        if p.bullet:
            ppr = par._p.get_or_add_pPr()
            ppr.set("marL", str(emu(BULLET_INDENT)))
            ppr.set("indent", str(-emu(BULLET_INDENT)))
            from lxml import etree

            clr = etree.SubElement(ppr, qn("a:buClr"))
            etree.SubElement(clr, qn("a:srgbClr")).set(
                "val", AMBER if p.color.upper() in ("FFFFFF", "CFE3EA") else BLUE
            )
            etree.SubElement(ppr, qn("a:buFont")).set("typeface", "Arial")
            etree.SubElement(ppr, qn("a:buChar")).set("char", "•")

    for s in slides:
        sld = prs.slides.add_slide(blank)
        bgfill = sld.background.fill
        bgfill.solid()
        bgfill.fore_color.rgb = rgb(INK if s.dark else BG)
        for el in s.els:
            if isinstance(el, Rect):
                shape = sld.shapes.add_shape(
                    MSO_SHAPE.OVAL
                    if el.oval
                    else (MSO_SHAPE.ROUNDED_RECTANGLE if el.radius else MSO_SHAPE.RECTANGLE),
                    emu(el.x),
                    emu(el.y),
                    emu(el.w),
                    emu(el.h),
                )
                if el.radius and not el.oval:
                    shape.adjustments[0] = min(0.5, el.radius / min(el.w, el.h))
                if el.fill:
                    shape.fill.solid()
                    shape.fill.fore_color.rgb = rgb(el.fill)
                else:
                    shape.fill.background()
                if el.line:
                    shape.line.color.rgb = rgb(el.line)
                    shape.line.width = Pt(0.75)
                else:
                    shape.line.fill.background()
                sp = shape._element.spPr
                from lxml import etree

                etree.SubElement(sp, qn("a:effectLst"))  # no theme shadow
                shape._element.nvSpPr.cNvPr.set("name", "Kart" if el.radius else "Şekil")
            elif isinstance(el, Text):
                tb = sld.shapes.add_textbox(emu(el.x), emu(el.y), emu(el.w), emu(el.h))
                tb.name = el.name or "Metin"
                tf = tb.text_frame
                tf.word_wrap = True
                tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
                tf.vertical_anchor = anchors[el.anchor]
                for i, p in enumerate(el.paras):
                    par = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                    style_par(par, p, i == len(el.paras) - 1)
                    fill_runs(par, p)
            elif isinstance(el, Pic):
                pic = sld.shapes.add_picture(
                    str(el.path), emu(el.x), emu(el.y), emu(el.w), emu(el.h)
                )
                pic._element.nvPicPr.cNvPr.set("descr", el.alt or el.path.stem)
                pic._element.nvPicPr.cNvPr.set("name", el.path.stem)
            elif isinstance(el, Table):
                gf = sld.shapes.add_table(
                    len(el.rows),
                    len(el.col_w),
                    emu(el.x),
                    emu(el.y),
                    emu(sum(el.col_w)),
                    emu(sum(el.row_h)),
                )
                tbl = gf.table
                tbl_pr = tbl._tbl.tblPr
                tbl_pr.set("firstRow", "0")
                tbl_pr.set("bandRow", "0")
                for child in list(tbl_pr):
                    tbl_pr.remove(child)  # no built-in style: fills are explicit
                for j, cwid in enumerate(el.col_w):
                    tbl.columns[j].width = emu(cwid)
                for i, row in enumerate(el.rows):
                    tbl.rows[i].height = emu(el.row_h[i])
                    for j, txt in enumerate(row):
                        cell = tbl.cell(i, j)
                        cell.margin_left = cell.margin_right = emu(0.12)
                        cell.margin_top = cell.margin_bottom = emu(0.1)
                        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                        cell.fill.solid()
                        cell.fill.fore_color.rgb = rgb(
                            INK if i == 0 else (CARD if i % 2 else "E9EFF1")
                        )
                        p = P(txt, el.size, "FFFFFF" if i == 0 else TEXT, bold=(i == 0), after=0)
                        par = cell.text_frame.paragraphs[0]
                        cell.text_frame.word_wrap = True
                        style_par(par, p, True)
                        fill_runs(par, p)
        sld.notes_slide.notes_text_frame.text = s.notes
    path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(path)


def draw_preview(s: Slide, path: Path, ppi: int = 100) -> None:
    img = Image.new("RGB", (int(W * ppi), int(H * ppi)), "#" + (INK if s.dark else BG))
    d = ImageDraw.Draw(img)

    def px(v):
        return int(round(v * ppi))

    def draw_text(x, y, w, h, paras, anchor):
        total = text_height(paras, w)
        cy = y + (0 if anchor == "t" else (h - total) / 2 if anchor == "m" else h - total)
        for pi, p in enumerate(paras):
            lines = wrap(p, w)
            for line in lines:
                lh = p.size * LINE_SPACING / 72
                indent = BULLET_INDENT if p.bullet else 0
                width = sum(
                    pil_font(
                        p.size * ppi / 72, b or p.bold, p.italic, m or p.font == MONO
                    ).getlength(t)
                    for t, b, m in line
                )
                lx = x + indent
                if p.align == "c":
                    lx = x + indent + (w - indent) / 2 - width / ppi / 2
                elif p.align == "r":
                    lx = x + w - width / ppi
                if p.bullet and line is lines[0]:
                    d.text(
                        (px(x + 0.02), px(cy)),
                        "•",
                        font=pil_font(p.size * ppi / 72, True, False, False),
                        fill="#" + (AMBER if p.color.upper() in ("FFFFFF", "CFE3EA") else BLUE),
                    )
                cx = px(lx)
                for t, b, m in line:
                    f = pil_font(p.size * ppi / 72, b or p.bold, p.italic, m or p.font == MONO)
                    d.text(
                        (cx, px(cy) + int(p.size * ppi / 72 * 0.08)), t, font=f, fill="#" + p.color
                    )
                    cx += f.getlength(t)
                cy += lh
            if pi < len(paras) - 1:
                cy += p.after / 72

    for el in s.els:
        if isinstance(el, Rect):
            box = [px(el.x), px(el.y), px(el.x + el.w), px(el.y + el.h)]
            fill = "#" + el.fill if el.fill else None
            outline = "#" + el.line if el.line else None
            if el.oval:
                d.ellipse(box, fill=fill, outline=outline)
            elif el.radius:
                d.rounded_rectangle(
                    box, radius=px(min(el.radius, el.h / 2, el.w / 2)), fill=fill, outline=outline
                )
            else:
                d.rectangle(box, fill=fill, outline=outline)
        elif isinstance(el, Text):
            draw_text(el.x, el.y, el.w, el.h, el.paras, el.anchor)
        elif isinstance(el, Pic):
            im = Image.open(el.path).convert("RGB").resize((px(el.w), px(el.h)))
            img.paste(im, (px(el.x), px(el.y)))
        elif isinstance(el, Table):
            y = el.y
            for i, row in enumerate(el.rows):
                x = el.x
                for j, txt in enumerate(row):
                    cw = el.col_w[j]
                    d.rectangle(
                        [px(x), px(y), px(x + cw), px(y + el.row_h[i])],
                        fill="#" + (INK if i == 0 else (CARD if i % 2 else "E9EFF1")),
                    )
                    p = P(txt, el.size, "FFFFFF" if i == 0 else TEXT, bold=(i == 0), after=0)
                    draw_text(x + 0.12, y + 0.1, cw - 0.24, el.row_h[i] - 0.2, [p], "m")
                    x += cw
                y += el.row_h[i]
    img.save(path)


def contact_sheets(dirpath: Path, files: list[Path], per: int = 4) -> list[Path]:
    out = []
    for k in range(0, len(files), per):
        chunk = files[k : k + per]
        ims = [Image.open(f) for f in chunk]
        w, h = ims[0].size
        sheet = Image.new("RGB", (w * 2 + 10, h * 2 + 10), "#888888")
        for i, im in enumerate(ims):
            sheet.paste(im, ((i % 2) * (w + 10), (i // 2) * (h + 10)))
        p = dirpath / f"sheet_{k // per + 1}.png"
        sheet.save(p)
        out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--preview", metavar="DIR", help="also render PNG previews and contact sheets into DIR"
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="build in memory and fail on any problem; write nothing",
    )
    args = ap.parse_args()
    slides = build()
    attach(slides)
    # the footer needs the final count, so it is added last
    for i, s in enumerate(slides, 1):
        if s.key not in ("1", "13"):
            footer(s, i, len(slides))
    problems = [p for s in slides for p in s.problems]
    for p in problems:
        print("PROBLEM:", p)
    if args.check:
        print("deck check: OK" if not problems else f"deck check: {len(problems)} problem(s)")
        return 1 if problems else 0
    write_pptx(slides, OUT)
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB, {len(slides)} slides)")
    if args.preview:
        d = Path(args.preview)
        d.mkdir(parents=True, exist_ok=True)
        files = []
        for i, s in enumerate(slides, 1):
            f = d / f"slide_{i:02d}.png"
            draw_preview(s, f)
            files.append(f)
        print("sheets:", *[str(p) for p in contact_sheets(d, files)], sep="\n  ")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
