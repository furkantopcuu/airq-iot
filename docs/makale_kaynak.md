# Makale kaynakları ve doğrulama kaydı

TALIMAT §11.5 gereği: ders makalesi, kaynakça doğrulaması ve Ek A'ya göre değişiklikler. Tarih: 2026-11-21 (Gün 17).

## 1. Ders makalesi

- **Kullanıcıdan alınan bilgi:** Hoca örnek olarak *"Air-quality sensor networks + ML"* konulu bir makale gösterdi; dersin adı *Nesnelerin İnterneti*.
- **Künye / PDF: yok.** Kullanıcı (2026-11-21) doğruladı: hoca makalenin yalnızca adını verdi, künye ya da PDF vermedi ve elde yok. Bu yüzden makalenin içeriğini tahmin edip yazmıyoruz (uydurma künye kabul edilemez) ve karşılaştırma tablosuna eklemiyoruz. Hoca ileride künye veya PDF verirse bu dosyaya künye, yöntem özeti ve bizim çalışmamızdan farkı eklenir.
- **Merkezî atıf:** Bu konuyu kapsayan iki derleme Ek A'da var ve makalede merkezî atıf olarak kullanıldı: **[R1]** Concas vd. (düşük maliyetli açık hava sensörleri ve kalibrasyon derlemesi) ve **[R2]** Garcia vd. (IoT tabanlı hava kalitesi izleme ve yapay zekâ derlemesi). Ders makalesi bunlardan biriyse künyesi aynen kalır; değilse ayrıca eklenir.

## 2. Kaynakça doğrulama yöntemi

`paper/refs.bib`, Ek A'dan üretildi. Her DOI'li kayıt için künye, yayıncı kayıt sisteminden (Crossref REST API) alınıp Ek A ile karşılaştırıldı; veri seti DataCite'tan, arXiv kayıtları arXiv API'sinden doğrulandı.

