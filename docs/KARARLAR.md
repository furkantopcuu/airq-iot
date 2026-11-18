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
- 2026-11-18 · Python 3.11 yerelde kurulu (3.14 de var); proje 3.11/3.12 hedefler. Colab Python sürümü Gün 1'de kontrol edilecek. · TALIMAT §14.3.
