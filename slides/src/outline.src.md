# Slayt iskeleti: 14 slayt, 13 dakika + 5 dakika soru

Süre: 12-15 dakika + 5 dakika soru (TALIMAT §12.0). Başlıklar birer bulgu cümlesidir; içindeki her sayı
`paper/numbers.tex` makrosundan gelir (bu dosya `slides/src/outline.src.md`'den üretilir, elle düzenlenmez).
Şekiller reports/figures klasöründeki PNG dosyalarıdır. Her teknik slaytta bir **Neden?** kutusu vardır: 1-2 cümle ve mümkünse bir sayı.

| # | Slayt | Süre |
|---|---|---|
| 1 | Başlık | 0,3 |
| 2 | Problem | 0,7 |
| 3 | Sorular ve katkılar | 0,7 |
| 4 | Mimari | 1,0 |
| 5 | MQTT tasarımı ve edge | 1,2 |
| 6 | Veri ve sızıntısız değerlendirme | 0,8 |
| 6a | Neyi neden kullandık | 0,8 |
| 7 | Canlı demo | 3,5 |
| 8 | RQ1: komşu bilgisi ve ufuk | 0,8 |
| 9 | RQ2: erken uyarı | 0,8 |
| 10 | RQ3: ağ ve veri kalitesi | 1,2 |
| 10a | Ölçümün bulduğu kusur | 0,5 |
| 11 | Sınırlamalar | 0,4 |
| 12 | Sonuç ve gelecek çalışma | 0,4 |
| 13 | Sorular | 5 (soru-cevap) |

Toplam: yaklaşık 13,1 dakika (demo dahil) + soru-cevap.

---

## 1. IoT tabanlı hava kalitesi izleme: tahmin ve erken uyarı, ağ ve veri kalitesi altında
- Orhan Akbaba, Furkan Topçu: Bilgisayar Mühendisliği, İstanbul Medeniyet Üniversitesi
- Ders: Nesnelerin İnterneti
- Şekil: yok (kapakta mimari şemasının küçük hâli isteğe bağlı: `reports/figures/architecture.png`)

## 2. PM2.5'i önceden bilmek, ölçümün ağdan sağlıklı gelmesine bağlıdır
- PM2.5 izlemesi giderek düşük maliyetli sensör ağlarına dayanıyor [R4][R1]
- Tahmin ve erken uyarı, maruziyeti azaltan kararlar için gerekli [R3]
- Sensörler bozulur (kayma, takılı kalma, ani sıçrama) [R22][R21]; mesajlar kaybolur, gecikir, bir cihaz susar
- Çoğu çalışma temiz, arşivlenmiş veride model karşılaştırır: ölçümü taşıyan IoT hattı ölçülmez
- **Neden bu soru?** Model iyi olsa bile hat bozulursa uyarı çalışır mı? Bunu aynı düzenekte ölçen bir çalışma bulamadık (taramamızda).

## 3. Dört soru, üç katkı: tahmini ve IoT hattını aynı düzenekte ölçtük
- RQ1 tahmin: komşu istasyonlar 1/6/24 saatte ne kadar yardım eder? RQ2 erken uyarı: ne kadar önceden, ne doğrulukla?
- RQ3 dayanıklılık: kayıp, gecikme, kopan cihaz ve hatalı girdi tahmini ne kadar bozar; edge bunu ne kadar engeller?
- RQ4 belirsizlik: tahmin aralıkları kalibre mi?
- K1 sızıntısız çok ufuklu tahmin ve komşu ablasyonu; K2 tahmin tabanlı erken uyarı ve öncül süre; K3 ağ ve veri kalitesinin tahmine etkisi

## 4. {{nDataStations}} sanal cihaz gerçek ölçümleri MQTT ile akıtır; kenarda doğrulanır, tahmine ve uyarıya dönüşür
- Şekil: `../reports/figures/architecture.png`
- Cihaz (LWT, heartbeat, `seq`) → broker → edge doğrulama → ingest (SQLite) → tahmin + uyarı → API → pano
- Komut kanalı (`cmd`/`ack`) aynı MQTT hattından cihazı, ağı ve edge filtresini canlı değiştirir
- **Neden?** Fiziksel sensörümüz yok ama gerçek haze olayları var: gerçek kayıtlı ölçümleri sanal cihazlarla yeniden oynatıyoruz. Bu saha çalışması değil, iz sürümlü emülasyon.

## 5. QoS 1 ve idempotent kayıt: mesaj kaybolmaz, tekrar zararsız (ölçülen tekrar oranı {{nDupRateMax}})
- MQTT: sensör için hafif, yayıncı ile abone birbirini tanımaz, QoS/LWT/retained hazır [R7]
- QoS 1 "en az bir kez": tekrar gelirse `(istasyon, ts)` anahtarıyla idempotent kayıt
- LWT ve retained durum: cihaz çökerse broker `offline` duyurur
- Edge: 5 kural (eksik, aralık dışı, ani sıçrama, takılı kalma, PM2.5 ≤ PM10); filtre açıkken güvenilmez değer `null`
- **Neden?** QoS 0'da ağ kaybında mesaj sessizce gider ve tahmin eksik veriyle çalışır. QoS 1'in bedeli olan tekrar, kayıt anında zararsız: tüm koşularda tekrar oranı {{nDupRateMax}}.

## 6. Kronolojik bölme ve sızıntı önlemleri: R² 1 saatte {{nRTwoMtwobHOne}}, 24 saatte {{nRTwoMtwobHTwentyFour}}
- "R²=0,99" şüphelidir: rastgele bölme ve tüm veride ölçekleme sızıntısı sonucu şişirir [R13][R17][R16]
- Bölme: eğitim {{nTrainStart}}-{{nTrainEnd}}, doğrulama {{nValStart}}-{{nValEnd}}, test {{nTestStart}}-{{nTestEnd}}; uydurma yalnızca eğitimde, seçim yalnızca doğrulamada
- Eksik doldurma yalnızca geçmişe bakar (en çok {{nFfillLimit}} saat); hiçbir özellik gelecekten bilgi taşımaz; önlemler testlerle denetlenir
- Ufuk uzadıkça R² düşer: dürüst bir sonuç (persistence 24 saatte R² {{nRTwoPersistHTwentyFour}})
- **Neden?** Gerçek sistem geleceği bilmez. Test dönemi her protokol için bir kez değerlendirildi (tek istisna makalede açıkça yazılı: yeniden üretilebilirlik düzeltmesi).

## 6a. Neyi neden kullandık
| Teknoloji | Neden | Alternatif ve neden seçilmedi |
|---|---|---|
| MQTT | sensör için hafif, yayıncı-abone, cihaz kopmasını kendisi bildirir | HTTP/CoAP: istek-yanıt, kopmayı bildirmez |
| QoS 1 + idempotent kayıt | kayıpta mesaj gitmez, tekrar zararsız | QoS 0 kayıp; QoS 2 gereksiz yük |
| LWT + retained durum | çöken cihazı broker duyurur | yalnızca heartbeat zaman aşımı: yavaş, belirsiz |
| Edge veri kalitesi | bozuk değer tahmini bozar; kaynakta temizle | sunucuda doğrulama: hatalı veri ağdan geçer |
| SQLite (WAL) | saatte {{nDataStations}} satırlık yük; kurulum yok | PostgreSQL/TimescaleDB: bu ölçekte fayda yok |
| LightGBM | tabloda hızlı, eksik değer, SHAP ile açıklanabilir | LSTM/GNN: daha çok ayar, koordinat yok |
| Komşu özellikleri | kirlilik şehirde yayılır; ablasyonla ölçtük | GNN: koordinat ve süre maliyeti |
| Kronolojik bölme | gelecek sızıntısı olmasın | rastgele K-fold |
| F2 ve δ payı | olay kaçırmak yanlış alarmdan pahalı | F1, sabit eşik (δ=0) |
| Optuna (TPE) | az denemede iyi ayar; {{nOptunaTrials}} deneme yeterli (10→20 kazanç %{{nTuneGainTenTwenty}}) | ızgara: pahalı; elle: tekrar edilemez |
- Her satırın gerekçesi `docs/NEDEN.md`'de.

## 7. Canlı demo: tek komut, planlı akış yaklaşık 3 dakika
- Komut: `python -m scripts.demo` (broker, edge, ingest, tahmin, filo, API ve pano; Ctrl+C hepsini kapatır)
- A) Planlı akış: `gercek_haze_replay` (uyarı epizottan {{nScnHazeLead}} saat önce), `sensor_takilmasi` (edge önce kapalı sonra açık), `cihaz_kopmasi` (LWT, kartlar offline), `ag_bozulmasi` (teslim oranı {{nScnDelivery}}, p95 {{nScnLatencyP}} ms)
- B) Serbest test (jüri seçer): istasyon + değer, örneğin "Dongsi PM2.5 6 saatte 300'e çıksın"; geçersiz değer reddedilir; "Sıfırla" temiz duruma döner
- Yedekler: `python -m scripts.demo --offline` (kayıtlı koşu, broker yok), `docs/assets/demo_dashboard.gif`, `slides/demo_screens/`, `slides/demo_backup.mp4`
- **Neden?** Komut MQTT'den gider (`cmd`/`ack`): kontrol yolu da IoT'nin kendi kanalı; her senaryonun hipotezi önceden yazıldı ({{nScnConfirmed}} / {{nScnTotal}} kontrol doğrulandı, {{nScnRefuted}} çürütüldü ve olduğu gibi raporlandı).

