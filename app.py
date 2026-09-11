import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Şah Entegre - MetEntegre Yönetim Paneli",
    page_icon="👑",
    layout="wide",
)

# MetEntegre Standardında Profesyonel CSS Tasarımı
st.markdown(
    """
    <style>
    .stApp { background-color: #f1f5f9; }
    
    /* Pazaryeri Üst Grid Kartları */
    .mp-grid { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
    .mp-card { flex: 1; min-width: 120px; background: white; border: 1px solid #cbd5e1; border-radius: 6px; padding: 10px; text-align: center; box-shadow: 0 1px 2px rgba(0,0,0,0.02); }
    .mp-badge { font-size: 10px; font-weight: 700; padding: 3px 6px; border-radius: 4px; color: white; display: inline-block; margin-bottom: 5px; }
    
    /* Fatura ve Abonelik Konteynerleri */
    .box-container { background: white; border: 1px solid #cbd5e1; border-radius: 8px; padding: 15px; margin-bottom: 15px; box-shadow: 0 1px 3px rgba(0,0,0,0.03); }
    .box-header { background: #1e3a8a; color: white; padding: 8px 12px; font-weight: 700; font-size: 13px; border-radius: 4px; margin-bottom: 10px; text-align: center; }
    
    /* Trendyol Özel Panel Kutuları */
    .action-box { background: white; border: 1px solid #cbd5e1; border-radius: 6px; padding: 12px; margin-bottom: 10px; }
    .action-title { font-size: 12px; font-weight: 700; color: #1e293b; margin-bottom: 8px; display: flex; align-items: center; gap: 5px; }
    </style>
""",
    unsafe_allow_html=True,
)

# -------------------------------------------------------------
# GİRİŞ YAPAN KULLANICI BİLGİSİ
# -------------------------------------------------------------
aktif_kullanici = "Şahin Yiğit"

# -------------------------------------------------------------
# ÜST HEADER VE SAĞ PROFİL MENÜSÜ
# -------------------------------------------------------------
col_h1, col_h2 = st.columns([4, 2])
with col_h1:
  st.markdown(
      f"<span style='font-size: 14px; font-weight: 700; color:"
      f" #1e293b;'>👑 {aktif_kullanici} - MetEntegre Yönetim Paneli</span>",
      unsafe_allow_html=True,
  )
with col_h2:
  profil_secenekleri = [
      f"👤 {aktif_kullanici} (Profil)",
      "⚙️ Hesap Ayarları",
      "🔔 Bildirim İzinleri",
      "📄 Sözleşmeler",
      "📁 Belgelerim",
      "💳 Ödemelerim - Faturalarım",
      "🚪 Çıkış Yap",
  ]
  secilen_profil = st.selectbox(
      "Profil", profil_secenekleri, label_visibility="collapsed"
  )

st.markdown("---")

# Sol Menü
st.sidebar.markdown(
    f"""
    <div style="text-align: center; padding: 10px 0; margin-bottom: 10px;">
        <span style="font-size: 26px; font-weight: 800; color: #f27a1a;">MET</span>
        <span style="font-size: 15px; font-weight: 600; color: #0f172a;">ENTEGRE</span>
        <div style="font-size: 10px; color: #64748b; margin-top: 2px;">👑 {aktif_kullanici} Panel</div>
    </div>
""",
    unsafe_allow_html=True,
)

menu_options = [
    "🏠 Anasayfa",
    "🎧 Destek Taleplerim",
    "🔔 Bildirimler",
    "📢 Duyurular",
    "📦 Sistemdeki Ürünler",
    "⚡ Oto Kritik Stok",
    "🧡 Trendyol",
    "🌸 ÇiçekSepeti",
    "💜 N11",
    "💛 E-PTT AVM",
    "🧡 Hepsiburada",
    "🛒 Pazaryeri",
    "💙 İdefix",
    "⚙️ Ayarlar",
]

selected_menu = st.sidebar.selectbox("Yönetim Paneli", menu_options)

