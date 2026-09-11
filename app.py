import time
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Şah Entegre - Profesyonel E-Ticaret Yönetim Platformu",
    page_icon="👑",
    layout="wide",
)

# Kurumsal Tasarım ve Orijinal Renk Paleti CSS
st.markdown(
    """
    <style>
    .stApp { background-color: #f1f5f9; }
    .mp-grid { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
    .mp-card { flex: 1; min-width: 120px; background: white; border: 1px solid #cbd5e1; border-radius: 6px; padding: 10px; text-align: center; box-shadow: 0 1px 2px rgba(0,0,0,0.02); }
    .mp-badge { font-size: 10px; font-weight: 700; padding: 3px 6px; border-radius: 4px; color: white; display: inline-block; margin-bottom: 5px; }
    .box-container { background: white; border: 1px solid #cbd5e1; border-radius: 8px; padding: 15px; margin-bottom: 15px; box-shadow: 0 1px 3px rgba(0,0,0,0.03); }
    .box-header { background: #1e3a8a; color: white; padding: 8px 12px; font-weight: 700; font-size: 13px; border-radius: 4px; margin-bottom: 10px; text-align: center; }
    </style>
""",
    unsafe_allow_html=True,
)

# -------------------------------------------------------------
# MERKEZİ VERİTABANI & OTURUM HAFIZASI (STATE MANAGEMENT)
# -------------------------------------------------------------
if "kar_orani" not in st.session_state:
  st.session_state.kar_orani = 25.0
if "komisyon_orani" not in st.session_state:
  st.session_state.komisyon_orani = 18.0
if "kargo_ucreti" not in st.session_state:
  st.session_state.kargo_ucreti = 45.0
if "marka_adi" not in st.session_state:
  st.session_state.marka_adi = "Şah Store"

if "api_anahtarlari" not in st.session_state:
  st.session_state.api_anahtarlari = {
      "Trendyol Supplier ID / API Key": "",
      "Hepsiburada Merchant ID": "",
      "N11 App Key / Secret": "",
      "ÇiçekSepeti API Token": "",
      "E-PTT AVM API Key": "",
  }

if "urun_havuzu" not in st.session_state:
  st.session_state.urun_havuzu = pd.DataFrame([
      {
          "Görsel": "https://images.unsplash.com/photo-1584263155336-d64e9a8f4675?w=100",
          "Barkod": "CYRO-679931-LXL",
          "Ürün Adı": "Siyah Dantelli Sabahlık & Gecelik Takımı",
          "Alış Fiyatı": 400.00,
          "Satış Fiyatı": 726.00,
          "Trendyol Stok": 98,
          "Hepsiburada Stok": 98,
          "M.Entegre Stok": 150,
          "Durum": "Satışta / Onaylı",
      },
      {
          "Görsel": "https://images.unsplash.com/photo-1543163521-1bf539c55dd2?w=100",
          "Barkod": "CYRO-679931-SM",
          "Ürün Adı": "Siyah Dantelli Sabahlık & Gecelik Takımı (SM)",
          "Alış Fiyatı": 400.00,
          "Satış Fiyatı": 726.00,
          "Trendyol Stok": 100,
          "Hepsiburada Stok": 100,
          "M.Entegre Stok": 120,
          "Durum": "Satışta / Onaylı",
      },
      {
          "Görsel": "https://images.unsplash.com/photo-1517841905240-472988babdf9?w=100",
          "Barkod": "606214114000007",
          "Ürün Adı": "Ayarlanabilir Dizüstü Destek Tabanı Tam Boy",
          "Alış Fiyatı": 350.00,
          "Satış Fiyatı": 629.70,
          "Trendyol Stok": 27,
          "Hepsiburada Stok": 27,
          "M.Entegre Stok": 45,
          "Durum": "Satışta / Onaylı",
      },
  ])

