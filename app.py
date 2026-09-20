import datetime
import pandas as pd
import requests
import streamlit as st
import xml.etree.ElementTree as ET

# Sayfa Konfigürasyonu
st.set_page_config(
    page_title="ProEntegre - Profesyonel E-Ticaret Yönetim Merkezi",
    layout="wide",
)

# Üst Başlık ve Durum Çubuğu
st.title("🚀 ProEntegre | Çoklu Pazaryeri & XML Yönetim Sistemi")
st.markdown(
    "Trendyol ve Hepsiburada operasyonlarınızı tek merkezden yönetin."
)
st.markdown("---")

# Session State Başlatma
if "urunler_df" not in st.session_state:
  st.session_state["urunler_df"] = pd.DataFrame()
if "loglar" not in st.session_state:
  st.session_state["loglar"] = []


def log_ekle(mesaj, seviye="INFO"):
  zaman = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
  st.session_state["loglar"].insert(
      0, {"Zaman": zaman, "Seviye": seviye, "Mesaj": mesaj}
  )


# Sekmeler (Tabs) - Profesyonel Panel Mimarisi
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Genel Özet",
    "📦 XML & Ürün Yönetimi",
    "💰 Fiyat & Komisyon Kuralları",
    "🛒 Sipariş Yönetimi",
    "🪵 Sistem Logları",
])

with tab1:
  st.subheader("📈 Anlık İş Operasyonları Özeti")

  col1, col2, col3, col4 = st.columns(4)
  df_mevcut = st.session_state["urunler_df"]
  toplam_urun = len(df_mevcut) if not df_mevcut.empty else 0
  aktif_stok = (
      len(df_mevcut[df_mevcut["Stok"] > 0]) if not df_mevcut.empty else 0
  )

  col1.metric("Toplam Aktif Ürün", toplam_urun)
  col2.metric("Stokta Var", aktif_stok)
  col3.metric("Trendyol Senkron", "Aktif 🟢")
  col4.metric("Hepsiburada Senkron", "Aktif 🟢")

  st.info(
      "💡 İpucu: Ürünlerinizi güncellemek için 'XML & Ürün Yönetimi' sekmesini"
      " kullanabilirsiniz."
  )

with tab2:
  st.subheader("📥 XML Tedarikçi Entegrasyonu ve Ürün Listesi")

  with st.expander("⚙️ XML Bağlantı Ayarları", expanded=True):
    col_a, col_b = st.columns(2)
    with col_a:
      xml_url = st.text_input(
          "XML Feed URL Adresi",
          placeholder="https://tedarikci.com/xml/urunler.xml",
      )
    with col_b:
      xml_tipi = st.selectbox(
          "XML Sağlayıcı Şablonu", ["Standart (Item/Product)", "Özel XML"]
      )

    if st.button("XML Verilerini Senkronize Et", type="primary"):
      if xml_url:
        with st.spinner("XML verileri indiriliyor ve parse ediliyor..."):
          try:
            response = requests.get(xml_url, timeout=20)
            response.raise_for_status()
            root = ET.fromstring(response.content)

            urunler = []
            # Genel arama (item veya product etiketleri)
            for item in root.findall(".//item") + root.findall(".//product"):
              baslik = (
                  item.find("title").text
                  if item.find("title") is not None
                  else (
                      item.find("UrunAdi").text
                      if item.find("UrunAdi") is not None
                      else "İsimsiz"
                  )
              )
              stok_val = (
                  item.find("stock").text
                  if item.find("stock") is not None
                  else (
                      item.find("Stok").text
                      if item.find("Stok") is not None
                      else "0"
                  )
              )
              fiyat_val = (
                  item.find("price").text
                  if item.find("price") is not None
                  else (
                      item.find("Fiyat").text
                      if item.find("Fiyat") is not None
                      else "0"
                  )
              )
              barkod_val = (
                  item.find("barcode").text
                  if item.find("barcode") is not None
                  else (
                      item.find("Barkod").text
                      if item.find("Barkod") is not None
                      else "Yok"
                  )
              )

              # Fiyat temizleme
              fiyat_temiz = (
                  fiyat_val.replace("TL", "")
                  .replace(" ", "")
                  .replace(".", "")
                  .replace(",", ".")
              )
              try:
                alis = float(fiyat_temiz)
              except:
                alis = 0.0

              try:
                stok = int(stok_val)
              except:
                stok = 0

              urunler.append({
                  "Barkod": barkod_val,
                  "Ürün Adı": baslik,
                  "Stok": stok,
                  "Alış Fiyatı (₺)": alis,
              })

            if urunler:
              st.session_state["urunler_df"] = pd.DataFrame(urunler)
              log_ekle(
                  f"Başarıyla {len(urunler)} ürün XML'den çekildi.", "SUCCESS"
              )
              st.success(f"Toplam {len(urunler)} ürün sisteme aktarıldı!")
            else:
              st.warning(
                  "XML içinde uygun ürün etiketi bulunamadı. Yapıyı"
                  " kontrol edin."
              )
          except Exception as e:
            log_ekle(f"XML çekme hatası: {str(e)}", "ERROR")
            st.error(f"Hata oluştu: {e}")
      else:
        st.warning("Lütfen geçerli bir XML URL adresi girin.")

  if not st.session_state["urunler_df"].empty:
    st.markdown("### 📋 Mevcut Ürün Veritabanı")
    arama_terimi = st.text_input("Ürün Havuzunda Ara (Ürün Adı / Barkod)")
    df_goster = st.session_state["urunler_df"]

    if arama_terimi:
      df_goster = df_goster[
          df_goster["Ürün Adı"]
          .str.contains(arama_terimi, case=False, na=False)
          | df_goster["Barkod"]
          .str.contains(arama_terimi, case=False, na=False)
      ]

    st.dataframe(df_goster, use_container_width=True)

