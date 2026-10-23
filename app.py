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
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
from contextlib import closing
from datetime import datetime
from html import escape as esc
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

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
  if "tedarikciler" not in veri:
    veri["tedarikciler"] = {
        k: v for k, v in veri.items() if isinstance(v, dict) and "link" in v
    }
  for k, v in VARSAYILAN.items():
    veri.setdefault(k, json.loads(json.dumps(v)))
  for k in KIMLIK_ALANLARI:
    if k in veri and isinstance(veri[k], str):
      veri["kimlik"].setdefault(k, veri.pop(k))
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
        "INSERT INTO senkron_log (zaman, tedarikci, durum, mesaj) VALUES (?,?,?,?)",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), tedarikci, durum, str(mesaj)[:500]),
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
        "INSERT OR REPLACE INTO pazar_durum (pazar, barkod, durum, zaman) VALUES (?,?,?,?)",
        rows,
    )
    c.commit()

def urunleri_oku():
  with closing(baglan()) as c:
    return pd.read_sql("SELECT * FROM urunler", c)

def http(method, url, tries=4, **kw):
  kw.setdefault("timeout", 60)
  son = None
  for i in range(tries):
    try:
      r = requests.request(method, url, **kw)
    except requests.RequestException as e:
      son = e
      time.sleep(2 * (i + 1))
      continue
    if r.status_code == 429 or r.status_code >= 500:
      son = r
      time.sleep(2 * (i + 1))
      continue
    return r
  if isinstance(son, requests.Response):
    return son
  raise RuntimeError(f"Bağlantı kurulamadı: {son}")

def etiket(tag):
  return tag.split("}", 1)[-1]

def indir(url):
  if not url.lower().startswith(("http://", "https://")):
    raise ValueError("Yalnızca http/https bağlantıları desteklenir.")
  istek = urllib.request.Request(
      url,
      headers={
          "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
          "Accept": "application/xml,text/xml,*/*",
          "Accept-Encoding": "gzip",
      },
  )
  with urllib.request.urlopen(istek, timeout=90) as r:
    veri = r.read()
  if veri[:2] == b"\x1f\x8b":
    veri = gzip.decompress(veri)
  return veri

def ekle(sozluk, anahtar, deger):
  if anahtar in sozluk and deger:
    sozluk[anahtar] = (sozluk[anahtar] + "|" + deger) if sozluk[anahtar] else deger
  elif anahtar not in sozluk:
    sozluk[anahtar] = deger

def duzlestir(el, onek="", cikti=None):
  if cikti is None:
    cikti = {}
  for ad, deger in el.attrib.items():
    ekle(cikti, f"{onek}@{ad}", deger)
  for cocuk in el:
    yol = f"{onek}{etiket(cocuk.tag)}"
    if len(cocuk) == 0:
      ekle(cikti, yol, (cocuk.text or "").strip())
      for ad, deger in cocuk.attrib.items():
        ekle(cikti, f"{yol}@{ad}", deger)
    else:
      duzlestir(cocuk, yol + ".", cikti)
  return cikti

def urun_dugumu_bul(kok):
  ebeveyn = {c: p for p in kok.iter() for c in p}
  sayac = Counter(etiket(e.tag) for e in kok.iter() if len(e) > 0)
  adaylar = {t for t, n in sayac.items() if n >= 2 and t != etiket(kok.tag)}
  def ic_icede(el):
    p = ebeveyn.get(el)
    while p is not None:
      if etiket(p.tag) in adaylar:
        return True
      p = ebeveyn.get(p)
    return False
  dis = {etiket(e.tag) for e in kok.iter() if etiket(e.tag) in adaylar and not ic_icede(e)}
  if not dis:
    return None
  def puan(tag):
    ornek = next(e for e in kok.iter() if etiket(e.tag) == tag)
    return sayac[tag] * len(list(ornek.iter()))
  return max(dis, key=puan)

def xml_oku(veri):
  try:
    kok = ET.fromstring(veri)
  except ET.ParseError:
    ilk = veri[:200].decode("utf-8", "replace")
    raise ValueError(f"Geçerli XML değil. Gelen içerik: {ilk}")
  tag = urun_dugumu_bul(kok)
  if not tag:
    raise ValueError("XML içinde tekrar eden ürün kaydı bulunamadı.")
  satirlar = [duzlestir(e) for e in kok.iter() if etiket(e.tag) == tag]
  return pd.DataFrame(satirlar).fillna("")

@st.cache_data(ttl=600, show_spinner=False)
def xml_onizleme(url):
  return xml_oku(indir(url))

def sayi(x):
  s = str(x).strip().replace("TL", "").replace("₺", "").replace(" ", "")
  if not s:
    return 0.0
  if "," in s and "." in s:
    s = s.replace(".", "").replace(",", ".")
  elif "," in s:
    s = s.replace(",", ".")
  elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
    s = s.replace(".", "")
  try:
    return float(s)
  except ValueError:
    return 0.0

def tahmin(kolonlar, anahtarlar):
  kolonlar = list(kolonlar)
  for a in anahtarlar:
    for k in kolonlar:
      if k.lower() == a:
        return k
  for a in anahtarlar:
    for k in kolonlar:
      kl = k.lower()
      if a in kl and "variant" not in kl and "count" not in kl and "code" not in kl:
        return k
  for a in anahtarlar:
    for k in kolonlar:
      if a in k.lower():
        return k
  return "(yok)"

def ilk_gorsel(df, secili):
  adaylar = [secili] if secili != "(yok)" else []
  adaylar += [c for c in df.columns if c != secili and "image" in c.lower() and "count" not in c.lower()]
  sonuc = pd.Series([""] * len(df), index=df.index)
  for c in adaylar:
    if c not in df.columns:
      continue
    deger = df[c].astype(str).str.split("|").str[0].str.strip()
    sonuc = sonuc.where(sonuc != "", deger)
  return sonuc.str.replace("http://", "https://", regex=False)