Notlar:
- `doi.org` çözümleyicisi bu makineden "DOI Not Found" döndürdü (yönlendirme sorunu, DOI'lerin kendisi geçerli); bu yüzden Crossref doğrudan kullanıldı. 22 DOI'nin hepsi Crossref'te bulundu.
- dblp, otomatik istemcilere bot doğrulaması gösterdi; **aşılmaya çalışılmadı**. OpenAlex'in NeurIPS sayfa numaraları kendi içinde çelişkili çıktı (aynı makale için farklı kayıtlar), bu yüzden güvenilmedi.
- Doğrulanamayan alan **uydurulmadı, atlandı** (aşağıda R15, R26).

## 3. Kayıt kayıt durum

| # | Durum | Doğrulama sonucu / yapılan değişiklik |
|---|---|---|
| R1 | ✓ | Crossref: ACM TOSN 17(2), 1–44, 2021. Alt başlık ("A Survey and Critical Analysis") Crossref'te ayrı alanda; birleştirildi. 8 yazar: ilk yazar + "ve ark." |
| R2 | ✓ | *Artif. Intell. Rev.* 58(9), Art. 275, 2025. |
| R3 | ✓ | *Artif. Intell. Rev.* 56(9), 10031–10066, 2023. |
| R4 | ✓ | *Environ. Int.* 116, 286–299, 2018. 26 yazar: ilk yazar + "ve ark.". |
| R5 | ✓ | *Sensors* 18(9), 3021, 2018. Tam başlık DOI'den alındı (Ek A'nın "tam başlığı kontrol et" notu kapandı). |
| R6 | ✓ | *Complex Intell. Syst.* **7(6), 2923–2947, 2021** (Ek A'da cilt/sayfa eksikti: tamamlandı). |
| R7 | ✓ | **DOI eklendi: 10.1145/3292674** (ACM CSUR 51(6), 2019). Ek A yalnızca arXiv:1804.01747 veriyordu. |
| R8 | ✓ | *Proc. R. Soc. A* 473(2205), 20170457, 2017. Veri seti DataCite'ta doğrulandı: "Beijing Multi-Site Air Quality", Song Chen, UCI ML Repository, 2017, doi:10.24432/C5RK5G (anahtar `R8d`). |
| R9 | ✓ | *Environ. Pollut.* 231, 997–1004, 2017. |
| R10 | ✓ | *Sensors* 18(7), 2220, 2018. |
| R11 | ✓ | KDD 2018, 965–973. |
| R12 | ✓ | SIGSPATIAL 2020 (28th Int. Conf. on Advances in GIS), 163–166. |
| R13 | ön baskı | arXiv:2607.07279 doğrulandı: Yusheng Wang, Ruiyan Du; ilk sürüm 2026-07-08, son güncelleme 2026-08-25. arXiv kaydında dergi künyesi veya DOI **yok** → hakemli sürüm bulunamadı; **ön baskı olarak** anıldı (§11.5-3). |
| R14 | ✓ | *Environ. Monit. Assess.* 198(9), Art. 938, 2026. |
| R15 | doğrula | LightGBM (NeurIPS 2017). Sayfa numarası güvenilir kaynaktan doğrulanamadı → **sayfa verilmedi**; cilt 30, 2017, yazarlar "Ke, Guolin ve ark." (OpenAlex: 8 yazar, ilk üçü Ke, Meng, Finley). |
| R16 | ✓ | *Mach. Learn.* 109(11), 1997–2028, 2020. |
| R17 | ✓ | arXiv:2104.03226 ve **IEEE I2CT 2021, 1–8, doi:10.1109/I2CT51068.2021.9418215** (Crossref; Ek A'nın "başlık doğrula" notu kapandı). |
| R18 | ✓ (düzeltildi) | **Ek A'daki yazar adları yanlıştı.** Crossref: Vanessa E. Alvear-Puertas, Yadira A. Burbano-Prado, Paul D. Rosero-Montalvo, Pınar Tözün, Fabricio Marcillo, Wilmar Hernandez (Ek A: "J. … P. …"). *Sensors* 22(18), 7015, 2022. |
| R19 | ✓ | *J. Supercomput.* 80(7), 9961–9985; yıl **2024** (basılı sayı; çevrimiçi 2023-12-19). Yazarlar: Y. Chan, E. Kristiani, H. Fathoni, C. Chen, C. Yang. |
| R20 | ✓ | *Atmos. Meas. Tech.* 14(6), 4617–4637, 2021. |
| R21 | ✓ | *ACM TOSN* 6(3), 2010. Alt başlık birleştirildi. |
| R22 | ✓ | *ACM TOSN* 5(3), 2009 (10 yazar: ilk yazar + "ve ark."). |
| R23 | kullanılmadı | Kapalı alan CO₂ (P2) görevi yapılmadı; `refs.bib`'e **girmedi**. |
| R24 | ✓ | DM, *J. Bus. Econ. Stat.* 13(3), 253–263, 1995, **doi:10.1080/07350015.1995.10524599**. |
| R25 | ✓ | HLN, *Int. J. Forecast.* 13(2), 281–291, 1997, **doi:10.1016/S0169-2070(96)00719-4**. |
| R26 | doğrula | SHAP (NeurIPS 2017); arXiv:1705.07874 yazarlar ve başlık doğrulandı. Sayfa numarası doğrulanamadı → **sayfa verilmedi**; cilt 30, 2017. |
| R27 | ✓ | *Econometrica* 46(1), 1978, doi:10.2307/1913643. |

## 4. Gün 18'de yapılacaklar

1. Ders makalesi: künye/PDF yok (kullanıcı doğruladı, bölüm 1); yapılacak bir şey yok.
2. R15 ve R26 için NeurIPS bildiri sayfa numaralarını resmî bildiri sayfasından (papers.nips.cc) doğrula; doğrulanırsa `refs.bib`'e ekle. Doğrulanamazsa sayfasız kalır.
3. R13'ün hakemli sürümü yayımlandı mı tekrar kontrol et (§11.5-3).
4. Sonuç yazımında "bildiğimiz kadarıyla" iddiasını (K3) son kez gözden geçir; literatür taraması güncel mi?
