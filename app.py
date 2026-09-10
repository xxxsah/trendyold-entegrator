import streamlit as st
import pandas as pd

st.set_page_config(
    page_title="MetEntegre - E-Ticaret Yönetim Paneli", 
    page_icon="⚡", 
    layout="wide"
)

if 'selected_menu' not in st.session_state:
    st.session_state.selected_menu = "Anasayfa"

st.sidebar.title("🚀 MetEntegre Paneli")
menu_options = [
    "Anasayfa",
    "Destek Taleplerim",
    "Bildirimler",
    "Duyurular",
    "Sistemdeki Ürünler",
    "Oto Kritik Stok",
    "Trendyol",
    "Çiçeksepeti",
    "N11",
    "E-PTT AVM",
    "Hepsiburada",
    "Pazarama",
    "İdefix",
    "Ayarlar"
]

try:
    default_index = menu_options.index(st.session_state.selected_menu)
except ValueError:
    default_index = 0

selected_menu = st.sidebar.selectbox("Menü", menu_options, index=default_index)
st.session_state.selected_menu = selected_menu

if st.session_state.selected_menu == "Anasayfa":
    st.subheader("📊 Mağaza ve Sipariş Durumu")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("🛒 HEPSİBURADA\n\n1 Kargoda", use_container_width=True):
            st.session_state.selected_menu = "Hepsiburada"
            st.rerun()
    with col2:
        if st.button("📦 TRENDYOL\n\nSipariş yok", use_container_width=True):
            st.session_state.selected_menu = "Trendyol"
            st.rerun()
    with col3:
        if st.button("🌸 ÇİÇEKSEPETİ\n\nSipariş yok", use_container_width=True):
            st.session_state.selected_menu = "Çiçeksepeti"
            st.rerun()
    with col4:
        if st.button("🏢 PTT AVM\n\nSipariş yok", use_container_width=True):
            st.session_state.selected_menu = "E-PTT AVM"
            st.rerun()

    col5, col6, col7 = st.columns(3)
    with col5:
        if st.button("🟠 N11\n\nSipariş yok", use_container_width=True):
            st.session_state.selected_menu = "N11"
            st.rerun()
    with col6:
        st.button("🚀 PAZARAMA\n\nÇok Yakında", use_container_width=True, disabled=True)
    with col7:
        st.button("🚀 İDEFİX\n\nÇok Yakında", use_container_width=True, disabled=True)

    st.markdown("---")
    
    col_fat, col_sub = st.columns([1.2, 1])
    
    with col_fat:
        st.subheader("📄 Fatura Bilgileri")
        st.text_input("İsim", value="Şahin Yiğit", disabled=True)
        st.text_input("Email", value="sah1357sah@gmail.com", disabled=True)
        st.text_input("Telefon", value="05346944235", disabled=True)
        st.text_input("Vergi Numarası", value="9800650692", disabled=True)
        st.text_input("Vergi Dairesi", value="Kadifekale", disabled=True)
        st.text_input("TC Kimlik No", value="34510406564", disabled=True)
        st.text_input("Adres", value="Sevgi mah. 4642 sok no 4/1 Karabağlar İzmir", disabled=True)
        
        if st.button("Düzenle"):
            st.info("Fatura bilgileri düzenleme modu aktif.")
    
    with col_sub:
        st.subheader("⭐ Abonelik Bilgileri")
        st.metric(label="Kalan Gün Sayaç", value="78 Gün", delta="Aktif")
        st.write("**Sipariş ID:** SA1707418640181936")
        st.write("**Tutar:** 0 ₺")
        st.write("**Son Tarih:** 27.11.2026")
        st.write("**Durum:** Aktif")
        
        st.info("Abonelik uzatma: Süre uzatma işlemleri yöneticimiz tarafından yapılmaktadır. Süreniz dolmadan önce lütfen destek talebi oluşturarak bize ulaşın.")
        if st.button("Destek Talebi Oluştur"):
            st.success("Destek talebiniz oluşturuldu.")

    st.markdown("---")
    
    st.subheader("📦 Mağaza Ürün Limitleri")
    lim1, lim2 = st.columns(2)
    with lim1:
        st.metric("Trendyol Mağazanıza yüklenebilir ürün adedi", "20243")
        st.metric("N11 Mağazanıza yüklenebilir ürün adedi", "31920")
        st.metric("EPtt AVM Mağazanıza yüklenebilir ürün adedi", "37116")
    with lim2:
        st.metric("Çiçeksepeti Mağazanıza yüklenebilir ürün adedi", "30453")
        st.metric("Hepsiburada Mağazanıza yüklenebilir ürün adedi", "39868")

    st.markdown("---")
    st.subheader("📢 Duyurularım")
    st.success("Sistem güncellemeleri ve duyurular burada yer almaktadır. (Toplam: 1)")

