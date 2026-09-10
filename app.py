import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Şah Entegre - E-Ticaret Yönetim Paneli",
    page_icon="👑",
    layout="wide",
)

# MetEntegre ile Birebir Aynı Canlı, Renkli ve Ferah Profesyonel CSS
st.markdown(
    """
    <style>
    .stApp {
        background-color: #f8fafc;
    }
    /* Anasayfa Renkli Pazar Yeri Grid Kartları */
    .market-grid-row {
        display: flex;
        gap: 8px;
        margin-bottom: 8px;
        width: 100%;
    }
    .market-card-btn {
        flex: 1;
        background: white;
        border: 1px solid #cbd5e1;
        border-radius: 8px;
        padding: 12px 6px;
        text-align: center;
        text-decoration: none !important;
        box-shadow: 0 2px 4px rgba(0,0,0,0.04);
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        min-height: 85px;
        transition: all 0.2s ease-in-out;
    }
    .market-card-btn:hover {
        border-color: #94a3b8;
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.08);
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
    /* Canlı Pazar Yeri Renkleri */
    .bg-hb { background-color: #ff6600; }
    .bg-ty { background-color: #f27a1a; }
    .bg-cs { background-color: #e6005c; }
    .bg-ptt { background-color: #ff9900; }
    .bg-n11 { background-color: #6b46c1; }
    .bg-pz { background-color: #0099ff; }
    .bg-id { background-color: #00b33c; }

    /* Üst İstatistik Sayacı Kutuları */
    .metric-grid {
        display: flex;
        gap: 6px;
        margin-bottom: 12px;
        width: 100%;
        flex-wrap: wrap;
    }
    .metric-box {
        flex: 1;
        min-width: 130px;
        background: white;
        border: 1px solid #cbd5e1;
        border-radius: 8px;
        padding: 12px;
        text-align: center;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }
    .metric-val {
        font-size: 18px;
        font-weight: 800;
    }
    .metric-lbl {
        font-size: 10px;
        font-weight: 600;
        color: #64748b;
        margin-top: 2px;
        text-transform: uppercase;
    }
    </style>
""",
    unsafe_allow_html=True,
)

if "selected_menu" not in st.session_state:
  st.session_state.selected_menu = "Anasayfa"

