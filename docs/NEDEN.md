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

### Edge katmanı ve veri kalitesi kuralları
- Ne: Sensör ile sunucu arasındaki ara düğüm; gelen her mesajı doğrular, ölçümün güvenilir olup olmadığını işaretler ve sunucuya iletir.
- Neden: Bozuk bir sensör değeri (takılı kalma, ani sıçrama) tahmini bozar. Kontrolü kaynağa yakın yapmak hem veriyi temizler hem de hatalı cihazı erkenden görünür kılar; literatürdeki edge mimarileri de aynı gerekçeyi kullanır [R5][R21][R22]. Kuralların false alarm oranı temiz veride ölçüldü: kural başına yaklaşık %0,1–0,4.
- Alternatifler ve neden seçilmedi: Doğrulamayı sunucuda yapmak (hatalı veri ağdan geçer, edge'in yük azaltma faydası kaybolur), edge'de tahmin yapmak [R6] (modeli cihaza dağıtmak ve güncellemek zor; kapsamımız dışında).
- Projede nerede: `src/airq/edge/quality.py`, `gateway.py`
- Sunumda tek cümle: Bozuk ölçümü sunucuya varmadan işaretliyoruz; filtreyi açıp kapatarak tahmine etkisini canlı gösteriyoruz.

### PM2.5 ≤ PM10 fiziksel tutarlılık kuralı
- Ne: PM2.5 (ince partikül) tanım gereği PM10'un (kaba+ince) bir parçasıdır; PM2.5'in PM10'dan belirgin büyük çıkması ölçüm hatasıdır.
- Neden: Literatürde nadiren açıkça kullanılır. Ancak gerçek veride PM2.5 > PM10 satırları %8,2; bu yüzden katı kural çok yanlış alarm verirdi. Toleransı (ε=0,1 ve c≈98,85) train'de kalan %0,1'lik uç değerlere göre seçtik; kural yalnızca belirgin tutarsızlıkları yakalar.
- Alternatifler ve neden seçilmedi: Katı `PM2.5 ≤ PM10` (%8 yanlış alarm), kuralı hiç kullanmamak (bu hata türü kaçar).
- Projede nerede: `src/airq/edge/quality.py` (`PM_INCONSISTENT`)
- Sunumda tek cümle: Gerçek veride ince partikül bazen kaba partikülden büyük çıkıyor; toleransı veriden ölçüp kuralı ona göre gevşettik.

### SQLite (ve neden PostgreSQL/TimescaleDB değil)
- Ne: Tek dosyalık, kurulum gerektirmeyen veritabanı; WAL modunda yazıcı ve okuyucu aynı anda çalışabilir.
- Neden: Bir şehir ağı için saatte 12 satırlık yük SQLite'a çok küçük; ayrı sunucu kurmadan Windows, CI ve Colab'da aynı şekilde çalışır. Tek yazıcı (ingest) kuralıyla yarış durumu yoktur; API salt-okunur bağlantı kullanır.
- Alternatifler ve neden seçilmedi: PostgreSQL/TimescaleDB (ayrı sunucu, kurulum ve bakım; bu ölçekte fayda yok, kapsam dışı). Ölçeklenme sınırı makalede açıkça yazılacak.
- Projede nerede: `src/airq/server/db.py`, `ingest.py`
- Sunumda tek cümle: Yükümüz saatte 12 satır; ayrı veritabanı sunucusu kurmak yerine WAL modundaki SQLite yetiyor, ölçek sınırını da açıkça belirtiyoruz.

### Google Colab ve ince notebook'lar
- Ne: Tüm mantık `src/airq/` paketindedir; notebook'lar yalnızca paket fonksiyonlarını çağırır.
- Neden: GitHub'a gelen biri "Open in Colab" ile sonuçları tarayıcıda yeniden üretebilir; laptop yetmezse Colab yedek ortam olur. Mantığı notebook'a gömseydik iki kopya oluşur, biri bozulurdu. `AIRQ_FIXTURE=1` küçük sentetik veriyle notebook'ları internetsiz (CI'da) çalıştırır.
- Alternatifler ve neden seçilmedi: Mantığı notebook'ta yazmak (kopya ve sürüm kayması), Colab'ı hiç desteklememek (yeniden üretilebilirlik zayıflar).
- Projede nerede: `notebooks/`, `scripts/build_notebooks.py`, `src/airq/pipelines/colab.py`, `src/airq/data/fixture.py`
- Sunumda tek cümle: Notebook'lar ince; aynı kod hem laptopta hem Colab'da çalışıyor ve CI'da sentetik veriyle her değişiklikte deneniyor.