elif st.session_state.selected_menu == "Destek Taleplerim":
    st.subheader("📌 Destek Taleplerim")
    st.info("Destek talebi geçmişiniz ve durumları.")
    if st.button("➕ Yeni Destek Talebi Aç"):
        st.success("Destek formu açıldı.")

elif st.session_state.selected_menu == "Bildirimler":
    st.subheader("🔔 Bildirimler")
    st.info("Sistem bildirimleri listelenmektedir.")

elif st.session_state.selected_menu == "Duyurular":
    st.subheader("📢 Duyurular")
    st.success("Tüm sistem duyuruları burada yer alır.")

elif st.session_state.selected_menu == "Sistemdeki Ürünler":
    st.subheader("📦 Sistemdeki Ürünler")
    st.text_input("🔍 SKU veya Ürün Adı ile Ara...", placeholder="Arama yapın...")
    st.dataframe(pd.DataFrame({
        "SKU": ["SKU-001", "SKU-002"],
        "Ürün Adı": ["Örnek Ürün A", "Örnek Ürün B"],
        "Kategori": ["Elektronik", "Giyim"],
        "Stok": [150, 42],
        "Fiyat": ["500 ₺", "250 ₺"]
    }), use_container_width=True)

elif st.session_state.selected_menu == "Oto Kritik Stok":
    st.subheader("⚙️ Oto Kritik Stok Yönetimi")
    st.number_input("Kritik Stok Eşiği", value=5)
    if st.button("💾 Kritik Stok Ayarlarını Kaydet"):
        st.success("Kritik stok ayarları güncellendi.")

elif st.session_state.selected_menu == "Trendyol":
    st.subheader("🛍️ Trendyol Ürünlerim")
    
    with st.expander("⚠️ Önemli Bilgilendirme", expanded=False):
        st.warning("Trendyol entegrasyonu ve ürün yönetimi ile ilgili tüm toplu işlemler bu alandan gerçekleştirilir.")

    st.markdown("##### 📁 Arşivleme İşlemleri")
    ar1, ar2, ar3, ar4 = st.columns(4)
    with ar1:
        if st.button("Tümünü Arşivle", use_container_width=True):
            st.warning("Tüm ürünler arşive gönderiliyor...")
    with ar2:
        if st.button("Kapatılanı Arşivle", use_container_width=True):
            st.info("Kapatılan ürünler arşivlendi.")
    with ar3:
        if st.button("Satıştaki Arşivle", use_container_width=True):
            st.info("Satıştaki ürünler arşivlendi.")
    with ar4:
        if st.button("Stok 0 Arşivle", use_container_width=True):
            st.info("Stoku 0 olan ürünler arşivlendi.")

    st.markdown("##### 🗑️ Silme İşlemleri & Veri Yönetimi")
    sil1, sil2, ver1, ver2 = st.columns(4)
    with sil1:
        if st.button("Onay Sürecini Sil", use_container_width=True):
            st.error("Onay sürecindeki ürünler silindi.")
    with sil2:
        if st.button("Arşivledikleri Sil", use_container_width=True):
            st.error("Arşivlenenler kalıcı olarak silindi.")
    with ver1:
        if st.button("Trendyol'dan Çek", use_container_width=True):
            st.success("Ürünler Trendyol'dan başarıyla çekildi!")
    with ver2:
        if st.button("Listeyi Yenile", use_container_width=True):
            st.rerun()

    st.markdown("---")
    
    st.markdown("##### 🔍 Ürün Filtreleme ve Arama")
    if st.button("🔄 TRENDYOL ÜRÜNLERİMİ GÜNCELLE", type="primary", use_container_width=True):
        st.success("Trendyol ürün listesi güncelleniyor...")
        
    st.text_input("🔍 Ürün adı, barkod veya model kodu ile ara...", placeholder="Arama yapın...")

    # Filtre Butonları (Görseldeki renkli filtre barı)
    f_cols = st.columns(7)
    with f_cols[0]: st.button("Tümü (4029)")
    with f_cols[1]: st.button("Satışta")
    with f_cols[2]: st.button("Eşleşmeyenler")
    with f_cols[3]: st.button("Satışa Kapalı")
    with f_cols[4]: st.button("Arşivde")
    with f_cols[5]: st.button("Onaylı")
    with f_cols[6]: st.button("Onay Bekliyor")

    f_cols2 = st.columns(3)
    with f_cols2[0]: st.button("Reddedilen")
    with f_cols2[1]: st.button("Blacklist")
    with f_cols2[2]: st.button("Kilitli")

    st.markdown("---")

    # Ürün Tablosu (Görseldeki gerçekçi liste formatı)
    ty_table = pd.DataFrame({
        "Barkod": ["8697577754265107681282837", "8697577752520107681282837", "8697577793107681282837"],
        "Ürün Adı": [
            "8Bitdo Retro R8 Fare, Şarj Yuvası, PAW 3...",
            "Aula S98 Pro 3 Modlu RGB Hot Swap Me...",
            "USB to USB C Gen2 2.5\" Hard Disk Kutus..."
        ],
        "Satış Fiyatı": ["10137 TL", "8002.14 TL", "0 TL"],
        "Trendyol Stok": [0, 0, 0],
        "M.Entegre Stok": [0, 0, 0],
        "Durum": ["Onaylı", "Satışa Kapalı", "Blacklist"]
    })
    st.dataframe(ty_table, use_container_width=True)

    st.markdown("---")
    st.subheader("⚙️ Trendyol API Ayarları ve Entegrasyon")
    st.text_input("🔑 API KEY", value="8AJFfnpGxxZCZp98Dc8")
    st.text_input("🔒 API SECRET", type="password", value="LZ4cNgROhsbHBeNUKWzC")
    st.text_input("🏢 MAĞAZA ID", value="1282837")
    if st.button("💾 Ayarları Kaydet"):
        st.success("API ayarları kaydedildi.")

