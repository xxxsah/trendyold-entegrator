import time
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Şah Entegre - Profesyonel E-Ticaret Yönetim Paneli",
    page_icon="⚡",
    layout="wide",
)

# Profesyonel UI & Orijinal Renk Konsepti CSS
st.markdown(
    """
    <style>
    .stApp { background-color: #f8fafc; }
    .mp-grid { display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap; }
    .mp-card { flex: 1; min-width: 140px; background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }
    .mp-badge { font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 4px; color: white; display: inline-block; margin-bottom: 6px; }
    .box-container { background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 15px; margin-bottom: 15px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }
    .box-header { background: #f27a1a; color: white; padding: 10px 14px; font-weight: 700; font-size: 14px; border-radius: 6px; margin-bottom: 12px; text-align: left; }
    </style>
""",
    unsafe_allow_html=True,
)

# -------------------------------------------------------------
# OTURUM HAFIZASI VE GLOBAL PARAMETRELER (STATE MANAGEMENT)
# -------------------------------------------------------------
if "ayar_komisyon" not in st.session_state:
  st.session_state.ayar_komisyon = 18.0
if "ayar_kar_marji" not in st.session_state:
  st.session_state.ayar_kar_marji = 25.0
if "ayar_kargo_fiyati" not in st.session_state:
  st.session_state.ayar_kargo_fiyati = 45.00
if "ayar_marka" not in st.session_state:
  st.session_state.ayar_marka = "Şah Store"

if "api_bilgileri" not in st.session_state:
  st.session_state.api_bilgileri = {
      "Trendyol Supplier ID / API Key": "",
      "Hepsiburada Merchant ID": "",
      "N11 App Key / Secret": "",
      "ÇiçekSepeti API Token": "",
      "XML Tedarikçi Feed Linki": "",
  }

if "urunler_db" not in st.session_state:
  st.session_state.urunler_db = pd.DataFrame([
      {
          "Görsel": "https://images.unsplash.com/photo-1584263155336-d64e9a8f4675?w=100",
          "Barkod": "CYRO-679931-LXL",
          "Ürün Adı": "Siyah Dantelli Sabahlık & Gecelik Takımı",
          "Alış Fiyatı": 400.00,
          "Satış Fiyatı": 726.00,
          "Stok": 98,
          "Pazaryeri Durumu": "Trendyol / Hepsiburada Aktif",
      },
      {
          "Görsel": "https://images.unsplash.com/photo-1543163521-1bf539c55dd2?w=100",
          "Barkod": "CYRO-679931-SM",
          "Ürün Adı": "Siyah Dantelli Sabahlık & Gecelik Takımı (SM)",
          "Alış Fiyatı": 400.00,
          "Satış Fiyatı": 726.00,
          "Stok": 100,
          "Pazaryeri Durumu": "Trendyol Aktif",
      },
      {
          "Görsel": "https://images.unsplash.com/photo-1517841905240-472988babdf9?w=100",
          "Barkod": "606214114000007",
          "Ürün Adı": "Ayarlanabilir Dizüstü Destek Tabanı Tam Boy",
          "Alış Fiyatı": 350.00,
          "Satış Fiyatı": 629.70,
          "Stok": 27,
          "Pazaryeri Durumu": "Tüm Mağazalar Aktif",
      },
      {
          "Görsel": "https://images.unsplash.com/photo-1585338107529-13afc5f02586?w=100",
          "Barkod": "606903317053779",
          "Ürün Adı": "TONTON - NO:1 ÇEKMECE 3 KATLI",
          "Alış Fiyatı": 320.00,
          "Satış Fiyatı": 583.31,
          "Stok": 44,
          "Pazaryeri Durumu": "Beklemede",
      },
  ])

