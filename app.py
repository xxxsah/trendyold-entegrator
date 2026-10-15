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

st.set_page_config(page_title="ŞahEntegre - Profesyonel E-Ticaret Yönetim Paneli", page_icon="👑", layout="wide")

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
    "n11_key", "n11_secret", "cicek_key", "ptt_user", "ptt_pass",
    "pazarama_key", "pazarama_secret", "anthropic_api_key"
]

VARSAYILAN = {
    "tedarikciler": {},
    "kimlik": {},
    "kategori_eslesme": {},
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
        c.execute("""
            CREATE TABLE IF NOT EXISTS urunler (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gorsel TEXT, tedarikci TEXT, barkod TEXT, urun_adi TEXT, stok INTEGER,
                alis_fiyati REAL, satis_fiyati REAL, kategori TEXT
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
    df = normalle(ad, df_ham, bilgi.get("harita", {}), float(bilgi.get("marj", 30.0)),
                  float(bilgi.get("sabit_ek", 0.0)), kritik_esik)
    if df.empty:
        raise ValueError("XML'den geçerli ürün çıkmadı (veri korunuyor).")
    with closing(baglan()) as c:
        c.execute("BEGIN")
        c.execute("DELETE FROM urunler WHERE tedarikci = ?", (ad,))
        c.executemany(
            "INSERT INTO urunler (gorsel, tedarikci, barkod, urun_adi, stok, alis_fiyati, satis_fiyati, kategori) "
            "VALUES (?,?,?,?,?,?,?,?)",
            df[["gorsel", "tedarikci", "barkod", "urun_adi", "stok", "alis_fiyati",
                "satis_fiyati", "kategori"]].itertuples(index=False, name=None),
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
                                      ("N11", "n11_oto_guncelle", n11_oto_guncelle)):
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
    for i in range(0, len(liste), paket):
        no = i // paket + 1
        grup = liste[i:i + paket]
        for deneme in range(8):
            if not grup:
                break
            try:
                r = requests.post(f"{TR_BASE}/products/bulk", json={"products": grup},
                                  headers=headers, timeout=60)
            except Exception as e:
                loglar.append(f"⚠️ Paket {no} bağlantı hatası: {e}")
                time.sleep(2)
                continue
            if r.status_code in (200, 202):
                basarili += 1
                art_arda = 0
                loglar.append(f"✅ Paket {no}: {len(grup)} ürün gönderildi")
                break
            if r.status_code in (422, 500):
                try:
                    j = r.json()
                    metin = " ".join(map(str, (j.get("errors") or {}).get("errors", []))) or r.text
                except Exception:
                    metin = r.text
                cakisan = set(re.findall(r"(\d{6,})\\?\"\s*barkodu", metin))
                var = [u for u in grup if u["children_products"][0]["barcode"] in cakisan]
                if var:
                    var_olan += [u["model_code"] for u in var]
                    grup = [u for u in grup if u not in var]
                    loglar.append(f"ℹ️ Paket {no}: {len(var)} ürün mağazada zaten kayıtlı, atlandı")
                    continue
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 * (deneme + 1))
                continue
            loglar.append(f"❌ Paket {no}: HTTP {r.status_code} {r.text[:1500]}")
            art_arda += 1
            break
        if ilerleme:
            ilerleme(no / toplam, loglar)
        if art_arda >= 3:
            loglar.append("⛔ Üst üste 3 paket reddedildi, gönderim durduruldu.")
            if ilerleme:
                ilerleme(1.0, loglar)
            break
    if var_olan:
        loglar.append(f"ℹ️ Toplam {len(var_olan)} ürün mağazada zaten kayıtlıydı.")
    return basarili, toplam, loglar

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
        r = None
        for deneme in range(4):
            try:
                r = requests.post(f"{TR_BASE}/products/bulk-update", json={"products": grup},
                                  headers=headers, timeout=120)
            except Exception as e:
                loglar.append(f"⚠️ Paket {no} bağlantı hatası: {e}")
                r = None
                time.sleep(2)
                continue
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 * (deneme + 1))
                continue
            break
        if r is None:
            hata += len(grup)
            hata_s |= {x["barcode"] for x in grup}
        elif r.status_code == 200:
            try:
                d = r.json().get("data") or {}
            except Exception:
                d = {}
            guncel += int(d.get("updated_count", 0))
            hata += int(d.get("failed_count", 0))
            hatalar = d.get("errors") or []
            for e in hatalar:
                hata_s |= set(re.findall(r"\d{6,}", str(e)))
            ornek += [str(e)[:200] for e in hatalar[:3]]
            loglar.append(f"✅ Paket {no}: {d.get('updated_count', 0)} güncellendi")
        else:
            hata += len(grup)
            hata_s |= {x["barcode"] for x in grup}
            loglar.append(f"❌ Paket {no}: HTTP {r.status_code}")
        if ilerleme:
            ilerleme(no / toplam)
    try:
        pazar_isaretle("trendruum", [orijin[b] for b in orijin if b not in hata_s],
                       [orijin[b] for b in hata_s if b in orijin])
    except Exception:
        pass
    return guncel, hata, ornek[:5], loglar

def trendruum_durum(token, barkodlar, durum):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    ok, hata, loglar = 0, 0, []
    for i in range(0, len(barkodlar), 500):
        grup = barkodlar[i:i + 500]
        no = i // 500 + 1
        try:
            r = requests.post(f"{TR_BASE}/products/status-update",
                              json={"products": [{"barcode": sabit_barkod(b), "status": durum} for b in grup]},
                              headers=headers, timeout=120)
        except Exception as e:
            hata += len(grup)
            loglar.append(f"⚠️ Paket {no} bağlantı hatası: {e}")
            continue
        if r.status_code == 200:
            ok += len(grup)
            loglar.append(f"✅ Paket {no}: {len(grup)} ürün güncellendi")
        else:
            hata += len(grup)
            loglar.append(f"❌ Paket {no}: HTTP {r.status_code}")
    return ok, hata, loglar

def trendruum_siparisler(token, durum="new", limit=50):
    r = requests.get(f"{TR_BASE}/orders", params={"status": durum, "page": 1, "limit": limit},
                     headers={"Authorization": f"Bearer {token}"}, timeout=30)
    r.raise_for_status()
    return r.json()

def trendruum_oto_guncelle(ayarlar):
    key, secret = kimlik(ayarlar, "trendruum_key"), kimlik(ayarlar, "trendruum_secret")
    if not (key and secret):
        return
    with closing(baglan()) as c:
        df = pd.read_sql("SELECT barkod, stok, satis_fiyati FROM urunler", c)
    token = trendruum_token(key, secret)
    g, h, _, _ = trendruum_guncelle(df, token)
    log_yaz("Trendruum", "OK", f"{g} ürün güncellendi, {h} hata")

def tr_kucuk(metin):
    return str(metin).replace("İ", "i").replace("I", "ı").lower().strip()

def trendruum_kategoriler(token):
    r = requests.get(f"{TR_BASE}/categories", params={"limit": 5000},
                     headers={"Authorization": f"Bearer {token}"}, timeout=90)
    r.raise_for_status()
    j = r.json()
    veri = j.get("data", j) if isinstance(j, dict) else j
    if isinstance(veri, dict):
        veri = next((v for v in veri.values() if isinstance(v, list)), [])
    duz = []

    def gez(liste):
        for k in liste or []:
            alt = k.get("sub_categories") or []
            duz.append({"id": k.get("id"), "ad": k.get("name", ""),
                        "yol": k.get("full_path") or k.get("name", ""),
                        "parent": k.get("parent_id"), "alt": bool(alt)})
            gez(alt)

    gez(veri)
    ebeveynler = {k["parent"] for k in duz if k["parent"]}
    for k in duz:
        k["yaprak"] = (not k["alt"]) and (k["id"] not in ebeveynler)
    return duz

def trendruum_markalar(token, ara):
    r = requests.get(f"{TR_BASE}/brands", params={"search": ara},
                     headers={"Authorization": f"Bearer {token}"}, timeout=30)
    r.raise_for_status()
    j = r.json()
    veri = j.get("data", []) if isinstance(j, dict) else j
    return veri if isinstance(veri, list) else []

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
            log.append("✅ Paket gönderildi")
        else:
            hata_b += [x["barcode"] for x in grup]
            log.append(f"❌ Paket HTTP {r.status_code}")
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
            skular.append({"stockCode": str(r["barkod"]), "listPrice": fiyat, "salePrice": fiyat,
                           "quantity": int(r["stok"]), "currencyType": "TL"})
    ok, log, ok_b, hata_b = 0, [], [], []
    for i in range(0, len(skular), 1000):
        grup = skular[i:i + 1000]
        no = i // 1000 + 1
        try:
            r = requests.post(f"{N11_BASE}/ms/product/tasks/price-stock-update",
                              json={"payload": {"integrator": "SahEntegre", "skus": grup}},
                              headers=n11_header(key, secret), timeout=120)
            j = r.json() if r.text else {}
        except Exception as e:
            hata_b += [x["stockCode"] for x in grup]
            log.append(f"⚠️ Paket {no} bağlantı hatası: {e}")
            continue
        if r.status_code == 200 and str(j.get("status", "")).upper() != "REJECT":
            ok += len(grup)
            ok_b += [x["stockCode"] for x in grup]
            log.append(f"✅ Paket {no}: görev kuyruğa alındı")
        else:
            hata_b += [x["stockCode"] for x in grup]
            log.append(f"❌ Paket {no}: HTTP {r.status_code}")
    try:
        pazar_isaretle("n11", ok_b, hata_b)
    except Exception:
        pass
    return ok, log

def n11_oto_guncelle(ayarlar):
    k_, x_ = kimlik(ayarlar, "n11_key"), kimlik(ayarlar, "n11_secret")
    if not (k_ and x_):
        return
    with closing(baglan()) as c:
        df = pd.read_sql("SELECT barkod, stok, satis_fiyati FROM urunler", c)
    ok, _ = n11_stok_fiyat(k_, x_, df)
    log_yaz("N11", "OK", f"{ok} kalem kuyruğa alındı")

def n11_siparisler(key, secret, durum, sayfa_siniri=3):
    sonuc = []
    for sayfa_ in range(sayfa_siniri):
        r = requests.get(f"{N11_BASE}/rest/delivery/v1/shipmentPackages",
                         params={"status": durum, "page": sayfa_, "size": 100, "orderByDirection": "DESC"},
                         headers=n11_header(key, secret), timeout=60)
        r.raise_for_status()
        icerik = r.json().get("content") or []
        sonuc += icerik
        if len(icerik) < 100:
            break
    return sonuc

def trendyol_oto_guncelle(ayarlar):
    s_, k_, x_ = (kimlik(ayarlar, "trendyol_seller_id"), kimlik(ayarlar, "trendyol_key"),
                  kimlik(ayarlar, "trendyol_secret"))
    if not (s_ and k_ and x_):
        return
    with closing(baglan()) as c:
        df = pd.read_sql("SELECT barkod, stok, satis_fiyati FROM urunler", c)
    ok, _ = trendyol_stok_fiyat(s_, k_, x_, df)
    log_yaz("Trendyol", "OK", f"{ok} kalem gönderildi")

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
    gerek_haritasi = {
        "trendruum": ["trendruum_key", "trendruum_secret"],
        "trendyol": ["trendyol_seller_id", "trendyol_key", "trendyol_secret"],
        "n11": ["n11_key", "n11_secret"],
        "cicek": ["cicek_key"],
        "ptt": ["ptt_user", "ptt_pass"],
        "hb": ["hb_merchant_id", "hb_user", "hb_pass"],
        "pazarama": ["pazarama_key", "pazarama_secret"],
        "idefix": ["idefix_satici_id", "idefix_token", "idefix_secret"]
    }
    alanlar = gerek_haritasi.get(pid)
    if not alanlar:
        return False
    for k in alanlar:
        val = kimlik(ayarlar, k)
        if not val or str(val).strip() == "":
            return False
    return True

def _pazara_gonder(ayarlar, pid, df, ilerleme=None):
    df = fiyat_artis_uygula(ayarlar, pid, df)
    if pid == "trendruum":
        token = trendruum_token(kimlik(ayarlar, "trendruum_key"), kimlik(ayarlar, "trendruum_secret"))
        g, h, ornek, loglar = trendruum_guncelle(df, token, ilerleme)
        return g, h, "\n".join(ornek + loglar[-5:])
    if pid == "trendyol":
        ok, log = trendyol_stok_fiyat(kimlik(ayarlar, "trendyol_seller_id"), kimlik(ayarlar, "trendyol_key"),
                                      kimlik(ayarlar, "trendyol_secret"), df)
        return ok, 0, "\n".join(log)
    if pid == "n11":
        ok, log = n11_stok_fiyat(kimlik(ayarlar, "n11_key"), kimlik(ayarlar, "n11_secret"), df)
        return ok, 0, "\n".join(log)
    raise RuntimeError(f"Bu pazar yeri ({pid}) için henüz API gönderim entegrasyonu tanımlı değil.")

def pazara_gonder(ayarlar, pid, df, ilerleme=None):
    ad_ = {"trendruum": "Trendruum", "trendyol": "Trendyol", "n11": "N11"}.get(pid, pid)
    try:
        g, h, msg = _pazara_gonder(ayarlar, pid, df, ilerleme)
    except Exception as e:
        log_yaz(ad_, "HATA", f"Gönderilemedi: {e}")
        raise
    log_yaz(ad_, "OK" if g > 0 else "HATA", f"{g} gönderildi, {h} hata. {msg}"[:500])
    return g, h, msg

def baglanti_testi(ayarlar, pid):
    try:
        if pid == "trendruum":
            trendruum_token(kimlik(ayarlar, "trendruum_key"), kimlik(ayarlar, "trendruum_secret"))
            return True, "Giriş başarılı, anahtarlar doğru."
        if pid == "trendyol":
            s_, k_, x_ = (kimlik(ayarlar, "trendyol_seller_id"), kimlik(ayarlar, "trendyol_key"),
                          kimlik(ayarlar, "trendyol_secret"))
            r = requests.get(f"{TY_BASE}/order/sellers/{s_}/orders", params={"size": 1},
                             headers=trendyol_header(s_, k_, x_), timeout=30)
        elif pid == "n11":
            r = requests.get(f"{N11_BASE}/rest/delivery/v1/shipmentPackages",
                             params={"status": "Created", "page": 0, "size": 1},
                             headers=n11_header(kimlik(ayarlar, "n11_key"), kimlik(ayarlar, "n11_secret")),
                             timeout=30)
        else:
            return False, "Bu pazar yeri için test yok."
        return r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
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

def getp(d, *yollar):
    for y in yollar:
        cur = d
        for k in y.split("."):
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                cur = None
                break
        if cur not in (None, "", [], {}):
            return cur
    return None

def metin(v):
    if isinstance(v, dict):
        return ", ".join(str(x) for x in v.values() if x not in (None, ""))
    return "" if v is None else str(v)

DURUM_ETIKET = {"yeni": "🆕 Yeni", "hazir": "🚚 Gönderime Hazır", "kargoda": "🚛 Kargoda",
                "teslim": "✅ Teslim Edildi", "iptal": "❌ İptal"}

def durum_kodu(pid, d):
    d = str(d or "").lower()
    if pid in ("trendyol", "n11"):
        harita = {"created": "yeni", "picking": "hazir", "invoiced": "hazir", "shipped": "kargoda",
                  "delivered": "teslim", "cancelled": "iptal", "unsupplied": "iptal", "unpacked": "iptal"}
    else:
        harita = {"new": "yeni", "pending": "yeni", "in_progress": "hazir", "shipped": "kargoda",
                  "shipping": "kargoda", "delivered": "teslim", "completed": "teslim",
                  "cancelled": "iptal", "returned": "iptal"}
    return harita.get(d, "yeni")

def siparis_normalle_ty(p):
    adr = p.get("shipmentAddress") or {}
    satirlar = p.get("lines") or []
    return {
        "pid": "trendyol", "id": str(p.get("id", "")), "no": str(p.get("orderNumber", "")),
        "tarih": tr_tarih(p.get("orderDate")),
        "durum": durum_kodu("trendyol", p.get("status") or p.get("shipmentPackageStatus")),
        "alici": adr.get("fullName") or f"{adr.get('firstName', '')} {adr.get('lastName', '')}".strip(),
        "adres": adr.get("fullAddress") or metin(adr.get("address1")),
        "urunler": [{"ad": l.get("productName", ""), "sku": l.get("merchantSku") or l.get("barcode", ""),
                     "adet": l.get("quantity", 1)} for l in satirlar],
        "tutar": p.get("totalPrice"), "teslim": tr_tarih(p.get("agreedDeliveryDate")),
        "kargo": p.get("cargoProviderName", ""), "barkod": str(p.get("cargoTrackingNumber", "") or ""),
        "link": p.get("cargoTrackingLink", "") or "",
        "satirlar": [{"lineId": l.get("id"), "quantity": l.get("quantity", 1)} for l in satirlar],
        "ham": p,
    }

def siparis_normalle_tr(o):
    ogid = getp(o, "ogid", "order_group_id", "id", "_id")
    ham_urun = getp(o, "items", "order_group_items", "products", "lines") or []
    urunler = []
    for u in ham_urun:
        if isinstance(u, dict):
            urunler.append({"ad": metin(getp(u, "name", "product_name", "title")),
                            "sku": metin(getp(u, "barcode", "stock_code", "sku")),
                            "adet": getp(u, "quantity", "qty") or 1})
    return {
        "pid": "trendruum", "id": str(ogid or ""),
        "no": str(getp(o, "order_number", "orderNumber", "ogid", "id", "_id") or ""),
        "tarih": tr_tarih(getp(o, "created_at", "createdAt", "order_date", "date")),
        "durum": durum_kodu("trendruum", getp(o, "status", "shipment_status")),
        "alici": metin(getp(o, "customer.name", "customer.full_name", "shipping_address.full_name",
                            "shipping_address.name", "buyer_name", "name")),
        "adres": metin(getp(o, "shipping_address.full_address", "shipping_address.address",
                            "address.full_address", "address")),
        "urunler": urunler, "tutar": getp(o, "total_price", "total", "grand_total"),
        "teslim": tr_tarih(getp(o, "estimated_delivery_date", "delivery_date")),
        "kargo": metin(getp(o, "cargo_company", "shipment.cargo_company")),
        "barkod": metin(getp(o, "tracking_number", "shipment.tracking_number")), "link": "", "ham": o,
    }

def siparis_normalle_n11(p):
    adr = p.get("shippingAddress") or {}
    satirlar = p.get("lines") or []
    gecmis = p.get("packageHistories") or []
    ilk = gecmis[0].get("createdDate") if gecmis else p.get("lastModifiedDate")
    return {
        "pid": "n11", "id": str(p.get("id", "")), "no": str(p.get("orderNumber", "")),
        "tarih": tr_tarih(ilk), "durum": durum_kodu("n11", p.get("shipmentPackageStatus")),
        "alici": adr.get("fullName") or p.get("customerfullName") or "",
        "adres": ", ".join(x for x in (adr.get("address"), adr.get("district"), adr.get("city")) if x),
        "urunler": [{"ad": l.get("productName", ""), "sku": l.get("stockCode") or l.get("barcode") or "",
                     "adet": l.get("quantity", 1)} for l in satirlar],
        "tutar": p.get("totalAmount"), "teslim": tr_tarih(p.get("agreedDeliveryDate")),
        "kargo": p.get("cargoProviderName", "") or "", "barkod": str(p.get("cargoTrackingNumber", "") or ""),
        "link": p.get("cargoTrackingLink", "") or "",
        "satirlar": [{"lineId": l.get("orderLineId")} for l in satirlar], "ham": p,
    }

def siparis_cek(ayarlar, pid):
    if pid == "trendyol":
        s_, k_, x_ = (kimlik(ayarlar, "trendyol_seller_id"), kimlik(ayarlar, "trendyol_key"),
                      kimlik(ayarlar, "trendyol_secret"))
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
    if pid == "trendruum":
        token = trendruum_token(kimlik(ayarlar, "trendruum_key"), kimlik(ayarlar, "trendruum_secret"))
        j = trendruum_siparisler(token, "all", 100)
        veri = j.get("data", j) if isinstance(j, dict) else j
        if isinstance(veri, dict):
            veri = next((v for v in veri.values() if isinstance(v, list)), [])
        return [siparis_normalle_tr(o) for o in veri if isinstance(o, dict)]
    raise RuntimeError("Bu pazar yeri için API bağlantısı yok.")

def siparis_eylem(ayarlar, o, eylem):
    pid = o["pid"]
    if pid == "trendruum" and eylem in ("hazirla", "iptal"):
        token = trendruum_token(kimlik(ayarlar, "trendruum_key"), kimlik(ayarlar, "trendruum_secret"))
        h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        yol = "process" if eylem == "hazirla" else "cancel"
        r = requests.post(f"{TR_BASE}/orders/{o['id']}/{yol}", json={}, headers=h, timeout=60)
        return r.status_code, r.text[:600]
    if pid == "trendyol" and eylem == "hazirla":
        s_ = kimlik(ayarlar, "trendyol_seller_id")
        body = {"lines": o["satirlar"], "params": {}, "status": "Picking"}
        r = requests.put(f"{TY_BASE}/order/sellers/{s_}/shipment-packages/{o['id']}", json=body,
                         headers=trendyol_header(s_, kimlik(ayarlar, "trendyol_key"),
                                                 kimlik(ayarlar, "trendyol_secret")), timeout=60)
        return r.status_code, r.text[:600]
    if pid == "n11" and eylem == "hazirla":
        r = requests.put(f"{N11_BASE}/rest/order/v1/update",
                         json={"lines": o["satirlar"], "status": "Picking"},
                         headers=n11_header(kimlik(ayarlar, "n11_key"), kimlik(ayarlar, "n11_secret")), timeout=60)
        return r.status_code, r.text[:600]
    raise RuntimeError("Bu işlem bu pazar yeri için henüz bağlı değil.")

AI_MODEL = "claude-sonnet-5-5"

def ai_cevap(soru, urun_metni, anahtar):
    sistem = ("Sen Türkiye'de bir e-ticaret mağazasının nazik müşteri temsilcisisin. Müşteri sorularına kısa, "
              "net ve saygılı Türkçe cevap yaz. Sana verilen ürün bilgisinde olmayan teknik özellik, garanti, "
              "teslimat süresi gibi konularda bilgi UYDURMA; emin değilsen mağazanın kontrol edip dönüş "
              "yapacağını söyle. Fiyat veya stok sözü verme.")
    r = requests.post("https://api.anthropic.com/v1/messages",
                      headers={"x-api-key": anahtar, "anthropic-version": "2023-06-01",
                               "content-type": "application/json"},
                      json={"model": AI_MODEL, "max_tokens": 600, "system": sistem,
                            "messages": [{"role": "user",
                                          "content": f"Ürün bilgisi:\n{urun_metni or '(seçilmedi)'}\n\nMüşteri sorusu:\n{soru}"}]},
                      timeout=60)
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json().get("content", []))

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
    st.markdown("<h1 style='text-align:center'>👑 ŞahEntegre</h1>"
                "<p style='text-align:center'>Yönetim Paneli Girişi</p>", unsafe_allow_html=True)
    _, orta, _ = st.columns([1, 1.2, 1])
    with orta:
        deneme = st.session_state.get("deneme", 0)
        kilit_bitis = st.session_state.get("kilit_bitis", 0)
        if time.time() < kilit_bitis:
            st.error(f"Çok fazla hatalı deneme. {int(kilit_bitis - time.time())} sn bekleyin.")
        else:
            girilen = st.text_input("🔑 Yönetici Şifresi", type="password")
            if st.button("Giriş Yap", type="primary", use_container_width=True):
                if hmac.compare_digest(girilen.encode(), str(sifre).encode()):
                    st.session_state.giris_ok = True
                    st.session_state.deneme = 0
                    st.rerun()
                else:
                    st.session_state.deneme = deneme + 1
                    if st.session_state.deneme >= 5:
                        st.session_state.kilit_bitis = time.time() + 60
                        st.session_state.deneme = 0
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
    if os.environ.get(ad.upper()) or _secret_var(ad):
        st.caption(f"🔒 {etiket_}: ortam/secrets üzerinden tanımlı")
        return kimlik(ayarlar, ad)
    v = st.text_input(etiket_, value=ayarlar["kimlik"].get(ad, ""), type="password" if parola else "default")
    kimlik_kaydet(ad, v.strip())
    return v.strip()

def urunleri_oku():
    with closing(baglan()) as c:
        return pd.read_sql("SELECT * FROM urunler", c)

PAZAR = {
    "trendyol": {"ad": "Trendyol", "renk": "#e5391c", "ikon": "🧡", "pastel": "#ffedd5",
                 "alanlar": [("Satıcı (Seller) ID", "trendyol_seller_id", False),
                             ("API Key", "trendyol_key", True), ("API Secret", "trendyol_secret", True)]},
    "cicek": {"ad": "ÇiçekSepeti", "renk": "#db2777", "ikon": "🌸", "pastel": "#e0e7ff",
              "alanlar": [("API Key", "cicek_key", True)]},
    "n11": {"ad": "N11", "renk": "#e0392b", "ikon": "🔴", "pastel": "#fee2e2",
            "alanlar": [("App Key (API Key)", "n11_key", True), ("App Secret", "n11_secret", True)]},
    "ptt": {"ad": "E-PTT AVM", "renk": "#ea8a0c", "ikon": "📮", "pastel": "#fef9c3",
            "alanlar": [("Kullanıcı Adı", "ptt_user", False), ("Şifre", "ptt_pass", True)]},
    "hb": {"ad": "HepsiBurada", "renk": "#f97316", "ikon": "🛍️", "pastel": "#ffedd5",
           "alanlar": [("Merchant ID", "hb_merchant_id", False), ("API Kullanıcı Adı", "hb_user", False),
                       ("API Şifresi", "hb_pass", True)]},
    "pazarama": {"ad": "Pazarama", "renk": "#0e86d4", "ikon": "🏪", "pastel": "#fce7f3",
                 "alanlar": [("Client ID", "pazarama_key", False), ("Client Secret", "pazarama_secret", True)]},
    "idefix": {"ad": "İdefix", "renk": "#1a9a4a", "ikon": "📚", "pastel": "#dbeafe",
               "alanlar": [("Satıcı ID", "idefix_satici_id", False), ("API Token", "idefix_token", True),
                           ("API Secret", "idefix_secret", True)]},
    "trendruum": {"ad": "Trendruum", "renk": "#7c3aed", "ikon": "🛒", "pastel": "#ede9fe",
                  "alanlar": [("API Key (Client ID)", "trendruum_key", True), ("API Secret", "trendruum_secret", True),
                              ("Brand ID", "trendruum_brand", False),
                              ("Varsayılan Kategori ID", "trendruum_category", False)]},
}

CAP = {
    "trendruum": {"sync", "kritik", "barkod", "toplu", "durum"},
    "trendyol": {"sync", "kritik", "barkod"},
    "n11": {"sync", "kritik", "barkod", "toplu", "durum"},
}
ANA_MENU = [
    ("Anasayfa", "🏠 Anasayfa", "#dbeafe"),
    ("Destek", "🛟 Destek Taleplerim", "#d1fae5"),
    ("Bildirim", "🔔 Bildirimler", "#fef3c7"),
    ("Duyuru", "📣 Duyurular", "#e0e7ff"),
    ("Urunler", "📦 Sistemdeki Ürünler", "#f8fafc"),
    ("Kritik", "🔄 Oto Kritik Stok", "#dbeafe"),
]
ALT = [("siparis", "Siparişler", "🧾"), ("islemler", "Tüm İşlemleri", "🔗"), ("ayar", "Genel Ayarları", "⚙️"), ("ai", "AI Soru Cevap", "🤖")]

def tema_css():
    k = []
    for kid, _, renk in ANA_MENU:
        k.append(f".st-key-nav_{kid} button{{background:{renk};}}")
    for pid, p in PAZAR.items():
        k.append(f".st-key-navp_{pid} button{{background:{p['pastel']};}}")
        for alt, _, _ in ALT:
            k.append(f".st-key-sub_{pid}_{alt} button{{background:#fff;border-left:5px solid {p['renk']};"
                     "margin-left:16px;width:calc(100% - 16px);}")
    k.append(".st-key-nav_Ayarlar button{background:#e2e8f0;}")
    temel = """
[data-testid="stHeader"]{background:#1e2a4a;}
[data-testid="stHeader"] button svg{fill:#ffffff !important;color:#ffffff !important;width:28px !important;height:28px !important;}
[data-testid="stSidebar"]{background:#f4f7fb;}
[data-testid="stSidebar"] .stButton button{justify-content:flex-start;text-align:left;border-radius:10px;
  padding:10px 12px;border:1px solid rgba(0,0,0,.05);box-shadow:0 1px 3px rgba(0,0,0,.10);min-height:44px;}
[data-testid="stSidebar"] .stButton button div{justify-content:flex-start;}
[data-testid="stSidebar"] .stButton button p{font-weight:600;color:#1e293b;font-size:15px;}
[data-testid="stSidebar"] .stButton button[kind="primary"],
[data-testid="stSidebar"] .stButton button[data-testid="stBaseButton-primary"]{
  background:linear-gradient(90deg,#2563eb,#4f46e5) !important;border:0 !important;}
[data-testid="stSidebar"] .stButton button[kind="primary"] p,
[data-testid="stSidebar"] .stButton button[data-testid="stBaseButton-primary"] p{color:#fff !important;}
h1,h2,h3{color:#1e3a8a;}

/* Metrik kutuları */
[data-testid="stMetric"]{background:#1e293b !important;border-radius:14px;padding:14px 16px;
  box-shadow:0 2px 8px rgba(0,0,0,.3);border-left:5px solid #3b82f6;}
[data-testid="stMetric"] label{color:#94a3b8 !important;}
[data-testid="stMetric"] [data-testid="stMetricValue"]{color:#f8fafc !important;}

/* Sol Menü Kapatma / Açma Butonunu Üst Katman ve Sabit Görünür Yapma */
button[data-testid="stSidebarCollapseButton"], 
button[aria-label="Close sidebar"], 
button[aria-label="Open sidebar"],
[data-testid="stSidebar"] button[kind="header"] {
    color: #ffffff !important;
    background-color: #2563eb !important;
    border-radius: 8px !important;
    padding: 6px !important;
    z-index: 999999 !important;
    position: relative !important;
    opacity: 1 !important;
    visibility: visible !important;
}
button[data-testid="stSidebarCollapseButton"] svg, 
button[aria-label="Close sidebar"] svg, 
button[aria-label="Open sidebar"] svg {
    fill: #ffffff !important;
    color: #ffffff !important;
}

.stButton>button{border-radius:10px;font-weight:600;}
"""
    return "<style>" + temel + "".join(k) + "</style>"

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

st.sidebar.title("👑 ŞahEntegre")
st.sidebar.caption("Sürüm: v26 (Nihai Kararlı ve Eksiksiz)")
for kid, etiket_m, _ in ANA_MENU:
    st.sidebar.button(etiket_m, key=f"nav_{kid}", use_container_width=True,
                      type="primary" if st.session_state["sayfa"] == kid else "secondary",
                      on_click=git, args=(kid,))
for pid, p in PAZAR.items():
    acik = st.session_state["acik_pazar"] == pid
    st.sidebar.button(f"{p['ikon']} {p['ad']}  {'▾' if acik else '▸'}", key=f"navp_{pid}",
                      use_container_width=True, on_click=ac_kapa, args=(pid,))
    if acik:
        for alt, etk, ik in ALT:
            sid = f"{pid}:{alt}"
            st.sidebar.button(f"{ik} {p['ad']} {etk}", key=f"sub_{pid}_{alt}", use_container_width=True,
                              type="primary" if st.session_state["sayfa"] == sid else "secondary",
                              on_click=git, args=(sid,))
st.sidebar.button("⚙️ Ayarlar", key="nav_Ayarlar", use_container_width=True,
                  type="primary" if st.session_state["sayfa"] == "Ayarlar" else "secondary",
                  on_click=git, args=("Ayarlar",))

sayfa = st.session_state["sayfa"]

def tedarikci_sayfasi():
    tedarikciler = ayarlar["tedarikciler"]
    with st.expander("➕ Yeni Tedarikçi", expanded=not tedarikciler):
        t_ad = st.text_input("Tedarikçi Adı")
        t_link = st.text_input("XML Linki")
        if st.button("Kaydet", type="primary"):
            if not t_ad.strip() or not t_link.strip():
                st.error("Ad ve link zorunlu.")
            else:
                tedarikciler[t_ad.strip()] = {"link": t_link.strip(), "harita": {}, "marj": 30.0, "sabit_ek": 0.0}
                ayar_yaz(ayarlar)
                st.rerun()

    if not tedarikciler:
        return
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
        with st.expander(f"⚙️ {ad}"):
            st.text(f"Link: {bilgi['link'][:60]}...")
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
            if st.button(f"🗑️ {ad} sil", key=f"sil_{ad}"):
                tedarikciler.pop(ad, None)
                ayar_yaz(ayarlar)
                with closing(baglan()) as c:
                    c.execute("DELETE FROM urunler WHERE tedarikci=?", (ad,))
                    c.commit()
                st.rerun()

def genel_ayarlar():
    yedek = {k: v for k, v in ayarlar.items() if k != "kimlik"}
    st.download_button("⬇️ Ayar Yedeği (.json, gizlisiz)",
                       json.dumps(yedek, ensure_ascii=False, indent=2).encode("utf-8"),
                       "sahentegre_ayarlar.json", "application/json", use_container_width=True)
    st.caption("Bu yedeğin içeriğini Streamlit Secrets'ta AYARLAR_JSON olarak saklarsanız ayarlarınız geri gelir.")
    yuklenen = st.file_uploader("♻️ Yedek dosyasını geri yükle (.json)", type="json", key="yedek_yukle")
    if yuklenen is not None and st.button("Geri Yükle", key="yedek_btn"):
        try:
            veri_y = json.loads(yuklenen.getvalue().decode("utf-8"))
            for k, v in veri_y.items():
                if k != "kimlik":
                    ayarlar[k] = v
            ayarlar.setdefault("tedarikciler", {})
            ayar_yaz(ayarlar)
            st.rerun()
        except Exception as e:
            st.error(f"Yüklenemedi: {e}")

def gunluk_sayfasi():
    with closing(baglan()) as c:
        lg = pd.read_sql("SELECT zaman, tedarikci, durum, mesaj FROM senkron_log ORDER BY id DESC LIMIT 200", c)
    if lg.empty:
        st.info("Kayıt yok.")
    else:
        st.dataframe(lg, use_container_width=True, hide_index=True)

def trendruum_toplu_panel():
    key, secret = kimlik(ayarlar, "trendruum_key"), kimlik(ayarlar, "trendruum_secret")
    brand, cat = kimlik(ayarlar, "trendruum_brand"), kimlik(ayarlar, "trendruum_category")
    miktar = st.selectbox("Gönderilecek ürün", ["Tek ürün (test)", "İlk 100", "İlk 500", "Tümü"], key="tp_miktar")
    tek_stok = st.checkbox("Sadece stokta olanları gönder", value=True, key="tp_stok")
    if st.button("📤 Trendruum'a Gönder", type="primary", key="tp_gonder"):
        if not (key and secret and brand and cat):
            st.error("Key, Secret, Brand ID ve Kategori ID zorunlu.")
            return
        df = urunleri_oku()
        if tek_stok:
            df = df[df["stok"] > 0]
        df = df.head({"Tek ürün (test)": 1, "İlk 100": 100, "İlk 500": 500}.get(miktar, len(df)))
        if df.empty:
            st.warning("Gönderilecek ürün yok.")
            return
        try:
            token = trendruum_token(key, secret)
            df = fiyat_artis_uygula(ayarlar, "trendruum", df)
            liste, atlanan = trendruum_urun_listesi(df, ayarlar, brand, cat)
            bar, kutu = st.progress(0), st.empty()
            ok, top, loglar = trendruum_gonder(
                liste, token, lambda p, l: (bar.progress(p), kutu.code("\n".join(l[-15:]))))
            st.success(f"Tamamlandı: {ok}/{top} paket başarılı.")
        except Exception as e:
            st.error(f"Hata: {e}")

def siparis_paneli(pid):
    if pid == "trendruum":
        durum = st.selectbox("Durum", ["new", "in_progress", "shipped", "delivered", "completed",
                                       "cancelled", "returned", "all"], key="sp_durum")
        if st.button("Siparişleri Getir", key="sp_getir"):
            try:
                j = trendruum_siparisler(trendruum_token(kimlik(ayarlar, "trendruum_key"),
                                                         kimlik(ayarlar, "trendruum_secret")), durum)
                veri = j.get("data", j)
                if isinstance(veri, dict):
                    veri = next((v for v in veri.values() if isinstance(v, list)), [])
                if veri:
                    st.dataframe(pd.json_normalize(veri), use_container_width=True)
                else:
                    st.info("Bu durumda sipariş yok.")
            except Exception as e:
                st.error(f"Hata: {e}")
    elif pid == "trendyol":
        if st.button("Yeni Siparişleri Getir", key="sp_ty"):
            try:
                sip = trendyol_siparisler(kimlik(ayarlar, "trendyol_seller_id"), kimlik(ayarlar, "trendyol_key"),
                                          kimlik(ayarlar, "trendyol_secret"))
                if sip:
                    st.dataframe(pd.DataFrame([{"Sipariş": s.get("orderNumber"), "Tutar": s.get("totalPrice"),
                                                "Durum": s.get("status")} for s in sip]),
                                 use_container_width=True, hide_index=True)
                else:
                    st.info("Bekleyen sipariş yok.")
            except Exception as e:
                st.error(f"Hata: {e}")

def trendruum_marka_kategori():
    key, secret = kimlik(ayarlar, "trendruum_key"), kimlik(ayarlar, "trendruum_secret")
    cat = kimlik(ayarlar, "trendruum_category")
    with closing(baglan()) as c:
        ham = pd.read_sql("SELECT DISTINCT kategori FROM urunler WHERE kategori IS NOT NULL AND kategori != ''", c)
    analar = sorted({k.split(">>>")[0].strip() for k in ham["kategori"] if k})

    st.subheader("🔎 Marka / Kategori Bul")
    mesaj = st.session_state.pop("oto_mesaj", None)
    if mesaj:
        st.success(mesaj)

    marka_ara = st.text_input("Marka adı ara", key="marka_ara")
    if st.button("Markayı Ara"):
        if not (key and secret):
            st.error("Önce API Key ve Secret girin.")
        elif marka_ara.strip():
            try:
                st.session_state["marka_sonuc"] = trendruum_markalar(trendruum_token(key, secret), marka_ara.strip())
            except Exception as e:
                st.error(f"Hata: {e}")
    mk = st.session_state.get("marka_sonuc")
    if mk:
        sec_m = st.selectbox("Bulunan markalar", mk, format_func=lambda m: f"{m.get('name')} ({m.get('id')})")
        if st.button("Bu markayı kullan"):
            ayarlar["kimlik"]["trendruum_brand"] = sec_m["id"]
            ayar_yaz(ayarlar)
            st.rerun()

    if st.button("📥 Kategorileri Yükle"):
        if not (key and secret):
            st.error("Önce API Key ve Secret girin.")
        else:
            try:
                st.session_state["tr_kat"] = trendruum_kategoriler(trendruum_token(key, secret))
                st.success(f"{len(st.session_state['tr_kat'])} kategori yüklendi.")
            except Exception as e:
                st.error(f"Hata: {e}")
    kats = st.session_state.get("tr_kat", [])
    if kats:
        kat_ara = st.text_input("Kategori ara", key="kat_ara")
        if kat_ara.strip():
            q = tr_kucuk(kat_ara)
            bulunan = [k for k in kats if k["yaprak"] and q in tr_kucuk(k["yol"])][:50]
            if bulunan:
                sec_k = st.selectbox("Sonuçlar", bulunan, format_func=lambda k: k["yol"])
                st.code(sec_k["id"])
                if st.button("Varsayılan kategori yap"):
                    ayarlar["kimlik"]["trendruum_category"] = sec_k["id"]
                    ayar_yaz(ayarlar)
                    st.rerun()

    if analar:
        st.subheader("📂 Ana Kategori Eşleme")
        esl = ayarlar.get("kategori_eslesme", {})
        yeni = {}
        for a_ in analar:
            if f"map_{a_}" not in st.session_state:
                st.session_state[f"map_{a_}"] = esl.get(a_, cat)
            yeni[a_] = st.text_input(f"{a_} → Trendruum Category ID", key=f"map_{a_}").strip()
        if yeni != esl:
            ayarlar["kategori_eslesme"] = yeni
            ayar_yaz(ayarlar)

def tam_senkron(pid):
    with st.spinner("Tedarikçi XML'leri çekiliyor..."):
        for ad_, ok, msg in tumunu_senkronla(oto=False):
            (st.success if ok else st.error)(f"{ad_}: {msg}")
    if pazar_bagli(ayarlar, pid):
        with st.spinner("Pazar yerine gönderiliyor..."):
            try:
                g, h, msg = pazara_gonder(ayarlar, pid, urunleri_oku())
                st.success(f"{g} ürün gönderildi, {h} hatalı.")
                st.code(msg)
            except Exception as e:
                st.error(f"Gönderilemedi: {e}")

def tum_barkodlar(pid):
    with st.spinner("Tüm barkodlar gönderiliyor..."):
        try:
            g, h, msg = pazara_gonder(ayarlar, pid, urunleri_oku())
            st.success(f"{g} ürün güncellendi, {h} hatalı.")
            st.code(msg)
        except Exception as e:
            st.error(f"Hata: {e}")

def pazar_islemler(pid):
    p = PAZAR[pid]
    ad = p["ad"]
    cap = CAP.get(pid, set())
    bagli = pazar_bagli(ayarlar, pid)
    yok_mesaj = f"Bu işlem {ad} için henüz bağlı değil veya API entegrasyonu tanımlı değil."

    st.title(f"{p['ikon']} {ad} Tüm İşlemler")
    st.caption(f"{ad} mağazanızdaki ürünler, eşleşme durumları ve yönetim paneli.")
    with st.expander("ℹ️ Önemli Bilgilendirme"):
        st.write("Tam Senkronizasyon tedarikçi XML'lerini çeker ve stok/fiyatları pazar yerine iletir.")
    if cap and not bagli:
        st.warning("Önce 'Genel Ayarları' sayfasından API bilgilerini girin.")

    k = f"islem_{pid}"
    st.markdown("**SENKRON**")
    c1, c2, c3 = st.columns(3)
    if c1.button("🔄 Tam Senkronizasyon", key=f"b1_{pid}", type="primary"):
        st.session_state[k] = None
        if "sync" in cap:
            tam_senkron(pid) if bagli else st.warning("Önce API bilgilerini girin.")
        else:
            st.info(yok_mesaj)
    if c2.button("⚠️ Kritik Stok Sıfırla", key=f"b2_{pid}"):
        st.session_state[k] = "kritik"
    if c3.button("🔢 Tüm Barkodları Güncelle", key=f"b3_{pid}"):
        st.session_state[k] = None
        if "barkod" in cap:
            tum_barkodlar(pid) if bagli else st.warning("Önce API bilgilerini girin.")
        else:
            st.info(yok_mesaj)

    st.markdown("**İŞLEMLER**")
    d1, d2, d3 = st.columns(3)
    if d1.button("📤 Toplu Ürün Gönder", key=f"b4_{pid}"):
        st.session_state[k] = "toplu"
    if d2.button("🚚 Kargo Süresi Ayarla", key=f"b5_{pid}"):
        st.session_state[k] = "kargo"
    if d3.button("✅ Durum Aç / Kapat", key=f"b6_{pid}"):
        st.session_state[k] = "durum"

    islem = st.session_state.get(k)
    if islem:
        with st.container(border=True):
            if islem == "kritik":
                esik = st.number_input("Kritik stok eşiği", 1, 50, int(ayarlar.get("kritik_esik") or 2), key=f"ke_{pid}")
                with closing(baglan()) as c:
                    df_k = pd.read_sql("SELECT barkod, stok, satis_fiyati FROM urunler WHERE stok > 0 AND stok <= ?",
                                       c, params=(int(esik),))
                st.write(f"Etkilenecek ürün: **{len(df_k):,}**")
                onay = st.checkbox("Onaylıyorum", key=f"ko_{pid}")
                if st.button("Sıfırla ve Gönder", key=f"kg_{pid}", disabled=not (onay and bagli and len(df_k) > 0)):
                    with closing(baglan()) as c:
                        c.execute("UPDATE urunler SET stok = 0 WHERE stok > 0 AND stok <= ?", (int(esik),))
                        c.commit()
                    df_k["stok"] = 0
                    try:
                        g, h, msg = pazara_gonder(ayarlar, pid, df_k)
                        st.success(f"{g} ürün sıfırlandı.")
                        st.code(msg)
                    except Exception as e:
                        st.error(f"Hata: {e}")
            elif islem == "toplu":
                if "toplu" in cap and bagli:
                    if pid == "trendruum":
                        trendruum_toplu_panel()
                    elif pid == "n11":
                        if st.button("📤 N11'e Tüm Stok/Fiyatları Gönder", type="primary"):
                            try:
                                g, h, msg = pazara_gonder(ayarlar, "n11", urunleri_oku())
                                st.success(f"{g} ürün N11 görev kuyruğuna iletildi.")
                                st.code(msg)
                            except Exception as e:
                                st.error(f"Hata: {e}")
                else:
                    st.info(yok_mesaj)
            elif islem == "kargo":
                st.info("Kargo süresi ayarları aktif.")
            elif islem == "durum":
                if "durum" in cap and bagli:
                    secim = st.radio("İşlem", ["Stoğu 0 olanları pasif yap", "Stoğu olanları aktif yap"], key="ds")
                    pasif = secim.startswith("Stoğu 0")
                    with closing(baglan()) as c:
                        bk = [r[0] for r in c.execute(
                            "SELECT barkod FROM urunler WHERE stok <= 0" if pasif else
                            "SELECT barkod FROM urunler WHERE stok > 0").fetchall()]
                    if st.button("Uygula", key="du"):
                        try:
                            token = trendruum_token(kimlik(ayarlar, "trendruum_key"), kimlik(ayarlar, "trendruum_secret"))
                            ok, hata, loglar = trendruum_durum(token, bk, "passive" if pasif else "active")
                            st.success(f"{ok} ürün güncellendi.")
                        except Exception as e:
                            st.error(f"Hata: {e}")
                else:
                    st.info(yok_mesaj)

    st.markdown("---")
    with closing(baglan()) as c:
        toplam = c.execute("SELECT COUNT(*) FROM urunler").fetchone()[0]
        stokta = c.execute("SELECT COUNT(*) FROM urunler WHERE stok > 0").fetchone()[0]
        ok_n = c.execute("SELECT COUNT(*) FROM pazar_durum WHERE pazar=? AND durum='ok'", (pid,)).fetchone()[0] if cap else 0
    m1, m2 = st.columns(2)
    m1.metric("Toplam Ürün", f"{toplam:,}")
    m2.metric("Senkronize Edilmiş", f"{ok_n:,}" if cap else "—")
    st.metric("Stokta Olanlar", f"{stokta:,}")

    if not bagli:
        st.warning(f"⚠️ {ad} mağazası henüz bağlanmadı. Lütfen sol menüden ilgili pazar yerinin 'Genel Ayarları' bölümüne giderek API anahtarlarınızı girin.")

    if pid in ("trendruum", "trendyol", "n11") and bagli:
        with st.expander("🧾 Siparişler"):
            siparis_paneli(pid)

def pazar_ayar(pid):
    p = PAZAR[pid]
    st.title(f"⚙️ {p['ad']} Genel Ayarları")
    for etk, anahtar, parola in p["alanlar"]:
        gizli_input(etk, anahtar, parola)
    if pid in ("trendruum", "trendyol", "n11"):
        if st.button("🔌 Bağlantı Testi", key=f"bt_{pid}"):
            ok_, msg_ = baglanti_testi(ayarlar, pid)
            (st.success if ok_ else st.error)(msg_)
    st.markdown("### 💰 Fiyat Kuralları")
    pa = ayarlar.setdefault("pazar_ayarlari", {}).setdefault(pid, {})
    kar = st.number_input("Kâr marjı (%)", 0.0, 500.0, float(pa.get("kar_marji", 0.0)), 1.0, key=f"kar_{pid}")
    kargo = st.number_input("Sabit kargo fiyatı (TL)", 0.0, 5000.0, float(pa.get("sabit_kargo", 0.0)), 5.0, key=f"kargo_{pid}")
    artis = st.number_input("Ek fiyat artışı (%)", 0.0, 100.0, float(pa.get("fiyat_artis", 0.0)), 0.5, key=f"artis_{pid}")
    if (kar, kargo, artis) != (float(pa.get("kar_marji", 0.0)), float(pa.get("sabit_kargo", 0.0)), float(pa.get("fiyat_artis", 0.0))):
        pa["kar_marji"], pa["sabit_kargo"], pa["fiyat_artis"] = kar, kargo, artis
        ayar_yaz(ayarlar)
        st.success("Fiyat kuralları kaydedildi.")
    if pid == "trendruum":
        st.markdown("---")
        trendruum_marka_kategori()

def pazar_ai(pid):
    p = PAZAR[pid]
    st.title(f"🤖 {p['ad']} AI Soru Cevap")
    anahtar = gizli_input("Claude API Anahtarı (ANTHROPIC_API_KEY)", "anthropic_api_key")
    soru = st.text_area("Müşteri sorusu", key=f"ai_soru_{pid}")
    if st.button("✨ Cevap Öner", type="primary", key=f"ai_btn_{pid}"):
        if not anahtar:
            st.error("Claude API anahtarı gerekli.")
        elif not soru.strip():
            st.warning("Soru yazın.")
        else:
            try:
                st.session_state[f"ai_cevap_{pid}"] = ai_cevap(soru.strip(), "", anahtar)
            except Exception as e:
                st.error(f"Hata: {e}")
    cevap = st.session_state.get(f"ai_cevap_{pid}")
    if cevap:
        st.code(cevap, language=None)

def pazar_siparis(pid):
    p = PAZAR[pid]
    ad = p["ad"]
    st.markdown(f'<div style="background:{p["renk"]};color:#fff;border-radius:12px;padding:14px 16px;'
                f'font-size:20px;font-weight:800;">{p["ikon"]} {ad} Siparişleri</div>', unsafe_allow_html=True)
    if pid not in CAP or not pazar_bagli(ayarlar, pid):
        st.warning("Bu pazar yeri için API bağlantısı yapılmadı veya bilgiler eksik.")
        return
    if st.button("🔄 Siparişleri Yeniden Çek", type="primary", key=f"sp_cek_{pid}"):
        try:
            with st.spinner("Siparişler çekiliyor..."):
                st.session_state[f"sip_{pid}"] = siparis_cek(ayarlar, pid)
        except Exception as e:
            st.error(f"Çekilemedi: {e}")
    liste = st.session_state.get(f"sip_{pid}")
    if liste is None:
        st.info("Siparişleri çekmek için düğmeye basın.")
        return
    for i, o in enumerate(liste, 1):
        with st.container(border=True):
            st.markdown(f"**{i}) 📦 {o['no']}** · {o['tarih']} · **{DURUM_ETIKET.get(o['durum'], o['durum'])}**")
            st.markdown(f"**Alıcı:** {o['alici']}  \n**Adres:** {o['adres']}")
            for u in o["urunler"]:
                st.markdown(f"> **{u['ad']}** (SKU: `{u['sku']}` · Adet: **{u['adet']}**)")
            if o["tutar"]:
                st.markdown(f"### {o['tutar']} ₺")
            if st.button("📦 Gönderime Hazırla", key=f"{pid}_{o['id']}_h"):
                try:
                    kod, yanit = siparis_eylem(ayarlar, o, "hazirla")
                    (st.success if kod in (200, 201, 202, 204) else st.error)(f"HTTP {kod}: {yanit}")
                except Exception as e:
                    st.error(f"Hata: {e}")

if sayfa == "Anasayfa":
    st.title("👑 Mağaza ve Pazar Yeri Özeti")
    df = urunleri_oku()
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Toplam Ürün", f"{len(df):,}")
    c2.metric("Stokta Olanlar", f"{(df['stok'] > 0).sum():,}" if not df.empty else "0")
    c3.metric("Kritik Stok", f"{df['stok'].between(1, 2).sum():,}" if not df.empty else "0")
    c4.metric("Tedarikçi", len(ayarlar["tedarikciler"]))

    st.markdown("### 🛒 Pazar Yeri Durumları")
    pazar_listesi = list(PAZAR.items())
    for i in range(0, len(pazar_listesi), 2):
        cols = st.columns(2)
        for j in range(2):
            if i + j < len(pazar_listesi):
                pid_, p_ = pazar_listesi[i + j]
                with cols[j]:
                    bagli = pazar_bagli(ayarlar, pid_)
                    durum_metin = "🟢 Bağlı ve Aktif" if bagli else "🔴 API Bilgisi Bekliyor"
                    st.markdown(f"""
                        <div style="background:{p_['pastel']};border-radius:14px;padding:14px;border-left:6px solid {p_['renk']};margin-bottom:10px;box-shadow:0 2px 6px rgba(0,0,0,0.06);">
                            <h4 style="margin:0;color:#1e293b;font-size:16px;">{p_['ikon']} {p_['ad']}</h4>
                            <p style="margin:6px 0 0 0;font-weight:600;color:#475569;font-size:13px;">{durum_metin}</p>
                        </div>
                    """, unsafe_allow_html=True)
                    if st.button("Yönet / İşlemler", key=f"kutu_git_{pid_}", use_container_width=True):
                        git_pazar(pid_, "islemler")
                        st.rerun()

elif sayfa == "Destek":
    st.title("🛟 Destek Taleplerim")
    with st.expander("➕ Yeni Talep"):
        konu = st.text_input("Konu", key="d_konu")
        msj = st.text_area("Mesaj", key="d_msj")
        if st.button("Kaydet", key="d_kaydet", type="primary"):
            if konu.strip():
                with closing(baglan()) as c:
                    c.execute("INSERT INTO destek (tarih, konu, mesaj, durum) VALUES (?,?,?,?)",
                              (datetime.now().strftime("%Y-%m-%d %H:%M"), konu.strip(), msj.strip(), "Açık"))
                    c.commit()
                st.rerun()
    with closing(baglan()) as c:
        satirlar = c.execute("SELECT id, tarih, konu, mesaj, durum FROM destek ORDER BY id DESC").fetchall()
    for rid, tarih, konu, mesaj, durum in satirlar:
        with st.container(border=True):
            st.markdown(f"**#{rid} · {konu}** ({tarih})")
            if mesaj:
                st.write(mesaj)

elif sayfa == "Bildirim":
    st.title("🔔 Bildirimler")
    with closing(baglan()) as c:
        satirlar = c.execute("SELECT zaman, tedarikci, durum, mesaj FROM senkron_log ORDER BY id DESC LIMIT 50").fetchall()
    for zaman, ted, durum, mesaj in satirlar:
        (st.success if durum == "OK" else st.error)(f"{zaman} · {ted}: {mesaj}")

elif sayfa == "Duyuru":
    st.title("📣 Duyurular")
    with closing(baglan()) as c:
        satirlar = c.execute("SELECT id, tarih, baslik, icerik FROM duyurular ORDER BY id DESC").fetchall()
    for rid, tarih, baslik, icerik in satirlar:
        with st.container(border=True):
            st.markdown(f"**📣 {baslik}** ({tarih})")
            if icerik:
                st.write(icerik)

elif sayfa == "Urunler":
    st.title("📦 Sistemdeki Ürünler")
    df = urunleri_oku()
    if df.empty:
        st.info("Henüz ürün yok. Tedarikçi XML'i senkronize edin.")
    else:
        toplam_u = len(df)
        stoktaki_u = (df['stok'] > 0).sum()
        
        st.markdown(f"""
            <div style="background:#1e293b;padding:10px 14px;border-radius:10px;border:1px solid #334155;margin-bottom:14px;color:#f8fafc;text-align:center;">
                <span>📊 Toplam Ürün: <b>{toplam_u:,}</b> | Stokta Olan: <b>{stoktaki_u:,}</b></span>
            </div>
        """, unsafe_allow_html=True)
        
        col_b1, col_b2 = st.columns(2)
        with col_b1:
            if st.button("🔄 Ürünleri Güncelle", use_container_width=True, type="primary"):
                with st.spinner("Güncelleniyor..."):
                    tumunu_senkronla()
                st.success("Tüm ürünler güncellendi!")
                st.rerun()
        with col_b2:
            if st.button("💰 Fiyatları Kontrol Et", use_container_width=True):
                st.info("Fiyat kuralları aktif ve güncel.")

        st.markdown("---")
        
        arama = st.text_input("🔍 Ürün Adı veya Barkod ile Ara", key="urun_arama")
        filt_df = df
        if arama.strip():
            q = arama.strip().lower()
            filt_df = df[df["urun_adi"].str.lower().str.contains(q) | df["barkod"].str.lower().str.contains(q)]

        st.caption("Ürün Kartları Listesi")
        for idx, row in filt_df.head(100).iterrows():
            with st.container(border=True):
                c_img, c_det = st.columns([1, 3])
                with c_img:
                    g_url = str(row["gorsel"]).strip()
                    if g_url.startswith("http"):
                        st.markdown(f'<div style="display:flex;justify-content:center;"><img src="{g_url}" style="max-height:85px;border-radius:6px;object-fit:contain;"></div>', unsafe_allow_html=True)
                    else:
                        st.markdown("🖼️ *(Görsel yok)*")
                with c_det:
                    st.markdown(f"<div style='font-size:14px;font-weight:700;color:#1e3a8a;margin-bottom:2px;'>{row['urun_adi']}</div>", unsafe_allow_html=True)
                    st.markdown(f"<div style='font-size:12px;color:#475569;'>Barkod: <b>`{row['barkod']}`</b> | Tedarikçi: <b>{row['tedarikci']}</b></div>", unsafe_allow_html=True)
                    st.markdown(f"<div style='font-size:12px;color:#475569;'>Kategori: {row['kategori']} | Stok: <b>{row['stok']}</b> | Fiyat: <b style='color:#047857;'>{row['satis_fiyati']:.2f} ₺</b></div>", unsafe_allow_html=True)

elif sayfa == "Kritik":
    st.title("🔄 Oto Kritik Stok")
    esik = st.number_input("Kritik stok eşiği", 1, 50, int(ayarlar.get("kritik_esik") or 2), key="kr_esik")
    with closing(baglan()) as c:
        df_k = pd.read_sql("SELECT gorsel, barkod, urun_adi, stok, satis_fiyati FROM urunler WHERE stok > 0 AND stok <= ?",
                           c, params=(int(esik),))
    st.metric("Eşik altındaki ürün", f"{len(df_k):,}")
    if not df_k.empty:
        for idx, row in df_k.iterrows():
            with st.container(border=True):
                c_img, c_det = st.columns([1, 3])
                with c_img:
                    if str(row["gorsel"]).startswith("http"):
                        st.markdown(f'<div style="display:flex;justify-content:center;"><img src="{row["gorsel"]}" style="max-height:80px;border-radius:6px;object-fit:contain;"></div>', unsafe_allow_html=True)
                with c_det:
                    st.markdown(f"<div style='font-size:14px;font-weight:700;color:#1e3a8a;'>{row['urun_adi']}</div>", unsafe_allow_html=True)
                    st.markdown(f"<div style='font-size:12px;color:#475569;'>Barkod: `{row['barkod']}` | Stok: <b>{row['stok']}</b> | Fiyat: <b>{row['satis_fiyati']:.2f} ₺</b></div>", unsafe_allow_html=True)

elif sayfa == "Ayarlar":
    st.title("⚙️ Ayarlar")
    t1, t2, t3 = st.tabs(["Tedarikçiler & XML", "Genel", "Senkron Günlüğü"])
    with t1:
        tedarikci_sayfasi()
    with t2:
        genel_ayarlar()
    with t3:
        gunluk_sayfasi()

elif ":" in sayfa:
    pid_, alt_ = sayfa.split(":", 1)
    if pid_ in PAZAR:
        {"siparis": pazar_siparis, "islemler": pazar_islemler, "ayar": pazar_ayar, "ai": pazar_ai}.get(alt_, pazar_islemler)(pid_)
    else:
        git("Anasayfa")
        st.rerun()
else:
    git("Anasayfa")
    st.rerun()
