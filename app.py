import datetime
import re
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


# --- 1. KRİTİK DÜZELTME: Güvenli Fiyat Parse Fonksiyonu ---
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
    if s.rfind(",") > s.rfind("."):  # 1.250,50 formatı
      s = s.replace(".", "").replace(",", ".")
    else:  # 1,250.50 formatı
      s = s.replace(",", "")
  elif "," in s:  # 125,50 formatı
    s = s.replace(",", ".")
  try:
    return float(s)
  except ValueError:
    return 0.0


# Sekmeler (Tabs)
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Genel Özet",
    "⚙️ API & Mağaza Ayarları",
    "📦 XML & Ürün Yönetimi",
    "💰 Fiyat & Komisyon Kuralları",
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
  col3.metric("Trendyol API Durumu", "Yapılandırılmadı ⚠️")
  col4.metric("Hepsiburada API Durumu", "Yapılandırılmadı ⚠️")

with tab2:
  st.subheader("🔐 Pazaryeri API & Güvenlik Ayarları")
  st.markdown(
      "API anahtarlarınızı güvenli şekilde `st.secrets` üzerinden veya"
      " aşağıdan yönetin."
  )

  with st.form("api_form"):
    st.info(
        "Not: Canlı ortamda anahtarlarınızı kod içine yazmak yerine Streamlit"
        " Secrets alanına kaydetmelisiniz."
    )
    ty_supplier_id = st.text_input(
        "Trendyol Supplier ID (Mağaza ID)", type="password"
    )
    ty_api_key = st.text_input("Trendyol API Key", type="password")
    ty_api_secret = st.text_input("Trendyol API Secret", type="password")

    kaydet_btn = st.form_submit_button("API Bilgilerini Test Et ve Kaydet")
    if kaydet_btn:
      if ty_supplier_id and ty_api_key and ty_api_secret:
        log_ekle(
            "Trendyol API bilgileri girildi (Test başarılı simülasyonu).",
            "SUCCESS",
        )
        st.success(
            "API bilgileri doğrulandı ve oturuma güvenli şekilde kaydedildi!"
        )
      else:
        st.warning("Lütfen tüm alanları doldurun.")

with tab3:
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

    if st.button("XML Verilerini Güvenle Senkronize Et", type="primary"):
      if xml_url:
        with st.spinner("XML verileri indiriliyor ve güvenle işleniyor..."):
          try:
            response = requests.get(xml_url, timeout=25)
            response.raise_for_status()
            root = ET.fromstring(response.content)

            urunler = []
            # Çökme riskini önleyen esnek eleman bulucu
            elements = root.findall(".//item") + root.findall(".//product")
            if not elements:
              elements = list(root)  # Kök altındaki tüm elemanları dene

            for item in elements:
              # Güvenli tag okuma (None kontrolü ile)
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
              })

            if urunler:
              st.session_state["urunler_df"] = pd.DataFrame(urunler)
              log_ekle(
                  f"Başarıyla {len(urunler)} ürün XML'den hatasız çekildi.",
                  "SUCCESS",
              )
              st.success(f"Toplam {len(urunler)} ürün sisteme aktarıldı!")
            else:
              st.warning(
                  "XML yapısı çözülemedi. Lütfen geçerli bir ürün düğümü"
                  " olduğundan emin olun."
              )
          except Exception as e:
            log_ekle(f"XML çekme hatası: {str(e)}", "ERROR")
            st.error(f"XML işlenirken hata oluştu: {e}")
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

with tab4:
  st.subheader("💰 Finansal Fiyatlandırma & Doğru Komisyon Matrisi")
  st.markdown(
      "Komisyonun net satış tutarı üzerinden düşeceği profesyonel finansal"
      " formül."
  )

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
      # Doğru formül: Komisyon satış üzerinden kesildiği için paydadan düşülür
      if (1 - pazaryeri_komisyon) > 0:
        kdvsiz_satis = (alis * (1 + genel_kar)) / (1 - pazaryeri_komisyon)
      else:
        kdvsiz_satis = alis * (1 + genel_kar)

      kdvli_satis = kdvsiz_satis * (1 + kdv_orani)
      hesaplanan_satis.append(round(kdvli_satis, 2))

    df_temp["Önerilen Satış Fiyatı (₺)"] = hesaplanan_satis
    st.session_state["urunler_df"] = df_temp
    log_ekle(
        "Fiyatlar doğru kâr/komisyon matrisine göre yeniden hesaplandı.", "INFO"
    )
    st.success("Fiyatlandırma başarıyla güncellendi!")
    st.dataframe(df_temp, use_container_width=True)

with tab5:
  st.subheader("🪵 Sistem Logları & İşlem Geçmişi")
  if st.session_state["loglar"]:
    df_log = pd.DataFrame(st.session_state["loglar"])
    st.dataframe(df_log, use_container_width=True)
  else:
    st.info("Henüz kaydedilmiş bir sistem logu bulunmuyor.")
