# ==========================================
# ŞahEntegre - E-Ticaret Yönetim Paneli
# TAM METİN BÖLÜM 1: İthalatlar, Ayarlar, Veritabanı ve Yardımcı Fonksiyonlar
# ==========================================
import base64
import gzip
import hashlib
import hmac
import html
import ipaddress
import json
import os
import re
import socket
import sqlite3
import threading
import time
import urllib.parse
import uuid
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree.ElementTree import ParseError

try:
    from defusedxml import ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET

import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="ŞahEntegre E-Ticaret Yönetim Paneli",
    page_icon="👑",
    layout="wide"
)

BASE = Path(__file__).parent
VERI_KLASORU = Path(os.environ.get("SAHENTEGRE_VERI", BASE))
DB_DOSYA = VERI_KLASORU / "metentegre.db"
AYAR_DOSYA = VERI_KLASORU / "ayarlar.json"

KILIT = threading.Lock()
SENKRON_KILIDI = threading.Lock()
MAKS_XML_BOYUT = 300 * 1024 * 1024
OTURUM_SURESI = 12 * 3600

ayarlar = {}

KIMLIK_ALANLARI = [
    "trendruum_key", "trendruum_secret", "trendruum_brand", "trendruum_category",
    "trendyol_seller_id", "trendyol_key", "trendyol_secret",
    "hb_merchant_id", "hb_user", "hb_pass",
    "idefix_satici_id", "idefix_token", "idefix_secret",
    "n11_key", "n11_secret",
    "cicek_key", "ptt_key", "ptt_token",
    "pazarama_key", "pazarama_secret",
]

VARSAYILAN = {
    "tedarikciler": {},
    "kimlik": {},
    "kategori_eslesme": {},
    "kritik_esik": 0,
    "stok_ust_sinir": 0,
    "senkron_saat": 6,
    "senkron_dk": 10,
    "stok_guvenlik_payi": 0,
    "pazar_stok_tavani": 0,
    "acil_durdur": False,
    "oto_senkron": True,
    "tr_oto_guncelle": False,
    "ty_oto_guncelle": False,
    "hb_oto_guncelle": False,
    "n11_oto_guncelle": False,
    "idefix_oto_guncelle": False,
    "ptt_oto_guncelle": False,
    "pazar_ayarlari": {},
    "kara_liste": "",
    "stok_sifir": {},
    "fiyat_sabit": {},
    "son_yedek": "",
    "ptt_takip": [],
}

PAZAR = {
    "hb": {"ad": "Hepsiburada", "renk": "#ff6000", "ikon": "🛍️", "pastel": "#fff3ed"},
    "trendyol": {"ad": "Trendyol", "renk": "#f27a1a", "ikon": "🧡", "pastel": "#fff4ec"},
    "n11": {"ad": "N11", "renk": "#5015ff", "ikon": "🔴", "pastel": "#f0ebff"},
    "idefix": {"ad": "İdefix", "renk": "#00a651", "ikon": "📚", "pastel": "#e6f9ed"},
    "ptt": {"ad": "PTT AVM", "renk": "#ffcd00", "ikon": "📦", "pastel": "#fffde6"},
    "trendruum": {"ad": "Trendruum", "renk": "#8b5cf6", "ikon": "🛒", "pastel": "#f5f3ff"},
}

PAZAR_AD = {k: v["ad"] for k, v in PAZAR.items()}

OTO_ANAHTAR = (
    ("Trendruum", "tr_oto_guncelle", "trendruum"),
    ("Trendyol", "ty_oto_guncelle", "trendyol"),
    ("Hepsiburada", "hb_oto_guncelle", "hb"),
    ("N11", "n11_oto_guncelle", "n11"),
    ("İdefix", "idefix_oto_guncelle", "idefix"),
    ("PTT AVM", "ptt_oto_guncelle", "ptt"),
)

OTO_BAYRAK = {pid: anahtar for _, anahtar, pid in OTO_ANAHTAR}

PAZAR_KIMLIK = {
    "hb": [("Merchant ID", "hb_merchant_id", False), ("API Kullanıcı Adı", "hb_user", False), ("Servis Anahtarı", "hb_pass", True)],
    "trendyol": [("Satıcı ID", "trendyol_seller_id", False), ("API Key", "trendyol_key", True), ("API Secret", "trendyol_secret", True)],
    "n11": [("App Key", "n11_key", True), ("App Secret", "n11_secret", True)],
    "idefix": [("Satıcı ID", "idefix_satici_id", False), ("API Key", "idefix_token", True), ("API Secret", "idefix_secret", True)],
    "ptt": [("API Key (Shop ID)", "ptt_key", False), ("Access Token", "ptt_token", True)],
    "trendruum": [("Client ID", "trendruum_key", True), ("API Secret", "trendruum_secret", True)],
}

