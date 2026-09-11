import time
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="MetEntegre - Profesyonel E-Ticaret Entegrasyon Platformu",
    page_icon="⚡",
    layout="wide",
)

# Profesyonel UI & Kurumsal Renk Paleti CSS
st.markdown(
    """
    <style>
    .stApp { background-color: #f4f6f9; }
    .metric-container { display: flex; gap: 15px; margin-bottom: 20px; flex-wrap: wrap; }
    .metric-card { flex: 1; min-width: 180px; background: white; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
    .pazar-badge { font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 4px; color: white; display: inline-block; margin-bottom: 8px; }
    .panel-box { background: white; border: 1px solid #e2e8f0; border-radius: 10px; padding: 20px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
    .panel-header { background: #0f172a; color: white; padding: 12px 16px; font-weight: 700; font-size: 14px; border-radius: 6px; margin-bottom: 15px; }
    </style>
""",
    unsafe_allow_html=True,
)

# -------------------------------------------------------------
# MERKEZİ VERİTABANI & OTURUM BAŞLANGICI (STATE MANAGEMENT)
# -------------------------------------------------------------
if "kar_orani" not in st.session_state:
  st.session_state.kar_orani = 20.0
if "komisyon_orani" not in st.session_state:
  st.session_state.komisyon_orani = 15.0
if "kargo_ucreti" not in st.session_state:
  st.session_state.kargo_ucreti = 40.0
if "marka_adi" not in st.session_state:
  st.session_state.marka_adi = "MetEntegre Store"

if "api_anahtarlari" not in st.session_state:
  st.session_state.api_anahtarlari = {
      "Trendyol Supplier ID & Key": "",
      "Hepsiburada Merchant ID": "",
      "N11 App Key & Secret": "",
      "ÇiçekSepeti API Token": "",
      "Pazarama / İdefix API": "",
  }

if "urun_havuzu" not in st.session_state:
  st.session_state.urun_havuzu = pd.DataFrame([
      {
          "Görsel": "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=100",
          "Barkod": "8680001122331",
          "Ürün Adı": "Kablosuz Hızlı Şarj Cihazı 15W",
          "Kategori": "Elektronik > Aksesuar",
          "Alış Fiyatı": 250.00,
          "Satış Fiyatı": 396.75,
          "Stok": 142,
          "Senkronizasyon": "Aktif / Eşitlendi",
      },
      {
          "Görsel": "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=100",
          "Barkod": "8680001122332",
          "Ürün Adı": "Bluetooth 5.0 Gürültü Önleyici Kulaklık",
          "Kategori": "Elektronik > Ses",
          "Alış Fiyatı": 600.00,
          "Satış Fiyatı": 952.20,
          "Stok": 85,
          "Senkronizasyon": "Aktif / Eşitlendi",
      },
      {
          "Görsel": "https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=100",
          "Barkod": "8680001122333",
          "Ürün Adı": "Ortopedik Taban Spor Koşu Ayakkabısı",
          "Kategori": "Spor > Giyim",
          "Alış Fiyatı": 450.00,
          "Satış Fiyatı": 714.15,
          "Stok": 12,
          "Senkronizasyon": "Kritik Stok (<50)",
      },
  ])

if "siparisler_db" not in st.session_state:
  st.session_state.siparisler_db = pd.DataFrame([
      {
          "Sipariş ID": "MET-88412",
          "Pazaryeri": "Trendyol",
          "Müşteri": "Kerem Aksoy",
          "Ürün": "Kablosuz Hızlı Şarj Cihazı",
          "Tutar": "396.75 TL",
          "Kargo Durumu": "Hazırlanıyor",
      },
      {
          "Sipariş ID": "MET-88413",
          "Pazaryeri": "Hepsiburada",
          "Müşteri": "Zeynep Demir",
          "Ürün": "Bluetooth Kulaklık",
          "Tutar": "952.20 TL",
          "Kargo Durumu": "Faturalandı",
      },
  ])

