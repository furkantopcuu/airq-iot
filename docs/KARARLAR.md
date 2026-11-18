# KARARLAR (decision log)

Format: tarih · karar · gerekçe · kaynak.

- 2026-11-18 · Repo public: `furkantopcuu/airq-iot`; çalışma dalı `main` (kullanıcı tercihi, PR akışı sonra). · Kullanıcı isteği.
- 2026-11-18 · Lisans MIT (kullanıcı onayladı). · TALIMAT §13.3.
- 2026-11-18 · Yazarlar: Orhan Akbaba, Furkan Topçu (LICENSE, README, CITATION.cff). · Kullanıcı bildirimi.
- 2026-11-18 · `docs/TALIMAT.md` repoda tutulmaz (yerelde kalır, .gitignore'da). İlk iki commit'te geçmişte durur; geçmişi temizlemek force-push gerektirir. · Kullanıcı kararı.
- 2026-11-18 · Mosquitto zorunlu değil: `amqtt` yedeği var (TALIMAT §3.2). RQ3a gecikme ölçümleri için referans broker Mosquitto tercih edilir; kurulum `winget install EclipseFoundation.Mosquitto`. Kurulana kadar `amqtt`. · TALIMAT §3.2.
- 2026-11-18 · Ders makalesi: "8. IoT Tabanlı Hava Kalitesi ve Çevresel İzleme — Air-quality sensor networks + ML". Ayrı künye yoksa merkezî atıf [R1] ve [R2]. · TALIMAT §11.5.
- 2026-11-18 · Commit'lerde Claude atıf satırı yok. · Kullanıcının açık talimatı.
- 2026-11-18 · Veri seti lisansı UCI sayfasından doğrulandı: CC BY 4.0; DOI 10.24432/C5RK5G. · UCI dataset #501.
- 2026-11-18 · Veri sayıları doğrulandı: 420.768 istasyon-saat, PM2.5 eksik %2,077, ortalama 79,79, medyan 55, p95 242 (literatürle uyumlu [R13]). Train p95 = 232. · reports/tables/dataset_summary.csv.
- 2026-11-18 · Önemli bulgu: train'de PM2.5 > PM10 oranı %8,2 (ALL); aşım p99,9 değeri yüksek. Edge fiziksel tutarlılık kuralının (ε, c) toleransı bu tanıya göre Gün 6'da seçilecek; kural gevşek olmalı. · reports/tables/physical_consistency.csv.
- 2026-11-18 · Epizot etiketleri ham (doldurulmamış) PM2.5 üzerinden hesaplanır; NaN aşım sayılmaz. Epizot, başlangıcının düştüğü split'e atanır. · TALIMAT §2.5.
- 2026-11-18 · İndirme önce `.part` dosyasına yazılır, geçerli zip ise yeniden adlandırılır (UCI bağlantısı bir kez yarıda kesildi). · download.py.
- 2026-11-18 · Özellikler float32 (Colab belleği, §14.6). Rolling pencere t'yi içerir, min_periods = max(2, ceil(w/2)); yağış 24 saat toplamı min_periods=12. · TALIMAT §4.2.
- 2026-11-18 · `edge`'den gelen `quality_flags` özellik olarak Gün 6'da (edge/quality.py yazılınca) eklenecek; şimdilik `*_missing` göstergeleri var. · TALIMAT §4.2.7.
- 2026-11-18 · k=3 komşular train'de (ts <= 2015-08-31 23:00) ham PM2.5 korelasyonuyla seçilir; `models/neighbors.json`. k=11 hepsi. Hedef y = doldurulmamış PM2.5(t+h) (`make_target`). · TALIMAT §4.2.6.
- 2026-11-18 · Gün 4 (v0) VALIDATION üzerinde değerlendirildi, test'e bakılmadı (TALIMAT §2.4: test tek bakış). LightGBM'in early stopping'i val kullandığı için val RMSE hafif iyimserdir; seçim ve sağlamlık kontrolü içindir. · reports/metrics/forecast_v0.json.
- 2026-11-18 · v0 sonuçları (val, persistence'a göre RMSE iyileşmesi): h=1: Ridge +5,9%, M1 +2,4%, M2(k=3) +10,4%, M2(k=11) +10,1%; h=6: Ridge +7,7%, M1 +9,7%, M2 k3 +10,2%, M2 k11 +11,8%; h=24: Ridge +14,3%, M1 +14,6%, M2 k3 +14,4%, M2 k11 +15,0%. Komşu bilgisi en çok h=1 ve h=6'da katkı veriyor (M1→M2); h=24'te fark küçük. Sağlamlık alarmı yok. B1 (seasonal-naive) persistence'tan çok kötü (RMSE ~106). · forecast_v0.json.
- 2026-11-18 · Dikkat: LightGBM train RMSE, val RMSE'den belirgin düşük (h=24'te ~52 vs ~90; h=1'de ~14–15 vs ~21–22). Hem aşırı öğrenme hem dağılım kayması (val = Eylül–Şubat kış/haze ağırlıklı) olabilir; Gün 8'de Optuna ile düzenlileştirme (min_child_samples, lambda, num_leaves) ve kayma analizi yapılacak. Bu aşamada ayrıştırılmadı, iddia edilmiyor. · TALIMAT §4.5.
- 2026-11-18 · Ridge (B2) k=0 özellikleriyle çalışır; medyan imputasyon + standardizasyon yalnızca train'de fit edilir, alpha val'de seçilir. LightGBM modelleri `models/` altında (git dışı), her model manifest.json'da kayıtlı. · TALIMAT §4.3.
- 2026-11-18 · Broker: Mosquitto kurulu değil, amqtt 0.12 ile devam; testler kendi broker'ını boş bir portta başlatır (tests/conftest.py). RQ3a mutlak gecikme değerleri amqtt ile ölçülürse makalede belirtilir. · TALIMAT §3.2.
- 2026-11-18 · paho-mqtt 2.2, Pydantic 2.14. Cihazlar ham veriyi (load_raw, doldurulmamış) yayınlar; eksik ölçüm null; ts naive yerel saat. Heartbeat her 30 simüle dakikada (saatte 2), QoS 0. `seq` her çalıştırmada 0'dan başlar. · TALIMAT §3.2, §8.1.
- 2026-11-18 · Doğrulama: 12 cihaz × 24 simüle saat = 288 telemetri, seq boşluğu 0, 576 heartbeat, kapanışta 12 cihaz `offline`; LWT süreç öldürmeyle test edildi. · tests/integration + gerçek veri duman testi.
- 2026-11-18 · Python 3.11 yerelde kurulu (3.14 de var); proje 3.11/3.12 hedefler. Colab Python sürümü Gün 1'de kontrol edilecek. · TALIMAT §14.3.