# -------------------------------------------------------------
# SAĞ PROFİL MENÜSÜ SAYFALARI
# -------------------------------------------------------------
if secilen_profil == "⚙️ Hesap Ayarları":
  st.subheader("⚙️ Hesap Ayarları")
  st.text_input("Ad Soyad", value=aktif_kullanici)
  st.text_input("E-posta Adresi", value="sah1357sah@gmail.com")
  st.text_input("Telefon Numarası", value="05346944235")
  if st.button("Bilgileri Kaydet"):
    st.success("Hesap ayarlarınız başarıyla güncellendi!")

elif secilen_profil == "🔔 Bildirim İzinleri":
  st.subheader("🔔 Bildirim İzinleri ve Tercihleri")
  st.checkbox("E-posta Bildirimleri Aktif", value=True)
  st.checkbox("SMS Bilgilendirmeleri Aktif", value=True)
  st.checkbox("Pazaryeri Kritik Stok Uyarıları", value=True)

elif secilen_profil == "📄 Sözleşmeler":
  st.subheader("📄 Kullanıcı Sözleşmeleri")
  st.info("Hizmet Sözleşmesi ve KVKK metinleri onaylanmıştır.")

elif secilen_profil == "📁 Belgelerim":
  st.subheader("📁 Mağaza Belgelerim")
  st.success("✔ Vergi Levhası Doğrulandı (9800650692)")

elif secilen_profil == "💳 Ödemelerim - Faturalarım":
  st.subheader("💳 Ödemelerim ve Geçmiş Faturalarım")
  fatura_data = pd.DataFrame([{
      "Sipariş ID": "SAH707418640181936",
      "Hizmet": "MetEntegre Pro Abonelik",
      "Tutar": "0,00 ₺",
      "Tarih": "27.08.2026",
      "Durum": "Ödendi / Aktif",
  }])
  st.dataframe(fatura_data, use_container_width=True, hide_index=True)

elif secilen_profil == "🚪 Çıkış Yap":
  st.warning("Oturum kapatılıyor...")

