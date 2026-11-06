# SAP2000 2D Eğri/Sürekli Hat Joint Local Axes Hizalama Aracı - Geliştirme Planı

Bu proje, SAP2000'de 2 boyutlu (XY düzlemi) kırıklı eğriler (curved segments) ve doğrulardan (lines) oluşan bir geometri üzerindeki düğüm noktalarının (joint) yerel eksenlerini (Local Axes), komşu noktaların oluşturduğu kirişe dik ve dışa doğru olacak şekilde topluca güncelleyen bir otomasyon aracıdır.

## 1. Veri Yapısı, Girdi Doğrulama ve Koordinat Çekme (Kritik Öncelik - Temel)
- [x] **SAP2000 OAPI Bağlantı Modülü:** Aktif SAP2000 인스턴sına (`SapObject` -> `SapModel`) bağlanan ve bağlantı hatası durumunda anlamlı uyarı döndüren yapıyı kur.
- [x] **Kullanıcı Sıralı Joint Listesi Girdisi:** Kullanıcının sıralı olarak girdiği Joint ID listesini (virgülle ayrılmış metin veya liste formatında: `[J1, J2, J3, ..., Jn]`) alacak veri yapısını oluştur. Minimum 2 joint girildiğini doğrula (`n >= 2`).
- [x] **Koordinatların Okunması:** Listedeki her bir joint için `SapModel.PointObj.GetCoordCartesian(name, x, y, z)` fonksiyonunu çağırarak $(X, Y, Z)$ koordinatlarını çek ve sıralı bir veri yapısında (liste/sözlük) sakla. Modelde bulunamayan bir Joint ID varsa işlemi durdurup hatalı ID'yi bildir.

## 2. 2B Vektör Matematiği ve Teğet/Normal Hesabı (Kritik Öncelik - Çekirdek Algoritma)
- [x] **Hayali Kiriş (Teğet) Vektörünün ($\vec{T}$) Hesaplanması:** Sıralı listedeki her $i$ noktası için XY düzleminde ($\Delta X, \Delta Y$) teğet vektörünü şu kurallara göre hesapla:
  - [x] **İlk Nokta ($i = 0$):** İleri fark yöntemi kullan: $\vec{T}_0 = P_1 - P_0 = (X_1 - X_0, Y_1 - Y_0)$
  - [x] **Ara Noktalar ($0 < i < n-1$):** Merkezi fark (komşu noktaları birleştiren hayali çizgi) yöntemi kullan: $\vec{T}_i = P_{i+1} - P_{i-1} = (X_{i+1} - X_{i-1}, Y_{i+1} - Y_{i-1})$
  - [x] **Son Nokta ($i = n-1$):** Geri fark yöntemi kullan: $\vec{T}_{n-1} = P_{n-1} - P_{n-2} = (X_{n-1} - X_{n-2}, Y_{n-1} - Y_{n-2})$
- [x] **Sıfır Vektör (Çakışık Nokta) Kontrolü:** Eğer $\vec{T}_i$ vektörünün boyu sıfıra çok yakınsa ($\sqrt{\Delta X^2 + \Delta Y^2} < 10^{-6}$), sıfıra bölme hatasını önlemek için bir önceki geçerli açıyı koru veya uyarı ver.
- [x] **Dik (Normal) Vektörün ($\vec{N}$) Elde Edilmesi:** 2B düzlemde $\vec{T} = (\Delta X, \Delta Y)$ vektörüne dik olan birim normal vektörü hesapla:
  - [x] Standart sağ el dönüşü (saat yönünün tersi Gidişe göre Dış/Sağ): $\vec{N} = (\Delta Y, -\Delta X)$
  - [x] Alternatif (Ters) dönüş: $\vec{N}_{rev} = (-\Delta Y, \Delta X)$

