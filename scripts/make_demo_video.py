"""Build the silent backup video of the dashboard from the screenshots (TALIMAT 12.3).

    python -m scripts.make_demo_video

Reads slides/demo_screens/*.jpg, writes a caption under each picture and encodes
slides/demo_backup.mp4 with ffmpeg (4 seconds per screen). It is a fallback for a failing live
demo; a narrated screen recording of the live flow can replace it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SCREENS = ROOT / "slides" / "demo_screens"
OUT = ROOT / "slides" / "demo_backup.mp4"
SECONDS = 4
CAPTIONS = {
    "01_canli_izleme": "Canlı izleme: 12 istasyon kartı, 1 ve 6 saat sonrası tahmin, uyarı sayısı",
    "02_puan_tablosu": "Puan tablosu: her müdahale için uyarı, öncül süre ve tahmin hatası",
    "03_ag_gorunumu": "Ağ görünümü: kartlar, kirlilik bandı ve uyarılar",
    "04_istasyon_detayi": "İstasyon detayı: ölçüm, 1/6/24 saatlik tahmin, q10-q90 bandı, uyarılar",
    "05_uyarilar": "Uyarılar: istasyon, ufuk, eşik, tahmin ve gerçekleşme",
    "06_deney_sonuclari": "Deney sonuçları (API üzerinden): şekiller ve tablolar",
}
NOTE = "Kayıtlı koşu (python -m scripts.demo --offline): yedek gösterim"


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def frame(path: Path, caption: str, step: str) -> Image.Image:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    bar = 64
    canvas = Image.new("RGB", (w - w % 2, h + bar - (h + bar) % 2), (24, 24, 28))
    canvas.paste(img, (0, 0))
    d = ImageDraw.Draw(canvas)
    d.text((16, h + 8), f"{step}  {caption}", font=font(22), fill=(255, 255, 255))
    d.text((16, h + 36), NOTE, font=font(16), fill=(170, 170, 180))
    return canvas


def main() -> int:
    if shutil.which("ffmpeg") is None:
        print("ffmpeg not found: install it to build the video")
        return 1
    files = sorted(SCREENS.glob("*.jpg"))
    if not files:
        print(f"no screenshots in {SCREENS}")
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        for i, f in enumerate(files, 1):
            cap = CAPTIONS.get(f.stem, f.stem.replace("_", " "))
            frame(f, cap, f"{i}/{len(files)}").save(Path(tmp) / f"f{i:02d}.png")
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error", "-framerate", f"1/{SECONDS}", "-i",
            str(Path(tmp) / "f%02d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "25",
            "-movflags", "+faststart", str(OUT),
        ]  # fmt: skip
        subprocess.run(cmd, check=True)  # noqa: S603
    print(
        f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB, {len(files) * SECONDS} s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