# -------------------------------------------------------------
# 1. ANASAYFA
# -------------------------------------------------------------
elif selected_menu == "🏠 Anasayfa":
  st.subheader(f"👑 {aktif_kullanici} - Ana Kontrol Paneli")

  st.markdown(
      """
        <div class="mp-grid">
            <div class="mp-card"><div class="mp-badge" style="background:#ff6600;">HEPSİBURADA</div><div style="font-size:11px; color:#64748b;">Siparişiniz</div><div style="font-size:12px; font-weight:700; color:#dc2626;">Sipariş yok</div></div>
            <div class="mp-card"><div class="mp-badge" style="background:#f27a1a;">TRENDYOL</div><div style="font-size:11px; color:#64748b;">Siparişiniz</div><div style="font-size:12px; font-weight:700; color:#dc2626;">Sipariş yok</div></div>
            <div class="mp-card"><div class="mp-badge" style="background:#e6005c;">ÇİÇEKSEPETİ</div><div style="font-size:11px; color:#64748b;">Siparişiniz</div><div style="font-size:12px; font-weight:700; color:#dc2626;">Sipariş yok</div></div>
            <div class="mp-card"><div class="mp-badge" style="background:#334155;">PTT AVM</div><div style="font-size:11px; color:#64748b;">Siparişiniz</div><div style="font-size:12px; font-weight:700; color:#dc2626;">Sipariş yok</div></div>
            <div class="mp-card"><div class="mp-badge" style="background:#6b46c1;">N11</div><div style="font-size:11px; color:#64748b;">Siparişiniz</div><div style="font-size:12px; font-weight:700; color:#dc2626;">Sipariş yok</div></div>
            <div class="mp-card"><div class="mp-badge" style="background:#0284c7;">PAZARAMA</div><div style="font-size:11px; color:#64748b; margin-top:5px; font-weight:700; color:#0f172a;">🚀 Çok yakında</div></div>
            <div class="mp-card"><div class="mp-badge" style="background:#059669;">İDEFİX</div><div style="font-size:11px; color:#64748b; margin-top:5px; font-weight:700; color:#0f172a;">🚀 Çok yakında</div></div>
        </div>
    """,
      unsafe_allow_html=True,
  )

  st.markdown(
      f"""
        <div class="box-container">
            <div class="box-header">👤 Fatura Bilgileri</div>
            <table style="width:100%; font-size:13px; color:#1e293b; border-collapse:collapse;">
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:600; width:150px;">İsim:</td><td style="padding:6px;">{aktif_kullanici}</td></tr>
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:600;">Email:</td><td style="padding:6px;">sah1357sah@gmail.com</td></tr>
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:600;">Telefon:</td><td style="padding:6px;">05346944235</td></tr>
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:600;">Vergi Numarası:</td><td style="padding:6px;">9800650692</td></tr>
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:600;">Vergi Dairesi:</td><td style="padding:6px;">Kadifekale</td></tr>
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:600;">TC Kimlik No:</td><td style="padding:6px;">34510406564</td></tr>
                <tr><td style="padding:6px; font-weight:600;">Adres:</td><td style="padding:6px;">Sevgi mah. 4642 sok no 4/1 Karabağlar İzmir</td></tr>
            </table>
        </div>
    """,
      unsafe_allow_html=True,
  )

  st.markdown(
      """
        <div class="box-container">
            <div class="box-header">📦 Abonelik Bilgileri</div>
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div style="font-size:13px; color:#1e293b;">
                    <b>Sipariş ID:</b> SAH707418640181936<br>
                    <b>Tutar:</b> 0₺<br>
                    <b>Son Tarih:</b> 27.11.2026<br>
                    <b>Durum:</b> <span style="color:#16a34a; font-weight:700;">Aktif</span>
                </div>
                <div style="text-align:center; background:#f8fafc; border:2px solid #0284c7; border-radius:50%; width:70px; height:70px; display:flex; flex-direction:column; justify-content:center; align-items:center;">
                    <span style="font-size:18px; font-weight:800; color:#0284c7;">77</span>
                    <span style="font-size:9px; font-weight:600; color:#64748b;">GÜN KALDI</span>
                </div>
            </div>
        </div>
    """,
      unsafe_allow_html=True,
  )

  col1, col2 = st.columns(2)
  with col1:
    st.info("🧡 **Trendyol**\n\nMağazanıza yüklenebilir ürün adedi:\n### 21.203")
    st.info("💜 **N11**\n\nMağazanıza yüklenebilir ürün adedi:\n### 33.622")
    st.info("💛 **EPtt AVM**\n\nMağazanıza yüklenebilir ürün adedi:\n### 38.894")
  with col2:
    st.info("🌸 **Çiçeksepeti**\n\nMağazanıza yüklenebilir ürün adedi:\n### 32.020")
    st.info("🧡 **Hepsiburada**\n\nMağazanıza yüklenebilir ürün adedi:\n### 42.323")

