# Sunum hazırlık rehberi: bilmen gerekenler

Bu belge, sunumda ve soru-cevapta ayakta kalmak için bilmen gerekenleri sade Türkçe ile anlatır. Ezberlemek için
değil, **anlamak** için yazıldı: önce 1. ve 2. bölümü oku, sonra her soruyu kendi cümlelerinle yüksek sesle cevapla,
sonra buradaki cevapla karşılaştır. Sayılar `paper/numbers.tex` makrolarından gelir (makaleyle aynı sayı).

Altın kural: bilmediğin şeye "ölçmedik" ya da "kapsam dışı" de. Uydurma cevap, "bilmiyorum"dan her zaman daha kötüdür.

---

## 1. Projeyi 30 saniyede anlat

> Hava kirliliği (PM2.5) tahmini genellikle temiz, arşivlenmiş veride denenir. Gerçekte ölçüm bir IoT hattından
> geçer ve bu hat bozulur: mesaj kaybolur, cihaz susar, sensör bozuk değer yollar. Biz Pekin'in gerçek
> ölçümlerini ({{nDataStations}} istasyon, {{nDataHours}} saat) {{nDataStations}} sanal cihazla MQTT üzerinden yeniden
> oynattık; kenarda doğruladık, SQLite'a yazdık, LightGBM ile 1, 6 ve 24 saat sonrasını tahmin edip uyarı ürettik.
> Sonra tahminin ve uyarının ağ ve veri kalitesi bozulunca ne kadar bozulduğunu ölçtük.

Dört araştırma sorusu:
- **RQ1:** Komşu istasyonların verisi tahmine ne kadar yardım eder (1/6/24 saat)?
- **RQ2:** Erken uyarı ne kadar önceden ve ne doğrulukla çalışır?
- **RQ3:** Mesaj kaybı, gecikme, kopan cihaz ve hatalı girdi tahmini ne kadar bozar? Edge filtresi bunu ne kadar engeller?
- **RQ4:** Tahmin aralıkları (belirsizlik) güvenilir mi (kalibre mi)?

Sistem zinciri: **cihaz → MQTT broker → edge doğrulama → ingest (SQLite) → tahmin + uyarı → API → pano.** Ters yönde
**komut kanalı** (`cmd`/`ack`) aynı MQTT hattından cihazı, ağı ve edge filtresini canlı değiştirir (Senaryo Kontrol).

Dürüst çerçeve (bunu hep söyle): bu **saha çalışması değil, iz sürümlü emülasyondur**; referans istasyon verisidir, düşük
maliyetli sensör değil.

---

## 2. Kavram sözlüğü (jüri bunları sorabilir)

