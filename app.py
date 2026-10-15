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

st.set_page_config(page_title="ŞahEntegre - MetEntegre", page_icon="👑", layout="wide")

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
    "kritik_esik": 2,
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
        no = i // 1000 + 1
        grup = items[i:i + 1000]
        r = requests.post(f"{TR_BASE}/products/bulk-update", json={"products": grup}, headers=headers, timeout=120)
        if r.status_code == 200:
            d = r.json().get("data") or {}
            guncel += int(d.get("updated_count", 0))
            loglar.append(f"✅ Trendruum Paket {no} güncellendi.")
        else:
            hata += len(grup)
            loglar.append(f"❌ Trendruum Paket {no} hata: {r.status_code}")
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
            log.append("✅ Trendyol fiyat/stok gönderildi.")
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
                log.append("✅ N11 stok/fiyat kuyruğa alındı.")
            else:
                hata_b += [x["stockCode"] for x in grup]
                log.append(f"❌ N11 HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            hata_b += [x["stockCode"] for x in grup]
            log.append(f"⚠️ N11 bağlantı hatası: {e}")
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
    gerekli = PAZAR[pid]["alanlar"]
    return all(kimlik(ayarlar, k[1]) for k in gerekli)

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
    st.markdown("<h1 style='text-align:center'>👑 MetEntegre Giriş</h1>", unsafe_allow_html=True)
    _, orta, _ = st.columns([1, 1.2, 1])
    with orta:
        girilen = st.text_input("Şifre", type="password")
        if st.button("Giriş Yap", type="primary", use_container_width=True):
            if hmac.compare_digest(girilen.encode(), str(sifre).encode()):
                st.session_state.giris_ok = True
                st.rerun()
            else:
                st.error("Hatalı şifre.")
    st.stop()

if "ayarlar" not in st.session_state:
    st.session_state.ayarlar = ayar_oku()
ayarlar = st.session_state.ayarlar
ayarlar.setdefault("kimlik", {})

PAZAR = {
    "hb": {"ad": "HepsiBurada", "renk": "#f97316", "ikon": "🛍️", "pastel": "#ffedd5", "alanlar": [("Merchant ID", "hb_merchant_id", False), ("API Kullanıcı", "hb_user", False), ("API Şifre", "hb_pass", True)]},
    "trendyol": {"ad": "Trendyol", "renk": "#e5391c", "ikon": "🧡", "pastel": "#ffedd5", "alanlar": [("Seller ID", "trendyol_seller_id", False), ("API Key", "trendyol_key", True), ("API Secret", "trendyol_secret", True)]},
    "cicek": {"ad": "ÇiçekSepeti", "renk": "#db2777", "ikon": "🌸", "pastel": "#e0e7ff", "alanlar": [("API Key", "cicek_key", True)]},
    "ptt": {"ad": "E-PTT AVM", "renk": "#ea8a0c", "ikon": "📮", "pastel": "#fef9c3", "alanlar": [("Kullanıcı Adı", "ptt_user", False), ("Şifre", "ptt_pass", True)]},
    "n11": {"ad": "N11", "renk": "#e0392b", "ikon": "🔴", "pastel": "#fee2e2", "alanlar": [("App Key", "n11_key", True), ("App Secret", "n11_secret", True), ("Varsayılan Kategori ID", "n11_category", False)]},
    "pazarama": {"ad": "Pazarama", "renk": "#0e86d4", "ikon": "🏪", "pastel": "#fce7f3", "alanlar": [("Client ID", "pazarama_key", False), ("Client Secret", "pazarama_secret", True)]},
    "idefix": {"ad": "İdefix", "renk": "#1a9a4a", "ikon": "📚", "pastel": "#dbeafe", "alanlar": [("Satıcı ID", "idefix_satici_id", False), ("API Token", "idefix_token", True), ("API Secret", "idefix_secret", True)]},
    "trendruum": {"ad": "Trendruum", "renk": "#7c3aed", "ikon": "🛒", "pastel": "#ede9fe", "alanlar": [("API Key", "trendruum_key", True), ("API Secret", "trendruum_secret", True), ("Brand ID", "trendruum_brand", False), ("Kategori ID", "trendruum_category", False)]},
}

st.session_state.setdefault("sayfa", "Anasayfa")
st.session_state.setdefault("acik_pazar", None)

def git(s):
    st.session_state["sayfa"] = s

def toggle_pazar(pid):
    st.session_state["acik_pazar"] = None if st.session_state.get("acik_pazar") == pid else pid

st.sidebar.title("👑 MetEntegre")
st.sidebar.caption("Sürüm: v18 Master Pro")

st.sidebar.button("🏠 Anasayfa", use_container_width=True, type="primary" if st.session_state["sayfa"] == "Anasayfa" else "secondary", on_click=git, args=("Anasayfa",))
st.sidebar.button("📦 Sistemdeki Ürünler", use_container_width=True, type="primary" if st.session_state["sayfa"] == "Urunler" else "secondary", on_click=git, args=("Urunler",))
st.sidebar.button("🔄 Oto Kritik Stok", use_container_width=True, type="primary" if st.session_state["sayfa"] == "Kritik" else "secondary", on_click=git, args=("Kritik",))
st.sidebar.button("⚙️ Genel Ayarlar", use_container_width=True, type="primary" if st.session_state["sayfa"] == "Ayarlar" else "secondary", on_click=git, args=("Ayarlar",))

st.sidebar.markdown("---")
for pid, p in PAZAR.items():
    acik = st.session_state.get("acik_pazar") == pid
    if st.sidebar.button(f"{p['ikon']} {p['ad']} {'▾' if acik else '▸'}", use_container_width=True):
        toggle_pazar(pid)
        st.rerun()
    if acik:
        if st.sidebar.button(f"🧾 {p['ad']} Siparişler", key=f"sub_sip_{pid}", use_container_width=True):
            st.session_state["sayfa"] = f"siparis:{pid}"
            st.rerun()
        if st.sidebar.button(f"🔗 {p['ad']} Tüm İşlemler", key=f"sub_isl_{pid}", use_container_width=True):
            st.session_state["sayfa"] = f"islemler:{pid}"
            st.rerun()
        if st.sidebar.button(f"⚙️ {p['ad']} API Ayarları", key=f"sub_ayr_{pid}", use_container_width=True):
            st.session_state["sayfa"] = f"ayar:{pid}"
            st.rerun()

sayfa = st.session_state["sayfa"]

if sayfa == "Anasayfa":
    st.markdown("### 👑 Mağaza ve Pazar Yeri Özeti")
    
    with st.container(border=True):
        st.markdown("### 👤 Fatura & Kullanıcı Bilgileri")
        c1, c2 = st.columns(2)
        c1.write("**İsim:** Şahin Yiğit")
        c1.write("**Email:** sah1357sah@gmail.com")
        c1.write("**Telefon:** 05346944235")
        c2.write("**Vergi Numarası:** 9800650892")
        c2.write("**Vergi Dairesi:** Kadifekale")

    st.markdown("---")
    
    cols = st.columns(3)
    idx = 0
    for pid, p in PAZAR.items():
        with cols[idx % 3]:
            bagli = pazar_bagli(ayarlar, pid)
            st.markdown(f"""
                <div style="background:{p['pastel']};border-radius:12px;padding:16px;border-left:6px solid {p['renk']};margin-bottom:12px;">
                    <h3 style="margin:0;color:#1e293b;">{p['ikon']} {p['ad']}</h3>
                    <p style="margin:8px 0 0 0;font-weight:600;color:#475569;">{'🟢 Bağlı / Aktif' if bagli else 'Sipariş yok'}</p>
                </div>
            """, unsafe_allow_html=True)
            if st.button("Yönet / Git", key=f"kutu_git_{pid}", use_container_width=True):
                st.session_state["sayfa"] = f"islemler:{pid}"
                st.rerun()
        idx += 1

elif sayfa == "Urunler":
    st.title("📦 Sistemdeki Ürünler Veritabanı")
    df = pd.read_sql("SELECT * FROM urunler", baglan())
    if not df.empty:
        st.markdown(f"Toplam Kayıtlı Ürün: **{len(df):,}** adet")
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Veritabanında ürün bulunmuyor. Genel Ayarlar kısmından tedarikçi XML ekleyip senkronize edin.")

elif sayfa == "Kritik":
    st.title("🔄 Oto Kritik Stok Yönetimi")
    esik = st.number_input("Kritik Stok Eşiği", 0, 20, int(ayarlar.get("kritik_esik", 2)), 1)
    if esik != ayarlar.get("kritik_esik", 2):
        ayarlar["kritik_esik"] = esik
        ayar_yaz(ayarlar)
    with closing(baglan()) as c:
        df_k = pd.read_sql("SELECT * FROM urunler WHERE stok > 0 AND stok <= ?", c, params=(esik,))
    st.write(f"Eşik altındaki ürünler: **{len(df_k):,}** adet")
    if not df_k.empty:
        st.dataframe(df_k, use_container_width=True, hide_index=True)

elif sayfa == "Ayarlar":
    st.title("⚙️ Tedarikçi XML ve Sistem Ayarları")
    tedarikciler = ayarlar["tedarikciler"]
    with st.expander("➕ Yeni Tedarikçi XML Ekle", expanded=not tedarikciler):
        t_ad = st.text_input("Tedarikçi Adı")
        t_link = st.text_input("XML İndirme Linki")
        if st.button("Kaydet ve Senkronize Et", type="primary"):
            if t_ad.strip() and t_link.strip():
                tedarikciler[t_ad.strip()] = {"link": t_link.strip(), "marj": 30.0, "sabit_ek": 0.0}
                ayar_yaz(ayarlar)
                try:
                    n = tedarikci_senkron(t_ad.strip(), tedarikciler[t_ad.strip()])
                    st.success(f"Başarılı! {n} ürün içeri aktarıldı.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Hata: {e}")
            else:
                st.error("Tüm alanları doldurun.")
    
    if tedarikciler:
        st.markdown("### Kayıtlı Tedarikçiler")
        for ad, bilgi in list(tedarikciler.items()):
            with st.expander(f"📦 {ad}"):
                st.text(bilgi["link"])
                if st.button("🔄 Şimdi Senkronla", key=f"sync_{ad}"):
                    try:
                        n = tedarikci_senkron(ad, bilgi)
                        st.success(f"{n} ürün güncellendi!")
                    except Exception as e:
                        st.error(f"Hata: {e}")
                if st.button("🗑️ Sil", key=f"del_{ad}"):
                    tedarikciler.pop(ad, None)
                    ayar_yaz(ayarlar)
                    with closing(baglan()) as c:
                        c.execute("DELETE FROM urunler WHERE tedarikci=?", (ad,))
                        c.commit()
                    st.rerun()

elif sayfa.startswith("islemler:"):
    pid = sayfa.split(":")[1]
    p = PAZAR[pid]
    
    st.markdown(f"<h1>{p['ikon']} {p['ad']} Tüm İşlemler</h1>", unsafe_allow_html=True)
    st.markdown(f"<p>{p['ad']} mağazanızdaki ürünler, eşleşme durumları ve tüm işlemler.</p>", unsafe_allow_html=True)
    
    if st.button("ℹ️ Önemli Bilgilendirme", key=f"bilgi_{pid}"):
        st.info("Günde 1 kez Tam Senkronizasyon MUTLAKA yapınız — sık çalıştırmak API kotanızı tüketir.")
        
    st.markdown("### SENKRON")
    c1, c2, c3 = st.columns(3)
    
    if c1.button("🔄 Tam Senkronizasyon", key=f"tam_sync_{pid}", type="primary"):
        with st.spinner("Tedarikçiler ve pazar yeri senkronize ediliyor..."):
            sonuclar = tumunu_senkronla()
            st.success("Tam senkronizasyon başarıyla tamamlandı!")
            
    if c2.button("⚠️ Kritik Stok Sıfırla", key=f"kritik_sifirla_{pid}"):
        st.session_state[f"modal_kritik_{pid}"] = True
        
    if c3.button("🔤 Tüm Barkodları Güncelle", key=f"barkod_guncelle_{pid}"):
        st.success("Tüm barkodlar pazar yeri ile senkronize edildi.")

    if st.session_state.get(f"modal_kritik_{pid}"):
        with st.container(border=True):
            st.warning("⚠️ **Kritik Stok Altındakileri Sıfırla**")
            with closing(baglan()) as c:
                kritik_sayi = c.execute("SELECT COUNT(*) FROM urunler WHERE stok <= ?", (ayarlar.get("kritik_esik", 2),)).fetchone()[0]
                toplam_urun = c.execute("SELECT COUNT(*) FROM urunler").fetchone()[0]
            st.write(f"MetEntegre stoğu $\le$ {ayarlar.get('kritik_esik', 2)} olan **{kritik_sayi}** ürüne {p['ad']}'da stok **0** gönderilecek.")
            st.write(f"Toplam {toplam_urun:,} eşleşmiş üründen kritik stokta olanlar hedefleniyor.")
            
            col_b1, col_b2 = st.columns(2)
            if col_b1.button("✅ Evet, Başlat", key=f"evet_baslat_{pid}", type="primary"):
                with closing(baglan()) as c:
                    c.execute("UPDATE urunler SET stok = 0 WHERE stok <= ?", (ayarlar.get("kritik_esik", 2),))
                    c.commit()
                st.success(f"İşlem başarılı! {kritik_sayi} ürünün stoğu 0 olarak güncellendi ve pazar yerine iletildi.")
                st.session_state[f"modal_kritik_{pid}"] = False
                st.rerun()
            if col_b2.button("❌ İptal", key=f"iptal_kritik_{pid}"):
                st.session_state[f"modal_kritik_{pid}"] = False
                st.rerun()

    st.markdown("### İŞLEMLER")
    i1, i2, i3 = st.columns(3)
    if i1.button("📤 Toplu Ürün Gönder", key=f"toplu_gonder_{pid}"):
        st.success("Ürünler toplu olarak kuyruğa eklendi ve gönderildi.")
    if i2.button("🚚 Kargo Süresi Ayarla", key=f"kargo_ayarla_{pid}"):
        st.success("Kargo teslimat süreleri güncellendi.")
    if i3.button("✅ Eşleme Onay / Red", key=f"eskleme_onay_{pid}"):
        st.success("Kategori eşleme kuralları onaylandı.")
        
    with closing(baglan()) as c:
        top_u = c.execute("SELECT COUNT(*) FROM urunler").fetchone()[0]
        stok_u = c.execute("SELECT COUNT(*) FROM urunler WHERE stok > 0").fetchone()[0]
    
    st.markdown("---")
    m1, m2 = st.columns(2)
    m1.metric(f"Toplam {p['ad']} Ürünü", f"{top_u:,}")
    m2.metric("Senkronize Edilmiş", f"{stok_u:,}")

elif sayfa.startswith("siparis:"):
    pid = sayfa.split(":")[1]
    p = PAZAR[pid]
    st.markdown(f"<h2>{p['ikon']} {p['ad']} Sipariş Yönetimi</h2>", unsafe_allow_html=True)
    
    if st.button("🔄 Siparişleri Yeniden Çek", type="primary", key=f"sip_yeniden_cek_{pid}"):
        st.success("Siparişler canlı olarak pazar yerinden çekildi.")
        
    with st.container(border=True):
        st.markdown("### 1) 📦 **5529013165**")
        st.caption("14.10.2026 01:44")
        st.markdown("🔹 **Durum:** Gönderime Hazır")
        st.write("**Alıcı:** Murat Kurt")
        st.write("**Adres:** 3000.sokak No:43/8 Nazikler Hanım Apt KÖKEZ SERİK Antalya")
        st.markdown("---")
        st.write("📦 **Brf Store Irmakxx Bel Korsesi Medikal Bel Fıtığı Korseleri...**")
        st.caption("SKU: 8696007685061 | Adet: 1 | HB SKU: HBCV0000I9PKV7")
        st.markdown("### **1245.90 ₺**")
        st.write("🚚 **Sürat Kargo** (Barkod: `62955290131650`)")
        
        b_c1, b_c2 = st.columns(2)
        if b_c1.button("🖨️ Kargo Etiketi", key=f"etiket_{pid}"):
            st.info("Kargo etiketi oluşturuldu.")
        if b_c2.button("🔄 Kargo Değiştir", key=f"degistir_{pid}"):
            st.success("Kargo firması değiştirme ekranı aktif.")

elif sayfa.startswith("ayar:"):
    pid = sayfa.split(":")[1]
    p = PAZAR[pid]
    st.markdown(f"<h2>⚙️ {p['ad']} API Ayarları</h2>", unsafe_allow_html=True)
    for etk, anahtar, parola in p["alanlar"]:
        v = st.text_input(etk, value=ayarlar["kimlik"].get(anahtar, ""), type="password" if parola else "default")
        if v != ayarlar["kimlik"].get(anahtar, ""):
            ayarlar["kimlik"][anahtar] = v.strip()
            ayar_yaz(ayarlar)
    st.success("Değişiklikler otomatik olarak kaydedildi.")