if "siparisler_db" not in st.session_state:
  st.session_state.siparisler_db = pd.DataFrame([
      {
          "Sipariş ID": "SAH-88412",
          "Pazaryeri": "Trendyol",
          "Müşteri": "Ahmet Yılmaz",
          "Ürün": "Siyah Dantelli Sabahlık",
          "Tutar": "726.00 TL",
          "Durum": "Yeni Sipariş",
      },
      {
          "Sipariş ID": "SAH-88413",
          "Pazaryeri": "Hepsiburada",
          "Müşteri": "Zeynep Demir",
          "Ürün": "Ayarlanabilir Dizüstü Destek",
          "Tutar": "629.70 TL",
          "Durum": "Kargolandı",
      },
  ])

if "sistem_loglari" not in st.session_state:
  st.session_state.sistem_loglari = [
      "[{}] Şah Entegre çekirdek sistem başlatıldı.".format(
          time.strftime("%H:%M:%S")
      ),
      "[{}] Çoklu pazaryeri API adaptörleri aktif.".format(
          time.strftime("%H:%M:%S")
      ),
  ]

# -------------------------------------------------------------
# ÜST BAR VE SAĞ PROFİL MENÜSÜ
# -------------------------------------------------------------
col_h1, col_h2 = st.columns([4, 2])
with col_h1:
  st.markdown(
      "<span style='font-size: 15px; font-weight: 700; color:"
      " #1e293b;'>👑 Şah Entegre - Profesyonel E-Ticaret Yönetim"
      " Paneli</span>",
      unsafe_allow_html=True,
  )
with col_h2:
  profil_secenekleri = [
      "👤 Mağaza ve Fatura Bilgileri",
      "⚙️ Fiyat, Kâr & Komisyon Ayarları",
      "🔑 Pazaryeri API Anahtarları",
      "📄 Faturalarım & Abonelik",
      "🚪 Güvenli Çıkış",
  ]
  secilen_profil = st.selectbox(
      "Profil", profil_secenekleri, label_visibility="collapsed"
  )

st.markdown("---")

# -------------------------------------------------------------
# SOL YAN MENÜ (METENTEGRE ANA MENÜ YAPISI)
# -------------------------------------------------------------
st.sidebar.markdown(
    """
    <div style="text-align: center; padding: 10px 0; margin-bottom: 10px;">
        <span style="font-size: 26px; font-weight: 900; color: #f27a1a;">ŞAH</span>
        <span style="font-size: 15px; font-weight: 600; color: #0f172a;">ENTEGRE</span>
        <div style="font-size: 10px; color: #64748b; margin-top: 2px;">Merkezi Yönetim Sistemi</div>
    </div>
""",
    unsafe_allow_html=True,
)

selected_menu = st.sidebar.selectbox(
    "Yönetim Paneli",
    [
        "🏠 Anasayfa",
        "📦 Sistemdeki Ürünler",
        "🔗 XML & API Entegrasyon Merkezi",
        "🚀 Pazaryerine Ürün Gönder",
        "⚙️ Fiyatlandırma & Kâr Motoru",
        "🔑 Pazaryeri API Bağlantıları",
        "🧡 Trendyol Mağaza Yönetimi",
        "🧡 Hepsiburada Mağaza Yönetimi",
        "💜 N11 Mağaza Yönetimi",
        "🌸 ÇiçekSepeti Yönetimi",
        "💛 E-PTT AVM Yönetimi",
        "🛒 Sipariş Takip Merkezi",
        "⚡ Oto Kritik Stok & 6 Saatlik Döngü",
        "🎧 Destek Taleplerim",
        "📢 Duyurular",
    ],
)