| Terim | Sade anlamı |
|---|---|
| **PM2.5** | 2,5 mikrondan küçük partikül; sağlığa en zararlı hava kirliliği ölçüsü (µg/m³) |
| **MQTT** | Sensörler için tasarlanmış hafif yayın-abone protokolü: cihaz bir konuya yayınlar, abone olanlar alır; yayıncı ile abone birbirini tanımaz |
| **Broker** | Mesajları dağıtan aracı sunucu (biz Mosquitto kullandık) |
| **QoS 0 / 1 / 2** | Teslim garantisi: 0 = en fazla bir kez (kayıp olabilir), 1 = **en az bir kez** (tekrar olabilir), 2 = tam bir kez (en ağırı) |
| **LWT (Last Will)** | Cihaz habersiz çökerse broker onun yerine "offline" duyurur |
| **Retained mesaj** | Broker son mesajı saklar; yeni gelen abone hemen güncel durumu görür |
| **Idempotent kayıt** | Aynı mesaj iki kez gelse bile veritabanında tek satır kalır (`(istasyon, ts)` anahtarı) |
| **Edge** | Veriyi kaynağa yakın, sunucuya varmadan kontrol eden katman. Bizde 5 kural: eksik değer, aralık dışı, ani sıçrama, takılı kalma, PM2.5 ≤ PM10 |
| **Leakage (sızıntı)** | Modelin eğitimde gelecekten bilgi görmesi; sonuçlar yapay olarak iyi çıkar |
| **Persistence** | "Yarın bugünkü gibi olacak" tahmini (son ölçümü aynen tekrarla). Basit ama güçlü referans |
| **LightGBM** | Karar ağaçlarını art arda ekleyen hızlı bir makine öğrenmesi yöntemi, tablo verisinde çok başarılı |
| **RMSE** | Tahmin hatasının tipik büyüklüğü (µg/m³); küçük = iyi |
| **R²** | Modelin değişimin ne kadarını açıkladığı; 1 = mükemmel, 0 = ortalamayı söylemek kadar, negatif = ondan kötü |
| **Ablasyon** | Bir bileşeni çıkarıp sonuç ne kadar değişiyor diye ölçmek (komşu özellikleri çıkardık) |
| **LOSO** | Leave-one-station-out: bir istasyonu hiç görmeden eğitip o istasyonda test etmek |
| **F2 skoru** | Uyarı kalitesi ölçüsü; kaçırılan olayı yanlış alarmdan daha ağır cezalandırır (β={{nBeta}}) |
| **δ payı** | Uyarı kuralı: tahmin > eşik − δ. Model tepeleri küçük tahmin ettiği için eşiği biraz aşağı çekeriz |
| **q10 / q90** | Alt ve üst nicelik tahmini: "değer %90 olasılıkla bu bandın içinde" gibi belirsizlik aralığı |
| **Kalibrasyon** | Bandın söylediği güven ile gerçek kapsamanın eşleşmesi (hedef 0.80) |
| **Optuna (TPE)** | Hiperparametreleri akıllıca arayan araç; {{nOptunaTrials}} deneme kullandık |
| **Emülasyon** | Gerçek kayıtlı ölçümlerin sanal cihazlarla canlıymış gibi oynatılması |

---

## 3. On soru: kendi cümlelerinle cevapla, sonra karşılaştır

Her soruda: **Sade anlatım** (anlamak için), **Jüriye söyle** (2-3 cümle), **Tuzak** (kaçınılacak ifade).

### Soru 1. Neden MQTT? HTTP ya da CoAP neden değil?
**Sade anlatım.** Sensör küçük, pille çalışır, ağı kesintilidir. MQTT bunun için tasarlanmış: mesaj başlığı çok küçük,
cihaz yalnızca broker'a bağlanır, kimin dinlediğini bilmez. Üstüne QoS, LWT ve retained hazır gelir. HTTP istek-yanıt
modelidir: sunucu cihaza kendiliğinden haber veremez, cihaz koptuğunda kimse duymaz. CoAP hafiftir ama UDP tabanlıdır
ve ekosistemi daha dardır [R7]. Hava kalitesi mimarilerinin çoğu da MQTT kullanır [R18][R19].

**Jüriye söyle.** "MQTT sensör için tasarlanmış hafif bir yayın-abone protokolü. QoS, LWT ve retained mesaj hazır
geliyor, cihaz koptuğunda broker bunu kendisi duyuruyor. HTTP'de bunların hiçbiri hazır değil."

**Tuzak.** "MQTT en iyisidir" deme; "bu iş için uygundur ve literatürde yaygındır" de.

### Soru 2. QoS 1 neden? Aynı mesaj iki kez gelirse ne olur?
**Sade anlatım.** Ölçüm kaybolursa tahmin eksik veriyle çalışır. QoS 0'da ağ kopunca mesaj *sessizce* gider. QoS 1
"en az bir kez" teslim eder: gönderen onay (PUBACK) alana kadar tekrar dener, bu yüzden **aynı mesaj iki kez gelebilir**.
Bunun çözümü kayıt tarafında: ingest `(istasyon, ts)` anahtarıyla yazar, aynı mesaj ikinci kez satır eklemez
(idempotent). Ölçtük: tüm koşularda tekrar oranı en çok {{nDupRateMax}}. QoS 2 "tam bir kez" der ama el sıkışma yükü
fazladır; saatlik veri için gereksiz.