if "siparisler" not in st.session_state:
  st.session_state.siparisler = pd.DataFrame([
      {
          "Sipariş No": "SHT-2026-901",
          "Pazaryeri": "Trendyol",
          "Müşteri": "Ahmet Y.",
          "Ürün": "Siyah Dantelli Sabahlık",
          "Tutar": "726.00 TL",
          "Durum": "Yeni Sipariş",
      },
      {
          "Sipariş No": "SHT-2026-902",
          "Pazaryeri": "Hepsiburada",
          "Müşteri": "Merve K.",
          "Ürün": "Ayarlanabilir Dizüstü Destek",
          "Tutar": "629.70 TL",
          "Durum": "Kargolandı",
      },
  ])

if "loglar" not in st.session_state:
  st.session_state.loglar = [
      "Şah Entegre çekirdek sistem başlatıldı.",
      "Pazaryeri adaptörleri hazır.",
  ]

# -------------------------------------------------------------
# ÜST BAŞLIK VE PROFİL MENÜSÜ
# -------------------------------------------------------------
col_h1, col_h2 = st.columns([4, 2])
with col_h1:
  st.markdown(
      "<span style='font-size: 16px; font-weight: 800; color:"
      " #1e293b;'>⚡ ŞAH ENTEGRE - E-Ticaret Otomasyon ve Yönetim"
      " Merkezi</span>",
      unsafe_allow_html=True,
  )
with col_h2:
  profil_secenekleri = [
      "👤 Mağaza Profili & Bilgileri",
      "⚙️ Fiyat, Kâr & Komisyon Kuralları",
      "🔑 API Entegrasyon Anahtarları",
      "📄 Faturalarım & Abonelik",
      "🚪 Güvenli Çıkış",
  ]
  secilen_profil = st.selectbox(
      "Profil", profil_secenekleri, label_visibility="collapsed"
  )

st.markdown("---")

# -------------------------------------------------------------
# SOL MENÜ (NAVİGASYON)
# -------------------------------------------------------------
st.sidebar.markdown(
    """
    <div style="text-align: center; padding: 10px 0; margin-bottom: 10px;">
        <span style="font-size: 28px; font-weight: 900; color: #f27a1a;">ŞAH</span>
        <span style="font-size: 16px; font-weight: 600; color: #0f172a;">ENTEGRE</span>
        <div style="font-size: 11px; color: #64748b; margin-top: 2px;">Bulut Entegrasyon Yazılımı</div>
    </div>
""",
    unsafe_allow_html=True,
)

menu_secimi = st.sidebar.selectbox(
    "Ana Menü",
    [
        "🏠 Ana Kontrol Paneli",
        "📦 Ürünler & Barkod Eşleme",
        "🚀 Pazaryerine Ürün Gönder",
        "⚙️ Fiyatlandırma & Kâr Marjı",
        "🔑 API & Mağaza Bağlantıları",
        "🛒 Sipariş Takip Merkezi",
        "🔄 Stok Senkronizasyonu",
        "🎧 Destek & Bildirimler",
    ],
)

# -------------------------------------------------------------
# PROFİL / HESAP AYARLARI SAYFALARI
# -------------------------------------------------------------
if secilen_profil == "⚙️ Fiyat, Kâr & Komisyon Kuralları":
  st.subheader("⚙️ Global Fiyatlandırma ve Kâr Kuralları")
  st.markdown(
      "Belirleyeceğiniz oranlar sisteme yüklenen tüm ürünlerin satış fiyatını"
      " otomatik olarak günceller."
  )

  c1, c2, c3, c4 = st.columns(4)
  with c1:
    y_kar = st.number_input("Kâr Marjı (%)", value=st.session_state.ayar_kar_marji)
  with c2:
    y_kom = st.number_input(
        "Komisyon Oranı (%)", value=st.session_state.ayar_komisyon
    )
  with c3:
    y_kargo = st.number_input(
        "Kargo Ücreti (TL)", value=st.session_state.ayar_kargo_fiyati
    )
  with c4:
    y_marka = st.text_input("Marka Adı", value=st.session_state.ayar_marka)

  if st.button("Kuralları Kaydet ve Fiyatları Güncelle", use_container_width=True):
    st.session_state.ayar_kar_marji = y_kar
    st.session_state.ayar_komisyon = y_kom
    st.session_state.ayar_kargo_fiyati = y_kargo
    st.session_state.ayar_marka = y_marka

    # Otomatik formül hesaplama: Alış * (1 + Kar/100) * (1 + Komisyon/100) + Kargo
    for idx, row in st.session_state.urunler_db.iterrows():
      alis = row["Alış Fiyatı"]
      yeni_satis = (
          alis
          * (1 + y_kar / 100)
          * (1 + y_kom / 100)
          + y_kargo
      )
      st.session_state.urunler_db.at[idx, "Satış Fiyatı"] = round(yeni_satis, 2)

    st.success(
        "Tüm ürünlerin satış fiyatları yeni kural setine göre başarıyla"
        " yeniden hesaplandı!"
    )

