import base64
import gzip
import hashlib
import hmac
import json
import os
import re
import sqlite3
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="ŞahEntegre", page_icon="👑", layout="wide")

BASE = Path(__file__).parent
DB_DOSYA = BASE / "metentegre.db"
AYAR_DOSYA = BASE / "ayarlar.json"
SENKRON_ARALIK = 6 * 3600
KILIT = threading.Lock()

KIMLIK_ALANLARI = [
    "trendruum_key", "trendruum_secret", "trendruum_brand", "trendruum_category",
    "trendyol_seller_id", "trendyol_key", "trendyol_secret",
    "hb_merchant_id", "hb_user", "hb_pass",
    "idefix_satici_id", "idefix_token", "idefix_secret",
    "n11_key", "n11_secret", "n11_category"
]

VARSAYILAN = {
    "tedarikciler": {},
    "kimlik": {},
    "kategori_eslesme": {},
    "n11_kategori_eslesme": {},
    "kritik_esik": 0,
    "oto_senkron": True,
    "tr_oto_guncelle": False,
    "ty_oto_guncelle": False,
    "n11_oto_guncelle": False,
    "pazar_ayarlari": {},
}

def _ayar_tohumu():
    ham = os.environ.get("AYARLAR_JSON")
    if not ham:
        try:
            if "AYARLAR_JSON" in st.secrets:
                ham = str(st.secrets["AYARLAR_JSON"])
        except Exception:
            pass
    try:
        return json.loads(ham) if ham else {}
    except Exception:
        return {}

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
    if not veri["tedarikciler"]:
        for k, v in _ayar_tohumu().items():
            if k != "kimlik" and not veri.get(k):
                veri[k] = v
    for k in KIMLIK_ALANLARI:
        if k in veri and isinstance(veri[k], str):
            veri["kimlik"].setdefault(k, veri.pop(k))
    return veri