**Jüriye söyle.** "QoS 1 kaybı önlüyor, bedeli tekrar; tekrarı kayıt anında idempotent yazımla zararsız yapıyoruz.
Ölçtüğümüz tekrar oranı {{nDupRateMax}}."

**Tuzak.** "QoS 1 tekrarı önler" deme; **tekrara izin verir**, biz kayıtta eleriz.

### Soru 3. Leakage'ı nasıl önlediniz?
**Sade anlatım.** Leakage'ın klasik örneği: veriyi rastgele bölmek ya da ölçeklemeyi tüm veride yapmak. O zaman model
"geleceği" görmüş olur ve R² 0.99 gibi şüpheli bir sayı çıkar [R13][R17][R16]. Biz:
- **Kronolojik bölme:** eğitim {{nTrainStart}}–{{nTrainEnd}}, doğrulama {{nValStart}}–{{nValEnd}}, test {{nTestStart}}–{{nTestEnd}}.
- **Uydurma (imputation/ölçekleme) yalnızca eğitimde**, model/eşik **seçimi yalnızca doğrulamada**.
- Eksik doldurma yalnızca geçmişe bakar (en çok {{nFfillLimit}} saat); gelecekteki PM10 kullanılmaz.
- Hedef zamanı bir sonraki bölmeye düşen satırlar atılır.
- Hepsi birim testleriyle denetlenir.
Kanıt: R² 1 saatte {{nRTwoMtwobHOne}}, 24 saatte {{nRTwoMtwobHTwentyFour}}. Şişirilmiş sonuçlarda uzun ufukta da yüksek R² beklenirdi.

**Jüriye söyle.** "Kronolojik bölme, uydurma yalnızca eğitimde, seçim yalnızca doğrulamada, ve bunlar testlerle
denetleniyor. İyi bir işaret: R² ufuk uzadıkça {{nRTwoMtwobHOne}}'dan {{nRTwoMtwobHTwentyFour}}'ye düşüyor; şişirilmiş sonuç böyle olmaz."

**Tuzak.** "Sızıntı kesinlikle yok" deme; "bildiğimiz yolları kapattık ve testle denetledik" de.

### Soru 4. Neden LightGBM? LSTM/GNN neden değil?
**Sade anlatım.** Elimizdeki veri **tablo** (saat, geçmiş değerler, komşu istasyonlar). Bu tür veride ağaç modelleri
sızıntısız protokolde çok rekabetçidir [R13][R14]. LightGBM CPU'da dakikalar içinde eğitilir, eksik değeri kendisi
işler, SHAP ile açıklanır. LSTM/GNN daha çok ayar ve süre ister; GNN'in asıl gücü istasyon koordinatlarıyla çalışır, bizde
koordinat yok [R9][R10][R11][R12]. Komşu bilgisinin değerini ablasyonla ölçtük: RMSE 1 saatte %{{nAblKelevenHOne}}, 6 saatte
%{{nAblKelevenHSix}} düşüyor, 24 saatte kazanç yok.

**Jüriye söyle.** "Tablo verisinde LightGBM hızlı, açıklanabilir ve literatürde güçlü. GNN ile karşılaştırma yapmadık,
bunu gelecek çalışmaya bıraktık. Komşu bilgisinin etkisini ablasyonla ölçtük."

**Tuzak.** "LSTM/GNN daha kötüdür" deme; **denemedik**.

