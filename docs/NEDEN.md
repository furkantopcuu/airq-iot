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
- Neden: ML (LightGBM, pandas), IoT (paho-mqtt) ve web (FastAPI) kütüphaneleri tek dilde; kurulumu tek komut.
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
- Neden: Kirlilik dalgaları şehirde istasyondan istasyona yayılır; komşuları görmek özellikle 6 ve 24 saat sonrasını tahmin etmeyi kolaylaştırması beklenir (ablasyonla ölçüldü: 1 saatte %4,3 ve 6 saatte %4,7 anlamlı kazanç, 24 saatte %0,3 ve anlamsız; `FINDINGS.md`). Komşu eksikse hesaba katılmaz; kaç komşu olduğu da özellik olduğundan ağ kopmasının etkisi ölçülebilir.
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
- Neden: Başka bir bilgisayarda ya da eski bir sürümle eğitilen modelin yanlış özelliklerle yüklenip sessizce kötü tahmin üretmesini önler; uyuşmazlıkta açık hata verir. Pickle sürümler arası kırılgandır.
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
- Neden: Hava kalitesi ölçümü kaybolursa tahmin eksik veriyle çalışır; QoS 0'da ağ kaybında mesaj sessizce gider. Bedeli, aynı mesajın iki kez gelebilmesidir; bunu `(istasyon, ts)` anahtarıyla yapılan idempotent kayıt zararsız hale getirir; RQ3a'da tekrar oranı her koşuda sıfır ölçüldü [R7].
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
- Neden: Literatürde nadiren açıkça kullanılır. Ancak eğitim döneminde PM2.5 > PM10 olan satırlar %8,2 (tüm veride %5,2); bu yüzden katı kural çok yanlış alarm verirdi. Toleransı (ε=0,1 ve c≈98,85) train'de kalan %0,1'lik uç değerlere göre seçtik; kural yalnızca belirgin tutarsızlıkları yakalar.
- Alternatifler ve neden seçilmedi: Katı `PM2.5 ≤ PM10` (%8 yanlış alarm), kuralı hiç kullanmamak (bu hata türü kaçar).
- Projede nerede: `src/airq/edge/quality.py` (`PM_INCONSISTENT`)
- Sunumda tek cümle: Gerçek veride ince partikül bazen kaba partikülden büyük çıkıyor; toleransı veriden ölçüp kuralı ona göre gevşettik.

### SQLite (ve neden PostgreSQL/TimescaleDB değil)
- Ne: Tek dosyalık, kurulum gerektirmeyen veritabanı; WAL modunda yazıcı ve okuyucu aynı anda çalışabilir.
- Neden: Bir şehir ağı için saatte 12 satırlık yük SQLite'a çok küçük; ayrı sunucu kurmadan Windows'ta ve CI'da (Ubuntu) aynı şekilde çalışır. Tek yazıcı (ingest) kuralıyla yarış durumu yoktur; API salt-okunur bağlantı kullanır.
- Alternatifler ve neden seçilmedi: PostgreSQL/TimescaleDB (ayrı sunucu, kurulum ve bakım; bu ölçekte fayda yok, kapsam dışı). Ölçeklenme sınırı makalede (Sınırlamalar) açıkça yazıldı.
- Projede nerede: `src/airq/server/db.py`, `ingest.py`
- Sunumda tek cümle: Yükümüz saatte 12 satır; ayrı veritabanı sunucusu kurmak yerine WAL modundaki SQLite yetiyor, ölçek sınırını da açıkça belirtiyoruz.

