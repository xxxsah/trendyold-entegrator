import time
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title=(
        "Şah Entegre & E-Ticaret Altyapısı (Ticimax / Entegra Modeli)"
    ),
    page_icon="👑",
    layout="wide",
)

# -------------------------------------------------------------
# 1. PROFESYONEL CSS & MOBİL UYUMLU ARAYÜZ
# -------------------------------------------------------------
st.markdown(
    """
    <style>
    .stApp { background-color: #f8fafc; }
    .product-card { background: white; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.05); margin-bottom: 15px; }
    .price-tag { font-size: 18px; font-weight: 800; color: #0284c7; margin: 8px 0; }
    .panel-box { background: white; border: 1px solid #e2e8f0; border-radius: 10px; padding: 20px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
    .panel-header { background: #1e293b; color: white; padding: 12px 16px; font-weight: 700; font-size: 14px; border-radius: 6px; margin-bottom: 15px; }
    </style>
""",
    unsafe_allow_html=True,
)

# -------------------------------------------------------------
# 2. OTURUM VE SEPET YÖNETİMİ
# -------------------------------------------------------------
if "authenticated" not in st.session_state:
  st.session_state.authenticated = False

if "sepet" not in st.session_state:
  st.session_state.sepet = []

if not st.session_state.authenticated:
  st.markdown(
      "<h2 style='text-align: center; color: #1e293b;'>⚡ ŞAH TİCİMAX &"
      " ENTEGRE - Yönetici Girişi</h2>",
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
    k_adi = st.text_input("Kullanıcı Adı", value="admin")
    k_sifre = st.text_input("Şifre", type="password", value="123456")
    if st.button("Panele Giriş Yap", use_container_width=True):
      if k_adi and k_sifre:
        st.session_state.authenticated = True
        st.session_state.kullanici = k_adi
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
  st.stop()

# -------------------------------------------------------------
# 3. VERİTABANI (STATE)
# -------------------------------------------------------------
if "urunler_db" not in st.session_state:
  st.session_state.urunler_db = pd.DataFrame([
      {
          "id": 1,
          "gorsel": (
              "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=300"
          ),
          "barkod": "8680001122331",
          "urun_adi": "Kablosuz Hızlı Şarj Cihazı 15W",
          "kategori": "Elektronik",
          "alis_fiyati": 250.0,
          "satis_fiyati": 396.75,
          "stok": 142,
          "durum": "Aktif",
      },
      {
          "id": 2,
          "gorsel": (
              "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=300"
          ),
          "barkod": "8680001122332",
          "urun_adi": "Bluetooth 5.0 Kulaklık",
          "kategori": "Elektronik",
          "alis_fiyati": 600.0,
          "satis_fiyati": 952.20,
          "stok": 85,
          "durum": "Aktif",
      },
      {
          "id": 3,
          "gorsel": (
              "https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=300"
          ),
          "barkod": "8680001122333",
          "urun_adi": "Ortopedik Spor Ayakkabı",
          "kategori": "Spor",
          "alis_fiyati": 450.0,
          "satis_fiyati": 714.15,
          "stok": 12,
          "durum": "Aktif",
      },
  ])

if "siparisler_db" not in st.session_state:
  st.session_state.siparisler_db = pd.DataFrame([
      {
          "siparis_no": "SAH-9011",
          "kanal": "E-Ticaret Siteniz (Vitrin)",
          "musteri": "Mehmet Demir",
          "urun": "Kablosuz Hızlı Şarj",
          "tutar": "396.75 TL",
          "durum": "Onaylandı",
      },
      {
          "siparis_no": "TRD-4482",
          "kanal": "Trendyol",
          "musteri": "Ayşe Kaya",
          "urun": "Bluetooth Kulaklık",
          "tutar": "952.20 TL",
          "durum": "Kargolandı",
      },
  ])

# -------------------------------------------------------------
# 4. ÜST HEADER
# -------------------------------------------------------------
ust1, ust2 = st.columns([3, 2])
with ust1:
  st.markdown(
      "<span style='font-size: 16px; font-weight: 800; color:"
      " #0f172a;'>👑 ŞAH TİCİMAX & ENTEGRE - E-Ticaret Altyapısı</span>",
      unsafe_allow_html=True,
  )
with ust2:
  profil_islem = st.selectbox(
      "Profil",
      [
          f"👤 {st.session_state.get('kullanici', 'Admin')} (Yönetici)",
          "🚪 Çıkış Yap",
      ],
      label_visibility="collapsed",
  )

st.markdown("---")
if profil_islem == "🚪 Çıkış Yap":
  st.session_state.authenticated = False
  st.rerun()

# -------------------------------------------------------------
# 5. SOL MENÜ
# -------------------------------------------------------------
st.sidebar.markdown(
    """
    <div style="text-align: center; padding: 10px 0; margin-bottom: 10px;">
        <span style="font-size: 24px; font-weight: 900; color: #f27a1a;">ŞAH</span>
        <span style="font-size: 18px; font-weight: 700; color: #0f172a;">TİCİMAX</span>
        <div style="font-size: 11px; color: #64748b; margin-top: 2px;">B2C Vitrin + Entegratör</div>
    </div>
""",
    unsafe_allow_html=True,
)

menu = st.sidebar.selectbox(
    "Yönetim Paneli",
    [
        "🌐 E-Ticaret Sitem (Müşteri Vitrini)",
        "🛒 Sepetim ve Siparişi Tamamla",
        "🏠 Yönetim & Özet Paneli",
        "📦 Ürün ve Stok Yönetimi",
        "🔗 Pazaryeri Entegrasyonları (Trendyol/HBS)",
        "⚙️ Fiyat & Komisyon Motoru",
        "📜 Sistem Logları",
    ],
)

# -------------------------------------------------------------
# SAYFALAR
# -------------------------------------------------------------

if menu == "🌐 E-Ticaret Sitem (Müşteri Vitrini)":
  st.subheader("🌐 E-Ticaret Altyapı Vitrininiz (Müşteri Ön Yüzü)")
  st.markdown(
      "Müşterilerinizin sitenize girip doğrudan inceleyip sepetine ekleyebileceği"
      " ana sayfa vitrini:"
  )

  cols = st.columns(3)
  for idx, row in st.session_state.urunler_db.iterrows():
    with cols[idx % 3]:
      st.markdown(
          f"""
                <div class="product-card">
                    <img src="{row['gorsel']}" style="width:100%; height:140px; object-fit:cover; border-radius:8px;">
                    <div style="font-weight:700; font-size:14px; margin-top:10px; color:#1e293b;">{row['urun_adi']}</div>
                    <div style="font-size:12px; color:#64748b;">Stok: {row['stok']} Adet</div>
                    <div class="price-tag">{row['satis_fiyati']} ₺</div>
                </div>
            """,
            unsafe_allow_html=True,
      )
      if st.button(f"Sepete Ekle #{row['id']}", key=f"sepet_{row['id']}"):
        st.session_state.sepet.append(row.to_dict())
        st.success(f"'{row['urun_adi']}' sepete eklendi!")

elif menu == "🛒 Sepetim ve Siparişi Tamamla":
  st.subheader("🛒 Alışveriş Sepeti ve Ödeme Ekranı")
  if len(st.session_state.sepet) == 0:
    st.info("Sepetinizde henüz ürün bulunmuyor. Vitrinden ürün ekleyebilirsiniz.")
  else:
    sepet_df = pd.DataFrame(st.session_state.sepet)
    st.dataframe(
        sepet_df[["urun_adi", "satis_fiyati", "stok"]],
        use_container_width=True,
        hide_index=True,
    )
    toplam_tutar = sepet_df["satis_fiyati"].sum()
    st.markdown(
        f"### **Toplam Tutar: {toplam_tutar:.2f} TL**"
    )

    m_ad = st.text_input("Ad Soyad", value="Ahmet Yılmaz")
    m_tel = st.text_input("Telefon Numarası", value="0532 000 00 00")
    m_adres = st.text_area(
        "Teslimat Adresi", value="Atatürk Mah. Cumhuriyet Cad. No:10 İzmir"
    )

    if st.button("Siparişi Onayla ve Tamamla", use_container_width=True):
      yeni_sip = {
          "siparis_no": f"SAH-{int(time.time()) % 10000}",
          "kanal": "E-Ticaret Siteniz (Vitrin)",
          "musteri": m_ad,
          "urun": sepet_df["urun_adi"].iloc[0],
          "tutar": f"{toplam_tutar:.2f} TL",
          "durum": "Yeni Sipariş",
      }
      st.session_state.siparisler_db = pd.concat(
          [
              st.session_state.siparisler_db,
              pd.DataFrame([yeni_sip]),
          ],
          ignore_index=True,
      )
      st.session_state.sepet = []
      st.success(
          "Siparişiniz başarıyla alındı! Otomatik olarak yönetim paneline ve"
          " muhasebeye aktarıldı."
      )

elif menu == "🏠 Yönetim & Özet Paneli":
  st.subheader("🏠 Operasyonel Kontrol Merkezi")
  st.markdown(
      """
        <div class="panel-box">
            <div class="panel-header">📊 Ticimax & Entegre Altyapı Özeti</div>
            <table style="width:100%; font-size:13px; color:#1e293b; border-collapse:collapse;">
                <tr><td style="padding:6px; font-weight:600; width:220px;">E-Ticaret Vitrin Durumu:</td><td>Aktif (B2C Satışa Açık)</td></tr>
                <tr><td style="padding:6px; font-weight:600;">Pazaryeri Entegrasyonu:</td><td>Trendyol, Hepsiburada, N11 Bağlı</td></tr>
                <tr><td style="padding:6px; font-weight:600;">Toplam Sipariş Adedi:</td><td>{sip_sayisi} Adet</td></tr>
            </table>
        </div>
    """.format(
          sip_sayisi=len(st.session_state.siparisler_db)
      ),
      unsafe_allow_html=True,
  )
  st.dataframe(
      st.session_state.siparisler_db,
      use_container_width=True,
      hide_index=True,
  )

elif menu == "📦 Ürün ve Stok Yönetimi":
  st.subheader("📦 Ürün ve Barkod Havuzu")
  with st.expander("➕ Yeni Ürün Ekle", expanded=False):
    c1, c2 = st.columns(2)
    with c1:
      p_ad = st.text_input("Ürün Adı")
      p_barkod = st.text_input("Barkod")
      p_kat = st.selectbox("Kategori", ["Elektronik", "Spor", "Ev & Yaşam"])
    with c2:
      p_alis = st.number_input("Alış Fiyatı (TL)", value=100.0)
      p_stok = st.number_input("Stok", value=50)
      p_gorsel = st.text_input(
          "Görsel URL",
          value="https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=300",
      )

    if st.button("Ürünü Vitrine ve Pazaryerlerine Ekle"):
      if p_ad and p_barkod:
        yeni_satis = round(p_alis * 1.4, 2)
        yeni_p = {
            "id": len(st.session_state.urunler_db) + 1,
            "gorsel": p_gorsel,
            "barkod": p_barkod,
            "urun_adi": p_ad,
            "kategori": p_kat,
            "alis_fiyati": p_alis,
            "satis_fiyati": yeni_satis,
            "stok": p_stok,
            "durum": "Aktif",
        }
        st.session_state.urunler_db = pd.concat(
            [
                st.session_state.urunler_db,
                pd.DataFrame([yeni_p]),
            ],
            ignore_index=True,
        )
        st.success(
            "Ürün hem e-ticaret sitenize hem de pazaryerlerine eklendi!"
        )
        st.rerun()

  st.dataframe(
      st.session_state.urunler_db,
      column_config={
          "gorsel": st.column_config.ImageColumn("Görsel", width=70)
      },
      use_container_width=True,
      hide_index=True,
  )

elif menu == "🔗 Pazaryeri Entegrasyonları (Trendyol/HBS)":
  st.subheader("🔗 Çoklu Pazaryeri ve Stok Senkronizasyonu")
  pazar = st.selectbox(
      "Seçilen Pazaryeri", ["Trendyol", "Hepsiburada", "N11", "ÇiçekSepeti"]
  )
  if st.button(
      f"🔄 Tüm Ürünleri {pazar} ile Eşitle", use_container_width=True
  ):
    with st.spinner(f"{pazar} API havuzuyla senkronize ediliyor..."):
      time.sleep(1.2)
    st.success(f"Tüm stok ve fiyatlar {pazar} mağazanıza güncellendi!")

  st.dataframe(
      st.session_state.urunler_db[["barkod", "urun_adi", "satis_fiyati", "stok"]],
      use_container_width=True,
      hide_index=True,
  )

elif menu == "⚙️ Fiyat & Komisyon Motoru":
  st.subheader("⚙️ Otomatik Fiyatlandırma")
  k_marj = st.number_input("Kâr Oranı (%)", value=30.0)
  if st.button("Fiyatları Güncelle"):
    st.session_state.urunler_db["satis_fiyati"] = st.session_state.urunler_db[
        "alis_fiyati"
    ].apply(lambda x: round(x * (1 + k_marj / 100), 2))
    st.success("Tüm fiyatlar güncellendi!")

elif menu == "📜 Sistem Logları":
  st.subheader("📜 Sistem ve API Logları")
  st.code(
      f"[{time.strftime('%H:%M:%S')}] Ticimax B2C vitrin altyapısı aktif.\n[{time.strftime('%H:%M:%S')}] Trendyol stok senkronizasyonu başarılı.",
      language="text",
  )
