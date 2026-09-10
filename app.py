import streamlit as st
import pandas as pd

# Sayfa Yapılandırması
st.set_page_config(
    page_title="MetEntegre - E-Ticaret Yönetim Paneli", 
    page_icon="⚡", 
    layout="wide"
)

# Sidebar Navigasyon Menüsü
st.sidebar.title("🚀 MetEntegre Paneli")
menu = st.sidebar.selectbox("Menü", ["Genel Bakış", "Trendyol İşlemleri", "Trendyol API Ayarları", "Siparişler"])

if menu == "Genel Bakış":
    st.subheader("📊 Mağaza ve Sipariş Durumu")
    
    # Pazaryeri Sipariş Durum Kutuları
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.error("🛒 **HEPSİBURADA**\n\n 1 Kargoda")
    with col2:
        st.info("📦 **TRENDYOL**\n\n Sipariş yok")
    with col3:
        st.warning("🌸 **ÇİÇEKSEPETİ**\n\n Sipariş yok")
    with col4:
        st.success("🏢 **PTT AVM**\n\n Sipariş yok")

    col5, col6, col7 = st.columns(3)
    with col5:
        st.info("🟠 **N11**\n\n Sipariş yok")
    with col6:
        st.markdown("🚀 **PAZARAMA**\n\n Çok Yakında")
    with col7:
        st.markdown("🚀 **İDEFİX**\n\n Çok Yakında")

    st.markdown("---")
    
    # Fatura Bilgileri ve Abonelik Bilgileri Bölümü
    col_fat, col_sub = st.columns([1.2, 1])
    
    with col_fat:
        st.subheader("📄 Fatura Bilgileri")
        st.text_input("İsim", value="Şahin Yiğit", disabled=True)
        st.text_input("Email", value="sah1357sah@gmail.com", disabled=True)
        st.text_input("Telefon", value="05346944235", disabled=True)
        st.text_input("Vergi Numarası", value="9800650692", disabled=True)
        st.text_input("Adres", value="Sevgi mah. 4642 sok no 4/1 Karabağlar İzmir", disabled=True)
    
    with col_sub:
        st.subheader("⭐ Abonelik Bilgileri")
        st.metric(label="Kalan Gün", value="78 Gün", delta="Aktif")
        st.write("**Paket Durumu:** Aktif")
        st.write("**Son Tarih:** 27.11.2026")
        if st.button("Destek Talebi Oluştur"):
            st.success("Destek talebiniz oluşturuldu.")

    st.markdown("---")
    
    # Mağazalara Yüklenebilir Ürün Adetleri
    st.subheader("📦 Mağaza Ürün Limitleri")
    lim1, lim2, lim3 = st.columns(3)
    lim1.metric("Trendyol Yüklenebilir Ürün", "20243")
    lim2.metric("Çiçeksepeti Yüklenebilir Ürün", "30453")
    lim3.metric("N11 Yüklenebilir Ürün", "31920")
    
    lim4, lim5 = st.columns(2)
    lim4.metric("Hepsiburada Yüklenebilir Ürün", "39868")
    lim5.metric("EPtt AVM Yüklenebilir Ürün", "37116")

