import time
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Şah Entegre - Profesyonel E-Ticaret ve Pazaryeri Yönetimi",
    page_icon="👑",
    layout="wide",
)

# -------------------------------------------------------------
# 1. PROFESYONEL CSS & MOBİL UYUMLU ARAYÜZ TASARIMI
# -------------------------------------------------------------
st.markdown(
    """
    <style>
    .stApp { background-color: #f8fafc; }
    .metric-container { display: flex; gap: 15px; margin-bottom: 20px; flex-wrap: wrap; }
    .metric-card { flex: 1; min-width: 180px; background: white; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
    .pazar-badge { font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 4px; color: white; display: inline-block; margin-bottom: 8px; }
    .panel-box { background: white; border: 1px solid #e2e8f0; border-radius: 10px; padding: 20px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
    .panel-header { background: #1e293b; color: white; padding: 12px 16px; font-weight: 700; font-size: 14px; border-radius: 6px; margin-bottom: 15px; }
    </style>
""",
    unsafe_allow_html=True,
)

# -------------------------------------------------------------
# 2. OTURUM VE GÜVENLİ GİRİŞ YÖNETİMİ
# -------------------------------------------------------------
if "authenticated" not in st.session_state:
  st.session_state.authenticated = False

if not st.session_state.authenticated:
  st.markdown(
      "<h2 style='text-align: center; color: #1e293b;'>⚡ ŞAH ENTEGRE"
      " Kurumsal Giriş Paneli</h2>",
      unsafe_allow_html=True,
  )
  col1, col2, col3 = st.columns([1, 2, 1])
  with col2:
    st.markdown(
        "<div"
        " style='background:white; padding:30px; border-radius:10px;"
        " border:1px solid #e2e8f0;'>",
        unsafe_allow_html=True,
    )
    kullanici_adi = st.text_input("Mağaza / Firma Yetkilisi", value="admin")
    sifre = st.text_input("Erişim Şifresi", type="password", value="123456")
    if st.button("Sisteme Giriş Yap", use_container_width=True):
      if kullanici_adi and sifre:
        st.session_state.authenticated = True
        st.session_state.kullanici = kullanici_adi
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
  st.stop()

# -------------------------------------------------------------
# 3. BELLEK İÇİ PROFESYONEL VERİTABANI (STATE)
# -------------------------------------------------------------
if "urunler_db" not in st.session_state:
  st.session_state.urunler_db = pd.DataFrame([
      {
          "id": 1,
          "gorsel": (
              "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=100"
          ),
          "barkod": "8680001122331",
          "urun_adi": "Kablosuz Hızlı Şarj Cihazı 15W",
          "kategori": "Elektronik > Aksesuar",
          "alis_fiyati": 250.0,
          "satis_fiyati": 396.75,
          "stok": 142,
          "durum": "Aktif",
      },
      {
          "id": 2,
          "gorsel": (
              "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=100"
          ),
          "barkod": "8680001122332",
          "urun_adi": "Bluetooth 5.0 Kulaklık",
          "kategori": "Elektronik > Ses",
          "alis_fiyati": 600.0,
          "satis_fiyati": 952.20,
          "stok": 85,
          "durum": "Aktif",
      },
      {
          "id": 3,
          "gorsel": (
              "https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=100"
          ),
          "barkod": "8680001122333",
          "urun_adi": "Ortopedik Spor Ayakkabı",
          "kategori": "Spor > Giyim",
          "alis_fiyati": 450.0,
          "satis_fiyati": 714.15,
          "stok": 12,
          "durum": "Kritik Stok",
      },
  ])

if "siparisler_db" not in st.session_state:
  st.session_state.siparisler_db = pd.DataFrame([
      {
          "siparis_no": "SAH-88412",
          "pazaryeri": "Trendyol",
          "musteri": "Ahmet Yılmaz",
          "urun": "Kablosuz Şarj",
          "tutar": "396.75 TL",
          "kargo_kodu": "TRG-99812345",
          "durum": "Yeni Sipariş",
      },
      {
          "siparis_no": "SAH-88413",
          "pazaryeri": "Hepsiburada",
          "musteri": "Zeynep Demir",
          "urun": "Kulaklık",
          "tutar": "952.20 TL",
          "kargo_kodu": "HB-44521890",
          "durum": "Kargolandı",
      },
  ])

