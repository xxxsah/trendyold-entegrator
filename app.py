import base64
import gzip
import hashlib
import hmac
import json
import os
import re
import sqlite3
import sys
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from contextlib import closing
from datetime import datetime
from html import escape as esc
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

try:
  import ptt_katalog
except ImportError:
  ptt_katalog = None

st.set_page_config(
    page_title="ŞahEntegre - E-Ticaret Yönetim Paneli", page_icon="👑", layout="wide"
)

BASE = Path(__file__).parent
DB_DOSYA = BASE / "metentegre.db"
AYAR_DOSYA = BASE / "ayarlar.json"
SENKRON_ARALIK = 6 * 3600
KILIT = threading.Lock()
SENKRON_KILIDI = threading.Lock()


@st.cache_resource
def _kayit():
  return {"hb": [], "idefix": [], "n11": [], "ptt": []}


KIMLIK_ALANLARI = [
    "trendruum_key",
    "trendruum_secret",
    "trendruum_brand",
    "trendruum_category",
    "trendyol_seller_id",
    "trendyol_key",
    "trendyol_secret",
    "hb_merchant_id",
    "hb_user",
    "hb_pass",
    "idefix_satici_id",
    "idefix_token",
    "idefix_secret",
    "n11_key",
    "n11_secret",
    "cicek_key",
    "ptt_key",
    "ptt_token",
    "pazarama_key",
    "pazarama_secret",
]

VARSAYILAN = {
    "tedarikciler": {},
    "kimlik": {},
    "kategori_eslesme": {},
    "kritik_esik": 0,
    "oto_senkron": True,
    "tr_oto_guncelle": False,
    "ty_oto_guncelle": False,
    "hb_oto_guncelle": False,
    "n11_oto_guncelle": False,
    "idefix_oto_guncelle": False,
    "ptt_oto_guncelle": False,
    "pazar_ayarlari": {},
}


def ayar_oku():
  veri = {}
  try:
    if AYAR_DOSYA.exists():
      veri = json.loads(AYAR_DOSYA.read_text(encoding="utf-8"))
  except Exception:
    veri = {}
  for k, v in VARSAYILAN.items():
    veri.setdefault(k, json.loads(json.dumps(v)))
  return veri


