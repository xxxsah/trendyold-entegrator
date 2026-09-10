import streamlit as st
import pandas as pd

st.set_page_config(
    page_title="Şah Entegre - E-Ticaret Yönetim Paneli",
    page_icon="👑",
    layout="wide",
)

# Mobilde ve masaüstünde kutuların alt alta kaymasını önleyen ve MetEntegre stili sağlayan CSS
st.markdown(
    """
    <style>
    .stApp {
        background-color: #f8f9fa;
    }
    /* Anasayfa Pazaryeri Grid Yapısı */
    .market-container {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin-bottom: 10px;
    }
    .market-card-item {
        flex: 1;
        min-width: 130px;
    }
    div.stButton > button {
        width: 100%;
        height: 85px;
        border-radius: 8px;
        font-weight: bold;
        font-size: 12px;
        color: white;
        border: none;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        transition: 0.2s;
    }
    div.stButton > button:hover {
        opacity: 0.9;
        transform: translateY(-1px);
    }
    .btn-hb > button { background-color: #ff6600 !important; }
    .btn-ty > button { background-color: #f27a1a !important; }
    .btn-cs > button { background-color: #e6005c !important; }
    .btn-ptt > button { background-color: #ff9900 !important; }
    .btn-n11 > button { background-color: #6b46c1 !important; }
    .btn-pz > button { background-color: #0099ff !important; }
    .btn-id > button { background-color: #00b33c !important; }
    </style>
""",
    unsafe_allow_html=True,
)

if "selected_menu" not in st.session_state:
  st.session_state.selected_menu = "Anasayfa"

if "previous_menu" not in st.session_state:
  st.session_state.previous_menu = "Anasayfa"

# Sidebar Başlığı
st.sidebar.markdown(
    """
    <div style="text-align: center; padding: 10px 0; margin-bottom: 10px;">
        <span style="font-size: 34px; font-weight: 800; font-family: 'Georgia', serif; font-style: italic; color: #f27a1a; text-shadow: 1px 1px 2px rgba(0,0,0,0.1);">Şah</span>
        <span style="font-size: 20px; font-weight: 600; letter-spacing: 1.5px; margin-left: 4px;">ENTEGRE</span>
        <div style="font-size: 12px; color: #888; margin-top: 4px;">👑 Yönetim Paneli</div>
    </div>
""",
    unsafe_allow_html=True,
)

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
    "Ayarlar",
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
  # 1. Satır: 4'lü Yan Yana Kare Kutular
  st.markdown('<div class="market-container">', unsafe_allow_html=True)
  col1, col2, col3, col4 = st.columns(4)
  with col1:
    st.markdown('<div class="btn-hb">', unsafe_allow_html=True)
    if st.button("🛒 HEPSİBURADA\n\n1 Kargoda", key="hb_btn"):
      st.session_state.previous_menu = "Anasayfa"
      st.session_state.selected_menu = "Hepsiburada"
      st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
  with col2:
    st.markdown('<div class="btn-ty">', unsafe_allow_html=True)
    if st.button("📦 TRENDYOL\n\nSipariş yok", key="ty_btn"):
      st.session_state.previous_menu = "Anasayfa"
      st.session_state.selected_menu = "Trendyol"
      st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
  with col3:
    st.markdown('<div class="btn-cs">', unsafe_allow_html=True)
    if st.button("🌸 ÇİÇEKSEPETİ\n\nSipariş yok", key="cs_btn"):
      st.session_state.previous_menu = "Anasayfa"
      st.session_state.selected_menu = "Çiçeksepeti"
      st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
  with col4:
    st.markdown('<div class="btn-ptt">', unsafe_allow_html=True)
    if st.button("🏢 PTT AVM\n\nSipariş yok", key="ptt_btn"):
      st.session_state.previous_menu = "Anasayfa"
      st.session_state.selected_menu = "E-PTT AVM"
      st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
  st.markdown("</div>", unsafe_allow_html=True)

  # 2. Satır: 3'lü Yan Yana Kare Kutular
  st.markdown('<div class="market-container">', unsafe_allow_html=True)
  col5, col6, col7 = st.columns(3)
  with col5:
    st.markdown('<div class="btn-n11">', unsafe_allow_html=True)
    if st.button("🟠 N11\n\nSipariş yok", key="n11_btn"):
      st.session_state.previous_menu = "Anasayfa"
      st.session_state.selected_menu = "N11"
      st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
  with col6:
    st.markdown('<div class="btn-pz">', unsafe_allow_html=True)
    st.button("👑 PAZARAMA\n\nÇok Yakında", disabled=True, key="pz_btn")
    st.markdown("</div>", unsafe_allow_html=True)
  with col7:
    st.markdown('<div class="btn-id">', unsafe_allow_html=True)
    st.button("👑 İDEFİX\n\nÇok Yakında", disabled=True, key="id_btn")
    st.markdown("</div>", unsafe_allow_html=True)
  st.markdown("</div>", unsafe_allow_html=True)

  st.markdown("---")

  # Fatura Bilgileri
  st.markdown("### 👤 Fatura Bilgileri")
  st.text_input("İsim:", value="Şahin Yiğit", disabled=True)
  st.text_input("Email:", value="sah1357sah@gmail.com", disabled=True)
  st.text_input("Telefon:", value="05346944235", disabled=True)
  st.text_input("Vergi Numarası:", value="9800650692", disabled=True)
  st.text_input("Vergi Dairesi:", value="Kadifekale", disabled=True)
  st.text_input("TC Kimlik No:", value="34510406564", disabled=True)
  st.text_input(
      "Adres:", value="Sevgi mah. 4642 sok no 4/1 Karabağlar İzmir", disabled=True
  )

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

  st.markdown("---")

  # Mağaza Ürün Limitleri
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
  st.success("📢 **Duyurularım** — Sistem güncellemeleri ve duyurular.")