elif menu == "Trendyol İşlemleri":
    st.subheader("🛍️ Trendyol Tüm İşlemler")
    
    # Üst İşlem Butonları
    cols = st.columns(6)
    with cols[0]: st.button("Tüm Senkronizasyon")
    with cols[1]: st.button("Kritik Stok Silindir")
    with cols[2]: st.button("Tüm Barkodları Güncelle")
    with cols[3]: st.button("Stok Tutmayanları Güncelle")
    with cols[4]: st.button("Toplu Ürün Gönder")
    with cols[5]: st.button("Toplu Ürün Gönder (Riskli)")

    st.markdown("---")

    # Metrik Özet Kutuları
    m1, m2, m3 = st.columns(3)
    m1.metric("Toplam TY Ürün", "5.782")
    m2.metric("Senkronize Edilmiş", "2.300")
    m3.metric("Senkronize Edilememiş", "3.482")

    m4, m5 = st.columns(2)
    m4.metric("TY Aktif", "906")
    m5.metric("Stok Tutmayanlar", "5.233")

    st.markdown("---")
    
    # Ürün Filtreleme Sekmeleri (Görseldeki gibi)
    tab_tumu, tab_eslesen, tab_eslesmeyen, tab_stoksuz = st.tabs(["Tümü", "Eşleşmiş", "Eşleşmemiş", "Stok Tutmayanlar"])
    
    with tab_tumu:
        st.text_input("🔍 SKU veya Ürün Adı ile ara...", placeholder="Arama yapın...")
        
        table_data = pd.DataFrame({
            "Merchant SKU": ["CYRE-879524-4L", "CYRE-798837-L/XL", "CYRE-679542-STANDARD"],
            "Ürün Adı": ["Kamuflaj Fantezi Asker Kostümü", "Mavi Siyah Dantelli Jartiyer Takım", "Siyah Kırmızı Fantezi Jartiyer Takım"],
            "Mağaza Stok": [-1, -1, -1],
            "MetEntegre Stok": [384, 191, 87],
            "Mağaza Fiyat": ["-", "-", "-"],
            "MetEntegre Fiyat": ["310,20 ₺", "264,00 ₺", "264,00 ₺"],
            "Eşleşme Durumu": ["Eşleşti", "Eşleşti", "Eşleşti"],
            "Son Güncelleme": ["08.09.2026 17:30", "08.09.2026 17:30", "08.09.2026 17:30"]
        })
        st.dataframe(table_data, use_container_width=True)
        
    with tab_eslesen:
        st.info("Eşleşen ürünler burada listelenir.")
    with tab_eslesmeyen:
        st.warning("Eşleşmeyen ürünler burada listelenir.")
    with tab_stoksuz:
        st.error("Stok tutmayan ürünler burada listelenir.")

elif menu == "Trendyol API Ayarları":
    st.subheader("⚙️ Trendyol API ve Entegrasyon Ayarları")
    
    st.info("Değerli Kullanıcımız, Trendyol entegrasyonunu başlatmak için öncelikle bağlantı bilgilerinizin test edilmesi gerekmektedir.")
    
    st.text_input("🔑 API KEY", value="8AJFfnpGxxZCZp98Dc8")
    st.text_input("🔒 API SECRET", type="password", value="LZ4cNgROhsbHBeNUKWzC")
    st.text_input("🏢 MAĞAZA ID", value="1282837")
    
    st.markdown("---")
    st.text_input("MARKA ARAMA VE MARKA TANIMLAMA", value="")
    st.text_input("Seçilen Marka", value="colezium", disabled=True)
    
    col_set1, col_set2 = st.columns(2)
    with col_set1:
        st.text_input("BARCODE BAŞLANGICI", value="CYRE")
        st.text_input("TRENDYOL HİZMET BEDELİ (TL)", value="12")
    with col_set2:
        st.text_input("SABİT KARGO FİYATI", value="120")
        st.text_input("FİYAT ARTIŞ ORANI (%)", value="60")
        
    st.markdown("---")
    st.subheader("🤖 Otomatik Ürün Yükleme")
    auto_status = st.toggle("Otomatik Yükleme Sistemi", value=True)
    if auto_status:
        st.success("Otomatik yükleme aktif. Ürünler otomatik olarak Trendyol'a yüklenecektir.")
    else:
        st.warning("Otomatik yükleme pasif.")
        
    if st.button("Ayarları Güncelle"):
        st.success("Ayarlar başarıyla güncellendi!")

elif menu == "Siparişler":
    st.subheader("🛒 Gelen Sipariş Yönetimi")
    st.write("Tüm pazaryerlerinden düşen siparişlerin listesi.")
    st.dataframe(pd.DataFrame(columns=["Sipariş No", "Pazaryeri", "Müşteri Adı", "Toplam Tutar", "Kargo Durumu"]))
