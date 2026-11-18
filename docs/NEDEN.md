# NEDEN — Neyi neden kullandık

Her giriş bileşen yazılırken eklenir (TALIMAT §0.10). Format:

```
### <Seçim>
- Ne:
- Neden:
- Alternatifler ve neden seçilmedi:
- Projede nerede:
- Sunumda tek cümle:
```

### Python
- Ne: Projenin tüm kodunu yazdığımız programlama dili.
- Neden: ML (LightGBM, pandas), IoT (paho-mqtt) ve web (FastAPI) kütüphaneleri tek dilde; Colab'da hazır gelir.
- Alternatifler ve neden seçilmedi: Java/C++ (ML ekosistemi zayıf), Node.js (veri bilimi araçları sınırlı).
- Projede nerede: `src/airq/`
- Sunumda tek cümle: Veri bilimi ve IoT araçlarının hepsi tek dilde olduğu için Python seçtik.

### GitHub Actions CI
- Ne: Her push'ta testleri ve stil denetimini otomatik çalıştıran servis.
- Neden: Bozuk kodun fark edilmeden birikmesini önler; public repoda güven verir.
- Alternatifler ve neden seçilmedi: Elle test (unutulur), harici CI (ek kurulum).
- Projede nerede: `.github/workflows/ci.yml`
- Sunumda tek cümle: Her değişiklikte testler otomatik koşuyor, böylece sonuçlar tekrarlanabilir.

### pre-commit
- Ne: Commit atılmadan önce stil, büyük dosya ve gizli anahtar kontrolü yapan kancalar.
- Neden: Public repoda sır veya 5 MB üstü dosya sızmasını commit anında engeller.
- Alternatifler ve neden seçilmedi: Sadece CI (hata geç yakalanır, geçmişe girer).
- Projede nerede: `.pre-commit-config.yaml`
- Sunumda tek cümle: Hatalı ya da gizli bilgi içeren dosya daha commit anında engelleniyor.

### Beijing Multi-Site veri seti (UCI #501)
- Ne: 12 Pekin istasyonunun 4 yıllık saatlik hava kalitesi ve meteoroloji kaydı.
- Neden: (1) Gerçek ölçüm verisi, fiziksel sensörümüz yok. (2) 12 istasyon komşu bilgisi ablasyonunu mümkün kılıyor. (3) Literatürde sızıntısız sonuçlar var, karşılaştırılabilir [R13][R14].
- Alternatifler ve neden seçilmedi: Kendi sensör verimiz yok; sentetik veri gerçekçi kirlilik olaylarını (haze) taşımaz.
- Projede nerede: `src/airq/data/`, `scripts/download_data.py`
- Sunumda tek cümle: Gerçek ölçümleri sanal cihazlarla yeniden oynatıyoruz; saha çalışması iddiamız yok.

### Kronolojik split ve sızıntı önlemleri
- Ne: Veriyi rastgele değil zamana göre ayırıyoruz (train 2013-03 → 2015-08, val 2015-09 → 2016-02, test 2016-03 → 2017-02).
- Neden: Gerçek sistem geleceği bilmez. Rastgele bölme ve tüm veride ölçekleme R²≈0,99 gibi şişirilmiş sonuçlar verir [R13][R16]. Hedef zamanı sonraki bölüme düşen satırlar atılır; eksik doldurma yalnızca geçmişe bakar (ffill, en çok 3 saat).
- Alternatifler ve neden seçilmedi: Rastgele K-fold (geleceği eğitime sokar), çift yönlü interpolasyon (gelecekten bilgi sızdırır).
- Projede nerede: `src/airq/data/splits.py`, `clean.py`, `tests/unit/test_splits.py`, `test_clean.py`
- Sunumda tek cümle: Model, test döneminde hiç görmediği geleceği tahmin ediyor; sızıntıyı testlerle engelledik.

### Epizot etiketleme (haze ve aşım olayları)
- Ne: PM2.5 eşiğini (75 ve 150 µg/m³) aşan ardışık saatleri "olay", 8+ istasyonun aynı anda 150'yi aştığı ≥6 saati "bölgesel haze" olarak işaretliyoruz.
- Neden: Erken uyarının başarısını saat bazında değil olay bazında (yakalandı mı, kaç saat önce) ölçebilmek için.
- Alternatifler ve neden seçilmedi: Yalnızca saat bazlı sınıflandırma (kısa kesintiler olayı bölüp sayıyı şişirir).
- Projede nerede: `src/airq/data/episodes.py`
- Sunumda tek cümle: Uyarının değerini "olayı kaç saat önceden haber verdi" ile ölçüyoruz.