### Canlı predictor, komşu bekleme süresi ve parite testi
- Ne: Edge'den gelen ölçümleri bir kayan tamponda biriktirir, eğitimdekiyle aynı özellik fonksiyonunu çalıştırır ve 1/6/24 saat sonrasını tahmin eder. Her saatte diğer istasyonların ölçümünü en çok `predictor_wait_ms` (500 ms) bekler; gelmeyen istasyon "eksik" sayılır.
- Neden: (1) İstasyonlar ayrı MQTT bağlantısı olduğundan aynı saatin mesajları karışık sırada gelir; beklemezsek komşu özellikleri rastgele eksik kalırdı. (2) Süre dolunca eksik sayıldığı için ağ bozulmasının tahmine etkisini (RQ3a) gerçekçi ölçeriz. (3) Eğitim ve canlıda aynı kod çalıştığından ayrışma olmadığını testle kanıtlarız: aynı veri hem doğrudan hem MQTT hattından geçiyor ve özellikler ile tahminler eşit çıkıyor.
- Alternatifler ve neden seçilmedi: Beklemeden hemen tahmin (komşu verisi tutarsız), sonsuz bekleme (bir cihaz çökerse sistem takılır), özellikleri veritabanından yeniden okumak (gecikme ve ikinci bir kod yolu).
- Projede nerede: `src/airq/server/predictor.py`, `tests/integration/test_online_offline_parity.py`
- Sunumda tek cümle: Canlı sistem, modelin eğitildiği kodla birebir aynı özellikleri üretiyor; bunu aynı veriyi iki yoldan geçirip eşitliği ölçerek gösterdik.

### FastAPI (salt-okunur API)
- Ne: Dashboard'un ve diğer araçların veritabanını okuduğu küçük bir HTTP servisi.
- Neden: Dashboard veritabanına doğrudan bağlanmaz; tek bir kapıdan okur, hatalı istekler 404/422 ile açıkça reddedilir. Otomatik şema doğrulaması ve belge sayfası (`/docs`) hazır gelir; Python'da Streamlit ve MQTT ile aynı dilde.
- Alternatifler ve neden seçilmedi: Flask (doğrulama ve şema elle yazılır), dashboard'un doğrudan SQLite okuması (kontrol uçları ve yetki ileride eklenemez).
- Projede nerede: `src/airq/server/api.py`
- Sunumda tek cümle: Dashboard yalnızca API'den okuyor; hatalı isteği sessizce yutmuyor, açıkça reddediyor.