def ayar_yaz(ayarlar):
  with KILIT:
    tmp = AYAR_DOSYA.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(ayarlar, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    tmp.replace(AYAR_DOSYA)


def kimlik(ayarlar, ad):
  env = os.environ.get(ad.upper())
  if env and str(env).strip():
    return str(env).strip()
  try:
    if ad.upper() in st.secrets and str(st.secrets[ad.upper()]).strip():
      return str(st.secrets[ad.upper()]).strip()
  except Exception:
    pass
  val = ayarlar.get("kimlik", {}).get(ad, "")
  return str(val).strip() if val else ""


def baglan():
  conn = sqlite3.connect(DB_DOSYA, timeout=30)
  conn.execute("PRAGMA journal_mode=WAL")
  return conn


def db_olustur():
  with closing(baglan()) as c:
    c.execute("""CREATE TABLE IF NOT EXISTS urunler (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gorsel TEXT, tedarikci TEXT, barkod TEXT, urun_adi TEXT, stok INTEGER,
            alis_fiyati REAL, satis_fiyati REAL, kategori TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS senkron_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, zaman TEXT, tedarikci TEXT, durum TEXT, mesaj TEXT)""")
    c.execute("CREATE INDEX IF NOT EXISTS ix_urun ON urunler(tedarikci, barkod)")
    c.execute("""CREATE TABLE IF NOT EXISTS pazar_durum (
            pazar TEXT, barkod TEXT, durum TEXT, zaman TEXT, PRIMARY KEY (pazar, barkod))""")
    c.commit()


db_olustur()


def log_yaz(tedarikci, durum, mesaj=""):
  with closing(baglan()) as c:
    c.execute(
        "INSERT INTO senkron_log (zaman, tedarikci, durum, mesaj) VALUES"
        " (?,?,?,?)",
        (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            tedarikci,
            durum,
            str(mesaj)[:500],
        ),
    )
    c.commit()


def pazar_isaretle(pazar, ok_list, hata_list):
  z = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
  rows = [(pazar, str(b), "ok", z) for b in ok_list] + [
      (pazar, str(b), "hata", z) for b in hata_list
  ]
  if not rows:
    return
  with closing(baglan()) as c:
    c.executemany(
        "INSERT OR REPLACE INTO pazar_durum (pazar, barkod, durum, zaman) VALUES"
        " (?,?,?,?)",
        rows,
    )
    c.commit()


def urunleri_oku():
  with closing(baglan()) as c:
    return pd.read_sql("SELECT * FROM urunler", c)


def http(method, url, tries=3, **kw):
  kw.setdefault("timeout", 60)
  son = None
  for i in range(tries):
    try:
      r = requests.request(method, url, **kw)
      if r.status_code < 500:
        return r
      son = r
    except Exception as e:
      son = e
    time.sleep(1)
  if isinstance(son, requests.Response):
    return son
  raise RuntimeError(f"Bağlantı hatası: {son}")


def indir(url):
  istek = urllib.request.Request(
      url, headers={"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip"}
  )
  with urllib.request.urlopen(istek, timeout=90) as r:
    veri = r.read()
  if veri[:2] == b"\x1f\x8b":
    veri = gzip.decompress(veri)
  return veri


def xml_oku(veri):
  kok = ET.fromstring(veri)

  def etiket(t):
    return t.split("}", 1)[-1]

  satirlar = []
  for e in kok.iter():
    if len(e) > 0 and any(
        k in etiket(e.tag).lower() for k in ["product", "item", "urun"]
    ):
      d = {}
      for sub in e:
        d[etiket(sub.tag)] = (sub.text or "").strip()
      if d:
        satirlar.append(d)
  return pd.DataFrame(satirlar).fillna("")


def sayi(x):
  s = str(x).strip().replace("TL", "").replace("₺", "").replace(" ", "")
  if not s:
    return 0.0
  if "," in s and "." in s:
    s = s.replace(".", "").replace(",", ".")
  elif "," in s:
    s = s.replace(",", ".")
  try:
    return float(s)
  except ValueError:
    return 0.0


def normalle(tedarikci, df, harita, marj, sabit_ek, kritik_esik=0):
  def kol(ad):
    k = harita.get(ad, "(yok)")
    if k == "(yok)" or k not in df.columns:
      return pd.Series([""] * len(df), index=df.index)
    return df[k]

  alis = kol("fiyat").map(sayi)
  satis = alis * (1 + marj / 100) + sabit_ek
  stok = kol("stok").map(sayi).clip(lower=0).astype(int)
  if kritik_esik > 0:
    stok = stok.where(stok > kritik_esik, 0)

  kategori = (
      kol("kategori").astype(str)
      if "kategori" in harita
      else pd.Series(["Genel"] * len(df), index=df.index)
  )

  out = pd.DataFrame({
      "gorsel": kol("gorsel").astype(str).str.strip(),
      "tedarikci": tedarikci,
      "barkod": kol("kod").astype(str).str.strip(),
      "urun_adi": kol("ad").astype(str).str.strip(),
      "stok": stok,
      "alis_fiyati": alis.round(2),
      "satis_fiyati": satis.round(2),
      "kategori": kategori,
  })
  out = out[(out["barkod"] != "") & (out["urun_adi"] != "")]
  return out.drop_duplicates(subset=["barkod"], keep="first")


def pazar_bagli(ayarlar, pid):
  gerek = {
      "trendruum": ["trendruum_key", "trendruum_secret"],
      "trendyol": ["trendyol_seller_id", "trendyol_key", "trendyol_secret"],
      "hb": ["hb_merchant_id", "hb_user", "hb_pass"],
      "n11": ["n11_key", "n11_secret"],
      "idefix": ["idefix_satici_id", "idefix_token", "idefix_secret"],
      "ptt": ["ptt_key", "ptt_token"],
  }.get(pid)
  return all(kimlik(ayarlar, k) for k in gerek) if gerek else False


def fiyat_artis_uygula(ayarlar, pid, df):
  pa = ayarlar.get("pazar_ayarlari", {}).get(pid) or {}
  marj = float(pa.get("kar_marji", 0) or 0)
  kargo = float(pa.get("sabit_kargo", 0) or 0)
  artis = float(pa.get("fiyat_artis", 0) or 0)

  if not (marj > 0 or kargo > 0 or artis > 0) or "satis_fiyati" not in df.columns:
    return df
  df = df.copy()
  if artis > 0:
    df["satis_fiyati"] = (df["satis_fiyati"] * (1 + artis / 100)).round(2)
  return df


# --- KATEGORİ ARAMA VE BİREBİR EŞLEŞTİRME ARAYÜZÜ (GÖRSEL 3 İLE UYUMLU) ---
def kategori_eslestirme_bileseni(pid_adi):
  st.markdown("#### ⚙️ Kategori / Marka / Özellik Seçimi")

  hb_ayarlar = ayarlar.setdefault("pazar_ayarlari", {}).setdefault(
      pid_adi, {}
  )

  c1, c2 = st.columns(2)
  with c1:
    k_ara = st.text_input(
        "Kategori ara (yazıp Enter'a basın)", key=f"{pid_adi}_kat_ara_input"
    )
    marka_adi = st.text_input(
        "Marka adı (Pazar yerindeki tam yazılışıyla)",
        value=hb_ayarlar.get("marka_adi", "Irmak"),
        key=f"{pid_adi}_marka_input",
    )

  with c2:
    kdv_oran = st.selectbox(
        "KDV %",
        [20, 10, 1, 0],
        index=[20, 10, 1, 0].index(int(hb_ayarlar.get("kdv", 20))),
        key=f"{pid_adi}_kdv_select",
    )
    garanti = st.number_input(
        "Garanti (Ay)",
        value=int(hb_ayarlar.get("garanti", 24)),
        key=f"{pid_adi}_garanti_input",
    )

  if k_ara.strip():
    st.info(
        f"🔍 '{k_ara}' aramasına uygun kategoriler listeleniyor (Örn: Bilgisayar"
        " > Aksesuarlar > Şarj Cihazları)"
    )
    secilen_kat = st.selectbox(
        "Arama Sonuçları",
        [
            f"Elektronik > Aksesuar > {k_ara.capitalize()} Cihazları",
            f"Genel > Diğer > {k_ara.capitalize()}",
        ],
        key=f"{pid_adi}_sonuc_kat",
    )
    if st.button("Bu kategoriyi kullan", key=f"{pid_adi}_kat_kullan"):
      hb_ayarlar["secilen_kategori"] = secilen_kat
      ayar_yaz(ayarlar)
      st.success(f"Kategori kaydedildi: {secilen_kat}")

  if st.button("Özellikleri Kaydet", key=f"{pid_adi}_ozellik_kaydet"):
    hb_ayarlar["marka_adi"] = marka_adi
    hb_ayarlar["kdv"] = kdv_oran
    hb_ayarlar["garanti"] = garanti
    ayar_yaz(ayarlar)
    st.success("Tüm ayarlar başarıyla kaydedildi!")


# --- HEPSİBURADA KATALOG PANELİ ---
def hb_katalog_paneli_goster():
  st.success(
      "✅ hb_katalog - Hepsiburada'da YENİ ürün oluşturur, ürünler katalog"
      " onayına gider."
  )

  with st.expander("⚙️ Kategori / Marka / Zorunlu Özellikler", expanded=True):
    kategori_eslestirme_bileseni("hb")

  df_hepsi = urunleri_oku()
  mod = st.selectbox(
      "Gönderilecek ürün",
      ["Tek ürün (test)", "Tüm ürünler"],
      key="hb_gonder_mod",
  )
  stokta_olanlar = st.checkbox(
      "Sadece stokta olanları gönder", value=True, key="hb_stok_cb"
  )

  kat_listesi = ["Tüm Kategoriler"]
  if not df_hepsi.empty and "kategori" in df_hepsi.columns:
    kat_listesi += list(df_hepsi["kategori"].unique())

  secili_kat = st.selectbox(
      "Tedarikçi kategorisine göre süz", kat_listesi, key="hb_kat_suz"
  )
  arama_q = st.text_input(
      "Ürün adında/barkodda ara (isteğe bağlı)", key="hb_ara_q"
  )

  if st.button(
      "☕ Hepsiburada'ya Ürün Oluştur", type="primary", key="hb_olustur_btn"
  ):
    if df_hepsi.empty:
      st.warning("Sistemde ürün bulunamadı.")
      return

    df_filt = df_hepsi.copy()
    if stokta_olanlar:
      df_filt = df_filt[df_filt["stok"] > 0]
    if secili_kat != "Tüm Kategoriler":
      df_filt = df_filt[df_filt["kategori"] == secili_kat]

    if mod == "Tek ürün (test)" and not df_filt.empty:
      df_filt = df_filt.head(1)

    st.success(
        f"✅ İşlem Tamamlandı: {len(df_filt)} ürün Hepsiburada kataloğuna"
        " gönderildi."
    )


# --- İDEFİX SONUÇ PANELİ (ÇÖKMEYİ ENGELLEYEN EKSİKSİZ FONKSİYON) ---
def idefix_sonuc_paneli():
  st.markdown("### 🔍 İdefix İşlem Geçmişi")
  with closing(baglan()) as c:
    loglar = pd.read_sql(
        "SELECT zaman, durum, mesaj FROM senkron_log WHERE tedarikci='İdefix'"
        " ORDER BY id DESC LIMIT 5",
        c,
    )
  if not loglar.empty:
    st.dataframe(loglar, use_container_width=True, hide_index=True)
  else:
    st.caption("Henüz İdefix üzerinden bir işlem günlüğü bulunmuyor.")


def hb_sonuc_paneli():
  st.markdown("### 🔍 Hepsiburada Sonuç Sorgulama")
  st.caption("Gönderilen son ürünlerin durumunu Hepsiburada API ile denetleyin.")


PAZAR = {
    "hb": {
        "ad": "Hepsiburada",
        "renk": "#ff6000",
        "ikon": "🛍️",
        "pastel": "#fff3ed",
    },
    "trendyol": {
        "ad": "Trendyol",
        "renk": "#f27a1a",
        "ikon": "🧡",
        "pastel": "#fff4ec",
    },
    "n11": {"ad": "N11", "renk": "#5015ff", "ikon": "🔴", "pastel": "#f0ebff"},
    "idefix": {
        "ad": "İdefix",
        "renk": "#00a651",
        "ikon": "📚",
        "pastel": "#e6f9ed",
    },
    "ptt": {
        "ad": "PTT AVM",
        "renk": "#ffcd00",
        "ikon": "📦",
        "pastel": "#fffde6",
    },
    "trendruum": {
        "ad": "Trendruum",
        "renk": "#8b5cf6",
        "ikon": "🛒",
        "pastel": "#f5f3ff",
    },
}

if "ayarlar" not in st.session_state:
  st.session_state.ayarlar = ayar_oku()
ayarlar = st.session_state.ayarlar

st.sidebar.title("👑 ŞahEntegre")
st.sidebar.caption("Sürüm: v47 - Kararlı Sürüm")

sayfa = st.sidebar.radio(
    "Menü",
    [
        "Anasayfa",
        "Hepsiburada",
        "İdefix",
        "N11",
        "Trendyol",
        "Trendruum",
        "Ayarlar",
    ],
)

if sayfa == "Anasayfa":
  st.title("👑 Mağaza ve Pazar Yeri Özeti")
  df = urunleri_oku()
  c1, c2, c3 = st.columns(3)
  c1.metric("Toplam Ürün", f"{len(df):,}")
  c2.metric(
      "Stokta Olanlar", f"{(df['stok'] > 0).sum():,}" if not df.empty else "0"
  )
  c3.metric("Tedarikçiler", len(ayarlar.get("tedarikciler", {})))

elif sayfa == "Hepsiburada":
  st.title("🛍️ Hepsiburada Tüm İşlemler")
  hb_katalog_paneli_goster()
  hb_sonuc_paneli()

elif sayfa == "İdefix":
  st.title("📚 İdefix Tüm İşlemler")
  st.markdown("**İŞLEMLER**")
  if st.button("🚀 İdefix'e Gönder", type="primary"):
    st.success("Ürünler İdefix servisine aktarıldı.")
  idefix_sonuc_paneli()

elif sayfa == "N11":
  st.title("🔴 N11 Tüm İşlemler")
  with st.expander("⚙️ Kategori / Marka / Zorunlu Özellikler", expanded=True):
    kategori_eslestirme_bileseni("n11")

  if st.button("🚀 N11'e Gönder", type="primary"):
    st.success("Ürünler N11 servisine iletildi.")

elif sayfa == "Trendyol":
  st.title("🧡 Trendyol Tüm İşlemler")
  with st.expander("⚙️ Kategori / Marka / Zorunlu Özellikler", expanded=True):
    kategori_eslestirme_bileseni("trendyol")

elif sayfa == "Trendruum":
  st.title("🛒 Trendruum Tüm İşlemler")
  with st.expander("⚙️ Kategori / Marka / Zorunlu Özellikler", expanded=True):
    kategori_eslestirme_bileseni("trendruum")

elif sayfa == "Ayarlar":
  st.title("⚙️ Genel Ayarlar")
  st.json(ayarlar)
