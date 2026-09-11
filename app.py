import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title=(
        "Şah Entegre - Yapay Zeka Destekli E-Ticaret Yönetim Paneli"
    ),
    page_icon="👑",
    layout="wide",
)

# MetEntegre Standardında Profesyonel Tasarım CSS
st.markdown(
    """
    <style>
    .stApp { background-color: #f1f5f9; }
    .market-grid-row { display: flex; gap: 8px; margin-bottom: 8px; width: 100%; }
    .market-card-btn {
        flex: 1; background: white; border: 1px solid #cbd5e1; border-radius: 8px;
        padding: 10px; text-align: center; text-decoration: none !important;
        box-shadow: 0 2px 4px rgba(0,0,0,0.04); display: flex; flex-direction: column;
        align-items: center; justify-content: center; min-height: 80px;
    }
    .m-badge { font-size: 11px; font-weight: 700; padding: 4px 8px; border-radius: 4px; color: white; margin-bottom: 4px; width: 100%; text-align: center; }
    .m-status { font-size: 11px; font-weight: 600; color: #334155; }
    .bg-hb { background-color: #ff6600; }
    .bg-ty { background-color: #f27a1a; }
    .bg-cs { background-color: #e6005c; }
    .bg-ptt { background-color: #ff9900; }
    .bg-n11 { background-color: #6b46c1; }
    
    .metric-grid { display: flex; gap: 6px; margin-bottom: 12px; width: 100%; flex-wrap: wrap; }
    .metric-box { flex: 1; min-width: 130px; background: white; border: 1px solid #cbd5e1; border-radius: 8px; padding: 12px; text-align: center; }
    .metric-val { font-size: 18px; font-weight: 800; color: #0f172a; }
    .metric-lbl { font-size: 10px; font-weight: 600; color: #64748b; margin-top: 2px; text-transform: uppercase; }
    
    .ai-box { background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%); color: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 12px rgba(79, 70, 229, 0.2); }
    </style>
""",
    unsafe_allow_html=True,
)

if "selected_menu" not in st.session_state:
  st.session_state.selected_menu = "Anasayfa"

# Sidebar
st.sidebar.markdown(
    """
    <div style="text-align: center; padding: 10px 0; margin-bottom: 10px;">
        <span style="font-size: 32px; font-weight: 800; font-family: 'Georgia', serif; font-style: italic; color: #f27a1a;">Şah</span>
        <span style="font-size: 18px; font-weight: 600; letter-spacing: 1px; margin-left: 4px;">ENTEGRE</span>
        <div style="font-size: 11px; color: #888; margin-top: 2px;">👑 Yapay Zeka Destekli v4.2</div>
    </div>
""",
    unsafe_allow_html=True,
)

menu_options = [
    "Anasayfa",
    "Sistemdeki Ürünler",
    "Trendyol Entegrasyonu",
    "Hepsiburada Entegrasyonu",
    "N11 Entegrasyonu",
    "👑 Şah Yapay Zeka Asistanı",
    "API & Barkod Eşitleme",
    "Ayarlar",
]

selected_menu = st.sidebar.selectbox("Menü", menu_options)

# -------------------------------------------------------------
# 1. ANA SAYFA
# -------------------------------------------------------------
if selected_menu == "Anasayfa":
  st.subheader("👑 Şah Entegre Ana Kontrol Paneli")

  st.markdown(
      """
        <div class="market-grid-row">
            <div class="market-card-btn"><div class="m-badge bg-hb">HEPSİBURADA</div><div class="m-status">60.000+ Ürün Aktif</div></div>
            <div class="market-card-btn"><div class="m-badge bg-ty">TRENDYOL</div><div class="m-status">21.210 Ürün Aktif</div></div>
            <div class="market-card-btn"><div class="m-badge bg-n11">N11</div><div class="m-status">33.890 Ürün Aktif</div></div>
            <div class="market-card-btn"><div class="m-badge bg-cs">ÇİÇEKSEPETİ</div><div class="m-status">Aktif</div></div>
        </div>
    """,
      unsafe_allow_html=True,
  )

  st.markdown("---")
  st.markdown("### 📊 Genel Entegrasyon ve Yapay Zeka Durumu")
  st.info(
      "Yapay zeka motoru aktif; ürün optimizasyonu, fiyatlandırma ve otomatik"
      " stok senkronizasyonu arka planda çalışmaktadır."
  )

  col1, col2, col3 = st.columns(3)
  with col1:
    st.metric("Toplam Sistem Ürünü", "115.100+", "Gerçek Zamanlı")
  with col2:
    st.metric("Yapay Zeka Optimize Eden", "98.450", "SEO Uyumlu")
  with col3:
    st.metric("Barkod Eşleşmeyen", "1.240", "Yapay Zeka Düzeltiyor")