## 3. "Dışa Doğru" (Outward) Yön Tespiti ve Tutarlılık (Yüksek Öncelik)
- [x] **Otomatik Konvekslik (Dışbükeylik) Analizi:** Eğrinin "dış" tarafını otomatik bulmak için ara noktalarda ($0 < i < n-1$) kiriş orta noktası $M_i = \frac{P_{i-1} + P_{i+1}}{2}$ ile mevcut nokta $P_i$ arasındaki fark vektörünü ($\vec{C}_i = P_i - M_i$) hesapla.
- [x] **Yön Doğrulama (Dot Product Kontrolü):** Hesaplanan normal vektör $\vec{N}$ ile eğrilik vektörü $\vec{C}_i$'nin skaler çarpımına ($\vec{N} \cdot \vec{C}_i$) bak. Çoğunluk negatifse, tüm hat boyunca tutarlılığı bozmamak adına tüm normal vektörleri $(-1)$ ile çarparak dışa bakacak şekilde sabitle.
- [x] **Manuel Yön Çevirme (Reverse Direction) Bayrağı:** Düz (line) segmentlerin ağırlıkta olduğu veya S çizen geometrilerde kullanıcının tek tıkla "Dış / İç" yönünü 180 derece tersine çevirebilmesi için algoritmaya `reverse_normal: bool = False` parametresi ekle.

## 4. Açı Hesabı ve SAP2000 Local Axes Ataması (Yüksek Öncelik - API Entegrasyonu)
- [x] **Global X ile Yapılan Açının ($\theta$) Bulunması:** Her joint için elde edilen nihai $\vec{N} = (N_x, N_y)$ vektörünün Global X ekseniyle yaptığı açıyı `atan2(Ny, Nx)` fonksiyonu ile radyan cinsinden bul ve dereceye ($\text{Degrees}$) çevir. Açıyı $[-180^\circ, 180^\circ]$ veya $[0^\circ, 360^\circ]$ aralığında normalize et.
- [x] **SAP2000 Local Axes Güncellemesi:** Her bir joint için `SapModel.PointObj.SetLocalAxes(name, A, B, C)` fonksiyonunu çağır:
  - [x] `A = theta` (Z ekseni etrafında dönüş açısı - derece)
  - [x] `B = 0.0`
  - [x] `C = 0.0`
- [x] **Ekranı Yenileme:** Tüm atamalar bittikten sonra SAP2000 arayüzünde güncel eksen oklarının görünmesi için `SapModel.View.RefreshView(0, False)` fonksiyonunu çağır.

## 5. Kullanıcı Arayüzü (UI) / Kullanım Akışı (Orta Öncelik)
- [x] **Girdi Alanı:** Kullanıcının sıralı joint isimlerini girebileceği bir metin kutusu (örn: `1, 2, 3, 4, 5, 6` veya her satıra bir joint).
- [x] **SAP2000 Seçiminden Çekme (Opsiyonel Yardımcı):** Kullanıcının SAP2000 ekranında seçtiği jointleri `SapModel.SelectObj.GetSelected()` ile çekip girdi kutusuna aktaran bir buton (kullanıcı sıralamayı kutu içinde düzenleyebilmeli).
- [x] **Yön Seçimi (Checkbox):** "Yönü Ters Çevir (Invert/Reverse Outward Direction)" seçeneği.
- [x] **Önizleme / Log Tablosu:** İşlem uygulandığında her bir Joint ID, hesaplanan Teğet Vektörü, Normal Vektörü ve atanan `A` açısını (derece) gösteren bir sonuç/log listesi.

## 6. Hata Yönetimi ve Uç Durum Testleri (Düşük Öncelik - Kalite Kontrol)
- [x] **Doğrusal (Collinear) Segment Testi:** Eğri ile düz çizginin (line) birleştiği geçiş noktalarında ve tamamen düz olan ara segmentlerde ($\vec{C}_i = 0$ olduğunda) yönün aniden 180 derece dönmediğini (tutarlı kaldığını) doğrula.
- [x] **Birim Bağımsızlığı:** Koordinat farkları üzerinden oran (`atan2`) alındığı için SAP2000 mevcut birim sisteminden (kN-m, N-mm vb.) bağımsız çalıştığını doğrula.
- [x] **İşlem Sonucu Raporlama:** Kaç adet jointin başarıyla güncellendiğini ve varsa hata alınan jointleri kullanıcıya özet olarak bildir.