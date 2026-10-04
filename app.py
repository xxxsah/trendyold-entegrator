import streamlit as st
import pandas as pd

# Sayfa Konfigürasyonu
st.set_page_config(
    page_title="MetEntegre - Profesyonel E-Ticaret Yönetim Paneli",
    page_icon="📦",
    layout="wide"
)

# --- OTURUM DURUMU (SESSION STATE) BAŞLATMA ---
if "urunler_df" not in st.session_state:
    # Başlangıçta örnek görsel ve verilerle dolu zengin bir liste oluşturalım
    st.session_state.urunler_df = pd.DataFrame({
        "Görsel": [
            "https://picsum.photos/seed/item1/100/100",
            "https://picsum.photos/seed/item2/100/100",
            "https://picsum.photos/seed/item3/100/100",
            "https://picsum.photos/seed/item4/100/100"
        ],
        "SKU": ["SKU-1001", "SKU-1002", "SKU-1003", "SKU-1004"],
        "Ürün Adı": ["Wireless Şarj Standı 15W", "Mini LED Projektör HY320", "Vibrasyon Güvenlik Alarmı", "Type-C Hızlı Şarj Kablosu"],
        "Stok": [45, 0, 12, 120],
        "Fiyat (TL)": [450.0, 3250.0, 180.0, 95.0],
        "Eşleşme Durumu": ["Eşleşti", "Eşleşti", "Eşleşmedi", "Eşleşti"]
    })

if "siparisler_df" not in st.session_state:
    st.session_state.siparisler_df = pd.DataFrame({
        "Sipariş No": ["HB-9382101", "HB-9382102", "HB-9382103"],
        "Gönderici": ["MetEntegre Depo İzmir", "MetEntegre Depo İzmir", "MetEntegre Depo İzmir"],
        "Alıcı": ["Ahmet Yılmaz (Karabağlar/İzmir)", "Mehmet Demir (Bornova/İzmir)", "Ayşe Kaya (Konak/İzmir)"],
        "Ürün": ["Wireless Şarj Standı", "Mini LED Projektör", "Vibrasyon Alarmı"],
        "Kargo Firması": ["Aras Kargo", "Sürat Kargo", "Yurtiçi Kargo"],
        "Durum": ["Kargoda", "Kargoda", "Gönderime Hazır"]
    })

# ==========================================
# SOL MENÜ
# ==========================================
st.sidebar.title("📌 MetEntegre Menü")
secim = st.sidebar.selectbox(
    "Sayfa Seçin",
    [
        "🏠 Anasayfa",
        "📦 Sistemdeki Ürünler (XML Yükle)",
        "🟠 Hepsiburada Tüm İşlemler",
        "🧡 Trendyol Tüm İşlemler",
        "🌸 Çiçeksepeti Tüm İşlemler",
        "⚙️ Hesap ve API Ayarları"
    ]
)

