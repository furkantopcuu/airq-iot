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

### Tek özellik fonksiyonu (offline = online)
- Ne: Hem model eğitiminde hem canlı sistemde aynı `build_features` fonksiyonunu çalıştırıyoruz.
- Neden: İki ayrı kod yazılırsa eğitimde görülen özellikler ile canlıda hesaplananlar sessizce ayrışır (train/serve skew) ve model canlıda bozulur. Tek fonksiyon + parite testi bunu engeller.
- Alternatifler ve neden seçilmedi: Canlı için ayrı optimize kod (hızlı ama tutarsızlık riski), önceden hesaplanmış özellik tablosu (canlı veriyle çalışmaz).
- Projede nerede: `src/airq/features/build.py`
- Sunumda tek cümle: Eğitimde ve canlıda aynı kod çalıştığı için modelin gördüğü veri değişmiyor.

### Komşu istasyon özellikleri
- Ne: Bir istasyonun tahminine, diğer istasyonların o anki PM2.5 ortalaması, medyanı, eğimi ve kaç komşudan veri geldiği gibi özetleri ekliyoruz.
- Neden: Kirlilik dalgaları şehirde istasyondan istasyona yayılır; komşuları görmek özellikle 6 ve 24 saat sonrasını tahmin etmeyi kolaylaştırması beklenir (ölçülmeden iddia edilmez, ablasyonla test edilecek). Komşu eksikse hesaba katılmaz; kaç komşu olduğu da özellik olduğundan ağ kopmasının etkisi ölçülebilir.
- Alternatifler ve neden seçilmedi: Grafik sinir ağları (GNN [R11][R12]): koordinat yok, süre ve açıklanabilirlik maliyeti yüksek; açık komşu özellikleri hafif bir yaklaşık.
- Projede nerede: `src/airq/features/build.py`, `neighbors.py`
- Sunumda tek cümle: Komşu istasyonları özellik olarak veriyoruz; faydasını komşusuz modelle karşılaştırarak ölçüyoruz.

### Persistence baseline (ŷ = PM2.5(t))
- Ne: "Bir sonraki saat de şimdiki gibi olacak" diyen en basit tahmin.
- Neden: PM2.5 yavaş değiştiği için kısa ufukta yenilmesi zordur [R13]. Bir model onu geçemiyorsa işe yaramıyordur; tüm başarıyı "persistence'a göre % iyileşme" ile ölçüyoruz.
- Alternatifler ve neden seçilmedi: Yalnızca ortalamayla karşılaştırmak (haksız derecede kolay bir çıta).
- Projede nerede: `src/airq/models/baselines.py`
- Sunumda tek cümle: Modelimizi en basit "değişmez" tahminle kıyaslıyoruz, çünkü kolay çıtayı geçmek bir şey kanıtlamaz.

### LightGBM (ve neden LSTM/GNN değil)
- Ne: Birçok küçük karar ağacını arka arkaya eğiten, tablo verisinde güçlü ve hızlı bir yöntem.
- Neden: (1) Tablo özelliklerinde (gecikmeler, meteoroloji, komşu özetleri) derin ağlarla rekabetçi ve CPU'da dakikalar içinde eğitilir. (2) Eksik değerleri doğrudan işler. (3) SHAP ile açıklanabilir [R15][R26]. Sızıntısız protokolde ağaç modelleri literatürde güçlüdür [R13][R14].
- Alternatifler ve neden seçilmedi: LSTM/CNN-LSTM [R9][R10] ve GNN [R11][R12]: daha fazla ayar ve süre gerektirir, koordinat olmadan GNN'in avantajı sınırlı; açık komşu özellikleri hafif bir yaklaşık ve ablasyonla test ediliyor.
- Projede nerede: `src/airq/models/gbm.py`
- Sunumda tek cümle: Tablo verisinde hızlı, açıklanabilir ve güçlü olduğu için LightGBM seçtik; komşu bilgisinin faydasını ablasyonla ölçtük.

### Model manifest ve LightGBM metin formatı
- Ne: Modeli pickle yerine LightGBM'in kendi metin dosyasıyla saklıyor, yanına özellik listesi ve sürüm bilgisini yazıyoruz.
- Neden: Farklı ortamda (Colab, laptop) eğitilen modelin yanlış özelliklerle yüklenip sessizce kötü tahmin üretmesini önler; uyuşmazlıkta açık hata verir. Pickle sürümler arası kırılgandır.
- Alternatifler ve neden seçilmedi: Pickle/joblib (sürüm ve güvenlik riski), manifest'siz kayıt (sessiz hata).
- Projede nerede: `src/airq/models/manifest.py`
- Sunumda tek cümle: Modelin hangi özelliklerle eğitildiğini kayıt altında tutuyoruz; uyuşmazsa sistem hata verip duruyor.