## 8. Komşu istasyonlar 1 ve 6 saatte RMSE'yi %{{nAblKelevenHOne}} ve %{{nAblKelevenHSix}} düşürür, 24 saatte işe yaramaz
- Şekil: `../reports/figures/rq1_horizon.png`, `../reports/figures/rq1_ablation_loso.png`
- Persistence'a göre RMSE iyileşmesi (M2b): %{{nImprMtwobHOne}} (1 sa), %{{nImprMtwobHSix}} (6 sa), %{{nImprMtwobHTwentyFour}} (24 sa)
- Görülmemiş istasyonda (LOSO) iyileşme %{{nLosoMeanHOne}} (istasyon eğitimdeyken %{{nLosoInSampleHOne}}): genelleme korunuyor
- Olumsuz sonuç: aşırı olaylarda (> {{nExtPNinetyFive}} µg/m³) model düşük tahmin eder ve 24 saatte persistence'ın gerisinde kalır (RMSE {{nExtRmseMtwobHTwentyFour}} karşı {{nExtRmsePersistHTwentyFour}})
- **Neden?** Kirlilik dalgası şehirde istasyondan istasyona yayılır; bunu iddia etmedik, ablasyonla ölçtük: kısa ufukta anlamlı kazanç, 24 saatte yok.

