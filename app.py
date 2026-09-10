import streamlit as st
import pandas as pd

st.set_page_config(
    page_title="Şah Entegre - E-Ticaret Yönetim Paneli",
    page_icon="👑",
    layout="wide",
)

# MetEntegre tarzı rengarenk, canlı, şık ve asla siyah/boğuk olmayan özel CSS
st.markdown(
    """
    <style>
    .stApp {
        background-color: #f8fafc;
    }
    /* Anasayfa Kare Kutular (Mobilde bile yan yana kilitlenir) */
    .market-grid-row {
        display: flex;
        gap: 8px;
        margin-bottom: 8px;
        width: 100%;
    }
    .market-card-btn {
        flex: 1;
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 10px 4px;
        text-align: center;
        text-decoration: none !important;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        min-height: 80px;
        transition: all 0.2s ease-in-out;
    }
    .market-card-btn:hover {
        border-color: #cbd5e1;
        transform: translateY(-2px);
        box-shadow: 0 4px 6px rgba(0,0,0,0.08);
    }
    .m-badge {
        font-size: 11px;
        font-weight: 700;
        padding: 4px 8px;
        border-radius: 4px;
        color: white;
        margin-bottom: 6px;
        width: 100%;
        text-align: center;
    }
    .m-status {
        font-size: 11px;
        font-weight: 600;
        color: #334155;
    }
    /* Canlı Pazaryeri Renkleri */
    .bg-hb { background-color: #ff6600; }
    .bg-ty { background-color: #f27a1a; }
    .bg-cs { background-color: #e6005c; }
    .bg-ptt { background-color: #ff9900; }
    .bg-n11 { background-color: #6b46c1; }
    .bg-pz { background-color: #0099ff; }
    .bg-id { background-color: #00b33c; }

    /* Rengarenk İstatistik Kartları */
    .stat-card {
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 14px;
        text-align: center;
        box-shadow: 0 1px 3px rgba(0,0,0,0.03);
        margin-bottom: 8px;
    }
    .stat-number {
        font-size: 22px;
        font-weight: 800;
    }
    .stat-label {
        font-size: 11px;
        font-weight: 600;
        color: #64748b;
        margin-top: 4px;
    }
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
  st.markdown(
      """
        <div class="market-grid-row">
            <a href="?menu=Hepsiburada" target="_self" class="market-card-btn">
                <div class="m-badge bg-hb">HEPSİBURADA</div>
                <div class="m-status">1 Kargoda</div>
            </a>
            <a href="?menu=Trendyol" target="_self" class="market-card-btn">
                <div class="m-badge bg-ty">TRENDYOL</div>
                <div class="m-status">Sipariş yok</div>
            </a>
            <a href="?menu=Çiçeksepeti" target="_self" class="market-card-btn">
                <div class="m-badge bg-cs">ÇİÇEKSEPETİ</div>
                <div class="m-status">Sipariş yok</div>
            </a>
            <a href="?menu=E-PTT AVM" target="_self" class="market-card-btn">
                <div class="m-badge bg-ptt">PTT AVM</div>
                <div class="m-status">Sipariş yok</div>
            </a>
        </div>
    """,
      unsafe_allow_html=True,
  )

  # 2. Satır: 3'lü Yan Yana Kare Kutular
  st.markdown(
      """
        <div class="market-grid-row">
            <a href="?menu=N11" target="_self" class="market-card-btn">
                <div class="m-badge bg-n11">N11</div>
                <div class="m-status">Sipariş yok</div>
            </a>
            <div class="market-card-btn" style="opacity: 0.7; cursor: default;">
                <div class="m-badge bg-pz">PAZARAMA</div>
                <div class="m-status" style="color: #94a3b8;">Çok Yakında</div>
            </div>
            <div class="market-card-btn" style="opacity: 0.7; cursor: default;">
                <div class="m-badge bg-id">İDEFİX</div>
                <div class="m-status" style="color: #94a3b8;">Çok Yakında</div>
            </div>
        </div>
    """,
      unsafe_allow_html=True,
  )

  # URL Parametresi ile menü geçiş kontrolü
  query_params = st.query_params
  if "menu" in query_params:
    target = query_params["menu"]
    if target in menu_options:
      st.session_state.previous_menu = "Anasayfa"
      st.session_state.selected_menu = target
      st.rerun()

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

elif selected_menu in [
    "Trendyol",
    "Hepsiburada",
    "N11",
    "Çiçeksepeti",
    "E-PTT AVM",
]:
  st.subheader(f"🛍️ {selected_menu} Tüm Ürünler ve İşlemler")
  st.info(
      f"{selected_menu} mağazanıza ait ürün listesi, fiyatlar ve eşleşme"
      " durumları aşağıdadır."
  )

  # MetEntegre Tarzı Rengarenk Üst İstatistik Kartları
  st.markdown(
      """
        <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px;">
            <div style="flex: 1; min-width: 100px;" class="stat-card">
                <div class="stat-number" style="color: #0284c7;">5.782</div>
                <div class="stat-label">Toplam Ürün</div>
            </div>
            <div style="flex: 1; min-width: 100px;" class="stat-card">
                <div class="stat-number" style="color: #16a34a;">2.300</div>
                <div class="stat-label">Senkronize Edilmiş</div>
            </div>
            <div style="flex: 1; min-width: 100px;" class="stat-card">
                <div class="stat-number" style="color: #dc2626;">3.482</div>
                <div class="stat-label">Senkronize Edilmemiş</div>
            </div>
        </div>
        <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 15px;">
            <div style="flex: 1; min-width: 140px;" class="stat-card">
                <div class="stat-number" style="color: #475569;">906</div>
                <div class="stat-label">Aktif Mağaza</div>
            </div>
            <div style="flex: 1; min-width: 140px;" class="stat-card">
                <div class="stat-number" style="color: #ca8a04;">5.236</div>
                <div class="stat-label">Stok Tutmayanlar</div>
            </div>
        </div>
    """,
      unsafe_allow_html=True,
  )

  st.markdown("---")

  # Arama Çubuğu
  st.text_input("🔍 SKU veya Ürün Adı ile Ara...", placeholder="Arama yapın...")

  # Rengarenk ve Net Ürün Tablosu (Fiyatlar yeşil/renkli vurgulu)
  urunler_data = {
      "Merchant SKU": [
          "CYRB-462192",
          "CYRB-462175",
          "CYRB-462199",
          "CYRB-46448",
          "CYRB-582129",
      ],
      "Ürün Adı": [
          "Protez Bandı / 1 Cm",
          "Su Dalgası Uzun Perçemsiz Peruk",
          "Sentetik Örgülük Espirir",
          "Açık Ruz Kumral Beyaz Peruk",
          "Tokalı Kuyruklu Dağınık Topuz",
      ],
      "Mağaza Stok": [0, 0, 0, 0, 0],
      "Entegre Stok": [0, 0, 0, 0, 0],
      "Mağaza Fiyat": [
          "🟢 292,76 ₺",
          "🟢 1.326,24 ₺",
          "🟢 156,56 ₺",
          "🟢 5.218,56 ₺",
          "🟢 292,32 ₺",
      ],
      "Durum": ["Eşleşti", "Eşleşti", "Eşleşti", "Eşleşti", "Eşleşti"],
  }
  st.dataframe(pd.DataFrame(urunler_data), use_container_width=True)

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
  st.subheader("📦 Tüm Sistem Ürünleri")
  st.text_input("🔍 SKU veya Ürün Adı ile Ara...", placeholder="Arama yapın...")
  st.dataframe(
      pd.DataFrame({
          "SKU": ["SKU-001", "SKU-002", "SKU-003"],
          "Ürün Adı": ["Örnek Ürün A", "Örnek Ürün B", "Örnek Ürün C"],
          "Kategori": ["Elektronik", "Giyim", "Kozmetik"],
          "Stok": [150, 42, 95],
          "Fiyat": ["🟢 500 ₺", "🟢 250 ₺", "🟢 1.200 ₺"],
      }),
      use_container_width=True,
  )

elif st.session_state.selected_menu == "Oto Kritik Stok":
  st.subheader("⚙️ Oto Kritik Stok Yönetimi")
  st.number_input("Kritik Stok Eşiği", value=5)

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