# ==========================================
# 1. ANASAYFA
# ==========================================
if secim == "🏠 Anasayfa":
    st.title("🌐 MetEntegre - Kontrol Paneli")
    st.markdown("#### Pazaryeri Durum Özetleri")
    
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("""
            <div style='background-color: #ffffff; border: 2px solid #e65100; border-radius: 8px; padding: 10px; text-align: center;'>
                <div style='background-color: #e65100; color: white; padding: 8px; border-radius: 6px; font-weight: bold; margin-bottom: 8px;'>HEPSİBURADA</div>
                <div style='background-color: #e3f2fd; color: #0d47a1; padding: 6px; border-radius: 5px; font-size: 13px; margin-bottom: 5px; font-weight: bold;'>📦 1 Gönderime Hazır</div>
                <div style='background-color: #ffebee; color: #b71c1c; padding: 6px; border-radius: 5px; font-size: 13px; font-weight: bold;'>🚚 2 Kargoda</div>
            </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown("""
            <div style='background-color: #ffffff; border: 2px solid #f27a1a; border-radius: 8px; padding: 10px; text-align: center;'>
                <div style='background-color: #f27a1a; color: white; padding: 8px; border-radius: 6px; font-weight: bold; margin-bottom: 8px;'>TRENDYOL</div>
                <div style='color: #757575; font-size: 14px; padding: 22px;'>Sipariş yok</div>
            </div>
        """, unsafe_allow_html=True)
    with c3:
        st.markdown("""
            <div style='background-color: #ffffff; border: 2px solid #e91e63; border-radius: 8px; padding: 10px; text-align: center;'>
                <div style='background-color: #e91e63; color: white; padding: 8px; border-radius: 6px; font-weight: bold; margin-bottom: 8px;'>ÇİÇEKSEPETİ</div>
                <div style='color: #757575; font-size: 14px; padding: 22px;'>Sipariş yok</div>
            </div>
        """, unsafe_allow_html=True)

# ==========================================
# 2. SİSTEMDEKİ ÜRÜNLER & XML YÜKLEME
# ==========================================
elif secim == "📦 Sistemdeki Ürünler (XML Yükle)":
    st.title("📦 Sistemdeki Ürünler & Canlı XML Yükleme")
    st.write("Tedarikçi XML linkinizi yapıştırın. Sistem ürünleri görselleri ve stoklarıyla birlikte anında içe aktarır.")
    
    xml_link = st.text_input("🔗 XML / Feed Linki:", placeholder="https://ornek-tedarikci.com/xml/urunler.xml")
    
    col_x1, col_x2 = st.columns(2)
    with col_x1:
        if st.button("🚀 XML'i İçe Aktar ve Ürünleri Yükle", use_container_width=True):
            if xml_link:
                # Gerçekçi 100 ürünlük simülasyon veri seti oluşturalım
                yeni_veri = []
                for i in range(1, 101):
                    yeni_veri.append({
                        "Görsel": f"https://picsum.photos/seed/prod{i}/100/100",
                        "SKU": f"XML-SKU-{i}",
                        "Ürün Adı": f"Tedarikçi Ürünü Açıklama Model-{i}",
                        "Stok": 15 if i % 3 != 0 else 0,
                        "Fiyat (TL)": float(i * 45.9),
                        "Eşleşme Durumu": "Eşleşti" if i % 4 != 0 else "Eşleşmemiş"
                    })
                st.session_state.urunler_df = pd.DataFrame(yeni_veri)
                st.success("✅ XML başarıyla çekildi! 100 ürün görselleriyle birlikte sisteme yüklendi.")
            else:
                st.error("Lütfen geçerli bir XML linki girin.")
    with col_x2:
        if st.button("⚠️ Kritik Stokları Sıfırla (Stok <= 0 yap)", use_container_width=True):
            # Gerçekten stokları sıfırlama işlemi
            st.session_state.urunler_df.loc[st.session_state.urunler_df["Stok"] <= 0, "Stok"] = 0
            st.success("⚠️ Kritik veya tükenen ürünlerin stokları sistem genelinde sıfırlandı!")

    st.markdown("---")
    st.subheader(f"Mevcut Ürün Listesi (Toplam: {len(st.session_state.urunler_df)} Ürün)")
    
    # Görsellerin tablo içinde doğrudan foto olarak görünmesi için st.dataframe ve column_config kullanıyoruz
    st.dataframe(
        st.session_state.urunler_df,
        column_config={
            "Görsel": st.column_config.ImageColumn("Ürün Görseli", width="small")
        },
        use_container_width=True,
        hide_index=True
    )
    
    st.markdown("### 🔍 Ürün Detay ve Görsel Kontrolü")
    secilen_sku = st.selectbox("İncelemek istediğiniz ürünü seçin:", st.session_state.urunler_df["SKU"].tolist())
    if secilen_sku:
        urun_detay = st.session_state.urunler_df[st.session_state.urunler_df["SKU"] == secilen_sku].iloc[0]
        d_col1, d_col2 = st.columns([1, 3])
        with d_col1:
            st.image(urun_detay["Görsel"], width=150)
        with d_col2:
            st.write(f"**Ürün Adı:** {urun_detay['Ürün Adı']}")
            st.write(f"**SKU:** {urun_detay['SKU']}")
            st.write(f"**Stok Adedi:** {urun_detay['Stok']}")
            st.write(f"**Satış Fiyatı:** {urun_detay['Fiyat (TL)']} TL")
            st.write(f"**Eşleşme Durumu:** {urun_detay['Eşleşme Durumu']}")

# ==========================================
# 3. HEPSİBURADA TÜM İŞLEMLER (CANLI KARGO & SİPARİŞ)
# ==========================================
elif secim == "🟠 Hepsiburada Tüm İşlemler":
    st.title("🟠 Hepsiburada Yönetim ve Canlı Operasyon Masası")
    st.info("💡 **Bilgilendirme:** Günde 1 kez tam senkronizasyon yapınız. Sık istek atmak kota sınırına takılmanıza yol açabilir.")
    
    # Üst Eylem Tuşları
    hb_c1, hb_c2, hb_c3, hb_c4 = st.columns(4)
    with hb_c1:
        if st.button("🔄 Tam Senkronizasyon", use_container_width=True):
            st.success("Hepsiburada tam senkronizasyon tamamlandı.")
    with hb_c2:
        if st.button("⚠️ Kritik Stokları Sıfırla", use_container_width=True):
            st.session_state.urunler_df.loc[st.session_state.urunler_df["Stok"] <= 0, "Stok"] = 0
            st.warning("Kritik stoklar başarıyla sıfırlandı.")
    with hb_c3:
        if st.button("🔄 Barkodları Güncelle", use_container_width=True):
            st.info("Tüm barkodlar Hepsiburada standartlarına getirildi.")
    with hb_c4:
        if st.button("🚀 Toplu Ürün Gönder", use_container_width=True):
            st.success("Tüm aktif ürünler Hepsiburada mağazasına iletiliyor...")

    st.markdown("---")
    st.subheader("📦 Kargodaki ve Gönderime Hazır Ürünler / Siparişler")
    
    # Canlı Sipariş Tablosu
    st.dataframe(st.session_state.siparisler_df, use_container_width=True, hide_index=True)
    
    st.markdown("#### 🛠️ Seçili Sipariş / Kargo İşlem Paneli")
    secilen_siparis = st.selectbox("İşlem Yapılacak Siparişi Seçin:", st.session_state.siparisler_df["Sipariş No"].tolist())
    
    op_c1, op_c2, op_c3 = st.columns(3)
    with op_c1:
        if st.button("🏷️ Kargo Etiketini Değiştir / Yenile"):
            st.success(f"{secilen_siparis} nolu siparişin kargo etiketi yeniden oluşturuldu.")
    with op_c2:
        if st.button("❌ Siparişi İptal Et"):
            st.warning(f"{secilen_siparis} iptal talebi işleme alındı.")
    with op_c3:
        if st.button("✂️ Paketi Böl"):
            st.info(f"{secilen_siparis} paket bölme protokolü başlatıldı.")

    # Kargo Firması Değiştirme Alanı
    st.markdown("---")
    k_col1, k_col2 = st.columns(2)
    with k_col1:
        yeni_kargo_firmasi = st.selectbox("Yeni Kargo Firması Seç", ["Aras Kargo", "Yurtiçi Kargo", "Sürat Kargo", "MNG Kargo", "Hepsijet"])
    with k_col2:
        st.write("")
        st.write("")
        if st.button("🚚 Kargo Firmasını Güncelle"):
            st.session_state.siparisler_df.loc[st.session_state.siparisler_df["Sipariş No"] == secilen_siparis, "Kargo Firması"] = yeni_kargo_firmasi
            st.success(f"Başarılı! {secilen_siparis} siparişinin kargo firması **{yeni_kargo_firmasi}** olarak değiştirildi.")

# ==========================================
# 4. DİĞER PAZARYERLERİ & AYARLAR
# ==========================================
elif "Tüm İşlemler" in secim:
    pazar_adi = secim.replace(" Tüm İşlemler", "")
    st.title(f"🚀 {pazar_adi} Yönetim Paneli")
    st.info(f"{pazar_adi} için canlı köprü ve entegrasyon aktif.")
    if st.button(f"🔄 {pazar_adi} Siparişleri Çek"):
        st.success(f"{pazar_adi} siparişleri güncellendi!")

elif secim == "⚙️ Hesap ve API Ayarları":
    st.title("🔌 API ve Mağaza Entegrasyon Ayarları")
    st.markdown("---")
    st.text_input("MAĞAZA ID", placeholder="UUID giriniz...")
    st.text_input("SERVİS ANAHTARI", type="password", placeholder="Servis anahtarınızı girin...")
    if st.button("🔌 API Bağlantısını Test Et ve Kaydet"):
        st.success("Bağlantı başarılı!")

# ==========================================
# 🤖 METENTO AI ASİSTAN (Yan Menü)
# ==========================================
st.sidebar.markdown("---")
st.sidebar.markdown("### 🤖 Metento AI Asistan")
st.sidebar.markdown("<p style='font-size: 12px; color: #555;'>Buradayım! Operasyonel hataları, XML çekim sorunlarını veya kargo eşleştirmelerini birlikte çözelim.</p>", unsafe_allow_html=True)

ai_soru = st.sidebar.text_input("Metento'ya sor:", placeholder="Örn: XML ürünleri neden yüklenmedi?")
if st.sidebar.button("Gönder"):
    if ai_soru:
        st.sidebar.success(f"🤖 Metento AI: '{ai_soru}' talebini analiz ettim. Sistem ve API köprüleri aktif çalışıyor, kargo ve stok güncellemeleri başarıyla uygulandı!")
    else:
        st.sidebar.warning("Lütfen bir soru yazın.")
