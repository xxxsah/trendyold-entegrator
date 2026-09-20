import pandas as pd
import requests
import streamlit as st
import xml.etree.ElementTree as ET

st.set_page_config(
    page_title="Profesyonel XML Entegrasyon Paneli", layout="wide"
)

st.title("📦 Profesyonel XML & Ürün Yönetim Sistemi")
st.markdown("---")

# Yan Panel - Ayarlar
st.sidebar.header("⚙️ Entegrasyon Ayarları")
xml_url = st.sidebar.text_input(
    "XML Linki (URL)",
    placeholder="https://ornek.com/feed.xml",
)
kar_marji = st.sidebar.number_input(
    "Genel Kar Marjı (%)", min_value=0.0, value=20.0, step=1.0
)
kdv_orani = st.sidebar.selectbox("KDV Oranı (%)", [1, 10, 20], index=2)


# XML Çekme ve İşleme Fonksiyonu
@st.cache_data(ttl=3600)
def xml_verisini_cek(url):
  try:
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    return root
  except Exception as e:
    st.error(f"XML çekilirken hata oluştu: {e}")
    return None


if xml_url:
  if st.sidebar.button("XML Verilerini Güncelle ve Yükle"):
    with st.spinner("XML verileri indiriliyor ve işleniyor..."):
      root = xml_verisini_cek(xml_url)

      if root is not None:
        urunler = []
        # Not: XML tag isimleri sağlayıcıya göre değişebilir (örn: 'item', 'product', 'Urun')
        # Genel bir arama mantığı veya en sık kullanılan 'item'/'product' yapısı kurulabilir.
        for item in root.findall(
            ".//item"
        ):  # Alternatif olarak './/product' veya './/Urun'
          baslik = (
              item.find("title").text
              if item.find("title") is not None
              else "İsimsiz Ürün"
          )
          stok = (
              int(item.find("stock").text)
              if item.find("stock") is not None and item.find("stock").text
              else 0
          )
          fiyat_str = (
              item.find("price").text
              if item.find("price") is not None
              else "0"
          )
          barkod = (
              item.find("barcode").text
              if item.find("barcode") is not None
              else "Yok"
          )

          # Fiyat temizleme (virgül/nokta dönüşümleri için)
          fiyat_str = (
              fiyat_str.replace("TL", "")
              .replace(" ", "")
              .replace(".", "")
              .replace(",", ".")
          )
          try:
            alis_fiyati = float(fiyat_str)
          except ValueError:
            alis_fiyati = 0.0

          # Kar ve KDV hesaplama
          satis_fiyati_kdvsiz = alis_fiyati * (1 + kar_marji / 100)
          satis_fiyati_kdvli = satis_fiyati_kdvsiz * (1 + kdv_orani / 100)

          urunler.append({
              "Barkod": barkod,
              "Ürün Adı": baslik,
              "Stok": stok,
              "Alış Fiyatı (₺)": round(alis_fiyati, 2),
              "Hesaplanan Satış (₺)": round(satis_fiyati_kdvli, 2),
          })

        df = pd.DataFrame(urunler)
        st.session_state["urunler_df"] = df
        st.success(f"Toplam {len(df)} ürün başarıyla yüklendi!")

# Veri Gösterim Alanı
if "urunler_df" in st.session_state:
  df = st.session_state["urunler_df"]

  col1, col2, col3 = st.columns(3)
  col1.metric("Toplam Ürün Sayısı", len(df))
  col2.metric("Stoktaki Ürünler", len(df[df["Stok"] > 0]))
  col3.metric("Tükenen Ürünler", len(df[df["Stok"] == 0]))

  st.markdown("### 📋 Ürün Listesi ve Fiyatlandırma")
  arama = st.text_input("Ürünlerde Ara (İsim veya Barkod):")

  if arama:
    df = df[
        df["Ürün Adı"].str.contains(arama, case=False, na=False)
        | df["Barkod"].str.contains(arama, case=False, na=False)
    ]

  st.dataframe(df, use_container_width=True)
else:
  st.info(
      "👈 Başlamak için soldaki panele XML linkinizi girin ve butona tıklayın."
  )