# -------------------------------------------------------------
# 🧡 TRENDYOL ÜRÜNLERİM (Görseldeki Birebir Sayfa)
# -------------------------------------------------------------
elif selected_menu == "🧡 Trendyol":
  st.subheader("🧡 Trendyol Ürünlerim")

  # Üst Uyarı
  st.warning("⚠️ Önemli Bilgilendirme: Ürün senkronizasyonları aktif durumdadır.")

  # İşlem Panelleri (Arşivleme, Silme, Veri Yönetimi)
  col_a, col_b, col_c = st.columns(3)

  with col_a:
    st.markdown(
        """<div class="action-box"><div class="action-title">📂 Arşivleme"
        " İşlemleri</div></div>""",
        unsafe_allow_html=True,
    )
    b1, b2 = st.columns(2)
    with b1:
      if st.button("Tümünü Arşivle", use_container_width=True):
        st.toast("Tüm ürünler arşive taşındı.")
      if st.button("Satıştaki Arşivle", use_container_width=True):
        st.toast("Satıştaki ürünler arşive taşındı.")
    with b2:
      if st.button("Kapatılan Arşivle", use_container_width=True):
        st.toast("Kapatılan ürünler arşive taşındı.")
      if st.button("Stok 0 Arşivle", use_container_width=True):
        st.toast("Stoku 0 olanlar arşive taşındı.")

  with col_b:
    st.markdown(
        """<div class="action-box"><div class="action-title">🗑️ Silme"
        " İşlemleri</div></div>""",
        unsafe_allow_html=True,
    )
    if st.button("Onay Sürecini Sil", use_container_width=True):
      st.toast("Onay sürecindeki ürünler silindi.")
    if st.button("Arşivledikleri Sil", use_container_width=True):
      st.toast("Arşivlenen ürünler kalıcı olarak silindi.")

  with col_c:
    st.markdown(
        """<div class="action-box"><div class="action-title">⚡ Veri"
        " Yönetimi</div></div>""",
        unsafe_allow_html=True,
    )
    if st.button("📥 Trendyol'dan Çek", use_container_width=True):
      st.success("Trendyol'dan ürünler başarıyla çekildi!")
    if st.button("🔄 Listeyi Yenile", use_container_width=True):
      st.toast("Ürün listesi yenilendi.")

  st.markdown("---")

  # Ürün Listesi Başlığı ve Güncelle Butonu
  col_u1, col_u2 = st.columns([3, 1])
  with col_u1:
    st.markdown("📋 **Ürün Listesi** (Toplam: 6553 / 6553)")
  with col_u2:
    if st.button("🚀 TRENDYOL ÜRÜNLERİMİ GÜNCELLE"):
      st.success("Trendyol ürünleri toplu olarak güncellendi!")

  # Arama Çubuğu
  arama_terimi = st.text_input(
      "Ara", placeholder="🔍 Ürün adı, barkod veya model kodu ara..."
  )

  # Filtre Butonları (Görseldeki Renkli Filtre Alanı)
  st.markdown(
      """
        <div style="background:#f8fafc; padding:10px; border-radius:6px; border:1px solid #cbd5e1; margin-bottom:15px; font-size:12px; font-weight:600; color:#475569;">
            FİLTRELE: &nbsp; 
            <span style="background:#0f172a; color:white; padding:3px 8px; border-radius:4px; margin-right:4px;">Tümü (6553)</span>
            <span style="background:#16a34a; color:white; padding:3px 8px; border-radius:4px; margin-right:4px;">Satışta</span>
            <span style="background:#ea580c; color:white; padding:3px 8px; border-radius:4px; margin-right:4px;">Eşleşmeyenler</span>
            <span style="background:#0284c7; color:white; padding:3px 8px; border-radius:4px; margin-right:4px;">Satışa Kapalı</span>
            <span style="background:#64748b; color:white; padding:3px 8px; border-radius:4px; margin-right:4px;">Arşivde</span>
            <span style="background:#2563eb; color:white; padding:3px 8px; border-radius:4px; margin-right:4px;">Onaylı</span>
            <span style="background:#ca8a04; color:white; padding:3px 8px; border-radius:4px; margin-right:4px;">Onay Bekliyor</span>
            <span style="background:#dc2626; color:white; padding:3px 8px; border-radius:4px; margin-right:4px;">Reddedilen</span>
            <span style="background:#334155; color:white; padding:3px 8px; border-radius:4px; margin-right:4px;">Blacklist</span>
            <span style="background:#7c3aed; color:white; padding:3px 8px; border-radius:4px;">Kilitli</span>
        </div>
    """,
      unsafe_allow_html=True,
  )

  # Gerçekçi Trendyol Ürün Veri Tablosu
  urunler_data = [
      {
          "Resim": "📦",
          "Barkod": "CYRO-679931-LXL",
          "Ürün Adı": "Siyah Dantelli Sabahlık &amp; Gecelik Takımı",
          "Satış Fiyatı": "726 TL",
          "Trendyol Stok": 98,
          "M.Entegre Stok": 0,
          "Durum": "Onaylı / Satışta",
      },
      {
          "Resim": "📦",
          "Barkod": "CYRO-679931-SM",
          "Ürün Adı": "Siyah Dantelli Sabahlık &amp; Gecelik Takımı",
          "Satış Fiyatı": "726 TL",
          "Trendyol Stok": 100,
          "M.Entegre Stok": 0,
          "Durum": "Onaylı / Satışta",
      },
      {
          "Resim": "📦",
          "Barkod": "606214114000007",
          "Ürün Adı": "Ayarlanabilir Dizüstü Destek Tabanı Tam Boy",
          "Satış Fiyatı": "629.7 TL",
          "Trendyol Stok": 27,
          "M.Entegre Stok": 0,
          "Durum": "Onaylı / Satışta",
      },
      {
          "Resim": "📦",
          "Barkod": "606903317053779400007",
          "Ürün Adı": "TONTON - NO:1 ÇEKMECE 3 KATLI 21.5...",
          "Satış Fiyatı": "583.31 TL",
          "Trendyol Stok": 44,
          "M.Entegre Stok": 0,
          "Durum": "Onaylı / Satışta",
      },
      {
          "Resim": "📦",
          "Barkod": "606905115554563300007",
          "Ürün Adı": "MARS 28 BÖLMELİ ORGANİZER BOX",
          "Satış Fiyatı": "476.4 TL",
          "Trendyol Stok": 76,
          "M.Entegre Stok": 0,
          "Durum": "Onaylı / Satışta",
      },
      {
          "Resim": "📦",
          "Barkod": "606909118417096300007",
          "Ürün Adı": "6 RAFLI - GRİ MODÜLER ÜNİTE PLASTİK...",
          "Satış Fiyatı": "1660.54 TL",
          "Trendyol Stok": 13,
          "M.Entegre Stok": 0,
          "Durum": "Onaylı / Satışta",
      },
      {
          "Resim": "📦",
          "Barkod": "60689204013402643700007",
          "Ürün Adı": "Ağaç Şekilli Mücevher Standı",
          "Satış Fiyatı": "176.66 TL",
          "Trendyol Stok": 304,
          "M.Entegre Stok": 0,
          "Durum": "Onaylı / Satışta",
      },
  ]

  df_urunler = pd.DataFrame(urunler_data)

  # Arama filtresi uygulaması
  if arama_terimi:
    df_urunler = df_urunler[
        df_urunler["Ürün Adı"]
        .str.lower()
        .str.contains(arama_terimi.lower())
        | df_urunler["Barkod"]
        .str.lower()
        .str.contains(arama_terimi.lower())
    ]

  st.dataframe(df_urunler, use_container_width=True, hide_index=True)