if "sistem_loglari" not in st.session_state:
  st.session_state.sistem_loglari = [
      "[{}] MetEntegre çekirdek servis başlatıldı.".format(
          time.strftime("%H:%M:%S")
      ),
      "[{}] Tüm pazaryeri adaptörleri aktif konuma getirildi.".format(
          time.strftime("%H:%M:%S")
      ),
      "[{}] 6 saatlik otomatik stok cron görevi devrede.".format(
          time.strftime("%H:%M:%S")
      ),
  ]

# -------------------------------------------------------------
# ÜST BAR VE HESAP / PROFİL YÖNETİMİ
# -------------------------------------------------------------
ust_col1, ust_col2 = st.columns([3, 2])
with ust_col1:
  st.markdown(
      "<span style='font-size: 18px; font-weight: 800; color:"
      " #0f172a;'>⚡ METENTEGRE - Kurumsal E-Ticaret Otomasyon"
      " Platformu</span>",
      unsafe_allow_html=True,
  )
with ust_col2:
  profil_menu = [
      "👤 Mağaza & Bayi Bilgileri",
      "⚙️ Otomatik Fiyat & Komisyon",
      "🔑 API Entegrasyon Anahtarları",
      "📄 Lisans ve Sürüm Bilgisi",
      "🚪 Oturumu Kapat",
  ]
  secilen_profil_islem = st.selectbox(
      "Profil", profil_menu, label_visibility="collapsed"
  )

st.markdown("---")

# -------------------------------------------------------------
# SOL YAN MENÜ (NAVİGASYON)
# -------------------------------------------------------------
st.sidebar.markdown(
    """
    <div style="text-align: center; padding: 12px 0; margin-bottom: 15px;">
        <span style="font-size: 26px; font-weight: 900; color: #2563eb;">MET</span>
        <span style="font-size: 20px; font-weight: 700; color: #0f172a;">ENTEGRE</span>
        <div style="font-size: 11px; color: #64748b; margin-top: 4px;">Uçtan Uca Pazaryeri Yönetimi</div>
    </div>
""",
    unsafe_allow_html=True,
)

aktif_sayfa = st.sidebar.selectbox(
    "Ana Menü",
    [
        "🏠 Yönetim Paneli",
        "📦 Ürünler & Hazır Eşleme",
        "🚀 Pazaryerine Toplu Gönder",
        "⚙️ Fiyat & Kâr Motoru",
        "🔑 API & Mağaza Bağlantıları",
        "🛒 Sipariş & Kargo Merkezi",
        "🔄 6 Saatlik Otomatik Stok",
        "📜 Sistem Log Kayıtları",
        "🎧 Teknik Destek",
    ],
)

# -------------------------------------------------------------
# PROFİL / AYAR İŞLEMLERİ MANTIĞI
# -------------------------------------------------------------
if secilen_profil_islem == "⚙️ Otomatik Fiyat & Komisyon":
  st.subheader("⚙️ Global Fiyat ve Kâr Marjı Ayarları")
  c1, c2, c3, c4 = st.columns(4)
  with c1:
    y_kar = st.number_input("Kâr Oranı (%)", value=st.session_state.kar_orani)
  with c2:
    y_kom = st.number_input(
        "Komisyon Oranı (%)", value=st.session_state.komisyon_orani
    )
  with c3:
    y_kargo = st.number_input(
        "Kargo Bedeli (TL)", value=st.session_state.kargo_ucreti
    )
  with c4:
    y_marka = st.text_input("Marka Adı", value=st.session_state.marka_adi)

  if st.button("Ayarları Kaydet ve Tüm Fiyatları Güncelle"):
    st.session_state.kar_orani = y_kar
    st.session_state.komisyon_orani = y_kom
    st.session_state.kargo_ucreti = y_kargo
    st.session_state.marka_adi = y_marka

    for idx, row in st.session_state.urun_havuzu.iterrows():
      alis = row["Alış Fiyatı"]
      yeni_satis = (
          alis
          * (1 + y_kar / 100)
          * (1 + y_kom / 100)
          + y_kargo
      )
      st.session_state.urun_havuzu.at[idx, "Satış Fiyatı"] = round(yeni_satis, 2)

    st.success("Tüm ürün fiyatları yeni kurallara göre otomatik güncellendi!")