# Sidebar Başlığı ve Navigasyon
st.sidebar.markdown(
    """
    <div style="text-align: center; padding: 10px 0; margin-bottom: 10px;">
        <span style="font-size: 32px; font-weight: 800; font-family: 'Georgia', serif; font-style: italic; color: #f27a1a;">Şah</span>
        <span style="font-size: 18px; font-weight: 600; letter-spacing: 1px; margin-left: 4px;">ENTEGRE</span>
        <div style="font-size: 11px; color: #888; margin-top: 2px;">👑 Yönetim Paneli</div>
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
  st.session_state.selected_menu = selected_menu
  st.rerun()

# -------------------------------------------------------------
# 1. ANA SAYFA GÖRÜNÜMÜ
# -------------------------------------------------------------
if selected_menu == "Anasayfa":
  st.subheader("👑 Şah Entegre Kontrol Paneli")

  # Üst Pazar Yeri Kare Kutuları (Tıklanabilir Linkler)
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

  # URL Parametresi ile Anasayfadan Pazar Yerine Geçiş
  query_params = st.query_params
  if "menu" in query_params:
    target = query_params["menu"]
    if target in menu_options:
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

  st.markdown("---")

  # Abonelik ve Limitler
  st.markdown("### ⭐ Abonelik & Mağaza Limitleri")
  col_ab1, col_ab2 = st.columns(2)
  with col_ab1:
    st.write("**Sipariş ID:** SA1707418640181936")
    st.write("**Tutar:** 0₺ | **Durum:** Aktif")
    st.metric(label="Kalan Abonelik Süresi", value="78 Gün")
  with col_ab2:
    st.metric("Trendyol Ürün Limiti", "21.210")
    st.metric("Hepsiburada Ürün Limiti", "42.662")

# -------------------------------------------------------------
# 2. PAZARYERLERİ & SİSTEMDEKİ ÜRÜNLER (METENTEGRE BİREBİR)
# -------------------------------------------------------------
elif selected_menu in [
    "Sistemdeki Ürünler",
    "Trendyol",
    "Hepsiburada",
    "N11",
    "Çiçeksepeti",
    "E-PTT AVM",
]:
  st.subheader(f"📊 {selected_menu} - Ürün ve Entegrasyon Yönetimi")
  st.markdown(
      '<span style="font-size: 13px; color: #64748b;">Mağazanıza ait'
      " tüm ürünler, orijinal resimleri, stoklar ve varyant dağılımları.</span>",
      unsafe_allow_html=True,
  )

  # MetEntegre Üst Yönetim ve Senkronizasyon Butonları
  st.markdown("##### ⚡ Hızlı İşlemler & API Yönetimi")
  b1, b2, b3, b4 = st.columns(4)
  with b1:
    if st.button("🔄 Tam Senkronizasyon"):
      st.success("Tüm pazaryeri senkronizasyonu başlatıldı!")
  with b2:
    if st.button("📥 Mağazadan Ürün Çek"):
      st.success("Ürünler API üzerinden başarıyla çekildi!")
  with b3:
    if st.button("🔗 API Bağlantısını Test Et"):
      st.success("API Bağlantısı ve Token Durumu: Sorunsuz Çalışıyor (200 OK)")
  with b4:
    if st.button("📦 Tüm Stokları Güncelle"):
      st.success("Stoklar güncellendi!")

  st.markdown("---")

  # MetEntegre Üst Renkli Sayaç Kartları
  st.markdown(
      """
        <div class="metric-grid">
            <div class="metric-box">
                <div class="metric-val" style="color: #16a34a;">4.009</div>
                <div class="metric-lbl">Toplam Kategori</div>
            </div>
            <div class="metric-box">
                <div class="metric-val" style="color: #0284c7;">202.046</div>
                <div class="metric-lbl">Toplam Sistem Ürünü</div>
            </div>
            <div class="metric-box">
                <div class="metric-val" style="color: #7c3aed;">60.004</div>
                <div class="metric-lbl">Stoklu Ürünler (>0)</div>
            </div>
            <div class="metric-box">
                <div class="metric-val" style="color: #dc2626;">142.042</div>
                <div class="metric-lbl">Tükenmiş Ürünler</div>
            </div>
            <div class="metric-box">
                <div class="metric-val" style="color: #2563eb;">9.631</div>
                <div class="metric-lbl">Varyantlı Ürün</div>
            </div>
            <div class="metric-box">
                <div class="metric-val" style="color: #d97706;">50</div>
                <div class="metric-lbl">Görünen Ürün</div>
            </div>
        </div>
    """,
      unsafe_allow_html=True,
  )

  # Filtreler ve Arama Çubuğu
  scol1, scol2 = st.columns([2, 3])
  with scol1:
    st.markdown(
        "**Tümü (202.046)** &nbsp;|&nbsp; <span"
        ' style="color: #16a34a; font-weight: 600;">Aktif (60.004)</span>'
        ' &nbsp;|&nbsp; <span style="color: #dc2626; font-weight:'
        ' 600;">Tükenmiş (142.042)</span>',
        unsafe_allow_html=True,
    )
  with scol2:
    arama_metni = st.text_input(
        "🔍 SKU, model veya ürün adı ile ara...",
        placeholder="Arama yapın ve Enter'a basın...",
    )

  st.markdown("---")

  # Genişletilmiş Canlı Ürün Kataloğu (Gerçek Resimler, Renkli Fiyatlar ve Varyant Kutuları)
   katalog_data = {
      "Görsel": [
          "https://images.unsplash.com/photo-1543163521-1bf539c55dd2?w=100&auto=format&fit=crop&q=60",
          "https://images.unsplash.com/photo-1595950653106-6c9ebd614d3a?w=100&auto=format&fit=crop&q=60",
          "https://images.unsplash.com/photo-1515886657613-9f3515b0c78f?w=100&auto=format&fit=crop&q=60",
          "https://images.unsplash.com/photo-1539109136881-3be0616acf4b?w=100&auto=format&fit=crop&q=60",
          "https://images.unsplash.com/photo-1552374196-1ab2a1c593e8?w=100&auto=format&fit=crop&q=60",
          "https://images.unsplash.com/photo-1584308666744-24d5c474f2ae?w=100&auto=format&fit=crop&q=60",
          "https://images.unsplash.com/photo-1522337360788-8b13dee7a37e?w=100&auto=format&fit=crop&q=60",
      ],
      "ÜRÜN ID": [
          "717142",
          "717138",
          "717137",
          "717136",
          "717134",
          "717130",
          "717125",
      ],
      "ÜRÜN ADI": [
          "Kadın Yüksek Taban Rahat Şık Günlük Spor Ayakkabı",
          "Kadın Yüksek Taban Rahat Şık Günlük Spor Ayakkabı",
          "Kadın Yüksek Taban Rahat Şık Günlük Spor Ayakkabı",
          "Kadın Beli Lastikli Pantolon",
          "Kadın Bürümcük Kumaş Pantolon",
          "Su Dalgası Uzun Perçemsiz Peruk",
          "Sentetik Örgülük Esnek Saç",
      ],
      "MODEL / SKU": [
          "CLZ191 - 52755",
          "CLZ191 - 52766",
          "CLZ191 - 52888",
          "CLZ191 - 53578",
          "CLZ191 - 59120",
          "CYRB-462192",
          "CYRB-462199",
      ],
      "FİYAT": [
          "🟢 650,00 ₺",
          "🟢 650,00 ₺",
          "🟢 650,00 ₺",
          "🟢 332,00 ₺",
          "🟢 241,00 ₺",
          "🟢 292,76 ₺",
          "🟢 156,56 ₺",
      ],
      "ANA STOK": ["🟡 500", "🟡 500", "🟡 500", "🟡 239", "🟡 250", "🟡 12", "🟡 45"],
      "VARYANTLAR (BEDEN / ADET)": [
          "36(100) 37(100) 38(100) 39(100) 40(100)",
          "36(100) 37(97) 38(100) 39(99) 40(100)",
          "36(100) 37(100) 38(100) 39(100) 40(100)",
          "S(50) M(50) L(50) XL(44) XXL(45)",
          "S(50) M(50) L(50) XL(50)",
          "Standart (12 Adet)",
          "Standart (45 Adet)",
      ],
  }

  df_katalog = pd.DataFrame(katalog_data)

  # Arama filtresi uygulaması
  if arama_metni:
    df_katalog = df_katalog[
        df_katalog["ÜRÜN ADI"]
        .str.lower()
        .str.contains(arama_metni.lower())
        | df_katalog["MODEL / SKU"]
        .str.lower()
        .str.contains(arama_metni.lower())
    ]

  # Tabloyu akıcı ve resimli şekilde ekrana basma
  st.dataframe(
      df_katalog,
      column_config={
          "Görsel": st.column_config.ImageColumn(
              "RESİM", help="Orijinal Ürün Görseli", width="small"
          )
      },
      use_container_width=True,
      hide_index=True,
      height=500,
  )

# -------------------------------------------------------------
# 3. DİĞER MENÜLER
# -------------------------------------------------------------
elif selected_menu == "Destek Taleplerim":
  st.subheader("📌 Destek Taleplerim")
  st.info("Aktif destek talebi bulunmamaktadır.")

elif selected_menu == "Bildirimler":
  st.subheader("🔔 Sistem Bildirimleri")
  st.success("Tüm sistem bildirimleri güncel.")

elif selected_menu == "Duyurular":
  st.subheader("📢 Duyurular ve Güncellemeler")
  st.info("Şah Entegre v3.2 sürümü yayında.")

elif selected_menu == "Oto Kritik Stok":
  st.subheader("⚙️ Oto Kritik Stok Yönetimi")
  st.number_input("Kritik Stok Eşiği", value=5)

elif selected_menu == "Ayarlar":
  st.subheader("⚙️ Genel Sistem ve API Ayarları")
  st.text_input("Firma Adı", value="Şahin Yiğit E-Ticaret")
  st.text_input("Trendyol API Key", value="************************")
  st.text_input("Hepsiburada Merchant ID", value="HB-9856321")
