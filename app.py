import streamlit as st
import pandas as pd

st.set_page_config(
    page_title="Şahentegre - E-Ticaret Yönetim Paneli", 
    page_icon="👑", 
    layout="wide"
)

# Streamlit karanlık mod/tema farkından ötürü taban renklerinin tam beyaz görünmesi için CSS ekliyoruz
st.markdown("""
    <style>
    .stApp {
        background-color: #f8f9fa;
    }
    .market-card {
        background-color: #ffffff;
        border-radius: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        margin-bottom: 12px;
        overflow: hidden;
        border: 1px solid #e0e0e0;
    }
    .market-header {
        color: white;
        padding: 8px;
        font-weight: bold;
        text-align: center;
        font-size: 14px;
    }
    </style>
""", unsafe_allow_html=True)

if 'selected_menu' not in st.session_state:
    st.session_state.selected_menu = "Anasayfa"

if 'previous_menu' not in st.session_state:
    st.session_state.previous_menu = "Anasayfa"

st.sidebar.title("👑 Şahentegre Paneli")
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

if selected_menu != st.session_state.selected_menu:
    st.session_state.previous_menu = st.session_state.selected_menu
    st.session_state.selected_menu = selected_menu
    st.rerun()

def go_back():
    st.session_state.selected_menu = st.session_state.previous_menu
    st.rerun()

if st.session_state.selected_menu != "Anasayfa":
    if st.button("⬅️ Geri Dön"):
        go_back()
    st.markdown("---")

if st.session_state.selected_menu == "Anasayfa":
    # Gönderdiğin görseldeki gibi tam genişlikte (full-width) alt alta büyük kartlar ve beyaz tabanlı yapı
    
    # 1. Hepsiburada
    st.markdown('<div class="market-card"><div class="market-header" style="background-color: #ff6000;">🛒 HEPSİBURADA</div>', unsafe_allow_html=True)
    if st.button("1 Kargoda", use_container_width=True, key="btn_hb"):
        st.session_state.previous_menu = "Anasayfa"
        st.session_state.selected_menu = "Hepsiburada"
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)
    
    # 2. Trendyol
    st.markdown('<div class="market-card"><div class="market-header" style="background-color: #f27a1a;">📦 TRENDYOL</div>', unsafe_allow_html=True)
    if st.button("Sipariş yok", use_container_width=True, key="btn_ty"):
        st.session_state.previous_menu = "Anasayfa"
        st.session_state.selected_menu = "Trendyol"
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)
    
    # 3. Çiçeksepeti
    st.markdown('<div class="market-card"><div class="market-header" style="background-color: #e6005c;">🌸 ÇİÇEKSEPETİ</div>', unsafe_allow_html=True)
    if st.button("Sipariş yok", use_container_width=True, key="btn_cs"):
        st.session_state.previous_menu = "Anasayfa"
        st.session_state.selected_menu = "Çiçeksepeti"
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)
    
    # 4. PTT AVM
    st.markdown('<div class="market-card"><div class="market-header" style="background-color: #ff9900;">🏢 PTT AVM</div>', unsafe_allow_html=True)
    if st.button("Sipariş yok", use_container_width=True, key="btn_ptt"):
        st.session_state.previous_menu = "Anasayfa"
        st.session_state.selected_menu = "E-PTT AVM"
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)
    
    # 5. N11
    st.markdown('<div class="market-card"><div class="market-header" style="background-color: #5d3ebc;">🟠 N11</div>', unsafe_allow_html=True)
    if st.button("Sipariş yok", use_container_width=True, key="btn_n11"):
        st.session_state.previous_menu = "Anasayfa"
        st.session_state.selected_menu = "N11"
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)
    
    # 6. Pazarama (Taç 👑 ikonlu)
    st.markdown('<div class="market-card"><div class="market-header" style="background-color: #0099ff;">👑 PAZARAMA</div>', unsafe_allow_html=True)
    st.button("Çok Yakında", use_container_width=True, disabled=True, key="btn_pz")
    st.markdown('</div>', unsafe_allow_html=True)
    
    # 7. İdefix (Taç 👑 ikonlu)
    st.markdown('<div class="market-card"><div class="market-header" style="background-color: #00b33c;">👑 İDEFİX</div>', unsafe_allow_html=True)
    st.button("Çok Yakında", use_container_width=True, disabled=True, key="btn_id")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("---")
    
    # Fatura Bilgileri
    st.markdown("### 👤 Fatura Bilgileri")
    st.text_input("İsim:", value="Şahin Yiğit", disabled=True)
    st.text_input("Email:", value="sah1357sah@gmail.com", disabled=True)
    st.text_input("Telefon:", value="05346944235", disabled=True)
    st.text_input("Vergi Numarası:", value="9800650692", disabled=True)
    st.text_input("Vergi Dairesi:", value="Kadifekale", disabled=True)
    st.text_input("TC Kimlik No:", value="34510406564", disabled=True)
    st.text_input("Adres:", value="Sevgi mah. 4642 sok no 4/1 Karabağlar İzmir", disabled=True)
    
    st.warning("⚠️ Fatura bilgilerinde eksik veya hata varsa lütfen düzenleyiniz.")

    st.markdown("---")

    # Abonelik Bilgileri
    st.markdown("### ⭐ Abonelik Bilgileri")
    ab_col1, ab_col2 = st.columns([3, 1])
    with ab_col1:
        st.write("**Sipariş ID:** SA1707418640181936")
        st.write("**Tutar:** 0₺")
        st.write("**Son Tarih:** 27.11.2026")
        st.write("**Durum:** Aktif")
    with ab_col2:
        st.metric(label="Kalan Gün", value="78 Gün", delta="Aktif")
        
    st.info("Abonelik uzatma: Süre uzatma işlemleri yönetimimiz tarafından yapılmaktadır. Süreniz dolmadan önce lütfen destek talebi oluşturarak bize ulaşın.")

    st.markdown("---")
    
    # Mağaza Yüklenebilir Ürün Adetleri
    st.markdown("### 📦 Mağaza Ürün Limitleri")
    p1, p2 = st.columns(2)
    with p1:
        st.metric("Trendyol Mağazanıza yüklenebilir ürün adedi", "21210")
        st.metric("N11 Mağazanıza yüklenebilir ürün adedi", "33890")
        st.metric("EPtt AVM Mağazanıza yüklenebilir ürün adedi", "39231")
    with p2:
        st.metric("Çiçeksepeti Mağazanıza yüklenebilir ürün adedi", "32351")
        st.metric("Hepsiburada Mağazanıza yüklenebilir ürün adedi", "42662")

    st.markdown("---")
    st.success("📢 **Duyurularım** — Sistem güncellemeleri ve duyurular burada yer almaktadır. (Toplam: 1)")