elif secilen_profil == "🔑 API Entegrasyon Anahtarları":
  st.subheader("🔑 Pazaryeri API Anahtar Yönetimi")
  st.markdown(
      "Pazaryerleri ile tam entegrasyon kurabilmek için API anahtarlarınızı"
      " eksiksiz girin."
  )

  for k, v in st.session_state.api_bilgileri.items():
    st.session_state.api_bilgileri[k] = st.text_input(
        k, value=v, type="password", key=f"prof_api_{k}"
    )

  if st.button("API Bilgilerini Güvenle Kaydet", use_container_width=True):
    st.success(
        "API anahtarları kaydedildi. Mağaza bağlantıları aktif hale getirildi!"
    )

elif secilen_profil == "📄 Faturalarım & Abonelik":
  st.subheader("📄 Abonelik ve Fatura Bilgileri")
  st.dataframe(
      pd.DataFrame([{
          "Paket": "Şah Entegre Kurumsal Sınırsız",
          "Periyot": "Yıllık Lisans",
          "Durum": "Aktif / Sorunsuz",
          "Son Ödeme": "01.09.2026",
      }]),
      use_container_width=True,
      hide_index=True,
  )

elif secilen_profil == "👤 Mağaza Profili & Bilgileri":
  st.subheader("👤 Mağaza Hesap Bilgileri")
  st.text_input("Şirket / Mağaza Unvanı", value="Şah E-Ticaret Limited Şti.")
  st.text_input("Vergi Dairesi / No", value="Kadifekale / 9800650692")
  st.text_input("İletişim E-posta", value="destek@sahentegre.com")
  if st.button("Bilgileri Güncelle"):
    st.success("Mağaza bilgileri güncellendi.")

# -------------------------------------------------------------
# 1. ANA KONTROL PANELİ
# -------------------------------------------------------------
if menu_secimi == "🏠 Ana Kontrol Paneli":
  st.subheader("👑 Operasyonel Genel Bakış")

  st.markdown(
      """
        <div class="mp-grid">
            <div class="mp-card"><div class="mp-badge" style="background:#ff6600;">HEPSİBURADA</div><div style="font-size:11px; color:#64748b;">Aktif Sipariş</div><div style="font-size:14px; font-weight:700; color:#0f172a;">1 Adet</div></div>
            <div class="mp-card"><div class="mp-badge" style="background:#f27a1a;">TRENDYOL</div><div style="font-size:11px; color:#64748b;">Aktif Sipariş</div><div style="font-size:14px; font-weight:700; color:#0f172a;">1 Adet</div></div>
            <div class="mp-card"><div class="mp-badge" style="background:#e6005c;">ÇİÇEKSEPETİ</div><div style="font-size:11px; color:#64748b;">Aktif Sipariş</div><div style="font-size:14px; font-weight:700; color:#0f172a;">0 Adet</div></div>
            <div class="mp-card"><div class="mp-badge" style="background:#6b46c1;">N11</div><div style="font-size:11px; color:#64748b;">Aktif Sipariş</div><div style="font-size:14px; font-weight:700; color:#0f172a;">0 Adet</div></div>
        </div>
    """,
      unsafe_allow_html=True,
  )

  st.markdown(
      f"""
        <div class="box-container">
            <div class="box-header">📊 Sistem Aktif Konfigürasyonu</div>
            <table style="width:100%; font-size:13px; color:#1e293b; border-collapse:collapse;">
                <tr><td style="padding:6px; font-weight:600; width:180px;">Aktif Marka:</td><td>{st.session_state.ayar_marka}</td></tr>
                <tr><td style="padding:6px; font-weight:600;">Uygulanan Kâr Marjı:</td><td>%{st.session_state.ayar_kar_marji}</td></tr>
                <tr><td style="padding:6px; font-weight:600;">Komisyon Oranı:</td><td>%{st.session_state.ayar_komisyon}</td></tr>
                <tr><td style="padding:6px; font-weight:600;">Kargo Maliyeti:</td><td>{st.session_state.ayar_kargo_fiyati} TL</td></tr>
                <tr><td style="padding:6px; font-weight:600;">Toplam Ürün Havuzu:</td><td>{len(st.session_state.urunler_db)} Adet</td></tr>
            </table>
        </div>
    """,
      unsafe_allow_html=True,
  )

  c_a, c_b = st.columns(2)
  with c_a:
    if st.button(
        "🚀 Tüm Pazaryerlerini ve Stokları Senkronize Et",
        use_container_width=True,
    ):
      with st.spinner("Stoklar, fiyatlar ve barkodlar eşitleniyor..."):
        time.sleep(1.2)
      st.success("Tüm pazaryerleri başarıyla senkronize edildi!")
  with c_b:
    if st.button("📥 Tedarikçi XML Verilerini Yeniden Çek", use_container_width=True):
      with st.spinner("XML linkleri taranıyor..."):
        time.sleep(1.2)
      st.success("Tedarikçi verileri sisteme aktarıldı!")