### İnce notebook'lar (ve neden Colab iddia edilmiyor)
- Ne: Tüm mantık `src/airq/` paketindedir; notebook'lar yalnızca paket fonksiyonlarını çağırır (`scripts/build_notebooks.py` üretir).
- Neden: Mantığı notebook'a gömseydik iki kopya oluşur, biri sessizce bozulurdu; ince notebook'larda tek kopya vardır. `AIRQ_FIXTURE=1` küçük sentetik veriyle notebook'ları internetsiz (CI'da) çalıştırır, böylece her değişiklikte denenirler. Google Colab desteği kapsam dışı bırakıldı (kullanıcı kararı, 2026-11-20): kod yolları durur ama Colab'da doğrulanmadığı için README ve makale Colab desteği iddia etmez.
- Alternatifler ve neden seçilmedi: Mantığı notebook'ta yazmak (kopya ve sürüm kayması), Colab'ı doğrulamadan "destekliyoruz" demek (kanıtsız iddia).
- Projede nerede: `notebooks/`, `scripts/build_notebooks.py`, `src/airq/pipelines/colab.py`, `src/airq/data/fixture.py`
- Sunumda tek cümle: Notebook'lar ince; aynı paket kodunu çağırıyor ve CI'da sentetik veriyle her değişiklikte deneniyor; Colab'ı doğrulamadığımız için iddia etmiyoruz.

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

