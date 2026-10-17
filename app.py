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
from html import escape as esc
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="ŞahEntegre - E-Ticaret Yönetim Paneli", page_icon="👑", layout="wide")

BASE = Path(__file__).parent
DB_DOSYA = BASE / "metentegre.db"
AYAR_DOSYA = BASE / "ayarlar.json"
SENKRON_ARALIK = 6 * 3600
KILIT = threading.Lock()
SENKRON_KILIDI = threading.Lock()

KIMLIK_ALANLARI = [
    "trendruum_key", "trendruum_secret", "trendruum_brand", "trendruum_category",
    "trendyol_seller_id", "trendyol_key", "trendyol_secret",
    "hb_merchant_id", "hb_user", "hb_pass",
    "idefix_satici_id", "idefix_token", "idefix_secret",
    "n11_key", "n11_secret", "cicek_key", "ptt_user", "ptt_pass",
    "pazarama_key", "pazarama_secret", "anthropic_api_key",
]

VARSAYILAN = {
    "tedarikciler": {},
    "kimlik": {
        "hb_merchant_id": "4fd80747-062b-41e8-980b-30a5481a8e1e",
        "hb_user": "sahin724_dev",
        "hb_pass": "uExAH7y8Qxuw",
    },
    "kategori_eslesme": {},
    "kritik_esik": 0,
    "oto_senkron": True,
    "tr_oto_guncelle": False,
    "ty_oto_guncelle": False,
    "n11_oto_guncelle": False,
    "idefix_oto_guncelle": False,
    "hb_oto_guncelle": False,
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
        veri["tedarikciler"] = {k: v for k, v in veri.items() if isinstance(v, dict) and "link" in v}
    for k, v in VARSAYILAN.items():
        veri.setdefault(k, json.loads(json.dumps(v)))
    if not veri["tedarikciler"]:
        for k, v in _ayar_tohumu().items():
            if k != "kimlik" and not veri.get(k):
                veri[k] = v
    for k in KIMLIK_ALANLARI:
        if k in veri and isinstance(veri[k], str):
            veri["kimlik"].setdefault(k, veri.pop(k))
    veri["kimlik"].setdefault("hb_merchant_id", "4fd80747-062b-41e8-980b-30a5481a8e1e")
    veri["kimlik"].setdefault("hb_user", "sahin724_dev")
    veri["kimlik"].setdefault("hb_pass", "uExAH7y8Qxuw")
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
        c.execute("""CREATE TABLE IF NOT EXISTS urunler (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gorsel TEXT, tedarikci TEXT, barkod TEXT, urun_adi TEXT, stok INTEGER,
            alis_fiyati REAL, satis_fiyati REAL, kategori TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS senkron_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, zaman TEXT, tedarikci TEXT, durum TEXT, mesaj TEXT)""")
        c.execute("CREATE INDEX IF NOT EXISTS ix_urun ON urunler(tedarikci, barkod)")
        c.execute("""CREATE TABLE IF NOT EXISTS destek (
            id INTEGER PRIMARY KEY AUTOINCREMENT, tarih TEXT, konu TEXT, mesaj TEXT, durum TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS duyurular (
            id INTEGER PRIMARY KEY AUTOINCREMENT, tarih TEXT, baslik TEXT, icerik TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS pazar_durum (
            pazar TEXT, barkod TEXT, durum TEXT, zaman TEXT, PRIMARY KEY (pazar, barkod))""")
        c.commit()

db_olustur()

def log_yaz(tedarikci, durum, mesaj=""):
    with closing(baglan()) as c:
        c.execute("INSERT INTO senkron_log (zaman, tedarikci, durum, mesaj) VALUES (?,?,?,?)",
                  (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), tedarikci, durum, str(mesaj)[:500]))
        c.commit()

def pazar_isaretle(pazar, ok_list, hata_list):
    z = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = [(pazar, str(b), "ok", z) for b in ok_list] + [(pazar, str(b), "hata", z) for b in hata_list]
    if not rows:
        return
    with closing(baglan()) as c:
        c.executemany("INSERT OR REPLACE INTO pazar_durum (pazar, barkod, durum, zaman) VALUES (?,?,?,?)", rows)
        c.commit()

def urunleri_oku():
    with closing(baglan()) as c:
        return pd.read_sql("SELECT * FROM urunler", c)

def http(method, url, tries=4, **kw):
    kw.setdefault("timeout", 120)
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
        raise ValueError("XML'den geçerli ürün çıkmadı (mevcut veri korunuyor).")
    with closing(baglan()) as c:
        c.execute("BEGIN")
        c.execute("DELETE FROM urunler WHERE tedarikci = ?", (ad,))
        c.executemany(
            "INSERT INTO urunler (gorsel, tedarikci, barkod, urun_adi, stok, alis_fiyati, satis_fiyati, kategori) "
            "VALUES (?,?,?,?,?,?,?,?)",
            df[["gorsel", "tedarikci", "barkod", "urun_adi", "stok", "alis_fiyati",
                "satis_fiyati", "kategori"]].itertuples(index=False, name=None))
        c.commit()
    return len(df)