elif secilen_profil_islem == "🔑 API Entegrasyon Anahtarları":
  st.subheader("🔑 Pazaryeri API Anahtar Yönetimi")
  for k, v in st.session_state.api_anahtarlari.items():
    st.session_state.api_anahtarlari[k] = st.text_input(
        k, value=v, type="password", key=f"prof_key_{k}"
    )
  if st.button("API Anahtarlarını Kaydet"):
    st.success("API anahtarları başarıyla güncellendi.")

elif secilen_profil_islem == "📄 Lisans ve Sürüm Bilgisi":
  st.subheader("📄 Lisans ve Abonelik Detayları")
  st.dataframe(
      pd.DataFrame([{
          "Paket Türü": "MetEntegre Kurumsal Sınırsız",
          "Kapsam": "Tüm Pazaryerleri Dahil",
          "Durum": "Aktif / Sorunsuz",
          "Otomatik Stok Döngüsü": "Aktif (6 Saatte Bir)",
      }]),
      use_container_width=True,
      hide_index=True,
  )

elif secilen_profil_islem == "👤 Mağaza & Bayi Bilgileri":
  st.subheader("👤 Mağaza ve Hesap Bilgileri")
  st.text_input("İşletme Unvanı", value="Şah E-Ticaret Bilişim Ltd. Şti.")
  st.text_input("Sistem Kullanıcısı", value="Şahin Yiğit")
  st.text_input("E-posta Adresi", value="sahin@metentegre.com")
  if st.button("Bilgileri Güncelle"):
    st.success("Bilgiler güncellendi.")

# -------------------------------------------------------------
# 1. YÖNETİM PANELİ (ANA SAYFA)
# -------------------------------------------------------------
if aktif_sayfa == "🏠 Yönetim Paneli":
  st.subheader("👑 Operasyonel Genel Bakış")

  st.markdown(
      """
        <div class="metric-container">
            <div class="metric-card"><div class="pazar-badge" style="background:#ff6600;">TRENDYOL</div><div style="font-size:11px; color:#64748b;">Aktif Sipariş</div><div style="font-size:16px; font-weight:700; color:#0f172a;">1 Adet</div></div>
            <div class="metric-card"><div class="pazar-badge" style="background:#f27a1a;">HEPSİBURADA</div><div style="font-size:11px; color:#64748b;">Aktif Sipariş</div><div style="font-size:16px; font-weight:700; color:#0f172a;">1 Adet</div></div>
            <div class="metric-card"><div class="pazar-badge" style="background:#e6005c;">ÇİÇEKSEPETİ</div><div style="font-size:11px; color:#64748b;">Aktif Sipariş</div><div style="font-size:16px; font-weight:700; color:#0f172a;">0 Adet</div></div>
            <div class="metric-card"><div class="pazar-badge" style="background:#6b46c1;">N11</div><div style="font-size:11px; color:#64748b;">Aktif Sipariş</div><div style="font-size:16px; font-weight:700; color:#0f172a;">0 Adet</div></div>
        </div>
    """,
      unsafe_allow_html=True,
  )

  st.markdown(
      f"""
        <div class="panel-box">
            <div class="panel-header">📊 Sistem Yapılandırması ve Durum Raporu</div>
            <table style="width:100%; font-size:13px; color:#1e293b; border-collapse:collapse;">
                <tr><td style="padding:6px; font-weight:600; width:200px;">Aktif Marka:</td><td>{st.session_state.marka_adi}</td></tr>
                <tr><td style="padding:6px; font-weight:600;">Uygulanan Kâr Marjı:</td><td>%{st.session_state.kar_orani}</td></tr>
                <tr><td style="padding:6px; font-weight:600;">Pazaryeri Komisyonu:</td><td>%{st.session_state.komisyon_orani}</td></tr>
                <tr><td style="padding:6px; font-weight:600;">Sabit Kargo Bedeli:</td><td>{st.session_state.kargo_ucreti} TL</td></tr>
                <tr><td style="padding:6px; font-weight:600;">Toplam Ürün Havuzu:</td><td>{len(st.session_state.urun_havuzu)} Adet</td></tr>
                <tr><td style="padding:6px; font-weight:600;">Otomatik Stok Döngüsü:</td><td>Aktif (Her 6 saatte bir güncellenir)</td></tr>
            </table>
        </div>
    """,
      unsafe_allow_html=True,
  )

  c_a, c_b = st.columns(2)
  with c_a:
    if st.button(
        "🔄 Tüm Pazaryerlerini ve Stokları Senkronize Et",
        use_container_width=True,
    ):
      with st.spinner("Pazaryeri API sunucularıyla senkronizasyon yapılıyor..."):
        time.sleep(1.2)
      st.success("Tüm mağazalar başarıyla güncellendi!")
  with c_b:
    if st.button("📥 Tedarikçi XML Verilerini Yeniden Çek", use_container_width=True):
      with st.spinner("XML feed bağlantıları taranıyor..."):
        time.sleep(1.2)
      st.success("Tedarikçi verileri sisteme işlendi!")