elif st.session_state.selected_menu == "Çiçeksepeti":
    st.subheader("🌸 Çiçeksepeti Yönetim Paneli")
    st.info("Çiçeksepeti ürün ve sipariş yönetimi aktif.")
    if st.button("Ürünleri Çiçeksepeti'ne Gönder"):
        st.success("Ürünler aktarıldı.")

elif st.session_state.selected_menu == "N11":
    st.subheader("🟠 N11 Yönetim Paneli")
    st.info("N11 ürün ve sipariş yönetimi aktif.")
    if st.button("N11 Stok Senkronizasyonu"):
        st.success("Stoklar senkronize edildi.")

elif st.session_state.selected_menu == "E-PTT AVM":
    st.subheader("🏢 E-PTT AVM Yönetim Paneli")
    st.info("E-PTT AVM ürün ve sipariş yönetimi aktif.")

elif st.session_state.selected_menu == "Hepsiburada":
    st.subheader("🛒 Hepsiburada Yönetim Paneli")
    st.info("Hepsiburada mağazanıza ait siparişler ve ürün senkronizasyon alanları.")
    hb_data = pd.DataFrame({
        "HB SKU": ["HB-9912", "HB-9913"],
        "Ürün Adı": ["Örnek HB Ürün 1", "Örnek HB Ürün 2"],
        "Fiyat": ["450.00 ₺", "850.00 ₺"],
        "Durum": ["Aktif", "Aktif"]
    })
    st.dataframe(hb_data, use_container_width=True)

elif st.session_state.selected_menu == "Pazarama":
    st.subheader("🚀 Pazarama Yönetim Paneli")
    st.info("Pazarama entegrasyonu yakında aktifleşecektir.")

elif st.session_state.selected_menu == "İdefix":
    st.subheader("🚀 İdefix Yönetim Paneli")
    st.info("İdefix entegrasyonu yakında aktifleşecektir.")

elif st.session_state.selected_menu == "Ayarlar":
    st.subheader("⚙️ Genel Sistem Ayarları")
    st.text_input("Firma Adı", value="Şahin Yiğit E-Ticaret")
    st.text_input("Bildirim E-postası", value="sah1357sah@gmail.com")
    if st.button("Genel Ayarları Kaydet"):
        st.success("Ayarlar başarıyla kaydedildi!")