elif st.session_state.selected_menu == "Destek Taleplerim":
    st.subheader("📌 Destek Taleplerim")
    st.info("Destek talebi geçmişiniz ve durumları.")

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

elif st.session_state.selected_menu == "Trendyol":
    st.subheader("🛍️ Trendyol Ürünlerim")
    with st.expander("⚠️ Önemli Bilgilendirme", expanded=False):
        st.warning("Trendyol entegrasyonu ve ürün yönetimi ile ilgili tüm toplu işlemler bu alandan gerçekleştirilir.")

    ty_table = pd.DataFrame({
        "Barkod": ["8697577754265107681282837", "8697577752520107681282837"],
        "Ürün Adı": ["8Bitdo Retro R8 Fare", "Aula S98 Pro 3 Modlu RGB"],
        "Satış Fiyatı": ["10137 TL", "8002.14 TL"],
        "Durum": ["Onaylı", "Satışa Kapalı"]
    })
    st.dataframe(ty_table, use_container_width=True)

elif st.session_state.selected_menu == "Çiçeksepeti":
    st.subheader("🌸 Çiçeksepeti Yönetim Paneli")
    st.info("Çiçeksepeti ürün ve sipariş yönetimi aktif.")

elif st.session_state.selected_menu == "N11":
    st.subheader("🟠 N11 Yönetim Paneli")
    st.info("N11 ürün ve sipariş yönetimi aktif.")

elif st.session_state.selected_menu == "E-PTT AVM":
    st.subheader("🏢 E-PTT AVM Yönetim Paneli")
    st.info("E-PTT AVM ürün ve sipariş yönetimi aktif.")

elif st.session_state.selected_menu == "Hepsiburada":
    st.subheader("🛒 Hepsiburada Yönetim Paneli")
    st.info("Hepsiburada mağazanıza ait siparişler ve ürün senkronizasyon alanları.")

elif st.session_state.selected_menu == "Pazarama":
    st.subheader("👑 Pazarama Yönetim Paneli")
    st.info("Pazarama entegrasyonu yakında aktifleşecektir.")

elif st.session_state.selected_menu == "İdefix":
    st.subheader("👑 İdefix Yönetim Paneli")
    st.info("İdefix entegrasyonu yakında aktifleşecektir.")

elif st.session_state.selected_menu == "Ayarlar":
    st.subheader("⚙️ Genel Sistem Ayarları")
    st.text_input("Firma Adı", value="Şahin Yiğit E-Ticaret")
    st.text_input("Bildirim E-postası", value="sah1357sah@gmail.com")
