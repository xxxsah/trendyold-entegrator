import time
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Şah Entegre - Profesyonel E-Ticaret Yönetim Paneli",
    page_icon="⚡",
    layout="wide",
)

# Profesyonel CSS Entegrasyonu (Orijinal Tasarım Renkleri: Trendyol Turuncusu & Modern Gri)
st.markdown(
    """
    <style>
    .stApp { background-color: #f8fafc; }
    .mp-grid { display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap; }
    .mp-card { flex: 1; min-width: 130px; background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }
    .mp-badge { font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 4px; color: white; display: inline-block; margin-bottom: 6px; }
    .box-container { background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 15px; margin-bottom: 15px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }
    .box-header { background: #f27a1a; color: white; padding: 10px 14px; font-weight: 700; font-size: 14px; border-radius: 6px; margin-bottom: 12px; text-align: left; }
    </style>
""",
    unsafe_allow_html=True,
)

# -------------------------------------------------------------
# OTURUM HAFIZASI (STATE MANAGEMENT) VE DİNAMİK AYARLAR
# -------------------------------------------------------------
if "ayar_komisyon" not in st.session_state:
  st.session_state.ayar_komisyon = 18.0  # % Komisyon Oranı
if "ayar_kar_marji" not in st.session_state:
  st.session_state.ayar_kar_marji = 25.0  # % Kâr Marjı
if "ayar_kargo_fiyati" not in st.session_state:
  st.session_state.ayar_kargo_fiyati = 45.00  # Sabit Kargo Ücreti (TL)
if "ayar_marka" not in st.session_state:
  st.session_state.ayar_marka = "Şah Store"

if "api_bilgileri" not in st.session_state:
  st.session_state.api_bilgileri = {
      "Trendyol Supplier ID": "",
      "Trendyol API Key": "",
      "Trendyol API Secret": "",
      "Hepsiburada Merchant ID": "",
      "N11 App Key": "",
  }

if "urunler_db" not in st.session_state:
  st.session_state.urunler_db = pd.DataFrame([
      {
          "Görsel": "https://images.unsplash.com/photo-1584263155336-d64e9a8f4675?w=100",
          "Barkod": "CYRO-679931-LXL",
          "Ürün Adı": "Siyah Dantelli Sabahlık & Gecelik Takımı",
          "Alış Fiyatı": 400.00,
          "Satış Fiyatı": 726.00,
          "Trendyol Stok": 98,
          "M.Entegre Stok": 150,
          "Durum": "Satışta",
      },
      {
          "Görsel": "https://images.unsplash.com/photo-1543163521-1bf539c55dd2?w=100",
          "Barkod": "CYRO-679931-SM",
          "Ürün Adı": "Siyah Dantelli Sabahlık & Gecelik Takımı (SM)",
          "Alış Fiyatı": 400.00,
          "Satış Fiyatı": 726.00,
          "Trendyol Stok": 100,
          "M.Entegre Stok": 120,
          "Durum": "Satışta",
      },
      {
          "Görsel": "https://images.unsplash.com/photo-1517841905240-472988babdf9?w=100",
          "Barkod": "606214114000007",
          "Ürün Adı": "Ayarlanabilir Dizüstü Destek Tabanı Tam Boy",
          "Alış Fiyatı": 350.00,
          "Satış Fiyatı": 629.70,
          "Trendyol Stok": 27,
          "M.Entegre Stok": 45,
          "Durum": "Satışta",
      },
      {
          "Görsel": "https://images.unsplash.com/photo-1585338107529-13afc5f02586?w=100",
          "Barkod": "606903317053779",
          "Ürün Adı": "TONTON - NO:1 ÇEKMECE 3 KATLI",
          "Alış Fiyatı": 320.00,
          "Satış Fiyatı": 583.31,
          "Trendyol Stok": 44,
          "M.Entegre Stok": 80,
          "Durum": "Satışta",
      },
  ])

if "loglar" not in st.session_state:
  st.session_state.loglar = [
      "Sistem başlatıldı.",
      "Pazaryeri entegrasyon altyapısı hazır.",
  ]