### Soru 5. Persistence neden bu kadar güçlü? Modeliniz zayıf mı?
**Sade anlatım.** PM2.5 saat saat yavaş değişir; "1 saat sonra şimdiki gibi" demek zaten çok iyi: persistence'ın R²'si
1 saatte yüksek (RMSE {{nRmsePersistHOne}}). Bu yüzden 1 saatte kazanç küçük kalır; asıl fark uzun ufukta açılır.
Persistence 24 saatte R² {{nRTwoPersistHTwentyFour}}'e düşer (ortalamayı söylemekten bile kötü). Bizim modelin
persistence'a göre RMSE iyileşmesi: **%{{nImprMtwobHOne}} (1 sa), %{{nImprMtwobHSix}} (6 sa), %{{nImprMtwobHTwentyFour}} (24 sa).**
Literatürde de fark küçüktür [R13].

**Jüriye söyle.** "Güçlü bir referansı yendik, %{{nImprMtwobHOne}}'den %{{nImprMtwobHTwentyFour}}'ya kadar. Zayıf referansa
karşı büyük sayı almak kolaydı; biz bilerek güçlü olanı seçtik ve dürüstçe raporladık."

**Tuzak.** Kazanç küçük diye özür dileme; bunu *dürüstlük* olarak sun.

### Soru 6. Aşırı olaylarda (haze) model neden zorlanıyor?
**Sade anlatım.** Model karesel hatayı küçültür; bu onu ortalamaya çeker. Eğitimde çok yüksek değerler azdır, model
onları az görür. Sonuç: aşırı olaylarda (> {{nExtPNinetyFive}} µg/m³) **düşük tahmin** ediyor; ortalama hata 24 saatte
{{nExtBiasMtwobHTwentyFour}} µg/m³ (gerçek eksi tahmin). 24 saatte RMSE {{nExtRmseMtwobHTwentyFour}}, persistence'ınki
{{nExtRmsePersistHTwentyFour}}: persistence'ın gerisinde. Nedenini ayrıca izole etmedik. Hafifletme: q90 tabanlı
uyarı recall'u {{nQwRecMtwobHTwentyFour}}'den {{nQwRecQnineHTwentyFour}}'e çıkarır; bedeli yanlış alarmdır
({{nQwFaMtwobHTwentyFour}} → {{nQwFaQnineHTwentyFour}}).

**Jüriye söyle.** "Bu olumsuz bir bulgu ve açıkça yazdık. Model aşırı olaylarda düşük tahmin ediyor; q90 ile uyarının
duyarlılığı artıyor ama yanlış alarm da artıyor. Asimetrik amaç fonksiyonu gelecek çalışma."

**Tuzak.** Nedeni kesinmiş gibi anlatma; "olası neden, ayrıca sınamadık".

### Soru 7. Edge'de neden tahmin yapmıyorsunuz?
**Sade anlatım.** Bazı çalışmalar tahmini edge'de yapıyor [R6]. Biz edge'de yalnızca **veri kalitesini** doğruluyoruz.
Tahmini sunucuda yapıyoruz çünkü (a) komşu istasyonların verisi sunucuda birleşiyor (komşu özellikleri 1-6 saatte kazanç sağladı), tek bir cihaz komşuları görmez,
(b) modeli onlarca cihaza dağıtıp güncellemek zor. Edge'de tahmin gelecek çalışma.

**Jüriye söyle.** "Komşu bilgisi 1-6 saatte kazanç sağladı ve o ancak sunucuda birleşiyor; bu yüzden tahmin sunucuda,
edge yalnızca veriyi doğruluyor."

**Tuzak.** "Edge'de tahmin olmaz" deme; "tercih ettik, gelecek çalışma" de.

### Soru 8. Test setini kaç kez kullandınız?
**Sade anlatım.** Her protokol için **bir kez**. Tek istisna: M2a modelinin 1 saatlik Optuna çalışması yeniden
üretilemediği için temiz yeniden koşuldu ve test ikinci kez hesaplandı. Seçim yine doğrulamada kaldı; iki değer de
{{nRmseMtwoaHOne}} µg/m³'e yuvarlanıyor, hiçbir bulgu değişmedi. Bu makalede açıkça yazılı.

**Jüriye söyle.** "Test dönemine her protokolde bir kez baktık. Tek istisnayı, nedenini ve sonucun değişmediğini
makalede yazdık."

