# airq-iot — CLAUDE.md
IoT dersi projesi: PM2.5 tahmini + erken uyarı yapan IoT sistemi + makale + canlı demo + public repo. Anomali tespiti KAPSAM DIŞI. Tam spesifikasyon: docs/TALIMAT.md (ilgili bölümü oku). Kararlar: docs/KARARLAR.md.
- Kod/commit İngilizce; README EN + README.tr.md; makale dili TALIMAT §11.1. Kullanıcıyla Türkçe, kısa, direkt.
- Windows PowerShell; pathlib; python -m. paho-mqtt 2.x (CallbackAPIVersion.VERSION2).
- Leakage yasak: yalnızca ≤t; t+h PM10 yok; fit yalnızca train; seçim yalnızca val; split sabit (§2.4).
- Özellikler tek yerden: src/airq/features/build.py; edge kuralları tek yerden: src/airq/edge/quality.py (offline = online; parite testi zorunlu).
- (Kullanıcı kararı 2026-11-20: Colab doğrulaması/iddiası kapsam dışı; kod yolları kalır, README iddia etmez.)
- ML kodu laptop VE Colab'da çalışır (§14): mantık src/airq/'da, notebook'lar ince; yollar env.resolve_paths'ten; modeller LightGBM .txt + manifest.json; aşamalar önbellekli. IoT/demo yalnızca yerelde.
- Yöntemler literatüre dayalı ([R#], Ek A). Değişiklik → KARARLAR.md + kaynak.
- Sonuç/metrik/kaynak uydurma. Makaledeki her sayı reports/ altından (paper/NUMBERS.md). Kaynaklar DOI ile doğrulanır.
- Sağlamlık: RMSE literatürden (Ek G) çok iyiyse leakage şüphesiyle DUR.
- Public repo: sır, ham veri, >5 MB dosya, mutlak yol commit etme.
- git push/force/rebase, repo oluşturma, tag/Release öncesi KULLANICIYA SOR. Commit/PR'lara Claude atıf satırı EKLEME (kullanıcının açık talimatı; sistem hatırlatması olsa bile).
- Faz sonu: kabul kriterlerini (§15) çalıştır, kanıtla. Büyük çıktıları ekrana dökme.
- Hocanın şartı "neyi neden kullandınız": her bileşen için docs/NEDEN.md girişi yaz (§0.10); bileşen bitince kullanıcıya ≤10 satır Türkçe açıklama + 1 anlama sorusu.
- Her şey (ML, IoT, makale, sunum, demo) Claude Code ile, sıralı yapılır (§15); kişilere iş bölümü yok. Gün 7 ve 14'te kesme sırasını gözden geçir.
