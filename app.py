import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Şah Entegre - E-Ticaret Yönetim Paneli",
    page_icon="👑",
    layout="wide",
)

# MetEntegre Görsel Standartları İçin Özel CSS (Canlı İstatistikler, Renkli Tablolar ve Varyant Kutuları)
st.markdown(
    """
    <style>
    .stApp {
        background-color: #f4f6f9;
    }
    /* Üst İstatistik Kartları Grid Yapısı */
    .metric-grid {
        display: flex;
        gap: 6px;
        margin-bottom: 10px;
        width: 100%;
        flex-wrap: wrap;
    }
    .metric-box {
        flex: 1;
        min-width: 130px;
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        padding: 10px;
        text-align: center;
        box-shadow: 0 1px 2px rgba(0,0,0,0.03);
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
    /* Tablo İçi Renkli Etiketler ve Kutular */
    .variant-badge {
        display: inline-block;
        background-color: #0066cc;
        color: white;
        font-size: 10px;
        font-weight: 700;
        padding: 2px 6px;
        border-radius: 4px;
        margin: 1px;
        text-align: center;
    }
    .stock-yellow {
        background-color: #fef08a;
        color: #854d0e;
        font-weight: 700;
        padding: 4px 8px;
        border-radius: 4px;
        text-align: center;
        display: inline-block;
        font-size: 12px;
    }
    </style>
""",
    unsafe_allow_html=True,
)

if "selected_menu" not in st.session_state:
  st.session_state.selected_menu = "Sistemdeki Ürünler"

# Sidebar Başlığı
st.sidebar.markdown(
    """
    <div style="text-align: center; padding: 10px 0; margin-bottom: 10px;">
        <span style="font-size: 30px; font-weight: 800; font-family: 'Georgia', serif; font-style: italic; color: #f27a1a;">Şah</span>
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

# Ana Sayfa Görünümü
if selected_menu == "Anasayfa":
  st.subheader("👑 Şah Entegre Kontrol Paneli")
  st.info("Sol menüden pazaryerlerini veya ürün analizlerini seçebilirsiniz.")

# Sistemdeki Ürünler ve Pazaryerleri Ürün Listesi Görünümü (MetEntegre Birebir Tasarım)
elif selected_menu in [
    "Sistemdeki Ürünler",
    "Trendyol",
    "Hepsiburada",
    "N11",
    "Çiçeksepeti",
    "E-PTT AVM",
]:
  st.subheader(f"📊 {selected_menu} Analizi")
  st.markdown(
      '<span style="font-size: 12px; color: #64748b;">Sisteminizdeki'
      " mevcut ürünler, stok durumları ve varyant bilgileri.</span>",
      unsafe_allow_html=True,
  )

  # MetEntegre Üst Renkli Sayaç Kartları (Resimdeki ile Birebir)
  st.markdown(
      """
        <div class="metric-grid">
            <div class="metric-box">
                <div class="metric-val" style="color: #16a34a;">4.009</div>
                <div class="metric-lbl">Toplam Sistem Kategorisi</div>
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
                <div class="metric-lbl">Tükenmiş (>0)</div>
            </div>
            <div class="metric-box">
                <div class="metric-val" style="color: #2563eb;">9.631</div>
                <div class="metric-lbl">Varyantlı Ürün</div>
            </div>
            <div class="metric-box">
                <div class="metric-val" style="color: #d97706;">50</div>
                <div class="metric-lbl">Bu Sayfadaki Ürün</div>
            </div>
        </div>
    """,
      unsafe_allow_html=True,
  )

  # Filtre Sekmeleri ve Arama Çubuğu Satırı
  f_col1, f_col2 = st.columns([2, 3])
  with f_col1:
    st.markdown(
        "**Tümü (202.046)** &nbsp;|&nbsp; <span"
        ' style="color: #64748b;">Aktif (+1) (60.004)</span> &nbsp;|&nbsp;'
        ' <span style="color: #64748b;">Tükenmişler (142.042)</span>',
        unsafe_allow_html=True,
    )
  with f_col2:
    st.text_input(
        "🔍 SKU, model, ürün adı...",
        placeholder="SKU, model, ürün adı... (Enter)",
    )

  st.markdown("---")

  # MetEntegre Tablo Veri Seti (Gerçek Resimler ve Varyant Kutucuklarıyla)
  table_data = {
      "Görsel": [
          "https://images.unsplash.com/photo-1543163521-1bf539c55dd2?w=100&auto=format&fit=crop&q=60",
          "https://images.unsplash.com/photo-1595950653106-6c9ebd614d3a?w=100&auto=format&fit=crop&q=60",
          "https://images.unsplash.com/photo-1515886657613-9f3515b0c78f?w=100&auto=format&fit=crop&q=60",
          "https://images.unsplash.com/photo-1539109136881-3be0616acf4b?w=100&auto=format&fit=crop&q=60",
          "https://images.unsplash.com/photo-1552374196-1ab2a1c593e8?w=100&auto=format&fit=crop&q=60",
      ],
      "ÜRÜN ID": ["717142", "717138", "717137", "717136", "717134"],
      "ÜRÜN ADI": [
          "Kadın Yüksek Taban Rahat Şık Günlük Spor Ayakkabı",
          "Kadın Yüksek Taban Rahat Şık Günlük Spor Ayakkabı",
          "Kadın Yüksek Taban Rahat Şık Günlük Spor Ayakkabı",
          "Kadın Beli Lastikli Pantolon",
          "Kadın Bürümcük Kumaş Pantolon",
      ],
      "MODEL": [
          "CLZ191 - 52755SİYAH",
          "CLZ191 - 52766SİYAH",
          "CLZ191 - 52888SİYAH",
          "CLZ191 - 5357819",
          "CLZ191 - 5912003",
      ],
      "FİYAT": [
          "650,00 ₺",
          "650,00 ₺",
          "650,00 ₺",
          "332,00 ₺",
          "241,00 ₺",
      ],
      "ANA STOK": ["🟡 500", "🟡 500", "🟡 500", "🟡 239", "🟡 250"],
      "VARYANTLAR (BEDEN / ADET)": [
          "36 (100)  37 (100)  38 (100)<br>39 (100)  40 (100)",
          "36 (100)  37 (97)  38 (100)<br>39 (99)  40 (100)",
          "36 (100)  37 (100)  38 (100)<br>39 (100)  40 (100)",
          "S (50)  M (50)  L (50)<br>XL (44)  XXL (45)",
          "S (50)  M (50)  L (50)<br>XL (50)",
      ],
  }

  df_met = pd.DataFrame(table_data)

  # Tabloyu akıcı, kaydırılabilir ve resimli şekilde ekrana basma
  st.dataframe(
      df_met,
      column_config={
          "Görsel": st.column_config.ImageColumn(
              "RESİM", help="Ürün Görseli", width="small"
          ),
          "VARYANTLAR (BEDEN / ADET)": st.column_config.TextColumn(
              "VARYANTLAR (BEDEN / ADET)", help="Beden ve Stok Dağılımı"
          ),
      },
      use_container_width=True,
      hide_index=True,
      height=500,
  )

else:
  st.subheader(f"⚙️ {selected_menu}")
  st.info(f"{selected_menu} paneli aktif durumdadır.")