# -------------------------------------------------------------
# ÜST HEADER VE PROFİL MENÜSÜ
# -------------------------------------------------------------
col_h1, col_h2 = st.columns([4, 2])
with col_h1:
  st.markdown(
      "<span style='font-size: 15px; font-weight: 700; color:"
      " #1e293b;'>⚡ Şah Entegre - Profesyonel E-Ticaret Yönetim"
      " Paneli</span>",
      unsafe_allow_html=True,
  )
with col_h2:
  profil_secenekleri = [
      "👤 Mağaza Profili",
      "⚙️ Genel Ayarlar (Komisyon / Kâr)",
      "🔑 Pazaryeri API Bilgileri",
      "📄 Faturalarım",
      "🚪 Çıkış",
  ]
  secilen_profil = st.selectbox(
      "Profil", profil_secenekleri, label_visibility="collapsed"
  )

st.markdown("---")

# Sol Menü Navigasyonu (Orijinal Renk Konsepti)
st.sidebar.markdown(
    """
    <div style="text-align: center; padding: 10px 0; margin-bottom: 10px;">
        <span style="font-size: 26px; font-weight: 800; color: #f27a1a;">ŞAH</span>
        <span style="font-size: 15px; font-weight: 600; color: #0f172a;">ENTEGRE</span>
        <div style="font-size: 11px; color: #64748b; margin-top: 2px;">Merkezi Yönetim Sistemi</div>
    </div>
""",
    unsafe_allow_html=True,
)

menu_options = [
    "🏠 Anasayfa",
    "📦 Ürün Yönetimi & XML",
    "⚙️ Fiyat, Komisyon & Marj Ayarları",
    "🔑 Pazaryeri API Entegrasyonları",
    "🧡 Trendyol",
    "🧡 Hepsiburada",
    "💜 N11",
    "🌸 ÇiçekSepeti",
    "💛 E-PTT AVM",
    "⚡ Oto Kritik Stok",
    "🎧 Destek",
]

selected_menu = st.sidebar.selectbox("Navigasyon", menu_options)

# -------------------------------------------------------------
# PROFİL / HESAP AYARLARI SAYFALARI
# -------------------------------------------------------------
if secilen_profil == "⚙️ Genel Ayarlar (Komisyon / Kâr)":
  st.subheader("⚙️ Fiyatlandırma, Komisyon ve Kargo Ayarları")
  st.markdown(
      "Tüm pazaryerlerine gönderilecek ürün fiyatları buradaki oranlara göre"
      " otomatik hesaplanır."
  )

  c1, c2, c3, c4 = st.columns(4)
  with c1:
    yeni_kar = st.number_input("Kâr Marjı (%)", value=st.session_state.ayar_kar_marji)
  with c2:
    yeni_komisyon = st.number_input(
        "Komisyon Oranı (%)", value=st.session_state.ayar_komisyon
    )
  with c3:
    yeni_kargo = st.number_input(
        "Kargo Ücreti (TL)", value=st.session_state.ayar_kargo_fiyati
    )
  with c4:
    yeni_marka = st.text_input("Marka Adı", value=st.session_state.ayar_marka)

  if st.button("Ayarları Kaydet ve Uygula", use_container_width=True):
    st.session_state.ayar_kar_marji = yeni_kar
    st.session_state.ayar_komisyon = yeni_komisyon
    st.session_state.ayar_kargo_fiyati = yeni_kargo
    st.session_state.ayar_marka = yeni_marka
    st.success("Tüm finansal oranlar başarıyla güncellendi!")

elif secilen_profil == "🔑 Pazaryeri API Bilgileri":
  st.subheader("🔑 Mağaza API Anahtar Yönetimi")
  st.markdown(
      "Pazaryerlerinden ürün çekmek ve ürün göndermek için API anahtarlarınızı"
      " girin."
  )

  for key in st.session_state.api_bilgileri.keys():
    st.session_state.api_bilgileri[key] = st.text_input(
        key, value=st.session_state.api_bilgileri[key], type="password"
    )

  if st.button("API Bilgilerini Kaydet", use_container_width=True):
    st.success("API anahtarları güvenle kaydedildi ve aktif hale getirildi!")