### Diebold–Mariano testi, Holm düzeltmesi ve blok-bootstrap
- Ne: "Model A, model B'den gerçekten daha mı iyi, yoksa şans mı?" sorusunu yanıtlayan istatistik testleri. Diebold–Mariano iki modelin hatalarını karşılaştırır; Holm, 12 istasyonu birlikte test ederken yanlış "anlamlı" bulguyu azaltır; blok-bootstrap güven aralığı verir.
- Neden: Tahmin hataları ardışık saatlerde birbirine bağlıdır (otokorelasyon); klasik t-testi bunu yok sayıp aşırı güvenli sonuç verir. DM, h adımlı tahminler için bu bağımlılığı düzeltir [R24][R25]. Bootstrap'ta 24 saatlik bloklar yeniden örneklenerek bağımlılık korunur [R13]. 12 testin birlikte yorumlanması için Holm uygulanır.
- Alternatifler ve neden seçilmedi: Eşleştirilmiş t-testi (bağımlılığı yok sayar), yalnızca RMSE farkını vermek (fark şans eseri olabilir).
- Projede nerede: `src/airq/eval/stats.py`
- Sunumda tek cümle: "Daha iyi" demek için yalnızca RMSE'ye bakmıyoruz; hataların zaman bağımlılığını hesaba katan testlerle farkın şans olmadığını gösteriyoruz.

### LOSO (görülmemiş istasyon) ve SHAP
- Ne: LOSO: bir istasyonu tamamen dışarıda bırakıp modeli diğer 11 istasyonla eğitmek ve dışarıdaki istasyonda sınamak. SHAP: bir tahminin hangi özelliklerden ne kadar etkilendiğini hesaplamak.
- Neden: Yeni bir kuruluma (hiç verisi olmayan istasyon) genelleme iddiası ancak LOSO ile sınanır [R13][R14]. SHAP, modelin "kara kutu" olmadığını gösterir ve komşu bilgisinin ne kadar kullanıldığını ölçer [R26]; ancak özelliğin kullanılması, doğruluğa artımlı katkı vermesi demek değildir, bu yüzden SHAP'ı ablasyon sonuçlarıyla birlikte yorumluyoruz.
- Alternatifler ve neden seçilmedi: Yalnızca rastgele istasyon bölmesi (tek bölme şansa bağlı), özellik önemini ağaç sayısından okumak (yanıltıcı).
- Projede nerede: `src/airq/pipelines/rq1_final.py`
- Sunumda tek cümle: Modelin hiç görmediği istasyonda da çalışıp çalışmadığını ve neye baktığını ayrı ayrı ölçtük.