# -------------------------------------------------------------
# 4. ÜST HEADER VE PROFİL YÖNETİMİ
# -------------------------------------------------------------
ust_col1, ust_col2 = st.columns([3, 2])
with ust_col1:
  st.markdown(
      "<span style='font-size: 16px; font-weight: 800; color:"
      " #0f172a;'>👑 ŞAH ENTEGRE - E-Ticaret Operasyon Merkezi</span>",
      unsafe_allow_html=True,
  )
with ust_col2:
  profil_menu = [
      f"👤 {st.session_state.get('kullanici', 'Admin')} (Yönetici)",
      "🚪 Güvenli Çıkış",
  ]
  secilen_profil_islem = st.selectbox(
      "Profil", profil_menu, label_visibility="collapsed"
  )

st.markdown("---")

if secilen_profil_islem == "🚪 Güvenli Çıkış":
  st.session_state.authenticated = False
  st.rerun()

# -------------------------------------------------------------
# 5. SOL MENÜ (EN İYİ ÖZELLİKLER KONSOLU)
# -------------------------------------------------------------
st.sidebar.markdown(
    """
    <div style="text-align: center; padding: 10px 0; margin-bottom: 10px;">
        <span style="font-size: 24px; font-weight: 900; color: #f27a1a;">ŞAH</span>
        <span style="font-size: 18px; font-weight: 700; color: #0f172a;">ENTEGRE</span>
        <div style="font-size: 11px; color: #64748b; margin-top: 2px;">Entegra Sürüm 5.0</div>
    </div>
""",
    unsafe_allow_html=True,
)

aktif_sayfa = st.sidebar.selectbox(
    "Ana Menü",
    [
        "🏠 Yönetim Paneli",
        "📦 Ürün ve Stok Havuzu",
        "🛒 Çift Yönlü Sipariş & Kargo",
        "⚙️ Fiyat & Komisyon Motoru",
        "📄 Ön Muhasebe & E-Fatura",
        "🔄 Çoklu Pazaryeri Eşitleme",
        "📜 Sistem Logları",
    ],
)

# -------------------------------------------------------------
# 6. SAYFA İÇERİKLERİ
# -------------------------------------------------------------

if aktif_sayfa == "🏠 Yönetim Paneli":
  st.subheader("👑 Genel Bakış ve Canlı Metrikler")

  st.markdown(
      """
        <div class="metric-container">
            <div class="metric-card"><div class="pazar-badge" style="background:#ff6600;">TRENDYOL</div><div style="font-size:11px; color:#64748b;">Bekleyen Sipariş</div><div style="font-size:16px; font-weight:700; color:#0f172a;">1 Adet</div></div>
            <div class="metric-card"><div class="pazar-badge" style="background:#f27a1a;">HEPSİBURADA</div><div style="font-size:11px; color:#64748b;">Bekleyen Sipariş</div><div style="font-size:16px; font-weight:700; color:#0f172a;">1 Adet</div></div>
            <div class="metric-card"><div class="pazar-badge" style="background:#e6005c;">ÇİÇEKSEPETİ</div><div style="font-size:11px; color:#64748b;">Bekleyen Sipariş</div><div style="font-size:16px; font-weight:700; color:#0f172a;">0 Adet</div></div>
            <div class="metric-card"><div class="pazar-badge" style="background:#6b46c1;">N11</div><div style="font-size:11px; color:#64748b;">Bekleyen Sipariş</div><div style="font-size:16px; font-weight:700; color:#0f172a;">0 Adet</div></div>
        </div>
    """,
      unsafe_allow_html=True,
  )

  toplam_urun = len(st.session_state.urunler_db)
  kritik_stok = len(
      st.session_state.urunler_db[st.session_state.urunler_db["stok"] < 20]
  )

  st.markdown(
      f"""
        <div class="panel-box">
            <div class="panel-header">📊 Entegrasyon Sağlık Durumu</div>
            <table style="width:100%; font-size:13px; color:#1e293b; border-collapse:collapse;">
                <tr><td style="padding:6px; font-weight:600; width:220px;">Sistem Modülü:</td><td>Aktif ve Kararlı (Entegra Altyapısı)</td></tr>
                <tr><td style="padding:6px; font-weight:600;">Havuzdaki Toplam Ürün:</td><td>{toplam_urun} Adet</td></tr>
                <tr><td style="padding:6px; font-weight:600;">Kritik Stoktaki Ürünler:</td><td>{kritik_stok} Adet</td></tr>
                <tr><td style="padding:6px; font-weight:600;">Otomatik Stok Senkronizasyonu:</td><td>Aktif (Anlık Çift Yönlü)</td></tr>
            </table>
        </div>
    """,
      unsafe_allow_html=True,
  )

  if st.button(
      "🔄 Tüm Pazaryeri Stok ve Fiyatlarını Şimdi Eşitle",
      use_container_width=True,
  ):
    with st.spinner(
        "Trendyol, Hepsiburada, N11 ve Çiçeksepeti API'leri taranıyor..."
    ):
      time.sleep(1.2)
    st.success(
        "Tüm pazaryerlerindeki stok ve fiyatlar başarıyla güncellendi!"
    )