elif secilen_profil == "📄 Faturalarım":
  st.subheader("📄 Abonelik ve Faturalar")
  st.dataframe(
      pd.DataFrame([{
          "Dönem": "2026/09",
          "Hizmet": "Şah Entegre Pro",
          "Tutar": "0.00 TL",
          "Durum": "Ödendi / Aktif",
      }]),
      use_container_width=True,
      hide_index=True,
  )

# -------------------------------------------------------------
# ANASAYFA
# -------------------------------------------------------------
elif selected_menu == "🏠 Anasayfa":
  st.subheader("👑 Ana Kontrol Paneli")

  st.markdown(
      """
        <div class="mp-grid">
            <div class="mp-card"><div class="mp-badge" style="background:#ff6600;">HEPSİBURADA</div><div style="font-size:11px; color:#64748b;">Sipariş</div><div style="font-size:13px; font-weight:700; color:#0f172a;">Bekleyen Yok</div></div>
            <div class="mp-card"><div class="mp-badge" style="background:#f27a1a;">TRENDYOL</div><div style="font-size:11px; color:#64748b;">Sipariş</div><div style="font-size:13px; font-weight:700; color:#0f172a;">Bekleyen Yok</div></div>
            <div class="mp-card"><div class="mp-badge" style="background:#e6005c;">ÇİÇEKSEPETİ</div><div style="font-size:11px; color:#64748b;">Sipariş</div><div style="font-size:13px; font-weight:700; color:#0f172a;">Bekleyen Yok</div></div>
            <div class="mp-card"><div class="mp-badge" style="background:#334155;">PTT AVM</div><div style="font-size:11px; color:#64748b;">Sipariş</div><div style="font-size:13px; font-weight:700; color:#0f172a;">Bekleyen Yok</div></div>
            <div class="mp-card"><div class="mp-badge" style="background:#6b46c1;">N11</div><div style="font-size:11px; color:#64748b;">Sipariş</div><div style="font-size:13px; font-weight:700; color:#0f172a;">Bekleyen Yok</div></div>
        </div>
    """,
      unsafe_allow_html=True,
  )

  # Bilgi Kutusu
  st.markdown(
      f"""
        <div class="box-container">
            <div class="box-header">📊 Aktif Sistem Parametreleri</div>
            <table style="width:100%; font-size:13px; color:#1e293b; border-collapse:collapse;">
                <tr><td style="padding:6px; font-weight:600; width:180px;">Aktif Marka:</td><td>{st.session_state.ayar_marka}</td></tr>
                <tr><td style="padding:6px; font-weight:600;">Kâr Marjı Oranı:</td><td>%{st.session_state.ayar_kar_marji}</td></tr>
                <tr><td style="padding:6px; font-weight:600;">Komisyon Oranı:</td><td>%{st.session_state.ayar_komisyon}</td></tr>
                <tr><td style="padding:6px; font-weight:600;">Sabit Kargo Fiyatı:</td><td>{st.session_state.ayar_kargo_fiyati} TL</td></tr>
            </table>
        </div>
    """,
      unsafe_allow_html=True,
  )

  col_q1, col_q2 = st.columns(2)
  with col_q1:
    if st.button(
        "🚀 Tüm Pazaryerlerini ve Stokları Senkronize Et",
        use_container_width=True,
    ):
      with st.spinner("Stoklar ve fiyatlar güncelleniyor..."):
        time.sleep(1.2)
      st.success("Tüm pazaryerleri başarıyla güncellendi!")
  with col_q2:
    if st.button("📥 Tüm XML Kaynaklarını Tetikle", use_container_width=True):
      with st.spinner("Tedarikçi XML linkleri taranıyor..."):
        time.sleep(1.2)
      st.success("Tüm ürünler güncel stok bilgileriyle çekildi!")

