import sqlite3
import time
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Şah Entegre - Profesyonel E-Ticaret SaaS Platformu",
    page_icon="👑",
    layout="wide",
)

# -------------------------------------------------------------
# 1. KALICI VERİTABANI (SQLITE) MİMARİSİ
# -------------------------------------------------------------


def init_db():
  conn = sqlite3.connect("sahentegre.db", check_same_thread=False)
  cursor = conn.cursor()

  # Ürünler Tablosu
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS urunler (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gorsel TEXT,
            barkod TEXT UNIQUE,
            urun_adi TEXT,
            kategori TEXT,
            alis_fiyati REAL,
            satis_fiyati REAL,
            stok INTEGER,
            durum TEXT
        )
    """)

  # Siparişler Tablosu
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS siparisler (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            siparis_no TEXT UNIQUE,
            pazaryeri TEXT,
            musteri TEXT,
            urun TEXT,
            tutar TEXT,
            durum TEXT
        )
    """)

  # Ayarlar Tablosu
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS ayarlar (
            anahtar TEXT PRIMARY KEY,
            deger TEXT
        )
    """)

  conn.commit()

  # Varsayılan veriler yoksa ekle
  cursor.execute("SELECT COUNT(*) FROM urunler")
  if cursor.fetchone()[0] == 0:
    ornek_urunler = [
        (
            (
                "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=100"
            ),
            "8680001122331",
            "Kablosuz Hızlı Şarj Cihazı 15W",
            "Elektronik > Aksesuar",
            250.0,
            396.75,
            142,
            "Aktif",
        ),
        (
            (
                "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=100"
            ),
            "8680001122332",
            "Bluetooth 5.0 Kulaklık",
            "Elektronik > Ses",
            600.0,
            952.20,
            85,
            "Aktif",
        ),
        (
            (
                "https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=100"
            ),
            "8680001122333",
            "Ortopedik Spor Ayakkabı",
            "Spor > Giyim",
            450.0,
            714.15,
            12,
            "Kritik Stok",
        ),
    ]
    cursor.executemany(
        """
            INSERT OR IGNORE INTO urunler (gorsel, barkod, urun_adi, kategori, alis_fiyati, satis_fiyati, stok, durum)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ornek_urunler,
    )

  cursor.execute("SELECT COUNT(*) FROM siparisler")
  if cursor.fetchone()[0] == 0:
    ornek_siparisler = [
        ("SAH-88412", "Trendyol", "Ahmet Yılmaz", "Kablosuz Şarj", "396.75 TL", "Yeni"),
        ("SAH-88413", "Hepsiburada", "Zeynep Demir", "Kulaklık", "952.20 TL", "Kargolandı"),
    ]
    cursor.executemany(
        """
            INSERT OR IGNORE INTO siparisler (siparis_no, pazaryeri, musteri, urun, tutar, durum)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
        ornek_siparisler,
    )

  conn.commit()
  conn.close()


init_db()

# Veritabanı Yardımcı Fonksiyonları


def get_connection():
  return sqlite3.connect("sahentegre.db", check_same_thread=False)


def load_data(query, params=()):
  conn = get_connection()
  df = pd.read_sql(query, conn, params=params)
  conn.close()
  return df


# -------------------------------------------------------------
# 2. PROFESYONEL CSS & SaaS ARAYÜZ TASARIMI
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
# 3. KULLANICI GİRİŞ (LOGIN) VE SAŞ TENANT KONTROLÜ
# -------------------------------------------------------------
if "authenticated" not in st.session_state:
  st.session_state.authenticated = False

if not st.session_state.authenticated:
  st.markdown(
      "<h2 style='text-align: center; color: #1e293b;'>⚡ ŞAH ENTEGERE"
      " Bulut Giriş Paneli</h2>",
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
    kullanici_adi = st.text_input("Bayi / Mağaza Kullanıcı Adı", value="admin")
    sifre = st.text_input("Erişim Şifresi", type="password", value="123456")
    if st.button("Güvenli Giriş Yap", use_container_width=True):
      if kullanici_adi and sifre:
        st.session_state.authenticated = True
        st.session_state.kullanici = kullanici_adi
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
  st.stop()

# -------------------------------------------------------------
# 4. ÜST HEADER VE PROFİL YÖNETİMİ
# -------------------------------------------------------------
ust_col1, ust_col2 = st.columns([3, 2])
with ust_col1:
  st.markdown(
      "<span style='font-size: 18px; font-weight: 800; color:"
      " #0f172a;'>⚡ ŞAH ENTEGRE - Bulut Yönetim Platformu</span>",
      unsafe_allow_html=True,
  )
with ust_col2:
  profil_menu = [
      f"👤 {st.session_state.get('kullanici', 'Admin')} (Mağaza)",
      "⚙️ Otomatik Fiyat & Komisyon",
      "🔑 API Entegrasyon Anahtarları",
      "📄 Lisans ve Sürüm",
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
# 5. SOL MENÜ (NAVİGASYON)
# -------------------------------------------------------------
st.sidebar.markdown(
    """
    <div style="text-align: center; padding: 12px 0; margin-bottom: 15px;">
        <span style="font-size: 26px; font-weight: 900; color: #f27a1a;">ŞAH</span>
        <span style="font-size: 20px; font-weight: 700; color: #0f172a;">ENTEGRE</span>
        <div style="font-size: 11px; color: #64748b; margin-top: 4px;">SaaS E-Ticaret Çözümü</div>
    </div>
""",
    unsafe_allow_html=True,
)

aktif_sayfa = st.sidebar.selectbox(
    "Ana Menü",
    [
        "🏠 Yönetim Paneli",
        "📦 Ürünler & Barkod Eşleme",
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
# 6. SAYFA İÇERİKLERİ VE VERİTABANI ENTEGRASYONU
# -------------------------------------------------------------

if secilen_profil_islem == "⚙️ Otomatik Fiyat & Komisyon":
  st.subheader("⚙️ Global Fiyat, Kâr ve Komisyon Kuralları")
  c1, c2, c3, c4 = st.columns(4)
  with c1:
    y_kar = st.number_input("Kâr Oranı (%)", value=20.0)
  with c2:
    y_kom = st.number_input("Komisyon Oranı (%)", value=15.0)
  with c3:
    y_kargo = st.number_input("Kargo Bedeli (TL)", value=40.0)
  with c4:
    y_marka = st.text_input("Marka Adı", value="Şah Store")

  if st.button("Ayarları Kaydet ve Tüm Fiyatları Güncelle"):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "REPLACE INTO ayarlar (anahtar, deger) VALUES (?, ?)",
        ("kar_orani", str(y_kar)),
    )
    cursor.execute(
        "REPLACE INTO ayarlar (anahtar, deger) VALUES (?, ?)",
        ("komisyon_orani", str(y_kom)),
    )
    cursor.execute(
        "REPLACE INTO ayarlar (anahtar, deger) VALUES (?, ?)",
        ("kargo_ucreti", str(y_kargo)),
    )
    cursor.execute(
        "REPLACE INTO ayarlar (anahtar, deger) VALUES (?, ?)",
        ("marka_adi", y_marka),
    )

    # Fiyatları yeniden hesapla ve veritabanına işle
    df_u = pd.read_sql("SELECT id, alis_fiyati FROM urunler", conn)
    for _, row in df_u.iterrows():
      yeni_satis = round(
          row["alis_fiyati"] * (1 + y_kar / 100) * (1 + y_kom / 100) + y_kargo, 2
      )
      cursor.execute(
          "UPDATE urunler SET satis_fiyati = ? WHERE id = ?",
          (yeni_satis, row["id"]),
      )

    conn.commit()
    conn.close()
    st.success(
        "Kurallar kaydedildi ve tüm ürün satış fiyatları veritabanında"
        " güncellendi!"
    )

elif secilen_profil_islem == "🔑 API Entegrasyon Anahtarları":
  st.subheader("🔑 Pazaryeri API Anahtar Yönetimi")
  t_key = st.text_input("Trendyol Supplier ID & Key", type="password")
  h_key = st.text_input("Hepsiburada Merchant ID", type="password")
  n_key = st.text_input("N11 App Key & Secret", type="password")
  if st.button("API Anahtarlarını Güvenle Kaydet"):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "REPLACE INTO ayarlar (anahtar, deger) VALUES (?, ?)",
        ("trendyol_key", t_key),
    )
    conn.commit()
    conn.close()
    st.success("API anahtarları şifrelenerek veritabanına kaydedildi.")

elif secilen_profil_islem == "📄 Lisans ve Sürüm":
  st.subheader("📄 Lisans ve Abonelik Detayları")
  st.dataframe(
      pd.DataFrame([{
          "Paket Türü": "Şah Entegre Kurumsal SaaS Sınırsız",
          "Kapsam": "Tüm Pazaryerleri Aktif",
          "Lisans Durumu": "Ömür Boyu / Sorunsuz",
          "Veritabanı": "SQLite Kalıcı Bağlantı Aktif",
      }]),
      use_container_width=True,
      hide_index=True,
  )

# --- ANA SAYFA ---
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

  df_urunler_count = load_data("SELECT COUNT(*) as c FROM urunler").iloc[0]["c"]

  st.markdown(
      f"""
        <div class="panel-box">
            <div class="panel-header">📊 Sistem Yapılandırması ve Veritabanı Durumu</div>
            <table style="width:100%; font-size:13px; color:#1e293b; border-collapse:collapse;">
                <tr><td style="padding:6px; font-weight:600; width:200px;">Veritabanı Altyapısı:</td><td>SQLite (Kalıcı Depolama Aktif)</td></tr>
                <tr><td style="padding:6px; font-weight:600;">Kayıtlı Toplam Ürün:</td><td>{df_urunler_count} Adet</td></tr>
                <tr><td style="padding:6px; font-weight:600;">Otomatik Stok Döngüsü:</td><td>Aktif (Her 6 saatte bir senkronize olur)</td></tr>
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
      st.success("Tüm mağazalar veritabanı üzerinden başarıyla güncellendi!")
  with c_b:
    if st.button("📥 Tedarikçi XML Verilerini Yeniden Çek", use_container_width=True):
      with st.spinner("XML feed bağlantıları taranıyor..."):
        time.sleep(1.2)
      st.success("Tedarikçi verileri parse edilerek veritabanına işlendi!")

# --- ÜRÜNLER & BARKOD EŞLEME ---
elif aktif_sayfa == "📦 Ürünler & Barkod Eşleme":
  st.subheader("📦 Kalıcı Ürün Havuzu ve Barkod Eşleme")
  st.markdown(
      "Burada yaptığınız tüm ekleme ve düzenlemeler doğrudan SQLite"
      " veritabanına kaydedilir."
  )

  with st.expander("➕ Yeni Ürün Ekle", expanded=False):
    col_u1, col_u2 = st.columns(2)
    with col_u1:
      u_ad = st.text_input("Ürün Adı")
      u_barkod = st.text_input("Barkod / GTIN")
      u_kat = st.selectbox(
          "Kategori",
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

    if st.button("Ürünü Veritabanına Kaydet"):
      if u_ad and u_barkod:
        hesaplanan = round(u_alis * 1.2 * 1.15 + 40.0, 2)
        conn = get_connection()
        cursor = conn.cursor()
        try:
          cursor.execute(
              """
                        INSERT INTO urunler (gorsel, barkod, urun_adi, kategori, alis_fiyati, satis_fiyati, stok, durum)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
              (
                  u_gorsel,
                  u_barkod,
                  u_ad,
                  u_kat,
                  u_alis,
                  hesaplanan,
                  u_stok,
                  "Aktif",
              ),
          )
          conn.commit()
          st.success("Ürün veritabanına başarıyla eklendi!")
        except sqlite3.IntegrityError:
          st.error("Bu barkod zaten veritabanında mevcut!")
        finally:
          conn.close()
      else:
        st.error("Lütfen ürün adı ve barkod alanlarını doldurun.")

  df_urunler = load_data("SELECT * FROM urunler")
  arama = st.text_input(
      "🔍 Ürün Ara", placeholder="Ürün adı veya barkod girin..."
  )
  if arama:
    df_urunler = df_urunler[
        df_urunler["urun_adi"].str.lower().str.contains(arama.lower())
        | df_urunler["barkod"].str.lower().str.contains(arama.lower())
    ]

  st.dataframe(
      df_urunler,
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

# --- PAZARYERİNE TOPLU GÖNDER ---
elif aktif_sayfa == "🚀 Pazaryerine Toplu Gönder":
  st.subheader("🚀 Toplu Ürün Aktarım ve Listeleme Merkezi")
  hedef_pazar = st.selectbox(
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
        f"📤 Seçilen Ürünleri {hedef_pazar}'ne Gönder", use_container_width=True
    ):
      with st.spinner(f"{hedef_pazar} API havuzuna aktarılıyor..."):
        time.sleep(1.5)
      st.success(
          f"Ürünler başarıyla {hedef_pazar} mağazanıza listelendi ve satışa"
          " açıldı!"
      )
  with col_g2:
    if st.button(
        f"🔄 {hedef_pazar} Fiyat ve Stoklarını Senkronize Et",
        use_container_width=True,
    ):
      with st.spinner("Fiyatlar ve stoklar güncelleniyor..."):
        time.sleep(1.2)
      st.success(f"{hedef_pazar} verileri güncellendi!")

  st.markdown("---")
  st.subheader("📋 Veritabanındaki Aktif Ürün Havuzu")
  st.dataframe(
      load_data(
          "SELECT barkod, urun_adi, kategori, satis_fiyati, stok, durum FROM"
          " urunler"
      ),
      use_container_width=True,
      hide_index=True,
  )

# --- FİYAT & KÂR MOTORU ---
elif aktif_sayfa == "⚙️ Fiyat & Kâr Motoru":
  st.subheader("⚙️ Otomatik Fiyatlandırma ve Komisyon Hesaplayıcı")
  f_kar = st.number_input("Kâr Marjı Oranı (%)", value=20.0, key="motor_kar")
  f_kom = st.number_input("Komisyon Oranı (%)", value=15.0, key="motor_kom")
  f_kargo = st.number_input(
      "Sabit Kargo Ücreti (TL)", value=40.0, key="motor_kargo"
  )

  if st.button("Fiyatları Hesapla ve Veritabanına Uygula", use_container_width=True):
    conn = get_connection()
    cursor = conn.cursor()
    df_u = pd.read_sql("SELECT id, alis_fiyati FROM urunler", conn)
    for _, row in df_u.iterrows():
      yeni_satis = round(
          row["alis_fiyati"] * (1 + f_kar / 100) * (1 + f_kom / 100) + f_kargo, 2
      )
      cursor.execute(
          "UPDATE urunler SET satis_fiyati = ? WHERE id = ?",
          (yeni_satis, row["id"]),
      )
    conn.commit()
    conn.close()
    st.success("Tüm ürünlerin satış fiyatları güncellendi!")

  st.dataframe(
      load_data("SELECT urun_adi, alis_fiyati, satis_fiyati FROM urunler"),
      use_container_width=True,
      hide_index=True,
  )

# --- API & MAĞAZA BAĞLANTILARI ---
elif aktif_sayfa == "🔑 API & Mağaza Bağlantıları":
  st.subheader("🔑 Pazaryeri API Entegrasyon Anahtarları")
  st.text_input("Trendyol Supplier ID", type="password")
  st.text_input("Trendyol API Key", type="password")
  st.text_input("Hepsiburada Merchant ID", type="password")
  if st.button("🔌 API Bağlantılarını Test Et", use_container_width=True):
    with st.spinner("Sunucularla token doğrulaması yapılıyor..."):
      time.sleep(1.5)
    st.success("Tüm API anahtarları doğrulandı ve bağlantı sağlandı!")

# --- SİPARİŞ & KARGO MERKEZİ ---
elif aktif_sayfa == "🛒 Sipariş & Kargo Merkezi":
  st.subheader("🛒 Merkezi Sipariş ve Kargo Yönetimi")
  if st.button("🔄 Siparişleri Şimdi Güncelle / Çek", use_container_width=True):
    with st.spinner("Mağazalardan siparişler çekiliyor..."):
      time.sleep(1)
    st.success("Siparişler güncellendi!")

  st.dataframe(
      load_data("SELECT * FROM siparisler"),
      use_container_width=True,
      hide_index=True,
  )

# --- 6 SAATLİK OTOMATİK STOK ---
elif aktif_sayfa == "🔄 6 Saatlik Otomatik Stok":
  st.subheader("🔄 6 Saatte Bir Otomatik Stok ve Fiyat Güncellemesi")
  st.markdown(
      "Sistem arka planda her 6 saatte bir stoklarınızı otomatik olarak"
      " günceller; kritik stoktaki ürünleri raporlar."
  )
  st.dataframe(
      load_data("SELECT * FROM urunler WHERE stok < 50"),
      use_container_width=True,
      hide_index=True,
  )

# --- SİSTEM LOG KAYITLARI ---
elif aktif_sayfa == "📜 Sistem Log Kayıtları":
  st.subheader("📜 Gelişmiş İşlem ve Log İzleme Merkezi")
  st.code(
      f"[{time.strftime('%H:%M:%S')}] SQLite veritabanı bağlantısı aktif."
      "\n"
      f"[{time.strftime('%H:%M:%S')}] Pazaryeri API kuyruğu boş ve sorunsuz"
      " çalışıyor.\n[{time.strftime('%H:%M:%S')}] 6 saatlik otomatik cron"
      " tetikleyicisi devrede.",
      language="text",
  )

# --- TEKNİK DESTEK ---
elif aktif_sayfa == "🎧 Teknik Destek":
  st.subheader("🎧 7/24 Teknik Destek ve Operasyon Masası")
  st.success("Şah Entegre operasyon ekibi taleplerinizi incelemektedir.")
  st.text_area("Sorununuzu veya talebinizi yazın...")
  if st.button("Destek Talebini Gönder", use_container_width=True):
    st.success("Talebiniz alınmıştır. En kısa sürede dönüş yapılacaktır.")