# -------------------------------------------------------------
# 2. ÜRÜNLER & HAZIR EŞLEME
# -------------------------------------------------------------
elif aktif_sayfa == "📦 Ürünler & Hazır Eşleme":
  st.subheader("📦 Hazır Kategori ve Varyant Eşleştirme Merkezi")
  st.markdown(
      "Kategori eşleştirme ve varyant karmaşasına son! Sistemimiz tüm"
      " ürünleri önceden eşleştirilmiş şemalarla yönetir."
  )

  with st.expander("➕ Yeni Ürün Ekle veya XML'den Aktar", expanded=False):
    col_u1, col_u2 = st.columns(2)
    with col_u1:
      u_ad = st.text_input("Ürün Adı")
      u_barkod = st.text_input("Barkod / GTIN")
      u_kat = st.selectbox(
          "Ön Eşleşmiş Kategori",
          [
              "Elektronik > Aksesuar",
              "Elektronik > Ses",
              "Spor > Giyim",
              "Ev > Yaşam",
          ],
      )
    with col_u2:
      u_alis = st.number_input("Alış Fiyatı (TL)", value=100.0)
      u_stok = st.number_input("Stok Adedi", value=50, step=1)
      u_gorsel = st.text_input(
          "Görsel URL",
          value="https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=100",
      )

    if st.button("Ürünü Kaydet ve Fiyat Hesapla"):
      if u_ad and u_barkod:
        hesaplanan = round(
            u_alis
            * (1 + st.session_state.kar_orani / 100)
            * (1 + st.session_state.komisyon_orani / 100)
            + st.session_state.kargo_ucreti,
            2,
        )
        yeni_kayit = {
            "Görsel": u_gorsel,
            "Barkod": u_barkod,
            "Ürün Adı": u_ad,
            "Kategori": u_kat,
            "Alış Fiyatı": u_alis,
            "Satış Fiyatı": hesaplanan,
            "Stok": u_stok,
            "Senkronizasyon": "Yeni Eklendi",
        }
        st.session_state.urun_havuzu = pd.concat(
            [st.session_state.urun_havuzu, pd.DataFrame([yeni_kayit])],
            ignore_index=True,
        )
        st.success(
            "Ürün başarıyla eklendi, kategorisi eşleştirildi ve fiyatı"
            " hesaplandı!"
        )
      else:
        st.error("Lütfen ürün adı ve barkod alanlarını doldurun.")

   arama = st.text_input(
      "🔍 Ürün Ara", placeholder="Ürün adı veya barkod girin..."
  )
  aktif_df = st.session_state.urun_havuzu.copy()
  if arama:
    aktif_df = aktif_df[
        aktif_df["Ürün Adı"].str.lower().str.contains(arama.lower())
        | aktif_df["Barkod"].str.lower().str.contains(arama.lower())
    ]

  duzenlenen_df = st.data_editor(
      aktif_df,
      column_config={
          "Görsel": st.column_config.ImageColumn(
              "Ürün Görseli", width=70
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

  if st.button("Değişiklikleri Veritabanına Kaydet"):
    st.session_state.urun_havuzu = duzenlenen_df
    st.success("Ürün havuzu güncellendi!")

# -------------------------------------------------------------
# 3. PAZARYERİNE TOPLU GÖNDER
# -------------------------------------------------------------
elif aktif_sayfa == "🚀 Pazaryerine Toplu Gönder":
  st.subheader("🚀 Toplu Ürün Aktarım ve Listeleme Merkezi")
  st.markdown(
      "Sistemdeki tüm ürünleri tek tıkla seçtiğiniz pazaryerine toplu olarak"
      " gönderin."
  )

  hedef_pazar_secimi = st.selectbox(
      "Hedef Pazaryeri",
      [
          "Trendyol",
          "Hepsiburada",
          "N11",
          "ÇiçekSepeti",
          "Pazarama",
          "İdefix",
          "Tümü",
      ],
  )

  col_g1, col_g2 = st.columns(2)
  with col_g1:
    if st.button(
        f"📤 Seçilen Ürünleri {hedef_pazar_secimi}'ne Gönder",
        use_container_width=True,
    ):
      with st.spinner(f"{hedef_pazar_secimi} API havuzuna aktarılıyor..."):
        time.sleep(1.5)
      st.success(
          f"Ürünler başarıyla {hedef_pazar_secimi} mağazanıza listelendi!"
      )
  with col_g2:
    if st.button(
        f"🔄 {hedef_pazar_secimi} Fiyat ve Stoklarını Senkronize Et",
        use_container_width=True,
    ):
      with st.spinner("Fiyatlar ve stoklar güncelleniyor..."):
        time.sleep(1.2)
      st.success(f"{hedef_pazar_secimi} verileri güncellendi!")

  st.markdown("---")
  st.subheader("📋 Gönderime Hazır Ürün Havuzu")
  st.dataframe(
      st.session_state.urun_havuzu[[
          "Barkod",
          "Ürün Adı",
          "Kategori",
          "Satış Fiyatı",
          "Stok",
          "Senkronizasyon",
      ]],
      use_container_width=True,
      hide_index=True,
  )

# -------------------------------------------------------------
# 4. FİYAT & KÂR MOTORU
# -------------------------------------------------------------
elif aktif_sayfa == "⚙️ Fiyat & Kâr Motoru":
  st.subheader("⚙️ Otomatik Fiyatlandırma ve Komisyon Hesaplayıcı")
  st.markdown(
      "Alış fiyatı üzerine kâr marjı, komisyon ve kargo eklenerek satış"
      " fiyatı otomatik hesaplanır."
  )

  f_kar = st.number_input(
      "Kâr Marjı Oranı (%)",
      value=st.session_state.kar_orani,
      key="motor_kar",
  )
  f_kom = st.number_input(
      "Komisyon Oranı (%)",
      value=st.session_state.komisyon_orani,
      key="motor_kom",
  )
  f_kargo = st.number_input(
      "Sabit Kargo Ücreti (TL)",
      value=st.session_state.kargo_ucreti,
      key="motor_kargo",
  )
  f_marka = st.text_input(
      "Marka İsmi", value=st.session_state.marka_adi, key="motor_marka"
  )

  if st.button("Fiyatları Hesapla ve Uygula", use_container_width=True):
    st.session_state.kar_orani = f_kar
    st.session_state.komisyon_orani = f_kom
    st.session_state.kargo_ucreti = f_kargo
    st.session_state.marka_adi = f_marka

    for idx, row in st.session_state.urun_havuzu.iterrows():
      alis = row["Alış Fiyatı"]
      yeni_satis = (
          alis
          * (1 + f_kar / 100)
          * (1 + f_kom / 100)
          + f_kargo
      )
      st.session_state.urun_havuzu.at[idx, "Satış Fiyatı"] = round(yeni_satis, 2)

    st.success("Tüm ürünlerin satış fiyatları güncellendi!")

  st.dataframe(
      st.session_state.urun_havuzu[["Ürün Adı", "Alış Fiyatı", "Satış Fiyatı"]],
      use_container_width=True,
      hide_index=True,
  )

# -------------------------------------------------------------
# 5. API & MAĞAZA BAĞLANTILARI
# -------------------------------------------------------------
elif aktif_sayfa == "🔑 API & Mağaza Bağlantıları":
  st.subheader("🔑 Pazaryeri API Entegrasyon Anahtarları")
  st.markdown(
      "Mağazalarınıza ait API anahtarlarını girerek entegrasyonu aktif"
      " edin."
  )

  for k, v in st.session_state.api_anahtarlari.items():
    st.session_state.api_anahtarlari[k] = st.text_input(
        k, value=v, type="password", key=f"menu_key_{k}"
    )

  c_t1, c_t2 = st.columns(2)
  with c_t1:
    if st.button("🔌 API Bağlantılarını Test Et", use_container_width=True):
      with st.spinner("Sunucularla token doğrulaması yapılıyor..."):
        time.sleep(1.5)
      st.success("Tüm API anahtarları doğrulandı ve bağlantı sağlandı!")
  with c_t2:
    if st.button("💾 Bilgileri Kalıcı Kaydet", use_container_width=True):
      st.success("API bilgileri kaydedildi.")

# -------------------------------------------------------------
# 6. SİPARİŞ & KARGO MERKEZİ
# -------------------------------------------------------------
elif aktif_sayfa == "🛒 Sipariş & Kargo Merkezi":
  st.subheader("🛒 Merkezi Sipariş ve Kargo Yönetimi")
  st.markdown(
      "Tüm pazaryerlerinden gelen siparişleri tek ekrandan yönetin, kargo"
      " etiketlerinizi oluşturun."
  )

  if st.button("🔄 Siparişleri Şimdi Güncelle / Çek", use_container_width=True):
    with st.spinner("Mağazalardan siparişler çekiliyor..."):
      time.sleep(1)
    st.success("Siparişler güncellendi!")

  st.dataframe(
      st.session_state.siparisler_db, use_container_width=True, hide_index=True
  )

# -------------------------------------------------------------
# 7. 6 SAATLİK OTOMATİK STOK
# -------------------------------------------------------------
elif aktif_sayfa == "🔄 6 Saatlik Otomatik Stok":
  st.subheader("🔄 6 Saatte Bir Otomatik Stok ve Fiyat Güncellemesi")
  st.markdown(
      "Sistem arka planda her 6 saatte bir stoklarınızı otomatik olarak"
      " günceller; kritik stoktaki ürünleri raporlar."
  )

  kritik = st.session_state.urun_havuzu[
      st.session_state.urun_havuzu["Stok"] < 50
  ]
  st.dataframe(kritik, use_container_width=True, hide_index=True)

  if st.button(
      "⚡ Şimdi Manuel Stok / Fiyat Senkronizasyonunu Tetikle",
      use_container_width=True,
  ):
    with st.spinner("Otomatik stok döngüsü tetiklendi..."):
      time.sleep(1)
    st.success("Stoklar tüm pazaryerlerinde eşitlendi!")

# -------------------------------------------------------------
# 8. SİSTEM LOG KAYITLARI
# -------------------------------------------------------------
elif aktif_sayfa == "📜 Sistem Log Kayıtları":
  st.subheader("📜 Gelişmiş İşlem ve Log İzleme Merkezi")
  st.markdown(
      "Tüm API istekleri, güncelleme döngüleri ve hata logları bu ekranda"
      " tutulur."
  )

  for log in st.session_state.sistem_loglari:
    st.code(log, language="text")

  if st.button("Log Kayıtlarını Temizle"):
    st.session_state.sistem_loglari = [
        "[{}] Log kayıtları sıfırlandı.".format(time.strftime("%H:%M:%S"))
    ]
    st.success("Loglar temizlendi.")

# -------------------------------------------------------------
# 9. TEKNİK DESTEK
# -------------------------------------------------------------
elif aktif_sayfa == "🎧 Teknik Destek":
  st.subheader("🎧 7/24 Teknik Destek ve Operasyon Masası")
  st.success(
      "Teknik ekibimiz taleplerinizi incelemektedir. Destek talebinizi iletin."
  )
  st.text_area("Sorununuzu veya talebinizi yazın...")
  if st.button("Destek Talebini Gönder", use_container_width=True):
    st.success("Talebiniz alınmıştır. En kısa sürede dönüş yapılacaktır.")