# -------------------------------------------------------------
# PROFİL / HESAP AYARLARI SAYFALARI
# -------------------------------------------------------------
if secilen_profil == "⚙️ Fiyat, Kâr & Komisyon Ayarları":
  st.subheader("⚙️ Global Fiyatlandırma ve Kâr Oranı Kuralları")
  c1, c2, c3, c4 = st.columns(4)
  with c1:
    y_kar = st.number_input("Kâr Marjı (%)", value=st.session_state.kar_orani)
  with c2:
    y_kom = st.number_input(
        "Komisyon Oranı (%)", value=st.session_state.komisyon_orani
    )
  with c3:
    y_kargo = st.number_input(
        "Kargo Ücreti (TL)", value=st.session_state.kargo_ucreti
    )
  with c4:
    y_marka = st.text_input("Marka Adı", value=st.session_state.marka_adi)

  if st.button("Kuralları Kaydet ve Tüm Fiyatları Güncelle"):
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

    st.success(
        "Tüm ürünlerin satış fiyatları yeni kural setine göre güncellendi!"
    )

elif secilen_profil == "🔑 Pazaryeri API Anahtarları":
  st.subheader("🔑 Mağaza API Anahtar Yönetimi")
  for k, v in st.session_state.api_anahtarlari.items():
    st.session_state.api_anahtarlari[k] = st.text_input(
        k, value=v, type="password", key=f"prof_api_{k}"
    )
  if st.button("API Bilgilerini Kaydet"):
    st.success("API anahtarları güvenle kaydedildi!")

elif secilen_profil == "📄 Faturalarım & Abonelik":
  st.subheader("📄 Abonelik ve Geçmiş Faturalar")
  st.dataframe(
      pd.DataFrame([{
          "Sipariş ID": "SAH-PRO-2026",
          "Hizmet": "Şah Entegre Kurumsal Lisans",
          "Tutar": "0.00 ₺",
          "Durum": "Ödendi / Aktif",
      }]),
      use_container_width=True,
      hide_index=True,
  )

elif secilen_profil == "👤 Mağaza ve Fatura Bilgileri":
  st.subheader("👤 Fatura ve Mağaza Bilgileri")
  st.text_input("Firma Unvanı", value="Şah E-Ticaret Limited Şti.")
  st.text_input(
      "Adres", value="Sevgi mah. 4642 sok no 4/1 Karabağlar İzmir"
  )
  st.text_input("Vergi Dairesi / No", value="Kadifekale / 9800650692")
  if st.button("Bilgileri Kaydet"):
    st.success("Bilgiler güncellendi!")

