import streamlit as st
import pandas as pd

st.set_page_config(
    page_title="Şah Entegre - E-Ticaret Yönetim Paneli",
    page_icon="👑",
    layout="wide",
)

# Pazaryeri butonlarını tam kare, renkli ve tıklanabilir kutulara dönüştüren özel CSS
st.markdown(
    """
    <style>
    .stApp {
        background-color: #f8f9fa;
    }
    /* Streamlit butonlarını kare pazaryeri kutularına benzetiyoruz */
    div.stButton > button {
        width: 100%;
        height: 95px;
        border-radius: 10px;
        font-weight: bold;
        font-size: 13px;
        color: white;
        border: none;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        transition: 0.2s;
    }
    div.stButton > button:hover {
        opacity: 0.9;
        transform: translateY(-2px);
    }
    /* Pazaryeri özel renkleri (Göz yormayan, canlı ve şık tonlar) */
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

# Sidebar Başlığı (Şah büyük ve farklı, entegre ayrı)
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
  # 1. Satır: 4'lü Yan Yana Kare Kutular (Hepsiburada, Trendyol, Çiçeksepeti, PTT AVM)
  c1, c2, c3, c4 = st.columns(4)

  with c1:
    st.markdown('<div class="btn-hb">', unsafe_allow_html=True)
    if st.button("🛒 HEPSİBURADA\n\n1 Kargoda", key="hb_btn"):
      st.session_state.previous_menu = "Anasayfa"
      st.session_state.selected_menu = "Hepsiburada"
      st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

  with c2:
    st.markdown('<div class="btn-ty">', unsafe_allow_html=True)
    if st.button("📦 TRENDYOL\n\nSipariş yok", key="ty_btn"):
      st.session_state.previous_menu = "Anasayfa"
      st.session_state.selected_menu = "Trendyol"
      st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

  with c3:
    st.markdown('<div class="btn-cs">', unsafe_allow_html=True)
    if st.button("🌸 ÇİÇEKSEPETİ\n\nSipariş yok", key="cs_btn"):
      st.session_state.previous_menu = "Anasayfa"
      st.session_state.selected_menu = "Çiçeksepeti"
      st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

  with c4:
    st.markdown('<div class="btn-ptt">', unsafe_allow_html=True)
    if st.button("🏢 PTT AVM\n\nSipariş yok", key="ptt_btn"):
      st.session_state.previous_menu = "Anasayfa"
      st.session_state.selected_menu = "E-PTT AVM"
      st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

  # 2. Satır: 3'lü Yan Yana Kare Kutular (N11, Pazarama, İdefix)
  c5, c6, c7 = st.columns(3)

  with c5:
    st.markdown('<div class="btn-n11">', unsafe_allow_html=True)
    if st.button("🟠 N11\n\nSipariş yok", key="n11_btn"):
      st.session_state.previous_menu = "Anasayfa"
      st.session_state.selected_menu = "N11"
      st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

  with c6:
    st.markdown('<div class="btn-pz">', unsafe_allow_html=True)
    st.button("👑 PAZARAMA\n\nÇok Yakında", disabled=True, key="pz_btn")
    st.markdown("</div>", unsafe_allow_html=True)

  with c7:
    st.markdown('<div class="btn-id">', unsafe_allow_html=True)
    st.button("👑 İDEFİX\n\nÇok Yakında", disabled=True, key="id_btn")
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

  st.info(
      "Abonelik uzatma: Süre uzatma işlemleri yönetimimiz tarafından"
      " yapılmaktadır. Süreniz dolmadan önce lütfen destek talebi oluşturarak"
      " bize ulaşın."
  )

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
  st.success(
      "📢 **Duyurularım** — Sistem güncellemeleri ve duyurular burada yer"
      " almaktadır. (Toplam: 1)"
  )

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
  st.dataframe(
      pd.DataFrame({
          "SKU": ["SKU-001", "SKU-002"],
          "Ürün Adı": ["Örnek Ürün A", "Örnek Ürün B"],
          "Kategori": ["Elektronik", "Giyim"],
          "Stok": [150, 42],
          "Fiyat": ["500 ₺", "250 ₺"],
      }),
      use_container_width=True,
  )

elif st.session_state.selected_menu == "Oto Kritik Stok":
  st.subheader("⚙️ Oto Kritik Stok Yönetimi")
  st.number_input("Kritik Stok Eşiği", value=5)

elif st.session_state.selected_menu == "Trendyol":
  st.subheader("🛍️ Trendyol Ürünlerim ve Siparişleri")
  with st.expander("⚠️ Önemli Bilgilendirme", expanded=False):
    st.warning(
        "Trendyol entegrasyonu ve ürün yönetimi ile ilgili tüm toplu işlemler bu"
        " alandan gerçekleştirilir."
    )
  ty_table = pd.DataFrame({
      "Barkod": [
          "8697577754265107681282837",
          "8697577752520107681282837",
      ],
      "Ürün Adı": ["8Bitdo Retro R8 Fare", "Aula S98 Pro 3 Modlu RGB"],
      "Satış Fiyatı": ["10137 TL", "8002.14 TL"],
      "Durum": ["Onaylı", "Satışa Kapalı"],
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
  st.subheader("🛒 Hepsiburada Yönetim Paneli (1 Kargoda)")
  st.info(
      "Hepsiburada mağazanıza ait aktif kargo ve sipariş detayları"
      " listelenmektedir."
  )
  hb_table = pd.DataFrame({
      "Sipariş ID": ["4284984074"],
      "Ürün": ["Örnek Elektronik Parça"],
      "Durum": ["1 Kargoda Hazırlanıyor"],
      "Tutar": ["1.250 ₺"],
  })
  st.dataframe(hb_table, use_container_width=True)

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