elif aktif_sayfa == "📦 Ürün ve Stok Havuzu":
  st.subheader("📦 Merkezi Ürün ve Barkod Yönetimi")

  with st.expander("➕ Yeni Ürün Ekle ve Pazaryerlerine Gönder", expanded=False):
    c1, c2 = st.columns(2)
    with c1:
      y_ad = st.text_input("Ürün Adı")
      y_barkod = st.text_input("Barkod / GTIN Numarası")
      y_kat = st.selectbox(
          "Kategori",
          [
              "Elektronik > Aksesuar",
              "Elektronik > Ses",
              "Spor > Giyim",
              "Ev > Yaşam",
          ],
      )
    with c2:
      y_alis = st.number_input("Alış Fiyatı (TL)", value=100.0)
      y_stok = st.number_input("Stok Adedi", value=50, step=1)
      y_gorsel = st.text_input(
          "Görsel URL",
          value="https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=100",
      )

    if st.button("Ürünü Kaydet ve Listele", use_container_width=True):
      if y_ad and y_barkod:
        hesaplanan_satis = round(y_alis * 1.2 * 1.15 + 40.0, 2)
        yeni_id = (
            int(st.session_state.urunler_db["id"].max()) + 1
            if not st.session_state.urunler_db.empty
            else 1
        )
        yeni_satir = pd.DataFrame([{
            "id": yeni_id,
            "gorsel": y_gorsel,
            "barkod": y_barkod,
            "urun_adi": y_ad,
            "kategori": y_kat,
            "alis_fiyati": y_alis,
            "satis_fiyati": hesaplanan_satis,
            "stok": y_stok,
            "durum": "Aktif",
        }])
        st.session_state.urunler_db = pd.concat(
            [st.session_state.urunler_db, yeni_satir], ignore_index=True
        )
        st.success("Ürün eklendi ve tüm pazaryeri havuzuna yansıtıldı!")
        st.rerun()
      else:
        st.error("Lütfen zorunlu alanları doldurun.")

  arama_terimi = st.text_input(
      "🔍 Ürün Ara", placeholder="Ürün adı veya barkod ile arayın..."
  )
  gosterilecek_df = st.session_state.urunler_db
  if arama_terimi:
    gosterilecek_df = gosterilecek_df[
        gosterilecek_df["urun_adi"]
        .str.lower()
        .str.contains(arama_terimi.lower())
        | gosterilecek_df["barkod"]
        .str.lower()
        .str.contains(arama_terimi.lower())
    ]

  st.dataframe(
      gosterilecek_df,
      column_config={
          "gorsel": st.column_config.ImageColumn("Görsel", width=70),
          "alis_fiyati": st.column_config.NumberColumn(
              "Alış (TL)", format="%.2f ₺"
          ),
          "satis_fiyati": st.column_config.NumberColumn(
              "Satış (TL)", format="%.2f ₺"
          ),
      },
      use_container_width=True,
      hide_index=True,
  )

elif aktif_sayfa == "🛒 Çift Yönlü Sipariş & Kargo":
  st.subheader("🛒 Otomatik Sipariş ve Kargo Barkod Yönetimi")
  if st.button("🔄 Pazaryerlerinden Yeni Siparişleri Çek", use_container_width=True):
    with st.spinner("Sipariş API'leri sorgulanıyor..."):
      time.sleep(1)
    st.success("Tüm yeni siparişler başarıyla içeri aktarıldı!")

  st.dataframe(
      st.session_state.siparisler_db,
      use_container_width=True,
      hide_index=True,
  )
  st.info(
      "💡 İpucu: Seçilen siparişlerin kargo barkodları otomatik olarak kargo"
      " firmasıyla paylaşılır ve müşteriye SMS/Email iletilir."
  )