**Tuzak.** Bu istisnayı saklama; sen söylemezsen jüri bulduğunda kötü görünür, sen söylersen dürüstlük puanı.

### Soru 9. Sonuçlar tekrar üretilebilir mi?
**Sade anlatım.** `python -m scripts.run_all` ham veriden her şeyi (tablolar, şekiller, makale sayıları) üretir. Tam
yeniden üretimde 9 Optuna çalışmasının 8'i birebir çıktı; dokuzuncusunun kesintiye uğramış bir denemeden saptığı bulundu
ve düzeltildi (yukarıdaki istisna). RQ2 ve RQ3b birebir. Makaledeki her sayı `reports/` dosyasından makro olarak
gelir, ayrı testler sayıları bağımsız yeniden hesaplar, CI her değişiklikte çalışır.

**Jüriye söyle.** "Tek komutla ham veriden her şeyi üretiyor; makaledeki sayılar elle yazılmadı, sonuç
dosyalarından makroyla geliyor. Bir tekrar üretilememe sorunu bulduk, düzelttik ve yazdık."

**Tuzak.** "Her şey birebir" deme; 8/9 birebir, dokuzuncunu açıkladık.

### Soru 10. En şaşırtıcı bulgunuz neydi?
**Sade anlatım.** Ölçüm bizim kendi tasarım kusurumuzu buldu. Tahmin servisi eksik bir istasyonu {{nWaitMs}} ms
bekliyordu; kalıcı çevrimdışı bir cihaz varsa her saat boşuna bekliyordu ve gecikme **{{nOffLatOneBefore}} s**'ye
çıkıyordu. Düzeltme: retained `offline` durumunu gören servis kısa bir süreden sonra beklemeyi bırakıyor; gecikme
**{{nOffLatOneAfter}} s** oldu. Düzeltme mesaj kaybında yardım etmez: kaybolan mesaj hiçbir şey duyurmaz. Bu kusur sistemi
ağ koşullarıyla birlikte ölçmeden görünmezdi: çalışmanın üçüncü katkısının (K3) somut örneği.

**Jüriye söyle.** "Sistemi bozulan ağda ölçünce kendi tasarım hatamızı bulduk: çevrimdışı bir cihaz yüzünden gecikme
{{nOffLatOneBefore}} saniyeydi, düzeltince {{nOffLatOneAfter}} saniyeye indi."

**Tuzak.** Alternatif cevap olarak "komşular 24 saatte işe yaramıyor" da dürüst bir sürpriz; ama bu cevap en iyisi.

---

## 4. Diğer sorular için kısa cevap kartları

- **Gerçek sensör neden yok?** Fiziksel sensörümüz yok; gerçek kentin gerçek ölçümlerini sanal cihazlarla oynatıyoruz
  (haze gibi gerçek olaylar var). Saha çalışması iddia etmiyoruz; gelecek çalışma: PMS5003 + ESP32 [R20][R1].
- **Uyarı eşiğini nasıl seçtiniz?** δ payı doğrulama verisinde F2'yi en büyük yapacak şekilde seçildi, test'e bakılmadı.
  F2, çünkü olay kaçırmak (sağlık riski) yanlış alarmdan pahalı. Uyarı sonrası {{nCooldownH}} saat soğuma.
- **Anomali tespiti neden yok?** Kapsam dışı: arızanın tahmine etkisini ölçüyoruz, arızayı tespit etmiyoruz. Edge'deki
  5 kural basit kural tabanlı kontroldür [R21][R22].
- **Güvenlik?** Komut kanalı kimlik doğrulamasız ve yalnızca yerel; gerçek dağıtım TLS ve erişim denetimi ister. Bir
  güvenlik taramasında üç açık bulundu ve düzeltildi (HTML enjeksiyonu, ağa açık pano, Host/Origin denetimi); testle korunuyor.