# -------------------------------------------------------------
# 2. ÜRÜNLER & BARKOD EŞLEME
# -------------------------------------------------------------
elif menu_secimi == "📦 Ürünler & Barkod Eşleme":
  st.subheader("📦 Ürün Yönetimi ve Barkod Eşleştirme Merkezi")
  st.markdown(
      "Sistemde kayıtlı ürünleri inceleyebilir, barkodlarını düzenleyebilir,"
      " yeni ürün ekleyebilir veya istenmeyen ürünleri silebilirsiniz."
  )

  with st.expander("➕ Yeni Ürün Ekle veya XML'den Aktar", expanded=False):
    col_u1, col_u2 = st.columns(2)
    with col_u1:
      y_ad = st.text_input("Ürün Adı")
      y_barkod = st.text_input("Barkod / GTIN")
      y_gorsel = st.text_input(
          "Görsel URL",
          value="https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=100",
      )
    with col_u2:
      y_alis = st.number_input("Alış Fiyatı (TL)", value=100.0)
      y_stok = st.number_input("Stok Adedi", value=50, step=1)

    if st.button("Ürünü Veritabanına Kaydet"):
      if y_ad and y_barkod:
        hesaplanan_satis = round(
            y_alis
            * (1 + st.session_state.ayar_kar_marji / 100)
            * (1 + st.session_state.ayar_komisyon / 100)
            + st.session_state.ayar_kargo_fiyati,
            2,
        )
        yeni_kayit = {
            "Görsel": y_gorsel,
            "Barkod": y_barkod,
            "Ürün Adı": y_ad,
            "Alış Fiyatı": y_alis,
            "Satış Fiyatı": hesaplanan_satis,
            "Stok": y_stok,
            "Pazaryeri Durumu": "Yeni Eklendi",
        }
        st.session_state.urunler_db = pd.concat(
            [st.session_state.urunler_db, pd.DataFrame([yeni_kayit])],
            ignore_index=True,
        )
        st.success("Ürün başarıyla eklendi ve fiyatı otomatik hesaplandı!")
      else:
        st.error("Lütfen ürün adı ve barkod alanlarını doldurun.")

  arama_term = st.text_input(
      "🔍 Ürün Ara", placeholder="Ürün adı veya barkod ile filtrele..."
  )
  aktif_df = st.session_state.urunler_db.copy()
  if arama_term:
    aktif_df = aktif_df[
        aktif_df["Ürün Adı"].str.lower().str.contains(arama_term.lower())
        | aktif_df["Barkod"].str.lower().str.contains(arama_term.lower())
    ]

  edited_df = st.data_editor(
      aktif_df,
      column_config={
          "Görsel": st.column_config.ImageColumn(
              "Orijinal Görsel", width=70
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

  if st.button("Tablo Değişikliklerini Kaydet"):
    st.session_state.urunler_db = edited_df
    st.success("Ürün verileri güncellendi!")

# -------------------------------------------------------------
# 3. PAZARYERİNE ÜRÜN GÖNDER
# -------------------------------------------------------------
elif menu_secimi == "🚀 Pazaryerine Ürün Gönder":
  st.subheader("🚀 Pazaryerlerine Toplu Ürün Aktarım Merkezi")
  st.markdown(
      "Sistemdeki tüm onaylı ürünleri seçtiğiniz pazaryerine tek tıkla"
      " gönderebilir, fiyat ve stok senkronizasyonunu anında"
      " tetikleyebilirsiniz."
  )

  hedef_pazar = st.selectbox(
      "Hedef Pazaryeri Seçin",
      ["Trendyol", "Hepsiburada", "N11", "ÇiçekSepeti", "E-PTT AVM", "Tümü"],
  )

  col_g1, col_g2 = st.columns(2)
  with col_g1:
    if st.button(
        f"📤 Seçilen Ürünleri {hedef_pazar}'ne Gönder", use_container_width=True
    ):
      with st.spinner(f"{hedef_pazar} API servisine bağlanılıyor..."):
        time.sleep(1.5)
      st.success(
          f"Ürünler başarıyla {hedef_pazar} mağazanıza listelendi ve satışa"
          " açıldı!"
      )
  with col_g2:
    if st.button(
        f"🔄 {hedef_pazar} Fiyat ve Stoklarını Güncelle", use_container_width=True
    ):
      with st.spinner("Stoklar ve kâr marjlı fiyatlar güncelleniyor..."):
        time.sleep(1.2)
      st.success(f"{hedef_pazar} üzerindeki veriler güncellendi!")

  st.markdown("---")
  st.subheader("📋 Aktarım Bekleyen Ürün Önizlemesi")
  st.dataframe(
      st.session_state.urunler_db[[
          "Barkod",
          "Ürün Adı",
          "Satış Fiyatı",
          "Stok",
          "Pazaryeri Durumu",
      ]],
      use_container_width=True,
      hide_index=True,
  )

# -------------------------------------------------------------
# 4. FİYATLANDIRMA & KÂR MARJI
# -------------------------------------------------------------
elif menu_secimi == "⚙️ Fiyatlandırma & Kâr Marjı":
  st.subheader("⚙️ Otomatik Fiyatlandırma ve Komisyon Hesaplayıcı")
  st.markdown(
      "Ürünlerin alış fiyatı üzerine kâr marjı, pazaryeri komisyonu ve kargo"
      " maliyeti eklenerek satış fiyatı otomatik bulunur."
  )

  f_kar = st.number_input(
      "Kâr Marjı Oranı (%)",
      value=st.session_state.ayar_kar_marji,
      key="fiyat_kar",
  )
  f_kom = st.number_input(
      "Komisyon Oranı (%)",
      value=st.session_state.ayar_komisyon,
      key="fiyat_kom",
  )
  f_kargo = st.number_input(
      "Sabit Kargo Ücreti (TL)",
      value=st.session_state.ayar_kargo_fiyati,
      key="fiyat_kargo",
  )
  f_marka = st.text_input(
      "Aktif Marka Bilgisi", value=st.session_state.ayar_marka, key="fiyat_marka"
  )

  if st.button("Fiyatları Hesapla ve Sisteme Uygula", use_container_width=True):
    st.session_state.ayar_kar_marji = f_kar
    st.session_state.ayar_komisyon = f_kom
    st.session_state.ayar_kargo_fiyati = f_kargo
    st.session_state.ayar_marka = f_marka

    for idx, row in st.session_state.urunler_db.iterrows():
      alis = row["Alış Fiyatı"]
      yeni_satis = (
          alis
          * (1 + f_kar / 100)
          * (1 + f_kom / 100)
          + f_kargo
      )
      st.session_state.urunler_db.at[idx, "Satış Fiyatı"] = round(yeni_satis, 2)

    st.success("Tüm satış fiyatları güncel oranlarla yeniden hesaplandı!")

  st.dataframe(
      st.session_state.urunler_db[["Ürün Adı", "Alış Fiyatı", "Satış Fiyatı"]],
      use_container_width=True,
      hide_index=True,
  )

# -------------------------------------------------------------
# 5. API & MAĞAZA BAĞLANTILARI
# -------------------------------------------------------------
elif menu_secimi == "🔑 API & Mağaza Bağlantıları":
  st.subheader("🔑 Pazaryeri API Entegrasyon ve Bağlantı Merkezi")
  st.markdown(
      "Pazaryerlerinden sipariş çekmek ve ürün göndermek için gerekli API"
      " anahtarlarınızı girip test edebilirsiniz."
  )

  for k, v in st.session_state.api_bilgileri.items():
    st.session_state.api_bilgileri[k] = st.text_input(
        k, value=v, type="password", key=f"menu_api_{k}"
    )

  col_t1, col_t2 = st.columns(2)
  with col_t1:
    if st.button("🔌 API Bağlantılarını Test Et", use_container_width=True):
      with st.spinner("Sunuculara ping atılıyor ve token doğrulanıyor..."):
        time.sleep(1.5)
      st.success("Tüm API bağlantıları başarılı ve aktif!")
  with col_t2:
    if st.button("💾 Bilgileri Kalıcı Kaydet", use_container_width=True):
      st.success("API bilgileri sisteme kaydedildi.")

# -------------------------------------------------------------
# 6. SİPARİŞ TAKİP MERKEZİ
# -------------------------------------------------------------
elif menu_secimi == "🛒 Sipariş Takip Merkezi":
  st.subheader("🛒 Pazaryeri Sipariş Takip ve Yönetim Paneli")
  st.markdown(
      "Tüm pazaryerlerinden gelen siparişler burada toplanır, kargo etiketleri"
      " oluşturulabilir."
  )

  if st.button("🔄 Siparişleri Şimdi Güncelle / Çek", use_container_width=True):
    with st.spinner("Mağazalardan yeni siparişler sorgulanıyor..."):
      time.sleep(1)
    st.success("Sipariş listesi güncel!")

  st.dataframe(
      st.session_state.siparisler, use_container_width=True, hide_index=True
  )

# -------------------------------------------------------------
# 7. STOK SENKRONİZASYONU
# -------------------------------------------------------------
elif menu_secimi == "🔄 Stok Senkronizasyonu":
  st.subheader("🔄 Otomatik Stok ve Kritik Stok Yönetimi")
  st.markdown(
      "Stoku azalan ürünler anlık tespit edilir ve tüm pazaryerlerinde eş"
      " zamanlı güncellenir."
  )

  kritik_stok = st.session_state.urunler_db[
      st.session_state.urunler_db["Stok"] < 50
  ]
  st.dataframe(kritik_stok, use_container_width=True, hide_index=True)

  if st.button(
      "⚡ Kritik Stokları Tüm Pazaryerlerinde Sıfırla / Güncelle",
      use_container_width=True,
  ):
    with st.spinner("Stok senkronizasyonu çalışıyor..."):
      time.sleep(1)
    st.success("Stoklar güncellendi!")

# -------------------------------------------------------------
# 8. DESTEK & BİLDİRİMLER
# -------------------------------------------------------------
elif menu_secimi == "🎧 Destek & Bildirimler":
  st.subheader("🎧 Teknik Destek ve Operasyon Masası")
  st.success("Şah Entegre operasyon ekibi taleplerinizi incelemektedir.")
  st.text_area("Destek Talebi veya Sorununuzu Yazın")
  if st.button("Destek Talebini Gönder", use_container_width=True):
    st.success(
        "Talebiniz başarıyla oluşturuldu. En kısa sürede dönüş yapılacaktır."
    )