with tab3:
  st.subheader("💰 Fiyatlandırma, Kar ve Komisyon Hesaplama")
  st.markdown(
      "Pazaryeri komisyonlarını ve genel kar oranını belirleyerek nihai satış"
      " fiyatlarını otomatik hesaplayın."
  )

  col_f1, col_f2, col_f3 = st.columns(3)
  with col_f1:
    genel_kar = st.number_input("Genel Kar Marjı (%)", value=25.0, step=1.0)
  with col_f2:
    pazaryeri_komisyon = st.number_input(
        "Pazaryeri Ortalama Komisyon (%)", value=15.0, step=1.0
    )
  with col_f3:
    kdv_orani = st.selectbox("KDV Oranı (%)", [1, 10, 20], index=2)

  if (
      not st.session_state["urunler_df"].empty
      and st.button("Fiyatları Otomatik Hesapla ve Güncelle")
  ):
    df_temp = st.session_state["urunler_df"].copy()
    # Basit profesyonel formül: Alış * (1 + Kar/100) * (1 + Komisyon/100) * (1 + KDV/100)
    hesaplanan_satis = []
    for alis in df_temp["Alış Fiyatı (₺)"]:
      kdvsiz_satis = alis * (1 + genel_kar / 100) * (1 + pazaryeri_komisyon / 100)
      kdvli_satis = kdvsiz_satis * (1 + kdv_orani / 100)
      hesaplanan_satis.append(round(kdvli_satis, 2))

    df_temp["Önerilen Satış Fiyatı (₺)"] = hesaplanan_satis
    st.session_state["urunler_df"] = df_temp
    log_ekle("Tüm ürünlerin fiyatlandırma kuralları güncellendi.", "INFO")
    st.success(
        "Fiyatlar kar marjı ve pazaryeri komisyonuna göre yeniden hesaplandı!"
    )
    st.dataframe(df_temp, use_container_width=True)

with tab4:
  st.subheader("🛒 Pazaryeri Sipariş Takibi")
  st.markdown(
      "Trendyol ve Hepsiburada üzerindeki gelen siparişlerinizi buradan"
      " gözlemleyebilirsiniz."
  )

  # Örnek simülasyon tablosu
  siparis_ornek = pd.DataFrame({
      "Sipariş No": ["#TRY-884923", "#HB-552109", "#TRY-884924"],
      "Pazaryeri": ["Trendyol", "Hepsiburada", "Trendyol"],
      "Müşteri": ["Ahmet Y.", "Mehmet K.", "Ayşe S."],
      "Tutar (₺)": [450.00, 1250.50, 320.00],
      "Durum": ["Onaylandı", "Kargoda", "Hazırlanıyor"],
  })
  st.dataframe(siparis_ornek, use_container_width=True)

with tab5:
  st.subheader("🪵 Sistem Logları & İşlem Geçmişi")
  if st.session_state["loglar"]:
    df_log = pd.DataFrame(st.session_state["loglar"])
    st.dataframe(df_log, use_container_width=True)
  else:
    st.info("Henüz kaydedilmiş bir sistem logu bulunmuyor.")