- **SQLite ölçeklenir mi?** Yükümüz saatte {{nDataStations}} satır; WAL ve tek yazıcıyla fazlasıyla yeter. Binlerce
  cihazda PostgreSQL/TimescaleDB gerekir. Sınırlamada yazılı.
- **Edge filtresi neden 6 saatte zarar verebiliyor?** Nedenini sınamadık. Olası: filtre değeri "eksik" yapıp modelin
  kullanabileceği bilgiyi kaldırıyor; bir sıçrama gerçek bilgi de olabilir. Eşleştirilmiş koşular yalnızca
  {{nAbSpikeWindows}} pencere: gösterim, kesin sonuç değil.
- **Colab?** Kapsam dışı; kod yolları durur ama Colab'da doğrulanmadığı için desteklediğimizi iddia etmiyoruz.

---

## 5. Sayı kopya kâğıdı (hepsi makaledeki sayı)

| Ne | Değer |
|---|---|
| Veri | {{nDataStations}} istasyon, {{nDataHours}} saat |
| Bölme | eğitim {{nTrainStart}}–{{nTrainEnd}}, doğrulama {{nValStart}}–{{nValEnd}}, test {{nTestStart}}–{{nTestEnd}} |
| R² (M2b) | 1 saatte {{nRTwoMtwobHOne}}, 24 saatte {{nRTwoMtwobHTwentyFour}} (persistence 24 saatte {{nRTwoPersistHTwentyFour}}) |
| Persistence'a göre RMSE iyileşmesi (M2b) | %{{nImprMtwobHOne}} / %{{nImprMtwobHSix}} / %{{nImprMtwobHTwentyFour}} (1/6/24 sa) |
| Komşu ablasyonu | 1 sa %{{nAblKelevenHOne}}, 6 sa %{{nAblKelevenHSix}}, 24 sa yok |
| Görülmemiş istasyon (LOSO) | {{nLosoStations}} istasyon; persistence'ı geçen: {{nLosoBetterHOne}} / {{nLosoBetterHSix}} / {{nLosoBetterHTwentyFour}} (1/6/24 sa); 1 sa iyileşme %{{nLosoMeanHOne}} (eğitimdeyken %{{nLosoInSampleHOne}}) |
| Erken uyarı F2 | 1 sa {{nWarnFtwoMtwobHOne}}, 6 sa {{nWarnFtwoMtwobHSix}}; 24 saatte persistence'ın gerisinde |
| Test yılı olayları | {{nEventsHundred}} aşım olayı, {{nEventsHaze}} bölgesel haze epizodu |
| 24 sa haze yakalama | M2b {{nHazeCaughtMtwobHTwentyFour}}, persistence {{nHazeCaughtPersistHTwentyFour}} |
| q90 uyarı (24 sa) | recall {{nQwRecMtwobHTwentyFour}} → {{nQwRecQnineHTwentyFour}}, yanlış alarm {{nQwFaMtwobHTwentyFour}} → {{nQwFaQnineHTwentyFour}} |
| Aşırı olay (> {{nExtPNinetyFive}} µg/m³, 24 sa) | RMSE {{nExtRmseMtwobHTwentyFour}} (persistence {{nExtRmsePersistHTwentyFour}}), ortalama hata {{nExtBiasMtwobHTwentyFour}} |
| Aralık kapsaması (hedef 0.80) | ham {{nCovRawHOne}} → kalibre {{nCovCalHOne}} (1 sa); aşırı hedeflerde 24 saatte yalnızca {{nCovExtCalHTwentyFour}} |
| %20 mesaj kaybı | teslim oranı {{nPdrTwenty}}, 1 saatlik hata +{{nDmgTwenty}} µg/m³, medyan DB gecikmesi {{nLatDbMedian}} ms |
| 3600× hızda | %20 kayıpta {{nRunsTwenty}} koşudan {{nBehindTwenty}}'ünde tahmin servisi geride |
| Edge filtresi geri aldığı zarar (1 sa, spike) | basit model %{{nRobRecPersistHOne}}, M2b %{{nRobRecMtwobHOne}} |
| Çevrimdışı cihaz gecikmesi | {{nOffLatOneBefore}} s → {{nOffLatOneAfter}} s (tam ağda {{nOffLatFullAfter}} s) |
| Senaryolar | {{nScnTotal}} hipotezden {{nScnConfirmed}} doğrulandı, {{nScnRefuted}} çürütüldü |
| Optuna | {{nOptunaTrials}} deneme; 10→20 kazanç %{{nTuneGainTenTwenty}} |
| Toplam deney koşusu | {{nRunsTotal}} |

