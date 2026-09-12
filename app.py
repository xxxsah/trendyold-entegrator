import random
import time
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Şah Platform - Ticimax, Entegra & Nesine Modülü",
    page_icon="👑",
    layout="wide",
)

# -------------------------------------------------------------
# 1. CSS & ARAYÜZ TASARIMI
# -------------------------------------------------------------
st.markdown(
    """
    <style>
    .stApp { background-color: #f8fafc; }
    .product-card { background: white; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.05); margin-bottom: 15px; }
    .match-card { background: white; border: 1px solid #e2e8f0; border-radius: 10px; padding: 15px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
    .price-tag { font-size: 16px; font-weight: 800; color: #0284c7; margin: 8px 0; }
    </style>
""",
    unsafe_allow_html=True,
)

# -------------------------------------------------------------
# 2. OTURUM VE STATE YÖNETİMİ
# -------------------------------------------------------------
if "authenticated" not in st.session_state:
  st.session_state.authenticated = False
if "sepet" not in st.session_state:
  st.session_state.sepet = []
if "bakiye" not in st.session_state:
  st.session_state.bakiye = 1000.0
if "aktif_kupon" not in st.session_state:
  st.session_state.aktif_kupon = []

if not st.session_state.authenticated:
  st.markdown(
      "<h2 style='text-align: center; color: #1e293b;'>⚡ ŞAH PLATFORM -"
      " Merkezi Yönetim Girişi</h2>",
      unsafe_allow_html=True,
  )
  c1, c2, c3 = st.columns([1, 2, 1])
  with c2:
    st.markdown(
        "<div"
        " style='background:white; padding:30px; border-radius:10px;"
        " border:1px solid #e2e8f0;'>",
        unsafe_allow_html=True,
    )
    k_adi = st.text_input("Kullanıcı Adı", value="admin")
    k_sifre = st.text_input("Şifre", type="password", value="123456")
    if st.button("Sisteme Giriş Yap", use_container_width=True):
      if k_adi and k_sifre:
        st.session_state.authenticated = True
        st.session_state.kullanici = k_adi
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
  st.stop()

# -------------------------------------------------------------
# 3. VERİTABANI BAŞLANGIÇ VERİLERİ
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
      },
  ])

if "bulten_db" not in st.session_state:
  st.session_state.bulten_db = [
      {
          "id": 101,
          "lig": "Trendyol Süper Lig",
          "mac": "Galatasaray - Fenerbahçe",
          "ms1": 2.10,
          "ms0": 3.20,
          "ms2": 2.80,
      },
      {
          "id": 102,
          "lig": "Premier League",
          "mac": "Arsenal - Manchester City",
          "ms1": 2.45,
          "ms0": 3.10,
          "ms2": 2.40,
      },
      {
          "id": 103,
          "lig": "La Liga",
          "mac": "Real Madrid - Barcelona",
          "ms1": 2.25,
          "ms0": 3.30,
          "ms2": 2.60,
      },
  ]

if "kupon_gecmisi" not in st.session_state:
  st.session_state.kupon_gecmisi = []

# -------------------------------------------------------------
# 4. ÜST HEADER VE MENÜ
# -------------------------------------------------------------
ust1, ust2 = st.columns([3, 2])
with ust1:
  st.markdown(
      "<span style='font-size: 16px; font-weight: 800; color:"
      " #0f172a;'>👑 ŞAH PLATFORM - E-Ticaret & İddaa Modülü</span>",
      unsafe_allow_html=True,
  )
with ust2:
  profil_islem = st.selectbox(
      "Profil",
      [
          f"👤 {st.session_state.get('kullanici', 'Admin')} (Bakiye:"
          f" {st.session_state.bakiye:.2f} ₺)",
          "🚪 Çıkış Yap",
      ],
      label_visibility="collapsed",
  )

st.markdown("---")
if profil_islem == "🚪 Çıkış Yap":
  st.session_state.authenticated = False
  st.rerun()

menu = st.sidebar.selectbox(
    "Ana Menü",
    [
        "🌐 E-Ticaret Vitrini (Ticimax)",
        "🛒 Sepetim",
        "⚽ Nesine / İddaa Bülteni",
        "🎫 Kuponlarım & Kasa",
        "📦 Pazaryeri Entegrasyonları",
        "🏠 Yönetim Paneli",
    ],
)

# -------------------------------------------------------------
# 5. SAYFA İÇERİKLERİ
# -------------------------------------------------------------

if menu == "🌐 E-Ticaret Vitrini (Ticimax)":
  st.subheader("🌐 E-Ticaret Müşteri Vitrini")
  cols = st.columns(2)
  for idx, row in st.session_state.urunler_db.iterrows():
    with cols[idx % 2]:
      st.markdown(
          f"""
                <div class="product-card">
                    <img src="{row['gorsel']}" style="width:100%; height:120px; object-fit:cover; border-radius:6px;">
                    <div style="font-weight:700; margin-top:8px;">{row['urun_adi']}</div>
                    <div class="price-tag">{row['satis_fiyati']} ₺</div>
                </div>
            """,
          unsafe_allow_html=True,
      )
      if st.button(f"Sepete Ekle #{row['id']}", key=f"vitrin_{row['id']}"):
        st.session_state.sepet.append(row.to_dict())
        st.success("Ürün sepete eklendi!")