# -------------------------------------------------------------
# ÜRÜN YÖNETİMİ & XML ENTEGRASYONU
# -------------------------------------------------------------
elif selected_menu == "📦 Ürün Yönetimi & XML":
  st.subheader("📦 Ürün Yönetimi, XML ve Pazaryerine Gönderim")

  with st.expander("📥 Tedarikçi XML Linki ile Ürün Ekle", expanded=False):
    xml_link = st.text_input(
        "XML / Feed URL",
        placeholder="https://tedarikci-ornek.com/urunler.xml",
    )
    ted_adi = st.text_input("Tedarikçi Firma Adı", placeholder="Örn: Global Depo")
    if st.button("XML Ürünlerini Sisteme Aktar"):
      if xml_link:
        with st.spinner("XML verileri parse ediliyor..."):
          time.sleep(1.5)
          yeni_urun = {
              "Görsel": (
                  "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=100"
              ),
              "Barkod": "XML-NEW-9981",
              "Ürün Adı": f"XML Gelen Ürün ({ted_adi})",
              "Alış Fiyatı": 500.00,
              "Satış Fiyatı": round(
                  500.00
                  * (1 + st.session_state.ayar_kar_marji / 100)
                  * (1 + st.session_state.ayar_komisyon / 100)
                  + st.session_state.ayar_kargo_fiyati,
                  2,
              ),
              "Trendyol Stok": 75,
              "M.Entegre Stok": 75,
              "Durum": "Satışta",
          }
          st.session_state.urunler_db = pd.concat(
              [st.session_state.urunler_db, pd.DataFrame([yeni_urun])],
              ignore_index=True,
          )
        st.success("XML ürünleri başarıyla veritabanına eklendi!")
      else:
        st.error("Lütfen geçerli bir XML linki girin.")

  col_b1, col_b2, col_b3 = st.columns(3)
  with col_b1:
    if st.button("🚀 Seçilen Ürünleri Trendyol'a Gönder", use_container_width=True):
      with st.spinner("API ile Trendyol'a ürünler aktarılıyor..."):
        time.sleep(1.5)
      st.success("Ürünler Trendyol mağazasına başarıyla listelendi!")
  with col_b2:
    if st.button("🔄 Stok ve Fiyatları Güncelle", use_container_width=True):
      with st.spinner("Hesaplanan kâr ve komisyonlar uygulanıyor..."):
        time.sleep(1.2)
      st.success("Stoklar ve güncel fiyatlar eşitlendi!")
  with col_b3:
    if st.button("📥 Mağazadan Ürün Çek", use_container_width=True):
      with st.spinner("Pazaryerinden ürünler indiriliyor..."):
        time.sleep(1.2)
      st.success("Güncel ürün listesi çekildi!")

  arama_q = st.text_input(
      "🔍 Ürün Ara", placeholder="Ürün adı veya barkod yazın..."
  )
  gosterim_df = st.session_state.urunler_db.copy()
  if arama_q:
    gosterim_df = gosterim_df[
        gosterim_df["Ürün Adı"].str.lower().str.contains(arama_q.lower())
        | gosterim_df["Barkod"].str.lower().str.contains(arama_q.lower())
    ]

  st.data_editor(
      gosterim_df,
      column_config={
          "Görsel": st.column_config.ImageColumn(
              "Ürün Görseli", help="Orijinal Ürün Görseli", width=80
          ),
          "Alış Fiyatı": st.column_config.NumberColumn(
              "Alış (TL)", format="%.2f ₺"
          ),
          "Satış Fiyatı": st.column_config.NumberColumn(
              "Satış (TL)", format="%.2f ₺"
          ),
      },
      use_container_width=True,
      hide_index=True,
  )