elif st.session_state.selected_menu == "Trendyol":
  st.subheader("🛍️ Trendyol Tüm İşlemler")
  st.info(
      "Trendyol mağazanızdaki ürünler, eşleşme durumları ve toplu işlemler."
  )

  # MetEntegre Üst İstatistik Kartları (Görseldeki gibi)
  m1, m2, m3 = st.columns(3)
  m1.metric("Toplam TY Ürünü", "5.782")
  m2.metric("Senkronize Edilmiş", "2.300")
  m3.metric("Senkronize Edilmemiş", "3.482")

  m4, m5 = st.columns(2)
  m4.metric("TY Aktif", "906")
  m5.metric("Stok Tutmayanlar", "5.236")

  st.markdown("---")

  # MetEntegre Tarzı Detaylı Ürün Tablosu
  st.text_input("🔍 SKU veya Ürün Adı ile Ara...", placeholder="Arama yapın...")

  ty_table = pd.DataFrame({
      "Merchant SKU": [
          "CYRB-462192",
          "CYRB-462175",
          "CYRB-462199",
          "CYRB-46448",
      ],
      "Ürün Adı": [
          "Protez Bandı / 1 Cm",
          "Su Dalgası Uzun Perçemsiz Peruk",
          "Sentetik Örgülük Espirir",
          "Açık Ruz Kumral Beyaz Peruk",
      ],
      "Mağaza Stok": [0, 0, 0, 0],
      "MetEntegre Stok": [0, 0, 0, 0],
      "Mağaza Fiyat": ["292,76 ₺", "1.326,24 ₺", "156,56 ₺", "5.218,56 ₺"],
      "Durum": ["Eşleşti", "Eşleşti", "Eşleşti", "Eşleşti"],
  })
  st.dataframe(ty_table, use_container_width=True)

elif st.session_state.selected_menu == "Destek Taleplerim":
  st.subheader("📌 Destek Taleplerim")
  st.info("Destek talebi geçmişiniz.")

elif st.session_state.selected_menu == "Bildirimler":
  st.subheader("🔔 Bildirimler")
  st.info("Sistem bildirimleri listelenmektedir.")

elif st.session_state.selected_menu == "Duyurular":
  st.subheader("📢 Duyurular")
  st.success("Tüm sistem duyuruları.")

elif st.session_state.selected_menu == "Sistemdeki Ürünler":
  st.subheader("📦 Sistemdeki Ürünler")
  st.text_input("SKU Ara...", placeholder="Arama...")

elif st.session_state.selected_menu == "Oto Kritik Stok":
  st.subheader("⚙️ Oto Kritik Stok Yönetimi")
  st.number_input("Kritik Stok Eşiği", value=5)

elif st.session_state.selected_menu == "Çiçeksepeti":
  st.subheader("🌸 Çiçeksepeti Yönetim Paneli")
  st.info("Çiçeksepeti yönetim paneli aktif.")

elif st.session_state.selected_menu == "N11":
  st.subheader("🟠 N11 Yönetim Paneli")
  st.info("N11 yönetim paneli aktif.")

elif st.session_state.selected_menu == "E-PTT AVM":
  st.subheader("🏢 E-PTT AVM Yönetim Paneli")
  st.info("E-PTT AVM yönetim paneli aktif.")

elif st.session_state.selected_menu == "Hepsiburada":
  st.subheader("🛒 Hepsiburada Yönetim Paneli")
  st.info("Hepsiburada ürün ve sipariş yönetimi aktif.")

elif st.session_state.selected_menu == "Pazarama":
  st.subheader("👑 Pazarama Yönetim Paneli")
  st.info("Çok yakında.")

elif st.session_state.selected_menu == "İdefix":
  st.subheader("👑 İdefix Yönetim Paneli")
  st.info("Çok yakında.")

elif st.session_state.selected_menu == "Ayarlar":
  st.subheader("⚙️ Genel Sistem Ayarları")
  st.text_input("Firma Adı", value="Şahin Yiğit E-Ticaret")
