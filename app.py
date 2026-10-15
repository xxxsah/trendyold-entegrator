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
SENKRON_ARALIK = 6 * 3600  # günde 4 kez
KILIT = threading.Lock()

# Gizli bilgiler: ortam değişkeni / st.secrets / panelden girilen (ayarlar.json)
KIMLIK_ALANLARI = [
    "trendruum_key", "trendruum_secret", "trendruum_brand", "trendruum_category",
    "trendyol_seller_id", "trendyol_key", "trendyol_secret",
    "hb_merchant_id", "hb_user", "hb_pass",
    "idefix_satici_id", "idefix_token", "idefix_secret",
]

# ---------------------------------------------------------------
# AYARLAR
# ---------------------------------------------------------------
VARSAYILAN = {
    "tedarikciler": {},
    "kimlik": {},
    "kategori_eslesme": {},
    "kritik_esik": 0,        # 0 = kapalı; stok <= eşik ise 0 yapılır
    "oto_senkron": True,
    "tr_oto_guncelle": False,
    "ty_oto_guncelle": False,
    "idefix_oto_guncelle": False,
    "pazar_ayarlari": {},
}


def _ayar_tohumu():
    """Dosya kaybolursa (Streamlit Cloud yeniden başlatma) ayarları secrets'tan geri getirir."""
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
    """Öncelik: ortam değişkeni > st.secrets > ayarlar.json > pazar_ayarlari"""
    env = os.environ.get(ad.upper())
    if env:
        return env
    try:
        if ad.upper() in st.secrets:
            return str(st.secrets[ad.upper()])
    except Exception:
        pass
    
    val = ayarlar.get("kimlik", {}).get(ad, "")
    if val:
        return val
        
    pazar_ayarlari = ayarlar.get("pazar_ayarlari", {})
    if ad.startswith("idefix_"):
        ide = pazar_ayarlari.get("İdefix", {})
        if ad == "idefix_satici_id": return ide.get("magaza_id", "")
        if ad == "idefix_token": return ide.get("api_key", "")
        if ad == "idefix_secret": return ide.get("servis_anahtari", "")
    return ""


# ---------------------------------------------------------------
# VERİTABANI
# ---------------------------------------------------------------
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


# ---------------------------------------------------------------
# XML OKUMA
# ---------------------------------------------------------------
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


# ---------------------------------------------------------------
# SENKRONİZASYON
# ---------------------------------------------------------------
def tedarikci_senkron(ad, bilgi, kritik_esik=0):
    df_ham = xml_oku(indir(bilgi["link"]))
    df = normalle(ad, df_ham, bilgi.get("harita", {}), float(bilgi.get("marj", 30.0)),
                  float(bilgi.get("sabit_ek", 0.0)), kritik_esik)
    if df.empty:
        raise ValueError("XML'den geçerli ürün çıkmadı (veri korunuyor).")
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
    if oto and any(x[1] for x in sonuclar):
        for ad_, anahtar_, fonk_ in (("Trendruum", "tr_oto_guncelle", trendruum_oto_guncelle),
                                      ("Trendyol", "ty_oto_guncelle", trendyol_oto_guncelle),
                                      ("İdefix", "idefix_oto_guncelle", idefix_oto_guncelle)):
            if ayarlar.get(anahtar_):
                try:
                    fonk_(ayarlar)
                except Exception as e:
                    log_yaz(ad_, "HATA", e)
    return sonuclar


def arka_plan_dongusu():
    time.sleep(30)
    while True:
        try:
            if ayar_oku().get("oto_senkron", True):
                tumunu_senkronla()
        except Exception as e:
            log_yaz("SİSTEM", "HATA", e)
        time.sleep(SENKRON_ARALIK)


@st.cache_resource
def arka_plan_baslat():
    t = threading.Thread(target=arka_plan_dongusu, daemon=True)
    t.start()
    return t


arka_plan_baslat()


# ---------------------------------------------------------------
# PAZAR YERİ: İDEFİX
# ---------------------------------------------------------------
IDEFIX_BASE = "https://api.idefix.com/api/v1"

