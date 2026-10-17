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
    "n11_key", "n11_secret", "n11_category", "cicek_key", "ptt_user", "ptt_pass",
    "pazarama_key", "pazarama_secret", "anthropic_api_key",
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
    "idefix_oto_guncelle": False,
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
    """429 / 5xx durumunda bekleyip tekrar dener. Son yanıtı döndürür."""
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
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):  # 1.234 / 12.345.678 → binlik ayracı
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
    """Gerçek (8-14 haneli sayısal) barkodu aynen döndürür.
    Barkod geçersizse: uret=True ise geçici barkod üretir, değilse None (ürün atlanır)."""
    g = gecerli_barkod(kod)
    if g:
        return g
    if not uret:
        return None
    temiz = "".join(ch for ch in str(kod) if ch.isdigit())  # eski sürümle birebir aynı eşleme
    if len(temiz) >= 8:
        return temiz
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
            sb = sabit_barkod(r["barkod"], uret)
            if not sb:
                atlanan += 1
                continue
            orijin[sb] = str(r["barkod"])
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
    barkodlar = [b for b in (sabit_barkod(x, uret) for x in barkodlar) if b]
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
    ok, log
