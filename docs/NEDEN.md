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