### Erken uyarı kuralı: eşik payı δ, F2 ve soğuma süresi
- Ne: Tahmin eşiğin δ kadar altına bile inerse uyarı veriyoruz (ŷ > θ − δ). δ'yı doğrulama verisinde F2 skorunu en büyük yapacak şekilde seçiyoruz. Bir uyarı açıldıktan sonra 6 saat boyunca aynı istasyon için yeni uyarı vermiyoruz (soğuma).
- Neden: Erken uyarıda bir kirlilik olayını kaçırmak (sağlık riski), yanlış alarmdan daha pahalıdır; F2 duyarlılığa (recall) daha çok ağırlık verir. δ güvenlik payı, modelin aşırı değerleri hep küçük tahmin etmesini (RQ1'de ölçtük) telafi eder. Soğuma, kirli havanın sürdüğü saatlerde aynı olay için yüzlerce bildirim gönderilmesini önler. δ yalnızca doğrulamada seçildiği için test sonucu uyarlanmaz.
- Alternatifler ve neden seçilmedi: Sabit eşik (δ=0; tahmin küçük kaldığı için olayları geç yakalar), F1 (yanlış alarm ve kaçırmayı eşit sayar), her saat uyarı (kullanıcıyı boğar).
- Projede nerede: `src/airq/warning/rules.py`, `src/airq/server/predictor.py` (canlı uygulama)
- Sunumda tek cümle: Olay kaçırmak yanlış alarmdan pahalı olduğu için eşiğin biraz altında uyarıyoruz; payı doğrulama verisinde seçip test'e hiç bakmıyoruz.

### "Ufukla eşleşen" öncül süre ölçümü
- Ne: Bir uyarının ancak öngördüğü an gerçekten kirlilik olayının içine düşüyorsa o olayı "önceden haber verdi" saymak.
- Neden: Kirlilik olayları sık olduğunda "olaydan önceki 24 saatte herhangi bir uyarı" kuralı, alakasız bir uyarıyı bile sayar; persistence gibi en basit yöntem bile %100 yakalama ve 16 saat öncül süre gösterir. Eşleşen tanımda öncül süre uyarının ufkunu aşamaz ve karşılaştırma gerçekten anlamlı olur. İki tanımı birlikte raporluyoruz.
- Alternatifler ve neden seçilmedi: Yalnızca basit pencere tanımı (şişkin sonuç), yalnızca saat bazlı metrik (olay bazlı yararı göstermez).
- Projede nerede: `src/airq/warning/evaluate.py` (`matched_leads`)
- Sunumda tek cümle: "Haber verdi" demek için uyarının tahmin ettiği anın gerçekten olayın içinde olması gerekiyor; yoksa en basit yöntem bile mükemmel görünürdü.

### Streamlit + Plotly dashboard (yalnızca API'den okur)
- Ne: Canlı ağı, tahminleri ve uyarıları gösteren web arayüzü; veriyi yalnızca API'den okur.
- Neden: (1) Python'da yazıldığı için tüm sistemle aynı dilde, ayrı bir ön yüz projesi gerektirmez. (2) Streamlit'in `fragment` özelliği sayfayı 1–5 saniyede bir kendiliğinden yeniler. (3) Plotly etkileşimli grafik verir (yakınlaşma, üzerine gelince değer). (4) Arayüz veritabanına doğrudan bağlanmadığı için tek kapıdan (API) okur; hata durumları açık gösterilir. Projektörde okunsun diye açık tema, büyük yazı, renk körü dostu palet kullanılır ve durum yalnızca renkle değil yazıyla da belirtilir (ör. "Çok ağır kirli", "UYARI").
- Alternatifler ve neden seçilmedi: Grafana (kurulum ve veri kaynağı ayarı gerekir, uyarı ve senaryo kontrolünü özelleştirmek zor), React/JS (ayrı bir ön yüz ve süre maliyeti), doğrudan SQLite okuyan betik (API ve hata doğrulaması atlanır).
- Projede nerede: `src/airq/dashboard/`
- Sunumda tek cümle: Dashboard yalnızca API'den okuyor ve durumu renkle birlikte yazıyla da söylüyor; böylece projektörde ve renk körü izleyiciler için de okunur.

### Sentetik hatalı girdi (spike, stuck, dropout) ve edge açık/kapalı karşılaştırması
- Ne: Gerçek test verisine bilerek üç tür sensör hatası ekliyoruz (ani sıçrama, takılı kalma, kesinti) ve tahminin ne kadar bozulduğunu, edge kontrolü açıkken ve kapalıyken ölçüyoruz. Hedef değerlere dokunmuyoruz.
- Neden: Sahada sensörler bozulur [R1][R21][R22]; hatalı girdinin tahmini ne kadar bozduğunu ve edge doğrulamasının bunu ne kadar önlediğini ölçmek bu çalışmanın katkılarından biri (K3). Hataları kontrollü ve tekrarlanabilir (tohumlu) ürettiğimiz için "edge açık" ile "kapalı" aynı bozulma üzerinde kıyaslanır. Hatalar sentetik olduğundan bu bir arıza tespiti başarısı iddiası değildir; yalnızca dayanıklılık ölçümüdür.
- Alternatifler ve neden seçilmedi: Gerçek arızalı sensör verisi (elimizde yok), yalnızca temiz veriyle test (edge'in değeri ölçülemez), edge'i yalnızca tespit oranıyla değerlendirmek (tahmine etkisini göstermez).
- Projede nerede: `src/airq/perturb/inject.py`, `src/airq/pipelines/rq3b.py`
- Sunumda tek cümle: Sensörü bilerek bozup edge filtresini açıp kapattık; filtre basit modelde zararın büyük kısmını geri aldı, güçlü modelde etkisi daha küçük kaldı.
