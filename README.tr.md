# airq-iot

IoT tabanlı hava kalitesi izleme, çok ufuklu PM2.5 tahmini ve erken uyarı.
Pekin çok istasyonlu hava kalitesi verisi, sanal IoT cihazlarıyla MQTT üzerinden yeniden
oynatılır (trace-driven emülasyon), edge gateway'de doğrulanır ve LightGBM ile 1/6/24 saat
sonrası tahmin edilir.

> **Durum:** devam ediyor (iskelet). Sonuçlar, demo GIF'i ve Colab rozetleri proje ilerledikçe
> eklenecek. English: [README.md](README.md).

## Hızlı başlangıç (Windows PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
pre-commit install
pytest -m "not broker and not slow"
```

## Colab notebook'ları

ML kısmı (veri, EDA, tahmin, erken uyarı, dayanıklılık) tarayıcıda yeniden üretilebilir; canlı IoT sistemi
(broker, cihaz filosu, edge, dashboard, demo) yalnızca yerelde çalışır.

| Notebook | İçerik |
|---|---|
| [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/furkantopcuu/airq-iot/blob/main/notebooks/00_setup_colab.ipynb) `00_setup_colab` | kurulum, indirme + SHA-256 kontrolü, temiz veri seti |
| [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/furkantopcuu/airq-iot/blob/main/notebooks/01_data_eda.ipynb) `01_data_eda` | Tablo 1, korelasyon / eksik veri şekli, epizotlar |

Her notebook `QUICK = True` ile başlar (2 istasyon, birkaç dakika); tam çalışma için `QUICK = False` yapın.

## Sınırlamalar

Veri, düşük maliyetli sensörlerden değil referans istasyonlardan gelir; değerlendirme saha
çalışması değil, trace-driven emülasyondur.

## Lisans

MIT.

## Yazarlar

Orhan Akbaba, Furkan Topçu — İstanbul Medeniyet Üniversitesi, Bilgisayar Mühendisliği (IoT dersi dönem projesi).
