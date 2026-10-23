import gzip
import re
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
import pandas as pd


# --- TEDARİKÇİ XML VE NORMALİZASYON MOTORU ---
def etiket(tag):
  return tag.split("}", 1)[-1]


def indir(url):
  if not url.lower().startswith(("http://", "https://")):
    raise ValueError("Yalnızca http/https bağlantıları desteklenir.")
  istek = urllib.request.Request(
      url,
      headers={
          "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
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
    sozluk[anahtar] = (
        (sozluk[anahtar] + "|" + deger) if sozluk[anahtar] else deger
    )
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
  dis = {
      etiket(e.tag)
      for e in kok.iter()
      if etiket(e.tag) in adaylar and not ic_icede(e)
  }
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
    raise ValueError(f"Geçerli XML değil: {ilk}")
  tag = urun_dugumu_bul(kok)
  if not tag:
    raise ValueError("XML içinde ürün kaydı bulunamadı.")
  satirlar = [duzlestir(e) for e in kok.iter() if etiket(e.tag) == tag]
  return pd.DataFrame(satirlar).fillna("")


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
  kategori = (
      df[kk].astype(str)
      if kk in df.columns
      else pd.Series(["Genel"] * len(df), index=df.index)
  )

  gorsel_col = harita.get("gorsel", "(yok)")
  gorseller = (
      df[gorsel_col].astype(str).str.split("|").str[0].str.strip()
      if gorsel_col in df.columns
      else pd.Series([""] * len(df), index=df.index)
  )

  out = pd.DataFrame({
      "gorsel": gorseller.str.replace("http://", "https://", regex=False),
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
