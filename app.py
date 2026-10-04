import streamlit as st
import pandas as pd
import datetime

# Sayfa Konfigürasyonu
st.set_page_config(
    page_title="MetEntegre Benzeri E-Ticaret Paneli",
    page_icon="🚀",
    layout="wide"
)

# --- ÜST MENÜ / BAŞLIK ---
st.title("🚀 Profesyonel E-Ticaret Entegrasyon & Yönetim Paneli")
st.markdown("Trendyol, Hepsiburada ve XML Tedarikçi Yönetim Merkezi")

# --- YAN MENÜ (SEKMELER) ---
menu = st.sidebar.selectbox(
    "Operasyon Menüsü",
    [
        "📊 Dashboard (Özet)", 
        "📥 Tedarikçi & XML Ürün Çekme", 
        "💰 Fiyat & Kar Marjı Motoru", 
        "🔄 Stok Senkronizasyonu", 
        "📦 Sipariş & İade Yönetimi"
    ]
)

# ==========================================
# 1. DASHBOARD (GENEL BAKIŞ)
# ==========================================
if menu == "📊 Dashboard (Özet)":
    st.header("Mağaza Genel Durumu")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(label="Aktif Ürün Sayısı", value="1,450", delta="+12")
    with col2:
        st.metric(label="Bugünkü Sipariş", value="24", delta="3 yeni")
    with col3:
        st.metric(label="Günlük Ciro", value="18,450 TL", delta="%18")
    with col4:
        st.metric(label="Kritik Stoktaki Ürün", value="5", delta="-2", delta_color="inverse")
    
    st.markdown("---")
    st.subheader("Son Hareketler & Bildirimler")
    st.info("ℹ️ Colezium XML başarıyla senkronize edildi. (Son güncelleme: Bugün 13:00)")
    st.warning("⚠️ 5 ürünün tedarikçi stoğu tükenmek üzere, pazaryerlerinde güncellendi.")

# ==========================================
# 2. TEDARİKÇİ & XML ÜRÜN ÇEKME
# ==========================================
elif menu == "📥 Tedarikçi & XML Ürün Çekme":
    st.header("Tedarikçi XML Entegrasyonu")
    
    with st.form("xml_form"):
        st.subheader("Yeni XML Kaynağı Ekle")
        tedarikci_adi = st.text_input("Tedarikçi Adı (Örn: Colezium / MetEntegre Tedarik)")
        xml_url = st.text_input("XML Linki (URL)")
        kategori_esitle = st.selectbox("Varsayılan Kategori Eşleme", ["Telefon Aksesuarları", "Ev Yaşam", "Elektronik"])
        
        submit_xml = st.form_submit_button("XML'i İçe Aktar ve Ürünleri Çek")
        
        if submit_xml:
            if xml_url:
                st.success(f"'{tedarikci_adi}' XML adresi sisteme tanımlandı ve ürünler kuyruğa eklendi!")
            else:
                st.error("Lütfen geçerli bir XML linki girin.")

    st.subheader("Mevcut Tedarikçiler ve Ürün Listesi")
    # Örnek Tablo
    data = {
        "Tedarikçi": ["Colezium", "Örnek Tedarikçi 2"],
        "Son Güncelleme": ["04.10.2026 12:30", "03.10.2026 09:15"],
        "Çekilen Ürün": [1250, 430],
        "Durum": ["Aktif 🟢", "Aktif 🟢"]
    }
    st.table(pd.DataFrame(data))

# ==========================================
# 3. FIYAT & KAR MARJI MOTORU
# ==========================================
elif menu == "💰 Fiyat & Kar Marjı Motoru":
    st.header("Akıllı Fiyatlandırma & Net Kar Hesaplayıcı")
    
    col1, col2 = st.columns(2)
    
    with col1:
        alis_fiyati = st.number_input("Ürün Alış Fiyatı (KDV Hariç) - TL", min_value=0.0, value=100.0)
        kdv_orani = st.selectbox("KDV Oranı (%)", [1, 10, 20], index=2)
        komisyon_orani = st.slider("Pazaryeri Komisyon Oranı (%)", min_value=5, max_value=30, value=15)
    
    with col2:
        kargo_maliyeti = st.number_input("Ortalama Kargo Gideri - TL", min_value=0.0, value=45.0)
        hedef_kar_marji = st.slider("İstenen Net Kar Marjı (%)", min_value=5, max_value=100, value=25)
    
    # Hesaplama Mantığı
    kdv_tutar = alis_fiyati * (kdv_orani / 100)
    maliyet_toplam = alis_fiyati + kdv_tutar + kargo_maliyeti
    # Hedef kar ve komisyon hesabı dahil satış fiyatı simülasyonu
    tahmini_satis = maliyet_toplam * (1 + (hedef_kar_marji / 100)) / (1 - (komisyon_orani / 100))
    
    st.markdown("---")
    st.subheader("Sonuç / Önerilen Satış Fiyatı")
    res_col1, res_col2, res_col3 = st.columns(3)
    res_col1.metric("Toplam Maliyet", f"{maliyet_toplam:.2f} TL")
    res_col2.metric("Önerilen Satış Fiyatı (KDV Dahil)", f"{tahmini_satis:.2f} TL")
    res_col3.metric("Net Tahmini Kazanç", f"{(tahmini_satis * (komisyon_orani/100)):.2f} TL")

# ==========================================
# 4. STOK SENKRONIZASYONU
# ==========================================
elif menu == "🔄 Stok Senkronizasyonu":
    st.header("Otomatik Stok ve Fiyat Güncelleyici")
    st.write("Tedarikçi XML'lerindeki değişimleri Trendyol ve Hepsiburada mağazalarınıza yansıtın.")
    
    col1, col2 = st.columns(2)
    with col1:
        st.info("⏱️ **Otomatik Çalışma:** Arka planda her 1 saatte bir güncellenir.")
        if st.button("Şimdi Tüm Stokları Senkronize Et (Manuel tetikle)"):
            st.success("Senkronizasyon başlatıldı! Stoklar pazaryeri API'lerine iletiliyor...")
    
    with col2:
        st.warning("🛡️ **Güvenlik Sınırı:** Tedarikçi stoğu 2 ve altındaysa mağazada '0' (Tükendi) göster.")
        guvenlik_kilidi = st.checkbox("Stok Emniyet Kilidini Etkinleştir", value=True)

# ==========================================
# 5. SIPARIŞ & İADE YÖNETİMİ
# ==========================================
elif menu == "📦 Sipariş & İade Yönetimi":
    st.header("Çoklu Pazaryeri Sipariş Merkezi")
    
    filtre = st.radio("Görüntüle:", ["Tüm Siparişler", "Bekleyenler", "Kargodakiler", "İadeler"], horizontal=True)
    
    siparis_data = {
        "Sipariş No": ["TRND-10492", "HPB-88392", "TRND-10493"],
        "Pazaryeri": ["Trendyol", "Hepsiburada", "Trendyol"],
        "Müşteri": ["Ahmet Y.", "Mehmet K.", "Ayşe D."],
        "Tutar": ["450.00 TL", "1,200.00 TL", "230.00 TL"],
        "Durum": ["Kargolandı 🚚", "Onay Bekliyor ⏳", "İade Talebi ↩️"]
    }
    st.dataframe(pd.DataFrame(siparis_data), use_container_width=True)