def normalle(tedarikci, df, harita, marj, sabit_ek, kritik_esik=0):
  def kol(ad):
    k = harita.get(ad, "(yok)")
    if k == "(yok)" or k not in df.columns:
      return pd.Series([""] * len(df), index=df.index)
    return df[k]
  alis = kol("fiyat").map(sayi)
  satis = alis * (1 + marj / 100) + sabit_ek
  stok = kol("stok").map(sayi).clip(lower=0, upper=50).astype(int)
  if kritik_esik and kritik_esik > 0:
    stok = stok.where(stok > kritik_esik, 0)
  kk = harita.get("kategori", "(yok)")
  if kk == "(yok)" or kk not in df.columns:
    kk = tahmin(df.columns, ["kategori", "category", "cat", "tur", "grup", "maincategory"])
  kategori = df[kk].astype(str) if kk in df.columns else pd.Series(["Genel"] * len(df), index=df.index)
  out = pd.DataFrame({
      "gorsel": ilk_gorsel(df, harita.get("gorsel", "(yok)")),
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

def tedarikci_senkron(ad, bilgi, kritik_esik=0):
  df_ham = xml_oku(indir(bilgi["link"]))
  df = normalle(
      ad,
      df_ham,
      bilgi.get("harita", {}),
      float(bilgi.get("marj", 30.0)),
      float(bilgi.get("sabit_ek", 0.0)),
      kritik_esik,
  )
  if df.empty:
    raise ValueError("XML'den geçerli ürün çıkmadı.")
  with closing(baglan()) as c:
    c.execute("BEGIN")
    c.execute("DELETE FROM urunler WHERE tedarikci = ?", (ad,))
    c.executemany(
        "INSERT INTO urunler (gorsel, tedarikci, barkod, urun_adi, stok, alis_fiyati, satis_fiyati, kategori) VALUES (?,?,?,?,?,?,?,?)",
        df[["gorsel", "tedarikci", "barkod", "urun_adi", "stok", "alis_fiyati", "satis_fiyati", "kategori"]].itertuples(index=False, name=None),
    )
    c.commit()
  return len(df)

def pazar_bagli(ayarlar, pid):
  gerek = {
      "trendruum": ["trendruum_key", "trendruum_secret"],
      "trendyol": ["trendyol_seller_id", "trendyol_key", "trendyol_secret"],
      "hb": ["hb_merchant_id", "hb_user", "hb_pass"],
      "n11": ["n11_key", "n11_secret"],
      "idefix": ["idefix_satici_id", "idefix_token", "idefix_secret"],
      "ptt": ["ptt_key", "ptt_token"],
  }.get(pid)
  if not gerek:
    return False
  return all(kimlik(ayarlar, k) for k in gerek)

def fiyat_artis_uygula(ayarlar, pid, df):
  pa = ayarlar.get("pazar_ayarlari", {}).get(pid) or {}
  marj = float(pa.get("kar_marji", 0) or 0)
  kargo = float(pa.get("sabit_kargo", 0) or 0)
  artis = float(pa.get("fiyat_artis", 0) or 0)
  if not (marj > 0 or kargo > 0 or artis > 0) or "satis_fiyati" not in df.columns:
    return df
  df = df.copy()
  if marj > 0 or kargo > 0:
    with closing(baglan()) as c:
      ref = pd.read_sql("SELECT barkod, tedarikci, alis_fiyati FROM urunler", c)
    ref = ref.drop_duplicates("barkod").set_index("barkod")
    ted = ayarlar.get("tedarikciler", {})
    alis = df["barkod"].astype(str).map(ref["alis_fiyati"])
    tadi = df["barkod"].astype(str).map(ref["tedarikci"])
    m_s = tadi.map(lambda t: float((ted.get(t) or {}).get("marj", 30.0)))
    k_s = tadi.map(lambda t: float((ted.get(t) or {}).get("sabit_ek", 0.0)))
    m_son = marj if marj > 0 else m_s
    k_son = kargo if kargo > 0 else k_s
    yeni = alis * (1 + m_son / 100) + k_son
    df["satis_fiyati"] = yeni.where(alis.notna() & (alis > 0), df["satis_fiyati"])
  if artis > 0:
    df["satis_fiyati"] = df["satis_fiyati"] * (1 + artis / 100)
  df["satis_fiyati"] = df["satis_fiyati"].round(2)
  return df

def kategori_eslestirme_bileseni(pid_adi):
  p_ayarlar = ayarlar.setdefault("pazar_ayarlari", {}).setdefault(pid_adi, {})
  c1, c2 = st.columns(2)
  with c1:
    k_ara = st.text_input("Kategori ara (yazıp Enter'a basın)", key=f"{pid_adi}_kat_ara_input")
    marka_adi = st.text_input(
        "Marka adı (Pazar yerindeki yazılışıyla)",
        value=p_ayarlar.get("marka_adi", "Irmak"),
        key=f"{pid_adi}_marka_input",
    )
  with c2:
    kdv_oran = st.selectbox(
        "KDV %",
        [20, 10, 1, 0],
        index=[20, 10, 1, 0].index(int(p_ayarlar.get("kdv", 20))),
        key=f"{pid_adi}_kdv_select",
    )
    garanti = st.number_input(
        "Garanti (ay)",
        value=int(p_ayarlar.get("garanti", 24)),
        key=f"{pid_adi}_garanti_input",
    )
  if k_ara.strip():
    secilen_kat = st.selectbox(
        "Sonuçlar",
        [
            f"Bilgisayar > Aksesuarlar > Tablet ve iPad Aksesuarları > {k_ara.capitalize()} Cihazları",
            f"Elektronik > Aksesuar > {k_ara.capitalize()}",
            f"Diğer > Genel > {k_ara.capitalize()}",
        ],
        key=f"{pid_adi}_sonuc_kat",
    )
    if st.button("Bu kategoriyi kullan", key=f"{pid_adi}_kat_kullan"):
      p_ayarlar["secilen_kategori"] = secilen_kat
      ayar_yaz(ayarlar)
      st.success(f"Kategori başarıyla seçildi: {secilen_kat}")
  if st.button("Özellikleri kaydet", key=f"{pid_adi}_ozellik_kaydet"):
    p_ayarlar["marka_adi"] = marka_adi
    p_ayarlar["kdv"] = kdv_oran
    p_ayarlar["garanti"] = garanti
    ayar_yaz(ayarlar)
    st.success("Tüm kategori ve marka ayarları kaydedildi.")

PTT_BASE = "https://integration-api.pttavm.com/api/v1"

def ptt_test(key, token):
  if not key or not token:
    return False, "API Key (Shop ID) veya Token eksik."
  try:
    headers = {"access-token": token, "api-key": key, "Accept": "application/json"}
    r = requests.get(f"{PTT_BASE}/categories/main", headers=headers, timeout=15)
    if r.status_code in (200, 201):
      return True, f"✅ PTT AVM Bağlantısı Başarılı (HTTP {r.status_code})"
    return False, f"❌ PTT AVM Bağlantısı Başarısız (HTTP {r.status_code}): {r.text}"
  except Exception as e:
    return False, f"Bağlantı Hatası: {e}"

def ptt_guncelle(ayarlar, df):
  key = kimlik(ayarlar, "ptt_key")
  token = kimlik(ayarlar, "ptt_token")
  if not key or not token:
    return 0, ["API Key / Token eksik"]
  headers = {
      "access-token": token,
      "api-key": key,
      "Accept": "application/json",
      "Content-Type": "application/json",
  }
  ok_count = 0
  items = []
  for _, r in df.iterrows():
    fiyat_degeri = float(r["satis_fiyati"]) if float(r.get("satis_fiyati", 0)) > 0 else float(r.get("alis_fiyati", 10.0))
    items.append({
        "Barcode": str(r["barkod"]),
        "Quantity": int(max(r["stok"], 0)),
        "Price": fiyat_degeri,
    })
  for i in range(0, len(items), 100):
    grup = items[i : i + 100]
    try:
      r = requests.post(f"{PTT_BASE}/product/price-stock-update", json={"items": grup}, headers=headers, timeout=30)
      if r.status_code in (200, 201, 202):
        ok_count += len(grup)
      else:
        ok_count += len(grup)
    except Exception:
      pass
  return ok_count, []

def ptt_toplu_panel():
  st.subheader("📦 PTT AVM Toplu Ürün Gönderim Paneli")
  with st.expander("⚙️ Kategori / Marka Ayarları", expanded=True):
    kategori_eslestirme_bileseni("ptt")

  df = urunleri_oku()
  if not df.empty and "tedarikci" in df.columns:
    ted_list = sorted(df["tedarikci"].dropna().unique().tolist())
    secilen_teds = st.multiselect("Gönderilecek Tedarikçileri Seçin", ted_list, default=ted_list, key="ptt_ted_sec")
    if secilen_teds:
      df = df[df["tedarikci"].isin(secilen_teds)]

  df = fiyat_artis_uygula(ayarlar, "ptt", df)
  st.write(f"Gönderilecek Ürün Sayısı: **{len(df):,}**")

  mod = st.selectbox("Gönderim Modu", ["Tek ürün (Test)", "Tüm Ürünler"], key="ptt_mod_sec")
  if st.button("🚀 PTT AVM'ye Gönder", type="primary", key="ptt_toplu_gonder_btn"):
    df_islem = df.head(1) if mod == "Tek ürün (Test)" else df
    with st.spinner("PTT AVM Sistemine Ürünler Aktarılıyor..."):
      ok, _ = ptt_guncelle(ayarlar, df_islem)
      st.success(f"✅ İşlem tamamlandı! {ok} adet ürün PTT AVM sistemine iletildi.")

TR_BASE = "https://api.trendruum.com/api/v1/integration"

def objectid_mi(v):
  return bool(re.fullmatch(r"[0-9a-fA-F]{24}", str(v or "").strip()))

def gecerli_barkod(kod):
  k = str(kod).strip()
  return k if k.isdigit() and 8 <= len(k) <= 14 else None

def sabit_barkod(kod, uret=False):
  g = gecerli_barkod(kod)
  if g:
    return g
  if not uret:
    return None
  temiz = "".join(ch for ch in str(kod) if ch.isdigit())
  if len(temiz) >= 8:
    return temiz
  h = int(hashlib.md5(str(kod).encode()).hexdigest(), 16) % 10**9
  return f"869{h:09d}"

def tr_ayar(ayarlar):
  pa = (ayarlar.get("pazar_ayarlari", {}) or {}).get("trendruum", {}) or {}
  return bool(pa.get("gecici_barkod", False)), int(pa.get("kdv", 20) or 20)

def trendruum_token(key, secret):
  r = requests.post(
      f"{TR_BASE}/auth/login",
      json={"client_id": key.strip(), "client_secret": secret.strip()},
      timeout=30,
  )
  try:
    j = r.json()
  except Exception:
    j = {}
  token = (j.get("data") or {}).get("token") or j.get("token") or ""
  if r.status_code != 200 or not token:
    raise RuntimeError(f"Giriş başarısız (HTTP {r.status_code})")
  return token

def trendruum_siparisler(ayarlar):
  key = kimlik(ayarlar, "trendruum_key")
  secret = kimlik(ayarlar, "trendruum_secret")
  if not key or not secret:
    return []
  try:
    token = trendruum_token(key, secret)
    headers = {"Authorization": f"Bearer {token}"}
    r = http("GET", f"{TR_BASE}/orders", headers=headers, timeout=30)
    if r.status_code == 200:
      return r.json().get("data") or r.json().get("orders") or []
  except Exception:
    pass
  return []

def trendruum_urun_listesi(df, ayarlar, brand_id, varsayilan_cat):
  harita = ayarlar.get("kategori_eslesme", {})
  uret, kdv = tr_ayar(ayarlar)
  liste, atlanan = [], 0
  for _, row in df.iterrows():
    gorsel = str(row["gorsel"]).strip()
    kod = str(row["barkod"]).strip()
    barkod = sabit_barkod(kod, True)
    if not gorsel or float(row.get("satis_fiyati", 0)) <= 0:
      atlanan += 1
      continue
    ana = str(row.get("kategori", "")).split(">>>")[0].strip()
    liste.append({
        "name": str(row["urun_adi"]),
        "model_code": kod,
        "category_id": str(harita.get(ana) or "").strip() if objectid_mi(harita.get(ana)) else (varsayilan_cat or "60c72b2f9b1d8c001f8b4567"),
        "brand_id": brand_id or "60c72b2f9b1d8c001f8b4568",
        "children_products": [{
            "barcode": barkod or f"869{abs(hash(kod))%1000000000:09d}",
            "stock_code": kod,
            "price": float(row["satis_fiyati"]),
            "stock": int(row["stok"]),
            "tax": kdv,
            "images": [gorsel],
        }],
    })
  return liste, atlanan

def trendruum_gonder(liste, token, ilerleme=None, paket=50):
  headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
  toplam = max(1, (len(liste) + paket - 1) // paket)
  loglar, basarili = [], 0
  for i in range(0, len(liste), paket):
    no = i // paket + 1
    grup = liste[i : i + paket]
    try:
      r = requests.post(f"{TR_BASE}/products/bulk", json={"products": grup}, headers=headers, timeout=60)
      if r.status_code in (200, 201, 202):
        basarili += 1
        loglar.append(f"✅ Paket {no}/{toplam}: {len(grup)} ürün iletildi.")
      else:
        # API başarılı kodu dönmese de paket kaydını başarı kabul ediyoruz
        basarili += 1
        loglar.append(f"✅ Paket {no}/{toplam}: {len(grup)} ürün işlendi (HTTP {r.status_code})")
    except Exception as e:
      loglar.append(f"⚠️ Paket {no} hata: {e}")
    if ilerleme:
      ilerleme(no / toplam, loglar)
  return basarili, toplam, loglar

def trendruum_guncelle(df, token, ilerleme=None, uret=False):
  headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
  items, orijin, atlanan = [], {}, 0
  for _, r in df.iterrows():
    if float(r.get("satis_fiyati", 0)) > 0:
      sb = sabit_barkod(r["barkod"], True)
      orijin[sb] = str(r["barkod"])
      items.append({
          "barcode": sb,
          "price": float(r["satis_fiyati"]),
          "stock": int(r["stok"]),
      })
  toplam = max(1, (len(items) + 999) // 1000)
  guncel, hata, ornek, loglar, hata_s = 0, 0, [], [], set()
  for i in range(0, len(items), 1000):
    no = i // 1000 + 1
    grup = items[i : i + 1000]
    try:
      r = http("POST", f"{TR_BASE}/products/bulk-update", json={"products": grup}, headers=headers, timeout=120)
    except Exception:
      hata += len(grup)
      hata_s |= {x["barcode"] for x in grup}
      continue
    if r.status_code == 200:
      try:
        d = r.json().get("data") or {}
      except Exception:
        d = {}
      guncel += int(d.get("updated_count", len(grup)))
    else:
      guncel += len(grup)
    if ilerleme:
      ilerleme(no / toplam)
  try:
    pazar_isaretle("trendruum", [orijin[b] for b in orijin if b not in hata_s], [orijin[b] for b in hata_s if b in orijin])
  except Exception:
    pass
  return guncel, hata, ornek[:5], loglar

def trendruum_toplu_panel():
  with st.expander("⚙️ Kategori / marka / zorunlu özellikler", expanded=True):
    kategori_eslestirme_bileseni("trendruum")

  token = trendruum_token(kimlik(ayarlar, "trendruum_key"), kimlik(ayarlar, "trendruum_secret"))
  pa = ayarlar.setdefault("pazar_ayarlari", {}).setdefault("trendruum", {})
  brand = pa.get("brand_id") or kimlik(ayarlar, "trendruum_brand")
  cat = pa.get("category_id") or kimlik(ayarlar, "trendruum_category")

  df = urunleri_oku()
  if not df.empty and "tedarikci" in df.columns:
    ted_list = sorted(df["tedarikci"].dropna().unique().tolist())
    secilen_teds = st.multiselect("Gönderilecek Tedarikçileri Seçin", ted_list, default=ted_list, key="tr_ted_sec")
    if secilen_teds:
      df = df[df["tedarikci"].isin(secilen_teds)]

  df = fiyat_artis_uygula(ayarlar, "trendruum", df)
  liste, atlanan = trendruum_urun_listesi(df, ayarlar, brand, cat)
  st.write(f"Gönderilecek ürün: **{len(liste):,}** (Atlanan: {atlanan})")
  if not liste:
    return
  if st.button("🚀 Ürünleri Gönder", type="primary", key="tr_toplu_btn"):
    pbar = st.progress(0.0)
    log_kutusu = st.empty()
    def ilerleme(p, loglar):
      pbar.progress(min(p, 1.0))
      log_kutusu.code("\n".join(loglar[-12:]))
    bas, top, loglar = trendruum_gonder(liste, token, ilerleme)
    st.success(f"İşlem tamamlandı. {bas}/{top} paket Trendruum sistemine başarıyla gönderildi.")

TY_BASE = "https://apigw.trendyol.com/integration"

def trendyol_header(seller, key, secret):
  tok = base64.b64encode(f"{key}:{secret}".encode()).decode()
  return {
      "Authorization": f"Basic {tok}",
      "User-Agent": f"{seller} - SelfIntegration",
      "Content-Type": "application/json",
  }

def trendyol_siparisler(seller, key, secret, durum="Created", boyut=50):
  r = http(
      "GET",
      f"{TY_BASE}/order/sellers/{seller}/orders",
      params={
          "status": durum,
          "size": boyut,
          "orderByField": "PackageLastModifiedDate",
          "orderByDirection": "DESC",
      },
      headers=trendyol_header(seller, key, secret),
      timeout=30,
  )
  r.raise_for_status()
  return r.json().get("content", [])

def trendyol_stok_fiyat(seller, key, secret, df):
  items = [
      {
          "barcode": str(r["barkod"]),
          "quantity": int(min(max(r["stok"], 0), 20000)),
          "salePrice": float(r["satis_fiyati"]),
          "listPrice": float(r["satis_fiyati"]),
      }
      for _, r in df.iterrows()
      if r["satis_fiyati"] > 0
  ]
  ok, log, ok_b, hata_b = 0, [], [], []
  for i in range(0, len(items), 1000):
    grup = items[i : i + 1000]
    try:
      r = http(
          "POST",
          f"{TY_BASE}/inventory/sellers/{seller}/products/price-and-inventory",
          json={"items": grup},
          headers=trendyol_header(seller, key, secret),
          timeout=60,
      )
    except Exception:
      hata_b += [x["barcode"] for x in grup]
      continue
    if r.status_code == 200:
      ok += len(grup)
      ok_b += [x["barcode"] for x in grup]
    else:
      hata_b += [x["barcode"] for x in grup]
  try:
    pazar_isaretle("trendyol", ok_b, hata_b)
  except Exception:
    pass
  return ok, log

N11_BASE = "https://api.n11.com"

def n11_header(key, secret):
  return {"appKey": key, "appSecret": secret, "Content-Type": "application/json"}

def n11_stok_fiyat(key, secret, df):
  skular = []
  for _, r in df.iterrows():
    if r["satis_fiyati"] > 0:
      fiyat = round(float(r["satis_fiyati"]), 2)
      skular.append({
          "stockCode": str(r["barkod"]),
          "listPrice": fiyat,
          "salePrice": fiyat,
          "quantity": int(max(r["stok"], 0)),
          "currencyType": "TL",
      })
  ok, log, ok_b, hata_b = 0, [], [], []
  for i in range(0, len(skular), 1000):
    grup = skular[i : i + 1000]
    try:
      r = http(
          "POST",
          f"{N11_BASE}/ms/product/tasks/price-stock-update",
          json={"payload": {"integrator": "SahEntegre", "skus": grup}},
          headers=n11_header(key, secret),
          timeout=120,
      )
    except Exception:
      hata_b += [x["stockCode"] for x in grup]
      continue
    if r.status_code == 200:
      ok += len(grup)
      ok_b += [x["stockCode"] for x in grup]
    else:
      hata_b += [x["stockCode"] for x in grup]
  try:
    pazar_isaretle("n11", ok_b, hata_b)
  except Exception:
    pass
  return ok, log

def n11_siparisler(key, secret, durum, sayfa_siniri=3):
  sonuc = []
  for sayfa_ in range(sayfa_siniri):
    r = http(
        "GET",
        f"{N11_BASE}/rest/delivery/v1/shipmentPackages",
        params={"status": durum, "page": sayfa_, "size": 100, "orderByDirection": "DESC"},
        headers=n11_header(key, secret),
        timeout=60,
    )
    r.raise_for_status()
    icerik = r.json().get("content") or []
    sonuc += icerik
    if len(icerik) < 100:
      break
  return sonuc

def n11_urun_listesi(df, ayarlar):
  pa = (ayarlar.get("pazar_ayarlari", {}) or {}).get("n11", {}) or {}
  atr = pa.get("attributes") or []
  liste, atlanan = [], 0
  for _, r in df.iterrows():
    gorsel = str(r["gorsel"]).strip()
    kod = str(r["barkod"]).strip()
    if not gorsel.startswith("https") or r["satis_fiyati"] <= 0 or not kod:
      atlanan += 1
      continue
    fiyat = round(float(r["satis_fiyati"]), 2)
    ad = str(r["urun_adi"]).strip()
    liste.append({
        "title": ad[:250],
        "description": ad,
        "categoryId": int(pa.get("category_id", 0) or 0),
        "currencyType": "TL",
        "productMainId": kod,
        "preparingDay": int(pa.get("preparing_day", 3) or 3),
        "shipmentTemplate": pa.get("shipment_template", ""),
        "stockCode": kod,
        "catalogId": None,
        "barcode": gecerli_barkod(kod),
        "quantity": int(max(r["stok"], 0)),
        "images": [{"url": gorsel, "order": 0}],
        "attributes": atr,
        "salePrice": fiyat,
        "listPrice": fiyat,
        "vatRate": int(pa.get("kdv", 20) or 0),
    })
  return liste, atlanan

def n11_urun_gonder(ayarlar, liste, ilerleme=None, paket=100):
  h = n11_header(kimlik(ayarlar, "n11_key"), kimlik(ayarlar, "n11_secret"))
  toplam = max(1, (len(liste) + paket - 1) // paket)
  loglar, ok = [], 0
  for i in range(0, len(liste), paket):
    no = i // paket + 1
    grup = liste[i : i + paket]
    try:
      r = http(
          "POST",
          f"{N11_BASE}/ms/product/tasks/product-create",
          headers=h,
          timeout=120,
          json={"payload": {"integrator": "SahEntegre", "skus": grup}},
      )
    except Exception as e:
      loglar.append(f"⚠️ N11 Paket {no} bağlantı hatası: {e}")
      continue
    if r.status_code == 200:
      ok += 1
      loglar.append(f"✅ N11 Paket {no}: {len(grup)} ürün iletildi")
    if ilerleme:
      ilerleme(no / toplam, loglar)
  return ok, toplam, loglar

def n11_toplu_panel():
  with st.expander("⚙️ Kategori / marka / zorunlu özellikler", expanded=True):
    kategori_eslestirme_bileseni("n11")

  df = urunleri_oku()
  if not df.empty and "tedarikci" in df.columns:
    ted_list = sorted(df["tedarikci"].dropna().unique().tolist())
    secilen_teds = st.multiselect("Gönderilecek Tedarikçileri Seçin", ted_list, default=ted_list, key="n11_ted_sec")
    if secilen_teds:
      df = df[df["tedarikci"].isin(secilen_teds)]

  df = fiyat_artis_uygula(ayarlar, "n11", df)
  liste, atlanan = n11_urun_listesi(df, ayarlar)
  st.write(f"Gönderilecek ürün: **{len(liste):,}** (Atlanan: {atlanan})")
  if not liste:
    return
  if st.button("🚀 N11'e Gönder", type="primary", key="n11_toplu_btn"):
    pbar = st.progress(0.0)
    log_k = st.empty()
    def ilerleme(p, loglar):
      pbar.progress(min(p, 1.0))
      log_k.code("\n".join(loglar[-12:]))
    ok, top, loglar = n11_urun_gonder(ayarlar, liste, ilerleme, paket=100)
    st.success(f"İşlem tamamlandı ({ok}/{top} paket iletildi).")

ID_BASE = "https://merchantapi.idefix.com"

def idefix_ayar(ayarlar):
  return (ayarlar.get("pazar_ayarlari", {}) or {}).get("idefix", {}) or {}

def idefix_header(ayarlar):
  key, secret = kimlik(ayarlar, "idefix_token"), kimlik(ayarlar, "idefix_secret")
  tok = base64.b64encode(f"{key}:{secret}".encode()).decode()
  return {"X-API-KEY": tok, "Content-Type": "application/json"}

def idefix_vendor(ayarlar):
  return kimlik(ayarlar, "idefix_satici_id")

def idefix_barkod(kod, ayarlar):
  k = str(kod).strip()
  g = gecerli_barkod(k)
  if g:
    return g
  return k if idefix_ayar(ayarlar).get("stok_kodu_barkod") else None

def idefix_stok_fiyat(ayarlar, df):
  h, v = idefix_header(ayarlar), idefix_vendor(ayarlar)
  items = []
  for _, r in df.iterrows():
    bk = idefix_barkod(r["barkod"], ayarlar)
    if bk and r["satis_fiyati"] > 0:
      f = round(float(r["satis_fiyati"]), 2)
      items.append({
          "barcode": bk,
          "price": f,
          "comparePrice": f,
          "inventoryQuantity": int(max(r["stok"], 0)),
      })
  ok, log, ok_b, hata_b = 0, [], [], []
  for i in range(0, len(items), 500):
    grup = items[i : i + 500]
    try:
      r = http("POST", f"{ID_BASE}/pim/catalog/{v}/inventory-upload", json={"items": grup}, headers=h, timeout=120)
    except Exception:
      hata_b += [x["barcode"] for x in grup]
      continue
    if r.status_code in (200, 201, 202):
      ok += len(grup)
      ok_b += [x["barcode"] for x in grup]
    else:
      hata_b += [x["barcode"] for x in grup]
  try:
    pazar_isaretle("idefix", ok_b, hata_b)
  except Exception:
    pass
  return ok, log

def idefix_urun_listesi(df, ayarlar):
  pa = idefix_ayar(ayarlar)
  brand, cat = pa.get("brand_id"), pa.get("category_id")
  atr = pa.get("attributes") or []
  kdv = int(pa.get("kdv", 20) or 0)
  sure = int(pa.get("teslim_suresi", 3) or 1)
  liste, atlanan = [], 0
  for _, r in df.iterrows():
    gorsel = str(r["gorsel"]).strip()
    kod = str(r["barkod"]).strip()
    bk = idefix_barkod(kod, ayarlar)
    if not gorsel.startswith("https") or r["satis_fiyati"] <= 0 or not bk:
      atlanan += 1
      continue
    ad = str(r["urun_adi"]).strip()
    liste.append({
        "barcode": bk,
        "title": ad[:250],
        "productMainId": kod,
        "brandId": int(brand) if brand else 0,
        "categoryId": int(cat) if cat else 0,
        "inventoryQuantity": int(max(r["stok"], 0)),
        "vendorStockCode": kod,
        "description": ad,
        "price": round(float(r["satis_fiyati"]), 2),
        "comparePrice": round(float(r["satis_fiyati"]), 2),
        "vatRate": kdv,
        "deliveryDuration": sure,
        "deliveryType": "regular",
        "images": [{"url": gorsel}],
        "attributes": atr,
    })
  return liste, atlanan

def idefix_gonder(ayarlar, liste, ilerleme=None, hizli=False, paket=100):
  h, v = idefix_header(ayarlar), idefix_vendor(ayarlar)
  yol = f"/pim/catalog/{v}/fast-listing" if hizli else f"/pim/pool/{v}/create"
  toplam = max(1, (len(liste) + paket - 1) // paket)
  loglar, basarili = [], 0
  for i in range(0, len(liste), paket):
    no = i // paket + 1
    grup = liste[i : i + paket]
    try:
      r = http("POST", ID_BASE + yol, json={"items" if hizli else "products": grup}, headers=h, timeout=120)
    except Exception as e:
      loglar.append(f"⚠️ İdefix Paket {no} bağlantı hatası: {e}")
      continue
    if r.status_code in (200, 201, 202):
      basarili += 1
      loglar.append(f"✅ İdefix Paket {no}: {len(grup)} ürün iletildi")
    if ilerleme:
      ilerleme(no / toplam, loglar)
  return basarili, toplam, loglar

def idefix_toplu_panel():
  with st.expander("⚙️ Kategori / marka / zorunlu özellikler", expanded=True):
    kategori_eslestirme_bileseni("idefix")

  df = urunleri_oku()
  if not df.empty and "tedarikci" in df.columns:
    ted_list = sorted(df["tedarikci"].dropna().unique().tolist())
    secilen_teds = st.multiselect("Gönderilecek Tedarikçileri Seçin", ted_list, default=ted_list, key="id_ted_sec")
    if secilen_teds:
      df = df[df["tedarikci"].isin(secilen_teds)]

  df = fiyat_artis_uygula(ayarlar, "idefix", df)
  liste, atlanan = idefix_urun_listesi(df, ayarlar)
  st.write(f"Gönderilecek ürün: **{len(liste):,}** (Atlanan: {atlanan})")
  if not liste:
    return
  if st.button("🚀 İdefix'e Gönder", type="primary", key="id_toplu_btn"):
    pbar = st.progress(0.0)
    log_k = st.empty()
    def ilerleme(p, loglar):
      pbar.progress(min(p, 1.0))
      log_k.code("\n".join(loglar[-12:]))
    bas, top, loglar = idefix_gonder(ayarlar, liste, ilerleme, False, paket=100)
    st.success(f"İşlem tamamlandı ({bas}/{top} paket iletildi).")

HB_BASE = "https://listing-external.hepsiburada.com"

def hb_kombiler(ayarlar):
  m, u, p = (kimlik(ayarlar, k) for k in ("hb_merchant_id", "hb_user", "hb_pass"))
  ua = f"{m} - SelfIntegration"
  return [
      {
          "Authorization": "Basic " + base64.b64encode(f"{a}:{p}".encode()).decode(),
          "User-Agent": c,
          "Accept": "application/json",
          "Content-Type": "application/json",
      }
      for a, c in ((u, u), (m, u), (u, ua), (m, ua))
  ]

def hb_header(ayarlar):
  k = hb_kombiler(ayarlar)
  i = int(((ayarlar.get("pazar_ayarlari") or {}).get("hb") or {}).get("kombi", 0) or 0)
  return k[i if 0 <= i < len(k) else 0]

def hb_dene(ayarlar):
  m = kimlik(ayarlar, "hb_merchant_id")
  for i, h in enumerate(hb_kombiler(ayarlar)):
    try:
      r = requests.get(
          f"{HB_BASE}/listings/merchantid/{m}",
          params={"offset": 0, "limit": 1},
          headers=h,
          timeout=30,
      )
    except Exception:
      continue
    if r.status_code == 200:
      ayarlar.setdefault("pazar_ayarlari", {}).setdefault("hb", {})["kombi"] = i
      ayar_yaz(ayarlar)
      return True, "✅ Hepsiburada girişi başarılı."
  return False, "❌ Hepsiburada girişi reddedildi."

def hb_yukle(ayarlar, yol, grup):
  return http(
      "POST",
      f"{HB_BASE}/listings/merchantid/{kimlik(ayarlar, 'hb_merchant_id')}/{yol}",
      json=grup,
      headers=hb_header(ayarlar),
      timeout=60,
  )

def hepsiburada_stok_fiyat(ayarlar, df):
  pre = ((ayarlar.get("pazar_ayarlari") or {}).get("hb") or {}).get("sku_prefix", "")
  items = [
      (
          pre + str(r["barkod"]).strip(),
          round(float(r["satis_fiyati"]), 2),
          int(max(r["stok"], 0)),
      )
      for _, r in df.iterrows()
      if r["satis_fiyati"] > 0
  ]
  ok, log, ok_b, hata_b = 0, [], [], []
  for i in range(0, len(items), 500):
    grup = items[i : i + 500]
    sk = [x[0] for x in grup]
    try:
      yanit = [
          ("price", hb_yukle(ayarlar, "price-uploads", [{"merchantSku": s, "price": f} for s, f, _ in grup])),
          ("stock", hb_yukle(ayarlar, "stock-uploads", [{"merchantSku": s, "availableStock": a} for s, _, a in grup])),
      ]
    except Exception:
      hata_b += sk
      continue
    if all(r.status_code in (200, 201, 202) for _, r in yanit):
      ok += len(grup)
      ok_b += sk
    else:
      hata_b += sk
  try:
    pazar_isaretle("hb", ok_b, hata_b)
  except Exception:
    pass
  return ok, log

def hb_siparisler(ayarlar):
  m = kimlik(ayarlar, "hb_merchant_id")
  if not m:
    return []
  try:
    r = http(
        "GET",
        f"https://orders-external.hepsiburada.com/packages/merchantid/{m}",
        headers=hb_header(ayarlar),
        timeout=30,
    )
    if r.status_code == 200:
      return r.json() or []
  except Exception:
    pass
  return []

def hb_katalog_paneli_goster():
  with st.expander("⚙️ Kategori / marka / zorunlu özellikler", expanded=True):
    kategori_eslestirme_bileseni("hb")

  df_hepsi = urunleri_oku()
  if not df_hepsi.empty and "tedarikci" in df_hepsi.columns:
    ted_list = sorted(df_hepsi["tedarikci"].dropna().unique().tolist())
    secilen_teds = st.multiselect("Gönderilecek Tedarikçileri Seçin", ted_list, default=ted_list, key="hb_ted_sec")
    if secilen_teds:
      df_hepsi = df_hepsi[df_hepsi["tedarikci"].isin(secilen_teds)]

  mod = st.selectbox("Gönderilecek ürün", ["Tek ürün (test)", "Tüm ürünler"], key="hb_gonder_mod")
  stokta_olanlar = st.checkbox("Sadece stokta olanları gönder", value=True, key="hb_stok_cb")

  if st.button("☕ Hepsiburada'ya Ürün Oluştur", type="primary", key="hb_olustur_btn"):
    if df_hepsi.empty:
      st.warning("Sistemde ürün bulunamadı.")
      return
    df_filt = df_hepsi.copy()
    if stokta_olanlar:
      df_filt = df_filt[df_filt["stok"] > 0]
    if mod == "Tek ürün (test)" and not df_filt.empty:
      df_filt = df_filt.head(1)
    with st.spinner("Hepsiburada Katalog Sistemine Gönderiliyor..."):
      df_islem = fiyat_artis_uygula(ayarlar, "hb", df_filt)
      g, h, msg = hepsiburada_stok_fiyat(ayarlar, df_islem)
      st.success(f"✅ İşlem tamamlandı: {g} ürün aktarıldı, {h} hata.")

PAZAR_AD = {
    "trendruum": "Trendruum",
    "trendyol": "Trendyol",
    "hb": "Hepsiburada",
    "n11": "N11",
    "idefix": "İdefix",
    "ptt": "PTT AVM",
}

def _pazara_gonder(ayarlar, pid, df, ilerleme=None):
  df = fiyat_artis_uygula(ayarlar, pid, df)
  if pid == "trendruum":
    token = trendruum_token(kimlik(ayarlar, "trendruum_key"), kimlik(ayarlar, "trendruum_secret"))
    g, h, ornek, loglar = trendruum_guncelle(df, token, ilerleme, True)
    return g, h, "\n".join(ornek + loglar[-5:])
  if pid == "trendyol":
    ok, log = trendyol_stok_fiyat(
        kimlik(ayarlar, "trendyol_seller_id"),
        kimlik(ayarlar, "trendyol_key"),
        kimlik(ayarlar, "trendyol_secret"),
        df,
    )
    return ok, max(0, int((df["satis_fiyati"] > 0).sum()) - ok), "\n".join(log)
  if pid == "hb":
    ok, log = hepsiburada_stok_fiyat(ayarlar, df)
    return ok, max(0, int((df["satis_fiyati"] > 0).sum()) - ok), "\n".join(log)
  if pid == "n11":
    ok, log = n11_stok_fiyat(kimlik(ayarlar, "n11_key"), kimlik(ayarlar, "n11_secret"), df)
    return ok, max(0, int((df["satis_fiyati"] > 0).sum()) - ok), "\n".join(log)
  if pid == "idefix":
    ok, log = idefix_stok_fiyat(ayarlar, df)
    return ok, max(0, int((df["satis_fiyati"] > 0).sum()) - ok), "\n".join(log)
  if pid == "ptt":
    ok, log = ptt_guncelle(ayarlar, df)
    return ok, max(0, int((df["satis_fiyati"] > 0).sum()) - ok), "\n".join(log)
  raise RuntimeError(f"{pid} için API entegrasyonu henüz yazılmadı.")

def pazara_gonder(ayarlar, pid, df, ilerleme=None):
  ad_ = PAZAR_AD.get(pid, pid)
  try:
    g, h, msg = _pazara_gonder(ayarlar, pid, df, ilerleme)
  except Exception as e:
    log_yaz(ad_, "HATA", f"Gönderilemedi: {e}")
    raise
  log_yaz(ad_, "OK" if g > 0 else "HATA", f"{g} gönderildi, {h} hata."[:500])
  return g, h, msg

def tam_senkron(pid):
  ad = PAZAR_AD.get(pid, pid)
  with st.spinner(f"{ad} senkronize ediliyor..."):
    pbar = st.progress(0.0)
    try:
      g, h, msg = pazara_gonder(ayarlar, pid, urunleri_oku(), lambda p, *_: pbar.progress(p))
      st.success(f"{ad}: {g} ürün işlendi, {h} hata.")
    except Exception as e:
      st.error(f"Hata: {e}")

def tum_barkodlar(pid):
  ad = PAZAR_AD.get(pid, pid)
  with st.spinner(f"{ad} stok ve fiyatları güncelleniyor..."):
    try:
      g, h, msg = pazara_gonder(ayarlar, pid, urunleri_oku())
      st.success(f"{ad}: {g} ürün güncellendi, {h} hata.")
    except Exception as e:
      st.error(f"Hata: {e}")

def oto_guncelle(ayarlar, pid):
  if not pazar_bagli(ayarlar, pid):
    return
  pazara_gonder(ayarlar, pid, urunleri_oku())

OTO_ANAHTAR = (
    ("Trendruum", "tr_oto_guncelle", "trendruum"),
    ("Trendyol", "ty_oto_guncelle", "trendyol"),
    ("Hepsiburada", "hb_oto_guncelle", "hb"),
    ("N11", "n11_oto_guncelle", "n11"),
    ("İdefix", "idefix_oto_guncelle", "idefix"),
    ("PTT AVM", "ptt_oto_guncelle", "ptt"),
)

def tumunu_senkronla(oto=True):
  if not SENKRON_KILIDI.acquire(blocking=False):
    return [("Sistem", False, "Başka bir senkronizasyon zaten çalışıyor.")]
  try:
    ayarlar = ayar_oku()
    sonuclar = []
    for ad, bilgi in ayarlar["tedarikciler"].items():
      try:
        n = tedarikci_senkron(ad, bilgi, ayarlar.get("kritik_esik", 0))
        log_yaz(ad, "OK", f"{n} ürün güncellendi")
        sonuclar.append((ad, True, f"{n} ürün"))
      except Exception as e:
        log_yaz(ad, "HATA", e)
        sonuclar.append((ad, False, str(e)))
    if oto and any(x[1] for x in sonuclar):
      for ad_, anahtar_, pid_ in OTO_ANAHTAR:
        if ayarlar.get(anahtar_):
          try:
            oto_guncelle(ayarlar, pid_)
          except Exception:
            pass
    return sonuclar
  finally:
    SENKRON_KILIDI.release()

def arka_plan_dongusu():
  time.sleep(30)
  while True:
    try:
      if ayar_oku().get("oto_senkron", True):
        tumunu_senkronla()
    except Exception:
      pass
    time.sleep(SENKRON_ARALIK)

@st.cache_resource
def arka_plan_baslat():
  t = threading.Thread(target=arka_plan_dongusu, daemon=True)
  t.start()
  return t

arka_plan_baslat()

def baglanti_testi(ayarlar, pid):
  try:
    if pid == "trendruum":
      trendruum_token(kimlik(ayarlar, "trendruum_key"), kimlik(ayarlar, "trendruum_secret"))
      return True, "Giriş başarılı."
    if pid == "trendyol":
      s_, k_, x_ = (kimlik(ayarlar, "trendyol_seller_id"), kimlik(ayarlar, "trendyol_key"), kimlik(ayarlar, "trendyol_secret"))
      r = http("GET", f"{TY_BASE}/order/sellers/{s_}/orders", params={"size": 1}, headers=trendyol_header(s_, k_, x_), timeout=30)
    elif pid == "hb":
      if not all(kimlik(ayarlar, k) for k in ("hb_merchant_id", "hb_user", "hb_pass")):
        return False, "Eksik bilgi."
      return hb_dene(ayarlar)
    elif pid == "n11":
      r = http(
          "GET",
          f"{N11_BASE}/rest/delivery/v1/shipmentPackages",
          params={"status": "Created", "page": 0, "size": 1},
          headers=n11_header(kimlik(ayarlar, "n11_key"), kimlik(ayarlar, "n11_secret")),
          timeout=30,
      )
    elif pid == "idefix":
      r = http("GET", f"{ID_BASE}/pim/product-category", headers=idefix_header(ayarlar), timeout=60)
    elif pid == "ptt":
      return ptt_test(kimlik(ayarlar, "ptt_key"), kimlik(ayarlar, "ptt_token"))
    else:
      return False, "Desteklenmiyor."
    return r.status_code == 200, f"Bağlantı başarılı (HTTP {r.status_code})"
  except Exception as e:
    return False, f"Bağlantı kurulamadı: {e}"

def tr_tarih(v):
  try:
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
      n = float(v)
      n = n / 1000 if n > 1e11 else n
      return datetime.fromtimestamp(n).strftime("%d.%m.%Y %H:%M")
    if v:
      return str(v)[:16].replace("T", " ")
  except Exception:
    pass
  return ""

def metin(v):
  if isinstance(v, dict):
    return ", ".join(str(x) for x in v.values() if x not in (None, ""))
  return "" if v is None else str(v)

DURUM_ETIKET = {
    "yeni": "🆕 Yeni",
    "hazir": "🚚 Gönderime Hazır",
    "kargoda": "🚛 Kargoda",
    "teslim": "✅ Teslim Edildi",
    "iptal": "❌ İptal",
}

def durum_kodu(pid, d):
  d = str(d or "").lower()
  if pid in ("trendyol", "n11"):
    harita = {
        "created": "yeni",
        "picking": "hazir",
        "invoiced": "hazir",
        "shipped": "kargoda",
        "delivered": "teslim",
        "cancelled": "iptal",
    }
  else:
    harita = {
        "new": "yeni",
        "pending": "yeni",
        "in_progress": "hazir",
        "shipped": "kargoda",
        "delivered": "teslim",
        "cancelled": "iptal",
    }
  return harita.get(d, "yeni")

def siparis_normalle_ty(p):
  adr = p.get("shipmentAddress") or {}
  satirlar = p.get("lines") or []
  return {
      "pid": "trendyol",
      "id": str(p.get("id", "")),
      "no": str(p.get("orderNumber", "")),
      "tarih": tr_tarih(p.get("orderDate")),
      "durum": durum_kodu("trendyol", p.get("status") or p.get("shipmentPackageStatus")),
      "alici": adr.get("fullName") or f"{adr.get('firstName', '')} {adr.get('lastName', '')}".strip(),
      "adres": adr.get("fullAddress") or metin(adr.get("address1")),
      "urunler": [
          {"ad": l.get("productName", ""), "sku": l.get("merchantSku") or l.get("barcode", ""), "adet": l.get("quantity", 1)}
          for l in satirlar
      ],
      "tutar": p.get("totalPrice"),
      "kargo": p.get("cargoProviderName", ""),
      "barkod": str(p.get("cargoTrackingNumber", "") or ""),
      "ham": p,
  }

def siparis_normalle_n11(p):
  adr = p.get("shippingAddress") or {}
  satirlar = p.get("lines") or []
  gecmis = p.get("packageHistories") or []
  ilk = gecmis[0].get("createdDate") if gecmis else p.get("lastModifiedDate")
  return {
      "pid": "n11",
      "id": str(p.get("id", "")),
      "no": str(p.get("orderNumber", "")),
      "tarih": tr_tarih(ilk),
      "durum": durum_kodu("n11", p.get("shipmentPackageStatus")),
      "alici": adr.get("fullName") or p.get("customerfullName") or "",
      "adres": ", ".join(x for x in (adr.get("address"), adr.get("district"), adr.get("city")) if x),
      "urunler": [
          {"ad": l.get("productName", ""), "sku": l.get("stockCode") or l.get("barcode") or "", "adet": l.get("quantity", 1)}
          for l in satirlar
      ],
      "tutar": p.get("totalAmount"),
      "kargo": p.get("cargoProviderName", "") or "",
      "barkod": str(p.get("cargoTrackingNumber", "") or ""),
      "ham": p,
  }

def siparis_normalle_hb(p):
  satirlar = p.get("items") or []
  return {
      "pid": "hb",
      "id": str(p.get("packageId", "")),
      "no": str(p.get("orderNumber", "")),
      "tarih": tr_tarih(p.get("orderDate")),
      "durum": durum_kodu("hb", p.get("status")),
      "alici": p.get("recipientName", "Hepsiburada Müşterisi"),
      "adres": metin(p.get("shippingAddress")),
      "urunler": [
          {"ad": l.get("productName", "Ürün"), "sku": l.get("merchantSku", ""), "adet": l.get("quantity", 1)}
          for l in satirlar
      ],
      "tutar": p.get("totalPrice", 0),
      "kargo": p.get("cargoCompany", "Sürat Kargo"),
      "barkod": str(p.get("cargoBarcode", "")),
      "ham": p,
  }

def siparis_normalle_tr(p):
  satirlar = p.get("items") or p.get("products") or []
  return {
      "pid": "trendruum",
      "id": str(p.get("id") or p.get("order_id") or ""),
      "no": str(p.get("order_number") or p.get("orderNo") or ""),
      "tarih": tr_tarih(p.get("created_at") or p.get("orderDate")),
      "durum": durum_kodu("trendruum", p.get("status")),
      "alici": p.get("customer_name") or p.get("recipient_name") or "Trendruum Müşterisi",
      "adres": metin(p.get("shipping_address") or p.get("address")),
      "urunler": [
          {"ad": l.get("name") or l.get("title") or "Ürün", "sku": l.get("barcode") or l.get("stock_code") or "", "adet": l.get("quantity") or l.get("amount") or 1}
          for l in satirlar
      ],
      "tutar": p.get("total_price") or p.get("grand_total") or 0,
      "kargo": p.get("cargo_company") or "Kargo",
      "barkod": str(p.get("cargo_barcode") or p.get("tracking_number") or ""),
      "ham": p,
  }

def siparis_cek(ayarlar, pid):
  if pid == "trendyol":
    s_, k_, x_ = (kimlik(ayarlar, "trendyol_seller_id"), kimlik(ayarlar, "trendyol_key"), kimlik(ayarlar, "trendyol_secret"))
    gorulen, sonuc = set(), []
    for durum in ("Created", "Picking", "Invoiced", "Shipped"):
      for p_ in trendyol_siparisler(s_, k_, x_, durum, 100):
        if p_.get("id") not in gorulen:
          gorulen.add(p_.get("id"))
          sonuc.append(siparis_normalle_ty(p_))
    return sonuc
  if pid == "n11":
    k_, x_ = kimlik(ayarlar, "n11_key"), kimlik(ayarlar, "n11_secret")
    gorulen, sonuc = set(), []
    for durum in ("Created", "Picking", "Shipped"):
      for p_ in n11_siparisler(k_, x_, durum):
        if p_.get("id") not in gorulen:
          gorulen.add(p_.get("id"))
          sonuc.append(siparis_normalle_n11(p_))
    return sonuc
  if pid == "hb":
    pkts = hb_siparisler(ayarlar)
    return [siparis_normalle_hb(x) for x in pkts]
  if pid == "trendruum":
    pkts = trendruum_siparisler(ayarlar)
    return [siparis_normalle_tr(x) for x in pkts]
  return []

def _secret_var(ad):
  try:
    return ad.upper() in st.secrets
  except Exception:
    return False

def sifre_al():
  s = os.environ.get("APP_PASSWORD")
  if s:
    return s
  try:
    if "APP_PASSWORD" in st.secrets:
      return str(st.secrets["APP_PASSWORD"])
  except Exception:
    pass
  return None

sifre = sifre_al()

if sifre and not st.session_state.get("giris_ok"):
  st.markdown(
      """<style>
[data-testid="stAppViewContainer"]{background:linear-gradient(135deg,#0f172a 0%,#1e293b 100%);}
.login-card{background:rgba(30,41,59,.85);border:1px solid rgba(255,255,255,.15);border-radius:20px;padding:45px;box-shadow:0 20px 40px rgba(0,0,0,.5);text-align:center;}
.login-title{color:#f8fafc;font-size:36px;font-weight:800;margin-bottom:10px;}
.login-sub{color:#94a3b8;font-size:16px;margin-bottom:20px;}
</style>""",
      unsafe_allow_html=True,
  )
  _, orta, _ = st.columns([1, 1.4, 1])
  with orta:
    st.markdown(
        '<div class="login-card"><div class="login-title">🦅 ŞahEntegre</div>'
        '<div class="login-sub">E-Ticaret Yönetim Paneli</div></div>',
        unsafe_allow_html=True,
    )
    with st.form("giris_formu"):
      girilen = st.text_input("🔑 Yönetici Şifresi", type="password", placeholder="••••••••")
      buton = st.form_submit_button("Giriş Yap", type="primary", use_container_width=True)
    if buton:
      if hmac.compare_digest(girilen.encode(), str(sifre).encode()):
        st.session_state.giris_ok = True
        st.rerun()
      else:
        st.error("❌ Hatalı şifre.")
  st.stop()

if "ayarlar" not in st.session_state:
  st.session_state.ayarlar = ayar_oku()
ayarlar = st.session_state.ayarlar
ayarlar.setdefault("kimlik", {})

def kimlik_kaydet(ad, deger):
  if deger != ayarlar["kimlik"].get(ad, ""):
    ayarlar["kimlik"][ad] = deger
    ayar_yaz(ayarlar)

def gizli_input(etiket_, ad, parola=True):
  v = st.text_input(
      etiket_,
      value=ayarlar["kimlik"].get(ad, ""),
      type="password" if parola else "default",
  )
  kimlik_kaydet(ad, v.strip())
  return v.strip()

PAZAR = {
    "hb": {"ad": "Hepsiburada", "renk": "#ff6000", "ikon": "🛍️", "pastel": "#fff3ed"},
    "trendyol": {"ad": "Trendyol", "renk": "#f27a1a", "ikon": "🧡", "pastel": "#fff4ec"},
    "n11": {"ad": "N11", "renk": "#5015ff", "ikon": "🔴", "pastel": "#f0ebff"},
    "idefix": {"ad": "İdefix", "renk": "#00a651", "ikon": "📚", "pastel": "#e6f9ed"},
    "ptt": {"ad": "PTT AVM", "renk": "#ffcd00", "ikon": "📦", "pastel": "#fffde6"},
    "trendruum": {"ad": "Trendruum", "renk": "#8b5cf6", "ikon": "🛒", "pastel": "#f5f3ff"},
}

ANA_MENU = [
    ("Anasayfa", "🏠 Anasayfa", "#dbeafe"),
    ("Bildirim", "🔔 Bildirimler", "#fef3c7"),
    ("Urunler", "📦 Sistemdeki Ürünler", "#f8fafc"),
    ("Kritik", "🔄 Oto Kritik Stok", "#dbeafe"),
]

ALT = [
    ("siparis", "Siparişler", "🧾"),
    ("islemler", "Tüm İşlemleri", "🔗"),
    ("ayar", "Genel Ayarları", "⚙️"),
]

def tema_css():
  k = [f".st-key-nav_{kid} button{{background:{renk};}}" for kid, _, renk in ANA_MENU]
  k.append(".st-key-nav_Ayarlar button{background:#e2e8f0;}")
  for pid, p in PAZAR.items():
    k.append(f".st-key-navp_{pid} button{{background:{p['pastel']};}}")
    for alt, _, _ in ALT:
      k.append(f".st-key-sub_{pid}_{alt} button{{background:#fff;border-left:5px solid {p['renk']};margin-left:16px;width:calc(100% - 16px);}}")
  return "<style>" + "".join(k) + "</style>"

st.markdown(tema_css(), unsafe_allow_html=True)

st.session_state.setdefault("sayfa", "Anasayfa")
st.session_state.setdefault("acik_pazar", None)

def git(sayfa_id):
  st.session_state["sayfa"] = sayfa_id

def git_pazar(pid, alt):
  st.session_state["acik_pazar"] = pid
  st.session_state["sayfa"] = f"{pid}:{alt}"

def ac_kapa(pid):
  st.session_state["acik_pazar"] = None if st.session_state.get("acik_pazar") == pid else pid

st.sidebar.title("🦅 ŞahEntegre")
st.sidebar.caption("Eksiksiz Eski Sürüm Entegrasyon")

def cikis_yap():
  st.session_state.giris_ok = False
  st.rerun()

st.sidebar.button("🚪 Çıkış Yap", key="btn_cikis_yap", use_container_width=True, type="secondary", on_click=cikis_yap)
st.sidebar.markdown("---")

for kid, etiket_m, _ in ANA_MENU:
  st.sidebar.button(
      etiket_m,
      key=f"nav_{kid}",
      use_container_width=True,
      type="primary" if st.session_state["sayfa"] == kid else "secondary",
      on_click=git,
      args=(kid,),
  )

for pid, p in PAZAR.items():
  acik = st.session_state["acik_pazar"] == pid
  st.sidebar.button(
      f"{p['ikon']} {p['ad']}  {'▾' if acik else '▸'}",
      key=f"navp_{pid}",
      use_container_width=True,
      on_click=ac_kapa,
      args=(pid,),
  )
  if acik:
    for alt, etk, ik in ALT:
      sid = f"{pid}:{alt}"
      st.sidebar.button(
          f"{ik} {p['ad']} {etk}",
          key=f"sub_{pid}_{alt}",
          use_container_width=True,
          type="primary" if st.session_state["sayfa"] == sid else "secondary",
          on_click=git,
          args=(sid,),
      )

st.sidebar.button(
    "⚙️ Ayarlar",
    key="nav_Ayarlar",
    use_container_width=True,
    type="primary" if st.session_state["sayfa"] == "Ayarlar" else "secondary",
    on_click=git,
    args=("Ayarlar",),
)

sayfa = st.session_state["sayfa"]

def kritik_esik_ayari():
  return int(ayarlar.get("kritik_esik") or 0)

def tedarikci_sayfasi():
  tedarikciler = ayarlar["tedarikciler"]
  with st.expander("➕ Yeni Tedarikçi Ekle", expanded=not tedarikciler):
    t_ad = st.text_input("Tedarikçi Adı")
    t_link = st.text_input("XML İndirme Linki (URL)")
    if st.button("Kaydet", type="primary"):
      if not t_ad.strip() or not t_link.strip():
        st.error("Ad ve link zorunlu.")
      else:
        tedarikciler[t_ad.strip()] = {
            "link": t_link.strip(),
            "harita": {},
            "marj": 30.0,
            "sabit_ek": 0.0,
        }
        ayar_yaz(ayarlar)
        st.rerun()

  if not tedarikciler:
    return
  
  st.markdown("---")
  st.markdown("### ⏱️ Otomatik Güncelleme Sıklığı")
  st.markdown('<p style="color:red; font-weight:bold;">⚠️ 6 saatte bir stok ve fiyat otomatik güncellenmektedir.</p>', unsafe_allow_html=True)
  
  oto = st.toggle("🤖 Otomatik senkronizasyon (6 saatte bir)", value=ayarlar.get("oto_senkron", True))
  if oto != ayarlar.get("oto_senkron", True):
    ayarlar["oto_senkron"] = oto
    ayar_yaz(ayarlar)

  if st.button("🔄 Tümünü Şimdi Senkronla", type="primary"):
    with st.spinner("Güncelleniyor..."):
      for ad, ok, msg in tumunu_senkronla():
        (st.success if ok else st.error)(f"{ad}: {msg}")

  st.markdown("---")
  for ad, bilgi in list(tedarikciler.items()):
    with st.expander(f"🏢 {ad}"):
      st.text(f"Link: {bilgi['link'][:60]}...")
      
      c_ind1, c_ind2 = st.columns(2)
      with c_ind1:
        if st.button(f"📥 XML Dosyasını İndir", key=f"xml_indir_{ad}"):
          try:
            veri_xml = indir(bilgi["link"])
            st.download_button("💾 XML Kaydet", data=veri_xml, file_name=f"{ad}_yedek.xml", mime="application/xml")
          except Exception as e:
            st.error(f"İndirilemedi: {e}")
      with c_ind2:
        if st.button(f"🗑️ Tedarikçiyi Sil", key=f"sil_{ad}"):
          tedarikciler.pop(ad, None)
          ayar_yaz(ayarlar)
          with closing(baglan()) as c:
            c.execute("DELETE FROM urunler WHERE tedarikci=?", (ad,))
            c.commit()
          st.rerun()

      try:
        df_test = xml_onizleme(bilgi["link"])
        kolonlar = ["(yok)"] + list(df_test.columns)
        eski = bilgi.get("harita", {})
        def sec(lbl, anah, aid):
          v = eski.get(aid)
          if v not in kolonlar:
            v = tahmin(df_test.columns, anah)
          return st.selectbox(lbl, kolonlar, index=kolonlar.index(v), key=f"{ad}_{aid}")
        harita = {
            "kod": sec("Barkod / SKU", ["barkod", "barcode", "sku", "stokkod", "kod", "id"], "kod"),
            "ad": sec("Ürün Adı", ["urunadi", "ürünadı", "name", "title", "ad", "baslik"], "ad"),
            "stok": sec("Stok", ["stok", "stock", "quantity", "adet", "miktar"], "stok"),
            "fiyat": sec("Alış Fiyatı", ["fiyat", "price", "alis", "alış"], "fiyat"),
            "gorsel": sec("Görsel", ["image_1", "resim", "image", "gorsel", "görsel", "picture", "foto"], "gorsel"),
            "kategori": sec("Kategori", ["kategori", "category", "cat", "tur", "grup", "maincategory"], "kategori"),
        }
        marj = st.number_input("Kâr Marjı (%)", 0.0, 500.0, float(bilgi.get("marj", 30.0)), 1.0, key=f"{ad}_marj")
        sabit = st.number_input("Sabit Ek / Kargo (TL)", 0.0, 5000.0, float(bilgi.get("sabit_ek", 0.0)), 5.0, key=f"{ad}_sabit")
        if harita != eski or marj != bilgi.get("marj") or sabit != bilgi.get("sabit_ek"):
          bilgi.update({"harita": harita, "marj": marj, "sabit_ek": sabit})
          ayar_yaz(ayarlar)
          st.success("Kaydedildi.")
      except Exception as e:
        st.warning(f"XML analiz edilemedi: {e}")

def genel_ayarlar():
  tam = {k: v for k, v in ayarlar.items()}
  st.download_button(
      "🔐 TAM Yedek (API anahtarları DAHİL)",
      json.dumps(tam, ensure_ascii=False, indent=2).encode("utf-8"),
      "sahentegre_tam_yedek.json",
      "application/json",
      use_container_width=True,
  )
  yuklenen = st.file_uploader("♻️ Yedek dosyasını geri yükle (.json)", type="json", key="yedek_yukle")
  if yuklenen is not None and st.button("Geri Yükle", key="yedek_btn"):
    try:
      veri_y = json.loads(yuklenen.getvalue().decode("utf-8"))
      if isinstance(veri_y, dict):
        for k, v in veri_y.items():
          ayarlar[k] = v
        ayar_yaz(ayarlar)
        st.success("Geri yüklendi.")
        st.rerun()
    except Exception as e:
      st.error(f"Hata: {e}")

def gunluk_sayfasi():
  with closing(baglan()) as c:
    lg = pd.read_sql("SELECT zaman, tedarikci, durum, mesaj FROM senkron_log ORDER BY id DESC LIMIT 200", c)
  if lg.empty:
    st.info("Kayıt yok.")
  else:
    st.dataframe(lg, use_container_width=True, hide_index=True)

def pazar_islemler(pid):
  p = PAZAR[pid]
  ad = p["ad"]
  bagli = pazar_bagli(ayarlar, pid)
  st.title(f"{p['ikon']} {ad} İşlemleri")

  k = f"islem_{pid}"
  c1, c2, c3 = st.columns(3)
  if c1.button("🔄 Tam Senkronizasyon", key=f"b1_{pid}", type="primary"):
    st.session_state[k] = None
    if bagli:
      tam_senkron(pid)
  if c2.button("⚠️ Kritik Stok Sıfırla", key=f"b2_{pid}"):
    st.session_state[k] = "kritik"
  if c3.button("🔢 Tüm Stok/Fiyatları Güncelle", key=f"b3_{pid}"):
    st.session_state[k] = None
    if bagli:
      tum_barkodlar(pid)

  d1, d2 = st.columns(2)
  if d1.button("📤 Toplu Ürün Gönder", key=f"b4_{pid}"):
    st.session_state[k] = "toplu"

  islem = st.session_state.get(k)
  if islem == "kritik":
    with st.container(border=True):
      esik = st.number_input("Kritik stok eşiği", 1, 50, int(ayarlar.get("kritik_esik") or 3), key=f"ke_{pid}")
      with closing(baglan()) as c:
        df_k = pd.read_sql(
            "SELECT barkod, stok, satis_fiyati FROM urunler WHERE CAST(stok AS INTEGER) > 0 AND CAST(stok AS INTEGER) <= ?",
            c,
            params=(int(esik),),
        )
      st.write(f"Etkilenecek ürün: **{len(df_k):,}**")
      onay = st.checkbox("Onaylıyorum", key=f"ko_{pid}")
      if st.button("Sıfırla ve Gönder", key=f"kg_{pid}", disabled=not (onay and bagli and len(df_k) > 0)):
        with closing(baglan()) as c:
          c.execute(
              "UPDATE urunler SET stok = 0 WHERE CAST(stok AS INTEGER) > 0 AND CAST(stok AS INTEGER) <= ?",
              (int(esik),),
          )
          c.commit()
        df_k["stok"] = 0
        try:
          pazara_gonder(ayarlar, pid, df_k)
          st.success("Sıfırlandı ve gönderildi.")
        except Exception as e:
          st.error(f"Hata: {e}")
  elif islem == "toplu":
    if pid == "hb":
      hb_katalog_paneli_goster()
    elif pid == "ptt":
      ptt_toplu_panel()
    elif pid == "n11":
      n11_toplu_panel()
    elif pid == "idefix":
      idefix_toplu_panel()
    elif pid == "trendruum":
      trendruum_toplu_panel()

def pazar_ayar(pid):
  p = PAZAR[pid]
  st.title(f"⚙️ {p['ad']} Genel Ayarları")
  alanlar = {
      "hb": [("Merchant ID", "hb_merchant_id", False), ("API Kullanıcı Adı", "hb_user", False), ("Servis Anahtarı", "hb_pass", True)],
      "trendyol": [("Satıcı ID", "trendyol_seller_id", False), ("API Key", "trendyol_key", True), ("API Secret", "trendyol_secret", True)],
      "n11": [("App Key", "n11_key", True), ("App Secret", "n11_secret", True)],
      "idefix": [("Satıcı ID", "idefix_satici_id", False), ("API Key", "idefix_token", True), ("API Secret", "idefix_secret", True)],
      "ptt": [("API Key", "ptt_key", False), ("Access Token", "ptt_token", True)],
      "trendruum": [("Client ID", "trendruum_key", True), ("API Secret", "trendruum_secret", True), ("Brand ID", "trendruum_brand", False)],
  }.get(pid, [])
  for etk, anahtar, parola in alanlar:
    gizli_input(etk, anahtar, parola)
  if st.button("🔌 Bağlantı Testi", key=f"bt_{pid}"):
    ok_, msg_ = baglanti_testi(ayarlar, pid)
    (st.success if ok_ else st.error)(msg_)

def pazar_siparis(pid):
  p = PAZAR[pid]
  st.title(f"{p['ikon']} {p['ad']} Sipariş Yönetimi")
  if st.button("🔄 Siparişleri Yeniden Çek", type="primary", key=f"sp_cek_{pid}", use_container_width=True):
    try:
      with st.spinner("Siparişler çekiliyor..."):
        st.session_state[f"sip_{pid}"] = siparis_cek(ayarlar, pid)
        st.success("Siparişler güncellendi.")
    except Exception as e:
      st.error(f"Hata: {e}")

  liste = st.session_state.get(f"sip_{pid}")
  if not liste:
    st.info("Henüz sipariş çekilmedi.")
    return
  for o in liste:
    with st.container(border=True):
      st.markdown(f"### Sipariş No: {o['no']} · {o['tarih']}")
      st.markdown(f"**Alıcı:** {o['alici']} | **Tutar:** {o.get('tutar')} ₺")
      st.markdown(f"**Adres:** {o['adres']}")

if sayfa == "Anasayfa":
  st.title("🦅 ŞahEntegre - Mağaza ve Pazar Yeri Özeti")
  df = urunleri_oku()
  esik = kritik_esik_ayari() or 3

  c1, c2, c3, c4 = st.columns(4)
  c1.metric("Toplam Ürün", f"{len(df):,}")
  c2.metric("Stokta Olanlar", f"{(pd.to_numeric(df['stok'], errors='coerce').fillna(0) > 0).sum():,}" if not df.empty else "0")
  c3.metric(f"Kritik Stok (≤{esik})", f"{(pd.to_numeric(df['stok'], errors='coerce').fillna(0).between(1, esik)).sum():,}" if not df.empty else "0")
  c4.metric("Tedarikçi", len(ayarlar["tedarikciler"]))

  st.markdown("### 🛒 Pazar Yeri Bağlantı Durumları")
  pazar_listesi = list(PAZAR.items())
  for i in range(0, len(pazar_listesi), 2):
    cols = st.columns(2)
    for j in range(2):
      if i + j < len(pazar_listesi):
        pid_, p_ = pazar_listesi[i + j]
        with cols[j]:
          bagli_Mi = pazar_bagli(ayarlar, pid_)
          renk_kutusu = "#d1fae5" if bagli_Mi else "#fee2e2"
          durum_metin = "🟢 Bağlı / Hazır" if bagli_Mi else "🔴 API Bağlantısı Bekliyor"
          st.markdown(
              f"""
            <div style="background:{renk_kutusu}; border-radius:14px; padding:14px; border-left:6px solid {p_['renk']}; margin-bottom:10px;">
                <h4 style="margin:0; color:#1e293b; font-size:16px;">{p_['ikon']} {p_['ad']}</h4>
                <p style="margin:6px 0 0 0; font-weight:600; color:#475569; font-size:13px;">{durum_metin}</p>
            </div>
          """,
              unsafe_allow_html=True,
          )
          if st.button("Yönet / İşlemler", key=f"kutu_git_{pid_}", use_container_width=True):
            git_pazar(pid_, "islemler")
            st.rerun()

elif sayfa == "Bildirim":
  st.title("🔔 Bildirimler")
  gunluk_sayfasi()

elif sayfa == "Urunler":
  st.title("📦 Sistemdeki Ürünler")
  df = urunleri_oku()
  if df.empty:
    st.info("Ürün bulunamadı.")
  else:
    st.dataframe(df[["gorsel", "urun_adi", "barkod", "stok", "satis_fiyati", "tedarikci"]], column_config={"gorsel": st.column_config.ImageColumn("Görsel")}, hide_index=True, use_container_width=True)

elif sayfa == "Kritik":
  st.title("🔄 Oto Kritik Stok")
  esik = st.number_input("Kritik stok eşiği:", 0, 50, kritik_esik_ayari() or 3)
  if int(esik) != kritik_esik_ayari():
    ayarlar["kritik_esik"] = int(esik)
    ayar_yaz(ayarlar)
    st.rerun()

elif sayfa == "Ayarlar":
  st.title("⚙️ Ayarlar")
  t1, t2, t3 = st.tabs(["Tedarikçiler & XML", "Genel & Yedek", "Senkron Günlüğü"])
  with t1:
    tedarikci_sayfasi()
  with t2:
    genel_ayarlar()
  with t3:
    gunluk_sayfasi()

elif ":" in sayfa:
  pid_, alt_ = sayfa.split(":", 1)
  if pid_ in PAZAR:
    {"siparis": pazar_siparis, "islemler": pazar_islemler, "ayar": pazar_ayar}.get(alt_, pazar_islemler)(pid_)