### MQTT (ve neden HTTP/CoAP değil)
- Ne: Cihazların yayın (publish) yaptığı, ilgilenenlerin abone olduğu hafif bir mesajlaşma protokolü; aradaki "broker" mesajları dağıtır.
- Neden: (1) Sensörler için tasarlanmış, az bant genişliği kullanır [R7]. (2) Yayıncı ve abone birbirini tanımaz; yeni bir servis (edge, sunucu, dashboard) cihazlara dokunmadan eklenir. (3) QoS, LWT ve retained mesaj gibi IoT'ye özgü özellikleri hazır sunar. Literatürdeki hava kalitesi mimarileri de MQTT kullanır [R18][R19].
- Alternatifler ve neden seçilmedi: HTTP (her ölçüm için istek-yanıt, cihazdan sunucuya tek yön; cihaz kopmasını kendi başına bildirmez), CoAP (UDP tabanlı, araç ve broker ekosistemi daha dar) [R7].
- Projede nerede: `src/airq/iot/`, `devices/`
- Sunumda tek cümle: MQTT'yi, sensörler için tasarlandığı ve cihaz kopmasını kendisi bildirebildiği için seçtik.

### QoS 1 ve idempotent kayıt
- Ne: Telemetri "en az bir kez" teslim edilir; alınmazsa yeniden gönderilir.
- Neden: Hava kalitesi ölçümü kaybolursa tahmin eksik veriyle çalışır; QoS 0'da ağ kaybında mesaj sessizce gider. Bedeli, aynı mesajın iki kez gelebilmesidir; bunu `(istasyon, ts)` anahtarıyla yapılan idempotent kayıt zararsız hale getirecek (Gün 6) ve tekrar oranını ölçeceğiz [R7].
- Alternatifler ve neden seçilmedi: QoS 0 (kayıp), QoS 2 (iki aşamalı, fazla yük; saatlik veride gereksiz).
- Projede nerede: `src/airq/iot/topics.py` (QoS tablosu)
- Sunumda tek cümle: Mesaj kaybolmasın diye QoS 1 kullandık, olası tekrarı kayıt anında eliyoruz.

### LWT ve retained durum mesajı
- Ne: Cihaz bağlanırken broker'a "ben ölürsem 'offline' yayınla" vasiyeti bırakır (LWT); `online`/`offline` durumu retained olduğundan sonradan bağlanan da son durumu görür.
- Neden: Cihaz çökerse kendisi haber veremez; broker bunu fark edip bildirir. Dashboard'un "kartı offline göster" davranışı buna dayanır ve testle doğrulandı (süreç öldürülünce `offline` geliyor).
- Alternatifler ve neden seçilmedi: Yalnızca heartbeat zaman aşımı (yavaş ve belirsiz), veritabanında periyodik yoklama.
- Projede nerede: `src/airq/devices/virtual_sensor.py`, `tests/integration/test_mqtt_devices.py`
- Sunumda tek cümle: Bir cihaz aniden ölürse broker bunu kendisi duyuruyor; kartı gri yapmak için ayrıca yoklama gerekmiyor.

### Sanal cihazlar (trace-driven emülasyon)
- Ne: Gerçek kayıtlı ölçümler, her istasyon için ayrı bir MQTT istemcisi tarafından saat saat yayınlanır; `speedup=3600` ile 1 saniye = 1 simüle saat.
- Neden: Fiziksel sensör yok; ama gerçek bir kentin gerçek haze olaylarını canlı sistemden geçirebiliyoruz. Eksik ölçüm `null` gider, `seq` sayacı kayıp tespitini mümkün kılar.
- Alternatifler ve neden seçilmedi: Rastgele sentetik veri (gerçekçi olay yok), tek betikle doğrudan veritabanına yazmak (IoT katmanını ölçemeyiz).
- Projede nerede: `src/airq/devices/`
- Sunumda tek cümle: Gerçek ölçümleri sanal cihazlarla yeniden oynatıyoruz; saha çalışması iddiamız yok.

### Mosquitto (asıl broker), amqtt (yedek) ve Pydantic şemaları
- Ne: Mesajları dağıtan broker olarak Mosquitto kullanıyoruz; kurulu değilse (ör. CI) saf-Python amqtt devreye girer. Mesaj biçimi Pydantic şemasıyla doğrulanır.
- Neden: Mosquitto olgun, hafif (birkaç MB RAM) bir C programı ve literatürdeki referans broker; ağ ölçümlerinde (gecikme, kayıp) broker kendi gecikmesini ölçüme katmaz. amqtt tek iş parçacıklı Python olduğundan yük altında ölçümü bulandırabilir. Testlerimiz her iki broker'da da geçiyor. Şema, bozuk mesajı kapıda reddeder.
- Alternatifler ve neden seçilmedi: Yalnızca amqtt (kurulumsuz ama ölçüm için zayıf), RabbitMQ (ağır, kapsam dışı), doğrulamasız JSON (bozuk veri tahmine sızar).
- Projede nerede: `src/airq/iot/broker.py`, `configs/mosquitto.conf`, `src/airq/iot/schemas.py`
- Sunumda tek cümle: Ağ ölçümlerini yaygın kullanılan Mosquitto ile yaptık; mesajlar şemayla doğrulanıyor.
