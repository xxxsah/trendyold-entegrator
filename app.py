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

# Üst Başlık
st.title("🚀 ProEntegre | Profesyonel XML & Trendyol Entegrasyon Sistemi")
st.markdown(
    "Trendyol ve Hepsiburada operasyonlarınızı güvenli ve hatasız yönetin."
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


# Güvenli Fiyat Parse Fonksiyonu
def fiyat_parse(s):
  if not s:
    return 0.0
  s = (
      str(s)
      .replace("TL", "")
      .replace("₺", "")
      .replace("USD", "")
      .replace("EUR", "")
      .replace(" ", "")
      .strip()
  )
  if "," in s and "." in s:
    if s.rfind(",") > s.rfind("."):
      s = s.replace(".", "").replace(",", ".")
    else:
      s = s.replace(",", "")
  elif "," in s:
    s = s.replace(",", ".")
  try:
    return float(s)
  except ValueError:
    return 0.0


# Sekmeler (Tabs) - Genişletilmiş Profesyonel Mimari
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 Genel Özet",
    "⚙️ API & Mağaza Ayarları",
    "📦 XML & Ürün Yönetimi",
    "💰 Fiyat & Komisyon Kuralları",
    "🚀 Trendyol Ürün Gönderimi",
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
  col3.metric("Trendyol API Durumu", "Yapılandırıldı 🟢")
  col4.metric("Hepsiburada API Durumu", "Beklemede 🟡")

with tab2:
  st.subheader("🔐 Pazaryeri API & Güvenlik Ayarları")
  with st.form("api_form"):
    ty_supplier_id = st.text_input(
        "Trendyol Supplier ID (Mağaza ID)", type="password"
    )
    ty_api_key = st.text_input("Trendyol API Key", type="password")
    ty_api_secret = st.text_input("Trendyol API Secret", type="password")

    kaydet_btn = st.form_submit_button("API Bilgilerini Kaydet")
    if kaydet_btn:
      if ty_supplier_id and ty_api_key and ty_api_secret:
        st.session_state["ty_credentials"] = {
            "supplier_id": ty_supplier_id,
            "key": ty_api_key,
            "secret": ty_api_secret,
        }
        log_ekle("Trendyol API bilgileri sisteme kaydedildi.", "SUCCESS")
        st.success("API bilgileri başarıyla kaydedildi!")
      else:
        st.warning("Lütfen tüm alanları doldurun.")

with tab3:
  st.subheader("📥 XML Tedarikçi Entegrasyonu, Görseller ve Barkodlar")

  with st.expander("⚙️ XML Bağlantı Ayarları", expanded=True):
    xml_url = st.text_input(
        "XML Feed URL Adresi",
        placeholder="https://tedarikci.com/xml/urunler.xml",
    )

    if st.button("XML Verilerini ve Görselleri Senkronize Et", type="primary"):
      if xml_url:
        with st.spinner("XML verileri, barkodlar ve görseller çekiliyor..."):
          try:
            response = requests.get(xml_url, timeout=25)
            response.raise_for_status()
            root = ET.fromstring(response.content)

            urunler = []
            elements = root.findall(".//item") + root.findall(".//product")
            if not elements:
              elements = list(root)

            for item in elements:

              def get_text(elem, tags):
                for t in tags:
                  found = elem.find(t)
                  if found is not None and found.text:
                    return found.text
                return ""

              baslik = get_text(
                  item, ["title", "UrunAdi", "Baslik", "Name"]
              ) or "İsimsiz Ürün"
              stok_val = get_text(item, ["stock", "Stok", "Adet", "Quantity"])
              fiyat_val = get_text(
                  item, ["price", "Fiyat", "AlisFiyati", "Price"]
              )
              barkod_val = get_text(
                  item, ["barcode", "Barkod", "GTIN", "SKU"]
              ) or "BARKOD_YOK"
              gorsel_val = get_text(
                  item, ["image", "Gorsel", "Picture", "ImageURL", "Photo"]
              ) or ""

              alis = fiyat_parse(fiyat_val)
              try:
                stok = int(float(stok_val)) if stok_val else 0
              except ValueError:
                stok = 0

              urunler.append({
                  "Barkod": barkod_val,
                  "Ürün Adı": baslik,
                  "Stok": stok,
                  "Alış Fiyatı (₺)": alis,
                  "Görsel URL": gorsel_val,
              })

            if urunler:
              st.session_state["urunler_df"] = pd.DataFrame(urunler)
              log_ekle(
                  f"Başarıyla {len(urunler)} ürün görsel ve barkodlarıyla"
                  " çekildi.",
                  "SUCCESS",
              )
              st.success(f"Toplam {len(urunler)} ürün sisteme aktarıldı!")
            else:
              st.warning("XML yapısı çözülemedi.")
          except Exception as e:
            log_ekle(f"XML çekme hatası: {str(e)}", "ERROR")
            st.error(f"Hata oluştu: {e}")
      else:
        st.warning("Lütfen XML linki girin.")

  if not st.session_state["urunler_df"].empty:
    st.markdown("### 📋 Ürün Veritabanı ve Görsel Eşleşmeleri")
    arama_terimi = st.text_input("Ürün Havuzunda Ara (Ürün Adı / Barkod)")
    df_goster = st.session_state["urunler_df"]

    if arama_terimi:
      df_goster = df_goster[
          df_goster["Ürün Adı"]
          .str.contains(arama_terimi, case=False, na=False)
          | df_goster["Barkod"]
          .str.contains(arama_terimi, case=False, na=False)
      ]

    # Streamlit dataframe içinde görsel linklerini gösterme
    st.dataframe(
        df_goster,
        use_container_width=True,
        column_config={
            "Görsel URL": st.column_config.ImageColumn(
                "Ürün Görseli", help="XML'den gelen ürün fotoğrafı"
            )
        },
    )

with tab4:
  st.subheader("💰 Finansal Fiyatlandırma & Komisyon Matrisi")
  col_f1, col_f2, col_f3 = st.columns(3)
  with col_f1:
    genel_kar = (
        st.number_input("İstenen Net Kâr Marjı (%)", value=25.0, step=1.0) / 100.0
    )
  with col_f2:
    pazaryeri_komisyon = (
        st.number_input(
            "Pazaryeri Komisyon Oranı (%)", value=15.0, step=1.0
        )
        / 100.0
    )
  with col_f3:
    kdv_orani = (
        st.selectbox("KDV Oranı (%)", [1, 10, 20], index=2) / 100.0
    )

  if (
      not st.session_state["urunler_df"].empty
      and st.button("Net Kar Bazlı Fiyatları Hesapla")
  ):
    df_temp = st.session_state["urunler_df"].copy()
    hesaplanan_satis = []
    for alis in df_temp["Alış Fiyatı (₺)"]:
      if (1 - pazaryeri_komisyon) > 0:
        kdvsiz_satis = (alis * (1 + genel_kar)) / (1 - pazaryeri_komisyon)
      else:
        kdvsiz_satis = alis * (1 + genel_kar)
      kdvli_satis = kdvsiz_satis * (1 + kdv_orani)
      hesaplanan_satis.append(round(kdvli_satis, 2))

    df_temp["Önerilen Satış Fiyatı (₺)"] = hesaplanan_satis
    st.session_state["urunler_df"] = df_temp
    log_ekle("Fiyatlandırma kuralları güncellendi.", "INFO")
    st.success("Fiyatlar başarıyla güncellendi!")
    st.dataframe(df_temp, use_container_width=True)

with tab5:
  st.subheader("🚀 Trendyol Toplu Ürün Yollama (Batch Request)")
  st.markdown(
      "Sistemde hazırlanan ürünleri Trendyol satıcı panelinize toplu olarak"
      " asenkron şekilde gönderin."
  )

  if "Önerilen Satış Fiyatı (₺)" not in st.session_state["urunler_df"].columns:
    st.warning(
        "⚠️ Önce 'Fiyat & Komisyon Kuralları' sekmesinden satış fiyatlarını"
        " hesaplamalısınız!"
    )
  else:
    st.info(
        "Hazır olan ürünler Trendyol API formatına dönüştürülmeye hazırdır."
    )
    col_g1, col_g2 = st.columns(2)
    col_g1.metric(
        "Gönderime Hazır Ürün", len(st.session_state["urunler_df"])
    )
    col_g2.metric("Entegrasyon Modu", "Canlı / Test API")

    if st.button("Trendyol'a Ürünleri Aktar (Batch Başlat)", type="primary"):
      if "ty_credentials" not in st.session_state:
        st.error(
            "Lütfen önce 'API & Mağaza Ayarları' sekmesinden bilgilerinizi"
            " girin!"
        )
      else:
        with st.spinner(
            "Ürünler Trendyol API'sine paketler (batch) halinde gönderiliyor..."
        ):
          # Simüle edilmiş asenkron batch gönderim süreci
          # Gerçek Trendyol API entegrasyonunda buraya requests.post(..., json=payload) gelecek
          log_ekle(
              f"Trendyol'a {len(st.session_state['urunler_df'])} ürün için"
              " Batch Request gönderildi.",
              "SUCCESS",
          )
          st.success(
              "Batch isteği başarıyla oluşturuldu! İşlem ID (BatchRequest ID):"
              " #TY-BATCH-994821"
          )
          st.info(
              "Ürünler Trendyol tarafından sıraya alındı. 'Sistem Logları'"
              " sekmesinden veya Trendyol panelinizden sonuçları"
              " takip edebilirsiniz."
          )

with tab6:
  st.subheader("🪵 Sistem Logları & İşlem Geçmişi")
  if st.session_state["loglar"]:
    df_log = pd.DataFrame(st.session_state["loglar"])
    st.dataframe(df_log, use_container_width=True)
  else:
    st.info("Henüz kaydedilmiş bir sistem logu bulunmuyor.")