# -------------------------------------------------------------
# FİYAT, KOMİSYON & MARJ AYARLARI SEKMESİ
# -------------------------------------------------------------
elif selected_menu == "⚙️ Fiyat, Komisyon & Marj Ayarları":
  st.subheader("⚙️ Otomatik Fiyatlandırma ve Komisyon Yönetimi")
  st.markdown(
      "Bu ekrandan yapacağınız değişiklikler tüm ürünlerin satış fiyatlarına"
      " anında yansıtılır."
  )

  f_kar = st.number_input(
      "Kâr Marjı Oranı (%)",
      value=st.session_state.ayar_kar_marji,
      key="f_kar_input",
  )
  f_kom = st.number_input(
      "Pazaryeri Komisyon Oranı (%)",
      value=st.session_state.ayar_komisyon,
      key="f_kom_input",
  )
  f_kargo = st.number_input(
      "Sabit Kargo Maliyeti (TL)",
      value=st.session_state.ayar_kargo_fiyati,
      key="f_kargo_input",
  )
  f_marka = st.text_input(
      "Ürün Markası", value=st.session_state.ayar_marka, key="f_marka_input"
  )

  if st.button(
      "Fiyatları ve Oranları Tüm Sistem İçin Güncelle", use_container_width=True
  ):
    st.session_state.ayar_kar_marji = f_kar
    st.session_state.ayar_komisyon = f_kom
    st.session_state.ayar_kargo_fiyati = f_kargo
    st.session_state.ayar_marka = f_marka

    # Otomatik Fiyat Hesaplama Simülasyonu
    for idx, row in st.session_state.urunler_db.iterrows():
      alis = row["Alış Fiyatı"]
      yeni_satis = (
          alis
          * (1 + f_kar / 100)
          * (1 + f_kom / 100)
          + f_kargo
      )
      st.session_state.urunler_db.at[idx, "Satış Fiyatı"] = round(yeni_satis, 2)

    st.success(
        "Tüm ürün satış fiyatları güncel kâr, komisyon ve kargo maliyetine"
        " göre yeniden hesaplandı!"
    )

# -------------------------------------------------------------
# PAZARYERİ API AYARLARI SEKMESİ
# -------------------------------------------------------------
elif selected_menu == "🔑 Pazaryeri API Entegrasyonları":
  st.subheader("🔑 Pazaryeri API Bağlantı Ayarları")
  st.markdown(
      "Ürün göndermek ve sipariş çekmek istediğiniz pazaryerlerinin API"
      " bilgilerini eksiksiz girin."
  )

  for k, v in st.session_state.api_bilgileri.items():
    st.session_state.api_bilgileri[k] = st.text_input(
        k, value=v, type="password", key=f"api_sec_{k}"
    )

  if st.button("API Bağlantılarını Kaydet", use_container_width=True):
    st.success(
        "API entegrasyon ayarları kaydedildi. Artık ürün gönderme işlemleri"
        " sorunsuz yapılabilir."
    )

# -------------------------------------------------------------
# DİĞER PAZARYERİ SEKMELERİ
# -------------------------------------------------------------
elif selected_menu in ["🧡 Trendyol", "🧡 Hepsiburada", "💜 N11", "🌸 ÇiçekSepeti", "💛 E-PTT AVM"]:
  pazar_adi = selected_menu.split(" ")[1]
  st.subheader(f"{selected_menu} Mağaza Yönetim Paneli")
  st.info(
      f"{pazar_adi} pazaryeri API entegrasyonu aktif. Ürün gönderebilir,"
      " siparişleri yönetebilir ve stok senkronize edebilirsiniz."
  )

  c_a, c_b = st.columns(2)
  with c_a:
    if st.button(
        f"{pazar_adi} Mağazasından Ürünleri Çek", use_container_width=True
    ):
      with st.spinner(f"{pazar_adi} API'sine bağlanılıyor..."):
        time.sleep(1)
      st.success(f"{pazar_adi} ürün listesi güncellendi!")
  with c_b:
    if st.button(
        f"Seçilen Ürünleri {pazar_adi}'ne Gönder", use_container_width=True
    ):
      with st.spinner(f"Ürünler {pazar_adi} sistemine aktarılıyor..."):
        time.sleep(1)
      st.success(f"Ürünler başarıyla {pazar_adi} mağazasına yüklendi!")

elif selected_menu == "⚡ Oto Kritik Stok":
  st.subheader("⚡ Otomatik Kritik Stok Takibi")
  st.markdown(
      "Stoku azalan ürünler listelenir ve tüm pazaryerlerinde otomatik"
      " güncellenir."
  )
  kritik_df = st.session_state.urunler_db[
      st.session_state.urunler_db["Trendyol Stok"] < 50
  ]
  st.dataframe(kritik_df, use_container_width=True, hide_index=True)

elif selected_menu == "🎧 Destek":
  st.subheader("🎧 Destek ve Operasyon Merkezi")
  st.success(
      "Şah Entegre operasyon merkezi taleplerinizi anında işleme almaktadır."
  )
  st.text_area("Destek Mesajınızı Yazın")
  if st.button("Talebi Gönder", use_container_width=True):
    st.success("Talebiniz başarıyla iletildi!")