# -------------------------------------------------------------
# DİĞER SOL MENÜ SEKMELERİ
# -------------------------------------------------------------
elif selected_menu == "🎧 Destek Taleplerim":
  st.subheader("🎧 Destek Taleplerim")
  st.info("Aktif destek talebiniz bulunmamaktadır.")

elif selected_menu == "🔔 Bildirimler":
  st.subheader("🔔 Bildirimler")
  st.success("Tüm sistemler sorunsuz çalışıyor.")

elif selected_menu == "📢 Duyurular":
  st.subheader("📢 Duyurular")
  st.markdown("**EĞİTİM VİDEOLARIMIZ YAYINLANMIŞTIR.** (01.09.2026)")

elif selected_menu == "📦 Sistemdeki Ürünler":
  st.subheader("📦 Sistemdeki Ürün Analizi")
  st.markdown("Sistemdeki 202.046 ürün listeleniyor...")

elif selected_menu == "⚡ Oto Kritik Stok":
  st.subheader("⚡ Oto Kritik Stok")
  st.markdown("Kritik stok seviyesindeki ürünlerin takibi.")

elif selected_menu == "🌸 ÇiçekSepeti":
  st.subheader("🌸 Çiçeksepeti Yönetimi")
  st.markdown("Çiçeksepeti entegrasyon ekranı.")

elif selected_menu == "💜 N11":
  st.subheader("💜 N11 Mağaza Yönetimi")
  st.markdown("N11 entegrasyon ekranı.")

elif selected_menu == "💛 E-PTT AVM":
  st.subheader("💛 E-PTT AVM Yönetimi")
  st.markdown("E-PTT AVM entegrasyon ekranı.")

elif selected_menu == "🧡 Hepsiburada":
  st.subheader("🧡 Hepsiburada Mağaza Yönetimi")
  st.markdown("Hepsiburada entegrasyon ekranı.")

elif selected_menu == "🛒 Pazaryeri":
  st.subheader("🛒 Genel Pazaryeri Yönetimi")
  st.markdown("Toplu pazaryeri yönetim paneli.")

elif selected_menu == "💙 İdefix":
  st.subheader("💙 İdefix Yönetimi")
  st.markdown("İdefix entegrasyon ekranı.")

elif selected_menu == "⚙️ Ayarlar":
  st.subheader("⚙️ Sistem Ayarları")
  st.text_input("Firma Adı", value=f"{aktif_kullanici} E-Ticaret")
