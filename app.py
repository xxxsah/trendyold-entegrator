import streamlit as st
import pandas as pd

# Sayfa Konfigürasyonu
st.set_page_config(
    page_title="MetEntegre - Profesyonel E-Ticaret Yönetim Paneli",
    page_icon="📦",
    layout="wide"
)

# Oturum Durumu
if "giris_yapildi" not in st.session_state:
    st.session_state.giris_yapildi = False

# ==========================================
# GİRİŞ EKRANI (LANDING)
# ==========================================
if not st.session_state.giris_yapildi:
    col_l1, col_l2, col_l3 = st.columns([1, 2, 1])
    with col_l2:
        st.markdown("### 🌐 **MetEntegre** Giriş Paneli")
        st.info("İrmakxx Mağaza Yönetim Sistemi")
        eposta = st.text_input("E-posta Adresi", value="sah1357sah@gmail.com")
        sifre = st.text_input("Şifre", type="password", value="123456")
        
        if st.button("🚀 Sisteme Giriş Yap", use_container_width=True):
            if eposta:
                st.session_state.giris_yapildi = True
                st.rerun()
else:
    # ==========================================
    # SOL MENÜ (Görseldeki Menünün Aynısı)
    # ==========================================
    st.sidebar.title("📌 MetEntegre Menü")
    secim = st.sidebar.selectbox(
        "Sayfa Seçin",
        [
            "🏠 Anasayfa",
            "💬 Destek Taleplerim",
            "🔔 Bildirimler",
            "📢 Duyurular",
            "📦 Sistemdeki Ürünler",
            "⚡ Oto Kritik Stok",
            "🧡 Trendyol İşlemleri",
            "🌸 Çiçeksepeti İşlemleri",
            "🔴 N11 İşlemleri",
            "📦 E-PTT AVM İşlemleri",
            "🟠 Hepsiburada Tüm İşlemler",
            "🔵 Pazarama İşlemleri",
            "📚 İdefix İşlemleri",
            "⚙️ Fiyat & Barkod Ayarları",
            "⚙️ Ayarlar"
        ]
    )

    if st.sidebar.button("🚪 Çıkış Yap"):
        st.session_state.giris_yapildi = False
        st.rerun()

    # ==========================================
    # 1. ANASAYFA
    # ==========================================
    if secim == "🏠 Anasayfa":
        st.title("🌐 MetEntegre - Kontrol Paneli")
        st.markdown("#### Pazaryeri Durum Özetleri")
        
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("""
                <div style='background-color: #f8f9fa; border: 2px solid #ff6600; border-radius: 10px; padding: 12px; text-align: center;'>
                    <h4 style='color: #ff6600; margin: 0;'>HEPSİBURADA</h4><hr style='margin: 5px 0;'>
                    <p style='background-color: #e6f2ff; color: #004085; padding: 5px; border-radius: 5px;'><b>6 Gönderime Hazır</b></p>
                    <p style='background-color: #f8d7da; color: #721c24; padding: 5px; border-radius: 5px;'><b>5 Kargoda</b></p>
                </div>
            """, unsafe_allow_html=True)
        with c2:
            st.markdown("""
                <div style='background-color: #f8f9fa; border: 2px solid #f27a1a; border-radius: 10px; padding: 12px; text-align: center;'>
                    <h4 style='color: #f27a1a; margin: 0;'>TRENDYOL</h4><hr style='margin: 5px 0;'>
                    <p style='color: #666; padding: 15px;'>Sipariş yok</p>
                </div>
            """, unsafe_allow_html=True)
        with c3:
            st.markdown("""
                <div style='background-color: #f8f9fa; border: 2px solid #ff69b4; border-radius: 10px; padding: 12px; text-align: center;'>
                    <h4 style='color: #ff69b4; margin: 0;'>ÇİÇEKSEPETİ</h4><hr style='margin: 5px 0;'>
                    <p style='color: #666; padding: 15px;'>Sipariş yok</p>
                </div>
            """, unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        
        # Fatura Bilgileri Kartı
        st.markdown("""
            <div style='background-color: #ffffff; border: 2px solid #004085; border-radius: 10px; padding: 15px;'>
                <h4 style='color: #004085; text-align: center; margin-top: 0;'>👤 Fatura & Hesap Bilgileri</h4>
                <hr>
                <p><b>İsim:</b> Şahin Yiğit</p>
                <p><b>Marka:</b> İrmakxx</p>
                <p><b>Email:</b> sah1357sah@gmail.com</p>
                <p><b>TC Kimlik No:</b> 34510406564</p>
            </div>
        """, unsafe_allow_html=True)

    # ==========================================
    # 2. HEPSİBURADA TÜM İŞLEMLER (Görseldeki Ekran)
    # ==========================================
    elif secim == "🟠 Hepsiburada Tüm İşlemler":
        st.title("🟠 Hepsiburada Mağaza Yönetimi")
        st.write("Hepsiburada mağazanızdaki ürünler, eşleşme durumları ve entegrasyon araçları.")
        
        st.markdown("---")
        col_hb1, col_hb2, col_hb3 = st.columns(3)
        with col_hb1:
            if st.button("🔄 Tam Senkronizasyon"):
                st.success("Hepsiburada tam senkronizasyon kuyruğa eklendi!")
        with col_hb2:
            if st.button("⚠️ Kritik Stok Sıfırla"):
                st.warning("Kritik stoktaki ürünler sıfırlandı.")
        with col_hb3:
            if st.button("📦 Tüm Barkodları Güncelle"):
                st.info("Barkod senkronizasyonu başlatıldı.")

        st.markdown("---")
        st.subheader("Hızlı İşlem Paneli")
        col_op1, col_op2 = st.columns(2)
        with col_op1:
            if st.button("🚀 Toplu Ürün Gönder"):
                st.success("XML'deki ürünler Hepsiburada'ya gönderiliyor...")
            if st.button("⏱️ Kargo Süresi Ayarla"):
                st.info("Kargo teslim süreleri güncellendi.")
        with col_op2:
            if st.button("✅ Eşleşme Onay / Red"):
                st.info("Eşleşme ekranı açıldı.")
            if st.button("❌ Eşleşmemiş Ürünleri Stok 0'la"):
                st.warning("Eşleşmeyen ürünlerin stoğu kapatıldı.")

    # ==========================================
    # 3. FİYAT & BARKOD AYARLARI (Görseldeki Ekran)
    # ==========================================
    elif secim == "⚙️ Fiyat & Barkod Ayarları":
        st.title("⚙️ Fiyat & Barkod Konfigürasyonu")
        st.markdown("---")
        
        st.subheader("BARCODE BAŞLANGICI")
        st.text_input("Ön Ek (Prefix)", value="RKRW", disabled=True)
        if st.button("🔄 Yeni Barcode Oluştur"):
            st.success("Yeni barkod öneki üretildi!")

        st.subheader("SABİT KARGO FİYATI (TL / $)")
        st.number_input("Kargo Maliyeti", value=120.0, disabled=True)
        st.caption("Bu alan sistem yöneticisi tarafından sabitlenmiştir.")

        st.subheader("SABİT ARTTIRIM VE KÂR MARJLARI")
        st.number_input("Sabit Artırım (TL)", value=15)
        st.info("Sistem tarafından otomatik kar marjı ve artırım uygulanmaktadır.")

    # ==========================================
    # 4. AYARLAR VE SOAP/REST API (Görseldeki Ekran)
    # ==========================================
    elif secim == "⚙️ Ayarlar":
        st.title("🔌 API ve Mağaza Bağlantı Ayarları")
        st.markdown("---")
        
        st.subheader("SOAP API - Ürün & Stok Yönetimi")
        st.text_input("MAĞAZA ID (SUPPLIER ID)", value="20178075")
        st.text_input("API KULLANICI ADI", value="İrmakxx")
        st.text_input("API ŞİFRE", type="password", value="******")
        st.text_input("MARKA", value="İrmak")
        
        if st.button("💾 Ayarları Kaydet"):
            st.success("API ve Mağaza ayarları başarıyla güncellendi!")

    # ==========================================
    # DİĞER SEKMELER (Dinamik Şablon)
    # ==========================================
    else:
        st.title(f"📌 {secim}")
        st.info(f"Bu modül ({secim}) şu anda aktif ve veritabanı ile senkronize çalışmaktadır.")
        st.write("İlgili operasyonel verileri buradan yönetebilirsiniz.")