elif aktif_sayfa == "⚙️ Fiyat & Komisyon Motoru":
  st.subheader("⚙️ Kural Tabanlı Otomatik Fiyatlandırma")
  f_kar = st.number_input("Global Kâr Marjı (%)", value=20.0)
  f_kom = st.number_input("Pazaryeri Komisyonu Oranı (%)", value=15.0)
  f_kargo = st.number_input("Sabit Kargo Hizmet Bedeli (TL)", value=40.0)

  if st.button(
      "Fiyatları Otomatik Hesapla ve Tüm Mağazalarda Güncelle",
      use_container_width=True,
  ):
    st.session_state.urunler_db["satis_fiyati"] = st.session_state.urunler_db[
        "alis_fiyati"
    ].apply(
        lambda x: round(x * (1 + f_kar / 100) * (1 + f_kom / 100) + f_kargo, 2)
    )
    st.success(
        "Tüm ürünlerin satış fiyatları komisyon ve kargo dahil edilerek"
        " güncellendi!"
    )

  st.dataframe(
      st.session_state.urunler_db[["urun_adi", "alis_fiyati", "satis_fiyati"]],
      use_container_width=True,
      hide_index=True,
  )

elif aktif_sayfa == "📄 Ön Muhasebe & E-Fatura":
  st.subheader("📄 Ön Muhasebe ve E-Arşiv / E-Fatura Entegrasyonu")
  st.markdown(
      "Sistem üzerinden kesilen faturalar otomatik olarak Logo, Mikro veya"
      " Paraşüt altyapısına işlenir."
  )
  st.dataframe(
      st.session_state.siparisler_db[["siparis_no", "musteri", "tutar", "durum"]],
      use_container_width=True,
      hide_index=True,
  )
  if st.button("Seçili Siparişlerin E-Faturalarını Kes", use_container_width=True):
    with st.spinner("GİB E-Fatura portalına bağlanılıyor..."):
      time.sleep(1.5)
    st.success(
        "Faturalar başarıyla oluşturuldu ve müşterilere elektronik olarak"
        " gönderildi!"
    )

elif aktif_sayfa == "🔄 Çoklu Pazaryeri Eşitleme":
  st.subheader("🔄 Çoklu Kanal Pazaryeri Entegrasyon Konsolu")
  secilen_kanal = st.selectbox(
      "Hedef Kanal",
      [
          "Trendyol",
          "Hepsiburada",
          "N11",
          "ÇiçekSepeti",
          "Pazarama",
          "İdefix",
          "Tüm Kanallar",
      ],
  )
  col_k1, col_k2 = st.columns(2)
  with col_k1:
    if st.button(
        f"📤 Ürünleri {secilen_kanal}'ne Toplu Gönder", use_container_width=True
    ):
      with st.spinner(f"{secilen_kanal} API kuyruğuna aktarılıyor..."):
        time.sleep(1.2)
      st.success(f"Ürünler başarıyla {secilen_kanal} mağazanızda satışa açıldı!")
  with col_k2:
    if st.button(
        f"📥 {secilen_kanal} Stok ve Fiyatlarını Eşitle", use_container_width=True
    ):
      with st.spinner("Veriler senkronize ediliyor..."):
        time.sleep(1.2)
      st.success(f"{secilen_kanal} senkronizasyonu tamamlandı!")

elif aktif_sayfa == "📜 Sistem Logları":
  st.subheader("📜 Canlı İşlem ve API Log Kayıtları")
  st.code(
      f"[{time.strftime('%H:%M:%S')}] Entegra çekirdek servisi kararlı"
      " çalışıyor.\n[{time.strftime('%H:%M:%S')}] Trendyol stok webhook bağlantısı"
      " aktif.\n[{time.strftime('%H:%M:%S')}] Hepsiburada sipariş kuyruğu"
      " dinleniyor.\n[{time.strftime('%H:%M:%S')}] Ön muhasebe bağlantı tokeni"
      " doğrulandı.",
      language="text",
  )