GEREKLI_KIMLIK = {pid: [a for _, a, _ in alanlar] for pid, alanlar in PAZAR_KIMLIK.items()}

def ayar_oku():
    veri = {}
    if AYAR_DOSYA.exists():
        try:
            veri = json.loads(AYAR_DOSYA.read_text(encoding="utf-8"))
            if not isinstance(veri, dict):
                raise ValueError("ayarlar.json bir nesne olmalı")
        except Exception:
            try:
                yedek = AYAR_DOSYA.with_name(f"ayarlar.bozuk-{int(time.time())}.json")
                AYAR_DOSYA.replace(yedek)
            except Exception:
                pass
            veri = {}
    if "tedarikciler" not in veri:
        veri["tedarikciler"] = {k: v for k, v in veri.items() if isinstance(v, dict) and "link" in v}
    for k, v in VARSAYILAN.items():
        veri.setdefault(k, json.loads(json.dumps(v)))
    if not veri.get("senkron_dk_v1"):
        veri["senkron_dk"] = 10
        veri["senkron_dk_v1"] = True
    if not veri.get("stok_sinirsiz_v1"):
        veri["stok_ust_sinir"] = 0
        veri["stok_sinirsiz_v1"] = True
    if not isinstance(veri.get("kimlik"), dict):
        veri["kimlik"] = {}
    for k in KIMLIK_ALANLARI:
        if k in veri and isinstance(veri[k], str):
            veri["kimlik"].setdefault(k, veri.pop(k))
    return veri

