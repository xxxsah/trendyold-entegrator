"""ŞahEntegre - E-Ticaret Yönetim Paneli (düzeltilmiş sürüm)

Çalıştırma:  streamlit run app.py
Gizli bilgiler için öncelik sırası: ortam değişkeni > st.secrets > ayarlar.json
Önerilen: APP_PASSWORD ortam değişkenini mutlaka tanımlayın.
"""
import base64
import gzip
import hashlib
import hmac
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
from datetime import datetime
from pathlib import Path
from xml.etree.ElementTree import ParseError

try:  # Güvenli XML ayrıştırıcı (billion-laughs vb. saldırılara karşı)
    from defusedxml import ElementTree as ET
except ImportError:  # pragma: no cover
    import xml.etree.ElementTree as ET

import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="ŞahEntegre - E-Ticaret Yönetim Paneli", page_icon="👑", layout="wide"
)

BASE = Path(__file__).parent
VERI_KLASORU = Path(os.environ.get("SAHENTEGRE_VERI", BASE))
DB_DOSYA = VERI_KLASORU / "metentegre.db"
AYAR_DOSYA = VERI_KLASORU / "ayarlar.json"
KILIT = threading.Lock()
SENKRON_KILIDI = threading.Lock()
MAKS_XML_BOYUT = 300 * 1024 * 1024
OTURUM_SURESI = 12 * 3600

ayarlar = {}  # main() içinde her çalışmada diskten yüklenir

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
    "stok_ust_sinir": 50,
    "senkron_saat": 6,
    "oto_senkron": True,
    "tr_oto_guncelle": False,
    "ty_oto_guncelle": False,
    "hb_oto_guncelle": False,
    "n11_oto_guncelle": False,
    "idefix_oto_guncelle": False,
    "ptt_oto_guncelle": False,
    "pazar_ayarlari": {},
    "kara_liste": "",
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


# --------------------------------------------------------------------------
# Ayarlar
# --------------------------------------------------------------------------
def ayar_oku():
    veri = {}
    if AYAR_DOSYA.exists():
        try:
            veri = json.loads(AYAR_DOSYA.read_text(encoding="utf-8"))
            if not isinstance(veri, dict):
                raise ValueError("ayarlar.json bir nesne olmalı")
        except Exception:
            # Bozuk dosyayı SESSİZCE ezme: önce yedekle.
            try:
                yedek = AYAR_DOSYA.with_name(f"ayarlar.bozuk-{int(time.time())}.json")
                AYAR_DOSYA.replace(yedek)
            except Exception:
                pass
            veri = {}
    if "tedarikciler" not in veri:
        veri["tedarikciler"] = {
            k: v for k, v in veri.items() if isinstance(v, dict) and "link" in v
        }
    for k, v in VARSAYILAN.items():
        veri.setdefault(k, json.loads(json.dumps(v)))
    if not isinstance(veri.get("kimlik"), dict):
        veri["kimlik"] = {}
    for k in KIMLIK_ALANLARI:  # eski düz yapıdan göç
        if k in veri and isinstance(veri[k], str):
            veri["kimlik"].setdefault(k, veri.pop(k))
    return veri


def _yedek_anahtar(parola, tuz):
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    kdf = Scrypt(salt=tuz, length=32, n=2 ** 15, r=8, p=1)
    return base64.urlsafe_b64encode(kdf.derive(parola.encode("utf-8")))


def yedek_sifrele(veri, parola):
    """Ayarları (API anahtarları dahil) parolayla şifreler. Dönüş: JSON baytları."""
    from cryptography.fernet import Fernet
    tuz = os.urandom(16)
    jeton = Fernet(_yedek_anahtar(parola, tuz)).encrypt(json.dumps(veri, ensure_ascii=False).encode("utf-8"))
    zarf = {"sahentegre_yedek": 1, "tuz": base64.b64encode(tuz).decode(), "veri": jeton.decode()}
    return json.dumps(zarf).encode("utf-8")


def yedek_coz(ham, parola):
    from cryptography.fernet import Fernet, InvalidToken
    zarf = json.loads(ham.decode("utf-8"))
    try:
        tuz = base64.b64decode(zarf["tuz"])
        return json.loads(Fernet(_yedek_anahtar(parola, tuz)).decrypt(zarf["veri"].encode()).decode("utf-8"))
    except InvalidToken:
        raise ValueError("Yedek parolası hatalı ya da dosya bozulmuş.")


def tr_norm(t):
    """Türkçe-güvenli küçük harf (İ/I/ı sorunu: Python 'İ'.lower() noktalı birleşik karakter üretir)."""
    return str(t).replace("İ", "i").replace("I", "i").replace("ı", "i").lower()


def kara_liste_maskesi(ayar, df):
    """Kara listedeki kelimeleri içeren ürünler için True döner (ad / kategori / barkod)."""
    kelimeler = [tr_norm(k.strip()) for k in str(ayar.get("kara_liste", "") or "").splitlines() if k.strip()]
    if not kelimeler or df.empty:
        return pd.Series(False, index=df.index)
    metin = pd.Series("", index=df.index)
    for kol in ("urun_adi", "kategori", "barkod"):
        if kol in df.columns:
            metin = metin + " " + df[kol].astype(str).map(tr_norm)
    return metin.apply(lambda t: any(k in t for k in kelimeler))