elif menu == "🛒 Sepetim":
  st.subheader("🛒 Alışveriş Sepeti")
  if not st.session_state.sepet:
    st.info("Sepetiniz boş.")
  else:
    sdf = pd.DataFrame(st.session_state.sepet)
    st.dataframe(
        sdf[["urun_adi", "satis_fiyati"]],
        use_container_width=True,
        hide_index=True,
    )
    tutar = sdf["satis_fiyati"].sum()
    st.markdown(f"**Toplam Tutar: {tutar:.2f} TL**")
    if st.button("Siparişi Tamamla"):
      st.session_state.sepet = []
      st.success("Sipariş başarıyla oluşturuldu!")

elif menu == "⚽ Nesine / İddaa Bülteni":
  st.subheader("⚽ Nesine / İddaa Canlı Maç Bülteni")
  st.markdown(
      f"Mevcut Kasanız / Bakiyeniz: **{st.session_state.bakiye:.2f} ₺**"
  )

  for mac in st.session_state.bulten_db:
    st.markdown(
        f"""
            <div class="match-card">
                <div style="font-size:12px; color:#64748b; font-weight:600;">{mac['lig']}</div>
                <div style="font-size:16px; font-weight:800; color:#1e293b; margin:6px 0;">{mac['mac']}</div>
            </div>
        """,
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns(3)
    with c1:
      if st.button(
          f"MS 1 ({mac['ms1']})", key=f"ms1_{mac['id']}", use_container_width=True
      ):
        st.session_state.aktif_kupon.append({
            "mac": mac["mac"],
            "secim": "MS 1",
            "oran": mac["ms1"],
        })
        st.toast(f"Eklendi: {mac['mac']} (MS 1)")
    with c2:
      if st.button(
          f"MS 0 ({mac['ms0']})", key=f"ms0_{mac['id']}", use_container_width=True
      ):
        st.session_state.aktif_kupon.append({
            "mac": mac["mac"],
            "secim": "MS 0",
            "oran": mac["ms0"],
        })
        st.toast(f"Eklendi: {mac['mac']} (MS 0)")
    with c3:
      if st.button(
          f"MS 2 ({mac['ms2']})", key=f"ms2_{mac['id']}", use_container_width=True
      ):
        st.session_state.aktif_kupon.append({
            "mac": mac["mac"],
            "secim": "MS 2",
            "oran": mac["ms2"],
        })
        st.toast(f"Eklendi: {mac['mac']} (MS 2)")

elif menu == "🎫 Kuponlarım & Kasa":
  st.subheader("🎫 Hazırlanan Kupon ve Kasa Yönetimi")
  if not st.session_state.aktif_kupon:
    st.info(
        "Kuponunuzda maç bulunmuyor. İddaa bülteninden oran seçebilirsiniz."
    )
  else:
    kdf = pd.DataFrame(st.session_state.aktif_kupon)
    st.dataframe(kdf, use_container_width=True, hide_index=True)
    toplam_oran = kdf["oran"].prod()
    st.markdown(f"### **Toplam Oran: {toplam_oran:.2f}**")

    misli = st.number_input("Misli / Yatırılacak Tutar (TL)", value=50.0)
    olasi_ikramiye = misli * toplam_oran
    st.markdown(f"**Olası İkramiye: {olasi_ikramiye:.2f} TL**")

    col_b1, col_b2 = st.columns(2)
    with col_b1:
      if st.button("Kuponu Oyna (Kasadan Düş)", use_container_width=True):
        if st.session_state.bakiye >= misli:
          st.session_state.bakiye -= misli
          st.session_state.kupon_gecmisi.append({
              "adet": len(kdf),
              "oran": round(toplam_oran, 2),
              "misli": misli,
              "ikramiye": round(olasi_ikramiye, 2),
              "durum": "Tuttu 🎉" if random.random() > 0.4 else "Yattı ❌",
          })
          st.session_state.aktif_kupon = []
          st.success("Kupon başarıyla oynandı!")
          st.rerun()
        else:
          st.error("Yetersiz bakiye!")
    with col_b2:
      if st.button("Kuponu Temizle", use_container_width=True):
        st.session_state.aktif_kupon = []
        st.rerun()

  st.markdown("---")
  st.subheader("📜 Oynanan Kupon Geçmişi")
  if st.session_state.kupon_gecmisi:
    st.dataframe(
        pd.DataFrame(st.session_state.kupon_gecmisi),
        use_container_width=True,
        hide_index=True,
    )
  else:
    st.info("Henüz geçmiş kuponunuz bulunmuyor.")

elif menu == "📦 Pazaryeri Entegrasyonları":
  st.subheader("📦 Trendyol & Hepsiburada Entegrasyonu")
  if st.button("🔄 Stok ve Fiyatları Eşitle"):
    time.sleep(1)
    st.success("Tüm pazaryerleri güncellendi!")
  st.dataframe(
      st.session_state.urunler_db,
      use_container_width=True,
      hide_index=True,
  )

elif menu == "🏠 Yönetim Paneli":
  st.subheader("🏠 Sistem Özeti")
  st.markdown(
      f"Aktif Bakiye: **{st.session_state.bakiye:.2f} ₺** | Sepet Ürün Sayısı:"
      f" **{len(st.session_state.sepet)}**"
  )