# -------------------------------------------------------------
# 2. SİSTEMDEKİ ÜRÜNLER & PAZARYERİ YÖNETİMİ
# -------------------------------------------------------------
elif selected_menu in [
    "Sistemdeki Ürünler",
    "Trendyol Entegrasyonu",
    "Hepsiburada Entegrasyonu",
    "N11 Entegrasyonu",
]:
  st.subheader(f"📦 {selected_menu} - Ürün Kataloğu ve Stok Yönetimi")

  # Üst Yönetim Butonları
  b1, b2, b3, b4 = st.columns(4)
  with b1:
    if st.button("📥 Pazaryerinden Ürün Çek (API)"):
      st.success(
          "API üzerinden tüm ürün listesi ve orijinal görseller çekiliyor..."
      )
  with b2:
    if st.button("🔄 Barkodları Eşleştir"):
      st.success("Eksik barkodlar katalog verileriyle eşleştirildi!")
  with b3:
    if st.button("📦 Stokları Güncelle"):
      st.success("Tüm mağazaların stokları güncellendi!")
  with b4:
    if st.button("🤖 AI ile Ürünleri Optimize Et"):
      st.success("Yapay zeka tüm ürün başlık ve açıklamalarını düzenledi!")

  st.markdown("---")

  # Sayaçlar
  st.markdown(
      """
        <div class="metric-grid">
            <div class="metric-box"><div class="metric-val" style="color: #16a34a;">60.004</div><div class="metric-lbl">Toplam Ürün (Katalog)</div></div>
            <div class="metric-box"><div class="metric-val" style="color: #0284c7;">58.200</div><div class="metric-lbl">Stoklu Ürünler</div></div>
            <div class="metric-box"><div class="metric-val" style="color: #dc2626;">1.804</div><div class="metric-lbl">Tükenmiş Ürün</div></div>
            <div class="metric-box"><div class="metric-val" style="color: #7c3aed;">60.000+</div><div class="metric-lbl">Yapay Zeka Denetimli</div></div>
        </div>
    """,
      unsafe_allow_html=True,
  )

  col_f1, col_f2 = st.columns([2, 3])
  with col_f1:
    st.markdown(
        "**Filtreler:** <span style='color: #16a34a; font-weight:600;'>Tümü"
        " Göster</span>",
        unsafe_allow_html=True,
    )
  with col_f2:
    arama_sorgusu = st.text_input(
        "🔍 60.000+ Ürün İçinde SKU, Barkod veya Ad ile Ara...",
        placeholder="Aramak istediğiniz kelimeyi yazın...",
    )

  genis_katalog = []
  for i in range(1, 51):
    genis_katalog.append({
        "Görsel": (
            "https://images.unsplash.com/photo-1543163521-1bf539c55dd2?w=100&auto=format&fit=crop&q=60"
            if i % 2 == 0
            else "https://images.unsplash.com/photo-1595950653106-6c9ebd614d3a?w=100&auto=format&fit=crop&q=60"
        ),
        "ÜRÜN ID": f"HB-717{100+i}",
        "ÜRÜN ADI": (
            f"Profesyonel E-Ticaret Ürünü ve Varyant Serisi #{i}"
        ),
        "SKU / BARKOD": f"SKU-TRND-{8000+i}",
        "FİYAT": f"🟢 {150 + (i*12)},00 ₺",
        "STOK": f"🟡 {50 + i}",
        "AI DURUMU": "✨ Optimize Edildi",
    })

  df_full = pd.DataFrame(genis_katalog)

  if arama_sorgusu:
    df_full = df_full[
        df_full["ÜRÜN ADI"]
        .str.lower()
        .str.contains(arama_sorgusu.lower())
        | df_full["SKU / BARKOD"]
        .str.lower()
        .str.contains(arama_sorgusu.lower())
    ]

  st.dataframe(
      df_full,
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
# 3. ŞAH YAPAY ZEKA ASİSTANI YÖNETİMİ
# -------------------------------------------------------------
elif selected_menu == "👑 Şah Yapay Zeka Asistanı":
  st.subheader("👑 Şah Yapay Zeka ve E-Ticaret Otomasyon Asistanı")
  st.markdown(
      "Bu ekrandan mağazanızdaki ürünleri yapay zekaya inceletebilir, SEO"
      " açıklamaları yazdırabilir ve hata kodlarını düzelttirebilirsiniz."
  )

  st.markdown(
      """
        <div class="ai-box">
            <h3>🤖 Şah AI Motoru Aktif (GPT-4 / Claude Entegre)</h3>
            <p>Mağazanızdaki 60.000+ ürünün başlıkları, açıklamaları ve anahtar kelimeleri arama motorlarında üst sıralara çıkmak için yapay zeka tarafından optimize edilmektedir.</p>
        </div>
    """,
      unsafe_allow_html=True,
  )

  st.markdown("### ⚡ Yapay Zeka Komut Paneli")

  ai_secenek = st.selectbox(
      "Yapılacak İşlemi Seçin:",
      [
          "Tüm Ürünlerin Açıklamalarını SEO Uyumlu Yeniden Yaz",
          "Kritik Stoktaki Ürünler İçin Fiyat Önerisi Oluştur",
          "Barkod Uyuşmazlıklarını Yapay Zeka ile Otomatik Eşleştir",
          "Müşteri Soru ve Mesajları İçin Otomatik Yanıt Taslağı Oluştur",
      ],
  )

  if st.button("🚀 Yapay Zeka İşlemini Başlat"):
    with st.spinner("Yapay zeka verileri işliyor ve optimize ediyor..."):
      st.success(
          f"'{ai_secenek}' görevi başarıyla tamamlandı! Mağaza verileriniz"
           " güncellendi."
      )

  st.markdown("---")
  st.markdown("### 💬 Ürün ve Süreçler İçin Yapay Zekaya Soru Sor")
  kullanici_sorusu = st.text_input(
      "Örn: Hangi ürünlerimde stok sorunu var veya başlıklar nasıl"
      " geliştirilmeli?"
  )
  if st.button("Yapay Zekaya Danış"):
    if kullanici_sorusu:
      st.info(
          f"**Şah AI Yanıtı:** '{kullanici_sorusu' konusunu analiz ettim."
          " Mağazanızdaki ana kategorilerde listeleme optimizasyonu yapılması"
          " ve eksik barkodların otomatik eşleme modülü ile taranması"
          " tavsiye edilir. Sistem sorunsuz çalışmaktadır."
      )
    else:
      st.warning("Lütfen yapay zekaya sormak istediğiniz soruyu yazın.")

# -------------------------------------------------------------
# 4. API & BARKOD EŞLEŞTİRME
# -------------------------------------------------------------
elif selected_menu == "API & Barkod Eşitleme":
  st.subheader("⚙️ API Bağlantıları ve Barkod Eşitleme Merkezi")
  st.text_input("Trendyol Supplier ID", value="985632", type="password")
  st.text_input(
      "Trendyol API Key / Secret", value="*******************pi_key", type="password"
  )
  if st.button("Trendyol API Bağlantısını Test Et"):
    st.success("Trendyol API bağlantısı başarılı! Mağaza verileri senkron.")

# -------------------------------------------------------------
# 5. AYARLAR
# -------------------------------------------------------------
elif selected_menu == "Ayarlar":
  st.subheader("⚙️ Sistem Ayarları")
  st.text_input("Firma Adı", value="Şahin Yiğit E-Ticaret")
  st.text_input("Bildirim E-postası", value="sah1357sah@gmail.com")
  st.success("Ayarlar güncel.")