def pazar_bagli(ayarlar, pid):
    gerek = {
        "trendruum": ["trendruum_key", "trendruum_secret"],
        "trendyol": ["trendyol_seller_id", "trendyol_key", "trendyol_secret"],
        "n11": ["n11_key", "n11_secret"],
        "cicek": ["cicek_key"],
        "ptt": ["ptt_user", "ptt_pass"],
        "hb": ["hb_merchant_id", "hb_user", "hb_pass"],
        "pazarama": ["pazarama_key", "pazarama_secret"],
        "idefix": ["idefix_satici_id", "idefix_token", "idefix_secret"],
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
    temiz = "".join(ch for ch in str(kod) if ch.isdigit())
    if len(temiz) >= 8:
        return temiz
    if not uret:
        return None
    h = int(hashlib.md5(str(kod).encode()).hexdigest(), 16) % 10**9
    return f"869{h:09d}"

def tr_ayar(ayarlar):
    pa = (ayarlar.get("pazar_ayarlari", {}) or {}).get("trendruum", {}) or {}
    return bool(pa.get("gecici_barkod", False)), int(pa.get("kdv", 20) or 20)

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
    uret, kdv = tr_ayar(ayarlar)
    liste, atlanan = [], 0
    for _, row in df.iterrows():
        gorsel = str(row["gorsel"]).strip()
        kod = str(row["barkod"]).strip()
        barkod = sabit_barkod(kod, uret)
        if not gorsel or row["satis_fiyati"] <= 0 or not barkod:
            atlanan += 1
            continue
        ana = str(row.get("kategori", "")).split(">>>")[0].strip()
        liste.append({
            "name": str(row["urun_adi"]),
            "model_code": kod,
            "category_id": (str(harita.get(ana) or "").strip() if objectid_mi(harita.get(ana)) else varsayilan_cat),
            "brand_id": brand_id,
            "children_products": [{
                "barcode": barkod,
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
                    metin_ = " ".join(map(str, (j.get("errors") or {}).get("errors", []))) or r.text
                except Exception:
                    metin_ = r.text
                cakisan = set(re.findall(r"(\d{6,})\\?\"\s*barkodu", metin_))
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
        else:
            loglar.append(f"❌ Paket {no}: 8 denemede gönderilemedi")
            art_arda += 1
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

def trendruum_guncelle(df, token, ilerleme=None, uret=False):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    items, orijin, atlanan = [], {}, 0
    for _, r in df.iterrows():
        if r["satis_fiyati"] > 0:
            raw_b = str(r["barkod"]).strip()
            sb = sabit_barkod(raw_b, uret=True)
            if not sb:
                atlanan += 1
                continue
            orijin[sb] = raw_b
            orijin[raw_b] = raw_b
            items.append({"barcode": sb, "price": float(r["satis_fiyati"]), "stock": int(r["stok"])})
    toplam = max(1, (len(items) + 999) // 1000)
    guncel, hata, ornek, loglar, hata_s = 0, 0, [], [], set()
    if atlanan:
        loglar.append(f"ℹ️ {atlanan} ürün geçerli barkodu olmadığı için atlandı")
    for i in range(0, len(items), 1000):
        no = i // 1000 + 1
        grup = items[i:i + 1000]
        try:
            r = http("POST", f"{TR_BASE}/products/bulk-update", json={"products": grup},
                     headers=headers, timeout=120)
        except Exception as e:
            hata += len(grup)
            hata_s |= {x["barcode"] for x in grup}
            loglar.append(f"⚠️ Paket {no}: {e}")
            continue
        if r.status_code == 200:
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
            loglar.append(f"❌ Paket {no}: HTTP {r.status_code} {r.text[:200]}")
        if ilerleme:
            ilerleme(no / toplam)
    try:
        pazar_isaretle("trendruum", [orijin[b] for b in orijin if b not in hata_s],
                       [orijin[b] for b in hata_s if b in orijin])
    except Exception:
        pass
    return guncel, hata, ornek[:5], loglar

def trendruum_durum(token, barkodlar, durum, uret=False):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    ok, hata, loglar = 0, 0, []
    barkodlar = [b for b in (sabit_barkod(x, uret=True) for x in barkodlar) if b]
    for i in range(0, len(barkodlar), 500):
        grup = barkodlar[i:i + 500]
        no = i // 500 + 1
        try:
            r = http("POST", f"{TR_BASE}/products/status-update",
                     json={"products": [{"barcode": b, "status": durum} for b in grup]},
                     headers=headers, timeout=120)
        except Exception as e:
            hata += len(grup)
            loglar.append(f"⚠️ Paket {no}: {e}")
            continue
        if r.status_code == 200:
            ok += len(grup)
            loglar.append(f"✅ Paket {no}: {len(grup)} ürün güncellendi")
        else:
            hata += len(grup)
            loglar.append(f"❌ Paket {no}: HTTP {r.status_code} {r.text[:200]}")
    return ok, hata, loglar

def trendruum_siparisler(token, durum="new", limit=50):
    params = {"page": 1, "limit": limit}
    if durum and durum != "all":
        params["status"] = durum
    r = http("GET", f"{TR_BASE}/orders", params=params, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    r.raise_for_status()
    return r.json()

def tr_kucuk(metin_):
    return str(metin_).replace("İ", "i").replace("I", "ı").lower().strip()

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
            adaylar = [k.get("id"), k.get("_id"), k.get("category_id"), k.get("object_id")]
            kid = next((x for x in adaylar if objectid_mi(x)), k.get("id") or k.get("_id"))
            def _ad(x):
                for an in ("name", "title", "label", "category_name", "ad"):
                    v = x.get(an)
                    if isinstance(v, dict):
                        v = v.get("tr") or next((y for y in v.values() if y), "")
                    if v:
                        return str(v)
                return ""
            ad_ = _ad(k)
            yol_ = k.get("full_path") or k.get("path") or k.get("breadcrumb") or ad_
            if isinstance(yol_, list):
                yol_ = " > ".join(str(y) for y in yol_)
            duz.append({"id": kid, "ad": ad_, "yol": str(yol_ or ad_),
                        "parent": k.get("parent_id") or k.get("parentId"), "alt": bool(alt),
                        "ham": json.dumps({a_: v_ for a_, v_ in k.items() if not isinstance(v_, (list, dict))},
                                          ensure_ascii=False)})
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

# --- HEPSİBURADA (HB) ENTEGRASYON MODÜLÜ ---
HB_BASE = "https://mp-api.hepsiburada.com"

def hb_header(user, password):
    tok = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {
        "Authorization": f"Basic {tok}",
        "Content-Type": "application/json",
        "User-Agent": f"{user} - SelfIntegration"
    }

def hepsiburada_stok_fiyat(merchant_id, user, password, df):
    items = []
    for _, r in df.iterrows():
        if r["satis_fiyati"] > 0:
            items.append({
                "merchantSku": str(r["barkod"]),
                "price": round(float(r["satis_fiyati"]), 2),
                "stock": int(max(r["stok"], 0)),
                "maximumOrderQuantity": 0
            })
    ok, log, ok_b, hata_b = 0, [], [], []
    for i in range(0, len(items), 500):
        grup = items[i:i + 500]
        no = i // 500 + 1
        try:
            r = http("POST", f"{HB_BASE}/listings/merchantid/{merchant_id}/inventory-price-updates",
                     json={"listings": grup}, headers=hb_header(user, password), timeout=120)
            try:
                j = r.json() if r.text else {}
            except Exception:
                j = {}
        except Exception as e:
            hata_b += [x["merchantSku"] for x in grup]
            log.append(f"⚠️ HB Paket {no}: {e}")
            continue
        if r.status_code in (200, 201, 202):
            ok += len(grup)
            ok_b += [x["merchantSku"] for x in grup]
            log.append(f"✅ HB Paket {no}: {len(grup)} ürün güncellendi")
        else:
            hata_b += [x["merchantSku"] for x in grup]
            log.append(f"❌ HB Paket {no}: HTTP {r.status_code} {r.text[:200]}")
    try:
        pazar_isaretle("hb", ok_b, hata_b)
    except Exception:
        pass
    return ok, log

def hepsiburada_urun_listesi(df, ayarlar):
    liste, atlanan = [], 0
    for _, r in df.iterrows():
        gorsel = str(r["gorsel"]).strip()
        kod = str(r["barkod"]).strip()
        if not gorsel.startswith("https") or r["satis_fiyati"] <= 0 or not kod:
            atlanan += 1
            continue
        ad = str(r["urun_adi"]).strip()
        liste.append({
            "merchantSku": kod,
            "barcode": kod,
            "productName": ad[:250],
            "price": round(float(r["satis_fiyati"]), 2),
            "stock": int(max(r["stok"], 0)),
            "images": [{"url": gorsel}],
            "description": ad
        })
    return liste, atlanan

def hepsiburada_gonder(ayarlar, liste, ilerleme=None, paket=100):
    merchant_id = kimlik(ayarlar, "hb_merchant_id")
    user = kimlik(ayarlar, "hb_user")
    password = kimlik(ayarlar, "hb_pass")
    toplam = max(1, (len(liste) + paket - 1) // paket)
    loglar, basarili = [], 0
    for i in range(0, len(liste), paket):
        no = i // paket + 1
        grup = liste[i:i + paket]
        try:
            r = http("POST", f"{HB_BASE}/listings/merchantid/{merchant_id}/products",
                     json={"listings": grup}, headers=hb_header(user, password), timeout=120)
        except Exception as e:
            loglar.append(f"⚠️ HB Paket {no}: {e}")
            continue
        if r.status_code in (200, 201, 202):
            basarili += 1
            loglar.append(f"✅ HB Paket {no}: {len(grup)} ürün gönderildi")
        else:
            loglar.append(f"❌ HB Paket {no}: HTTP {r.status_code} {r.text[:500]}")
        if ilerleme:
            ilerleme(min(no / toplam, 1.0), loglar)
    return basarili, toplam, loglar

TY_BASE = "https://apigw.trendyol.com/integration"

def trendyol_header(seller, key, secret):
    tok = base64.b64encode(f"{key}:{secret}".encode()).decode()
    return {"Authorization": f"Basic {tok}", "User-Agent": f"{seller} - SelfIntegration",
            "Content-Type": "application/json"}

def trendyol_siparisler(seller, key, secret, durum="Created", boyut=50):
    r = http("GET", f"{TY_BASE}/order/sellers/{seller}/orders",
             params={"status": durum, "size": boyut, "orderByField": "PackageLastModifiedDate",
                     "orderByDirection": "DESC"},
             headers=trendyol_header(seller, key, secret), timeout=30)
    r.raise_for_status()
    return r.json().get("content", [])

def trendyol_stok_fiyat(seller, key, secret, df):
    items = [{"barcode": str(r["barkod"]), "quantity": int(min(max(r["stok"], 0), 20000)),
              "salePrice": float(r["satis_fiyati"]), "listPrice": float(r["satis_fiyati"])}
             for _, r in df.iterrows() if r["satis_fiyati"] > 0]
    ok, log, ok_b, hata_b = 0, [], [], []
    for i in range(0, len(items), 1000):
        grup = items[i:i + 1000]
        no = i // 1000 + 1
        try:
            r = http("POST", f"{TY_BASE}/inventory/sellers/{seller}/products/price-and-inventory",
                     json={"items": grup}, headers=trendyol_header(seller, key, secret), timeout=60)
        except Exception as e:
            hata_b += [x["barcode"] for x in grup]
            log.append(f"⚠️ Paket {no}: {e}")
            continue
        if r.status_code == 200:
            ok += len(grup)
            ok_b += [x["barcode"] for x in grup]
            log.append(f"✅ Paket {no}: {len(grup)} kalem kuyruğa alındı")
        else:
            hata_b += [x["barcode"] for x in grup]
            log.append(f"❌ Paket {no}: HTTP {r.status_code} {r.text[:200]}")
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
                           "quantity": int(max(r["stok"], 0)), "currencyType": "TL"})
    ok, log, ok_b, hata_b = 0, [], [], []
    for i in range(0, len(skular), 1000):
        grup = skular[i:i + 1000]
        no = i // 1000 + 1
        try:
            r = http("POST", f"{N11_BASE}/ms/product/tasks/price-stock-update",
                     json={"payload": {"integrator": "SahEntegre", "skus": grup}},
                     headers=n11_header(key, secret), timeout=120)
            try:
                j = r.json() if r.text else {}
            except Exception:
                j = {}
        except Exception as e:
            hata_b += [x["stockCode"] for x in grup]
            log.append(f"⚠️ Paket {no}: {e}")
            continue
        if r.status_code == 200 and str(j.get("status", "")).upper() != "REJECT":
            ok += len(grup)
            ok_b += [x["stockCode"] for x in grup]
            log.append(f"✅ Paket {no}: görev kuyruğa alındı")
        else:
            hata_b += [x["stockCode"] for x in grup]
            log.append(f"❌ Paket {no}: HTTP {r.status_code} {r.text[:200]}")
    try:
        pazar_isaretle("n11", ok_b, hata_b)
    except Exception:
        pass
    return ok, log

def n11_siparisler(key, secret, durum, sayfa_siniri=3):
    sonuc = []
    for sayfa_ in range(sayfa_siniri):
        r = http("GET", f"{N11_BASE}/rest/delivery/v1/shipmentPackages",
                 params={"status": durum, "page": sayfa_, "size": 100, "orderByDirection": "DESC"},
                 headers=n11_header(key, secret), timeout=60)
        r.raise_for_status()
        icerik = r.json().get("content") or []
        sonuc += icerik
        if len(icerik) < 100:
            break
    return sonuc

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

def idefix_kategoriler(ayarlar):
    r = http("GET", f"{ID_BASE}/pim/product-category", headers=idefix_header(ayarlar), timeout=120)
    r.raise_for_status()
    veri = r.json()
    if isinstance(veri, dict):
        veri = next((v for v in veri.values() if isinstance(v, list)), [])
    duz = []

    def gez(liste, yol):
        for k in liste or []:
            ad = str(k.get("name", ""))
            y = f"{yol} > {ad}" if yol else ad
            subs = k.get("subs") or []
            duz.append({"id": k.get("id"), "yol": y, "yaprak": not subs})
            gez(subs, y)

    gez(veri, "")
    return duz

def idefix_ozellikler(ayarlar, kategori_id):
    r = http("GET", f"{ID_BASE}/pim/category-attribute/{kategori_id}", headers=idefix_header(ayarlar), timeout=60)
    r.raise_for_status()
    return r.json()

def idefix_marka_ara(ayarlar, ad):
    r = http("GET", f"{ID_BASE}/pim/brand/search-by-name", params={"title": ad},
             headers=idefix_header(ayarlar), timeout=30)
    r.raise_for_status()
    j = r.json()
    if isinstance(j, dict):
        j = j.get("data", [j]) if "id" not in j else [j]
    return [m for m in (j or []) if isinstance(m, dict) and m.get("id")]

def idefix_stok_fiyat(ayarlar, df):
    h, v = idefix_header(ayarlar), idefix_vendor(ayarlar)
    items = []
    for _, r in df.iterrows():
        bk = idefix_barkod(r["barkod"], ayarlar)
        if bk and r["satis_fiyati"] > 0:
            items.append({"barcode": bk, "price": round(float(r["satis_fiyati"]), 2), "comparePrice": 0,
                          "inventoryQuantity": int(max(r["stok"], 0))})
    ok, log, ok_b, hata_b = 0, [], [], []
    if len(df) and not items:
        log.append("ℹ️ Geçerli barkodu olan ürün yok.")
    for i in range(0, len(items), 500):
        grup = items[i:i + 500]
        no = i // 500 + 1
        try:
            r = http("POST", f"{ID_BASE}/pim/catalog/{v}/inventory-upload", json={"items": grup},
                     headers=h, timeout=120)
        except Exception as e:
            hata_b += [x["barcode"] for x in grup]
            log.append(f"⚠️ Paket {no}: {e}")
            continue
        if r.status_code in (200, 201, 202):
            ok += len(grup)
            ok_b += [x["barcode"] for x in grup]
            log.append(f"✅ Paket {no}: {len(grup)} kalem kuyruğa alındı")
        else:
            hata_b += [x["barcode"] for x in grup]
            log.append(f"❌ Paket {no}: HTTP {r.status_code} {r.text[:200]}")
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
            "barcode": bk, "title": ad[:250], "productMainId": kod,
            "brandId": int(brand), "categoryId": int(cat),
            "inventoryQuantity": int(max(r["stok"], 0)), "vendorStockCode": kod,
            "description": ad, "price": round(float(r["satis_fiyati"]), 2),
            "comparePrice": round(float(r["satis_fiyati"]), 2), "vatRate": kdv,
            "deliveryDuration": sure, "deliveryType": "regular",
            "images": [{"url": gorsel}], "attributes": atr,
        })
    return liste, atlanan

def idefix_gonder(ayarlar, liste, ilerleme=None, paket=100):
    h, v = idefix_header(ayarlar), idefix_vendor(ayarlar)
    toplam = max(1, (len(liste) + paket - 1) // paket)
    loglar, batchler, basarili = [], [], 0
    for i in range(0, len(liste), paket):
        no = i // paket + 1
        grup = liste[i:i + paket]
        try:
            r = http("POST", f"{ID_BASE}/pim/pool/{v}/create", json={"products": grup}, headers=h, timeout=120)
        except Exception as e:
            loglar.append(f"⚠️ Paket {no}: {e}")
            continue
        if r.status_code in (200, 201, 202):
            try:
                bid = r.json().get("batchRequestId")
            except Exception:
                bid = None
            if bid:
                batchler.append(bid)
            basarili += 1
            loglar.append(f"✅ Paket {no}: {len(grup)} ürün gönderildi (batch: {bid})")
        else:
            loglar.append(f"❌ Paket {no}: HTTP {r.status_code} {r.text[:500]}")
        if ilerleme:
            ilerleme(min(no / toplam, 1.0), loglar)
    return basarili, toplam, batchler, loglar

def idefix_batch_durum(ayarlar, batch_id):
    r = http("GET", f"{ID_BASE}/pim/pool/{idefix_vendor(ayarlar)}/batch-result/{batch_id}",
             headers=idefix_header(ayarlar), timeout=60)
    r.raise_for_status()
    return r.json()

PAZAR_AD = {"trendruum": "Trendruum", "trendyol": "Trendyol", "n11": "N11", "idefix": "İdefix", "hb": "HepsiBurada"}

def _pazara_gonder(ayarlar, pid, df, ilerleme=None):
    df = fiyat_artis_uygula(ayarlar, pid, df)
    if pid == "trendruum":
        token = trendruum_token(kimlik(ayarlar, "trendruum_key"), kimlik(ayarlar, "trendruum_secret"))
        uret, _ = tr_ayar(ayarlar)
        g, h, ornek, loglar = trendruum_guncelle(df, token, ilerleme, uret)
        return g, h, "\n".join(ornek + loglar[-5:])
    if pid == "trendyol":
        ok, log = trendyol_stok_fiyat(kimlik(ayarlar, "trendyol_seller_id"), kimlik(ayarlar, "trendyol_key"),
                                      kimlik(ayarlar, "trendyol_secret"), df)
        return ok, max(0, int((df["satis_fiyati"] > 0).sum()) - ok), "\n".join(log)
    if pid == "n11":
        ok, log = n11_stok_fiyat(kimlik(ayarlar, "n11_key"), kimlik(ayarlar, "n11_secret"), df)
        return ok, max(0, int((df["satis_fiyati"] > 0).sum()) - ok), "\n".join(log)
    if pid == "idefix":
        ok, log = idefix_stok_fiyat(ayarlar, df)
        return ok, max(0, int((df["satis_fiyati"] > 0).sum()) - ok), "\n".join(log)
    if pid == "hb":
        merchant_id = kimlik(ayarlar, "hb_merchant_id")
        user = kimlik(ayarlar, "hb_user")
        password = kimlik(ayarlar, "hb_pass")
        ok, log = hepsiburada_stok_fiyat(merchant_id, user, password, df)
        return ok, max(0, int((df["satis_fiyati"] > 0).sum()) - ok), "\n".join(log)
    raise RuntimeError(f"{pid} için API entegrasyonu henüz yazılmadı.")

def pazara_gonder(ayarlar, pid, df, ilerleme=None):
    ad_ = PAZAR_AD.get(pid, pid)
    try:
        g, h, msg = _pazara_gonder(ayarlar, pid, df, ilerleme)
    except Exception as e:
        log_yaz(ad_, "HATA", f"Gönderilemedi: {e}")
        raise
    log_yaz(ad_, "OK" if g > 0 else "HATA", f"{g} gönderildi, {h} hata. {msg}"[:500])
    return g, h, msg

def oto_guncelle(ayarlar, pid):
    if not pazar_bagli(ayarlar, pid):
        return
    pazara_gonder(ayarlar, pid, urunleri_oku())

OTO_ANAHTAR = (("Trendruum", "tr_oto_guncelle", "trendruum"),
               ("Trendyol", "ty_oto_guncelle", "trendyol"),
               ("N11", "n11_oto_guncelle", "n11"),
               ("İdefix", "idefix_oto_guncelle", "idefix"),
               ("HepsiBurada", "hb_oto_guncelle", "hb"))

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
                    except Exception as e:
                        log_yaz(ad_, "HATA", e)
        return sonuclar
    finally:
        SENKRON_KILIDI.release()

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

def baglanti_testi(ayarlar, pid):
    try:
        if pid == "trendruum":
            trendruum_token(kimlik(ayarlar, "trendruum_key"), kimlik(ayarlar, "trendruum_secret"))
            return True, "Giriş başarılı, anahtarlar doğru."
        if pid == "trendyol":
            s_, k_, x_ = (kimlik(ayarlar, "trendyol_seller_id"), kimlik(ayarlar, "trendyol_key"),
                          kimlik(ayarlar, "trendyol_secret"))
            r = http("GET", f"{TY_BASE}/order/sellers/{s_}/orders", params={"size": 1},
                     headers=trendyol_header(s_, k_, x_), timeout=30)
        elif pid == "n11":
            r = http("GET", f"{N11_BASE}/rest/delivery/v1/shipmentPackages",
                     params={"status": "Created", "page": 0, "size": 1},
                     headers=n11_header(kimlik(ayarlar, "n11_key"), kimlik(ayarlar, "n11_secret")), timeout=30)
        elif pid == "idefix":
            r = http("GET", f"{ID_BASE}/pim/product-category", headers=idefix_header(ayarlar), timeout=60)
        elif pid == "hb":
            mid = kimlik(ayarlar, "hb_merchant_id")
            usr = kimlik(ayarlar, "hb_user")
            pwd = kimlik(ayarlar, "hb_pass")
            r = http("GET", f"{HB_BASE}/listings/merchantid/{mid}/listings?page=0&size=1",
                     headers=hb_header(usr, pwd), timeout=30)
        else:
            return False, "Bu pazar yeri için API entegrasyonu yok."
        return r.status_code in (200, 201), f"HTTP {r.status_code}: {r.text[:300]}"
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

sifre = os.environ.get("APP_PASSWORD")
if not sifre:
    try:
        if "APP_PASSWORD" in st.secrets:
            sifre = str(st.secrets["APP_PASSWORD"])
    except Exception:
        pass

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
    if os.environ.get(ad.upper()) or ad.upper() in st.secrets:
        st.caption(f"🔒 {etiket_}: ortam/secrets üzerinden tanımlı")
        return kimlik(ayarlar, ad)
    v = st.text_input(etiket_, value=ayarlar["kimlik"].get(ad, ""), type="password" if parola else "default")
    kimlik_kaydet(ad, v.strip())
    return v.strip()

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
               "alanlar": [("Satıcı ID", "idefix_satici_id", False), ("API Key", "idefix_token", True),
                           ("API Secret", "idefix_secret", True)]},
    "trendruum": {"ad": "Trendruum", "renk": "#7c3aed", "ikon": "🛒", "pastel": "#ede9fe",
                  "alanlar": [("API Key (Client ID)", "trendruum_key", True), ("API Secret", "trendruum_secret", True),
                              ("Brand ID", "trendruum_brand", False),
                              ("Varsayılan Kategori ID", "trendruum_category", False)]},
}

CAP = {
    "trendruum": {"sync", "kritik", "barkod", "toplu", "durum"},
    "trendyol": {"sync", "kritik", "barkod"},
    "n11": {"sync", "kritik", "barkod", "toplu"},
    "idefix": {"sync", "kritik", "barkod", "toplu"},
    "hb": {"sync", "kritik", "barkod", "toplu"},
}
ANA_MENU = [
    ("Anasayfa", "🏠 Anasayfa", "#dbeafe"),
    ("Bildirim", "🔔 Bildirimler", "#fef3c7"),
    ("Urunler", "📦 Sistemdeki Ürünler", "#f8fafc"),
    ("Kritik", "🔄 Oto Kritik Stok", "#dbeafe"),
]
ALT = [("siparis", "Siparişler", "🧾"), ("islemler", "Tüm İşlemleri", "🔗"),
       ("ayar", "Genel Ayarları", "⚙️")]

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
[data-testid="stSidebar"]{background:#f4f7fb;}
[data-testid="stSidebar"] .stButton button{justify-content:flex-start;text-align:left;border-radius:10px;
  padding:10px 12px;border:1px solid rgba(0,0,0,.05);box-shadow:0 1px 3px rgba(0,0,0,.10);min-height:44px;}
h1,h2,h3{color:#1e3a8a;}
[data-testid="stMetric"]{background:#1e293b !important;border-radius:14px;padding:14px 16px;
  box-shadow:0 2px 8px rgba(0,0,0,.3);border-left:5px solid #3b82f6;}
[data-testid="stMetric"] label{color:#94a3b8 !important;}
[data-testid="stMetric"] [data-testid="stMetricValue"]{color:#f8fafc !important;}
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
st.sidebar.caption("Sürüm: v33 - Tam Orijinal ve Kusursuz")
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

def kritik_esik_ayari():
    return int(ayarlar.get("kritik_esik") or 0)

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

    st.markdown("**Senkron sonrası pazar yerlerine otomatik gönder**")
    for ad_, anahtar_, pid_ in OTO_ANAHTAR:
        v = st.toggle(f"{ad_}: stok/fiyatı otomatik gönder", value=bool(ayarlar.get(anahtar_)), key=f"oto_{pid_}")
        if v != bool(ayarlar.get(anahtar_)):
            ayarlar[anahtar_] = v
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
    _m = st.session_state.pop("yedek_mesaj", None)
    if _m:
        (st.success if _m[0] else st.warning)(_m[1])
    yedek = {k: v for k, v in ayarlar.items() if k != "kimlik"}
    st.download_button("⬇️ Ayar Yedeği (.json, gizlisiz)",
                       json.dumps(yedek, ensure_ascii=False, indent=2).encode("utf-8"),
                       "sahentegre_ayarlar.json", "application/json", use_container_width=True)

def gunluk_sayfasi():
    with closing(baglan()) as c:
        lg = pd.read_sql("SELECT zaman, tedarikci, durum, mesaj FROM senkron_log ORDER BY id DESC LIMIT 200", c)
    if lg.empty:
        st.info("Kayıt yok.")
    else:
        st.dataframe(lg, use_container_width=True, hide_index=True)

def hepsiburada_toplu_panel():
    miktar = st.selectbox("Gönderilecek ürün", ["İlk 100", "İlk 500", "Tümü"], key="hbp_miktar")
    tek_stok = st.checkbox("Sadece stokta olanları gönder", value=True, key="hbp_stok")
    if st.button("📤 Hepsiburada'ya Ürün Oluştur", type="primary", key="hbp_gonder"):
        df = urunleri_oku()
        if tek_stok:
            df = df[df["stok"] > 0]
        df = df.head({"İlk 100": 100, "İlk 500": 500}.get(miktar, len(df)))
        df = fiyat_artis_uygula(ayarlar, "hb", df)
        liste, atlanan = hepsiburada_urun_listesi(df, ayarlar)
        if atlanan:
            st.info(f"{atlanan} ürün atlandı (https görsel yok, fiyat 0 veya barkod eksik).")
        if not liste:
            st.warning("Gönderilecek geçerli ürün kalmadı.")
            return
        bar, kutu = st.progress(0), st.empty()
        ok, top, loglar = hepsiburada_gonder(
            ayarlar, liste, lambda p, l: (bar.progress(p), kutu.code("\n".join(l[-10:]))))
        (st.success if ok else st.error)(f"{ok}/{top} paket başarıyla gönderildi.")

def trendruum_toplu_panel():
    key, secret = kimlik(ayarlar, "trendruum_key"), kimlik(ayarlar, "trendruum_secret")
    brand, cat = kimlik(ayarlar, "trendruum_brand"), kimlik(ayarlar, "trendruum_category")
    miktar = st.selectbox("Gönderilecek ürün", ["Güncellemede bulunamayanlar", "Tek ürün (test)", "İlk 100", "İlk 500", "Tümü"], key="tp_miktar")
    tek_stok = st.checkbox("Sadece stokta olanları gönder", value=True, key="tp_stok")
    if st.button("📤 Trendruum'a Gönder", type="primary", key="tp_gonder"):
        eksik = [ad for ad, v in (("API Key", key), ("API Secret", secret),
                                  ("Brand ID", brand), ("Varsayılan Kategori ID", cat)) if not v]
        if eksik:
            st.error("Eksik alan: " + ", ".join(eksik) + ". Genel Ayarları sayfasından doldurun.")
            return
        df = urunleri_oku()
        if miktar == "Güncellemede bulunamayanlar":
            with closing(baglan()) as c:
                hatali = {r[0] for r in c.execute(
                    "SELECT barkod FROM pazar_durum WHERE pazar='trendruum' AND durum='hata'").fetchall()}
            df = df[df["barkod"].astype(str).isin(hatali)]
            if df.empty:
                st.info("Hatalı ürün kaydı yok.")
                return
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
            if atlanan:
                st.info(f"{atlanan} ürün atlandı.")
            if not liste:
                st.warning("Gönderilecek geçerli ürün kalmadı.")
                return
            bar, kutu = st.progress(0), st.empty()
            ok, top, loglar = trendruum_gonder(
                liste, token, lambda p, l: (bar.progress(min(p, 1.0)), kutu.code("\n".join(l[-15:]))))
            st.success(f"Tamamlandı: {ok}/{top} paket başarılı.")
        except Exception as e:
            st.error(f"Hata: {e}")

def tam_senkron(pid):
    with st.spinner("Tedarikçi XML'leri çekiliyor..."):
        for ad_, ok, msg in tumunu_senkronla(oto=False):
            (st.success if ok else st.error)(f"{ad_}: {msg}")
    if urunleri_oku().empty:
        st.warning("Hiç ürün çekilemedi.")
        return
    if pazar_bagli(ayarlar, pid):
        with st.spinner("Pazar yerine gönderiliyor..."):
            try:
                g, h, msg = pazara_gonder(ayarlar, pid, urunleri_oku())
                st.success(f"{g} ürün gönderildi, {h} hatalı.")
                st.code(msg)
            except Exception as e:
                st.error(f"Gönderilemedi: {e}")

def tum_barkodlar(pid):
    if urunleri_oku().empty:
        st.warning("Sistemde ürün yok.")
        return
    with st.spinner("Stok ve fiyatlar güncelleniyor..."):
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

    st.title(f"{p['ikon']} {ad} Tüm İşlemler")
    if not bagli:
        st.warning("Önce API bilgilerinin tam olduğundan emin olun.")

    k = f"islem_{pid}"
    st.markdown("**SENKRON**")
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

    st.markdown("**İŞLEMLER**")
    d1, _ = st.columns(2)
    if d1.button("📤 Toplu Ürün Gönder", key=f"b4_{pid}"):
        st.session_state[k] = "toplu"

    islem = st.session_state.get(k)
    if islem:
        with st.container(border=True):
            if islem == "toplu":
                if pid == "hb":
                    hepsiburada_toplu_panel()
                elif pid == "trendruum":
                    trendruum_toplu_panel()

    st.markdown("---")
    with closing(baglan()) as c:
        toplam = c.execute("SELECT COUNT(*) FROM urunler").fetchone()[0]
        stokta = c.execute("SELECT COUNT(*) FROM urunler WHERE stok > 0").fetchone()[0]
        ok_n = c.execute("SELECT COUNT(*) FROM pazar_durum WHERE pazar=? AND durum='ok'", (pid,)).fetchone()[0]
        hata_n = c.execute("SELECT COUNT(*) FROM pazar_durum WHERE pazar=? AND durum='hata'", (pid,)).fetchone()[0]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Toplam Ürün", f"{toplam:,}")
    m2.metric("Stokta", f"{stokta:,}")
    m3.metric("Gönderildi", f"{ok_n:,}")
    m4.metric("Hatalı", f"{hata_n:,}")

def pazar_ayar(pid):
    p = PAZAR[pid]
    st.title(f"⚙️ {p['ad']} Genel Ayarları")
    for etk, anahtar, parola in p["alanlar"]:
        gizli_input(etk, anahtar, parola)
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

def pazar_siparis(pid):
    p = PAZAR[pid]
    ad = p["ad"]
    st.markdown(f'<div style="background:{p["renk"]};color:#fff;border-radius:12px;padding:14px 16px;'
                f'font-size:20px;font-weight:800;">{p["ikon"]} {ad} Siparişleri</div>', unsafe_allow_html=True)
    st.info("Bu pazar yeri için sipariş modülü yakında aktifleşecek.")

if sayfa == "Anasayfa":
    st.title("👑 Mağaza ve Pazar Yeri Özeti")
    df = urunleri_oku()
    esik = kritik_esik_ayari() or 2
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Toplam Ürün", f"{len(df):,}")
    c2.metric("Stokta Olanlar", f"{(df['stok'] > 0).sum():,}" if not df.empty else "0")
    c3.metric(f"Kritik Stok (≤{esik})", f"{df['stok'].between(1, esik).sum():,}" if not df.empty else "0")
    c4.metric("Tedarikçi", len(ayarlar["tedarikciler"]))

    st.markdown("### 🛒 Pazar Yeri Durumları")
    pazar_listesi = list(PAZAR.items())
    for i in range(0, len(pazar_listesi), 2):
        cols = st.columns(2)
        for j in range(2):
            if i + j < len(pazar_listesi):
                pid_, p_ = pazar_listesi[i + j]
                with cols[j]:
                    durum_metin = "🟢 API Bağlı" if pazar_bagli(ayarlar, pid_) else "🔴 Bilgi Bekliyor"
                    st.markdown(f"""
                        <div style="background:{p_['pastel']};border-radius:14px;padding:14px;border-left:6px solid {p_['renk']};margin-bottom:10px;">
                            <h4 style="margin:0;color:#1e293b;font-size:16px;">{p_['ikon']} {p_['ad']}</h4>
                            <p style="margin:6px 0 0 0;font-weight:600;color:#475569;font-size:13px;">{durum_metin}</p>
                        </div>
                    """, unsafe_allow_html=True)
                    if st.button("Yönet / İşlemler", key=f"kutu_git_{pid_}", use_container_width=True):
                        git_pazar(pid_, "islemler")
                        st.rerun()

elif sayfa == "Bildirim":
    st.title("🔔 Bildirimler")
    with closing(baglan()) as c:
        satirlar = c.execute("SELECT zaman, tedarikci, durum, mesaj FROM senkron_log ORDER BY id DESC LIMIT 50").fetchall()
    if not satirlar:
        st.info("Bildirim yok.")
    for zaman, ted, durum, mesaj in satirlar:
        (st.success if durum == "OK" else st.error)(f"{zaman} · {ted}: {mesaj}")

elif sayfa == "Urunler":
    st.title("📦 Sistemdeki Ürünler")
    df = urunleri_oku()
    if df.empty:
        st.info("Henüz ürün yok.")
    else:
        st.markdown(f"""
            <div style="background:#1e293b;padding:10px 14px;border-radius:10px;border:1px solid #334155;margin-bottom:14px;color:#f8fafc;text-align:center;">
                <span>📊 Toplam Ürün: <b>{len(df):,}</b> | Stokta Olan: <b>{int((df['stok'] > 0).sum()):,}</b></span>
            </div>
        """, unsafe_allow_html=True)

        if st.button("🔄 Ürünleri Güncelle", use_container_width=True, type="primary"):
            with st.spinner("Güncelleniyor..."):
                sonuc = tumunu_senkronla()
            for ad_, ok_, msg_ in sonuc:
                (st.success if ok_ else st.error)(f"{ad_}: {msg_}")

        arama = st.text_input("🔍 Ürün Adı veya Barkod ile Ara", key="urun_arama")
        filt_df = df
        if arama.strip():
            q = arama.strip().lower()
            filt_df = df[df["urun_adi"].str.lower().str.contains(q, regex=False) |
                         df["barkod"].str.lower().str.contains(q, regex=False)]

        SAYFA_BOYU = 50
        toplam_sayfa = max(1, (len(filt_df) + SAYFA_BOYU - 1) // SAYFA_BOYU)
        sn = st.number_input(f"Sayfa (1-{toplam_sayfa})", 1, toplam_sayfa, 1, key="urun_sayfa")
        st.caption(f"{len(filt_df):,} ürün bulundu")
        for _, row in filt_df.iloc[(sn - 1) * SAYFA_BOYU: sn * SAYFA_BOYU].iterrows():
            with st.container(border=True):
                c_img, c_det = st.columns([1, 3])
                with c_img:
                    g_url = str(row["gorsel"]).strip()
                    if g_url.startswith("http"):
                        st.markdown(f'<div style="display:flex;justify-content:center;"><img src="{esc(g_url, quote=True)}" '
                                    'style="max-height:85px;border-radius:6px;object-fit:contain;"></div>',
                                    unsafe_allow_html=True)
                    else:
                        st.markdown("🖼️ *(Görsel yok)*")
                with c_det:
                    st.markdown(f"<div style='font-size:14px;font-weight:700;color:#1e3a8a;margin-bottom:2px;'>{esc(str(row['urun_adi']))}</div>", unsafe_allow_html=True)
                    st.markdown(f"<div style='font-size:12px;color:#475569;'>Barkod: <b>{esc(str(row['barkod']))}</b> | Tedarikçi: <b>{esc(str(row['tedarikci']))}</b></div>", unsafe_allow_html=True)
                    st.markdown(f"<div style='font-size:12px;color:#475569;'>Kategori: {esc(str(row['kategori']))} | Stok: <b>{int(row['stok'])}</b> | Fiyat: <b style='color:#047857;'>{row['satis_fiyati']:.2f} ₺</b></div>", unsafe_allow_html=True)

elif sayfa == "Kritik":
    st.title("🔄 Oto Kritik Stok")
    esik = st.number_input("Kritik stok eşiği", 0, 50, kritik_esik_ayari(), key="kr_esik")
    if int(esik) != kritik_esik_ayari():
        ayarlar["kritik_esik"] = int(esik)
        ayar_yaz(ayarlar)
        st.success("Eşik kaydedildi.")

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
        {"siparis": pazar_siparis, "islemler": pazar_islemler, "ayar": pazar_ayar}.get(alt_, pazar_islemler)(pid_)
    else:
        git("Anasayfa")
        st.rerun()
else:
    git("Anasayfa")
    st.rerun()