## 9. Uyarı 1 ve 6 saatte işe yarar (F2 {{nWarnFtwoMtwobHOne}} ve {{nWarnFtwoMtwobHSix}}), 24 saatte persistence'ın gerisinde
- Şekil: `../reports/figures/rq2_haze_example.png`, `../reports/figures/rq2_pr_lead.png`
- Kural: tahmin > eşik − δ; δ doğrulamada F2'yi (β={{nBeta}}) en büyük yapacak şekilde seçilir; uyarı sonrası {{nCooldownH}} saat soğuma
- Test yılında {{nEventsHundred}} aşım olayı ve {{nEventsHaze}} bölgesel haze epizodu; 24 saatte M2b {{nHazeCaughtMtwobHTwentyFour}} haze epizodu yakalar, persistence {{nHazeCaughtPersistHTwentyFour}}
- q90 tabanlı uyarı 24 saatte recall'u {{nQwRecMtwobHTwentyFour}}'den {{nQwRecQnineHTwentyFour}}'e çıkarır, yanlış alarm {{nQwFaMtwobHTwentyFour}}'den {{nQwFaQnineHTwentyFour}}'e yükselir
- **Neden?** Olay kaçırmak (sağlık riski) yanlış alarmdan pahalı: F2 duyarlılığa ağırlık verir; δ payı modelin tepeleri küçük tahmin etmesini telafi eder. δ yalnızca doğrulamada seçilir.

## 10. %20 kayıpta 1 saatlik hata +{{nDmgTwenty}} µg/m³; edge filtresi hatalı girdinin zararının %{{nRobRecPersistHOne}} ve %{{nRobRecMtwobHOne}}'ini geri alır
- Şekil: `../reports/figures/rq3a_system.png`, `../reports/figures/rq3b_damage.png`
- Teslim oranı yapılandırılan kayıpla örtüşür ({{nPdrTwenty}} @ %20 kayıp); cihazdan veritabanına medyan gecikme {{nLatDbMedian}} ms
- {{nSpeedSlow}}× hızda tahmin servisi %20 kayıpta {{nRunsTwenty}} koşunun {{nBehindTwenty}}'ünde geride kalır (medyan gecikme {{nWarnLatBehind}} s)
- Edge filtresi basit modele (persistence) çok, öğrenilmiş modele (M2b) daha az yardım eder; eşleştirilmiş koşularda spike altında 1 saatte yardım eder, 6 saatte zarar verebilir
- **Neden?** Ağ bozulması uygulama katmanında emüle edildi (kontrollü, tohumlu, tekrarlanabilir); tüm {{nRunsTotal}} koşu ayrı süreçlerle ve ayrı Mosquitto ile alındı.

