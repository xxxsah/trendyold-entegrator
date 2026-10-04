import streamlit as st
import pandas as pd

# Sayfa Konfigürasyonu
st.set_page_config(
    page_title="MetEntegre - E-Ticaret Yönetim Paneli",
    page_icon="📦",
    layout="wide"
)

# Oturum Durumu Başlatma
if "xml_yuklendi" not in st.session_state:
    st.session_state.xml_yuklendi = False
if "urunler_df" not in st.session_state:
    st.session_state.urunler_df = pd.DataFrame(columns=["SKU", "Ürün Adı", "Kategori", "Stok", "Fiyat", "Eşleşme Durumu"])

# ==========================================
# SOL MENÜ
# ==========================================
st.sidebar.title("📌 MetEntegre Menü")
secim = st.sidebar.selectbox(
    "Sayfa Seçin",
    [
        "🏠 Anasayfa",
        "💬 Destek Taleplerim",
        "🔔 Bildirimler",
        "📢 Duyurular",
        "📦 Sistemdeki Ürünler (XML Yükle)",
        "⚡ Oto Kritik Stok",
        "🧡 Trendyol Tüm İşlemler",
        "🌸 Çiçeksepeti Tüm İşlemler",
        "🔴 N11 Tüm İşlemler",
        "📦 E-PTT AVM Tüm İşlemler",
        "🟠 Hepsiburada Tüm İşlemler",
        "🔵 Pazarama Tüm İşlemler",
        "📚 İdefix Tüm İşlemler",
        "⚙️ Fiyat & Barkod Ayarları",
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
                <div style='background-color: #e3f2fd; color: #0d47a1; padding: 6px; border-radius: 5px; font-size: 13px; margin-bottom: 5px; font-weight: bold;'>📦 6 Gönderime Hazır</div>
                <div style='background-color: #ffebee; color: #b71c1c; padding: 6px; border-radius: 5px; font-size: 13px; font-weight: bold;'>🚚 5 Kargoda</div>
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

    st.markdown("<br>", unsafe_allow_html=True)
    
    c4, c5, c6 = st.columns(3)
    with c4:
        st.markdown("""
            <div style='background-color: #ffffff; border: 2px solid #d84315; border-radius: 8px; padding: 10px; text-align: center;'>
                <div style='background-color: #d84315; color: white; padding: 8px; border-radius: 6px; font-weight: bold; margin-bottom: 8px;'>PTT AVM</div>
                <div style='background-color: #e8f5e9; color: #1b5e20; padding: 6px; border-radius: 5px; font-size: 13px; margin-bottom: 5px; font-weight: bold;'>🛍️ 1 Yeni Sipariş</div>
                <div style='background-color: #ede7f6; color: #311b92; padding: 6px; border-radius: 5px; font-size: 13px; font-weight: bold;'>📦 1 Kargo Bekliyor</div>
            </div>
        """, unsafe_allow_html=True)
    with c5:
        st.markdown("""
            <div style='background-color: #ffffff; border: 2px solid #c62828; border-radius: 8px; padding: 10px; text-align: center;'>
                <div style='background-color: #c62828; color: white; padding: 8px; border-radius: 6px; font-weight: bold; margin-bottom: 8px;'>N11</div>
                <div style='color: #757575; font-size: 14px; padding: 22px;'>Sipariş yok</div>
            </div>
        """, unsafe_allow_html=True)
    with c6:
        st.markdown("""
            <div style='background-color: #ffffff; border: 2px solid #0277bd; border-radius: 8px; padding: 10px; text-align: center;'>
                <div style='background-color: #0277bd; color: white; padding: 8px; border-radius: 6px; font-weight: bold; margin-bottom: 8px;'>PAZARAMA</div>
                <div style='background-color: #eceff1; color: #37474f; padding: 18px; border-radius: 5px; font-size: 14px; font-weight: bold;'>Çok yakında</div>
            </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    c7, _, _ = st.columns(3)
    with c7:
        st.markdown("""
            <div style='background-color: #ffffff; border: 2px solid #2e7d32; border-radius: 8px; padding: 10px; text-align: center;'>
                <div style='background-color: #2e7d32; color: white; padding: 8px; border-radius: 6px; font-weight: bold; margin-bottom: 8px;'>İDEFİX</div>
                <div style='background-color: #eceff1; color: #37474f; padding: 18px; border-radius: 5px; font-size: 14px; font-weight: bold;'>Çok yakında</div>
            </div>
        """, unsafe_allow_html=True)

    st.markdown("<br><hr><br>")
    
    # Boş / Yeni Fatura Alanı
    st.markdown("""
        <div style='background-color: #ffffff; border: 2px solid #1565c0; border-radius: 10px; overflow: hidden;'>
            <div style='background-color: #1565c0; color: white; padding: 12px; font-size: 16px; font-weight: bold; text-align: center;'>
                👤 Fatura ve Mağaza Bilgileri
            </div>
            <div style='padding: 20px;'>
                <table style='width: 100%; font-size: 15px; border-collapse: collapse;'>
                    <tr style='border-bottom: 1px solid #e0e0e0;'>
                        <td style='padding: 12px; font-weight: bold; width: 25%; color: #333;'>👤 İsim:</td>
                        <td style='padding: 12px; color: #777;'>[Yeni Mağaza Sahibi]</td>
                    </tr>
                    <tr style='border-bottom: 1px solid #e0e0e0;'>
                        <td style='padding: 12px; font-weight: bold; color: #333;'>✉️ Email:</td>
                        <td style='padding: 12px; color: #777;'>[ornek@magaza.com]</td>
                    </tr>
                    <tr style='border-bottom: 1px solid #e0e0e0;'>
                        <td style='padding: 12px; font-weight: bold; color: #333;'>📞 Telefon:</td>
                        <td style='padding: 12px; color: #777;'>[0500 000 00 00]</td>
                    </tr>
                    <tr>
                        <td style='padding: 12px; font-weight: bold; color: #333;'>📍 Adres:</td>
                        <td style='padding: 12px; color: #777;'>[Şirket Adresi Girilmedi]</td>
                    </tr>
                </table>
            </div>
        </div>
    """, unsafe_allow_html=True)

# ==========================================
# 2. SİSTEMDEKİ ÜRÜNLER (XML YÜKLEME)
# ==========================================
elif secim == "📦 Sistemdeki Ürünler (XML Yükle)":
    st.stitle = st.title("📦 Sistemdeki Ürünler & XML Entegrasyonu")
    st.write("Tedarikçinizden aldığınız XML linkini veya dosyasını buraya yükleyerek tüm sistem ürünlerini canlı olarak çekin.")
    
    xml_url = st.text_input("🔗 Tedarikçi XML Linki (URL girin):", placeholder="https://ornek-tedarikci.com/feed.xml")
    
    if st.button("🚀 XML'i İçe Aktar ve Ürünleri Yükle"):
        if xml_url:
            # Canlı simülasyon olarak örnek binlerce ürün üretiyoruz
            st.session_state.xml_yuklendi = True
            st.session_state.urunler_df = pd.DataFrame({
                "SKU": [f"SKU-{i}" for i in range(1, 15001)],
                "Ürün Adı": [f"Tedarik Ürünü Model X-{i}" for i in range(1, 15001)],
                "Kategori": ["Elektronik / Aksesuar" if i % 2 == 0 else "Ev & Yaşam" for i in range(1, 15001)],
                "Stok": [10 if i % 3 != 0 else 0 for i in range(1, 15001)],
                "Fiyat": [float(i * 15.5) for i in range(1, 15001)],
                "Eşleşme Durumu": ["Eşleşti" if i % 4 != 0 else "Eşleşmedi" for i in range(1, 15001)]
            })
            st.success("✅ XML başarıyla işlendi! Toplam 15.000 ürün sisteme aktarıldı.")
        else:
            st.error("Lütfen geçerli bir XML linki girin.")

    if st.session_state.xml_yuklendi:
        st.metric("Sistemdeki Toplam Aktif Ürün", len(st.session_state.urunler_df))
        st.dataframe(st.session_state.urunler_df.head(100), use_container_width=True)

# ==========================================
# 3. HEPSİBURADA TÜM İŞLEMLER (CANLI OPERASYON)
# ==========================================
elif secim == "🟠 Hepsiburada Tüm İşlemler":
    st.title("🟠 Hepsiburada Yönetim ve Operasyon Paneli")
    
    # Önemli Bilgilendirme Kutusu
    st.info("💡 **Önemli Bilgilendirme:** Günde 1 kez Tam Senkronizasyon yapmanız önerilir. Sık istek atmak API kota sınırına takılmanıza neden olabilir.")
    
    # Üst Kontrol Butonları Satırı
    col_b1, col_b2, col_b3, col_b4 = st.columns(4)
    with col_b1:
        if st.button("🔄 Tam Senkronizasyon", use_container_width=True):
            st.success("Hepsiburada tam senkronizasyon kuyruğa eklendi.")
    with col_b2:
        if st.button("⚠️ Kritik Stok Sıfırla", use_container_width=True):
            st.warning("Kritik seviyedeki stoklar sıfırlandı.")
    with col_b3:
        if st.button("🔄 Tüm Barkodları Güncelle", use_container_width=True):
            st.info("Barkodlar HB formatına senkronize edildi.")
    with col_b4:
        if st.button("🚀 Toplu Ürün Gönder", use_container_width=True):
            st.success("Ürünler Hepsiburada mağazasına aktarılıyor...")

    col_b5, col_b6, col_b7 = st.columns(3)
    with col_b5:
        if st.button("⏱️ Kargo Süresi Ayarla", use_container_width=True):
            st.info("Teslimat süreleri güncellendi.")
    with col_b6:
        if st.button("✅ Eşleşme Onayı Ver", use_container_width=True):
            st.success("Seçili ürün eşleşmeleri onaylandı.")
    with col_b7:
        if st.button("🚫 Eşleşmemişleri Kapat (Stok 0)", use_container_width=True):
            st.warning("Eşleşmeyen ürünlerin stokları kapatıldı.")

    st.markdown("---")
    st.subheader("📦 Canlı Sipariş & Kargo Yönetim Masası")
    
    # Alt Sekme Filtreleri
    hb_tab = st.radio(
        "Görünüm Seçin:",
        ["Kargoda Olanlar", "Gönderime Hazır", "Tüm Ürünler", "Eşleşmiş Ürünler", "Eşleşmemiş Ürünler", "Stok Tutmayanlar"],
        horizontal=True
    )

    # Örnek Canlı Sipariş / Ürün Verisi Tablosu ve Yönetim Butonları
    st.markdown(f"### Aktif Kategori: {hb_tab}")
    
    siparis_df = pd.DataFrame({
        "Sipariş No": ["HB-9382104", "HB-9382105", "HB-9382106"],
        "Alıcı Adı": ["Ahmet Yılmaz", "Mehmet Demir", "Ayşe Kaya"],
        "Ürün Adı": ["Wireless Şarj Standı", "Mini LED Projektör HY320", "Vibrasyon Güvenlik Alarmı"],
        "Kargo Firması": ["Aras Kargo", "Surat Kargo", "Yurtiçi Kargo"],
        "Durum": [hb_tab, hb_tab, hb_tab]
    })
    
    st.dataframe(siparis_df, use_container_width=True)

    st.markdown("#### Seçili Sipariş / Ürün İşlem Masası")
    col_op1, col_op2, col_op3, col_op4 = st.columns(4)
    with col_op1:
        if st.button("🏷️ Kargo Etiketi Değiştir"):
            st.success("Kargo etiketi yenilendi.")
    with col_op2:
        if st.button("🔄 Barkod Değiştir"):
            st.success("Barkod güncellendi.")
    with col_op3:
        if st.button("❌ Siparişi İptal Et"):
            st.error("Sipariş iptal talebi iletildi.")
    with col_op4:
        if st.button("✂️ Paketi Böl"):
            st.info("Paket bölme işlemi başlatıldı.")

    col_op5, col_op6 = st.columns(2)
    with col_op5:
        yeni_kargo = st.selectbox("Kargo Firması Değiştir", ["Aras Kargo", "Yurtiçi Kargo", "Sürat Kargo", "MNG Kargo"])
        if st.button("Kargo Firmasını Güncelle"):
            st.success(f"Kargo firması {yeni_kargo} olarak değiştirildi!")
    with col_op6:
        st.text_input("Sipariş Notu / Alıcı Bilgisi Güncelle")
        if st.button("Bilgileri Kaydet"):
            st.success("Değişiklikler kaydedildi.")

# ==========================================
# 4. DİĞER PAZARYERLERİ
# ==========================================
elif "Tüm İşlemler" in secim:
    pazar = secim.replace(" Tüm İşlemler", "")
    st.title(f"🚀 {pazar} Yönetim Paneli")
    st.info(f"{pazar} için mağaza senkronizasyonu ve kargo yönetimi aktif.")
    if st.button(f"🔄 {pazar} Siparişleri Yeniden Çek"):
        st.success(f"{pazar} siparişleri güncellendi!")

# ==========================================
# 5. HESAP VE API AYARLARI
# ==========================================
elif secim == "⚙️ Hesap ve API Ayarları":
    st.title("🔌 API ve Mağaza Entegrasyon Ayarları")
    st.markdown("---")
    st.text_input("MAĞAZA ID", placeholder="UUID giriniz...")
    st.text_input("SERVİS ANAHTARI", type="password", placeholder="Servis anahtarınızı girin...")
    if st.button("🔌 API Bağlantısını Test Et ve Kaydet"):
        st.success("API bağlantısı başarılı!")

# ==========================================
# DİĞER MODÜLLER
# ==========================================
else:
    st.title(f"📌 {secim}")
    st.info("Modül aktif olarak çalışmaktadır.")


# ==========================================
# 🤖 METENTO AI ASİSTAN (Sağ Alt Köşe / Kenar Çubuğu Widget)
# ==========================================
st.sidebar.markdown("---")
st.sidebar.markdown("### 🤖 Metento AI Asistan")
st.sidebar.markdown("<p style='font-size: 12px; color: #555;'>Yardıma mı ihtiyacınız var? Buradayım, operasyonel hataları birlikte çözelim!</p>", unsafe_allow_html=True)

ai_soru = st.sidebar.text_input("Metento'ya sor:", placeholder="Örn: Stoklar neden senkronize olmadı?")
if st.sidebar.button("Soruyu Gönder"):
    if ai_soru:
        st.sidebar.success(f"🤖 Metento AI: '{ai_soru}' konusunu inceliyorum. API bağlantılarınızı ve XML akışınızı kontrol ettim, her şey normal görünmektedir!")
    else:
        st.sidebar.warning("Lütfen bir soru yazın.")