def ayar_yaz(ayar):
    with KILIT:
        tmp = AYAR_DOSYA.with_name(f"ayarlar.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(ayar, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)  # API anahtarları sadece sahibi tarafından okunabilsin
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


def pa_al(ayar, pid):
    """Pazar yeri ayar sözlüğü (yoksa oluşturur)."""
    return ayar.setdefault("pazar_ayarlari", {}).setdefault(pid, {})


def pazar_bagli(ayar, pid):
    gerek = GEREKLI_KIMLIK.get(pid)
    return bool(gerek) and all(kimlik(ayar, k) for k in gerek)


# --------------------------------------------------------------------------
# Veritabanı
# --------------------------------------------------------------------------
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
        c.execute("CREATE INDEX IF NOT EXISTS ix_urun_barkod ON urunler(barkod)")
        c.execute("""CREATE TABLE IF NOT EXISTS pazar_durum (
            pazar TEXT, barkod TEXT, durum TEXT, zaman TEXT, PRIMARY KEY (pazar, barkod))""")
        c.commit()


def log_yaz(tedarikci, durum, mesaj=""):
    with closing(baglan()) as c:
        c.execute(
            "INSERT INTO senkron_log (zaman, tedarikci, durum, mesaj) VALUES (?,?,?,?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), tedarikci, durum, str(mesaj)[:500]),
        )
        c.execute("DELETE FROM senkron_log WHERE id <= (SELECT MAX(id) FROM senkron_log) - 3000")
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
        df = pd.read_sql("SELECT * FROM urunler", c)
    if not df.empty:
        df["barkod"] = df["barkod"].astype(str)
        df["stok"] = pd.to_numeric(df["stok"], errors="coerce").fillna(0).astype(int)
    return df


# --------------------------------------------------------------------------
# HTTP / XML
# --------------------------------------------------------------------------
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
    govde = (r.text or "").strip().replace("\n", " ")[:200]
    return f"HTTP {r.status_code} {govde}".strip()


def etiket(tag):
    return tag.split("}", 1)[-1]


def url_guvenli(url):
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("Yalnızca http/https bağlantıları desteklenir.")
    if os.environ.get("XML_OZEL_AG_IZNI") == "1":
        return
    port = p.port or (443 if p.scheme == "https" else 80)
    try:
        bilgiler = socket.getaddrinfo(p.hostname, port)
    except socket.gaierror as e:
        raise ValueError(f"Adres çözümlenemedi: {p.hostname}") from e
    for b in bilgiler:
        ip = ipaddress.ip_address(b[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError("Yerel/özel ağ adreslerine erişime izin verilmiyor.")


def indir(url, okuma_sn=300, deneme=2):
    url = (url or "").strip()
    url_guvenli(url)
    basliklar = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept": "application/xml,text/xml,*/*",
    }
    son_hata = None
    for i in range(max(1, deneme)):
        parcalar, boyut = [], 0
        try:
            with requests.get(url, headers=basliklar, timeout=(20, max(30, float(okuma_sn))), stream=True) as r:
                r.raise_for_status()
                url_guvenli(r.url)  # yönlendirme sonrası adresi de doğrula
                for p in r.iter_content(1024 * 1024):
                    boyut += len(p)
                    if boyut > MAKS_XML_BOYUT:
                        raise ValueError("XML dosyası çok büyük (300 MB üstü).")
                    parcalar.append(p)
            veri = b"".join(parcalar)
            if veri[:2] == b"\x1f\x8b":
                veri = gzip.decompress(veri)
            return veri
        except (requests.Timeout, requests.ConnectionError) as e:
            son_hata = e
            if i < deneme - 1:
                time.sleep(5)
    raise RuntimeError(
        f"Sunucu {int(okuma_sn)} sn içinde yanıt vermedi ({deneme} deneme). "
        "Tedarikçi sitesi yavaş olabilir ya da bu sunucunun IP'sini engelliyor olabilir."
    ) from son_hata


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
    except ParseError:
        ilk = veri[:200].decode("utf-8", "replace")
        raise ValueError(f"Geçerli XML değil. Gelen içerik: {ilk}")
    tag = urun_dugumu_bul(kok)
    if not tag:
        raise ValueError("XML içinde tekrar eden ürün kaydı bulunamadı.")
    satirlar = [duzlestir(e) for e in kok.iter() if etiket(e.tag) == tag]
    return pd.DataFrame(satirlar).fillna("")


@st.cache_data(ttl=600, show_spinner=False)
def xml_onizleme(url, okuma_sn=300):
    return xml_oku(indir(url, okuma_sn))


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


def _f(x, varsayilan=0.0):
    try:
        v = float(x)
        return varsayilan if v != v else v  # NaN kontrolü
    except (TypeError, ValueError):
        return varsayilan


def _i(x, varsayilan=0):
    return int(_f(x, varsayilan))


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


def normalle(tedarikci, df, harita, marj, sabit_ek, kritik_esik=0, stok_ust=50):
    def kol(ad):
        k = harita.get(ad, "(yok)")
        if k == "(yok)" or k not in df.columns:
            return pd.Series([""] * len(df), index=df.index)
        return df[k]

    alis = kol("fiyat").map(sayi)
    satis = alis * (1 + marj / 100) + sabit_ek
    stok = kol("stok").map(sayi).clip(lower=0, upper=max(1, int(stok_ust))).astype(int)
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


def tedarikci_senkron(ad, bilgi, kritik_esik=0, stok_ust=50):
    df_ham = xml_oku(indir(bilgi["link"], _f(bilgi.get("zaman_asimi"), 300.0)))
    df = normalle(
        ad, df_ham, bilgi.get("harita", {}),
        float(bilgi.get("marj", 30.0)), float(bilgi.get("sabit_ek", 0.0)),
        kritik_esik, stok_ust,
    )
    if df.empty:
        raise ValueError("XML'den geçerli ürün çıkmadı. Alan eşleştirmesini kontrol edin.")
    sutunlar = ["gorsel", "tedarikci", "barkod", "urun_adi", "stok", "alis_fiyati", "satis_fiyati", "kategori"]
    with closing(baglan()) as c:
        try:
            c.execute("BEGIN IMMEDIATE")
            c.execute("DELETE FROM urunler WHERE tedarikci = ?", (ad,))
            c.executemany(
                "INSERT INTO urunler (gorsel, tedarikci, barkod, urun_adi, stok, alis_fiyati, satis_fiyati, kategori) VALUES (?,?,?,?,?,?,?,?)",
                df[sutunlar].itertuples(index=False, name=None),
            )
            c.commit()
        except Exception:
            c.rollback()
            raise
    return len(df)


# --------------------------------------------------------------------------
# Fiyat kuralları ve ortak yardımcılar
# --------------------------------------------------------------------------
def fiyat_artis_uygula(ayar, pid, df):
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
        m_s = tadi.map(lambda t: float((ted.get(t) or {}).get("marj", 30.0)))
        k_s = tadi.map(lambda t: float((ted.get(t) or {}).get("sabit_ek", 0.0)))
        yeni = alis * (1 + (marj if marj > 0 else m_s) / 100) + (kargo if kargo > 0 else k_s)
        df["satis_fiyati"] = yeni.where(alis.notna() & (alis > 0), df["satis_fiyati"])
    if artis > 0:
        df["satis_fiyati"] = df["satis_fiyati"] * (1 + artis / 100)
    df["satis_fiyati"] = df["satis_fiyati"].round(2)
    return df


def objectid_mi(v):
    return bool(re.fullmatch(r"[0-9a-fA-F]{24}", str(v or "").strip()))


def gecerli_barkod(kod):
    k = str(kod).strip()
    return k if k.isdigit() and 8 <= len(k) <= 14 else None


def sabit_barkod(kod, uret=False):
    """Aynı koddan her zaman aynı barkodu üretir (Python hash() KULLANILMAZ)."""
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


def paketle(kayitlar, paket, fn, ilerleme=None, ad=""):
    """kayitlar: [(anahtar, veri)]. fn(veri_listesi) -> (basarili_mi, mesaj).
    Her paketin sonucu GERÇEK HTTP durumuna göre sayılır."""
    ok_k, hata_k, loglar = [], [], []
    toplam = max(1, -(-len(kayitlar) // paket))
    for no, i in enumerate(range(0, len(kayitlar), paket), 1):
        grup = kayitlar[i:i + paket]
        anahtarlar = [k for k, _ in grup]
        try:
            basari, mesaj = fn([v for _, v in grup])
        except Exception as e:
            basari, mesaj = False, f"İstek hatası: {e}"
        if basari:
            ok_k += anahtarlar
            loglar.append(f"✅ {ad} paket {no}/{toplam}: {len(grup)} kayıt. {mesaj}".strip())
        else:
            hata_k += anahtarlar
            loglar.append(f"❌ {ad} paket {no}/{toplam}: {len(grup)} kayıt BAŞARISIZ. {mesaj}".strip())
        if ilerleme:
            ilerleme(no / toplam, loglar)
    return ok_k, hata_k, loglar


def _sonuc(pid, ok_k, hata_k, loglar, atlanan=0):
    try:
        pazar_isaretle(pid, ok_k, hata_k)
    except Exception:
        pass
    if atlanan:
        loglar.append(f"ℹ️ {atlanan} ürün eksik bilgi (fiyat/barkod) nedeniyle atlandı.")
    return len(ok_k), len(hata_k), loglar


def kayit_listesi(df):
    return df.to_dict("records") if not df.empty else []


# --------------------------------------------------------------------------
# Trendyol
# --------------------------------------------------------------------------
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
        "GET", f"{TY_BASE}/order/sellers/{seller}/orders",
        params={"status": durum, "size": boyut, "orderByField": "PackageLastModifiedDate", "orderByDirection": "DESC"},
        headers=trendyol_header(seller, key, secret), timeout=30,
    )
    r.raise_for_status()
    return r.json().get("content", [])


def trendyol_guncelle(ayar, df, ilerleme=None):
    s, k, x = (kimlik(ayar, a) for a in ("trendyol_seller_id", "trendyol_key", "trendyol_secret"))
    kayit, atlanan = [], 0
    for r in kayit_listesi(df):
        fiyat = _f(r.get("satis_fiyati"))
        if fiyat <= 0:
            atlanan += 1
            continue
        b = str(r["barkod"])
        kayit.append((b, {
            "barcode": b,
            "quantity": int(min(max(_i(r.get("stok")), 0), 20000)),
            "salePrice": fiyat,
            "listPrice": fiyat,
        }))

    def gonder(grup):
        r = http("POST", f"{TY_BASE}/inventory/sellers/{s}/products/price-and-inventory",
                 json={"items": grup}, headers=trendyol_header(s, k, x), timeout=60)
        return r.status_code == 200, yanit_ozet(r)

    ok_k, hata_k, loglar = paketle(kayit, 1000, gonder, ilerleme, "Trendyol")
    return _sonuc("trendyol", ok_k, hata_k, loglar, atlanan)


# --------------------------------------------------------------------------
# N11
# --------------------------------------------------------------------------
N11_BASE = "https://api.n11.com"


def n11_header(key, secret):
    return {"appKey": key, "appSecret": secret, "Content-Type": "application/json"}


def n11_siparisler(key, secret, durum, sayfa_siniri=3):
    sonuc = []
    for sayfa_ in range(sayfa_siniri):
        r = http(
            "GET", f"{N11_BASE}/rest/delivery/v1/shipmentPackages",
            params={"status": durum, "page": sayfa_, "size": 100, "orderByDirection": "DESC"},
            headers=n11_header(key, secret), timeout=60,
        )
        r.raise_for_status()
        icerik = r.json().get("content") or []
        sonuc += icerik
        if len(icerik) < 100:
            break
    return sonuc


def n11_guncelle(ayar, df, ilerleme=None):
    key, secret = kimlik(ayar, "n11_key"), kimlik(ayar, "n11_secret")
    kayit, atlanan = [], 0
    for r in kayit_listesi(df):
        fiyat = round(_f(r.get("satis_fiyati")), 2)
        if fiyat <= 0:
            atlanan += 1
            continue
        kod = str(r["barkod"])
        kayit.append((kod, {
            "stockCode": kod, "listPrice": fiyat, "salePrice": fiyat,
            "quantity": max(_i(r.get("stok")), 0), "currencyType": "TL",
        }))

    def gonder(grup):
        r = http("POST", f"{N11_BASE}/ms/product/tasks/price-stock-update",
                 json={"payload": {"integrator": "SahEntegre", "skus": grup}},
                 headers=n11_header(key, secret), timeout=120)
        return r.status_code == 200, yanit_ozet(r)

    ok_k, hata_k, loglar = paketle(kayit, 1000, gonder, ilerleme, "N11")
    return _sonuc("n11", ok_k, hata_k, loglar, atlanan)


def n11_urun_listesi(df, ayar):
    pa = pa_al(ayar, "n11")
    cat_varsayilan = _i(pa.get("category_id"))
    atr = pa.get("attributes") or []
    sablon = str(pa.get("shipment_template", "") or "").strip()
    if not sablon:
        raise ValueError("N11 için 'Kargo şablonu' ayarı boş. Genel Ayarlar'dan girin.")
    liste, atlanan = [], 0
    for r in kayit_listesi(df):
        gorsel = str(r.get("gorsel", "")).strip()
        kod = str(r["barkod"]).strip()
        fiyat = round(_f(r.get("satis_fiyati")), 2)
        cat = _i(kategori_id(pa, ayar, r.get("kategori"), "n11") or cat_varsayilan)
        if not gorsel.startswith("https") or fiyat <= 0 or not kod or cat <= 0:
            atlanan += 1
            continue
        ad = str(r["urun_adi"]).strip()
        liste.append({
            "title": ad[:250], "description": ad, "categoryId": cat, "currencyType": "TL",
            "productMainId": kod, "preparingDay": _i(pa.get("preparing_day"), 3) or 3,
            "shipmentTemplate": sablon, "stockCode": kod, "catalogId": None,
            "barcode": gecerli_barkod(kod), "quantity": max(_i(r.get("stok")), 0),
            "images": [{"url": gorsel, "order": 0}], "attributes": atr,
            "salePrice": fiyat, "listPrice": fiyat, "vatRate": _i(pa.get("kdv"), 20),
        })
    return liste, atlanan


def n11_urun_gonder(ayar, liste, ilerleme=None):
    h = n11_header(kimlik(ayar, "n11_key"), kimlik(ayar, "n11_secret"))
    kayit = [(u["stockCode"], u) for u in liste]

    def gonder(grup):
        r = http("POST", f"{N11_BASE}/ms/product/tasks/product-create", headers=h, timeout=120, tries=2,
                 json={"payload": {"integrator": "SahEntegre", "skus": grup}})
        return r.status_code == 200, yanit_ozet(r)

    ok_k, hata_k, loglar = paketle(kayit, 100, gonder, ilerleme, "N11")
    return len(ok_k), len(hata_k), loglar


# --------------------------------------------------------------------------
# İdefix
# --------------------------------------------------------------------------
ID_BASE = "https://merchantapi.idefix.com"


def idefix_header(ayar):
    key, secret = kimlik(ayar, "idefix_token"), kimlik(ayar, "idefix_secret")
    tok = base64.b64encode(f"{key}:{secret}".encode()).decode()
    return {"X-API-KEY": tok, "Content-Type": "application/json"}


def idefix_barkod(kod, ayar):
    k = str(kod).strip()
    g = gecerli_barkod(k)
    if g:
        return g
    return k if pa_al(ayar, "idefix").get("stok_kodu_barkod") else None


def idefix_guncelle(ayar, df, ilerleme=None):
    h, v = idefix_header(ayar), kimlik(ayar, "idefix_satici_id")
    kayit, atlanan = [], 0
    for r in kayit_listesi(df):
        bk = idefix_barkod(r["barkod"], ayar)
        fiyat = round(_f(r.get("satis_fiyati")), 2)
        if not bk or fiyat <= 0:
            atlanan += 1
            continue
        kayit.append((str(r["barkod"]), {
            "barcode": bk, "price": fiyat, "comparePrice": fiyat,
            "inventoryQuantity": max(_i(r.get("stok")), 0),
        }))

    def gonder(grup):
        r = http("POST", f"{ID_BASE}/pim/catalog/{v}/inventory-upload", json={"items": grup}, headers=h, timeout=120)
        return r.status_code in (200, 201, 202), yanit_ozet(r)

    ok_k, hata_k, loglar = paketle(kayit, 500, gonder, ilerleme, "İdefix")
    return _sonuc("idefix", ok_k, hata_k, loglar, atlanan)


def idefix_urun_listesi(df, ayar):
    pa = pa_al(ayar, "idefix")
    brand = _i(pa.get("brand_id"))
    if brand <= 0:
        raise ValueError("İdefix için 'Marka ID' ayarı boş. Genel Ayarlar'dan girin.")
    cat_varsayilan = _i(pa.get("category_id"))
    atr = pa.get("attributes") or []
    kdv = _i(pa.get("kdv"), 20)
    sure = _i(pa.get("teslim_suresi"), 3) or 1
    liste, atlanan = [], 0
    for r in kayit_listesi(df):
        gorsel = str(r.get("gorsel", "")).strip()
        kod = str(r["barkod"]).strip()
        bk = idefix_barkod(kod, ayar)
        fiyat = round(_f(r.get("satis_fiyati")), 2)
        cat = _i(kategori_id(pa, ayar, r.get("kategori"), "idefix") or cat_varsayilan)
        if not gorsel.startswith("https") or fiyat <= 0 or not bk or cat <= 0:
            atlanan += 1
            continue
        ad = str(r["urun_adi"]).strip()
        liste.append({
            "barcode": bk, "title": ad[:250], "productMainId": kod, "brandId": brand,
            "categoryId": cat, "inventoryQuantity": max(_i(r.get("stok")), 0),
            "vendorStockCode": kod, "description": ad, "price": fiyat, "comparePrice": fiyat,
            "vatRate": kdv, "deliveryDuration": sure, "deliveryType": "regular",
            "images": [{"url": gorsel}], "attributes": atr,
        })
    return liste, atlanan


def idefix_gonder(ayar, liste, ilerleme=None):
    h, v = idefix_header(ayar), kimlik(ayar, "idefix_satici_id")
    kayit = [(u["vendorStockCode"], u) for u in liste]

    def gonder(grup):
        r = http("POST", f"{ID_BASE}/pim/pool/{v}/create", json={"products": grup}, headers=h, timeout=120, tries=2)
        return r.status_code in (200, 201, 202), yanit_ozet(r)

    ok_k, hata_k, loglar = paketle(kayit, 100, gonder, ilerleme, "İdefix")
    return len(ok_k), len(hata_k), loglar


# --------------------------------------------------------------------------
# Hepsiburada
# --------------------------------------------------------------------------
HB_BASE = "https://listing-external.hepsiburada.com"


def hb_kombiler(ayar):
    m, u, p = (kimlik(ayar, k) for k in ("hb_merchant_id", "hb_user", "hb_pass"))
    ua = f"{m} - SelfIntegration"
    return [
        {
            "Authorization": "Basic " + base64.b64encode(f"{a}:{p}".encode()).decode(),
            "User-Agent": c, "Accept": "application/json", "Content-Type": "application/json",
        }
        for a, c in ((u, u), (m, u), (u, ua), (m, ua))
    ]


def hb_header(ayar):
    k = hb_kombiler(ayar)
    i = _i(pa_al(ayar, "hb").get("kombi"), 0)
    return k[i if 0 <= i < len(k) else 0]


def hb_dene(ayar):
    m = kimlik(ayar, "hb_merchant_id")
    for i, h in enumerate(hb_kombiler(ayar)):
        try:
            r = requests.get(f"{HB_BASE}/listings/merchantid/{m}", params={"offset": 0, "limit": 1}, headers=h, timeout=30)
        except Exception:
            continue
        if r.status_code == 200:
            pa_al(ayar, "hb")["kombi"] = i
            ayar_yaz(ayar)
            return True, "✅ Hepsiburada girişi başarılı."
    return False, "❌ Hepsiburada girişi reddedildi (kullanıcı adı / servis anahtarı / merchant ID kontrol edin)."


def hb_guncelle(ayar, df, ilerleme=None):
    m = kimlik(ayar, "hb_merchant_id")
    onek = str(pa_al(ayar, "hb").get("sku_prefix", "") or "")
    kayit, atlanan = [], 0
    for r in kayit_listesi(df):
        fiyat = round(_f(r.get("satis_fiyati")), 2)
        if fiyat <= 0:
            atlanan += 1
            continue
        sku = onek + str(r["barkod"]).strip()
        kayit.append((str(r["barkod"]), (sku, fiyat, max(_i(r.get("stok")), 0))))

    def gonder(grup):
        h = hb_header(ayar)
        url = f"{HB_BASE}/listings/merchantid/{m}"
        rf = http("POST", f"{url}/price-uploads", json=[{"merchantSku": s, "price": f} for s, f, _ in grup], headers=h, timeout=60)
        rs = http("POST", f"{url}/stock-uploads", json=[{"merchantSku": s, "availableStock": a} for s, _, a in grup], headers=h, timeout=60)
        ok = rf.status_code in (200, 201, 202) and rs.status_code in (200, 201, 202)
        return ok, f"fiyat: {yanit_ozet(rf)} | stok: {yanit_ozet(rs)}"

    ok_k, hata_k, loglar = paketle(kayit, 500, gonder, ilerleme, "Hepsiburada")
    return _sonuc("hb", ok_k, hata_k, loglar, atlanan)


def hb_urun_adresi(ayar):
    """Ürün oluşturma adresi: yalnızca https + hepsiburada.com alan adı (kimlik bilgisi başka siteye sızmasın)."""
    u = str(pa_al(ayar, "hb").get("urun_endpoint", "") or "").strip()
    if not u:
        raise ValueError("Hepsiburada 'Ürün oluşturma adresi' boş. Hepsiburada API dokümanındaki tam adresi Genel Ayarlar'dan girin.")
    pr = urllib.parse.urlparse(u)
    host = (pr.hostname or "").lower()
    if pr.scheme != "https" or not (host == "hepsiburada.com" or host.endswith(".hepsiburada.com")):
        raise ValueError("Hepsiburada ürün oluşturma adresi https:// ile başlamalı ve hepsiburada.com alan adında olmalı.")
    return u


def hb_urun_listesi(df, ayar):
    """UYARI: Hepsiburada ürün oluşturma alan adları resmi dokümandan doğrulanmadı.
    Önizlenen JSON'u Hepsiburada dokümanıyla karşılaştırın; önce 'Tek ürün (Test)' ile deneyin."""
    hb_urun_adresi(ayar)
    pa = pa_al(ayar, "hb")
    cat_varsayilan = str(pa.get("category_id", "") or "").strip()
    marka = str(pa.get("marka", "") or "").strip()
    atr = pa.get("attributes") or []
    onek = str(pa.get("sku_prefix", "") or "")
    kdv = _i(pa.get("kdv"), 20)
    uret = bool(pa.get("gecici_barkod", True))
    liste, atlanan = [], 0
    for r in kayit_listesi(df):
        gorsel = str(r.get("gorsel", "")).strip()
        kod = str(r["barkod"]).strip()
        barkod = sabit_barkod(kod, uret)
        fiyat = round(_f(r.get("satis_fiyati")), 2)
        cat = kategori_id(pa, ayar, r.get("kategori"), "hb") or cat_varsayilan
        if not gorsel.startswith("https") or fiyat <= 0 or not barkod or not cat:
            atlanan += 1
            continue
        ad = str(r["urun_adi"]).strip()
        liste.append({
            "merchantSku": onek + kod, "barcode": barkod, "productName": ad[:250], "description": ad,
            "categoryId": cat, "brand": marka, "price": fiyat, "availableStock": max(_i(r.get("stok")), 0),
            "vatRate": kdv, "images": [gorsel], "attributes": atr,
        })
    return liste, atlanan


def hb_urun_gonder(ayar, liste, ilerleme=None):
    url = hb_urun_adresi(ayar)
    kayit = [(u["merchantSku"], u) for u in liste]

    def gonder(grup):
        r = http("POST", url, json=grup, headers=hb_header(ayar), timeout=120, tries=2)
        return r.status_code in (200, 201, 202), yanit_ozet(r)

    ok_k, hata_k, loglar = paketle(kayit, 100, gonder, ilerleme, "Hepsiburada")
    return len(ok_k), len(hata_k), loglar


def hb_siparisler(ayar):
    m = kimlik(ayar, "hb_merchant_id")
    if not m:
        return []
    r = http("GET", f"https://orders-external.hepsiburada.com/packages/merchantid/{m}", headers=hb_header(ayar), timeout=30)
    r.raise_for_status()
    return r.json() or []


# --------------------------------------------------------------------------
# PTT AVM
# --------------------------------------------------------------------------
PTT_BASE = "https://integration-api.pttavm.com/api/v1"
PTT_URUN_YOLU = "products/upsert"  # PTT dokümanı: POST /api/v1/products/upsert (Ürün Ekleme Güncelleme)


def ptt_header(ayar):
    """PTT dokümanı: Api-Key, access-token ve X-Correlation-Id zorunlu (her istekte yeni benzersiz değer)."""
    return {
        "access-token": kimlik(ayar, "ptt_token"), "api-key": kimlik(ayar, "ptt_key"),
        "X-Correlation-Id": str(uuid.uuid4()),
        "Accept": "application/json", "Content-Type": "application/json",
    }


def ptt_test(key, token):
    if not key or not token:
        return False, "API Key (Shop ID) veya Token eksik."
    try:
        h = {"access-token": token, "api-key": key, "X-Correlation-Id": str(uuid.uuid4()), "Accept": "application/json"}
        r = requests.get(f"{PTT_BASE}/categories/main", headers=h, timeout=15)
        if r.status_code in (200, 201):
            return True, f"✅ PTT AVM bağlantısı başarılı (HTTP {r.status_code})"
        return False, f"❌ PTT AVM bağlantısı başarısız ({yanit_ozet(r)})"
    except Exception as e:
        return False, f"Bağlantı hatası: {e}"


def ptt_yanit_kontrol(r):
    """HTTP durumu + (varsa) yanıttaki success=false / message bilgisi. Dönüş: (basarili, mesaj)."""
    ok = r.status_code in (200, 201, 202)
    mesaj = ""
    try:
        j = r.json()
    except Exception:
        j = None
    if isinstance(j, dict):
        if j.get("success") is False:
            ok = False
        if j.get("message"):
            mesaj = f" | {str(j['message'])[:200]}"
    return ok, mesaj


def ptt_guncelle(ayar, df, ilerleme=None):
    """PTT 'Fiyat Stok Güncelle': POST /products/stock-prices (en çok 1000 ürün/istek; aynı istek 5 dk içinde
    tekrar gönderilemez; aynı barkod bir istekte tek kez; KDV dahil fiyat 1'den büyük olmalı)."""
    if not (kimlik(ayar, "ptt_key") and kimlik(ayar, "ptt_token")):
        raise RuntimeError("PTT API Key / Token eksik.")
    uret = bool(pa_al(ayar, "ptt").get("gecici_barkod", True))
    tekil, atlanan = {}, 0
    for r in kayit_listesi(df):
        fiyat = round(_f(r.get("satis_fiyati")), 2)
        if fiyat <= 1:  # fiyatı yoksa alış fiyatıyla GÖNDERME; PTT KDV dahil fiyatın 1'den büyük olmasını ister
            atlanan += 1
            continue
        ptt_b = sabit_barkod(str(r["barkod"]).strip(), uret)  # ürün oluştururken kullanılan barkodla aynı
        if not ptt_b or len(ptt_b) > 250:
            atlanan += 1
            continue
        tekil[ptt_b] = (str(r["barkod"]), {"barcode": ptt_b, "quantity": max(_i(r.get("stok")), 0), "priceWithVAT": fiyat})
    kayit = list(tekil.values())  # aynı barkod tek kez (sonuncusu)
    izler = []

    def gonder(grup):
        # tries=1: PTT aynı isteğin 5 dk içinde tekrarını reddeder; otomatik yeniden deneme anlamsız
        r = http("POST", f"{PTT_BASE}/products/stock-prices", json={"items": grup}, headers=ptt_header(ayar), timeout=60, tries=1)
        tid = ptt_tracking_id(r)
        if tid:
            izler.append(tid)
        ok, ek = ptt_yanit_kontrol(r)
        return ok, yanit_ozet(r) + ek + (f" | trackingId: {tid}" if tid else "")

    ok_k, hata_k, loglar = paketle(kayit, 500, gonder, ilerleme, "PTT")
    try:
        ptt_takip_kaydet(ayar, izler)
    except Exception:
        pass
    if hata_k:
        loglar.append("ℹ️ PTT aynı isteği 5 dakika içinde tekrar kabul etmez; hata aldıysanız 5 dk bekleyip tekrar deneyin.")
    return _sonuc("ptt", ok_k, hata_k, loglar, atlanan)


def ptt_urun_listesi(df, ayar):
    """PTT AVM 'Ürün Ekleme Güncelleme' (POST /products/upsert) — varyantsız ürün.
    Alan adları PTT dokümanındaki örnek istekten alınmıştır. Doğrulanamayanlar (hangi alan zorunlu,
    KDV'li/KDV'siz fiyat kuralı) için önce 'Tek ürün (Test)' ile deneyip sonucu sorgulayın."""
    pa = pa_al(ayar, "ptt")
    cat_varsayilan = str(pa.get("category_id", "") or "").strip()
    kdv = _i(pa.get("kdv"), 20)
    uret = bool(pa.get("gecici_barkod", True))
    marka = str(pa.get("marka", "") or "").strip()
    desi = _f(pa.get("desi"), 1.0) or 1.0
    desi = int(desi) if float(desi).is_integer() else desi
    kargo = str(pa.get("kargo_profil", "") or "").strip()
    aktif = bool(pa.get("aktif_gonder", False))
    liste, atlanan = [], 0
    for r in kayit_listesi(df):
        gorsel = str(r.get("gorsel", "")).strip()
        kod = str(r["barkod"]).strip()
        barkod = sabit_barkod(kod, uret)
        fiyat = round(_f(r.get("satis_fiyati")), 2)
        cat = kategori_id(pa, ayar, r.get("kategori"), "ptt") or cat_varsayilan
        if not gorsel.startswith("https") or fiyat <= 0 or not barkod or not cat.isdigit():
            atlanan += 1
            continue
        ad = str(r["urun_adi"]).strip()
        u = {
            "categoryId": int(cat), "barcode": barkod, "productCode": kod, "name": ad[:250],
            "shortDescription": ad[:250], "longDescription": ad,
            "priceWithVat": fiyat, "priceWithoutVat": round(fiyat / (1 + kdv / 100), 2), "vatRate": kdv,
            "quantity": max(_i(r.get("stok")), 0), "desi": desi,
            "images": [{"url": gorsel}], "active": aktif,
        }
        if gecerli_barkod(kod):  # yalnızca gerçek barkodlarda GTIN/EAN gönder
            u["ean"] = kod
            u["gtin"] = kod
        if marka:
            u["brand"] = marka
        if kargo:
            u["cargoProfileId"] = int(kargo) if kargo.isdigit() else kargo
        liste.append(u)
    return liste, atlanan


def ptt_tracking_id(r):
    """Yanıttaki trackingId'yi (büyük/küçük harf fark etmeksizin) bulur."""
    try:
        j = r.json()
    except Exception:
        return ""

    def ara(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if str(k).lower().replace("_", "") == "trackingid" and v:
                    return str(v)
            for v in o.values():
                b = ara(v)
                if b:
                    return b
        elif isinstance(o, list):
            for v in o:
                b = ara(v)
                if b:
                    return b
        return ""
    return ara(j)


def ptt_takip_kaydet(ayar, idler):
    liste = [i for i in idler if i]
    if not liste:
        return
    onceki = [i for i in (ayar.get("ptt_takip") or []) if i not in liste]
    ayar["ptt_takip"] = (liste + onceki)[:20]
    ayar_yaz(ayar)


def ptt_urun_gonder(ayar, liste, ilerleme=None):
    if not (kimlik(ayar, "ptt_key") and kimlik(ayar, "ptt_token")):
        raise RuntimeError("PTT API Key / Token eksik.")
    kayit = [(u["productCode"], u) for u in liste]
    izler = []

    def gonder(grup):
        r = http("POST", f"{PTT_BASE}/{PTT_URUN_YOLU}", json={"items": grup}, headers=ptt_header(ayar), timeout=60, tries=2)
        tid = ptt_tracking_id(r)
        if tid:
            izler.append(tid)
        ok, ek = ptt_yanit_kontrol(r)
        return ok, yanit_ozet(r) + ek + (f" | trackingId: {tid}" if tid else "")

    ok_k, hata_k, loglar = paketle(kayit, 25, gonder, ilerleme, "PTT")
    try:
        ptt_takip_kaydet(ayar, izler)
    except Exception:
        pass
    return len(ok_k), len(hata_k), loglar


def ptt_kategori_agaci(ayar):
    """PTT 'Kategori Ağacı': GET /categories/category-tree."""
    r = http("GET", f"{PTT_BASE}/categories/category-tree", headers=ptt_header(ayar), timeout=90, tries=2)
    if r.status_code != 200:
        raise RuntimeError(f"Kategori ağacı alınamadı ({yanit_ozet(r)})")
    return r.json()


def ptt_kategori_duzlestir(veri):
    """Yanıt biçimi dokümanda görünmediği için toleranslı okur: id+ad taşıyan düğümleri ve alt listelerini gezer."""
    sonuc = []

    def id_ad(d):
        i = next((d[k] for k in ("id", "Id", "ID", "categoryId", "category_id") if d.get(k) not in (None, "")), None)
        a = next((d[k] for k in ("name", "Name", "categoryName", "title", "displayName") if isinstance(d.get(k), str) and d[k].strip()), None)
        return i, a

    def alt(d):
        for k, v in d.items():
            if isinstance(v, list) and v and all(isinstance(x, dict) for x in v) and \
                    k.lower().replace("_", "") in ("children", "subcategories", "subcategorylist", "categories", "childcategories", "nodes", "items"):
                return v
        for k, v in d.items():
            if isinstance(v, list) and v and all(isinstance(x, dict) for x in v) and any(id_ad(x)[0] is not None and id_ad(x)[1] for x in v):
                return v
        return []

    def gez(o, yol, derinlik=0):
        if derinlik > 12:
            return
        if isinstance(o, list):
            for x in o:
                gez(x, yol, derinlik + 1)
        elif isinstance(o, dict):
            i, a = id_ad(o)
            cocuk = alt(o)
            y = yol
            if i is not None and a:
                y = yol + [a]
                sonuc.append({"ID": str(i), "Kategori": " > ".join(y), "Alt kategorisi var": bool(cocuk)})
            if cocuk:
                gez(cocuk, y, derinlik + 1)
            elif i is None:
                for v in o.values():
                    if isinstance(v, (list, dict)):
                        gez(v, y, derinlik + 1)

    gez(veri, [])
    return sonuc
