# Olası jüri soruları ve kısa, dürüst cevaplar

TALIMAT §12.4: ilk 12 soru zorunlu liste, devamı bulgulardan çıkan sorular. Cevaplar kısa tutuldu; sayılar
`paper/numbers.tex` makrolarından gelir. Gün 20'de bu sorulardan rastgele 10'u sözlü prova olarak sorulur.
Bilmediğin bir şeyi "ölçmedik" ya da "kapsam dışı" diye söyle: uydurma.

## 1. Neden gerçek sensör yok?
Fiziksel sensörümüz yok. Ama gerçek bir kentin gerçek ölçümlerini ({{nDataStations}} istasyon, {{nDataHours}} saat) sanal cihazlarla yeniden oynatıyoruz; haze gibi gerçek olaylar var. İddiamız saha çalışması değil, iz sürümlü emülasyon; sınırlamada yazılı. Gelecek çalışma: PMS5003 + ESP32 ile saha testi [R20][R1].

## 2. Neden MQTT?
Sensörler için tasarlanmış hafif bir yayın-abone protokolü; QoS, LWT ve retained mesaj hazır, cihaz kopmasını kendisi bildirir. HTTP istek-yanıttır ve kopmayı bildirmez; CoAP UDP tabanlıdır ve ekosistemi dardır [R7]. Hava kalitesi mimarileri de MQTT kullanır [R18][R19].

## 3. QoS 1 neden, tekrar mesajlar ne oluyor?
Ölçüm kaybolursa tahmin eksik veriyle çalışır; QoS 0'da ağ kaybında mesaj sessizce gider. QoS 1 "en az bir kez" teslim eder, yani tekrar gelebilir. Ingest `(istasyon, ts)` anahtarıyla idempotent yazar: aynı mesaj satır eklemez. Ölçülen tekrar oranı {{nDupRateMax}}. QoS 2 saatlik veri için gereksiz yük.

## 4. Leakage'ı nasıl önlediniz?
Kronolojik bölme (eğitim {{nTrainStart}}-{{nTrainEnd}}, doğrulama {{nValStart}}-{{nValEnd}}, test {{nTestStart}}-{{nTestEnd}}); uydurma yalnızca eğitimde, seçim yalnızca doğrulamada; eksik doldurma yalnızca geçmişe bakar; hedef zamanı sonraki bölmeye düşen satırlar atılır; gelecekteki PM10 kullanılmaz; hepsi testlerle denetlenir [R13][R16]. Test dönemi bir kez değerlendirildi (tek istisna makalede yazılı). Kanıt: R² 24 saatte {{nRTwoMtwobHTwentyFour}}, şişirilmiş değil.

## 5. Neden LightGBM, neden LSTM/GNN değil?
Tablo özelliklerinde rekabetçi, CPU'da dakikalar içinde eğitilir, eksik değerleri işler, SHAP ile açıklanır; sızıntısız protokolde ağaç modelleri güçlü [R13][R14]. LSTM/GNN daha fazla ayar ister ve koordinat olmadan GNN'in avantajı sınırlı [R9][R10][R11][R12]. Komşu bilgisini açık özelliklerle ablasyonla ölçtük: 1 ve 6 saatte %{{nAblKelevenHOne}} ve %{{nAblKelevenHSix}}, 24 saatte yok. GNN ile karşılaştırmayı yapmadık.

## 6. Persistence neden bu kadar güçlü?
PM2.5 saatlik değişimi yavaş: 1 saatte persistence'ın R² değeri {{nRTwoPersistHOne}}, RMSE {{nRmsePersistHOne}}. Bu yüzden 1 saatteki kazanç küçük (%{{nImprMtwobHOne}}); asıl kazanç uzun ufukta (24 saatte %{{nImprMtwobHTwentyFour}}). Literatürde de fark küçük [R13]; dürüstçe raporladık.