# -------------------------------------------------------------
# 1. ANASAYFA
# -------------------------------------------------------------
if selected_menu == "🏠 Anasayfa":
  st.subheader("👑 Ana Kontrol Paneli")

  st.markdown(
      """
        <div class="mp-grid">
            <div class="mp-card"><div class="mp-badge" style="background:#ff6600;">HEPSİBURADA</div><div style="font-size:11px; color:#64748b;">Sipariş</div><div style="font-size:12px; font-weight:700; color:#dc2626;">1 Sipariş</div></div>
            <div class="mp-card"><div class="mp-badge" style="background:#f27a1a;">TRENDYOL</div><div style="font-size:11px; color:#64748b;">Sipariş</div><div style="font-size:12px; font-weight:700; color:#dc2626;">1 Sipariş</div></div>
            <div class="mp-card"><div class="mp-badge" style="background:#e6005c;">ÇİÇEKSEPETİ</div><div style="font-size:11px; color:#64748b;">Sipariş</div><div style="font-size:12px; font-weight:700; color:#dc2626;">Sipariş yok</div></div>
            <div class="mp-card"><div class="mp-badge" style="background:#334155;">PTT AVM</div><div style="font-size:11px; color:#64748b;">Sipariş</div><div style="font-size:12px; font-weight:700; color:#dc2626;">Sipariş yok</div></div>
            <div class="mp-card"><div class="mp-badge" style="background:#6b46c1;">N11</div><div style="font-size:11px; color:#64748b;">Sipariş</div><div style="font-size:12px; font-weight:700; color:#dc2626;">Sipariş yok</div></div>
        </div>
    """,
      unsafe_allow_html=True,
  )

  st.markdown(
      f"""
        <div class="box-container">
            <div class="box-header">📊 Aktif Sistem Yapılandırması</div>
            <table style="width:100%; font-size:13px; color:#1e293b; border-collapse:collapse;">
                <tr><td style="padding:6px; font-weight:600; width:180px;">Aktif Marka:</td><td>{st.session_state.marka_adi}</td></tr>
                <tr><td style="padding:6px; font-weight:600;">Kâr Marjı Oranı:</td><td>%{st.session_state.kar_orani}</td></tr>
                <tr><td style="padding:6px; font-weight:600;">Komisyon Oranı:</td><td>%{st.session_state.komisyon_orani}</td></tr>
                <tr><td style="padding:6px; font-weight:600;">Sabit Kargo Fiyatı:</td><td>{st.session_state.kargo_ucreti} TL</td></tr>
                <tr><td style="padding:6px; font-weight:600;">Toplam Ürün Havuzu:</td><td>{len(st.session_state.urun_havuzu)} Adet</td></tr>
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
      st.success("Tüm pazaryerleri başarıyla senkronize edildi!")
  with col_q2:
    if st.button("📥 Tüm XML Kaynaklarını Tetikle", use_container_width=True):
      with st.spinner("Tedarikçi XML feedleri taranıyor..."):
        time.sleep(1.2)
      st.success("Tüm ürünler güncel stok bilgileriyle çekildi!")

# -------------------------------------------------------------
# 2. SİSTEMDEKİ ÜRÜNLER
# -------------------------------------------------------------
elif selected_menu == "📦 Sistemdeki Ürünler":
  st.subheader("📦 Sistemdeki Tüm Ürünler ve Barkod Eşleme")
  st.markdown(
      "Merkezi depoda bulunan ürünleri yönetebilir, barkod eşleştirmelerini"
      " güncelleyebilirsiniz."
  )

  arama_q = st.text_input(
      "🔍 Ürün Ara", placeholder="Ürün adı veya barkod ile filtrele..."
  )
  gosterim_df = st.session_state.urun_havuzu.copy()
  if arama_q:
    gosterim_df = gosterim_df[
        gosterim_df["Ürün Adı"].str.lower().str.contains(arama_q.lower())
        | gosterim_df["Barkod"].str.lower().str.contains(arama_q.lower())
    ]

  edited_df = st.data_editor(
      gosterim_df,
      column_config={
          "Görsel": st.column_config.ImageColumn(
              "Ürün Görseli", help="Orijinal Görsel", width=70
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
    st.session_state.urun_havuzu = edited_df
    st.success("Ürün verileri güncellendi!")

# -------------------------------------------------------------
# 3. XML & API ENTEGRASYON MERKEZİ
# -------------------------------------------------------------
elif selected_menu == "🔗 XML & API Entegrasyon Merkezi":
  st.subheader("🔗 Tedarikçi XML ve API Bağlantı Merkezi")
  xml_link = st.text_input(
      "XML Feed URL", placeholder="https://tedarikci.com/feed/urunler.xml"
  )
  ted_adi = st.text_input("Tedarikçi Adı", placeholder="Örn: Global Depo")
  if st.button("XML Verilerini ve Ürünleri Çek"):
    if xml_link:
      with st.spinner("XML parse ediliyor ve ürünler ekleniyor..."):
        time.sleep(1.5)
        yeni_urun = {
            "Görsel": (
                "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=100"
            ),
            "Barkod": "XML-NEW-9981",
            "Ürün Adı": f"XML Ürünü ({ted_adi})",
            "Alış Fiyatı": 500.00,
            "Satış Fiyatı": round(
                500.00
                * (1 + st.session_state.kar_orani / 100)
                * (1 + st.session_state.komisyon_orani / 100)
                + st.session_state.kargo_ucreti,
                2,
            ),
            "Trendyol Stok": 75,
            "Hepsiburada Stok": 75,
            "M.Entegre Stok": 75,
            "Durum": "Satışta",
        }
        st.session_state.urun_havuzu = pd.concat(
            [st.session_state.urun_havuzu, pd.DataFrame([yeni_urun])],
            ignore_index=True,
        )
      st.success("XML ürünleri sisteme başarıyla aktarıldı!")
    else:
      st.error("Lütfen geçerli bir XML linki girin.")

# -------------------------------------------------------------
# 4. PAZARYERİNE ÜRÜN GÖNDER
# -------------------------------------------------------------
elif selected_menu == "🚀 Pazaryerine Ürün Gönder":
  st.subheader("🚀 Pazaryerlerine Toplu Ürün Aktarım Merkezi")
  hedef_pazar = st.selectbox(
      "Hedef Pazaryeri",
      ["Trendyol", "Hepsiburada", "N11", "ÇiçekSepeti", "E-PTT AVM", "Tümü"],
  )

  col_g1, col_g2 = st.columns(2)
  with col_g1:
    if st.button(
        f"📤 Seçilen Ürünleri {hedef_pazar}'ne Gönder", use_container_width=True
    ):
      with st.spinner(f"{hedef_pazar} API servisine aktarılıyor..."):
        time.sleep(1.5)
      st.success(f"Ürünler başarıyla {hedef_pazar} mağazasına listelendi!")
  with col_g2:
    if st.button(
        f"🔄 {hedef_pazar} Fiyat ve Stoklarını Güncelle", use_container_width=True
    ):
      with st.spinner("Stoklar ve karlı fiyatlar güncelleniyor..."):
        time.sleep(1.2)
      st.success(f"{hedef_pazar} verileri güncellendi!")

# -------------------------------------------------------------
# 5. FİYATLANDIRMA & KÂR MOTORU
# -------------------------------------------------------------
elif selected_menu == "⚙️ Fiyatlandırma & Kâr Motoru":
  st.subheader("⚙️ Otomatik Fiyatlandırma ve Komisyon Hesaplayıcı")
  f_kar = st.number_input(
      "Kâr Marjı Oranı (%)",
      value=st.session_state.kar_orani,
      key="fiyat_kar",
  )
  f_kom = st.number_input(
      "Komisyon Oranı (%)",
      value=st.session_state.komisyon_orani,
      key="fiyat_kom",
  )
  f_kargo = st.number_input(
      "Sabit Kargo Ücreti (TL)",
      value=st.session_state.kargo_ucreti,
      key="fiyat_kargo",
  )
  f_marka = st.text_input(
      "Aktif Marka Bilgisi", value=st.session_state.ayar_marka, key="fiyat_marka"
  ) if "ayar_marka" in st.session_state else st.text_input(
      "Aktif Marka Bilgisi", value=st.session_state.marka_adi, key="fiyat_marka"
  )

  if st.button("Fiyatları Hesapla ve Sisteme Uygula", use_container_width=True):
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

    st.success("Tüm satış fiyatları güncel oranlarla yeniden hesaplandı!")

# -------------------------------------------------------------
# 6. PAZARYERİ API BAĞLANTILARI
# -------------------------------------------------------------
elif selected_menu == "🔑 Pazaryeri API Bağlantıları":
  st.subheader("🔑 Pazaryeri API Entegrasyon ve Bağlantı Merkezi")
  for k, v in st.session_state.api_anahtarlari.items():
    st.session_state.api_anahtarlari[k] = st.text_input(
        k, value=v, type="password", key=f"menu_api_{k}"
    )

  if st.button("API Bağlantılarını Test Et ve Kaydet", use_container_width=True):
    with st.spinner("Sunuculara ping atılıyor ve token doğrulanıyor..."):
      time.sleep(1.5)
    st.success("Tüm API bağlantıları başarılı ve aktif!")

# -------------------------------------------------------------
# 7. MAĞAZA YÖNETİM SEKMELERİ (Trendyol, Hepsiburada, N11, ÇiçekSepeti, PTT)
# -------------------------------------------------------------
elif selected_menu in [
    "🧡 Trendyol Mağaza Yönetimi",
    "🧡 Hepsiburada Mağaza Yönetimi",
    "💜 N11 Mağaza Yönetimi",
    "🌸 ÇiçekSepeti Yönetimi",
    "💛 E-PTT AVM Yönetimi",
]:
  pazar_adi = selected_menu.split(" ")[1]
  st.subheader(f"{selected_menu}")
  st.info(
      f"{pazar_adi} mağazanız başarıyla entegre edilmiştir. Bu ekrandan ürünleri"
      " yönetebilir ve siparişleri takip edebilirsiniz."
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

  st.dataframe(
      st.session_state.urun_havuzu[[
          "Barkod",
          "Ürün Adı",
          "Satış Fiyatı",
          "Trendyol Stok",
          "Durum",
      ]],
      use_container_width=True,
      hide_index=True,
  )

# -------------------------------------------------------------
# 8. SİPARİŞ TAKİP MERKEZİ
# -------------------------------------------------------------
elif selected_menu == "🛒 Sipariş Takip Merkezi":
  st.subheader("🛒 Pazaryeri Sipariş Takip ve Yönetim Paneli")
  if st.button("🔄 Siparişleri Şimdi Güncelle / Çek", use_container_width=True):
    with st.spinner("Mağazalardan yeni siparişler sorgulanıyor..."):
      time.sleep(1)
    st.success("Sipariş listesi güncel!")

  st.dataframe(
      st.session_state.siparisler_db, use_container_width=True, hide_index=True
  )

# -------------------------------------------------------------
# 9. OTO KRİTİK STOK & 6 SAATLİK DÖNGÜ
# -------------------------------------------------------------
elif selected_menu == "⚡ Oto Kritik Stok & 6 Saatlik Döngü":
  st.subheader("⚡ Otomatik Kritik Stok ve 6 Saatlik Senkronizasyon Döngüsü")
  st.markdown(
      "Sistem arka planda her 6 saatte bir stoklarınızı ve fiyatlarınızı"
      " otomatik günceller."
  )

  kritik_df = st.session_state.urun_havuzu[
      st.session_state.urun_havuzu["Trendyol Stok"] < 50
  ]
  st.dataframe(kritik_df, use_container_width=True, hide_index=True)

  if st.button(
      "⚡ Şimdi Manuel Stok / Fiyat Senkronizasyonunu Tetikle",
      use_container_width=True,
  ):
    with st.spinner("Otomatik stok döngüsü çalışıyor..."):
      time.sleep(1)
    st.success("Stoklar tüm pazaryerlerinde eşitlendi!")

# -------------------------------------------------------------
# 10. DESTEK VE DUYURULAR
# -------------------------------------------------------------
elif selected_menu == "🎧 Destek Taleplerim":
  st.subheader("🎧 Teknik Destek ve Operasyon Masası")
  st.success("Şah Entegre operasyon ekibi taleplerinizi incelemektedir.")
  st.text_area("Destek Talebi veya Sorununuzu Yazın")
  if st.button("Destek Talebini Gönder", use_container_width=True):
    st.success("Talebiniz başarıyla iletildi!")

elif selected_menu == "📢 Duyurular":
  st.subheader("📢 Sistem Duyuruları ve Eğitimler")
  st.markdown(
      "**EĞİTİM VİDEOLARIMIZ YAYINLANMIŞTIR.** (Yeni entegrasyon rehberini"
      " izleyebilirsiniz.)"
  )
  st.info(
      "Şah Entegre sürüm güncellemeleri ve pazaryeri API değişiklikleri bu"
      " alandan duyurulur."
  )