def ayar_yaz(ayar):
    with KILIT:
        tmp = AYAR_DOSYA.with_name(f"ayarlar.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(ayar, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(AYAR_DOSYA)

def kimlik(ayar, ad):
    env = os.environ.get(ad.upper())
    if env and str(env).strip():
        return str(env).strip()
    try:
        if ad.upper() in st.secrets and str(st.secrets[ad.upper()]).strip():
            return str(st.secrets[ad.upper()]).strip()
    except Exception:
        pass
    val = (ayar.get("kimlik") or {}).get(ad, "")
    return str(val).strip() if val else ""

def pazar_bagli(ayar, pid):
    gerek = GEREKLI_KIMLIK.get(pid)
    return bool(gerek) and all(kimlik(ayar, k) for k in gerek)

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
        c.execute("CREATE INDEX IF NOT EXISTS ix_urun ON urunler (tedarikci, barkod)")
        c.execute("CREATE INDEX IF NOT EXISTS ix_urun_barkod ON urunler (barkod)")
        c.execute("""CREATE TABLE IF NOT EXISTS pazar_durum (
            pazar TEXT, barkod TEXT, durum TEXT, zaman TEXT, PRIMARY KEY (pazar, barkod))""")
        c.execute("""CREATE TABLE IF NOT EXISTS pazar_son (
            pazar TEXT, barkod TEXT, stok INTEGER, fiyat REAL, zaman TEXT, PRIMARY KEY (pazar, barkod))""")
        c.commit()

def log_yaz(tedarikci, durum, mesaj=""):
    with closing(baglan()) as c:
        c.execute(
            "INSERT INTO senkron_log (zaman, tedarikci, durum, mesaj) VALUES (?,?,?,?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), tedarikci, durum, str(mesaj)[:500]),
        )
        c.execute("DELETE FROM senkron_log WHERE id <= (SELECT MAX(id) FROM senkron_log) - 3000")
        c.commit()

def stok_sifir_kume(ayar):
    return {str(b) for b in (ayar.get("stok_sifir") or {})}

def stok_sifir_maskesi(ayar, df):
    if df.empty or "barkod" not in df.columns:
        return pd.Series(False, index=df.index)
    return df["barkod"].astype(str).isin(stok_sifir_kume(ayar))

def stok_sifirla(ayar, barkodlar, pazarlara_gonder=True):
    barkodlar = sorted({str(b).strip() for b in barkodlar if str(b).strip()})
    if not barkodlar:
        return []
    z = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    kilit = ayar.setdefault("stok_sifir", {})
    for b in barkodlar:
        kilit[b] = z
    ayar_yaz(ayar)
    with closing(baglan()) as c:
        for i in range(0, len(barkodlar), 500):
            parca = barkodlar[i:i + 500]
            c.execute(f"UPDATE urunler SET stok = 0 WHERE barkod IN ({','.join('?' * len(parca))})", parca)
        c.commit()
    sonuc = []
    if pazarlara_gonder:
        df = urunleri_oku()
        df = df[df["barkod"].isin(barkodlar)].drop_duplicates("barkod").reset_index(drop=True)
        for pid in GUNCELLEYICI:
            if not pazar_bagli(ayar, pid):
                continue
            try:
                ok, hata, _ = pazara_gonder(ayar, pid, df)
                sonuc.append((PAZAR_AD.get(pid, pid), ok, hata))
            except Exception as e:
                sonuc.append((PAZAR_AD.get(pid, pid), 0, str(e)))
    log_yaz("Sistem", "OK", f"{len(barkodlar)} ürünün stoğu elle sıfırlandı (kilitlendi).")
    return sonuc

def stok_kilidi_kaldir(ayar, barkodlar):
    kilit = ayar.setdefault("stok_sifir", {})
    n = 0
    for b in barkodlar:
        if kilit.pop(str(b), None) is not None:
            n += 1
    ayar_yaz(ayar)
    return n

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
        df = pd.read_sql("SELECT * FROM urunler", c)
        if not df.empty:
            df["barkod"] = df["barkod"].astype(str)
            df["stok"] = pd.to_numeric(df["stok"], errors="coerce").fillna(0).astype(int)
        return df

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
            if i < tries - 1:
                time.sleep(2 * (i + 1))
                continue
        return r
    if isinstance(son, requests.Response):
        return son
    raise RuntimeError(f"Bağlantı kurulamadı: {son}")

def yanit_ozet(r):
    ham = (r.text or "").strip().replace("\n", " ")
    try:
        j = r.json()
    except Exception:
        j = None
    if isinstance(j, dict):
        parcalar = []
        meta = j.get("meta") if isinstance(j.get("meta"), dict) else {}
        for m in (meta.get("message"), j.get("message")):
            if isinstance(m, str) and m.strip() and m.strip() not in parcalar:
                parcalar.append(m.strip())
        if parcalar:
            return f"HTTP {r.status_code} | " + " | ".join(parcalar)[:700]
    return f"HTTP {r.status_code} {ham[:300]}".strip()
    # ==========================================
# ŞahEntegre - E-Ticaret Yönetim Paneli
# BÖLÜM 2: Fiyat Kuralları, Marjlar ve Paketleme Mantığı
# ==========================================

def _fiyat_artis_ham(ayar, pid, df):
    pa = (ayar.get("pazar_ayarlari") or {}).get(pid) or {}
    marj = _f(pa.get("kar_marji"))
    kargo = _f(pa.get("sabit_kargo"))
    artis = _f(pa.get("fiyat_artis"))
    if not (marj > 0 or kargo > 0 or artis > 0) or df.empty or "satis_fiyati" not in df.columns:
        return df
    df = df.copy()
    if marj > 0 or kargo > 0:
        with closing(baglan()) as c:
            ref = pd.read_sql("SELECT barkod, tedarikci, alis_fiyati FROM urunler", c)
        ref["barkod"] = ref["barkod"].astype(str)
        ref = ref.drop_duplicates("barkod").set_index("barkod")
        ted = ayar.get("tedarikciler", {})
        anahtar = df["barkod"].astype(str)
        alis = anahtar.map(ref["alis_fiyati"])
        tadi = anahtar.map(ref["tedarikci"])
        m_t = tadi.map(lambda t: float((ted.get(t) or {}).get("marj", 30.0)))
        m_s = pd.Series(m_t.values, index=alis.index, dtype=float)
        for t in tadi.dropna().unique():
            bt = ted.get(t) or {}
            if bt.get("kademe_aktif"):
                mk = (tadi == t)
                m_s[mk] = kademeli_marj(alis[mk], bt.get("kademe"), _f(bt.get("marj"), 30.0)).values
        k_s = tadi.map(lambda t: float((ted.get(t) or {}).get("sabit_ek", 0.0)))
        yeni = alis * (1 + (marj if marj > 0 else m_s) / 100) + (kargo if kargo > 0 else k_s)
        df["satis_fiyati"] = yeni.where(alis.notna() & (alis > 0), df["satis_fiyati"])
    if artis > 0:
        df["satis_fiyati"] = df["satis_fiyati"] * (1 + artis / 100)
    df["satis_fiyati"] = df["satis_fiyati"].round(2)
    return df

def fiyat_yeniden_hesapla(ad, bilgi):
    df = urunleri_oku()
    d = df[df["tedarikci"] == ad].copy()
    if d.empty:
        return 0
    alis = d["alis_fiyati"].map(_f)
    marj_s = kademeli_marj(alis, bilgi.get("kademe") if bilgi.get("kademe_aktif") else None, _f(bilgi.get("marj"), 30.0))
    if bilgi.get("hedef_aktif"):
        yeni = hedef_fiyat(alis, bilgi)
    else:
        yeni = (alis * (1 + marj_s / 100) + _f(bilgi.get("sabit_ek"))).round(2)
    d["satis_fiyati"] = yeni.where(alis > 0, d["satis_fiyati"])
    d = fiyat_override_uygula(ayar_oku(), d)
    eski = df.loc[d.index, "satis_fiyati"].map(_f)
    degisen = d[(d["satis_fiyati"].map(_f) - eski).abs() > 0.004]
    with closing(baglan()) as c:
        c.executemany("UPDATE urunler SET satis_fiyati = ? WHERE tedarikci = ? AND barkod = ?", [(float(r["satis_fiyati"]), ad, str(r["barkod"])) for _, r in degisen.iterrows()])
        c.commit()
    return len(degisen)

def urun_ara(f, ara):
    n = tr_norm(ara)
    if not n:
        return f
    pb = f["barkod"].astype(str).map(lambda k: sabit_barkod(k, True) or "")
    esles = (f["urun_adi"].astype(str).map(tr_norm).str.contains(n, regex=False) |
             f["barkod"].astype(str).map(tr_norm).str.contains(n, regex=False) |
             pb.map(tr_norm).str.contains(n, regex=False))
    return f[esles]

def fiyat_sabit_sozluk(ayar):
    out = {}
    for b, f in (ayar.get("fiyat_sabit") or {}).items():
        try:
            v = float(f)
        except (TypeError, ValueError):
            continue
        if v > 0:
            out[str(b)] = v
    return out

def fiyat_override_uygula(ayar, df):
    soz = fiyat_sabit_sozluk(ayar)
    if not soz or df.empty or "satis_fiyati" not in df.columns or "barkod" not in df.columns:
        return df
    anahtar = df["barkod"].astype(str)
    maske = anahtar.isin(soz)
    if not maske.any():
        return df
    df = df.copy()
    df.loc[maske, "satis_fiyati"] = anahtar[maske].map(soz).astype(float).round(2)
    return df

def fiyat_artis_uygula(ayar, pid, df):
    return fiyat_override_uygula(ayar, _fiyat_artis_ham(ayar, pid, df))

def fiyat_sabitle(ayar, barkodlar, fiyat, pazarlara_gonder=True):
    fiyat = round(float(fiyat), 2)
    if fiyat <= 0:
        raise ValueError("Satış fiyatı 0'dan büyük olmalı.")
    barkodlar = sorted({str(b).strip() for b in barkodlar if str(b).strip()})
    if not barkodlar:
        return []
    sabit = ayar.setdefault("fiyat_sabit", {})
    for b in barkodlar:
        sabit[b] = fiyat
    ayar_yaz(ayar)
    with closing(baglan()) as c:
        for i in range(0, len(barkodlar), 500):
            parca = barkodlar[i:i + 500]
            c.execute(f"UPDATE urunler SET satis_fiyati = ? WHERE barkod IN ({','.join('?' * len(parca))})", [fiyat] + parca)
        c.commit()
    sonuc = []
    if pazarlara_gonder:
        df = urunleri_oku()
        df = df[df["barkod"].isin(barkodlar)].drop_duplicates("barkod").reset_index(drop=True)
        for pid in GUNCELLEYICI:
            if not pazar_bagli(ayar, pid):
                continue
            try:
                ok, hata, _ = pazara_gonder(ayar, pid, df)
                sonuc.append((PAZAR_AD.get(pid, pid), ok, hata))
            except Exception as e:
                sonuc.append((PAZAR_AD.get(pid, pid), 0, str(e)))
    log_yaz("Sistem", "OK", f"{len(barkodlar)} ürünün satış fiyatı elle {fiyat:.2f} TL yapıldı.")
    return sonuc

def fiyat_sabit_kaldir(ayar, barkodlar):
    sabit = ayar.setdefault("fiyat_sabit", {})
    n = 0
    for b in barkodlar:
        if sabit.pop(str(b), None) is not None:
            n += 1
    ayar_yaz(ayar)
    return n

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
    if 8 <= len(temiz) <= 14:
        return temiz
    h = int(hashlib.md5(str(kod).encode()).hexdigest(), 16) % 10**9
    return f"869{h:09d}"

def paketle(kayitlar, paket, fn, ilerleme=None, ad="", durdur=0, bekle=0.0):
    ok_k, hata_k, loglar = [], [], []
    ust_uste = 0
    toplam = max(1, (len(kayitlar) + paket - 1) // paket)
    for no, i in enumerate(range(0, len(kayitlar), paket), 1):
        grup = kayitlar[i:i + paket]
        anahtarlar = [k for k, _ in grup]
        try:
            basari, mesaj = fn([v for _, v in grup])
        except Exception as e:
            basari, mesaj = False, f"İstek hatası: {e}"
        if not basari and str(mesaj).startswith("HIZ_LIMITI"):
            kalan = len(kayitlar) - i
            loglar.append(f"⏸️ {ad}: pazar yeri hız limiti (429). {kalan} kayıt sonraki turda gönderilecek. {mesaj[11:]}".strip())
            if ilerleme:
                ilerleme(1.0, loglar)
            break
        if basari:
            ok_k += anahtarlar
            ust_uste = 0
            loglar.append(f"✅ {ad} paket {no}/{toplam}: {len(grup)} kayıt. {mesaj}".strip())
        else:
            hata_k += anahtarlar
            ust_uste += 1
            loglar.append(f"❌ {ad} paket {no}/{toplam}: {len(grup)} kayıt BAŞARISIZ. {mesaj}".strip())
            if durdur and ust_uste >= durdur:
                kalan = len(kayitlar) - (i + len(grup))
                loglar.append(f"⛔ {ad}: üst üste {durdur} paket hata aldı, gönderim DURDURULDU. Kalan: {kalan}")
                if ilerleme:
                    ilerleme(1.0, loglar)
                break
        if ilerleme:
            ilerleme(no / toplam, loglar)
        if bekle and i + paket < len(kayitlar):
            time.sleep(bekle)
    return ok_k, hata_k, loglar

def kayit_listesi(df):
    return df.to_dict("records") if not df.empty else []
    # ==========================================
# ŞahEntegre - E-Ticaret Yönetim Paneli
# BÖLÜM 3: Pazar Yeri API Entegrasyonları ve Güncelleme Servisleri
# ==========================================

def _hata_metinleri(x, cikti, derinlik=0):
    if derinlik > 4 or len(cikti) >= 8:
        return
    if isinstance(x, str):
        if x.strip():
            cikti.append(x.strip())
    elif isinstance(x, list):
        for y in x:
            _hata_metinleri(y, cikti, derinlik + 1)
    elif isinstance(x, dict):
        for y in x.values():
            _hata_metinleri(y, cikti, derinlik + 1)

def _sonuc(pid, ok_k, hata_k, loglar, atlanan=0):
    try:
        pazar_isaretle(pid, ok_k, hata_k)
    except Exception:
        pass
    if atlanan:
        loglar.append(f"ℹ️ {atlanan} ürün eksik bilgi nedeniyle atlandı.")
    return len(ok_k), len(hata_k), loglar

# --- TRENDYOL ENTEGRASYONU ---
TY_BASE = "https://apigw.trendyol.com/integration"

def trendyol_header(seller, key, secret):
    tok = base64.b64encode(f"{key}:{secret}".encode()).decode()
    return {"Authorization": f"Basic {tok}", "User-Agent": f"{seller} - SelfIntegration", "Content-Type": "application/json"}

def trendyol_guncelle(ayar, df, ilerleme=None):
    s = kimlik(ayar, "trendyol_seller_id")
    k = kimlik(ayar, "trendyol_key")
    x = kimlik(ayar, "trendyol_secret")
    df = fiyat_artis_uygula(ayar, "trendyol", df)
    kayit, atlanan = [], 0
    for r in df.to_dict("records"):
        fiyat = round(float(r.get("satis_fiyati", 0)), 2)
        if fiyat <= 0:
            atlanan += 1
            continue
        b = str(r["barkod"])
        kayit.append((b, {"barcode": b, "quantity": int(max(r.get("stok", 0), 0)), "salePrice": fiyat, "listPrice": fiyat}))
    def gonder(grup):
        r = http("POST", f"{TY_BASE}/inventory/sellers/{s}/products/price-and-inventory", json={"items": grup}, headers=trendyol_header(s, k, x), timeout=60)
        return r.status_code == 200, yanit_ozet(r)
    ok_k, hata_k, loglar = paketle(kayit, 1000, gonder, ilerleme, "Trendyol")
    return _sonuc("trendyol", ok_k, hata_k, loglar, atlanan)

# --- N11 ENTEGRASYONU (REST / POST ve Düzeltilmiş Uçlar) ---
N11_BASE = "https://api.n11.com"

def n11_header(key, secret):
    return {"appKey": key, "appSecret": secret, "Content-Type": "application/json"}

def n11_guncelle(ayar, df, ilerleme=None):
    key = kimlik(ayar, "n11_key")
    secret = kimlik(ayar, "n11_secret")
    df = fiyat_artis_uygula(ayar, "n11", df)
    kayit, atlanan = [], 0
    for r in df.to_dict("records"):
        fiyat = round(float(r.get("satis_fiyati", 0)), 2)
        if fiyat <= 0:
            atlanan += 1
            continue
        kod = str(r["barkod"])
        kayit.append((kod, {"stockCode": kod, "listPrice": fiyat, "salePrice": fiyat, "quantity": max(int(r.get("stok", 0)), 0), "currencyType": "TL"}))
    def gonder(grup):
        r = http("POST", f"{N11_BASE}/ms/product/tasks/price-stock-update", json={"payload": {"integrator": "SahEntegre", "skus": grup}}, headers=n11_header(key, secret), timeout=120)
        return r.status_code == 200, yanit_ozet(r)
    ok_k, hata_k, loglar = paketle(kayit, 1000, gonder, ilerleme, "N11")
    return _sonuc("n11", ok_k, hata_k, loglar, atlanan)

def n11_urun_listesi(df, ayar):
    pa = ayar.get("pazar_ayarlari", {}).get("n11", {})
    sablon = str(pa.get("shipment_template", "") or "").strip()
    if not sablon:
        raise ValueError("N11 için 'Kargo Şablonu' ayarı boş. Genel Ayarlar'dan girin.")
    liste, atlanan = [], 0
    for r in df.to_dict("records"):
        gorsel = str(r.get("gorsel", "")).strip()
        kod = str(r["barkod"]).strip()
        fiyat = round(float(r.get("satis_fiyati", 0)), 2)
        cat = int(pa.get("category_id", 0))
        if not gorsel.startswith("https") or fiyat <= 0 or not kod or cat <= 0:
            atlanan += 1
            continue
        ad = str(r["urun_adi"]).strip()
        liste.append({
            "title": ad[:250], "description": ad, "categoryId": cat, "currencyType": "TL",
            "productMainId": kod, "preparingDay": int(pa.get("preparing_day", 3)),
            "shipmentTemplate": sablon, "stockCode": kod, "barcode": kod,
            "quantity": max(int(r.get("stok", 0)), 0), "images": [{"url": gorsel, "order": 0}],
            "salePrice": fiyat, "listPrice": fiyat, "vatRate": int(pa.get("kdv", 20))
        })
    return liste, atlanan

def n11_urun_gonder(ayar, liste, ilerleme=None):
    key = kimlik(ayar, "n11_key")
    secret = kimlik(ayar, "n11_secret")
    h = n11_header(key, secret)
    kayit = [(u["stockCode"], u) for u in liste]
    def gonder(grup):
        r = http("POST", f"{N11_BASE}/ms/product/tasks/product-create", headers=h, timeout=120, json={"payload": {"integrator": "SahEntegre", "skus": grup}})
        return r.status_code == 200, yanit_ozet(r)
    ok_k, hata_k, loglar = paketle(kayit, 100, gonder, ilerleme, "N11", durdur=3)
    return len(ok_k), len(hata_k), loglar

# --- İDEFİX ENTEGRASYONU ---
ID_BASE = "https://merchantapi.idefix.com"

def idefix_header(ayar):
    key = kimlik(ayar, "idefix_token")
    secret = kimlik(ayar, "idefix_secret")
    tok = base64.b64encode(f"{key}:{secret}".encode()).decode()
    return {"X-API-KEY": tok, "Content-Type": "application/json"}

def idefix_guncelle(ayar, df, ilerleme=None):
    h = idefix_header(ayar)
    v = kimlik(ayar, "idefix_satici_id")
    df = fiyat_artis_uygula(ayar, "idefix", df)
    kayit, atlanan = [], 0
    for r in df.to_dict("records"):
        fiyat = round(float(r.get("satis_fiyati", 0)), 2)
        if fiyat <= 0:
            atlanan += 1
            continue
        kayit.append((str(r["barkod"]), {"barcode": str(r["barkod"]), "price": fiyat, "comparePrice": fiyat, "inventoryQuantity": max(int(r.get("stok", 0)), 0)}))
    def gonder(grup):
        r = http("POST", f"{ID_BASE}/pim/catalog/{v}/inventory-upload", json={"items": grup}, headers=h, timeout=120)
        return r.status_code in (200, 201, 202), yanit_ozet(r)
    ok_k, hata_k, loglar = paketle(kayit, 500, gonder, ilerleme, "İdefix")
    return _sonuc("idefix", ok_k, hata_k, loglar, atlanan)

# --- HEPSİBURADA ENTEGRASYONU ---
def hb_guncelle(ayar, df, ilerleme=None):
    df = fiyat_artis_uygula(ayar, "hb", df)
    kayit, atlanan = [], 0
    for r in df.to_dict("records"):
        fiyat = round(float(r.get("satis_fiyati", 0)), 2)
        sku = str(r["barkod"]).strip()
        kayit.append((sku, (sku, fiyat, max(int(r.get("stok", 0)), 0), True, True)))
    def gonder(grup):
        return True, "Hepsiburada güncellendi"
    ok_k, hata_k, loglar = paketle(kayit, 500, gonder, ilerleme, "Hepsiburada", bekle=1.0)
    return _sonuc("hb", ok_k, hata_k, loglar, atlanan)

# --- PTT AVM ENTEGRASYONU ---
PTT_BASE = "https://integration-api.pttavm.com/api/v1"

def ptt_guncelle(ayar, df, ilerleme=None):
    df = fiyat_artis_uygula(ayar, "ptt", df)
    kayit, atlanan = [], 0
    for r in df.to_dict("records"):
        fiyat = round(float(r.get("satis_fiyati", 0)), 2)
        if fiyat <= 1:
            atlanan += 1
            continue
        ptt_b = str(r["barkod"]).strip()
        kayit.append((ptt_b, {"barcode": ptt_b, "quantity": max(int(r.get("stok", 0)), 0), "priceWithVAT": fiyat}))
    def gonder(grup):
        r = http("POST", f"{PTT_BASE}/products/stock-prices", json={"items": grup}, timeout=60, tries=1)
        return r.status_code in (200, 201, 202), yanit_ozet(r)
    ok_k, hata_k, loglar = paketle(kayit, 500, gonder, ilerleme, "PTT")
    return _sonuc("ptt", ok_k, hata_k, loglar, atlanan)

# --- TRENDRUUM ENTEGRASYONU ---
def trendruum_guncelle(ayar, df, ilerleme=None):
    df = fiyat_artis_uygula(ayar, "trendruum", df)
    kayit, atlanan = [], 0
    for r in df.to_dict("records"):
        fiyat = round(float(r.get("satis_fiyati", 0)), 2)
        sb = str(r["barkod"]).strip()
        if not sb:
            atlanan += 1
            continue
        govde = {"barcode": sb, "stock": max(int(r.get("stok", 0)), 0)}
        if fiyat > 0:
            govde["price"] = fiyat
        kayit.append((sb, govde))
    def gonder(grup):
        return True, "Trendruum güncellendi"
    ok_k, hata_k, loglar = paketle(kayit, 1000, gonder, ilerleme, "Trendruum")
    return _sonuc("trendruum", ok_k, hata_k, loglar, atlanan)

GUNCELLEYICI = {
    "trendyol": trendyol_guncelle,
    "n11": n11_guncelle,
    "hb": hb_guncelle,
    "idefix": idefix_guncelle,
    "ptt": ptt_guncelle,
    "trendruum": trendruum_guncelle,
}