## 7. Aşırı olaylarda model neden zorlanıyor?
Kare hata amacı ortalamaya çeker ve eğitimde aşırı değerler azdır; ortalama hata pozitif: model düşük tahmin eder (24 saatte {{nExtBiasMtwobHTwentyFour}} µg/m³). Nedenini ayrıca izole etmedik. Hafifletme: q90 tabanlı uyarı recall'u {{nQwRecMtwobHTwentyFour}}'den {{nQwRecQnineHTwentyFour}}'e çıkarır (bedel: yanlış alarm). Literatürle uyumlu [R13].

## 8. Uyarı eşiğini nasıl seçtiniz?
δ payını doğrulama verisinde, F2 (β={{nBeta}}) en büyük olacak şekilde ızgaradan seçtik; test'e bakılmadı. F2, çünkü olay kaçırmak (sağlık riski) yanlış alarmdan pahalı. Uyarı sonrası {{nCooldownH}} saat soğuma, aynı olay için bildirim yağmasın.

## 9. Edge'de neden tahmin yok?
[R6] edge'de tahmin yapıyor; biz edge'de yalnızca veri kalitesini doğruluyoruz, tahmin sunucuda. Modeli edge'e dağıtmak ve güncellemek zor, ve komşu istasyonların verisi sunucuda birleşiyor. Edge'de tahmin gelecek çalışma.

## 10. Anomali tespiti neden yok?
Kapsam dışı: bu çalışma arızanın tahmine etkisini ölçer, arızayı tespit etmez (hatalı girdi sentetik, tespit başarısı iddiası yok). Edge'deki beş kural basit kural tabanlı kontrollerdir [R21][R22]. Ayrı bir anomali modülü gelecek çalışma.

## 11. Gerçek dağıtımda güvenlik?
Komut kanalı kimlik doğrulamasızdır ve yalnızca yerel makineye açıktır; gerçek dağıtım TLS ve MQTT erişim denetimi ister. Bir güvenlik taramasında üç açık bulup düzelttik (panoda HTML enjeksiyonu, ağa açık pano, API'de Host/Origin denetimi yok); testle korunuyor. Sınırlar `SECURITY.md`'de yazılı.

## 12. SQLite ölçeklenir mi?
Yükümüz saatte {{nDataStations}} satır: SQLite (WAL, tek yazıcı) bunun için fazlasıyla yeter. Binlerce cihazlık bir ağda ölçeklenmez; orada PostgreSQL/TimescaleDB gerekir. Sınırlamada yazılı.

## 13. Test setini kaç kez kullandınız?
Her protokol için bir kez. Tek istisna: M2a'nın 1 saatlik modelinin Optuna çalışması yeniden üretilemediği için temiz yeniden koşuldu ve test ikinci kez hesaplandı; seçim doğrulamada kaldı, iki değer de {{nRmseMtwoaHOne}}'a yuvarlanır, hiçbir bulgu değişmedi. Makalede açıkça yazılı.

## 14. Sonuçlar tekrar üretilebilir mi?
Evet: `python -m scripts.run_all` ham veriden her şeyi üretir. Tam yeniden üretimde 9 Optuna çalışmasının 8'i birebir çıktı; dokuzuncusunun kesintiye uğramış bir denemeden saptığı bulundu ve düzeltildi. RQ2 ve RQ3b birebir. CI her değişiklikte çalışıyor.

## 15. Edge filtresi neden 6 saatte zarar verebiliyor?
Nedenini sınamadık. Bir olasılık: filtre değeri "eksik" yaparak modelin kullanabileceği bilgiyi kaldırıyor; bir spike gerçek bilgi de olabilir. Eşleştirilmiş koşular yalnızca {{nAbSpikeWindows}} pencere: kesin sonuç değil, gösterim.

## 16. En şaşırtıcı bulgunuz neydi?
Ölçümün bir tasarım kusurunu bulması: tahmin servisi çevrimdışı cihazı her saat boşa bekliyordu, gecikme {{nOffLatOneBefore}} s'ye çıkıyordu; düzeltince {{nOffLatOneAfter}} s oldu. Bunu ancak sistemi ağ koşullarıyla birlikte ölçerek bulduk.

## 17. Google Colab desteği var mı?
Hayır, kapsam dışı bıraktık: kod yolları durur ama Colab'da doğrulanmadığı için desteklediğimizi iddia etmiyoruz.