def ayar_yaz(ayarlar):
    with KILIT:
        tmp = AYAR_DOSYA.with_suffix(".tmp")
        tmp.write_text(json.dumps(ayarlar, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(AYAR_DOSYA)

def kimlik(ayarlar, ad):
    env = os.environ.get(ad.upper())
    if env:
        return env
    try:
        if ad.upper() in st.secrets:
            return str(st.secrets[ad.upper()])
    except Exception:
        pass
    return ayarlar.get("kimlik", {}).get(ad, "")

def baglan():
    conn = sqlite3.connect(DB_DOSYA, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def db_olustur():
    with closing(baglan()) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS urunler (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tedarikci TEXT, barkod TEXT, urun_adi TEXT, stok INTEGER,
                alis_fiyati REAL, satis_fiyati REAL, gorsel TEXT, kategori TEXT
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS senkron_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                zaman TEXT, tedarikci TEXT, durum TEXT, mesaj TEXT
            )""")
        c.execute("CREATE INDEX IF NOT EXISTS ix_urun ON urunler(tedarikci, barkod)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS destek (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tarih TEXT, konu TEXT, mesaj TEXT, durum TEXT
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS duyurular (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tarih TEXT, baslik TEXT, icerik TEXT
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS pazar_durum (
                pazar TEXT, barkod TEXT, durum TEXT, zaman TEXT,
                PRIMARY KEY (pazar, barkod)
            )""")
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
    rows = [(pazar, str(b), "ok", z) for b in ok_list] + [(pazar, str(b), "hata", z) for b in hata_list]
    if not rows:
        return
    with closing(baglan()) as c:
        c.executemany("INSERT OR REPLACE INTO pazar_durum (pazar, barkod, durum, zaman) VALUES (?,?,?,?)", rows)
        c.commit()

def etiket(tag):
    return tag.split("}", 1)[-1]

def indir(url):
    istek = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept": "application/xml,text/xml,*/*",
        "Accept-Encoding": "gzip",
    })
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
    stok = kol("stok").map(sayi).clip(lower=0).astype(int)
    if kritik_esik and kritik_esik > 0:
        stok = stok.where(stok > kritik_esik, 0)

    kk = harita.get("kategori", "(yok)")
    if kk == "(yok)" or kk not in df.columns:
        kk = tahmin(df.columns, ["kategori", "category", "cat", "tur", "grup", "maincategory"])
    kategori = df[kk].astype(str) if kk in df.columns else pd.Series(["Genel"] * len(df), index=df.index)

    out = pd.DataFrame({
        "tedarikci": tedarikci,
        "barkod": kol("kod").astype(str).str.strip(),
        "urun_adi": kol("ad").astype(str).str.strip(),
        "stok": stok,
        "alis_fiyati": alis.round(2),
        "satis_fiyati": satis.round(2),
        "gorsel": ilk_gorsel(df, harita.get("gorsel", "(yok)")),
        "kategori": kategori,
    })
    out = out[(out["barkod"] != "") & (out["urun_adi"] != "")]
    return out.drop_duplicates(subset=["barkod"], keep="first")

def tedarikci_senkron(ad, bilgi, kritik_esik=0):
    df_ham = xml_oku(indir(bilgi["link"]))
    df = normalle(ad, df_ham, bilgi.get("harita", {}), float(bilgi.get("marj", 30.0)),
                  float(bilgi.get("sabit_ek", 0.0)), kritik_esik)
    if df.empty:
        raise ValueError("XML'den geçerli ürün çıkmadı.")
    with closing(baglan()) as c:
        c.execute("BEGIN")
        c.execute("DELETE FROM urunler WHERE tedarikci = ?", (ad,))
        c.executemany(
            "INSERT INTO urunler (tedarikci,barkod,urun_adi,stok,alis_fiyati,satis_fiyati,gorsel,kategori) "
            "VALUES (?,?,?,?,?,?,?,?)",
            df[["tedarikci", "barkod", "urun_adi", "stok", "alis_fiyati",
                "satis_fiyati", "gorsel", "kategori"]].itertuples(index=False, name=None),
        )
        c.commit()
    return len(df)

def tumunu_senkronla(oto=True):
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
    return sonuclar

TR_BASE = "https://api.trendruum.com/api/v1/integration"

def sabit_barkod(kod):
    temiz = "".join(ch for ch in str(kod) if ch.isdigit())
    if len(temiz) >= 8:
        return temiz
    h = int(hashlib.md5(str(kod).encode()).hexdigest(), 16) % 10**9
    return f"869{h:09d}"

def trendruum_token(key, secret):
    r = requests.post(f"{TR_BASE}/auth/login",
                      json={"client_id": key.strip(), "client_secret": secret.strip()}, timeout=30)
    try:
        j = r.json()
    except Exception:
        j = {}
    token = (j.get("data") or {}).get("token") or j.get("token") or ""
    if r.status_code != 200 or not token:
        raise RuntimeError(f"Giriş başarısız (HTTP {r.status_code}): {r.text[:300]}")
    return token

def trendruum_guncelle(df, token, ilerleme=None):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    items, orijin = [], {}
    for _, r in df.iterrows():
        if r["satis_fiyati"] > 0:
            sb = sabit_barkod(r["barkod"])
            orijin[sb] = str(r["barkod"])
            items.append({"barcode": sb, "price": float(r["satis_fiyati"]), "stock": int(r["stok"])})
    toplam = max(1, (len(items) + 999) // 1000)
    guncel, hata, ornek, loglar, hata_s = 0, 0, [], [], set()
    for i in range(0, len(items), 1000):
        grup = items[i:i + 1000]
        r = requests.post(f"{TR_BASE}/products/bulk-update", json={"products": grup}, headers=headers, timeout=120)
        if r.status_code == 200:
            d = r.json().get("data") or {}
            guncel += int(d.get("updated_count", 0))
            loglar.append(f"✅ Paket güncellendi.")
        else:
            hata += len(grup)
            loglar.append(f"❌ Paket hatası: {r.status_code}")
    return guncel, hata, ornek[:5], loglar

TY_BASE = "https://apigw.trendyol.com/integration"

def trendyol_header(seller, key, secret):
    tok = base64.b64encode(f"{key}:{secret}".encode()).decode()
    return {"Authorization": f"Basic {tok}", "User-Agent": f"{seller} - SelfIntegration",
            "Content-Type": "application/json"}

def trendyol_siparisler(seller, key, secret, durum="Created", boyut=50):
    r = requests.get(f"{TY_BASE}/order/sellers/{seller}/orders",
                     params={"status": durum, "size": boyut, "orderByField": "PackageLastModifiedDate",
                             "orderByDirection": "DESC"},
                     headers=trendyol_header(seller, key, secret), timeout=30)
    r.raise_for_status()
    return r.json().get("content", [])

def trendyol_stok_fiyat(seller, key, secret, df):
    items = [{"barcode": str(r["barkod"]), "quantity": int(min(r["stok"], 20000)),
              "salePrice": float(r["satis_fiyati"]), "listPrice": float(r["satis_fiyati"])}
             for _, r in df.iterrows() if r["satis_fiyati"] > 0]
    ok, log, ok_b, hata_b = 0, [], [], []
    for i in range(0, len(items), 1000):
        grup = items[i:i + 1000]
        r = requests.post(f"{TY_BASE}/inventory/sellers/{seller}/products/price-and-inventory",
                          json={"items": grup},
                          headers=trendyol_header(seller, key, secret), timeout=60)
        if r.status_code == 200:
            ok += len(grup)
            ok_b += [x["barcode"] for x in grup]
            log.append(f"✅ Trendyol paket gönderildi.")
        else:
            hata_b += [x["barcode"] for x in grup]
            log.append(f"❌ Trendyol hata: {r.status_code}")
    return ok, log

N11_BASE = "https://api.n11.com"

def n11_header(key, secret):
    return {"appKey": key, "appSecret": secret, "Content-Type": "application/json"}

def n11_stok_fiyat(key, secret, df):
    skular = []
    for _, r in df.iterrows():
        if r["satis_fiyati"] > 0:
            fiyat = round(float(r["satis_fiyati"]), 2)
            skular.append({"stockCode": str(r["barkod"]), "listPrice": fiyat, "salePrice": fiyat,
                           "quantity": int(r["stok"]), "currencyType": "TL"})
    ok, log, ok_b, hata_b = 0, [], [], []
    for i in range(0, len(skular), 1000):
        grup = skular[i:i + 1000]
        try:
            r = requests.post(f"{N11_BASE}/ms/product/tasks/price-stock-update",
                              json={"payload": {"integrator": "SahEntegre", "skus": grup}},
                              headers=n11_header(key, secret), timeout=120)
            if r.status_code == 200:
                ok += len(grup)
                ok_b += [x["stockCode"] for x in grup]
                log.append(f"✅ N11 fiyat/stok kuyruğa alındı.")
            else:
                hata_b += [x["stockCode"] for x in grup]
                log.append(f"❌ N11 HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            hata_b += [x["stockCode"] for x in grup]
            log.append(f"⚠️ N11 bağlantı hatası: {e}")
    return ok, log

def n11_yeni_urun_gonder(key, secret, df, varsayilan_kategori=""):
    skular = []
    for _, r in df.iterrows():
        if r["satis_fiyati"] > 0:
            fiyat = round(float(r["satis_fiyati"]), 2)
            skular.append({
                "productCode": str(r["barkod"]),
                "title": str(r["urun_adi"])[:100],
                "price": fiyat,
                "quantity": int(r["stok"]),
                "categoryId": int(varsayilan_kategori) if str(varsayilan_kategori).isdigit() else 1,
                "images": [{"url": str(r["gorsel"])}] if str(r["gorsel"]).startswith("http") else []
            })
    ok, log, ok_b, hata_b = 0, [], [], []
    for i in range(0, len(skular), 100):
        grup = skular[i:i + 100]
        try:
            r = requests.post(f"{N11_BASE}/ws/productService.wsdl",
                              json={"products": grup},
                              headers=n11_header(key, secret), timeout=60)
            if r.status_code == 200:
                ok += len(grup)
                ok_b += [x["productCode"] for x in grup]
                log.append(f"✅ N11 yeni ürünler başarıyla gönderildi.")
            else:
                hata_b += [x["productCode"] for x in grup]
                log.append(f"❌ N11 Ürün Gönderim Hatası (HTTP {r.status_code})")
        except Exception as e:
            hata_b += [x["productCode"] for x in grup]
            log.append(f"⚠️ N11 İstek Hatası: {e}")
    return ok, log

def n11_siparisler(key, secret, durum="Created", sayfa_siniri=3):
    sonuc = []
    for sayfa_ in range(sayfa_siniri):
        try:
            r = requests.get(f"{N11_BASE}/rest/delivery/v1/shipmentPackages",
                             params={"status": durum, "page": sayfa_, "size": 100, "orderByDirection": "DESC"},
                             headers=n11_header(key, secret), timeout=60)
            if r.status_code == 200:
                icerik = r.json().get("content") or []
                sonuc += icerik
                if len(icerik) < 100:
                    break
        except Exception:
            break
    return sonuc

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

def pazar_bagli(ayarlar, pid):
    gerek = {"trendruum": ["trendruum_key", "trendruum_secret"],
             "trendyol": ["trendyol_seller_id", "trendyol_key", "trendyol_secret"],
             "n11": ["n11_key", "n11_secret"]}.get(pid)
    return bool(gerek) and all(kimlik(ayarlar, k) for k in gerek)

def pazara_gonder(ayarlar, pid, df):
    df = fiyat_artis_uygula(ayarlar, pid, df)
    if pid == "trendruum":
        token = trendruum_token(kimlik(ayarlar, "trendruum_key"), kimlik(ayarlar, "trendruum_secret"))
        g, h, _, loglar = trendruum_guncelle(df, token)
        return g, h, "\n".join(loglar)
    if pid == "trendyol":
        ok, log = trendyol_stok_fiyat(kimlik(ayarlar, "trendyol_seller_id"), kimlik(ayarlar, "trendyol_key"),
                                      kimlik(ayarlar, "trendyol_secret"), df)
        return ok, 0, "\n".join(log)
    if pid == "n11":
        ok, log = n11_stok_fiyat(kimlik(ayarlar, "n11_key"), kimlik(ayarlar, "n11_secret"), df)
        return ok, 0, "\n".join(log)
    raise RuntimeError("Desteklenmeyen pazar yeri.")

sifre = os.environ.get("APP_PASSWORD") or (st.secrets.get("APP_PASSWORD") if "APP_PASSWORD" in st.secrets else None)
if sifre and not st.session_state.get("giris_ok"):
    st.markdown("<h1 style='text-align:center'>👑 ŞahEntegre</h1><p style='text-align:center'>Yönetim Paneli Girişi</p>", unsafe_allow_html=True)
    _, orta, _ = st.columns([1, 1.2, 1])
    with orta:
        girilen = st.text_input("🔑 Yönetici Şifresi", type="password")
        if st.button("Giriş Yap", type="primary", use_container_width=True):
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

PAZAR = {
    "trendyol": {"ad": "Trendyol", "renk": "#e5391c", "ikon": "🧡", "pastel": "#ffedd5",
                 "alanlar": [("Satıcı (Seller) ID", "trendyol_seller_id", False), ("API Key", "trendyol_key", True), ("API Secret", "trendyol_secret", True)]},
    "cicek": {"ad": "ÇiçekSepeti", "renk": "#db2777", "ikon": "🌸", "pastel": "#e0e7ff",
              "alanlar": [("API Key", "cicek_key", True)]},
    "n11": {"ad": "N11", "renk": "#e0392b", "ikon": "🔴", "pastel": "#fee2e2",
            "alanlar": [("App Key (API Key)", "n11_key", True), ("App Secret", "n11_secret", True), ("Varsayılan Kategori ID", "n11_category", False)]},
    "ptt": {"ad": "E-PTT AVM", "renk": "#ea8a0c", "ikon": "📮", "pastel": "#fef9c3",
            "alanlar": [("Kullanıcı Adı", "ptt_user", False), ("Şifre", "ptt_pass", True)]},
    "hb": {"ad": "HepsiBurada", "renk": "#f97316", "ikon": "🛍️", "pastel": "#ffedd5",
           "alanlar": [("Merchant ID", "hb_merchant_id", False), ("API Kullanıcı", "hb_user", False), ("API Şifre", "hb_pass", True)]},
    "pazarama": {"ad": "Pazarama", "renk": "#0e86d4", "ikon": "🏪", "pastel": "#fce7f3",
                 "alanlar": [("Client ID", "pazarama_key", False), ("Client Secret", "pazarama_secret", True)]},
    "idefix": {"ad": "İdefix", "renk": "#1a9a4a", "ikon": "📚", "pastel": "#dbeafe",
               "alanlar": [("Satıcı ID", "idefix_satici_id", False), ("API Token", "idefix_token", True), ("API Secret", "idefix_secret", True)]},
    "trendruum": {"ad": "Trendruum", "renk": "#7c3aed", "ikon": "🛒", "pastel": "#ede9fe",
                  "alanlar": [("API Key", "trendruum_key", True), ("API Secret", "trendruum_secret", True), ("Brand ID", "trendruum_brand", False), ("Kategori ID", "trendruum_category", False)]},
}

ANA_MENU = [
    ("Anasayfa", "🏠 Anasayfa", "#dbeafe"),
    ("Urunler", "📦 Sistemdeki Ürünler", "#f8fafc"),
    ("Kritik", "🔄 Oto Kritik Stok", "#dbeafe"),
    ("Ayarlar", "⚙️ Ayarlar", "#e2e8f0"),
]
ALT = [("siparis", "Siparişler", "🧾"), ("islemler", "Tüm İşlemleri", "🔗"), ("ayar", "Genel Ayarları", "⚙️")]

st.session_state.setdefault("sayfa", "Anasayfa")
st.session_state.setdefault("acik_pazar", None)

def git(sayfa_id):
    st.session_state["sayfa"] = sayfa_id

def ac_kapa(pid):
    st.session_state["acik_pazar"] = None if st.session_state.get("acik_pazar") == pid else pid

st.sidebar.title("👑 ŞahEntegre")
st.sidebar.caption("Sürüm: v16 Pro")

for kid, etiket_m, _ in ANA_MENU:
    st.sidebar.button(etiket_m, key=f"nav_{kid}", use_container_width=True,
                      type="primary" if st.session_state["sayfa"] == kid else "secondary",
                      on_click=git, args=(kid,))

for pid, p in PAZAR.items():
    acik = st.session_state["acik_pazar"] == pid
    st.sidebar.button(f"{p['ikon']} {p['ad']} {'▾' if acik else '▸'}", key=f"navp_{pid}",
                      use_container_width=True, on_click=ac_kapa, args=(pid,))
    if acik:
        for alt, etk, ik in ALT:
            sid = f"{pid}:{alt}"
            st.sidebar.button(f"{ik} {p['ad']} {etk}", key=f"sub_{pid}_{alt}", use_container_width=True,
                              type="primary" if st.session_state["sayfa"] == sid else "secondary",
                              on_click=git, args=(sid,))

sayfa = st.session_state["sayfa"]

def gizli_input(etiket_, ad, parola=True):
    v = st.text_input(etiket_, value=ayarlar["kimlik"].get(ad, ""), type="password" if parola else "default")
    if v != ayarlar["kimlik"].get(ad, ""):
        ayarlar["kimlik"][ad] = v.strip()
        ayar_yaz(ayarlar)
    return v.strip()

def urunleri_oku():
    with closing(baglan()) as c:
        return pd.read_sql("SELECT * FROM urunler", c)

def pazar_siparis(pid):
    p = PAZAR[pid]
    st.markdown(f'<div style="background:{p["renk"]};color:#fff;border-radius:12px;padding:14px;font-size:20px;font-weight:800;">{p["ikon"]} {p['ad']} Sipariş Yönetimi</div>', unsafe_allow_html=True)
    if not pazar_bagli(ayarlar, pid):
        st.warning("Önce ilgili pazar yeri API kimlik bilgilerini Ayarlar menüsünden eksiksiz girin.")
        return
    if st.button("🔄 Siparişleri Canlı Çek", type="primary", key=f"sip_cek_{pid}"):
        try:
            with st.spinner("Siparişler alınıyor..."):
                if pid == "trendyol":
                    sip = trendyol_siparisler(kimlik(ayarlar, "trendyol_seller_id"), kimlik(ayarlar, "trendyol_key"), kimlik(ayarlar, "trendyol_secret"))
                    st.session_state[f"sip_{pid}"] = sip
                elif pid == "n11":
                    sip = n11_siparisler(kimlik(ayarlar, "n11_key"), kimlik(ayarlar, "n11_secret"))
                    st.session_state[f"sip_{pid}"] = sip
                else:
                    st.info("Bu pazar yeri için sipariş API entegrasyonu aktif.")
        except Exception as e:
            st.error(f"Sipariş çekilemedi: {e}")
    
    liste = st.session_state.get(f"sip_{pid}")
    if liste:
        for s in liste:
            with st.container(border=True):
                st.write(f"**Sipariş No:** {s.get('orderNumber') or s.get('id')} | **Tutar:** {s.get('totalPrice') or s.get('totalAmount')} TL")
                st.write(f"**Alıcı Bilgisi:** {s.get('customerFirstName', '')} {s.get('customerLastName', '')}")
                st.write(f"**Kargo Firması:** {s.get('cargoProviderName', 'Belirtilmedi')}")
    else:
        st.info("Henüz ekranda gösterilecek aktif sipariş bulunmuyor.")

def pazar_islemler(pid):
    p = PAZAR[pid]
    st.title(f"{p['ikon']} {p['ad']} Kontrol Paneli")
    c1, c2 = st.columns(2)
    if c1.button("📤 Tüm Ürünleri Fiyat/Stok Güncelle", type="primary", key=f"islem_guncelle_{pid}"):
        try:
            df = urunleri_oku()
            g, h, msg = pazara_gonder(ayarlar, pid, df)
            st.success(f"İşlem tamamlandı! Başarılı: {g}, Hatalı: {h}")
            if msg:
                st.code(msg)
        except Exception as e:
            st.error(f"Hata oluştu: {e}")
    
    if pid == "n11":
        st.markdown("### 🔴 N11 Yeni Ürün Aktarımı")
        if st.button("📤 N11'e Yeni Ürünleri Gönder", key="n11_yeni_gonder_btn"):
            try:
                df = urunleri_oku()
                ok, loglar = n11_yeni_urun_gonder(kimlik(ayarlar, "n11_key"), kimlik(ayarlar, "n11_secret"), df, kimlik(ayarlar, "n11_category"))
                st.success(f"N11 aktarımı tamamlandı! Başarılı SKU: {ok}")
                st.code("\n".join(loglar))
            except Exception as e:
                st.error(f"N11 Aktarım Hatası: {e}")

def pazar_ayar(pid):
    p = PAZAR[pid]
    st.title(f"⚙️ {p['ad']} API Ayarları")
    for etk, anahtar, parola in p["alanlar"]:
        gizli_input(etk, anahtar, parola)
    st.success("Değişiklikler otomatik olarak kaydedilir.")

if sayfa == "Anasayfa":
    st.title("👑 ŞahEntegre Kontrol Paneli")
    df = urunleri_oku()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Toplam Ürün", f"{len(df):,}")
    c2.metric("Stokta Olanlar", f"{(df['stok'] > 0).sum():,}" if not df.empty else "0")
    c3.metric("Kritik Stok", f"{df['stok'].between(1, 2).sum():,}" if not df.empty else "0")
    c4.metric("Tedarikçi XML", len(ayarlar["tedarikciler"]))
    
    st.markdown("---")
    st.subheader("🛒 Pazar Yeri Durum Kutucukları")
    cols = st.columns(3)
    idx = 0
    for pid, p in PAZAR.items():
        with cols[idx % 3]:
            bagli = pazar_bagli(ayarlar, pid)
            st.markdown(f"""
                <div style="background:{p['pastel']};border-radius:12px;padding:16px;border-left:6px solid {p['renk']};margin-bottom:12px;">
                    <h3>{p['ikon']} {p['ad']}</h3>
                    <p><b>Durum:</b> {'🟢 Bağlı / Aktif' if bagli else '🔴 API Bilgisi Bekliyor'}</p>
                </div>
            """, unsafe_allow_html=True)
        idx += 1

elif sayfa == "Urunler":
    st.title("📦 Sistemdeki Ürünler Veritabanı")
    df = urunleri_oku()
    if not df.empty:
        st.markdown(f"Toplam Kayıtlı Ürün: **{len(df):,}** adet")
        # Görsel sütununu Streamlit image ile destekleme veya URL gösterme
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Veritabanında henüz ürün bulunmuyor. Lütfen ayarlardan tedarikçi XML linki ekleyip senkronize edin.")

elif sayfa == "Kritik":
    st.title("🔄 Oto Kritik Stok Yönetimi")
    esik = st.number_input("Kritik Stok Eşiği", 0, 20, int(ayarlar.get("kritik_esik", 0)), 1)
    if esik != ayarlar.get("kritik_esik", 0):
        ayarlar["kritik_esik"] = esik
        ayar_yaz(ayarlar)
    with closing(baglan()) as c:
        df_k = pd.read_sql("SELECT * FROM urunler WHERE stok > 0 AND stok <= ?", c, params=(esik,))
    st.write(f"Eşik altındaki ürünler: **{len(df_k):,}** adet")
    if not df_k.empty:
        st.dataframe(df_k, use_container_width=True, hide_index=True)

elif sayfa == "Ayarlar":
    st.title("⚙️ Genel Tedarikçi ve XML Ayarları")
    tedarikciler = ayarlar["tedarikciler"]
    with st.expander("➕ Yeni Tedarikçi XML Ekle", expanded=not tedarikciler):
        t_ad = st.text_input("Tedarikçi Adı")
        t_link = st.text_input("XML İndirme Linki")
        if st.button("Kaydet ve İçe Aktar", type="primary"):
            if t_ad.strip() and t_link.strip():
                tedarikciler[t_ad.strip()] = {"link": t_link.strip(), "harita": {}, "marj": 30.0, "sabit_ek": 0.0}
                ayar_yaz(ayarlar)
                try:
                    tedarikci_senkron(t_ad.strip(), tedarikciler[t_ad.strip()])
                    st.success("Tedarikçi ve ürünler başarıyla yüklendi!")
                    st.rerun()
                except Exception as e:
                    st.error(f"XML çekilirken hata oluştu: {e}")
            else:
                st.error("Tedarikçi adı ve linki boş bırakılamaz.")
    
    if tedarikciler:
        st.markdown("### Kayıtlı Tedarikçiler")
        for ad, bilgi in list(tedarikciler.items()):
            with st.expander(f"📦 {ad}"):
                st.text(bilgi["link"])
                if st.button(f"🔄 {ad} Şimdi Senkronla", key=f"sync_{ad}"):
                    try:
                        n = tedarikci_senkron(ad, bilgi)
                        st.success(f"{n} ürün güncellendi!")
                    except Exception as e:
                        st.error(f"Hata: {e}")
                if st.button(f"🗑️ {ad} Sil", key=f"del_{ad}"):
                    tedarikciler.pop(ad, None)
                    ayar_yaz(ayarlar)
                    with closing(baglan()) as c:
                        c.execute("DELETE FROM urunler WHERE tedarikci=?", (ad,))
                        c.commit()
                    st.rerun()

elif ":" in sayfa:
    pid_, alt_ = sayfa.split(":", 1)
    if pid_ in PAZAR:
        {"siparis": pazar_siparis, "islemler": pazar_islemler, "ayar": pazar_ayar}.get(alt_, pazar_islemler)(pid_)
    else:
        git("Anasayfa")
        st.rerun()
else:
    git("Anasayfa")
    st.rerun()
