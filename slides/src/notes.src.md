# Konuşmacı notları

Ezber metin değil, anahtar noktalar listesi (TALIMAT §12.0): her slaytı kendi cümlelerinle anlat. Her teknik slaytta
**Söyle:** satırı, hocanın istediği "neyi neden kullandınız" cümlesidir. Bu dosya `slides/src/notes.src.md`'den
üretilir; sayılar `paper/numbers.tex` makrolarından gelir.

## 1. Başlık (0,3 dk)
- Kendini ve ortağını tanıt; dersin adı: Nesnelerin İnterneti
- Tek cümle: "Hava kirliliği tahminini, ölçümü taşıyan IoT hattıyla birlikte ölçtük."

## 2. Problem (0,7 dk)
- PM2.5 izleme düşük maliyetli sensör ağlarına dayanıyor; tahmin ve erken uyarı karar için gerekli
- Sensörler bozulur, mesajlar kaybolur: çoğu çalışma bunu hiç ölçmez
- **Söyle:** "Model iyi olsa bile hat bozulursa uyarı çalışır mı? Bunu ölçtük."
- Geçiş: "Bunun için bir sistem kurduk."

## 3. Sorular ve katkılar (0,7 dk)
- RQ1-RQ4'ü sırayla say; ayrıntıya girme
- Katkılar: K1 sızıntısız tahmin ve ablasyon, K2 erken uyarı, K3 ağ ve veri kalitesinin etkisi
- Dürüst ifade: "Taramamızda bu birleşimi ölçen bir hava kalitesi çalışması bulamadık" ("ilk" deme)

## 4. Mimari (1 dk)
- Şekli soldan sağa izle: cihaz → broker → edge → ingest/SQLite → tahmin → API → pano
- Komut kanalını göster: aynı hat, ters yön
- **Söyle:** "Fiziksel sensörümüz yok; gerçek ölçümleri sanal cihazlarla yeniden oynatıyoruz. Bu emülasyon, saha çalışması değil."

## 5. MQTT tasarımı ve edge (1,2 dk)
- Neden MQTT: hafif, yayıncı-abone, cihaz kopmasını kendisi bildirir (LWT)
- QoS 1: mesaj kaybolmasın; bedeli tekrar; idempotent kayıt zararsız kılar; tekrar oranı {{nDupRateMax}}
- Edge: bozuk değeri sunucuya varmadan işaretler; filtre açıkken `null`
- **Söyle:** "QoS 0'da kayıp sessiz olurdu; QoS 1'in tekrarını kayıt anında eliyoruz."

## 6. Veri ve sızıntısız değerlendirme (0,8 dk)
- "R²=0,99 gören sızıntıdan şüphelenmeli": rastgele bölme, tüm veride ölçekleme
- Bizim R²: 1 saatte {{nRTwoMtwobHOne}}, 24 saatte {{nRTwoMtwobHTwentyFour}}: ufuk uzadıkça düşer, bu dürüstlük işareti
- Test dönemi bir kez; tek istisnayı bilerek söyle (yeniden üretilebilirlik düzeltmesi, makalede yazılı)
- **Söyle:** "Gerçek sistem geleceği bilmez; modelin de bilmemesini testlerle zorunlu kıldık."

## 6a. Neyi neden kullandık (0,8 dk)
- Tabloyu satır satır okuma; 3 örnek seç: MQTT, SQLite, LightGBM
- Hazırlıklı ol: her satırın arkasında `docs/NEDEN.md` girişi var; jüri hangisini sorarsa oradan anlat
- **Söyle:** "Her seçimin alternatifini de değerlendirdik; tabloda ikinci sütun seçmediğimiz yol."

## 7. Canlı demo (3,5 dk)
- Başlatma: tek komut; bu sırada bir cümle: "Beş süreç ayağa kalkıyor"
- A) `gercek_haze_replay`: tahmin yükselir, uyarı epizottan önce çıkar; sonra `sensor_takilmasi`: edge kapalı/açık farkı; `cihaz_kopmasi`: kartlar offline (LWT); `ag_bozulmasi`: teslim oranı düşer, sistem çalışır
- B) Serbest test: jüriden istasyon ve değer iste; geçersiz değer reddedilir; "Sıfırla" her zaman çalışır
- Çökerse: `--offline` + GIF + ekran görüntüleri; panik yok, "yedek planımız var" de
- **Söyle:** "Komut da MQTT'den gidiyor: cihaz uygular, ack ile yanıtlar."

## 8. RQ1 (0,8 dk)
- Persistence'a göre %{{nImprMtwobHOne}} / %{{nImprMtwobHSix}} / %{{nImprMtwobHTwentyFour}}
- Komşular 1 ve 6 saatte anlamlı, 24 saatte değil
- Olumsuz sonuç söyle: aşırı olaylarda düşük tahmin, 24 saatte persistence'ın gerisinde
- **Söyle:** "Komşuların işe yaradığını varsaymadık, ablasyonla ölçtük."

## 9. RQ2 (0,8 dk)
- Kuralı bir cümlede: tahmin eşiğin δ altına inince uyar; δ doğrulamada, F2 ile
- 1 ve 6 saatte iyi; 24 saatte persistence'ın gerisinde: dürüstçe söyle
- q90 uyarı: recall artar, yanlış alarm da artar (takas)
- **Söyle:** "Olay kaçırmak yanlış alarmdan pahalı olduğu için F2 kullandık."

## 10. RQ3 (1,2 dk)
- %20 kayıpta 1 saatlik hata artışı +{{nDmgTwenty}} µg/m³: tahmin yavaş bozulur
- Asıl bulgu: {{nSpeedSlow}}× hızda servis geride kalıyor ({{nBehindTwenty}}/{{nRunsTwenty}} koşu)
- Edge filtresi: persistence'ta %{{nRobRecPersistHOne}}, LightGBM'de %{{nRobRecMtwobHOne}} geri kazanım; her modelde aynı etki değil
- **Söyle:** "Ağı yazılımla emüle ettik: kontrollü ve tekrarlanabilir; gerçek ağ değil."

## 10a. Ölçümün bulduğu kusur (0,5 dk)
- 500 ms bekleme, çevrimdışı cihazı her saat bekletiyordu: {{nOffLatOneBefore}} s → {{nOffLatOneAfter}} s
- Mesaj kaybında düzelmez: bunu da söyle
- **Söyle:** "Bu kusuru ancak sistemi ağ koşullarıyla birlikte ölçerek bulduk."

## 11. Sınırlamalar (0,4 dk)
- Hızlı say: emülasyon, referans veri, sentetik hata, tek şehir, güvenlik yok
- Sınırlamayı kendin söylersen jüri sormaz

## 12. Sonuç (0,4 dk)
- Tek cümle özet + gelecek çalışma (saha testi, TLS, GNN)
- Depo ve makale adresini göster

## 13. Sorular
- `slides/qa.md`'yi hazır tut; bilmediğini "ölçmedik" diye söyle, uydurma

## Yedek slaytlar (B1-B7)
- Sorulursa aç: hiperparametre, aşırı olay, LOSO, RQ4, literatür, senaryolar, güvenlik