### Uygulama katmanında ağ emülasyonu, özel broker ve ayrı süreçler (RQ3a)
- Ne: Sensörden edge'e giden bağlantıdaki kaybı, gecikmeyi ve sıra bozulmasını yazılımla taklit ediyoruz; her ölçümde kendi Mosquitto'muzu başlatıp edge, ingest, predictor ve cihaz filosunu ayrı süreçler olarak çalıştırıyoruz.
- Neden: Gerçek bozuk ağ kurmak mümkün değil; yazılım emülasyonu kontrollü ve tekrarlanabilir (tohumlu). Kaybı mesajın hiç yayınlanmaması olarak modelledik, çünkü sensör-gateway radyo bağlantısında kaybolan mesajı MQTT'nin kendi yeniden iletimi kurtarmaz. Ayrı süreçler gerçek dağıtıma benzer ve süreç başına CPU/RAM ölçmeyi mümkün kılar; özel broker koşuları birbirinden yalıtır.
- Alternatifler ve neden seçilmedi: İşletim sistemi düzeyi `tc netem` (Windows'ta yok; kayıpta TCP kuyruk gecikmesini gösterirdi, bu bizim sınırlamamız), tek süreçte iş parçacıkları (GIL gecikmeyi bozar), paylaşılan broker (koşular birbirini etkiler).
- Projede nerede: `src/airq/devices/netem.py`, `src/airq/pipelines/rq3a.py`
- Sunumda tek cümle: Ağ bozulmasını kontrollü taklit edip gerçek servislerle ölçtük; kayıp arttıkça teslim oranı birebir düştü ve en yavaş halka tahmin servisi çıktı.

### Komut kanalı: MQTT `cmd`/`ack` ile cihaz ve edge kontrolü (Senaryo Kontrol)
- Ne: Demoda ve testlerde sensör değerini, hatalı girdiyi, ağ koşulunu ve edge filtresini canlı değiştirmek için dashboard'dan API'ye, oradan MQTT komutu olarak cihazlara gidiyoruz; her cihaz komutu uygulayıp `ack` ile cevap veriyor. Komutlar ve cevaplar veritabanında kayıt altında.
- Neden: Kontrol yolunu da IoT'nin kendi kanalından geçirmek, uzaktan cihaz yönetimini (komut, onay, hata cevabı) gösteriyor; "sahte düğme" yerine gerçek mesajlaşma. Her komut bir kimlikle (cmd_id) izlenir, geçersiz komut açık bir hata cevabı alır (ör. fiziksel sınırın dışındaki PM2.5 reddedilir, "hatalı girdi testi" işaretlenirse uygulanır). Müdahale mantığı MQTT'den bağımsız yazıldığı için broker olmadan test edilebiliyor, hata türleri RQ3b ile aynı fonksiyonu kullanıyor, böylece demo ile deney aynı davranıştır.
- Alternatifler ve neden seçilmedi: Dashboard'un verileri doğrudan değiştirmesi (IoT katmanını atlar, tahminler gerçek akışı yansıtmaz), HTTP ile cihaza komut (cihazlar zaten MQTT istemcisi, ikinci bir kanal gerekmez), komutları yalnızca bellekte tutmak (denetim izi kalmaz).
- Projede nerede: `src/airq/iot/schemas.py`, `src/airq/devices/modes.py`, `src/airq/devices/fleet.py`, `src/airq/server/control.py`
- Sunumda tek cümle: Sensörü, ağı ve edge filtresini canlı bozabiliyoruz; komut MQTT'den cihaza gidiyor, cihaz onaylıyor ve tahminin tepkisini ekranda görüyoruz.

### Hazır senaryolar (YAML), puan tablosu ve komut kaydından referans üretme
- Ne: Demoda tek tuşla çalışan, zamanlanmış komut listeleri (ör. "sensör 12 saat takılır, edge önce kapalı sonra açık") ve her müdahale için sonucu ölçen bir puan tablosu: uyarı verildi mi, doğru muydu, ne kadar önceden, tahmin ne kadar yanıldı. Her senaryonun yanında bir hipotez yazılı; sonuç hipotezle karşılaştırılıp açıkça "doğrulandı" ya da "çürütüldü" diye raporlanır.
- Neden: Canlı demoyu anlatıdan çıkarıp ölçülebilir bir deneye çeviriyor; "ne bekliyorduk, ne oldu" yan yana görünür ve sonuç beklentiye uydurulamaz. Yanıt doğruluğunu ölçmek için gerçek değeri bilmek gerekir: sensör hatası senaryolarında gerçek değer temiz kayıt, müdahale dünyayı değiştiriyorsa cihazın yayınladığı değerdir. İkincisini veritabanından okumak yanlış olurdu (edge filtresi yayınlanan değeri silebilir), bu yüzden komut kaydı cihazla aynı kod ile yeniden oynatılıyor.
- Alternatifler ve neden seçilmedi: Elle tarif edilen senaryolar (tekrarlanamaz, hipotez kayıt altında olmaz), referansı yalnızca veritabanından almak (edge filtresi açıkken gerçek değer görünmez), her senaryo için ayrı kod (YAML ile kullanıcı kendi senaryosunu şema doğrulamasıyla ekleyebilir).
- Projede nerede: `configs/scenarios/`, `src/airq/scenarios/`, `src/airq/server/scorecard.py`, `src/airq/server/truth.py`, `scripts/run_scenarios.py`
- Sunumda tek cümle: Her senaryoda önce ne olmasını beklediğimizi yazdık, sonra gerçek sistemde çalıştırıp ölçtük; 11 beklentiden biri çürüdü ve onu da olduğu gibi raporladık.

### Tek komutla demo (`demo.py`) ve tek komutla yeniden üretim (`run_all.py`)
- Ne: `demo.py` broker, edge, ingest, predictor, cihaz filosu, API ve panoyu tek komutla ayağa kaldırır, ısınmayı hızla geçip canlı akışa girer, Ctrl+C ile temiz kapatır. `run_all.py` ham veriden tüm tabloları ve şekilleri sırayla üretir; bitmiş aşamaları atlar ve sonunda her çıktının varlığını doğrular.
- Neden: Jüri önünde onlarca komut yazmak yerine tek komut ve ısınma beklemeden başlayan bir akış gerekir; her servis ayrı süreç olduğu için gerçek dağıtıma benzer ve biri çökerse hangisi olduğu logdan görünür. Yeniden üretim için tek giriş noktası, sonuçların "benim makinemde çalıştı"dan öteye geçmesini sağlar; ayrı bir `--home` içinde çalıştığı için depodaki gerçek sonuçları kazara ezmez, test setini koruyan kilit de her home için ayrıdır.
- Alternatifler ve neden seçilmedi: Docker Compose (Windows'ta ek kurulum ve ağ ayarı, demo makinesinde risk), Makefile (Windows'ta standart değil), her aşamayı elle çalıştırmak (sıra hatası ve unutulan aşama riski).
- Projede nerede: `src/airq/pipelines/demo.py`, `src/airq/pipelines/run_all.py`, `scripts/demo.py`, `scripts/run_all.py`
- Sunumda tek cümle: Tek komutla bütün sistemi açıyoruz; sonuçların hepsi de tek komutla ham veriden yeniden üretilebiliyor.

### Sonuç tablolarını koddan üretmek (`make_tables`)
- Ne: Makaledeki ve README'deki tüm sonuç tabloları, `reports/tables/*.csv` dosyalarından otomatik LaTeX ve Markdown'a çevrilir.
- Neden: Elle yazılan her sayı bir yanlış yazım riskidir ve sonuçla makale arasındaki bağı koparır. Tablo hücreleri CSV'den hesaplandığı için sonuç değişirse tablo da değişir; bir test hücreleri CSV ile çapraz kontrol eder.
- Alternatifler ve neden seçilmedi: Tabloları elle Word/LaTeX'e yazmak (uydurma ve unutulan güncelleme riski).
- Projede nerede: `src/airq/pipelines/tables.py`, `scripts/make_tables.py`
- Sunumda tek cümle: Makaledeki her tablo doğrudan sonuç dosyalarından üretiliyor; elle yazılmış sayı yok.

### Belirsizlik: LightGBM quantile modelleri ve q90 tabanlı uyarı (RQ4)
- Ne: Tek bir sayı yerine "gerçek değer %80 olasılıkla şu aralıkta" diyen bir tahmin aralığı üretiyoruz (alt ve üst yüzde 10'luk sınırlar için ayrı modeller) ve uyarıyı üst sınıra bağlayan bir varyantı normal uyarıyla karşılaştırıyoruz.
- Neden: Erken uyarıda kaçırmak yanlış alarmdan pahalıdır; üst sınır doğal olarak ihtiyatlıdır ve olay yakalamayı artırır. Aralığın gerçekten %80'i tutup tutmadığını ölçüyoruz; tutmuyorsa (ilk hali %76'ydı) tek bir katsayı yalnızca doğrulama verisinde öğrenilip test'e aynen uygulanır. Test'e bakmadan önce protokolü ve hipotezi yazdık, sonucu olduğu gibi raporlayıp aşırı tepelerde aralığın yetersiz kaldığını da gösterdik.
- Alternatifler ve neden seçilmedi: Gauss varsayımlı aralık (PM2.5 dağılımı çarpık, haze'de kalın kuyruk), bootstrap toplulukları (çok daha pahalı), ayrı bir derin model (ek bağımlılık, LightGBM zaten aynı özellikleri kullanıyor).
- Projede nerede: `src/airq/models/quantile.py`, `src/airq/pipelines/rq4.py`
- Sunumda tek cümle: Tahminin yanına güven aralığı koyduk; aralık orta kirlilikte güvenilir ama aşırı tepelerde yetersiz, üst sınırla uyarı daha fazla olayı yakalıyor ama daha çok yanlış alarm veriyor.

### Makale sayılarını koddan üretmek (`make_paper_numbers`, `check_paper`)
- Ne: Makale metnindeki her sonuç sayısı bir LaTeX makrosudur (`
RmseMtwobHOne`); makrolar `paper/numbers.tex` dosyasına `reports/tables/*.csv` hücrelerinden üretilir ve `paper/NUMBERS.md` her makroyu dosya, satır seçici ve sütunla eşler. `check_paper` LaTeX kurulu olmadan tanımsız makro, eksik kaynak, kırık `ef` ve özet uzunluğunu denetler.
- Neden: Elle yazılan her sayı bir yanlış yazım ve sonuçla makale arasında kopma riskidir (TALIMAT §11.4). Sonuç yeniden üretilirse makale sayıları da değişir; bir test, `numbers.tex`'in `reports/` ile eşit olduğunu denetler. Yazım sırasında bu yolla, taslağın bir iddiasını (kenar filtresinin "geri kazanım" yüzdesi) tablodaki 1 ondalıklı değerle uyuşmayacak biçimde yuvarlamam yakalandı.
- Alternatifler ve neden seçilmedi: Sayıları elle yazıp sonra kontrol etmek (kontrol unutulur), tabloların yanında metni de üretmek (metin yazımı için fazla katı).
- Projede nerede: `scripts/make_paper_numbers.py`, `scripts/check_paper.py`, `paper/numbers.tex`, `paper/NUMBERS.md`, `tests/unit/test_paper.py`
- Sunumda tek cümle: Makaledeki her sayı bir sonuç dosyasındaki bir hücreye bağlı; sonuç değişirse makale sayısı da değişiyor ve bir test bunu denetliyor.

### Kaynakça doğrulaması (Crossref, DataCite, arXiv)
- Ne: `paper/refs.bib` Ek A'dan üretildi; her DOI'li kaydın künyesi yayıncı kayıt sisteminden (Crossref) alınıp Ek A ile karşılaştırıldı, veri seti DataCite'tan, arXiv kayıtları arXiv'den doğrulandı. Kayıt kayıt sonuç `docs/makale_kaynak.md`'dedir.
- Neden: Uydurma ya da hatalı künye kabul edilemez (TALIMAT §11.5). Doğrulama gerçek bir hatayı yakaladı: R18'in yazar adları Ek A'da yanlıştı. Doğrulanamayan alan (LightGBM ve SHAP bildirilerinin sayfa numarası) tahmin edilmedi, atlandı.
- Alternatifler ve neden seçilmedi: Künyeleri hafızadan yazmak (hata ve uydurma riski), yalnızca Ek A'ya güvenmek (R18 hatası kalırdı).
- Projede nerede: `paper/refs.bib`, `docs/makale_kaynak.md`
- Sunumda tek cümle: Her kaynağın künyesini yayıncının kayıt sisteminden doğruladık; Ek A'daki bir yazar adı hatası böyle düzeldi.

### Optuna (TPE) ile hiperparametre araması
- Ne: LightGBM'in ayarlarını (yaprak sayısı, öğrenme hızı, düzenleme gibi) doğrulama verisinde, önceki denemelerden öğrenen bir yöntemle (TPE) arayan kütüphane; her ufuk ve komşu sayısı için ayrı bir çalışma, çalışma başına 20 deneme.
- Neden: Varsayılan ayarlar iyi ama en iyisi değil (h=1/k=0 çalışmasında varsayılana göre doğrulama RMSE'si %3,0 düştü: 22,55 → 21,87). Izgara araması çok pahalıdır, rastgele arama geçmişten öğrenmez; TPE az denemede iyi sonuca varır. Seçim yalnızca doğrulamada yapılır, test'e hiç bakılmaz. Bütçeyi 20'de bıraktık çünkü arama yakınsadı: 9 çalışmada 10. ile 20. deneme arasındaki ortalama kazanç %0,5 (`reports/tables/rq1_tuning_convergence.csv`); 40 deneme koşulan tek çalışmada en iyi sonuç ilk 20'de bulundu. Sonuçlar tekrar üretilebilir: temiz bir çalışma deposuyla 9 çalışmanın 8'i birebir tekrarlandı, dokuzuncusunun kayıtlı çalışmada yarım kalmış bir denemeden saptığı bulundu ve düzeltildi.
- Alternatifler ve neden seçilmedi: Izgara (ayar sayısıyla üstel büyür), rastgele arama (geçmişten öğrenmez), elle ayar (tekrar edilemez ve test'e bakma riski), 40 deneme (kazanç ölçüm gürültüsünün altında, her sayıyı yeniden üretmeyi gerektirirdi).
- Projede nerede: `src/airq/pipelines/tuning.py`, `scripts/tuning_convergence.py`, `reports/tables/rq1_tuning.csv`
- Sunumda tek cümle: Ayarları test'e bakmadan, yalnızca doğrulamada ve 20 denemeyle seçtik; 10'dan 20'ye çıkmanın kazancı %0,5 olduğu için daha fazla denemedik.

### Sürüm paketleri, sağlama toplamı ve `fetch_release`
- Ne: Eğitilmiş modeller ve kayıtlı bir demo koşusu depoya değil GitHub Release'e yüklenir (`airq_models.zip`, `demo_recorded.db`); `fetch_release` bunları indirir, SHA-256 sağlama toplamını `configs/release.yaml`'daki değerle karşılaştırır ve zip içindeki yollar hedef klasörün dışına çıkıyorsa reddeder.
- Neden: Depo küçük kalır (>5 MB dosya yok) ama jüri veya yeni bir kullanıcı ham veri ve eğitim beklemeden demoyu açabilir. Sağlama toplamı, bozuk ya da değiştirilmiş bir dosyanın sessizce kullanılmasını engeller; hedef klasörün dışına yazmaya çalışan yollar içeren bir zip dosyası (zip-slip saldırısı) reddedilir.
- Alternatifler ve neden seçilmedi: Modelleri depoya eklemek (boyut ve geçmiş şişer), sağlama toplamsız indirme (bozuk dosya fark edilmez), Git LFS (ek kurulum).
- Projede nerede: `src/airq/pipelines/release.py`, `scripts/fetch_release.py`, `scripts/make_release_assets.py`, `configs/release.yaml`
- Sunumda tek cümle: Büyük dosyaları Release'e koyduk ve indirirken sağlama toplamıyla doğruluyoruz; böylece depo küçük, demo ise tek komut.

### Güvenlik sertleştirme (yerel kullanım için)
- Ne: Broker, API ve pano yalnızca `127.0.0.1`'de dinler; API yalnızca yerel `Host` başlıklarını kabul eder ve yerel olmayan bir `Origin` ile gelen durum değiştiren istekleri reddeder (DNS rebinding ve CSRF); MQTT'den gelen istasyon adı ve etiketler panoda HTML'e kaçışlanır; `.gitignore` gizli anahtar dosyalarını engeller; tarama (`bandit`, `pip-audit`, `detect-secrets`) CI'dadır.
- Neden: Komut kanalı kimlik doğrulamasızdır (bilinen sınırlama), bu yüzden tek koruma onu dış dünyaya açmamaktır. Güvenlik denetimi gerçek açıklar buldu: pano MQTT'den gelen metni HTML'e ham basıyordu (XSS), Streamlit ağa açık dinleyebiliyordu, API'de Host/Origin denetimi yoktu; üçü düzeltildi ve testlerle (`tests/unit/test_security.py`) korunuyor. Tam geçmiş taramasında hiçbir zaman gizli anahtar ya da `.env` commit'lenmediği görüldü.
- Alternatifler ve neden seçilmedi: Tam kimlik doğrulama ve TLS (bu proje yerel bir öğretim sistemi; gerçek dağıtım için gelecek çalışma), güvenliği hiç ele almamak (jüri sorusu ve gerçek açıklar).
- Projede nerede: `src/airq/server/api.py`, `src/airq/dashboard/data.py`, `.streamlit/config.toml`, `SECURITY.md`, `tests/unit/test_security.py`
- Sunumda tek cümle: Sistem kimlik doğrulamasız olduğu için yalnızca yerel makineye açık; bunu testle koruyoruz ve bir güvenlik taramasında bulduğumuz üç açığı düzelttik.

### Kalite kapıları: mypy, kapsama eşiği, dal koruması, Dependabot
- Ne: Çekirdek modüllerde tip denetimi (`mypy`), test kapsamında alt sınır (%60), `main` için "PR ve yeşil CI" kuralı, bağımlılık güncellemeleri için Dependabot ve sürümleri sabitleyen `constraints.txt`.
- Neden: Sonuçların "benim makinemde çalıştı"dan öteye geçmesi için hatalar commit'ten önce yakalanmalı. Bu işe yaradı: CI, bir commit'te iki gerçek hata yakaladı (gizli anahtar taramasının yanlış alarmı ve ML kurulumunda MQTT bağımlılığı), ikisi de aynı gün düzeltildi.
- Alternatifler ve neden seçilmedi: Yalnızca yerel kontrol (unutulur), tüm kodda katı tip denetimi (bu süre içinde gerçekçi değil; çekirdek modüllerle başladık).
- Projede nerede: `pyproject.toml`, `.github/workflows/ci.yml`, `.github/dependabot.yml`, `constraints.txt`
- Sunumda tek cümle: Her değişiklikte testler, tip denetimi ve güvenlik taraması çalışıyor; bunlar bir commit'teki iki gerçek hatayı yakaladı.