---

## 6. Söylememen gerekenler / söylemen gerekenler

| Söyleme | Söyle |
|---|---|
| "Bunu ilk biz yaptık" | "Taramamızda bu birleşimi ölçen bir hava kalitesi çalışması bulamadık" |
| "Gerçek sahada test ettik" | "Gerçek ölçümlerle iz sürümlü emülasyon yaptık" |
| "Sızıntı yok" | "Bildiğimiz yolları kapattık ve testlerle denetledik" |
| "Model çok iyi" | "1-6 saatte persistence'a göre %{{nImprMtwobHOne}}-%{{nImprMtwobHSix}} iyi; uzun ufukta ve aşırı olaylarda yetersiz" |
| "GNN/LSTM'den iyidir" | "GNN/LSTM ile karşılaştırmayı yapmadık" |
| "Güvenli" | "Yalnızca yerel; gerçek dağıtım TLS ve erişim denetimi ister" |
| Bilmediğin bir şey için uydurma | "Bunu ölçmedik / kapsam dışı / gelecek çalışma" |

---

## 7. Demo sırasında bilmen gerekenler

- Başlat: `python -m scripts.demo` (broker, edge, ingest, tahmin, filo, API ve pano tek komutta; Ctrl+C hepsini kapatır).
- Planlı akış (yaklaşık 3 dakika), her senaryonun hipotezi önceden yazıldı:
  1. `gercek_haze_replay`: gerçek haze olayında uyarı epizottan **{{nScnHazeLead}} saat önce** gelir.
  2. `sensor_takilmasi`: sensör takılır; edge kapalıyken zarar, açıkken filtre.
  3. `cihaz_kopmasi`: LWT devreye girer, kartlar "offline" olur.
  4. `ag_bozulmasi`: teslim oranı {{nScnDelivery}}, p95 gecikme {{nScnLatencyP}} ms.
- Jüri isterse: istasyon + değer seç (örneğin "Dongsi PM2.5 6 saatte 300'e çıksın"); geçersiz değer reddedilir; "Sıfırla" temiz duruma döner.
- Demo çökerse sırayla: `python -m scripts.demo --offline` → `docs/assets/demo_dashboard.gif` → `slides/demo_screens/` →
  `slides/demo_backup.mp4`. Panik yok: "yedek kayıtlı koşuyu gösteriyorum" de.
- Komutun kendisi MQTT'den gider (`cmd`/`ack`): kontrol yolu da IoT'nin kendi kanalı. Bu, "neden bu demo?" sorusunun cevabı.

---

## 8. Nasıl çalışmalı (30 dakika)

1. 1. bölümü sesli, kendi cümlelerinle anlat (30 sn). Takılırsan 2. bölümdeki terimlere bak.
2. 3. bölümdeki 10 soruyu **önce kendin** cevapla, sonra karşılaştır; zayıf kalanları işaretle.
3. 5. bölümdeki 6-8 sayıyı ezberle: R², iyileşme yüzdeleri, F2, %20 kayıp, {{nOffLatOneBefore}} → {{nOffLatOneAfter}} s.
4. Sunumu `slides/notes.md` ile zamanlayarak bir kez baştan sona söyle (hedef: 12-15 dk, demo dahil).
5. `slides/qa.md`'den rastgele 10 soru seç; Claude Code'a "sorularla beni sına" de, o da sorarak puanlasın.
