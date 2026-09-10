import streamlit as st
import pandas as pd

# Sayfa Yapılandırması
st.set_page_config(
    page_title="MetEntegre Benzeri Entegrasyon Paneli", 
    page_icon="⚡", 
    layout="wide"
)

# Özel CSS ile MetEntegre tarzı modern ve şık görünüm
st.markdown("""
    <style>
    .main-header {
        font-size: 36px;
        font-weight: bold;
        color: #1E3A8A;
        text-align: center;
        margin-bottom: 10px;
    }
    .sub-header {
        font-size: 18px;
        color: #4B5563;
        text-align: center;
        margin-bottom: 30px;
    }
    .card {
        background-color: #F3F4F6;
        padding: 20px;
        border-radius: 10px;
        text-align: center;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.05);
    }
    </style>
""", unsafe_allow_html=True)

# Üst Menü / Navigasyon
menu = st.sidebar.selectbox("Menü", ["Ana Sayfa", "Pazaryeri Entegrasyonları", "Ürün & XML Yönetimi", "Siparişler", "Ayarlar"])

if menu == "Ana Sayfa":
    # Hero / Banner Alanı
    st.markdown('<div class="main-header">Dijital Dönüşümün Güçlü Ortağı</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Trendyol, Hepsiburada, PttAVM, N11, Çiçeksepeti ve dahası ile tam entegrasyon sağlayın. Stok ve siparişlerinizi tek panelden yönetin.</div>', unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Desteklenen Pazaryerleri Bölümü
    st.subheader("🛒 Desteklediğimiz Pazaryerleri")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown("✅ **Trendyol**")
    with col2:
        st.markdown("✅ **Hepsiburada**")
    with col3:
        st.markdown("⏳ **PttAVM** (Çok Yakında)")
    with col4:
        st.markdown("✅ **N11**")
        
    col5, col6, col7, col8 = st.columns(4)
    with col5:
        st.markdown("✅ **Çiçeksepeti**")
    with col6:
        st.markdown("⏳ **İdefix** (Çok Yakında)")
    with col7:
        st.markdown("⏳ **Pazarama** (Çok Yakında)")
    with col8:
        st.markdown("⏳ **Amazon / Diğer**")

    st.markdown("---")

    # 4 Adımda Kolayca Satışa Başlayın Bölümü
    st.subheader("🚀 4 Adımda Kolayca Satışa Başlayın")
    step1, step2, step3, step4 = st.columns(4)
    
    with step1:
        st.markdown("### 1️⃣ Başvuru")
        st.write("Başvurunuzu hızlıca gönderin ve süreci başlatın.")
    with step2:
        st.markdown("### 2️⃣ API Bilgileri")
        st.write("Sisteme mağazanızın API bilgilerini kaydedin.")
    with step3:
        st.markdown("### 3️⃣ Gönderim")
        st.write("Toplu ürün yükleme ile mağazanıza ürünleri yükleyin.")
    with step4:
        st.markdown("### 4️⃣ Kazanç")
        st.write("Satış yapın ve siparişlerinizin keyfini alın.")

elif menu == "Pazaryeri Entegrasyonları":
    st.subheader("🔑 Mağaza ve API Bağlantıları")
    platform = st.selectbox("Entegrasyon Yapılacak Pazaryeri", ["Trendyol", "Hepsiburada", "N11", "Çiçeksepeti"])
    
    if platform == "Trendyol":
        st.text_input("Satıcı ID (Supplier ID)")
        st.text_input("API Key (Client ID)", type="password")
        st.text_input("API Secret", type="password")
    elif platform == "Hepsiburada":
        st.text_input("Merchant ID (Mağaza ID)")
        st.text_input("API Kullanıcı Adı")
        st.text_input("API Şifresi", type="password")
        
    if st.button("Bağlantıyı Test Et ve Kaydet"):
        st.success(f"{platform} bağlantı ayarları kaydedildi!")

elif menu == "Ürün & XML Yönetimi":
    st.subheader("📦 Tedarikçi XML ve Ürün Aktarımı")
    xml_input = st.text_input("Tedarikçi XML Linki Girin")
    
    if st.button("XML Ürünlerini Çek"):
        if xml_input:
            st.info("Ürünler XML'den başarıyla çekiliyor...")
            sample_df = pd.DataFrame({
                "Stok Kodu": ["SKU-001", "SKU-002"],
                "Ürün Adı": ["Örnek Ürün A", "Örnek Ürün B"],
                "Fiyat": [350.0, 750.0],
                "Stok": [45, 120]
            })
            st.dataframe(sample_df)
        else:
            st.error("Lütfen geçerli bir XML adresi yazın.")

elif menu == "Siparişler":
    st.subheader("🛒 Gelen Siparişler")
    st.write("Tüm pazaryerlerinden gelen siparişler burada birleşir.")
    st.dataframe(pd.DataFrame(columns=["Sipariş ID", "Pazaryeri", "Müşteri", "Tutar", "Durum"]))

elif menu == "Ayarlar":
    st.subheader("⚙️ Sistem Ayarları")
    st.slider("Genel Kâr / Fiyat Farkı Marjı (%)", 0, 100, 20)
    st.button("Ayarları Kaydet")