def idefix_header(token, secret, satici_id):
    return {
        "X-Api-Key": token.strip(),
        "X-Api-Secret": secret.strip(),
        "X-Seller-Id": str(satici_id).strip(),
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

def idefix_siparisler(token, secret, satici_id):
    headers = idefix_header(token, secret, satici_id)
    r = requests.get(f"{IDEFIX_BASE}/orders", headers=headers, timeout=30)
    if r.status_code == 200:
        return r.json().get("data", [])
    r2 = requests.get(f"{IDEFIX_BASE}/orders/list", headers=headers, timeout=30)
    if r2.status_code == 200:
        return r2.json().get("data", [])
    r.raise_for_status()
    return []

def idefix_stok_fiyat(token, secret, satici_id, df):
    headers = idefix_header(token, secret, satici_id)
    items = [{
        "barcode": str(r["barkod"]),
        "price": float(r["satis_fiyati"]),
        "stock": int(r["stok"])
    } for _, r in df.iterrows() if r["satis_fiyati"] > 0]
    
    ok, log, ok_b, hata_b = 0, [], [], []
    paket = 200
    for i in range(0, len(items), paket):
        grup = items[i:i + paket]
        try:
            r = requests.post(f"{IDEFIX_BASE}/inventory-upload", json={"items": grup}, headers=headers, timeout=60)
            if r.status_code in (200, 201, 202):
                ok += len(grup)
                ok_b += [x["barcode"] for x in grup]
                log.append(f"✅ İdefix {i // paket + 1}. paket gönderildi")
            else:
                r2 = requests.post(f"{IDEFIX_BASE}/products/inventory", json={"products": grup}, headers=headers, timeout=60)
                if r2.status_code in (200, 201, 202):
                    ok += len(grup)
                    ok_b += [x["barcode"] for x in grup]
                    log.append(f"✅ İdefix {i // paket + 1}. paket gönderildi (Alternatif uç)")
                else:
                    hata_b += [x["barcode"] for x in grup]
                    log.append(f"❌ İdefix {i // paket + 1}. paket HTTP {r.status_code}: {r.text[:300]}")
        except Exception as e:
            hata_b += [x["barcode"] for x in grup]
            log.append(f"⚠️ İdefix {i // paket + 1}. paket bağlantı hatası: {e}")
            
    try:
        pazar_isaretle("idefix", ok_b, hata_b)
    except Exception:
        pass
    return ok, len(hata_b), "\n".join(log)

def idefix_oto_guncelle(ayarlar):
    token, secret, satici = (kimlik(ayarlar, "idefix_token"), kimlik(ayarlar, "idefix_secret"), kimlik(ayarlar, "idefix_satici_id"))
    if not (token and secret and satici):
        return
    with closing(baglan()) as c:
        df = pd.read_sql("SELECT barkod, stok, satis_fiyati FROM urunler", c)
    ok, hata, _ = idefix_stok_fiyat(token, secret, satici, df)
    log_yaz("İdefix", "OK", f"{ok} ürün güncellendi, {hata} hata")


# ---------------------------------------------------------------
# PAZAR YERİ: TRENDRUUM
# ---------------------------------------------------------------
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


def trendruum_urun_listesi(df, ayarlar, brand_id, varsayilan_cat):
    harita = ayarlar.get("kategori_eslesme", {})
    liste, atlanan = [], 0
    for _, row in df.iterrows():
        gorsel = str(row["gorsel"]).strip()
        if not gorsel or row["satis_fiyati"] <= 0:
            atlanan += 1
            continue
        kod = str(row["barkod"]).strip()
        ana = str(row.get("kategori", "")).split(">>>")[0].strip()
        liste.append({
            "name": str(row["urun_adi"]),
            "model_code": kod,
            "category_id": harita.get(ana) or varsayilan_cat,
            "brand_id": brand_id,
            "children_products": [{
                "barcode": sabit_barkod(kod),
                "stock_code": kod,
                "price": float(row["satis_fiyati"]),
                "stock": int(row["stok"]),
                "tax": 20,
                "images": [gorsel],
            }],
        })
    return liste, atlanan


def trendruum_gonder(liste, token, ilerleme=None, paket=50):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    toplam = max(1, (len(liste) + paket - 1) // paket)
    loglar, basarili, art_arda, var_olan = [], 0, 0, []
    for