## 10a. Ölçüm bir tasarım kusurunu buldu: çevrimdışı cihaz beklemesi {{nOffLatOneBefore}} s'den {{nOffLatOneAfter}} s'ye indi
- Neden: tahmin servisi eksik bir istasyonu {{nWaitMs}} ms bekliyordu; kalıcı çevrimdışı cihaz her saat boşa bekletiyordu
- Düzeltme: retained `offline` durumunu gören servis kısa bir ek süreden sonra beklemeyi bırakır; tam ağda gecikme {{nOffLatFullAfter}} s (değişmedi), hiçbir koşu geride kalmadı
- Düzeltme mesaj kaybında yardımcı olmaz: kaybolan mesaj hiçbir şey duyurmaz
- **Neden?** Sistemi ağ koşullarıyla birlikte ölçmeden bu kusur görünmezdi: bu çalışmanın K3 katkısının somut örneği.

## 11. Sınırlamalar: emülasyon, referans veri, sentetik hata, tek şehir, güvenlik yok
- İz sürümlü emülasyon, saha çalışması değil; referans istasyon verisi, düşük maliyetli sensör değil
- Hatalı girdi sentetik; tek şehir ve tek test yılı; ağ emülasyonu uygulama katmanında, tek makine
- Komut kanalı kimlik doğrulamasız (yalnızca yerel); gerçek dağıtım TLS ve erişim denetimi ister
- Canlı senaryolar birer kez, eşleştirilmiş koşular {{nAbSpikeWindows}} pencere: istatistik değil, gösterim

## 12. Sonuç: tahmin ve uyarı IoT hattıyla birlikte ölçülür; 1-6 saatte işe yarar, uzun ufukta ve aşırı olaylarda yetersizdir
- LightGBM + komşu: persistence'a göre %{{nImprMtwobHOne}} / %{{nImprMtwobHSix}} / %{{nImprMtwobHTwentyFour}}; uyarı 1-6 saatte işe yarar
- Kayıp ve çevrimdışı cihaz gerçek zaman davranışını belirler; ölçüm bir kusuru buldu ve düzelttirdi
- Gelecek çalışma: gerçek düşük maliyetli sensörlerle saha testi (PMS5003 + ESP32) [R20][R1]; TLS ve erişim denetimi; GNN [R12]; aşırı olaylar için asimetrik amaç; anomali tespiti
- Kod, sonuçlar ve makale: github.com/furkantopcuu/airq-iot (sürüm v0.3.0)

## 13. Sorular
- Yedek slaytlar: B1-B7 aşağıda

---

## B1. Hiperparametreler: {{nOptunaTrials}} Optuna denemesi yeterli (10. ile 20. deneme arası ortalama kazanç %{{nTuneGainTenTwenty}})
- Şekil: yok; tablo `reports/tables/rq1_tuning.csv`, `reports/tables/rq1_tuning_convergence.csv`
- Seçim yalnızca doğrulamada; test'e bakılmadı

## B2. Aşırı olay tablosu: hedef > {{nExtPNinetyFive}} µg/m³ iken model düşük tahmin eder
- Tablo: `paper/tables/rq1_extreme.md`; ortalama hata (gerçek eksi tahmin) 24 saatte {{nExtBiasMtwobHTwentyFour}} µg/m³

## B3. LOSO: model {{nLosoStations}} istasyonun {{nLosoBetterHOne}} / {{nLosoBetterHSix}} / {{nLosoBetterHTwentyFour}}'inde görülmeden de persistence'ı geçer (1/6/24 sa)
- Tablo: `paper/tables/rq1_loso.md`

## B4. RQ4: ham aralık kapsaması {{nCovRawHOne}}, kalibre {{nCovCalHOne}} (1 sa); aşırı hedeflerde 24 saatte yalnızca {{nCovExtCalHTwentyFour}}
- Şekil: `../reports/figures/rq4_uncertainty.png`; tablo: `paper/tables/rq4_coverage.md`

## B5. Literatür karşılaştırması: ağ ve veri kalitesi etkisini tahminle birlikte ölçen çalışma bulamadık (taramamızda)
- Tablo: makale Tablo I (`paper/main.tex`)

## B6. Senaryo Kontrol: {{nScnConfirmed}} / {{nScnTotal}} hipotez doğrulandı, {{nScnRefuted}} çürütüldü
- Şekil: `../reports/figures/scenarios_ab.png`, `../reports/figures/scenarios_edge.png`; tablo: `paper/tables/scenarios.md`

## B7. Güvenlik: yalnızca yerel; üç açık bulundu ve düzeltildi
- Loopback bağlantılar, Host/Origin denetimi, HTML kaçışlama; `SECURITY.md`, `tests/unit/test_security.py`
