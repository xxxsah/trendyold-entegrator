"""\u015eahEntegre - E-Ticaret Y\u00f6netim Paneli (d\u00fczeltilmi\u015f s\u00fcr\u00fcm)

\u00c7al\u0131\u015ft\u0131rma:  streamlit run app.py
Gizli bilgiler i\u00e7in \u00f6ncelik s\u0131ras\u0131: ortam de\u011fi\u015fkeni > st.secrets > ayarlar.json
\u00d6nerilen: APP_PASSWORD ortam de\u011fi\u015fkenini mutlaka tan\u0131mlay\u0131n.
"""
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
from datetime import datetime
from pathlib import Path
from xml.etree.ElementTree import ParseError

try:  # G\u00fcvenli XML ayr\u0131\u015ft\u0131r\u0131c\u0131 (billion-laughs vb. sald\u0131r\u0131lara kar\u015f\u0131)
    from defusedxml import ElementTree as ET
except ImportError:  # pragma: no cover
    import xml.etree.ElementTree as ET

import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="\u015eahEntegre - E-Ticaret Y\u00f6netim Paneli", page_icon="\U0001f451", layout="wide"
)

BASE = Path(__file__).parent
VERI_KLASORU = Path(os.environ.get("SAHENTEGRE_VERI", BASE))
DB_DOSYA = VERI_KLASORU / "metentegre.db"
AYAR_DOSYA = VERI_KLASORU / "ayarlar.json"
KILIT = threading.Lock()
SENKRON_KILIDI = threading.Lock()
MAKS_XML_BOYUT = 300 * 1024 * 1024
OTURUM_SURESI = 12 * 3600

ayarlar = {}  # main() i\u00e7inde her \u00e7al\u0131\u015fmada diskten y\u00fcklenir

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
    "stok_sifir": {},
    "son_yedek": "",
    "ptt_takip": [],
}

PAZAR = {
    "hb": {"ad": "Hepsiburada", "renk": "#ff6000", "ikon": "\U0001f6cd\ufe0f", "pastel": "#fff3ed"},
    "trendyol": {"ad": "Trendyol", "renk": "#f27a1a", "ikon": "\U0001f9e1", "pastel": "#fff4ec"},
    "n11": {"ad": "N11", "renk": "#5015ff", "ikon": "\U0001f534", "pastel": "#f0ebff"},
    "idefix": {"ad": "\u0130defix", "renk": "#00a651", "ikon": "\U0001f4da", "pastel": "#e6f9ed"},
    "ptt": {"ad": "PTT AVM", "renk": "#ffcd00", "ikon": "\U0001f4e6", "pastel": "#fffde6"},
    "trendruum": {"ad": "Trendruum", "renk": "#8b5cf6", "ikon": "\U0001f6d2", "pastel": "#f5f3ff"},
}
PAZAR_AD = {k: v["ad"] for k, v in PAZAR.items()}

OTO_ANAHTAR = (
    ("Trendruum", "tr_oto_guncelle", "trendruum"),
    ("Trendyol", "ty_oto_guncelle", "trendyol"),
    ("Hepsiburada", "hb_oto_guncelle", "hb"),
    ("N11", "n11_oto_guncelle", "n11"),
    ("\u0130defix", "idefix_oto_guncelle", "idefix"),
    ("PTT AVM", "ptt_oto_guncelle", "ptt"),
)
OTO_BAYRAK = {pid: anahtar for _, anahtar, pid in OTO_ANAHTAR}

PAZAR_KIMLIK = {
    "hb": [("Merchant ID", "hb_merchant_id", False), ("API Kullan\u0131c\u0131 Ad\u0131", "hb_user", False), ("Servis Anahtar\u0131", "hb_pass", True)],
    "trendyol": [("Sat\u0131c\u0131 ID", "trendyol_seller_id", False), ("API Key", "trendyol_key", True), ("API Secret", "trendyol_secret", True)],
    "n11": [("App Key", "n11_key", True), ("App Secret", "n11_secret", True)],
    "idefix": [("Sat\u0131c\u0131 ID", "idefix_satici_id", False), ("API Key", "idefix_token", True), ("API Secret", "idefix_secret", True)],
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
                raise ValueError("ayarlar.json bir nesne olmal\u0131")
        except Exception:
            # Bozuk dosyay\u0131 SESS\u0130ZCE ezme: \u00f6nce yedekle.
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
    for k in KIMLIK_ALANLARI:  # eski d\u00fcz yap\u0131dan g\u00f6\u00e7
        if k in veri and isinstance(veri[k], str):
            veri["kimlik"].setdefault(k, veri.pop(k))
    return veri


def _yedek_anahtar(parola, tuz):
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    kdf = Scrypt(salt=tuz, length=32, n=2 ** 15, r=8, p=1)
    return base64.urlsafe_b64encode(kdf.derive(parola.encode("utf-8")))


def yedek_sifrele(veri, parola):
    """Ayarlar\u0131 (API anahtarlar\u0131 dahil) parolayla \u015fifreler. D\u00f6n\u00fc\u015f: JSON baytlar\u0131."""
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
        raise ValueError("Yedek parolas\u0131 hatal\u0131 ya da dosya bozulmu\u015f.")


def tr_norm(t):
    """T\u00fcrk\u00e7e-g\u00fcvenli k\u00fc\u00e7\u00fck harf (\u0130/I/\u0131 sorunu: Python '\u0130'.lower() noktal\u0131 birle\u015fik karakter \u00fcretir)."""
    return str(t).replace("\u0130", "i").replace("I", "i").replace("\u0131", "i").lower()


def kara_liste_maskesi(ayar, df):
    """Kara listedeki kelimeleri i\u00e7eren \u00fcr\u00fcnler i\u00e7in True d\u00f6ner (ad / kategori / barkod)."""
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
            os.chmod(tmp, 0o600)  # API anahtarlar\u0131 sadece sahibi taraf\u0131ndan okunabilsin
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
    """Pazar yeri ayar s\u00f6zl\u00fc\u011f\u00fc (yoksa olu\u015fturur)."""
    return ayar.setdefault("pazar_ayarlari", {}).setdefault(pid, {})


def pazar_bagli(ayar, pid):
    gerek = GEREKLI_KIMLIK.get(pid)
    return bool(gerek) and all(kimlik(ayar, k) for k in gerek)


# --------------------------------------------------------------------------
# Veritaban\u0131
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


def stok_sifir_kume(ayar):
    return {str(b) for b in (ayar.get("stok_sifir") or {})}


def stok_sifir_maskesi(ayar, df):
    """Elle 'stoku sifir' yapilmis (kilitli) barkodlar icin True doner."""
    if df.empty or "barkod" not in df.columns:
        return pd.Series(False, index=df.index)
    return df["barkod"].astype(str).isin(stok_sifir_kume(ayar))


def stok_sifirla(ayar, barkodlar, pazarlara_gonder=True):
    """Barkodlari kilitler, veritabaninda stogu 0 yapar ve istenirse bagli pazar yerlerine hemen gonderir.
    Donus: [(pazar_adi, ok, hata_ya_da_mesaj), ...]"""
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
    log_yaz("Sistem", "OK", f"{len(barkodlar)} \u00fcr\u00fcn\u00fcn sto\u011fu elle s\u0131f\u0131rland\u0131 (kilitlendi).")
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
    raise RuntimeError(f"Ba\u011flant\u0131 kurulamad\u0131: {son}")


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


def yanit_ozet(r):
    """Yaniti okunur ozet yapar: JSON ise mesaj + hata metinleri (Turkce karakterler cozulur)."""
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
        _hata_metinleri(j.get("errors") or j.get("error"), parcalar)
        if parcalar:
            return f"HTTP {r.status_code} " + " | ".join(parcalar)[:700]
    return f"HTTP {r.status_code} {ham[:300]}".strip()


def kod_goster(yer, metin):
    """Uzun log satirlarini kaydirmadan okunsun diye satir kaydirmali gosterir."""
    try:
        yer.code(metin, wrap_lines=True)
    except TypeError:
        yer.code(metin)


def etiket(tag):
    return tag.split("}", 1)[-1]


def url_guvenli(url):
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("Yaln\u0131zca http/https ba\u011flant\u0131lar\u0131 desteklenir.")
    if os.environ.get("XML_OZEL_AG_IZNI") == "1":
        return
    port = p.port or (443 if p.scheme == "https" else 80)
    try:
        bilgiler = socket.getaddrinfo(p.hostname, port)
    except socket.gaierror as e:
        raise ValueError(f"Adres \u00e7\u00f6z\u00fcmlenemedi: {p.hostname}") from e
    for b in bilgiler:
        ip = ipaddress.ip_address(b[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError("Yerel/\u00f6zel a\u011f adreslerine eri\u015fime izin verilmiyor.")


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
                url_guvenli(r.url)  # y\u00f6nlendirme sonras\u0131 adresi de do\u011frula
                for p in r.iter_content(1024 * 1024):
                    boyut += len(p)
                    if boyut > MAKS_XML_BOYUT:
                        raise ValueError("XML dosyas\u0131 \u00e7ok b\u00fcy\u00fck (300 MB \u00fcst\u00fc).")
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
        f"Sunucu {int(okuma_sn)} sn i\u00e7inde yan\u0131t vermedi ({deneme} deneme). "
        "Tedarik\u00e7i sitesi yava\u015f olabilir ya da bu sunucunun IP'sini engelliyor olabilir."
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
        raise ValueError(f"Ge\u00e7erli XML de\u011fil. Gelen i\u00e7erik: {ilk}")
    tag = urun_dugumu_bul(kok)
    if not tag:
        raise ValueError("XML i\u00e7inde tekrar eden \u00fcr\u00fcn kayd\u0131 bulunamad\u0131.")
    satirlar = [duzlestir(e) for e in kok.iter() if etiket(e.tag) == tag]
    return pd.DataFrame(satirlar).fillna("")


@st.cache_data(ttl=600, show_spinner=False)
def xml_onizleme(url, okuma_sn=300):
    return xml_oku(indir(url, okuma_sn))


def sayi(x):
    s = str(x).strip().replace("TL", "").replace("\u20ba", "").replace(" ", "")
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
        return varsayilan if v != v else v  # NaN kontrol\u00fc
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


VARSAYILAN_KADEME = [[500, 60.0], [5000, 30.0], [20000, 15.0], [None, 8.0]]


def kademe_temizle(k):
    """[[ust_sinir, marj], ...] -> gecerli, sirali liste. Son satir sinirsiz (None) olur."""
    sonuc = []
    for r in (k or []):
        try:
            ust = None if r[0] in (None, "") else float(r[0])
            mj = float(r[1])
        except (TypeError, ValueError, IndexError):
            continue
        if mj < 0 or (ust is not None and ust <= 0):
            continue
        sonuc.append([ust, mj])
    sinirli = sorted([r for r in sonuc if r[0] is not None], key=lambda r: r[0])
    sinirsiz = [r for r in sonuc if r[0] is None]
    son = sinirsiz[-1] if sinirsiz else None
    if not sinirli and not son:
        return []
    if son is None:
        son = [None, sinirli[-1][1]]
    return sinirli + [son]


def kademeli_marj(alis, kademe, varsayilan):
    """Alis fiyatina gore marj (%) serisi dondurur. Kademe yoksa varsayilan marj."""
    kademe = kademe_temizle(kademe)
    if not kademe:
        return pd.Series([float(varsayilan)] * len(alis), index=alis.index)
    sonuc = pd.Series([kademe[-1][1]] * len(alis), index=alis.index, dtype=float)
    for ust, mj in reversed([r for r in kademe if r[0] is not None]):
        sonuc = sonuc.where(alis > ust, mj)
    return sonuc


def ad_temizle(x):
    t = html.unescape(html.unescape(str(x)))
    return re.sub(r"\s+", " ", t).strip()


DOVIZ_TL = {"TL", "TRY", "TRL", "\u20ba"}
DOVIZ_USD = {"USD", "$"}
DOVIZ_SON = {}  # tedarikci adi -> son senkronizasyondaki para birimi dagilimi


def kesin_sayi(x):
    """Nokta her zaman ondalik ayracidir (ornek: 1282.275). Sadece kontrollu tedarikcilerde kullanilir."""
    s = str(x).strip().replace("TL", "").replace(" ", "")
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


def kdv_orani(x, varsayilan=0.20):
    try:
        v = float(str(x).strip().replace(",", "."))
    except ValueError:
        return varsayilan
    if v > 1:
        v = v / 100
    return v if 0 <= v <= 0.5 else varsayilan


def normalle(tedarikci, df, harita, marj, sabit_ek, kritik_esik=0, stok_ust=50, bilgi=None):
    def kol(ad):
        k = harita.get(ad, "(yok)")
        if k == "(yok)" or k not in df.columns:
            return pd.Series([""] * len(df), index=df.index)
        return df[k]

    bilgi = bilgi or {}
    kontrol = bool(bilgi.get("doviz_kontrol"))
    kdv_ekle = bool(bilgi.get("kdv_ekle"))
    ozet = None
    bilinmeyen = pd.Series([False] * len(df), index=df.index)
    if kontrol or kdv_ekle:
        fk = harita.get("fiyat", "(yok)")
        if kontrol and str(fk).lower().endswith("_tl"):
            raise ValueError(f"Fiyat alani '{fk}' zaten TL karsiligi. Para birimi kontrolu icin ham fiyat alanini (ornek: urun_fiyat) secin.")
        alis = kol("fiyat").map(kesin_sayi)
    else:
        alis = kol("fiyat").map(sayi)
    if kontrol:
        dk = tahmin(df.columns, ["doviz", "currency", "para_birimi"])
        if dk not in df.columns:
            raise ValueError("XML'de para birimi alani (urun_doviz) bulunamadi. Alan gelmeden senkronizasyon yapilmaz.")
        cur = df[dk].astype(str).str.strip().str.upper()
        usd = cur.isin(DOVIZ_USD)
        tl = cur.isin(DOVIZ_TL)
        bilinmeyen = ~(usd | tl)
        kur = _f(bilgi.get("usd_kuru"))
        if usd.any() and kur <= 1:
            raise ValueError(f"{int(usd.sum())} urun USD ama dolar kuru girilmemis. Tedarikci ayarindan kuru yazin.")
        alis = alis.where(~usd, alis * kur)
        ozet = {
            "tl": int(tl.sum()), "usd": int(usd.sum()), "bilinmeyen": int(bilinmeyen.sum()),
            "bilinmeyen_degerler": cur[bilinmeyen].replace("", "(bos)").value_counts().head(5).to_dict(),
            "ornek_usd": [],
        }
    if kdv_ekle:
        kdk = tahmin(df.columns, ["kdv", "vat"])
        oran = df[kdk].map(kdv_orani) if kdk in df.columns else pd.Series([0.20] * len(df), index=df.index)
        alis = alis * (1 + oran)
    if ozet is not None:
        ozet["ornek_usd"] = [f"{str(r)[:60]} | {f:.2f} TL" for r, f in zip(kol("ad")[usd].head(3), alis[usd].head(3))]
    alis = alis.where(~bilinmeyen, 0.0)
    marj_s = kademeli_marj(alis, bilgi.get("kademe") if bilgi.get("kademe_aktif") else None, marj)
    satis = (alis * (1 + marj_s / 100) + sabit_ek).where(~bilinmeyen, 0.0)
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
        "urun_adi": kol("ad").map(ad_temizle),
        "stok": stok,
        "alis_fiyati": alis.round(2),
        "satis_fiyati": satis.round(2),
        "kategori": kategori,
    })
    out = out[(out["barkod"] != "") & (out["urun_adi"] != "")]
    out = out.drop_duplicates(subset=["barkod"], keep="first")
    if bilinmeyen.any():
        out.loc[out["barkod"].isin(kol("kod").astype(str).str.strip()[bilinmeyen]), "stok"] = 0
    out.attrs["doviz_ozet"] = ozet
    return out


def tedarikci_senkron(ad, bilgi, kritik_esik=0, stok_ust=50):
    df_ham = xml_oku(indir(bilgi["link"], _f(bilgi.get("zaman_asimi"), 300.0)))
    df = normalle(
        ad, df_ham, bilgi.get("harita", {}),
        float(bilgi.get("marj", 30.0)), float(bilgi.get("sabit_ek", 0.0)),
        kritik_esik, stok_ust, bilgi,
    )
    ozet = df.attrs.get("doviz_ozet")
    if ozet:
        DOVIZ_SON[ad] = ozet
        log_yaz(ad, "BILGI", f"Para birimi: TL={ozet['tl']}, USD={ozet['usd']}, belirsiz={ozet['bilinmeyen']}")
        if bilgi.get("usd_bekle") and ozet["usd"] == 0:
            raise ValueError("USD urun beklenirken hic USD urun gelmedi. Tedarikci para birimi alanini henuz duzeltmemis olabilir; senkronizasyon durduruldu, eski veri korundu.")
    if df.empty:
        raise ValueError("XML'den ge\u00e7erli \u00fcr\u00fcn \u00e7\u0131kmad\u0131. Alan e\u015fle\u015ftirmesini kontrol edin.")
    kilit = stok_sifir_kume(ayar_oku())
    if kilit:  # elle sifirlanan urunler tedarikci stogu gelse bile 0 kalir
        df.loc[df["barkod"].astype(str).isin(kilit), "stok"] = 0
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
# Fiyat kurallar\u0131 ve ortak yard\u0131mc\u0131lar
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


def objectid_mi(v):
    return bool(re.fullmatch(r"[0-9a-fA-F]{24}", str(v or "").strip()))


def gecerli_barkod(kod):
    k = str(kod).strip()
    return k if k.isdigit() and 8 <= len(k) <= 14 else None


def sabit_barkod(kod, uret=False):
    """Ayn\u0131 koddan her zaman ayn\u0131 barkodu \u00fcretir (Python hash() KULLANILMAZ)."""
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


def paketle(kayitlar, paket, fn, ilerleme=None, ad="", durdur=0):
    """kayitlar: [(anahtar, veri)]. fn(veri_listesi) -> (basarili_mi, mesaj).
    Her paketin sonucu GER\u00c7EK HTTP durumuna g\u00f6re say\u0131l\u0131r."""
    ok_k, hata_k, loglar = [], [], []
    ust_uste = 0
    toplam = max(1, -(-len(kayitlar) // paket))
    for no, i in enumerate(range(0, len(kayitlar), paket), 1):
        grup = kayitlar[i:i + paket]
        anahtarlar = [k for k, _ in grup]
        try:
            basari, mesaj = fn([v for _, v in grup])
        except Exception as e:
            basari, mesaj = False, f"\u0130stek hatas\u0131: {e}"
        if basari:
            ok_k += anahtarlar
            ust_uste = 0
            loglar.append(f"\u2705 {ad} paket {no}/{toplam}: {len(grup)} kay\u0131t. {mesaj}".strip())
        else:
            hata_k += anahtarlar
            ust_uste += 1
            loglar.append(f"\u274c {ad} paket {no}/{toplam}: {len(grup)} kay\u0131t BA\u015eARISIZ. {mesaj}".strip())
        if durdur and ust_uste >= durdur:
            kalan = len(kayitlar) - (i + len(grup))
            if kalan > 0:
                loglar.append(f"\u26d4 {ad}: \u00fcst \u00fcste {durdur} paket hata ald\u0131, g\u00f6nderim DURDURULDU. "
                              f"G\u00f6nderilmeyen kalan kay\u0131t: {kalan}. Hata mesaj\u0131n\u0131 d\u00fczeltip tekrar deneyin.")
                if ilerleme:
                    ilerleme(1.0, loglar)
                break
        if ilerleme:
            ilerleme(no / toplam, loglar)
    return ok_k, hata_k, loglar


def _sonuc(pid, ok_k, hata_k, loglar, atlanan=0):
    try:
        pazar_isaretle(pid, ok_k, hata_k)
    except Exception:
        pass
    if atlanan:
        loglar.append(f"\u2139\ufe0f {atlanan} \u00fcr\u00fcn eksik bilgi (fiyat/barkod) nedeniyle atland\u0131.")
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
        raise ValueError("N11 i\u00e7in 'Kargo \u015fablonu' ayar\u0131 bo\u015f. Genel Ayarlar'dan girin.")
    liste, atlanan = [], 0
    for r in kayit_listesi(df):
        gorsel = str(r.get("gorsel", "")).strip()
        kod = str(r["barkod"]).strip()
        fiyat = round(_f(r.get("satis_fiyati")), 2)
        cat = _i(kat_sec(pa, ayar, r.get("kategori"), "n11"))
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

    ok_k, hata_k, loglar = paketle(kayit, 100, gonder, ilerleme, "N11", durdur=3)
    return len(ok_k), len(hata_k), loglar


# --------------------------------------------------------------------------
# \u0130defix
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

    ok_k, hata_k, loglar = paketle(kayit, 500, gonder, ilerleme, "\u0130defix")
    return _sonuc("idefix", ok_k, hata_k, loglar, atlanan)


def idefix_urun_listesi(df, ayar):
    pa = pa_al(ayar, "idefix")
    brand = _i(pa.get("brand_id"))
    if brand <= 0:
        raise ValueError("\u0130defix i\u00e7in 'Marka ID' ayar\u0131 bo\u015f. Genel Ayarlar'dan girin.")
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
        cat = _i(kat_sec(pa, ayar, r.get("kategori"), "idefix"))
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

    ok_k, hata_k, loglar = paketle(kayit, 100, gonder, ilerleme, "\u0130defix", durdur=3)
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
            return True, "\u2705 Hepsiburada giri\u015fi ba\u015far\u0131l\u0131."
    return False, "\u274c Hepsiburada giri\u015fi reddedildi (kullan\u0131c\u0131 ad\u0131 / servis anahtar\u0131 / merchant ID kontrol edin)."


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
    """\u00dcr\u00fcn olu\u015fturma adresi: yaln\u0131zca https + hepsiburada.com alan ad\u0131 (kimlik bilgisi ba\u015fka siteye s\u0131zmas\u0131n)."""
    u = str(pa_al(ayar, "hb").get("urun_endpoint", "") or "").strip()
    if not u:
        raise ValueError("Hepsiburada '\u00dcr\u00fcn olu\u015fturma adresi' bo\u015f. Hepsiburada API dok\u00fcman\u0131ndaki tam adresi Genel Ayarlar'dan girin.")
    pr = urllib.parse.urlparse(u)
    host = (pr.hostname or "").lower()
    if pr.scheme != "https" or not (host == "hepsiburada.com" or host.endswith(".hepsiburada.com")):
        raise ValueError("Hepsiburada \u00fcr\u00fcn olu\u015fturma adresi https:// ile ba\u015flamal\u0131 ve hepsiburada.com alan ad\u0131nda olmal\u0131.")
    if not pr.path.rstrip("/").endswith("/products/import"):
        raise ValueError("Hepsiburada \u00fcr\u00fcn olu\u015fturma adresi \u015fu \u015fekilde bitmeli: https://mpop.hepsiburada.com/product/api/products/import")
    return u


def hb_ek_ozellikler(pa):
    """Ayarlardaki ek ozellikleri sozluge cevirir ({"renk_variant_property": "Siyah"} ya da [{"name":..,"value":..}])."""
    ek = pa.get("ek_ozellik")
    if isinstance(ek, dict):
        return {str(k): v for k, v in ek.items()}
    if isinstance(ek, list):
        return {str(x.get("name") or x.get("slug")): x.get("value") for x in ek
                if isinstance(x, dict) and (x.get("name") or x.get("slug"))}
    return {}


def hb_fiyat_metni(fiyat):
    """Dokumandaki ornege gore ondalik ayraci virgul: 130,50"""
    return f"{round(float(fiyat), 2):.2f}".replace(".", ",")


def hb_urun_listesi(df, ayar):
    """Hepsiburada 'Urun Bilgisi Gonderme' (POST /product/api/products/import) bicimi:
    [{categoryId, merchant, attributes:{merchantSku, VaryantGroupID, Barcode, UrunAdi, UrunAciklamasi, Marka,
    GarantiSuresi, kg, tax_vat_rate, price, stock, Image1..}}] -- dosya (integrator.json) olarak yuklenir."""
    hb_urun_adresi(ayar)
    pa = pa_al(ayar, "hb")
    merchant = kimlik(ayar, "hb_merchant_id")
    if not merchant:
        raise ValueError("Hepsiburada Merchant ID kay\u0131tl\u0131 de\u011fil.")
    marka = str(pa.get("marka", "") or "").strip()
    if not marka:
        raise ValueError("Hepsiburada i\u00e7in Marka ad\u0131 gerekli (Genel Ayarlar > Marka ad\u0131).")
    ek = hb_ek_ozellikler(pa)
    onek = str(pa.get("sku_prefix", "") or "")
    kdv = _i(pa.get("kdv"), 20)
    garanti = _i(pa.get("garanti"), 24)
    kg = _f(pa.get("kg"), 1.0) or 1.0
    uret = bool(pa.get("gecici_barkod", True))
    liste, atlanan = [], 0
    for r in kayit_listesi(df):
        gorsel = str(r.get("gorsel", "")).strip()
        kod = str(r["barkod"]).strip()
        barkod = sabit_barkod(kod, uret)
        fiyat = round(_f(r.get("satis_fiyati")), 2)
        cat = kat_sec(pa, ayar, r.get("kategori"), "hb")
        if not gorsel.startswith("https") or fiyat <= 0 or not barkod or not cat:
            atlanan += 1
            continue
        ad = str(r["urun_adi"]).strip()
        sku = onek + kod
        oz = {
            "merchantSku": sku, "VaryantGroupID": "VG-" + sku, "Barcode": barkod,
            "UrunAdi": ad[:200], "UrunAciklamasi": ad, "Marka": marka, "GarantiSuresi": garanti,
            "kg": str(kg).rstrip("0").rstrip(".") if "." in str(kg) else str(kg),
            "tax_vat_rate": str(kdv), "price": hb_fiyat_metni(fiyat),
            "stock": str(max(_i(r.get("stok")), 0)), "Image1": gorsel,
        }
        for k, v in ek.items():
            oz.setdefault(k, v)
        liste.append({"categoryId": int(cat) if str(cat).isdigit() else cat, "merchant": merchant, "attributes": oz})
    return liste, atlanan


def hb_urun_gonder(ayar, liste, ilerleme=None):
    url = hb_urun_adresi(ayar)
    kayit = [(u["attributes"]["merchantSku"], u) for u in liste]
    baslik = {k: v for k, v in hb_header(ayar).items() if k.lower() != "content-type"}  # multipart sinirini requests koyar

    def gonder(grup):
        govde = json.dumps(grup, ensure_ascii=False).encode("utf-8")
        r = http("POST", url, files={"file": ("integrator.json", govde, "application/json")},
                 headers=baslik, timeout=120, tries=2)
        ok = r.status_code in (200, 201, 202)
        ozet = yanit_ozet(r)
        if ok:
            t = re.search(r'"trackingId"\s*:\s*"([^"]+)"', r.text or "")
            if t:
                log_yaz("Hepsiburada", "OK", f"\u00dcr\u00fcn y\u00fckleme izleme kodu: {t.group(1)}")
                ozet += f" | izleme kodu: {t.group(1)}"
        return ok, ozet

    ok_k, hata_k, loglar = paketle(kayit, 100, gonder, ilerleme, "Hepsiburada", durdur=3)
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
PTT_URUN_YOLU = "products/upsert"  # PTT dok\u00fcman\u0131: POST /api/v1/products/upsert (\u00dcr\u00fcn Ekleme G\u00fcncelleme)


def ptt_header(ayar):
    """PTT dok\u00fcman\u0131: Api-Key, access-token ve X-Correlation-Id zorunlu (her istekte yeni benzersiz de\u011fer)."""
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
            return True, f"\u2705 PTT AVM ba\u011flant\u0131s\u0131 ba\u015far\u0131l\u0131 (HTTP {r.status_code})"
        return False, f"\u274c PTT AVM ba\u011flant\u0131s\u0131 ba\u015far\u0131s\u0131z ({yanit_ozet(r)})"
    except Exception as e:
        return False, f"Ba\u011flant\u0131 hatas\u0131: {e}"


def ptt_yanit_kontrol(r):
    """HTTP durumu + (varsa) yan\u0131ttaki success=false / message bilgisi. D\u00f6n\u00fc\u015f: (basarili, mesaj)."""
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
    """PTT 'Fiyat Stok G\u00fcncelle': POST /products/stock-prices (en \u00e7ok 1000 \u00fcr\u00fcn/istek; ayn\u0131 istek 5 dk i\u00e7inde
    tekrar g\u00f6nderilemez; ayn\u0131 barkod bir istekte tek kez; KDV dahil fiyat 1'den b\u00fcy\u00fck olmal\u0131)."""
    if not (kimlik(ayar, "ptt_key") and kimlik(ayar, "ptt_token")):
        raise RuntimeError("PTT API Key / Token eksik.")
    uret = bool(pa_al(ayar, "ptt").get("gecici_barkod", True))
    tekil, atlanan = {}, 0
    for r in kayit_listesi(df):
        fiyat = round(_f(r.get("satis_fiyati")), 2)
        if fiyat <= 1:  # fiyat\u0131 yoksa al\u0131\u015f fiyat\u0131yla G\u00d6NDERME; PTT KDV dahil fiyat\u0131n 1'den b\u00fcy\u00fck olmas\u0131n\u0131 ister
            atlanan += 1
            continue
        ptt_b = sabit_barkod(str(r["barkod"]).strip(), uret)  # \u00fcr\u00fcn olu\u015ftururken kullan\u0131lan barkodla ayn\u0131
        if not ptt_b or len(ptt_b) > 250:
            atlanan += 1
            continue
        tekil[ptt_b] = (str(r["barkod"]), {"barcode": ptt_b, "quantity": max(_i(r.get("stok")), 0), "priceWithVAT": fiyat})
    kayit = list(tekil.values())  # ayn\u0131 barkod tek kez (sonuncusu)
    izler = []

    def gonder(grup):
        # tries=1: PTT ayn\u0131 iste\u011fin 5 dk i\u00e7inde tekrar\u0131n\u0131 reddeder; otomatik yeniden deneme anlams\u0131z
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
        loglar.append("\u2139\ufe0f PTT ayn\u0131 iste\u011fi 5 dakika i\u00e7inde tekrar kabul etmez; hata ald\u0131ysan\u0131z 5 dk bekleyip tekrar deneyin.")
    return _sonuc("ptt", ok_k, hata_k, loglar, atlanan)


def ptt_urun_listesi(df, ayar):
    """PTT AVM '\u00dcr\u00fcn Ekleme G\u00fcncelleme' (POST /products/upsert) \u2014 varyants\u0131z \u00fcr\u00fcn.
    Alan adlar\u0131 PTT dok\u00fcman\u0131ndaki \u00f6rnek istekten al\u0131nm\u0131\u015ft\u0131r. Do\u011frulanamayanlar (hangi alan zorunlu,
    KDV'li/KDV'siz fiyat kural\u0131) i\u00e7in \u00f6nce 'Tek \u00fcr\u00fcn (Test)' ile deneyip sonucu sorgulay\u0131n."""
    pa = pa_al(ayar, "ptt")
    cat_varsayilan = str(pa.get("category_id", "") or "").strip()
    if cat_varsayilan and not cat_varsayilan.isdigit():
        raise ValueError(f"PTT 'Varsay\u0131lan kategori ID' bir SAYI olmal\u0131 (\u00f6rn. 55) ama \u015fu yaz\u0131lm\u0131\u015f: '{cat_varsayilan[:60]}'. "
                         "Genel Ayarlar'dan d\u00fczeltin.")
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
        cat = kat_sec(pa, ayar, r.get("kategori"), "ptt")
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
        if gecerli_barkod(kod):  # yaln\u0131zca ger\u00e7ek barkodlarda GTIN/EAN g\u00f6nder
            u["ean"] = kod
            u["gtin"] = kod
        if marka:
            u["brand"] = marka
        if kargo:
            u["cargoProfileId"] = int(kargo) if kargo.isdigit() else kargo
        liste.append(u)
    return liste, atlanan


def ptt_tracking_id(r):
    """Yan\u0131ttaki trackingId'yi (b\u00fcy\u00fck/k\u00fc\u00e7\u00fck harf fark etmeksizin) bulur."""
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

    ok_k, hata_k, loglar = paketle(kayit, 25, gonder, ilerleme, "PTT", durdur=3)
    try:
        ptt_takip_kaydet(ayar, izler)
    except Exception:
        pass
    return len(ok_k), len(hata_k), loglar


def ptt_kategori_agaci(ayar):
    """PTT 'Kategori A\u011fac\u0131': GET /categories/category-tree."""
    r = http("GET", f"{PTT_BASE}/categories/category-tree", headers=ptt_header(ayar), timeout=90, tries=2)
    if r.status_code != 200:
        raise RuntimeError(f"Kategori a\u011fac\u0131 al\u0131namad\u0131 ({yanit_ozet(r)})")
    j = r.json()
    if isinstance(j, dict) and j.get("success") is False:
        ayrinti = j.get("error") or {k: v for k, v in j.items() if k != "category_tree"}
        raise RuntimeError("PTT kategori a\u011fac\u0131n\u0131 vermedi. PTT'nin yan\u0131t\u0131: " + json.dumps(ayrinti, ensure_ascii=False)[:800])
    return j


def ptt_kategori_duzlestir(veri):
    """Yan\u0131t bi\u00e7imi dok\u00fcmanda g\u00f6r\u00fcnmedi\u011fi i\u00e7in toleransl\u0131 okur: id+ad ta\u015f\u0131yan d\u00fc\u011f\u00fcmleri ve alt listelerini gezer."""
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


def ptt_kategori_getir(ayar, yol):
    """PTT kategori u\u00e7lar\u0131: 'main' (Ana Kategori Listesi) veya bir kategori ID'si (Kategori Bilgisi)."""
    yol = str(yol or "").strip()
    if yol != "main" and not yol.isdigit():
        raise ValueError("Kategori ID bir say\u0131 olmal\u0131.")
    r = http("GET", f"{PTT_BASE}/categories/{yol}", headers=ptt_header(ayar), timeout=60, tries=1)
    try:
        j = r.json()
    except Exception:
        j = None
    return r.status_code, j, (r.text or "")[:1500]


def ptt_kategori_gez():
    """A\u011fa\u00e7 \u00e7al\u0131\u015fmazsa: ana kategorilerden ba\u015flay\u0131p ID ile alt kategorilere inerek gezme."""
    st.markdown("**Ana kategorilerden gezerek bul**")
    c1, c2 = st.columns(2)
    istek = None
    if gen(c1.button, "\U0001f4c2 Ana kategorileri getir", key="ptt_kat_main"):
        istek = "main"
    hedef = c2.text_input("Kategori ID (i\u00e7indekileri g\u00f6rmek i\u00e7in)", key="ptt_kat_gez_id")
    if gen(c2.button, "\u27a1\ufe0f Bu kategoriyi a\u00e7", key="ptt_kat_ac"):
        istek = hedef
    if istek is not None:
        try:
            kod, j, ham = ptt_kategori_getir(ayarlar, istek)
            st.session_state["ptt_kat_gez"] = {
                "yol": str(istek), "kod": kod, "ham": ham,
                "liste": ptt_kategori_duzlestir(j) if j is not None else [],
                "json": j,
            }
        except Exception as e:
            st.session_state["ptt_kat_gez"] = None
            st.error(f"Hata: {e}")
    g = st.session_state.get("ptt_kat_gez")
    if not g:
        return
    (st.success if g["kod"] == 200 else st.error)(f"'{g['yol']}' i\u00e7in PTT yan\u0131t\u0131: HTTP {g['kod']}")
    if g["liste"]:
        d = pd.DataFrame(g["liste"]).head(300)
        st.dataframe(d[["ID", "Kategori"]], hide_index=True)
        secenek = [f"{r.ID} \u2014 {r.Kategori}" for r in d.itertuples()]
        sec = st.selectbox("Bu listeden se\u00e7", secenek, key="ptt_kat_gez_sec")
        k1, k2 = st.columns(2)
        if gen(k1.button, "\U0001f4c2 Se\u00e7ileni a\u00e7 (alt kategorileri)", key="ptt_kat_gez_ac"):
            st.session_state["ptt_kat_gez_id"] = sec.split(" \u2014 ")[0].strip()
            st.rerun()
        if gen(k2.button, "\u2705 Se\u00e7ileni varsay\u0131lan yap", key="ptt_kat_gez_varsayilan"):
            secilen = sec.split(" \u2014 ")[0].strip()
            varsayilan_kategori_yaz("ptt", secilen)
    else:
        st.warning("Listede kategori okunamad\u0131; ham yan\u0131t\u0131 a\u015fa\u011f\u0131dan inceleyebilirsiniz.")
    with st.expander("Ham yan\u0131t"):
        if g.get("json") is not None:
            st.json(g["json"])
        else:
            st.text(g["ham"])


def ptt_kategori_bulucu():
    if not pazar_bagli(ayarlar, "ptt"):
        st.caption("Kategori aramak i\u00e7in \u00f6nce PTT API bilgilerini kaydedin.")
        return
    ptt_kategori_gez()
    st.divider()
    st.markdown("**T\u00fcm kategori a\u011fac\u0131 (PTT bu hesapta hata verebilir)**")
    if gen(st.button, "\U0001f4e5 Kategorileri PTT'den y\u00fckle", key="ptt_kat_yukle"):
        try:
            with st.spinner("PTT kategori a\u011fac\u0131 al\u0131n\u0131yor..."):
                veri = ptt_kategori_agaci(ayarlar)
            st.session_state["ptt_kat_ham"] = json.dumps(veri, ensure_ascii=False)[:60000]
            st.session_state["ptt_kat"] = ptt_kategori_duzlestir(veri)
        except Exception as e:
            st.error(f"Hata: {e}")
    kat = st.session_state.get("ptt_kat")
    if kat is None:
        return
    if not kat:
        st.warning("Kategori listesi okunamad\u0131. A\u015fa\u011f\u0131daki ham yan\u0131t\u0131n ilk k\u0131sm\u0131n\u0131 bana g\u00f6nderin, okuyucuyu ona g\u00f6re d\u00fczelteyim.")
        ham = str(st.session_state.get("ptt_kat_ham", ""))[:3000]
        try:
            st.json(json.loads(ham))
        except Exception:
            st.text(ham)
        return
    ara = st.text_input("Kategori ara (\u00f6rn. elbise)", key="ptt_kat_ara")
    yaprak = st.checkbox("Sadece en alt (yaprak) kategoriler", value=True, key="ptt_kat_yaprak")
    d = pd.DataFrame(kat)
    if yaprak:
        d = d[~d["Alt kategorisi var"]]
    if ara.strip():
        d = d[d["Kategori"].map(tr_norm).str.contains(tr_norm(ara.strip()), regex=False)]
    st.caption(f"{len(d):,} sonu\u00e7" + (" (ilk 300 g\u00f6steriliyor)" if len(d) > 300 else ""))
    d = d.head(300)
    st.dataframe(d[["ID", "Kategori"]], hide_index=True)
    secenek = [f"{r.ID} \u2014 {r.Kategori}" for r in d.itertuples()]
    if secenek:
        sec = st.selectbox("Varsay\u0131lan yapmak istedi\u011finiz kategori", secenek, key="ptt_kat_sec")
        if gen(st.button, "\u2705 Bunu varsay\u0131lan kategori yap", key="ptt_kat_varsayilan"):
            secilen_id = sec.split(" \u2014 ")[0].strip()
            pa_al(ayarlar, "ptt")["category_id"] = secilen_id
            ayar_yaz(ayarlar)
            st.success(f"Varsay\u0131lan kategori ID: {secilen_id}")


def ptt_sonuc_ozet(metin):
    """PTT tracking-result yan\u0131t\u0131n\u0131 (dok\u00fcmandaki \u00f6rnek bi\u00e7im) okunur \u00f6zete \u00e7evirir."""
    try:
        j = json.loads(metin)
    except Exception:
        return None
    if not isinstance(j, dict):
        return None
    d = j.get("data") if isinstance(j.get("data"), dict) and ("productsSubTrackingResult" in j["data"] or "status" in j["data"]) else j
    alt = d.get("productsSubTrackingResult") or {}
    ozet = (f"Durum: {d.get('status')} | \u0130lerleme: {d.get('progress')} | Toplam: {alt.get('countOfTotalProducts')} | "
            f"Bekleyen: {alt.get('countOfWaitingProducts')} | \u0130\u015flenen: {alt.get('countOfInProgressProducts')} | "
            f"Tamamlanan: {alt.get('countOfCompletedProducts')} | \u0130ptal/hatal\u0131: {alt.get('countOfCancelledProducts')}")
    satirlar = []
    for b in (alt.get("productBasedInfos") or [])[:200]:
        if not isinstance(b, dict):
            continue
        neden = "; ".join(str(x) for x in (b.get("failureReasons") or []))
        satirlar.append({"Barkod": b.get("barcode"), "Durum": b.get("status"), "Mesaj": b.get("message"), "Hata nedenleri": neden})
    return {"ozet": ozet, "satirlar": satirlar}


def ptt_sonuc_sorgula(ayar, takip_id):
    """PTT '\u00dcr\u00fcn G\u00fcncelleme Kontrol': POST /products/tracking-result/{trackingId}. D\u00f6n\u00fc\u015f: (http_durum, metin)."""
    tid = str(takip_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,100}", tid):
        raise ValueError("Ge\u00e7ersiz trackingId.")
    r = http("POST", f"{PTT_BASE}/products/tracking-result/{tid}", headers=ptt_header(ayar), timeout=30, tries=2)
    return r.status_code, r.text[:4000]


# --------------------------------------------------------------------------
# Trendruum
# --------------------------------------------------------------------------
TR_BASE = "https://api.trendruum.com/api/v1/integration"


def trendruum_token(key, secret):
    r = requests.post(
        f"{TR_BASE}/auth/login",
        json={"client_id": key.strip(), "client_secret": secret.strip()}, timeout=30,
    )
    try:
        j = r.json()
    except Exception:
        j = {}
    token = (j.get("data") or {}).get("token") or j.get("token") or ""
    if r.status_code != 200 or not token:
        raise RuntimeError(f"Trendruum giri\u015fi ba\u015far\u0131s\u0131z (HTTP {r.status_code})")
    return token


def trendruum_siparisler(ayar):
    key, secret = kimlik(ayar, "trendruum_key"), kimlik(ayar, "trendruum_secret")
    if not key or not secret:
        return []
    token = trendruum_token(key, secret)
    r = http("GET", f"{TR_BASE}/orders", headers={"Authorization": f"Bearer {token}"}, timeout=30)
    r.raise_for_status()
    j = r.json()
    return j.get("data") or j.get("orders") or []


def trendruum_ayar(ayar):
    pa = pa_al(ayar, "trendruum")
    brand = pa.get("brand_id") or kimlik(ayar, "trendruum_brand")
    cat = pa.get("category_id") or kimlik(ayar, "trendruum_category")
    uret = bool(pa.get("gecici_barkod", True))
    return str(brand or "").strip(), str(cat or "").strip(), uret, _i(pa.get("kdv"), 20)


def trendruum_urun_listesi(df, ayar):
    pa = pa_al(ayar, "trendruum")
    brand, cat_varsayilan, uret, kdv = trendruum_ayar(ayar)
    if not objectid_mi(brand):
        raise ValueError("Trendruum 'Marka ID' ge\u00e7ersiz/bo\u015f (24 karakterlik ID olmal\u0131). Genel Ayarlar'dan girin.")
    liste, atlanan = [], 0
    for r in kayit_listesi(df):
        gorsel = str(r.get("gorsel", "")).strip()
        kod = str(r["barkod"]).strip()
        barkod = sabit_barkod(kod, uret)
        fiyat = _f(r.get("satis_fiyati"))
        cat = kat_sec(pa, ayar, r.get("kategori"), "trendruum")
        if not gorsel or fiyat <= 0 or not barkod or not objectid_mi(cat):
            atlanan += 1
            continue
        liste.append({
            "name": str(r["urun_adi"]), "model_code": kod, "category_id": cat, "brand_id": brand,
            "children_products": [{
                "barcode": barkod, "stock_code": kod, "price": fiyat,
                "stock": max(_i(r.get("stok")), 0), "tax": kdv, "images": [gorsel],
            }],
        })
    return liste, atlanan


def trendruum_kategori_duzlestir(j):
    """GET /categories yanitini (liste ya da {data:[...]}, ic ice sub_categories) duz listeye cevirir."""
    if isinstance(j, dict):
        for a in ("data", "categories", "items", "results"):
            if isinstance(j.get(a), list):
                j = j[a]
                break
        else:
            j = [j]
    cikti, goruldu = [], set()

    def gez(dugum):
        if not isinstance(dugum, dict):
            return
        cid = str(dugum.get("id") or dugum.get("_id") or "").strip()
        alt = dugum.get("sub_categories")
        if objectid_mi(cid) and cid not in goruldu:
            goruldu.add(cid)
            ad = str(dugum.get("name") or "")
            cikti.append({
                "ID": cid, "Kategori": str(dugum.get("full_path") or ad),
                "Uc kategori": "evet" if not alt else "hayir",
            })
        for a in (alt or []):
            gez(a)

    for d in (j if isinstance(j, list) else []):
        gez(d)
    return cikti


def trendruum_kategori_ara(ayar, ad, limit=300):
    ad = str(ad or "").strip()
    if len(ad) < 2:
        raise ValueError("Aramak icin en az 2 harf yazin.")
    token = trendruum_token(kimlik(ayar, "trendruum_key"), kimlik(ayar, "trendruum_secret"))
    r = http("GET", f"{TR_BASE}/categories", params={"name": ad, "limit": int(limit)},
             headers={"Authorization": f"Bearer {token}"}, timeout=60, tries=1)
    try:
        j = r.json()
    except Exception:
        j = None
    return r.status_code, j, (r.text or "")[:1500]


def trendruum_kategori_sema(ayar, cid):
    """GET /categories/{id}: kategorinin ozellik ve varyant semasi."""
    if not objectid_mi(cid):
        raise ValueError("Kategori ID 24 karakterlik olmali.")
    token = trendruum_token(kimlik(ayar, "trendruum_key"), kimlik(ayar, "trendruum_secret"))
    r = http("GET", f"{TR_BASE}/categories/{cid}", headers={"Authorization": f"Bearer {token}"}, timeout=60, tries=1)
    try:
        j = r.json()
    except Exception:
        j = None
    return r.status_code, j


def kat_belirtec(t):
    """Turkce-guvenli, ekleri kabaca kirpilmis kelime kumesi (ilk 5 harf)."""
    m = tr_norm(t).translate(str.maketrans("\u00e7\u011f\u00f6\u015f\u00fc", "cgosu"))
    dur = {"ve", "ile", "icin", "diger"}
    return {w[:5] for w in re.findall(r"[a-z0-9]+", m) if len(w) > 1 and w not in dur}


def trendruum_agac_yukle(ayar):
    """GET /categories?limit=5000 -> uc kategorilerin duz listesi (tek istek)."""
    token = trendruum_token(kimlik(ayar, "trendruum_key"), kimlik(ayar, "trendruum_secret"))
    r = http("GET", f"{TR_BASE}/categories", params={"limit": 5000},
             headers={"Authorization": f"Bearer {token}"}, timeout=120, tries=2)
    if r.status_code != 200:
        raise RuntimeError(f"Trendruum kategori listesi alinamadi (HTTP {r.status_code})")
    try:
        j = r.json()
    except Exception:
        raise RuntimeError("Trendruum kategori yaniti okunamadi.")
    dugumler = []
    for d in trendruum_kategori_duzlestir(j):
        if d["Uc kategori"] != "evet":
            continue
        son = d["Kategori"].split(">")[-1]
        dugumler.append({"ID": d["ID"], "yol": d["Kategori"], "son": kat_belirtec(son), "tum": kat_belirtec(d["Kategori"])})
    if not dugumler:
        raise RuntimeError("Trendruum kategori listesi bos geldi.")
    return dugumler


def kategori_oner(ted_yol, dugumler):
    """Tedarikci kategorisine en yakin Trendruum uc kategorisi: (ID, yol, guven)."""
    parcalar = [x.strip() for x in re.split(r"[>/|]+", str(ted_yol)) if x.strip()]
    if not parcalar:
        return "", "", "yok"
    sl, st_ = kat_belirtec(parcalar[-1]), kat_belirtec(ted_yol)
    en, en_puan, en_son = None, 0.0, 0.0
    for d in dugumler:
        u = sl | d["son"]
        son_sim = len(sl & d["son"]) / len(u) if u else 0.0
        u2 = st_ | d["tum"]
        tum_sim = len(st_ & d["tum"]) / len(u2) if u2 else 0.0
        puan = 0.65 * son_sim + 0.35 * tum_sim
        if puan > en_puan or (puan == en_puan and en and len(d["yol"]) < len(en["yol"])):
            en, en_puan, en_son = d, puan, son_sim
    if not en or en_puan < 0.3:
        return "", "", "yok"
    guven = "yuksek" if (en_son >= 0.8 and en_puan >= 0.6) else ("orta" if en_son >= 0.5 else "dusuk")
    return en["ID"], en["yol"], guven


def kategori_siralama(liste, aranan):
    """Aranan ada en yakin (son parcasi kisa ve aranani iceren) uc kategorileri uste alir."""
    q = tr_norm(aranan).strip()

    def anahtar(k):
        son = tr_norm(k["Kategori"].split(">")[-1]).strip()
        icerir = all(w in son for w in q.split()) if q else False
        uc = 0 if k.get("Uc kategori", "evet") == "evet" else 1
        return (0 if icerir else 1, uc, abs(len(son) - len(q)), len(k["Kategori"]))

    return sorted(liste, key=anahtar)


def kategoriye_ata_paneli(pid, secilen):
    """Bulucuda secilen pazar yeri kategorisini, bir tedarikci kategorisine tek tikla atar."""
    bilgi = st.session_state.pop(f"ata_bilgi_{pid}", None)
    if bilgi:
        st.success(bilgi)
    df = urunleri_oku()
    if df.empty or "kategori" not in df.columns:
        return
    ana = df["kategori"].dropna().astype(str).map(lambda k: k.split(">>>")[0].strip())
    adet = ana[ana != ""].value_counts()
    if adet.empty:
        return
    mevcut = (pa_al(ayarlar, pid).get("kategori_eslesme") or {})
    isaret = " \u2713"
    etiket = {}
    for k in adet.index:
        etiket[f"{k} ({int(adet[k])} \u00fcr\u00fcn){isaret if mevcut.get(k) else ''}"] = k
    sec = st.selectbox("Bu kategoriyi \u015fu tedarik\u00e7i kategorisine ata", list(etiket), key=f"ata_sec_{pid}")
    if gen(st.button, "Se\u00e7ili kategoriyi bu tedarik\u00e7i kategorisine ata", key=f"ata_btn_{pid}"):
        k = etiket[sec]
        yeni = dict(mevcut)
        yeni[k] = str(secilen)
        pa_al(ayarlar, pid)["kategori_eslesme"] = yeni
        ayar_yaz(ayarlar)
        st.session_state[f"ata_bilgi_{pid}"] = f"'{k}' kategorisi art\u0131k {secilen} ID'sine e\u015fle\u015fti. \u00d6nceki g\u00f6nderilmi\u015f \u00fcr\u00fcnler de\u011fi\u015fmez; gerekirse silip yeniden g\u00f6nderin."
        st.rerun()


def trendruum_kategori_bulucu():
    if not pazar_bagli(ayarlar, "trendruum"):
        st.caption("Kategori aramak icin once Trendruum API bilgilerini kaydedin.")
        return
    st.caption("Urun tipini yazin (ornek: laptop, kulaklik, tencere). 'Uc kategori = evet' olanlari secin.")
    c1, c2 = st.columns([3, 1])
    ad = c1.text_input("Kategori adi", key="trk_ara_ad")
    if gen(c2.button, "Ara", key="trk_ara_btn"):
        try:
            kod, j, ham = trendruum_kategori_ara(ayarlar, ad)
            st.session_state["trk_sonuc"] = {
                "kod": kod, "ham": ham, "json": j,
                "liste": kategori_siralama(trendruum_kategori_duzlestir(j), ad) if j is not None else [],
            }
        except Exception as e:
            st.session_state["trk_sonuc"] = None
            st.error(f"Hata: {e}")
    g = st.session_state.get("trk_sonuc")
    if not g:
        return
    if g["kod"] != 200:
        st.error(f"Trendruum yaniti: HTTP {g['kod']}")
    if not g["liste"]:
        st.warning("Sonuc bulunamadi; farkli bir kelime deneyin.")
        with st.expander("Ham yanit"):
            st.text(g["ham"])
        return
    d = pd.DataFrame(g["liste"]).head(200)
    st.caption(f"{len(g['liste'])} sonu\u00e7; aranan ada en yak\u0131n olanlar \u00fcstte.")
    st.dataframe(d, hide_index=True)
    secenek = [f"{r.ID} \u2014 {r.Kategori}" for r in d.itertuples()]
    sec = st.selectbox("Listeden sec", secenek, key="trk_sec")
    secilen = sec.split(" \u2014 ")[0].strip()
    mevcut_vk = pa_al(ayarlar, "trendruum").get("category_id") or "(bo\u015f)"
    st.caption(f"\u015eu an kay\u0131tl\u0131 varsay\u0131lan kategori ID: {mevcut_vk}")
    kategoriye_ata_paneli("trendruum", secilen)
    k1, k2 = st.columns(2)
    if gen(k1.button, "Varsayilan kategori yap", key="trk_varsayilan"):
        varsayilan_kategori_yaz("trendruum", secilen)
    if gen(k2.button, "Bu kategorinin zorunlu alanlari", key="trk_sema"):
        try:
            kod, j = trendruum_kategori_sema(ayarlar, secilen)
            st.session_state["trk_sema_sonuc"] = (secilen, kod, j)
        except Exception as e:
            st.error(f"Hata: {e}")
    sm = st.session_state.get("trk_sema_sonuc")
    if sm and sm[0] == secilen:
        j = sm[2] if isinstance(sm[2], dict) else {}
        j = j.get("data") if isinstance(j.get("data"), dict) else j
        st.caption(f"Yanit: HTTP {sm[1]}")
        for baslik, anahtar in (("Ozellikler", "attributes"), ("Varyantlar", "variants")):
            for x in (j.get(anahtar) or []):
                if isinstance(x, dict):
                    st.write(f"- {baslik}: {x.get('name')} ({x.get('slug')})" + (" - ZORUNLU" if x.get("required") else ""))


def trendruum_gonder(ayar, liste, ilerleme=None):
    token = trendruum_token(kimlik(ayar, "trendruum_key"), kimlik(ayar, "trendruum_secret"))
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    kayit = [(u["model_code"], u) for u in liste]

    def gonder(grup):
        r = http("POST", f"{TR_BASE}/products/bulk", json={"products": grup}, headers=h, timeout=60, tries=2)
        return r.status_code in (200, 201, 202), yanit_ozet(r)

    ok_k, hata_k, loglar = paketle(kayit, 50, gonder, ilerleme, "Trendruum", durdur=3)
    return len(ok_k), len(hata_k), loglar


def trendruum_guncelle(ayar, df, ilerleme=None):
    token = trendruum_token(kimlik(ayar, "trendruum_key"), kimlik(ayar, "trendruum_secret"))
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    _, _, uret, _ = trendruum_ayar(ayar)
    kayit, atlanan = [], 0
    for r in kayit_listesi(df):
        fiyat = _f(r.get("satis_fiyati"))
        sb = sabit_barkod(r["barkod"], uret)
        if fiyat <= 0 or not sb:
            atlanan += 1
            continue
        kayit.append((str(r["barkod"]), {"barcode": sb, "price": fiyat, "stock": max(_i(r.get("stok")), 0)}))

    def gonder(grup):
        r = http("POST", f"{TR_BASE}/products/bulk-update", json={"products": grup}, headers=h, timeout=120)
        if r.status_code != 200:
            return False, yanit_ozet(r)
        try:
            d = r.json().get("data") or {}
        except Exception:
            d = {}
        guncel = d.get("updated_count")
        return True, f"g\u00fcncellenen: {guncel if guncel is not None else len(grup)}"

    ok_k, hata_k, loglar = paketle(kayit, 1000, gonder, ilerleme, "Trendruum")
    return _sonuc("trendruum", ok_k, hata_k, loglar, atlanan)


def kat_sec(pa, ayar, kategori, pid):
    """Eslesmis kategori ID'si; yoksa varsayilan SADECE 'varsayilan kategoriyi kullan' acikken."""
    v = kategori_id(pa, ayar, kategori, pid)
    if v:
        return v
    if pa.get("varsayilan_kategori_kullan"):
        return str(pa.get("category_id") or "").strip()
    return ""


def kategori_id(pa, ayar, kategori, pid):
    ana = str(kategori or "").split(">>>")[0].strip()
    v = (pa.get("kategori_eslesme") or {}).get(ana)
    if not v and pid == "trendruum":  # eski s\u00fcr\u00fcmden kalan e\u015fle\u015ftirme
        v = (ayar.get("kategori_eslesme") or {}).get(ana)
    return str(v).strip() if v else ""


# --------------------------------------------------------------------------
# G\u00f6nderim orkestrasyonu
# --------------------------------------------------------------------------
GUNCELLEYICI = {
    "trendruum": trendruum_guncelle, "trendyol": trendyol_guncelle, "hb": hb_guncelle,
    "n11": n11_guncelle, "idefix": idefix_guncelle, "ptt": ptt_guncelle,
}


def pazara_gonder(ayar, pid, df, ilerleme=None):
    """Stok + fiyat g\u00f6nderir. D\u00f6n\u00fc\u015f: (ba\u015far\u0131l\u0131, hatal\u0131, \u00f6zet_metin)."""
    ad = PAZAR_AD.get(pid, pid)
    try:
        if pid not in GUNCELLEYICI:
            raise RuntimeError(f"{ad} i\u00e7in entegrasyon yok.")
        if not pazar_bagli(ayar, pid):
            raise RuntimeError(f"{ad} API bilgileri eksik.")
        df = fiyat_artis_uygula(ayar, pid, df)
        kara = kara_liste_maskesi(ayar, df) | stok_sifir_maskesi(ayar, df)
        if kara.any():  # kara listedeki \u00fcr\u00fcnler pazarda sat\u0131\u015ftan kalks\u0131n (stok 0)
            df = df.copy()
            df.loc[kara, "stok"] = 0
        ok, hata, loglar = GUNCELLEYICI[pid](ayar, df, ilerleme)
    except Exception as e:
        log_yaz(ad, "HATA", f"G\u00f6nderilemedi: {e}")
        raise
    son = loglar[-1] if loglar else ""
    if ok == 0 and hata == 0:
        durum = "UYARI"
    elif hata == 0:
        durum = "OK"
    elif ok > 0:
        durum = "KISM\u0130"
    else:
        durum = "HATA"
    log_yaz(ad, durum, f"{ok} g\u00f6nderildi, {hata} hata. {son}")
    return ok, hata, "\n".join(loglar[-8:])


def tumunu_senkronla(oto=True):
    if not SENKRON_KILIDI.acquire(blocking=False):
        return [("Sistem", False, "Ba\u015fka bir senkronizasyon zaten \u00e7al\u0131\u015f\u0131yor.")]
    try:
        ayar = ayar_oku()
        sonuclar = []
        for ad, bilgi in ayar["tedarikciler"].items():
            try:
                n = tedarikci_senkron(ad, bilgi, _i(ayar.get("kritik_esik")), _i(ayar.get("stok_ust_sinir"), 50))
                log_yaz(ad, "OK", f"{n} \u00fcr\u00fcn g\u00fcncellendi")
                sonuclar.append((ad, True, f"{n} \u00fcr\u00fcn"))
            except Exception as e:
                log_yaz(ad, "HATA", e)
                sonuclar.append((ad, False, str(e)))
        if oto and any(x[1] for x in sonuclar):
            for _, anahtar_, pid_ in OTO_ANAHTAR:
                if ayar.get(anahtar_) and pazar_bagli(ayar, pid_):
                    try:
                        pazara_gonder(ayar, pid_, urunleri_oku())
                    except Exception:
                        pass  # pazara_gonder zaten g\u00fcnl\u00fc\u011fe yazd\u0131
        return sonuclar
    finally:
        SENKRON_KILIDI.release()


def arka_plan_dongusu():
    time.sleep(30)
    while True:
        saat = 6.0
        try:
            ayar = ayar_oku()
            saat = max(1.0, _f(ayar.get("senkron_saat"), 6.0))
            if ayar.get("oto_senkron", True):
                tumunu_senkronla()
        except Exception:
            pass
        time.sleep(saat * 3600)


@st.cache_resource
def arka_plan_baslat():
    t = threading.Thread(target=arka_plan_dongusu, daemon=True)
    t.start()
    return t


def baglanti_testi(ayar, pid):
    try:
        if not pazar_bagli(ayar, pid):
            return False, "Eksik bilgi: t\u00fcm kimlik alanlar\u0131n\u0131 doldurup kaydedin."
        if pid == "trendruum":
            trendruum_token(kimlik(ayar, "trendruum_key"), kimlik(ayar, "trendruum_secret"))
            return True, "\u2705 Trendruum giri\u015fi ba\u015far\u0131l\u0131."
        if pid == "hb":
            return hb_dene(ayar)
        if pid == "ptt":
            return ptt_test(kimlik(ayar, "ptt_key"), kimlik(ayar, "ptt_token"))
        if pid == "trendyol":
            s_, k_, x_ = (kimlik(ayar, a) for a in ("trendyol_seller_id", "trendyol_key", "trendyol_secret"))
            r = http("GET", f"{TY_BASE}/order/sellers/{s_}/orders", params={"size": 1}, headers=trendyol_header(s_, k_, x_), timeout=30)
        elif pid == "n11":
            r = http("GET", f"{N11_BASE}/rest/delivery/v1/shipmentPackages",
                     params={"status": "Created", "page": 0, "size": 1},
                     headers=n11_header(kimlik(ayar, "n11_key"), kimlik(ayar, "n11_secret")), timeout=30)
        elif pid == "idefix":
            r = http("GET", f"{ID_BASE}/pim/product-category", headers=idefix_header(ayar), timeout=60)
        else:
            return False, "Desteklenmiyor."
        if r.status_code == 200:
            return True, "\u2705 Ba\u011flant\u0131 ba\u015far\u0131l\u0131 (HTTP 200)"
        return False, f"\u274c Ba\u011flant\u0131 ba\u015far\u0131s\u0131z ({yanit_ozet(r)})"
    except Exception as e:
        return False, f"Ba\u011flant\u0131 kurulamad\u0131: {e}"


# --------------------------------------------------------------------------
# Sipari\u015f normalle\u015ftirme
# --------------------------------------------------------------------------
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
    "yeni": "\U0001f195 Yeni", "hazir": "\U0001f69a G\u00f6nderime Haz\u0131r", "kargoda": "\U0001f69b Kargoda",
    "teslim": "\u2705 Teslim Edildi", "iptal": "\u274c \u0130ptal",
}


def durum_kodu(pid, d):
    d = str(d or "").lower()
    if pid in ("trendyol", "n11"):
        harita = {"created": "yeni", "picking": "hazir", "invoiced": "hazir", "shipped": "kargoda",
                  "delivered": "teslim", "cancelled": "iptal"}
    else:
        harita = {"new": "yeni", "pending": "yeni", "in_progress": "hazir", "shipped": "kargoda",
                  "delivered": "teslim", "cancelled": "iptal"}
    return harita.get(d, "yeni")


def siparis_normalle_ty(p):
    adr = p.get("shipmentAddress") or {}
    return {
        "pid": "trendyol", "id": str(p.get("id", "")), "no": str(p.get("orderNumber", "")),
        "tarih": tr_tarih(p.get("orderDate")),
        "durum": durum_kodu("trendyol", p.get("status") or p.get("shipmentPackageStatus")),
        "alici": adr.get("fullName") or f"{adr.get('firstName', '')} {adr.get('lastName', '')}".strip(),
        "adres": adr.get("fullAddress") or metin(adr.get("address1")),
        "urunler": [{"ad": l.get("productName", ""), "sku": l.get("merchantSku") or l.get("barcode", ""), "adet": l.get("quantity", 1)}
                    for l in (p.get("lines") or [])],
        "tutar": p.get("totalPrice"), "kargo": p.get("cargoProviderName", ""),
        "barkod": str(p.get("cargoTrackingNumber", "") or ""),
    }


def siparis_normalle_n11(p):
    adr = p.get("shippingAddress") or {}
    gecmis = p.get("packageHistories") or []
    ilk = gecmis[0].get("createdDate") if gecmis else p.get("lastModifiedDate")
    return {
        "pid": "n11", "id": str(p.get("id", "")), "no": str(p.get("orderNumber", "")),
        "tarih": tr_tarih(ilk), "durum": durum_kodu("n11", p.get("shipmentPackageStatus")),
        "alici": adr.get("fullName") or p.get("customerfullName") or "",
        "adres": ", ".join(x for x in (adr.get("address"), adr.get("district"), adr.get("city")) if x),
        "urunler": [{"ad": l.get("productName", ""), "sku": l.get("stockCode") or l.get("barcode") or "", "adet": l.get("quantity", 1)}
                    for l in (p.get("lines") or [])],
        "tutar": p.get("totalAmount"), "kargo": p.get("cargoProviderName", "") or "",
        "barkod": str(p.get("cargoTrackingNumber", "") or ""),
    }


def siparis_normalle_hb(p):
    return {
        "pid": "hb", "id": str(p.get("packageId", "")), "no": str(p.get("orderNumber", "")),
        "tarih": tr_tarih(p.get("orderDate")), "durum": durum_kodu("hb", p.get("status")),
        "alici": p.get("recipientName", "Hepsiburada M\u00fc\u015fterisi"), "adres": metin(p.get("shippingAddress")),
        "urunler": [{"ad": l.get("productName", "\u00dcr\u00fcn"), "sku": l.get("merchantSku", ""), "adet": l.get("quantity", 1)}
                    for l in (p.get("items") or [])],
        "tutar": p.get("totalPrice", 0), "kargo": p.get("cargoCompany", ""),
        "barkod": str(p.get("cargoBarcode", "")),
    }


def siparis_normalle_tr(p):
    satirlar = p.get("items") or p.get("products") or []
    return {
        "pid": "trendruum", "id": str(p.get("id") or p.get("order_id") or ""),
        "no": str(p.get("order_number") or p.get("orderNo") or ""),
        "tarih": tr_tarih(p.get("created_at") or p.get("orderDate")),
        "durum": durum_kodu("trendruum", p.get("status")),
        "alici": p.get("customer_name") or p.get("recipient_name") or "Trendruum M\u00fc\u015fterisi",
        "adres": metin(p.get("shipping_address") or p.get("address")),
        "urunler": [{"ad": l.get("name") or l.get("title") or "\u00dcr\u00fcn", "sku": l.get("barcode") or l.get("stock_code") or "",
                     "adet": l.get("quantity") or l.get("amount") or 1} for l in satirlar],
        "tutar": p.get("total_price") or p.get("grand_total") or 0,
        "kargo": p.get("cargo_company") or "", "barkod": str(p.get("cargo_barcode") or p.get("tracking_number") or ""),
    }


def siparis_cek(ayar, pid):
    if pid == "trendyol":
        s_, k_, x_ = (kimlik(ayar, a) for a in ("trendyol_seller_id", "trendyol_key", "trendyol_secret"))
        gorulen, sonuc = set(), []
        for durum in ("Created", "Picking", "Invoiced", "Shipped"):
            for p_ in trendyol_siparisler(s_, k_, x_, durum, 100):
                if p_.get("id") not in gorulen:
                    gorulen.add(p_.get("id"))
                    sonuc.append(siparis_normalle_ty(p_))
        return sonuc
    if pid == "n11":
        k_, x_ = kimlik(ayar, "n11_key"), kimlik(ayar, "n11_secret")
        gorulen, sonuc = set(), []
        for durum in ("Created", "Picking", "Shipped"):
            for p_ in n11_siparisler(k_, x_, durum):
                if p_.get("id") not in gorulen:
                    gorulen.add(p_.get("id"))
                    sonuc.append(siparis_normalle_n11(p_))
        return sonuc
    if pid == "hb":
        return [siparis_normalle_hb(x) for x in hb_siparisler(ayar)]
    if pid == "trendruum":
        return [siparis_normalle_tr(x) for x in trendruum_siparisler(ayar)]
    raise RuntimeError(f"{PAZAR_AD.get(pid, pid)} i\u00e7in sipari\u015f \u00e7ekme desteklenmiyor.")


# --------------------------------------------------------------------------
# Oturum (sayfa yenilense de a\u00e7\u0131k kal\u0131r; imzal\u0131, s\u00fcreli jeton)
# --------------------------------------------------------------------------
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


def _imza(sifre, ts):
    return hmac.new(str(sifre).encode(), f"oturum:{ts}".encode(), hashlib.sha256).hexdigest()


def oturum_jetonu(sifre):
    ts = str(int(time.time()))
    return f"{ts}.{_imza(sifre, ts)}"


def jeton_gecerli(jeton, sifre):
    try:
        ts, imza = str(jeton).split(".", 1)
        return hmac.compare_digest(imza, _imza(sifre, ts)) and 0 <= time.time() - int(ts) < OTURUM_SURESI
    except Exception:
        return False


# --------------------------------------------------------------------------
# Aray\u00fcz yard\u0131mc\u0131lar\u0131
# --------------------------------------------------------------------------
def gen(fn, *a, **kw):
    """Streamlit s\u00fcr\u00fcmleri aras\u0131nda 'tam geni\u015flik' parametresi uyumu."""
    for ek in ({"width": "stretch"}, {"use_container_width": True}, {}):
        try:
            return fn(*a, **kw, **ek)
        except TypeError:
            continue
        except Exception as e:  # eski s\u00fcr\u00fcmde width='stretch' farkl\u0131 hata verebilir
            if ek and "width" in str(e).lower():
                continue
            raise
    return fn(*a, **kw)


def tema_css():
    k = [".st-key-nav_%s button{background:%s;}" % (kid, renk) for kid, _, renk in ANA_MENU]
    k.append(".st-key-nav_Ayarlar button{background:#e2e8f0;}")
    for pid, p in PAZAR.items():
        k.append(".st-key-navp_%s button{background:%s;}" % (pid, p["pastel"]))
        for alt, _, _ in ALT:
            k.append(".st-key-sub_%s_%s button{background:#fff;border-left:5px solid %s;margin-left:16px;width:calc(100%% - 16px);}" % (pid, alt, p["renk"]))
    k.append('[data-testid="stSidebar"] button, [data-testid="stSidebar"] button p{color:#1e293b !important;}')
    k.append('[data-testid="stSidebar"] button[kind="primary"], [data-testid="stSidebar"] button[data-testid="stBaseButton-primary"]'
             '{font-weight:700;box-shadow:inset 0 0 0 2px #1e293b;}')
    return "<style>" + "".join(k) + "</style>"


ANA_MENU = [
    ("Anasayfa", "\U0001f3e0 Anasayfa", "#dbeafe"),
    ("Bildirim", "\U0001f514 Bildirimler", "#fef3c7"),
    ("Urunler", "\U0001f4e6 Sistemdeki \u00dcr\u00fcnler", "#f8fafc"),
    ("Kritik", "\U0001f504 Oto Kritik Stok", "#dbeafe"),
]
ALT = [("siparis", "Sipari\u015fler", "\U0001f9fe"), ("islemler", "T\u00fcm \u0130\u015flemleri", "\U0001f517"), ("ayar", "Genel Ayarlar\u0131", "\u2699\ufe0f")]


def git(sayfa_id):
    st.session_state["sayfa"] = sayfa_id


def git_pazar(pid, alt):
    st.session_state["acik_pazar"] = pid
    st.session_state["sayfa"] = f"{pid}:{alt}"


def ac_kapa(pid):
    st.session_state["acik_pazar"] = None if st.session_state.get("acik_pazar") == pid else pid


def cikis_yap():
    st.session_state.giris_ok = False
    try:
        st.query_params.clear()
    except Exception:
        pass


def giris_ekrani(sifre):
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
            '<div class="login-card"><div class="login-title">\U0001f985 \u015eahEntegre</div>'
            '<div class="login-sub">E-Ticaret Y\u00f6netim Paneli</div></div>',
            unsafe_allow_html=True,
        )
        with st.form("giris_formu"):
            girilen = st.text_input("\U0001f511 Y\u00f6netici \u015eifresi", type="password", placeholder="\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022")
            buton = gen(st.form_submit_button, "Giri\u015f Yap", type="primary")
        if buton:
            hatalar = st.session_state.get("hatali_giris", 0)
            if hatalar >= 5:  # kaba kuvvet yava\u015flatma
                time.sleep(min(2 ** (hatalar - 4), 30))
            if hmac.compare_digest(girilen.encode(), str(sifre).encode()):
                st.session_state.hatali_giris = 0
                st.session_state.giris_ok = True
                st.query_params["t"] = oturum_jetonu(sifre)
                st.rerun()
            else:
                st.session_state.hatali_giris = hatalar + 1
                st.error("\u274c Hatal\u0131 \u015fifre.")
    st.stop()


def secili_urunler(df, anahtar):
    if df.empty or "tedarikci" not in df.columns:
        return df
    liste = sorted(df["tedarikci"].dropna().unique().tolist())
    sec = st.multiselect("G\u00f6nderilecek Tedarik\u00e7ileri Se\u00e7in", liste, default=liste, key=f"{anahtar}_ted_sec")
    return df[df["tedarikci"].isin(sec)] if sec else df.iloc[0:0]


def hb_katalog_taban(ayar):
    """Katalog API tabani: urun adresindeki hepsiburada.com sunucusu, yoksa canli sunucu."""
    u = str(pa_al(ayar, "hb").get("urun_endpoint", "") or "").strip()
    host = (urllib.parse.urlparse(u).hostname or "").lower() if u else ""
    if not (host == "hepsiburada.com" or host.endswith(".hepsiburada.com")):
        host = "mpop.hepsiburada.com"
    return f"https://{host}/product/api"


def hb_kategori_ayikla(j):
    """get-all-categories yanitindan [{ID, Kategori}] cikarir (alan adlari esnek okunur)."""
    liste = None
    if isinstance(j, list):
        liste = j
    elif isinstance(j, dict):
        for a in ("data", "content", "items", "categories", "results"):
            v = j.get(a)
            if isinstance(v, list):
                liste = v
                break
            if isinstance(v, dict):
                for b in ("content", "items", "data", "categories"):
                    if isinstance(v.get(b), list):
                        liste = v[b]
                        break
                if liste is not None:
                    break
    cikti = []
    for x in (liste or []):
        if not isinstance(x, dict):
            continue
        cid = x.get("categoryId", x.get("id"))
        if cid in (None, ""):
            continue
        ad = str(x.get("displayName") or x.get("name") or "").strip()
        yol = x.get("paths") or x.get("path") or x.get("fullPath")
        if isinstance(yol, list):
            parca = [str(y.get("name") if isinstance(y, dict) else y).strip() for y in yol]
            yol = " > ".join(t for t in parca if t and t != "None")
        yol = str(yol or "").strip()
        if ad and not yol.endswith(ad):
            yol = f"{yol} > {ad}" if yol else ad
        cikti.append({"ID": str(cid).strip(), "Kategori": yol or str(cid)})
    return cikti


def hb_agac_yukle(ayar, en_fazla_sayfa=40, boyut=1000):
    """Tum uc kategorileri sayfa sayfa ceker (leaf=true, status=ACTIVE, available=true)."""
    taban = hb_katalog_taban(ayar)
    baslik = hb_header(ayar)
    sabit = {"leaf": "true", "status": "ACTIVE", "available": "true"}
    hepsi, goruldu = [], set()
    sayfali = True
    for sayfa in range(en_fazla_sayfa):
        prm = dict(sabit)
        if sayfali:
            prm.update({"page": sayfa, "size": boyut, "version": 1})
        r = http("GET", f"{taban}/categories/get-all-categories", params=prm, headers=baslik, timeout=120, tries=2)
        if r.status_code in (400, 422) and sayfali and sayfa == 0:
            sayfali = False  # sayfalama parametreleri kabul edilmediyse yalnizca temel parametrelerle dene
            r = http("GET", f"{taban}/categories/get-all-categories", params=sabit, headers=baslik, timeout=120, tries=2)
        if r.status_code != 200:
            raise RuntimeError("Hepsiburada kategori listesi alinamadi: " + yanit_ozet(r))
        try:
            yeni = hb_kategori_ayikla(r.json())
        except Exception:
            raise RuntimeError("Hepsiburada kategori yaniti okunamadi: " + yanit_ozet(r))
        eklenen = 0
        for k in yeni:
            if k["ID"] not in goruldu:
                goruldu.add(k["ID"])
                hepsi.append(k)
                eklenen += 1
        if not sayfali or eklenen == 0 or len(yeni) < boyut:
            break
    if not hepsi:
        raise RuntimeError("Hepsiburada kategori listesi bos geldi.")
    return hepsi


def hb_oto_dugumler(ayar):
    """Otomatik eslestirme icin Hepsiburada uc kategorilerini Trendruum'daki gibi hazirlar."""
    out = []
    for k in hb_agac_yukle(ayar):
        son = k["Kategori"].split(">")[-1]
        out.append({"ID": k["ID"], "yol": k["Kategori"], "son": kat_belirtec(son), "tum": kat_belirtec(k["Kategori"])})
    return out


def hb_kategori_sema(ayar, cid):
    r = http("GET", f"{hb_katalog_taban(ayar)}/categories/{urllib.parse.quote(str(cid), safe='')}/attributes",
             headers=hb_header(ayar), timeout=60, tries=1)
    try:
        j = r.json()
    except Exception:
        j = None
    return r.status_code, j, (r.text or "")[:3000]


def hb_kategori_bulucu():
    if not pazar_bagli(ayarlar, "hb"):
        st.caption("Kategori aramak i\u00e7in \u00f6nce Hepsiburada API bilgilerini kaydedin.")
        return
    st.caption("\u00d6nce 'Kategorileri y\u00fckle'ye bas\u0131n (bir kez, birka\u00e7 y\u00fcz sat\u0131r olabilir), sonra \u00fcr\u00fcn tipini yaz\u0131p aray\u0131n. Se\u00e7ece\u011finiz kategori \u00fcr\u00fcn\u00fcn ger\u00e7ek (u\u00e7) kategorisi olmal\u0131.")
    if gen(st.button, "Kategorileri y\u00fckle", key="hbk_yukle"):
        try:
            with st.spinner("Hepsiburada kategorileri al\u0131n\u0131yor..."):
                st.session_state["hbk_liste"] = hb_agac_yukle(ayarlar)
        except Exception as e:
            st.session_state["hbk_liste"] = None
            st.error(f"Hata: {e}")
    liste = st.session_state.get("hbk_liste")
    if not liste:
        return
    st.caption(f"{len(liste):,} u\u00e7 kategori y\u00fcklendi.")
    ad = st.text_input("Kategori ad\u0131 (birden \u00e7ok kelime yazabilirsiniz)", key="hbk_ara")
    kel = tr_norm(ad).split()
    bulunan = kategori_siralama([k for k in liste if kel and all(w in tr_norm(k["Kategori"]) for w in kel)], ad)[:100]
    if not kel:
        return
    if not bulunan:
        st.warning("Sonu\u00e7 bulunamad\u0131; daha k\u0131sa ya da farkl\u0131 bir kelime deneyin.")
        return
    d = pd.DataFrame(bulunan)
    st.dataframe(d, hide_index=True)
    secenek = [f"{k['ID']} \u2014 {k['Kategori']}" for k in bulunan]
    sec = st.selectbox("Listeden se\u00e7", secenek, key="hbk_sec")
    secilen = sec.split(" \u2014 ")[0].strip()
    mevcut_vk = pa_al(ayarlar, "hb").get("category_id") or "(bo\u015f)"
    st.caption(f"\u015eu an kay\u0131tl\u0131 varsay\u0131lan kategori ID: {mevcut_vk}")
    kategoriye_ata_paneli("hb", secilen)
    k1, k2 = st.columns(2)
    if gen(k1.button, "Varsay\u0131lan kategori yap", key="hbk_varsayilan"):
        varsayilan_kategori_yaz("hb", secilen)
    if gen(k2.button, "Zorunlu alanlar\u0131 g\u00f6ster", key="hbk_sema"):
        try:
            st.session_state["hbk_sema_sonuc"] = (secilen,) + hb_kategori_sema(ayarlar, secilen)
        except Exception as e:
            st.error(f"Hata: {e}")
    sm = st.session_state.get("hbk_sema_sonuc")
    if sm and sm[0] == secilen:
        st.caption(f"Yan\u0131t: HTTP {sm[1]}")
        j = sm[2] if isinstance(sm[2], dict) else {}
        veri = j.get("data") if isinstance(j.get("data"), (dict, list)) else j
        gruplar = veri if isinstance(veri, dict) else {"ozellikler": veri}
        gosterildi = 0
        for grup, oge in gruplar.items():
            if isinstance(oge, list):
                for x in oge:
                    if isinstance(x, dict) and (x.get("name") or x.get("id")):
                        zor = x.get("mandatory") or x.get("required")
                        st.write(f"- {grup}: {x.get('name') or x.get('id')}" + (" - ZORUNLU" if zor else ""))
                        gosterildi += 1
        if not gosterildi:
            st.text(sm[3])


def oto_esleme(pid, pa, adet, mevcut):
    st.markdown("**Otomatik \u00f6neri**")
    pazar_ad = {"trendruum": "Trendruum", "hb": "Hepsiburada"}.get(pid, pid)
    st.caption(f"{pazar_ad} kategori listesini \u00e7ekip tedarik\u00e7i kategorilerinize en yak\u0131n kategoriyi \u00f6nerir. "
               "Hi\u00e7bir \u015fey kendili\u011finden kaydedilmez; i\u015faretledi\u011finiz sat\u0131rlar kaydedilir.")
    bildirim = st.session_state.pop(f"oto_bildirim_{pid}", None)
    if bildirim:
        st.success(bildirim)
    tek_tus = gen(st.button, "\u26a1 Tek tu\u015f: hepsini bul, y\u00fcksek g\u00fcvenlileri kaydet", key=f"oto_tek_{pid}", type="primary")
    if gen(st.button, "\u00d6nerileri haz\u0131rla (\u00f6nce ben bakay\u0131m)", key=f"oto_hazirla_{pid}") or tek_tus:
        try:
            with st.spinner("Kategori listesi al\u0131n\u0131yor..."):
                dugumler = trendruum_agac_yukle(ayarlar) if pid == "trendruum" else hb_oto_dugumler(ayarlar)
            satirlar = []
            for k in adet.index:
                if mevcut.get(k):
                    continue
                i, y, g = kategori_oner(k, dugumler)
                satirlar.append({"Onayla": g == "yuksek", "Tedarik\u00e7i kategorisi": k, "\u00dcr\u00fcn": int(adet[k]),
                                 "\u00d6nerilen kategori": y, "G\u00fcven": {"yuksek": "Y\u00fcksek", "orta": "Orta", "dusuk": "D\u00fc\u015f\u00fck"}.get(g, "Yok"),
                                 "ID": i})
            if tek_tus:
                yeni_esl = dict(mevcut)
                kayit = 0
                for r in satirlar:
                    if r["G\u00fcven"] == "Y\u00fcksek" and str(r["ID"]).strip():
                        yeni_esl[str(r["Tedarik\u00e7i kategorisi"])] = str(r["ID"])
                        kayit += 1
                pa["kategori_eslesme"] = yeni_esl
                ayar_yaz(ayarlar)
                satirlar = [r for r in satirlar if not (r["G\u00fcven"] == "Y\u00fcksek" and str(r["ID"]).strip())]
                for r in satirlar:
                    r["Onayla"] = False
                st.session_state[f"oto_bildirim_{pid}"] = (
                    f"{kayit} kategori otomatik e\u015fle\u015ftirildi ve kaydedildi. {len(satirlar)} kategori i\u00e7in g\u00fcveni d\u00fc\u015f\u00fck "
                    "\u00f6neri a\u015fa\u011f\u0131da; kontrol edip i\u015faretleyin. B\u00fcy\u00fck kategorileri tabloda mutlaka g\u00f6zden ge\u00e7irin.")
                st.session_state[f"oneri_{pid}"] = satirlar
                st.rerun()
            st.session_state[f"oneri_{pid}"] = satirlar
        except Exception as e:
            st.session_state[f"oneri_{pid}"] = None
            st.error(f"Hata: {e}")
    sat = st.session_state.get(f"oneri_{pid}")
    if not sat:
        return
    d = pd.DataFrame(sat).head(300)
    st.caption(f"{len(sat)} e\u015fle\u015fmemi\u015f kategori i\u00e7in \u00f6neri haz\u0131r. 'Y\u00fcksek' g\u00fcvenliler i\u015faretli geldi; 'Orta/D\u00fc\u015f\u00fck' olanlar\u0131 kendiniz kontrol edip i\u015faretleyin.")
    duz = st.data_editor(d, hide_index=True, key=f"oto_{pid}_{len(d)}",
                         disabled=["Tedarik\u00e7i kategorisi", "\u00dcr\u00fcn", "\u00d6nerilen kategori", "G\u00fcven", "ID"])
    if gen(st.button, "\u0130\u015faretlenenleri kaydet", key=f"oto_kaydet_{pid}"):
        yeni = dict(mevcut)
        n = 0
        for _, r in duz.iterrows():
            if r["Onayla"] and str(r["ID"]).strip():
                yeni[str(r["Tedarik\u00e7i kategorisi"])] = str(r["ID"])
                n += 1
        pa["kategori_eslesme"] = yeni
        ayar_yaz(ayarlar)
        st.session_state[f"oneri_{pid}"] = None
        st.success(f"{n} kategori e\u015fle\u015ftirmesi kaydedildi (toplam {len(yeni)}).")
        st.rerun()
    st.divider()


def kategori_esleme_editoru(pid):
    pa = pa_al(ayarlar, pid)
    df = urunleri_oku()
    if df.empty or "kategori" not in df.columns:
        st.caption("Kategori e\u015fle\u015ftirmesi i\u00e7in \u00f6nce tedarik\u00e7i senkronizasyonu yap\u0131n.")
        return
    mevcut = pa.get("kategori_eslesme") or {}
    ana = df["kategori"].dropna().astype(str).map(lambda k: k.split(">>>")[0].strip())
    adet = ana[ana != ""].value_counts()
    st.caption(f"{len(adet)} farkl\u0131 tedarik\u00e7i kategorisi var; e\u015fle\u015fmemi\u015f \u00fcr\u00fcnler (varsay\u0131lan kapal\u0131yken) g\u00f6nderilmez.")
    if pid in ("trendruum", "hb"):
        oto_esleme(pid, pa, adet, mevcut)
    st.markdown("**Elle e\u015fle\u015ftirme**")
    ara = st.text_input("Kategori ara (filtre)", key=f"kat_ara_{pid}")
    liste = [k for k in adet.index if not ara.strip() or tr_norm(ara) in tr_norm(k)]
    sadece_bos = st.checkbox("Sadece ID'si girilmemi\u015fleri g\u00f6ster", key=f"kat_bos_{pid}")
    if sadece_bos:
        liste = [k for k in liste if not mevcut.get(k)]
    liste = liste[:300]
    tablo = pd.DataFrame({
        "Tedarik\u00e7i kategorisi": liste,
        "\u00dcr\u00fcn say\u0131s\u0131": [int(adet[k]) for k in liste],
        "Pazar yeri kategori ID": [str(mevcut.get(k, "")) for k in liste],
    })
    duz = st.data_editor(tablo, hide_index=True, disabled=["Tedarik\u00e7i kategorisi", "\u00dcr\u00fcn say\u0131s\u0131"], key=f"kat_edit_{pid}_{ara}_{sadece_bos}")
    if gen(st.button, "E\u015fle\u015ftirmeyi kaydet", key=f"kat_kaydet_{pid}"):
        yeni = dict(mevcut)  # filtrede g\u00f6r\u00fcnmeyen e\u015fle\u015ftirmeler korunur
        for _, r in duz.iterrows():
            k, v = str(r["Tedarik\u00e7i kategorisi"]), str(r["Pazar yeri kategori ID"]).strip()
            if v:
                yeni[k] = v
            else:
                yeni.pop(k, None)
        if pid == "trendruum":
            gecersiz = [k for k, v in yeni.items() if not objectid_mi(v)]
            if gecersiz:
                st.error(f"Trendruum kategori ID'si 24 karakterlik olmal\u0131. Hatal\u0131: {', '.join(gecersiz[:5])}")
                return
        pa["kategori_eslesme"] = yeni
        ayar_yaz(ayarlar)
        st.success(f"Toplam {len(yeni)} kategori e\u015fle\u015ftirmesi kay\u0131tl\u0131.")


def varsayilan_kategori_yaz(pid, cid):
    """Varsayilan kategori ID'sini kaydeder; formun yeni degeri gostermesi icin sayfayi yeniler."""
    pa_al(ayarlar, pid)["category_id"] = str(cid).strip()
    ayar_yaz(ayarlar)
    st.session_state[f"vk_bilgi_{pid}"] = str(cid).strip()
    st.rerun()


def pazar_ayar_formu(pid):
    pa = pa_al(ayarlar, pid)
    bilgi = st.session_state.pop(f"vk_bilgi_{pid}", None)
    if bilgi:
        st.success(f"Varsay\u0131lan kategori ID kaydedildi: {bilgi}")
    with st.form(f"ayar_form_{pid}"):
        st.markdown("**Fiyat kurallar\u0131 (bu pazar yeri i\u00e7in)**")
        c1, c2, c3 = st.columns(3)
        marj = c1.number_input("K\u00e2r marj\u0131 % (0 = tedarik\u00e7i de\u011feri)", 0.0, 500.0, _f(pa.get("kar_marji")), 1.0)
        kargo = c2.number_input("Sabit kargo TL (0 = tedarik\u00e7i de\u011feri)", 0.0, 5000.0, _f(pa.get("sabit_kargo")), 5.0)
        artis = c3.number_input("Ek fiyat art\u0131\u015f\u0131 % (komisyon vb.)", 0.0, 200.0, _f(pa.get("fiyat_artis")), 0.5)
        yeni = {"kar_marji": marj, "sabit_kargo": kargo, "fiyat_artis": artis}
        hata = None
        if pid == "hb":
            yeni["sku_prefix"] = st.text_input("Merchant SKU \u00f6neki (varsa)", value=str(pa.get("sku_prefix", "") or ""))
        if pid in ("n11", "idefix", "trendruum", "ptt", "hb"):
            st.markdown("**\u00dcr\u00fcn olu\u015fturma ayarlar\u0131**")
            c1, c2, c3 = st.columns(3)
            yeni["category_id"] = c1.text_input("Varsay\u0131lan kategori ID", value=str(pa.get("category_id", "") or ""),
                                                key=f"vk_alan_{pid}_{pa.get('category_id', '')}")
            yeni["varsayilan_kategori_kullan"] = st.checkbox(
                "E\u015fle\u015fmesi olmayan \u00fcr\u00fcnleri de varsay\u0131lan kategoriye koy",
                value=bool(pa.get("varsayilan_kategori_kullan", False)),
                help="Kapal\u0131yken (\u00f6nerilen) yaln\u0131zca 'Kategori e\u015fle\u015ftirme'de ID'si girilmi\u015f \u00fcr\u00fcnler g\u00f6nderilir; "
                     "di\u011ferleri atlan\u0131r. A\u00e7\u0131kken t\u00fcm \u00fcr\u00fcnler varsay\u0131lan kategoriye d\u00fc\u015fer.")
            if pid in ("idefix", "trendruum"):
                yeni["brand_id"] = c2.text_input("Marka ID", value=str(pa.get("brand_id", "") or (kimlik(ayarlar, "trendruum_brand") if pid == "trendruum" else "")))
            kdv_liste = [20, 10, 1, 0]
            kdv_now = _i(pa.get("kdv"), 20)
            yeni["kdv"] = c3.selectbox("KDV %", kdv_liste, index=kdv_liste.index(kdv_now) if kdv_now in kdv_liste else 0)
        if pid == "n11":
            c1, c2 = st.columns(2)
            yeni["shipment_template"] = c1.text_input("Kargo \u015fablonu ad\u0131", value=str(pa.get("shipment_template", "") or ""))
            yeni["preparing_day"] = int(c2.number_input("Haz\u0131rl\u0131k s\u00fcresi (g\u00fcn)", 1, 30, _i(pa.get("preparing_day"), 3) or 3))
        if pid == "idefix":
            c1, c2 = st.columns(2)
            yeni["teslim_suresi"] = int(c1.number_input("Teslim s\u00fcresi (g\u00fcn)", 1, 30, _i(pa.get("teslim_suresi"), 3) or 3))
            yeni["stok_kodu_barkod"] = c2.checkbox("Ge\u00e7erli barkodu olmayan \u00fcr\u00fcnlerde stok kodunu barkod yerine kullan", value=bool(pa.get("stok_kodu_barkod")))
        if pid == "hb":
            yeni["urun_endpoint"] = st.text_input("\u00dcr\u00fcn olu\u015fturma adresi (tam https URL, Hepsiburada dok\u00fcman\u0131ndan)", value=str(pa.get("urun_endpoint", "") or ""),
                                                  help="https://\u2026.hepsiburada.com/\u2026 bi\u00e7iminde; bo\u015fsa \u00fcr\u00fcn olu\u015fturma kapal\u0131 kal\u0131r.")
            yeni["marka"] = st.text_input("Marka ad\u0131", value=str(pa.get("marka", "") or ""))
        if pid == "ptt":
            c1, c2, c3 = st.columns(3)
            yeni["marka"] = c1.text_input("Marka ad\u0131 (iste\u011fe ba\u011fl\u0131)", value=str(pa.get("marka", "") or ""))
            yeni["desi"] = c2.number_input("Desi", 0.1, 500.0, _f(pa.get("desi"), 1.0) or 1.0, 0.5)
            yeni["kargo_profil"] = c3.text_input("Kargo profil ID (iste\u011fe ba\u011fl\u0131)", value=str(pa.get("kargo_profil", "") or ""))
            yeni["aktif_gonder"] = st.checkbox("\u00dcr\u00fcnleri aktif (sat\u0131\u015fta) olarak g\u00f6nder", value=bool(pa.get("aktif_gonder", False)),
                                               help="Kapal\u0131yken \u00fcr\u00fcnler pasif olu\u015fturulur; PTT panelinden kontrol edip aktifle\u015ftirebilirsiniz (\u00f6nerilen).")
        if pid in ("trendruum", "ptt", "hb"):
            yeni["gecici_barkod"] = st.checkbox("Ge\u00e7erli barkodu olmayan \u00fcr\u00fcnlere kal\u0131c\u0131 ge\u00e7ici barkod \u00fcret (869\u2026)", value=bool(pa.get("gecici_barkod", True)))
        if pid == "hb":
            h1, h2 = st.columns(2)
            yeni["garanti"] = int(h1.number_input("Garanti s\u00fcresi (ay)", 0, 120, _i(pa.get("garanti"), 24)))
            yeni["kg"] = h2.number_input("A\u011f\u0131rl\u0131k (kg)", 0.01, 500.0, _f(pa.get("kg"), 1.0) or 1.0, 0.1)
            ek_metin = st.text_area("Ek \u00fcr\u00fcn \u00f6zellikleri (JSON nesnesi; kategorinin istedi\u011fi alanlar)",
                                    value=json.dumps(pa.get("ek_ozellik") or {}, ensure_ascii=False),
                                    help='\u00d6rnek: {"renk_variant_property": "Siyah"}. Kategorinin zorunlu alanlar\u0131n\u0131 kategori bulucudaki "Zorunlu alanlar\u0131 g\u00f6ster" ile g\u00f6rebilirsiniz.')
            try:
                ek = json.loads(ek_metin.strip() or "{}")
                if not isinstance(ek, dict):
                    raise ValueError("nesne olmal\u0131")
                yeni["ek_ozellik"] = ek
            except ValueError as e:
                hata = f"Ek \u00f6zellikler ge\u00e7erli bir JSON nesnesi olmal\u0131: {e}"
        if pid in ("n11", "idefix"):
            atr_metin = st.text_area("Zorunlu \u00f6zellikler (JSON listesi, bo\u015f b\u0131rak\u0131labilir)",
                                     value=json.dumps(pa.get("attributes") or [], ensure_ascii=False))
            try:
                atr = json.loads(atr_metin.strip() or "[]")
                if not isinstance(atr, list):
                    raise ValueError("liste olmal\u0131")
                yeni["attributes"] = atr
            except ValueError as e:
                hata = f"\u00d6zellikler ge\u00e7erli bir JSON listesi olmal\u0131: {e}"
        if gen(st.form_submit_button, "\U0001f4be Ayarlar\u0131 kaydet", type="primary"):
            if hata:
                st.error(hata)
            else:
                pa.update(yeni)
                ayar_yaz(ayarlar)
                st.success("Kaydedildi.")


# --------------------------------------------------------------------------
# Sayfalar
# --------------------------------------------------------------------------
def tedarikci_sayfasi():
    tedarikciler = ayarlar["tedarikciler"]
    with st.expander("\u2795 Yeni Tedarik\u00e7i Ekle", expanded=not tedarikciler):
        t_ad = st.text_input("Tedarik\u00e7i Ad\u0131")
        t_link = st.text_input("XML \u0130ndirme Linki (URL)")
        if st.button("Kaydet", type="primary"):
            if not t_ad.strip() or not t_link.strip():
                st.error("Ad ve link zorunlu.")
            else:
                try:
                    url_guvenli(t_link.strip())
                except ValueError as e:
                    st.error(str(e))
                else:
                    tedarikciler[t_ad.strip()] = {"link": t_link.strip(), "harita": {}, "marj": 30.0, "sabit_ek": 0.0}
                    ayar_yaz(ayarlar)
                    st.rerun()

    if not tedarikciler:
        return

    st.markdown("---")
    st.markdown("### \u23f1\ufe0f Otomatik G\u00fcncelleme")
    saat = st.number_input("Senkronizasyon aral\u0131\u011f\u0131 (saat)", 1, 24, int(_f(ayarlar.get("senkron_saat"), 6.0)))
    st.caption("Aral\u0131k de\u011fi\u015fikli\u011fi bir sonraki d\u00f6ng\u00fcde ge\u00e7erli olur.")
    ust = st.number_input("Stok \u00fcst s\u0131n\u0131r\u0131 (tedarik\u00e7i sto\u011fu bu de\u011ferle s\u0131n\u0131rlan\u0131r)", 1, 100000, _i(ayarlar.get("stok_ust_sinir"), 50) or 50)
    oto = st.toggle(f"\U0001f916 Otomatik senkronizasyon ({int(saat)} saatte bir)", value=ayarlar.get("oto_senkron", True))
    if (oto, int(saat), int(ust)) != (ayarlar.get("oto_senkron", True), _i(ayarlar.get("senkron_saat"), 6), _i(ayarlar.get("stok_ust_sinir"), 50)):
        ayarlar.update({"oto_senkron": oto, "senkron_saat": int(saat), "stok_ust_sinir": int(ust)})
        ayar_yaz(ayarlar)

    if st.button("\U0001f504 T\u00fcm\u00fcn\u00fc \u015eimdi Senkronla", type="primary"):
        with st.spinner("G\u00fcncelleniyor..."):
            for ad, ok, msg in tumunu_senkronla(oto=False):
                (st.success if ok else st.error)(f"{ad}: {msg}")

    st.markdown("---")
    for ad, bilgi in list(tedarikciler.items()):
        with st.expander(f"\U0001f3e2 {ad}"):
            st.text(f"Link: {bilgi['link'][:70]}{'...' if len(bilgi['link']) > 70 else ''}")
            c1, c2 = st.columns(2)
            if c1.button("\U0001f4e5 XML'i yedek olarak haz\u0131rla", key=f"xml_indir_{ad}"):
                try:
                    st.session_state[f"xml_yedek_{ad}"] = indir(bilgi["link"], _f(bilgi.get("zaman_asimi"), 300.0))
                except Exception as e:
                    st.error(f"\u0130ndirilemedi: {e}")
            if f"xml_yedek_{ad}" in st.session_state:
                st.download_button("\U0001f4be XML Kaydet", data=st.session_state[f"xml_yedek_{ad}"], file_name=f"{ad}_yedek.xml", mime="application/xml", key=f"xml_kaydet_{ad}")
            with c2:
                onay = st.checkbox("Silmeyi onayla", key=f"sil_onay_{ad}")
                if st.button("\U0001f5d1\ufe0f Tedarik\u00e7iyi Sil", key=f"sil_{ad}", disabled=not onay):
                    tedarikciler.pop(ad, None)
                    ayar_yaz(ayarlar)
                    with closing(baglan()) as c:
                        c.execute("DELETE FROM urunler WHERE tedarikci=?", (ad,))
                        c.commit()
                    st.rerun()
            zs = st.number_input("XML bekleme s\u00fcresi (sn)", 30, 1800, int(_f(bilgi.get("zaman_asimi"), 300.0)), 30, key=f"{ad}_zs",
                                 help="Yava\u015f yan\u0131t veren tedarik\u00e7iler i\u00e7in art\u0131r\u0131n.")
            if float(zs) != _f(bilgi.get("zaman_asimi"), 300.0):
                bilgi["zaman_asimi"] = float(zs)
                ayar_yaz(ayarlar)
            st.markdown("**\U0001f4b1 Fiyat / Para Birimi**")
            kdv_e = st.checkbox("Fiyata KDV ekle (XML'deki KDV alan\u0131ndan, yoksa %20)", bool(bilgi.get("kdv_ekle")), key=f"{ad}_kdv_ekle")
            dv_k = st.checkbox("Para birimi kontrol\u00fc (urun_doviz: TL / USD)", bool(bilgi.get("doviz_kontrol")), key=f"{ad}_dvk",
                               help="A\u00e7\u0131kken USD \u00fcr\u00fcnler dolar kuruyla TL'ye \u00e7evrilir. TL/USD d\u0131\u015f\u0131 ya da bo\u015f para birimli \u00fcr\u00fcnler g\u00f6nderilmez.")
            kur_g = st.number_input("Dolar kuru (TL)", 0.0, 1000.0, _f(bilgi.get("usd_kuru")), 0.05, key=f"{ad}_kur",
                                    help="Elle girin ve d\u00fczenli g\u00fcncelleyin.")
            usd_b = st.checkbox("USD \u00fcr\u00fcn bekleniyor (hi\u00e7 gelmezse senkronizasyonu durdur)", bool(bilgi.get("usd_bekle")), key=f"{ad}_usdb")
            yeni_d = {"kdv_ekle": kdv_e, "doviz_kontrol": dv_k, "usd_kuru": float(kur_g), "usd_bekle": usd_b}
            if any(bilgi.get(k) != v for k, v in yeni_d.items()):
                bilgi.update(yeni_d)
                ayar_yaz(ayarlar)
                st.success("Kaydedildi. Senkronizasyondan sonra fiyatlara uygulan\u0131r.")
            oz = DOVIZ_SON.get(ad)
            if oz:
                st.dataframe(pd.DataFrame([{"TL": oz["tl"], "USD": oz["usd"], "Belirsiz (g\u00f6nderilmez)": oz["bilinmeyen"]}]), hide_index=True)
                if oz["bilinmeyen_degerler"]:
                    st.warning(f"Belirsiz para birimi de\u011ferleri: {oz['bilinmeyen_degerler']}")
                for o in oz.get("ornek_usd") or []:
                    st.caption(f"USD \u00f6rnek: {o}")
                if oz["usd"] == 0:
                    st.warning("Hi\u00e7 USD \u00fcr\u00fcn yok. Tedarik\u00e7i para birimi alan\u0131n\u0131 hen\u00fcz d\u00fczeltmemi\u015f olabilir.")
            onizleme = st.session_state.get(f"onizleme_{ad}")
            if gen(st.button, "\U0001f50d XML alanlar\u0131n\u0131 y\u00fckle / yenile", key=f"onizle_{ad}"):
                try:
                    with st.spinner("XML indiriliyor ve analiz ediliyor..."):
                        df_t = xml_onizleme(bilgi["link"], float(zs))
                    onizleme = {"kolonlar": list(df_t.columns), "ornek": df_t.head(5)}
                    st.session_state[f"onizleme_{ad}"] = onizleme
                except Exception as e:
                    st.warning(f"XML analiz edilemedi: {e}")
            if not onizleme:
                st.caption("Alan e\u015fle\u015ftirmesini d\u00fczenlemek i\u00e7in yukar\u0131daki d\u00fc\u011fmeyle XML'i y\u00fckleyin. Kay\u0131tl\u0131 e\u015fle\u015ftirme senkronizasyonda aynen kullan\u0131l\u0131r.")
                continue
            with st.expander("Ham XML \u00f6nizleme (ilk 5 \u00fcr\u00fcn)"):
                st.dataframe(onizleme["ornek"])
            kolonlar = ["(yok)"] + onizleme["kolonlar"]
            eski = bilgi.get("harita", {})

            def sec(lbl, anah, aid, ad=ad, kolonlar=kolonlar, eski=eski, kol_adlari=onizleme["kolonlar"]):
                v = eski.get(aid)
                if v not in kolonlar:
                    v = tahmin(kol_adlari, anah)
                return st.selectbox(lbl, kolonlar, index=kolonlar.index(v), key=f"{ad}_{aid}")

            harita = {
                "kod": sec("Barkod / SKU", ["barkod", "barcode", "sku", "stokkod", "kod", "id"], "kod"),
                "ad": sec("\u00dcr\u00fcn Ad\u0131", ["urunadi", "\u00fcr\u00fcnad\u0131", "name", "title", "ad", "baslik"], "ad"),
                "stok": sec("Stok", ["stok", "stock", "quantity", "adet", "miktar"], "stok"),
                "fiyat": sec("Al\u0131\u015f Fiyat\u0131", ["fiyat", "price", "alis", "al\u0131\u015f"], "fiyat"),
                "gorsel": sec("G\u00f6rsel", ["image_1", "resim", "image", "gorsel", "g\u00f6rsel", "picture", "foto"], "gorsel"),
                "kategori": sec("Kategori", ["kategori", "category", "cat", "tur", "grup", "maincategory"], "kategori"),
            }
            marj = st.number_input("K\u00e2r Marj\u0131 (%)", 0.0, 500.0, float(bilgi.get("marj", 30.0)), 1.0, key=f"{ad}_marj")
            sabit = st.number_input("Sabit Ek / Kargo (TL)", 0.0, 5000.0, float(bilgi.get("sabit_ek", 0.0)), 5.0, key=f"{ad}_sabit")
            if harita != eski or marj != bilgi.get("marj") or sabit != bilgi.get("sabit_ek"):
                bilgi.update({"harita": harita, "marj": marj, "sabit_ek": sabit})
                ayar_yaz(ayarlar)
                st.success("Kaydedildi. Yeni de\u011ferler bir sonraki senkronizasyonda \u00fcr\u00fcnlere uygulan\u0131r.")
            st.markdown("**\U0001f4ca Kademeli k\u00e2r marj\u0131 (al\u0131\u015f fiyat\u0131na g\u00f6re)**")
            kad_a = st.checkbox("Kademeli marj\u0131 kullan (a\u00e7\u0131kken yukar\u0131daki tek marj yerine ge\u00e7er)", bool(bilgi.get("kademe_aktif")), key=f"{ad}_kad_a")
            mevcut = kademe_temizle(bilgi.get("kademe")) or [list(r) for r in VARSAYILAN_KADEME]
            tablo = pd.DataFrame([{"Al\u0131\u015f fiyat\u0131 bu TL'ye kadar (bo\u015f = \u00fcst\u00fc hepsi)": r[0], "Marj %": r[1]} for r in mevcut])
            duz = st.data_editor(tablo, num_rows="dynamic", hide_index=True, key=f"{ad}_kad_t")
            yeni_k = kademe_temizle([[(None if r.iloc[0] != r.iloc[0] else r.iloc[0]), r.iloc[1]] for _, r in duz.iterrows()])
            if kad_a != bool(bilgi.get("kademe_aktif")) or yeni_k != kademe_temizle(bilgi.get("kademe")):
                bilgi.update({"kademe_aktif": kad_a, "kademe": yeni_k or [list(r) for r in VARSAYILAN_KADEME]})
                ayar_yaz(ayarlar)
                st.success("Kademe kaydedildi. Senkronizasyondan sonra uygulan\u0131r.")
            if kad_a:
                ozet_k = ", ".join(("\u00fcst\u00fc" if r[0] is None else f"{int(r[0])} TL'ye kadar") + f" %{r[1]:g}" for r in kademe_temizle(bilgi.get("kademe")))
                st.caption("\u00d6rnek: " + ozet_k)


def ayarlari_geri_yukle(veri_y):
    if not isinstance(veri_y, dict):
        raise ValueError("Dosya bir JSON nesnesi olmal\u0131.")
    for k in VARSAYILAN:  # yaln\u0131zca bilinen alanlar geri y\u00fcklenir
        if k == "kimlik" and isinstance(veri_y.get(k), dict):
            for ka in KIMLIK_ALANLARI:
                if isinstance(veri_y[k].get(ka), str) and veri_y[k][ka].strip():
                    ayarlar["kimlik"][ka] = veri_y[k][ka]
        elif k in veri_y and isinstance(veri_y[k], type(VARSAYILAN[k])):
            ayarlar[k] = veri_y[k]
    ayar_yaz(ayarlar)


def yedek_isaretle():
    ayarlar["son_yedek"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    ayar_yaz(ayarlar)


def genel_ayarlar(sifre):
    st.subheader("\U0001f6ab Kara liste")
    st.caption("Her sat\u0131ra bir kelime. Ad\u0131, kategorisi veya barkodu bu kelimeyi i\u00e7eren \u00fcr\u00fcnler yeni \u00fcr\u00fcn olarak H\u0130\u00c7B\u0130R pazara g\u00f6nderilmez; "
               "pazarda zaten varsa stok/fiyat g\u00fcncellemesinde sto\u011fu 0 yap\u0131l\u0131r (sat\u0131\u015ftan kalkar).")
    kl = st.text_area("Yasakl\u0131 kelimeler", value=str(ayarlar.get("kara_liste", "") or ""), height=120, key="kara_liste_alan")
    if gen(st.button, "\U0001f4be Kara listeyi kaydet", key="kara_kaydet"):
        ayarlar["kara_liste"] = kl
        ayar_yaz(ayarlar)
        st.success("Kara liste kaydedildi.")
    st.divider()

    st.subheader("\U0001f4be Yedekleme")
    if ayarlar.get("son_yedek"):
        st.caption(f"Son indirilen yedek: {ayarlar['son_yedek']}")
    else:
        st.warning("Hen\u00fcz yedek almad\u0131n\u0131z. Sunucu yeniden ba\u015flarsa ayarlar\u0131n\u0131z/anahtarlar\u0131n\u0131z silinebilir; yedek indirip g\u00fcvenli bir yerde saklay\u0131n.")
    st.markdown("**\U0001f510 \u015eifreli TAM yedek (API anahtarlar\u0131, tedarik\u00e7iler, kategori e\u015fle\u015ftirmeleri, t\u00fcm ayarlar)**")
    try:
        import cryptography  # noqa: F401
        sifreleme_var = True
    except ImportError:
        sifreleme_var = False
        st.error("\u015eifreli yedek i\u00e7in 'cryptography' paketi gerekli (requirements.txt i\u00e7inde var; sunucuyu yeniden ba\u015flat\u0131n).")
    if sifreleme_var:
        p1 = st.text_input("Yedek parolas\u0131 (en az 8 karakter)", type="password", key="yedek_p1")
        p2 = st.text_input("Yedek parolas\u0131 (tekrar)", type="password", key="yedek_p2")
        if p1 and (len(p1) < 8 or p1 != p2):
            st.info("Parola en az 8 karakter olmal\u0131 ve iki alan ayn\u0131 olmal\u0131.")
        elif p1:
            st.download_button("\u2b07\ufe0f \u015eifreli yede\u011fi indir", yedek_sifrele(ayarlar, p1),
                               f"sahentegre_sifreli_yedek_{datetime.now():%Y%m%d}.json", "application/json",
                               on_click=yedek_isaretle)
            st.caption("Parolay\u0131 kaybederseniz yedek a\u00e7\u0131lamaz; parola bu dosyada saklanmaz.")
    guvenli = {k: v for k, v in ayarlar.items() if k != "kimlik"}
    guvenli["kimlik"] = {}
    st.download_button("\U0001f4c4 Yedek (API anahtarlar\u0131 HAR\u0130\u00c7, \u015fifresiz)", json.dumps(guvenli, ensure_ascii=False, indent=2).encode("utf-8"),
                       "sahentegre_yedek.json", "application/json")

    yuklenen = st.file_uploader("\u267b\ufe0f Yedek dosyas\u0131n\u0131 geri y\u00fckle (.json \u2014 \u015fifreli veya d\u00fcz)", type="json", key="yedek_yukle")
    geri_parola = st.text_input("\u015eifreli yedekse parolas\u0131", type="password", key="yedek_geri_parola")
    if yuklenen is not None and st.button("Geri Y\u00fckle", key="yedek_btn"):
        try:
            ham = yuklenen.getvalue()
            veri_y = json.loads(ham.decode("utf-8"))
            if isinstance(veri_y, dict) and veri_y.get("sahentegre_yedek"):
                if not geri_parola:
                    raise ValueError("Bu yedek \u015fifreli; parolay\u0131 girin.")
                veri_y = yedek_coz(ham, geri_parola)
            ayarlari_geri_yukle(veri_y)
            st.success("Geri y\u00fcklendi.")
            st.rerun()
        except Exception as e:
            st.error(f"Hata: {e}")


def gunluk_sayfasi():
    with closing(baglan()) as c:
        lg = pd.read_sql("SELECT zaman, tedarikci, durum, mesaj FROM senkron_log ORDER BY id DESC LIMIT 200", c)
    if lg.empty:
        st.info("Kay\u0131t yok.")
    else:
        gen(st.dataframe, lg, hide_index=True)


def atlama_nedenleri(df, pid):
    """Gonderilemeyen urunlerin nedenlerini sayar (kullaniciya gostermek icin)."""
    pa = pa_al(ayarlar, pid)
    say = {}

    def ekle(k):
        say[k] = say.get(k, 0) + 1

    for r in kayit_listesi(df):
        if not str(r.get("gorsel", "")).strip():
            ekle("g\u00f6rseli yok")
        elif pid == "hb" and not str(r.get("gorsel", "")).strip().startswith("https"):
            ekle("g\u00f6rsel adresi https de\u011fil")
        if _f(r.get("satis_fiyati")) <= 0:
            ekle("fiyat\u0131 0")
        cat = kat_sec(pa, ayarlar, r.get("kategori"), pid)
        if not cat:
            ekle("kategorisi e\u015fle\u015ftirilmemi\u015f (varsay\u0131lan kategori kapal\u0131)")
        elif pid == "trendruum" and not objectid_mi(cat):
            ekle("kategori ID ge\u00e7ersiz")
    return ", ".join(f"{k}: {v}" for k, v in say.items())


def ilk_gonderilebilir(df, pid, uretici, en_fazla=500):
    """Test modunda listenin ilk degil, gonderilebilen ilk urununu bulur."""
    for i in range(min(len(df), en_fazla)):
        satir = df.iloc[[i]]
        liste, _ = uretici(satir, ayarlar)
        if liste:
            return satir, i
    return None, -1


def kategori_secimi_uygula(pid, df):
    """Gonderilecek kategorileri alt alta isaretlettirir; df'yi buna gore suzer."""
    if df.empty or "kategori" not in df.columns:
        return df
    pa = pa_al(ayarlar, pid)
    esl = pa.get("kategori_eslesme") or {}
    varsayilan = bool(pa.get("varsayilan_kategori_kullan"))
    ana = df["kategori"].fillna("").astype(str).map(lambda k: k.split(">>>")[0].strip())
    adet = ana[ana != ""].value_counts()
    gosterilen = [k for k in adet.index if varsayilan or esl.get(k)]
    eslesmeyen = [k for k in adet.index if k not in gosterilen]
    if eslesmeyen:
        st.caption(f"{len(eslesmeyen)} kategori ({int(adet[eslesmeyen].sum())} \u00fcr\u00fcn) pazar yeri kategorisine e\u015fle\u015ftirilmedi\u011fi i\u00e7in listede yok ve g\u00f6nderilmez.")
    if not gosterilen:
        st.warning("E\u015fle\u015ftirilmi\u015f kategori yok. Genel Ayarlar > Kategori e\u015fle\u015ftirme b\u00f6l\u00fcm\u00fcnden e\u015fle\u015ftirin.")
        return df.iloc[0:0]
    st.markdown("**G\u00f6nderilecek kategoriler**")
    tumu = st.checkbox("T\u00fcm kategorileri i\u015faretle", value=True, key=f"{pid}_kat_tumu")
    tablo = pd.DataFrame({
        "G\u00f6nder": [bool(tumu)] * len(gosterilen),
        "Kategori": gosterilen,
        "\u00dcr\u00fcn": [int(adet[k]) for k in gosterilen],
        "E\u015fle\u015fme": ["Kay\u0131tl\u0131" if esl.get(k) else "Varsay\u0131lan" for k in gosterilen],
    })
    duz = st.data_editor(tablo, hide_index=True, height=min(420, 40 + 35 * len(tablo)),
                         disabled=["Kategori", "\u00dcr\u00fcn", "E\u015fle\u015fme"], key=f"{pid}_kat_ed_{bool(tumu)}")
    secilen = set(duz.loc[duz["G\u00f6nder"], "Kategori"])
    st.caption(f"{len(secilen)}/{len(gosterilen)} kategori i\u015faretli. Yaln\u0131zca i\u015faretlenenler g\u00f6nderilir.")
    return df[ana.isin(secilen).values]


def toplu_urun_paneli(pid):
    """\u00dcr\u00fcn OLU\u015eTURMA (N11, \u0130defix, Trendruum)."""
    ad = PAZAR_AD[pid]
    if not pazar_bagli(ayarlar, pid):
        st.warning(f"{ad} API bilgileri eksik. 'Genel Ayarlar\u0131' sayfas\u0131ndan girin.")
        return
    st.info("Marka/kategori/KDV ayarlar\u0131 ve kategori e\u015fle\u015ftirmesi i\u00e7in 'Genel Ayarlar\u0131' sayfas\u0131n\u0131 kullan\u0131n.")
    df = secili_urunler(urunleri_oku(), pid)
    if not df.empty and st.checkbox("Sadece stokta olanlar", value=True, key=f"{pid}_stoklu"):
        df = df[df["stok"] > 0]
    kara = kara_liste_maskesi(ayarlar, df)
    if kara.any():
        st.caption(f"\U0001f6ab Kara listedeki {int(kara.sum())} \u00fcr\u00fcn g\u00f6nderim d\u0131\u015f\u0131 b\u0131rak\u0131ld\u0131.")
        df = df[~kara]
    df = kategori_secimi_uygula(pid, df)
    mod = st.selectbox("G\u00f6nderim Modu", ["Tek \u00fcr\u00fcn (Test)", "T\u00fcm \u00dcr\u00fcnler"], key=f"{pid}_mod")
    df = fiyat_artis_uygula(ayarlar, pid, df)
    uretici = {
        "n11": n11_urun_listesi, "idefix": idefix_urun_listesi, "trendruum": trendruum_urun_listesi,
        "ptt": ptt_urun_listesi, "hb": hb_urun_listesi,
    }[pid]
    if mod.startswith("Tek"):
        aranan = st.text_input("Test i\u00e7in \u00fcr\u00fcn ara (ad veya barkod)", key=f"{pid}_tek_ara",
                               help="\u00d6rnek: ASUS ya da Depo2-006.NOTE.ASUS.B1-I5-3D. Bo\u015f b\u0131rak\u0131rsan\u0131z listenin ilk \u00fcr\u00fcn\u00fc se\u00e7ilir.")
        if aranan.strip():
            q = tr_norm(aranan.strip())
            eslesen = df[df["urun_adi"].map(tr_norm).str.contains(q, regex=False) | df["barkod"].astype(str).map(tr_norm).str.contains(q, regex=False)]
            if eslesen.empty:
                st.warning("Aramaya uyan \u00fcr\u00fcn yok (stokta olmayanlar ve kara listedekiler listede olmaz).")
                return
            eslesen = eslesen.head(50)
            etiketler = [f"{r['urun_adi'][:70]} | {r['barkod']} | {r['satis_fiyati']:.2f} TL | stok {int(r['stok'])}" for _, r in eslesen.iterrows()]
            secim = st.selectbox(f"{len(eslesen)} \u00fcr\u00fcn bulundu, birini se\u00e7in", range(len(etiketler)), format_func=lambda i: etiketler[i], key=f"{pid}_tek_sec")
            df = eslesen.iloc[[secim]]
        else:
            try:
                bulunan, sira = ilk_gonderilebilir(df, pid, uretici)
            except ValueError as e:
                st.error(str(e))
                return
            if bulunan is not None:
                df = bulunan
                if sira > 0:
                    st.caption(f"Listenin ilk {sira} \u00fcr\u00fcn\u00fc g\u00f6nderilemedi\u011fi i\u00e7in g\u00f6nderilebilen ilk \u00fcr\u00fcn se\u00e7ildi.")
            else:
                df = df.head(1)
    try:
        liste, atlanan = uretici(df, ayarlar)
    except ValueError as e:
        st.error(str(e))
        return
    st.write(f"G\u00f6nderilecek \u00fcr\u00fcn: **{len(liste):,}** (Atlanan: {atlanan} \u2014 g\u00f6rsel/fiyat/barkod/kategori eksik)")
    if atlanan:
        neden = atlama_nedenleri(df, pid)
        if neden:
            st.caption("Atlanma nedenleri: " + neden)
    if not liste:
        if mod.startswith("Tek"):
            st.warning("G\u00f6nderilebilir \u00fcr\u00fcn bulunamad\u0131. Kategori e\u015fle\u015ftirmesini yap\u0131n ya da Genel Ayarlar'da 'E\u015fle\u015fmesi olmayan \u00fcr\u00fcnleri de varsay\u0131lan kategoriye koy'u a\u00e7\u0131p tek \u00fcr\u00fcnle deneyin.")
        return
    with st.expander("\U0001f50e \u0130lk \u00fcr\u00fcn\u00fcn g\u00f6nderilecek JSON'u (pazar yeri dok\u00fcman\u0131yla kar\u015f\u0131la\u015ft\u0131r\u0131n)"):
        st.json(liste[0])
    onay = st.checkbox("G\u00f6ndermeyi onayl\u0131yorum", key=f"{pid}_onay")
    if gen(st.button, f"\U0001f680 {ad}'e \u00dcr\u00fcnleri G\u00f6nder", type="primary", key=f"{pid}_toplu_btn", disabled=not onay):
        pbar, log_k = st.progress(0.0), st.empty()

        def ilerleme(p, loglar):
            pbar.progress(min(p, 1.0))
            kod_goster(log_k, "\n".join(loglar[-12:]))

        try:
            gonder = {"n11": n11_urun_gonder, "idefix": idefix_gonder, "trendruum": trendruum_gonder, "ptt": ptt_urun_gonder, "hb": hb_urun_gonder}[pid]
            ok, hata, loglar = gonder(ayarlar, liste, ilerleme)
        except Exception as e:
            log_yaz(ad, "HATA", f"\u00dcr\u00fcn g\u00f6nderimi: {e}")
            st.error(f"Hata: {e}")
            return
        dur = [x for x in loglar if x.startswith("\u26d4")]
        if dur:
            st.error(dur[0])
        log_yaz(ad, "OK" if hata == 0 else ("KISM\u0130" if ok else "HATA"), f"\u00dcr\u00fcn olu\u015fturma: {ok} \u00fcr\u00fcn iletildi, {hata} \u00fcr\u00fcn hatal\u0131.")
        (st.success if hata == 0 else st.warning)(f"{ok} \u00fcr\u00fcn iletildi, {hata} \u00fcr\u00fcn hatal\u0131. (API kabul\u00fc = \u00fcr\u00fcn onay\u0131 de\u011fildir; pazar yeri panelinden kontrol edin.)")


def pazar_ozet(pid):
    """Sistem kayitlarina gore pazar yeri ozeti (pazar yerinin canli sayimi degildir)."""
    with closing(baglan()) as c:
        d = pd.read_sql("SELECT barkod, durum, zaman FROM pazar_durum WHERE pazar=?", c, params=(pid,))
    if d.empty:
        st.caption("Bu pazar yerine hen\u00fcz \u00fcr\u00fcn g\u00f6nderilmedi; g\u00f6nderimden sonra burada durum \u00f6zeti \u00e7\u0131kacak.")
        return
    u = urunleri_oku()
    stok = u.groupby("barkod")["stok"].max() if not u.empty else pd.Series(dtype=int)
    m = d.copy()
    m["stok"] = m["barkod"].astype(str).map(stok)
    esik = _i(ayarlar.get("kritik_esik")) or 3
    ok = m[m["durum"] == "ok"]
    st.markdown("**\U0001f4ca Durum \u00f6zeti** (sistem kay\u0131tlar\u0131na g\u00f6re)")
    a, b, c3, d4, e5 = st.columns(5)
    a.metric("G\u00f6nderilen", f"{len(ok):,}")
    b.metric("Hatal\u0131", f"{int((m['durum'] == 'hata').sum()):,}")
    c3.metric("T\u00fckenen", f"{int((ok['stok'] == 0).sum()):,}")
    d4.metric(f"Az kalan (\u2264{esik})", f"{int(ok['stok'].between(1, esik).sum()):,}")
    e5.metric("Sistemde yok", f"{int(ok['stok'].isna().sum()):,}")
    son = ok["zaman"].max() if not ok.empty else None
    gonderilmeyen = max(int(u["barkod"].nunique()) - len(ok), 0) if not u.empty else 0
    st.caption(f"Son ba\u015far\u0131l\u0131 g\u00f6nderim: {son or '-'} \u00b7 Sistemde olup bu pazara hi\u00e7 gitmeyen: {gonderilmeyen:,}")


def pazar_islemler(pid):
    p = PAZAR[pid]
    ad = p["ad"]
    bagli = pazar_bagli(ayarlar, pid)
    st.title(f"{p['ikon']} {ad} \u0130\u015flemleri")
    if not bagli:
        st.warning("API bilgileri eksik: 'Genel Ayarlar\u0131' sayfas\u0131ndan girip kaydedin.")
    pazar_ozet(pid)

    k = f"islem_{pid}"
    with closing(baglan()) as c:
        ted_liste = [r[0] for r in c.execute("SELECT DISTINCT tedarikci FROM urunler WHERE tedarikci IS NOT NULL ORDER BY 1")]
    secili_ted = None
    if ted_liste:
        secili_ted = st.multiselect("Stok/fiyat g\u00f6nderilecek tedarik\u00e7iler", ted_liste, default=ted_liste, key=f"{pid}_gond_ted")
    c1, c2, c3 = st.columns(3)
    if gen(c1.button, "\U0001f504 Tam Senkronizasyon", key=f"b1_{pid}", type="primary", disabled=not bagli, help="\u00d6nce tedarik\u00e7i XML'lerini yeniler, sonra stok/fiyat\u0131 bu pazara g\u00f6nderir."):
        st.session_state[k] = None
        with st.spinner("Tedarik\u00e7iler g\u00fcncelleniyor..."):
            for tad, ok_, msg in tumunu_senkronla(oto=False):
                (st.success if ok_ else st.error)(f"{tad}: {msg}")
        gonder_ve_goster(pid, secili_ted)
    if gen(c2.button, "\u26a0\ufe0f Kritik Stok S\u0131f\u0131rla", key=f"b2_{pid}"):
        st.session_state[k] = "kritik"
    if gen(c3.button, "\U0001f522 T\u00fcm Stok/Fiyatlar\u0131 G\u00fcncelle", key=f"b3_{pid}", disabled=not bagli, help="Veritaban\u0131ndaki mevcut stok/fiyat\u0131 bu pazara g\u00f6nderir."):
        st.session_state[k] = None
        gonder_ve_goster(pid, secili_ted)

    if pid in ("n11", "idefix", "trendruum", "ptt", "hb"):
        if gen(st.button, "\U0001f4e4 Toplu \u00dcr\u00fcn Olu\u015ftur / G\u00f6nder", key=f"b4_{pid}"):
            st.session_state[k] = "toplu"

    islem = st.session_state.get(k)
    if islem == "kritik":
        with st.container(border=True):
            esik = st.number_input("Kritik stok e\u015fi\u011fi", 1, 50, _i(ayarlar.get("kritik_esik")) or 3, key=f"ke_{pid}")
            with closing(baglan()) as c:
                df_k = pd.read_sql(
                    "SELECT barkod, stok, satis_fiyati FROM urunler WHERE CAST(stok AS INTEGER) > 0 AND CAST(stok AS INTEGER) <= ?",
                    c, params=(int(esik),))
            st.write(f"Etkilenecek \u00fcr\u00fcn: **{len(df_k):,}**")
            st.caption("Not: Veritaban\u0131ndaki stoklar da 0'lan\u0131r; bir sonraki tedarik\u00e7i senkronizasyonunda tedarik\u00e7i sto\u011funa g\u00f6re yeniden hesaplan\u0131r.")
            onay = st.checkbox("Onayl\u0131yorum", key=f"ko_{pid}")
            if st.button("S\u0131f\u0131rla ve G\u00f6nder", key=f"kg_{pid}", disabled=not (onay and bagli and len(df_k) > 0)):
                try:
                    df_k["barkod"] = df_k["barkod"].astype(str)
                    df_k["stok"] = 0
                    ok, hata, _ = pazara_gonder(ayarlar, pid, df_k)
                    if ok > 0:  # \u00f6nce pazara gitsin; ba\u015far\u0131s\u0131zsa veritaban\u0131n\u0131 de\u011fi\u015ftirme
                        with closing(baglan()) as c:
                            c.execute("UPDATE urunler SET stok = 0 WHERE CAST(stok AS INTEGER) > 0 AND CAST(stok AS INTEGER) <= ?", (int(esik),))
                            c.commit()
                    (st.success if hata == 0 else st.warning)(f"{ok} \u00fcr\u00fcn s\u0131f\u0131rland\u0131, {hata} hata.")
                except Exception as e:
                    st.error(f"Hata: {e}")
    elif islem == "toplu":
        toplu_urun_paneli(pid)

    if pid == "ptt" and bagli:
        with st.expander("\U0001f4cb PTT g\u00f6nderim sonucunu sorgula (trackingId)"):
            kayitli = list(ayarlar.get("ptt_takip") or [])
            sec = st.selectbox("Son g\u00f6nderimlerin trackingId'leri", [""] + kayitli, key="ptt_takip_sec")
            elle = st.text_input("veya trackingId yap\u0131\u015ft\u0131r\u0131n", key="ptt_takip_elle")
            if gen(st.button, "\U0001f50e Sonucu getir", key="ptt_takip_btn"):
                try:
                    kod, metin_ = ptt_sonuc_sorgula(ayarlar, elle or sec)
                    (st.success if kod == 200 else st.error)(f"HTTP {kod}")
                    oz = ptt_sonuc_ozet(metin_)
                    if oz:
                        st.write(oz["ozet"])
                        if oz["satirlar"]:
                            st.dataframe(pd.DataFrame(oz["satirlar"]), hide_index=True)
                    with st.expander("Ham yan\u0131t"):
                        st.code(metin_)
                except Exception as e:
                    st.error(f"Hata: {e}")

    with closing(baglan()) as c:
        d = pd.read_sql("SELECT durum, COUNT(*) AS adet FROM pazar_durum WHERE pazar=? GROUP BY durum", c, params=(pid,))
    if not d.empty:
        st.caption("Son g\u00f6nderim durumu (barkod baz\u0131nda): " + ", ".join(f"{r.durum}: {r.adet}" for r in d.itertuples()))


def gonder_ve_goster(pid, tedarikciler=None):
    ad = PAZAR_AD[pid]
    pbar, log_k = st.progress(0.0), st.empty()

    def ilerleme(p, loglar):
        pbar.progress(min(p, 1.0))
        kod_goster(log_k, "\n".join(loglar[-8:]))

    try:
        df_g = urunleri_oku()
        if tedarikciler is not None:
            if not tedarikciler:
                st.warning("Hi\u00e7 tedarik\u00e7i se\u00e7ilmedi.")
                return
            df_g = df_g[df_g["tedarikci"].isin(tedarikciler)]
        with st.spinner(f"{ad} stok/fiyat g\u00f6nderiliyor..."):
            ok, hata, _ = pazara_gonder(ayarlar, pid, df_g, ilerleme)
        if ok == 0 and hata == 0:
            st.warning("G\u00f6nderilecek \u00fcr\u00fcn bulunamad\u0131 (\u00f6nce tedarik\u00e7i senkronizasyonu yap\u0131n / fiyat\u0131 olmayan \u00fcr\u00fcnler atlan\u0131r).")
        else:
            (st.success if hata == 0 else st.warning)(f"{ad}: {ok} \u00fcr\u00fcn iletildi, {hata} hata. (API kabul\u00fc = pazar yerinde i\u015flendi demek de\u011fildir.)")
    except Exception as e:
        st.error(f"Hata: {e}")


def pazar_ayar(pid):
    p = PAZAR[pid]
    st.title(f"\u2699\ufe0f {p['ad']} Genel Ayarlar\u0131")
    st.subheader("\U0001f511 API Kimlik Bilgileri")
    with st.form(f"kimlik_form_{pid}"):
        yeni = {}
        for etk, anahtar, parola in PAZAR_KIMLIK[pid]:
            yeni[anahtar] = st.text_input(etk, value=ayarlar["kimlik"].get(anahtar, ""), type="password" if parola else "default")
        if gen(st.form_submit_button, "\U0001f4be Kimlik bilgilerini kaydet", type="primary"):
            for a, v in yeni.items():
                ayarlar["kimlik"][a] = v.strip()
            ayar_yaz(ayarlar)
            st.success("Kaydedildi.")
    st.caption("G\u00fcvenlik i\u00e7in anahtarlar\u0131 ortam de\u011fi\u015fkeni (\u00f6rn. N11_KEY) veya Streamlit secrets ile de verebilirsiniz; bunlar dosyadakinden \u00f6nceliklidir.")
    if gen(st.button, "\U0001f50c Ba\u011flant\u0131 Testi", key=f"bt_{pid}"):
        ok_, msg_ = baglanti_testi(ayarlar, pid)
        (st.success if ok_ else st.error)(msg_)

    st.divider()
    bayrak = OTO_BAYRAK[pid]
    oto = st.toggle(f"\U0001f916 {p['ad']} stok/fiyat\u0131 her senkronizasyondan sonra otomatik g\u00fcncelle", value=bool(ayarlar.get(bayrak)), key=f"oto_{pid}")
    if oto != bool(ayarlar.get(bayrak)):
        ayarlar[bayrak] = oto
        ayar_yaz(ayarlar)
    st.divider()
    pazar_ayar_formu(pid)
    if pid == "ptt":
        with st.expander("\U0001f50e PTT kategori ID bulucu (kategori ad\u0131ndan ID bul)"):
            ptt_kategori_bulucu()
    if pid == "hb":
        with st.expander("\U0001f50e Hepsiburada kategori ID bulucu (kategori ad\u0131ndan ID bul)"):
            hb_kategori_bulucu()
    if pid == "trendruum":
        with st.expander("\U0001f50e Trendruum kategori ID bulucu (kategori ad\u0131ndan ID bul)"):
            trendruum_kategori_bulucu()
    if pid in ("n11", "idefix", "trendruum", "ptt", "hb"):
        with st.expander("\U0001f5c2\ufe0f Kategori e\u015fle\u015ftirme (tedarik\u00e7i kategorisi \u2192 pazar yeri kategori ID)"):
            kategori_esleme_editoru(pid)


def pazar_siparis(pid):
    p = PAZAR[pid]
    st.title(f"{p['ikon']} {p['ad']} Sipari\u015f Y\u00f6netimi")
    if pid not in ("trendyol", "n11", "hb", "trendruum"):
        st.info(f"{p['ad']} i\u00e7in sipari\u015f \u00e7ekme hen\u00fcz desteklenmiyor.")
        return
    if gen(st.button, "\U0001f504 Sipari\u015fleri Yeniden \u00c7ek", type="primary", key=f"sp_cek_{pid}"):
        try:
            with st.spinner("Sipari\u015fler \u00e7ekiliyor..."):
                st.session_state[f"sip_{pid}"] = siparis_cek(ayarlar, pid)
            st.success("Sipari\u015fler g\u00fcncellendi.")
        except Exception as e:
            st.error(f"Hata: {e}")
    liste = st.session_state.get(f"sip_{pid}")
    if liste is None:
        st.info("Hen\u00fcz sipari\u015f \u00e7ekilmedi.")
        return
    if not liste:
        st.info("A\u00e7\u0131k sipari\u015f bulunamad\u0131.")
        return
    st.metric("Sipari\u015f say\u0131s\u0131", len(liste))
    for o in liste:
        with st.container(border=True):
            st.markdown(f"### Sipari\u015f No: {o['no']} \u00b7 {o['tarih']}")
            st.markdown(f"**Durum:** {DURUM_ETIKET.get(o['durum'], o['durum'])} | **Al\u0131c\u0131:** {o['alici']} | **Tutar:** {o.get('tutar')} \u20ba")
            st.markdown(f"**Adres:** {o['adres']}")
            if o.get("kargo") or o.get("barkod"):
                st.markdown(f"**Kargo:** {o.get('kargo', '')} {o.get('barkod', '')}")
            for u in o.get("urunler", []):
                st.markdown(f"- {u['ad']} \u2014 `{u['sku']}` \u00d7 {u['adet']}")


def urunler_sayfasi():
    st.title("\U0001f4e6 Sistemdeki \u00dcr\u00fcnler")
    for mesaj in st.session_state.pop("urun_senk_sonuc", []) or []:
        (st.success if mesaj[1] else st.error)(f"{mesaj[0]}: {mesaj[2]}")
    for mesaj in st.session_state.pop("urun_sifir_sonuc", []) or []:
        st.info(mesaj)
    df = urunleri_oku()
    if df.empty:
        st.warning("Sistemde hen\u00fcz kay\u0131tl\u0131 \u00fcr\u00fcn bulunmuyor.")
        if gen(st.button, "\U0001f504 Stoklar\u0131 tedarik\u00e7iden \u00e7ek", key="urun_stok_cek_bos"):
            st.session_state["urun_senk_sonuc"] = tumunu_senkronla(oto=False)
            st.rerun()
        return
    kilit = stok_sifir_kume(ayarlar)
    esik = _i(ayarlar.get("kritik_esik")) or 3
    c1, c2 = st.columns([1, 2])
    secenek = ["T\u00fcm Bayiler"] + sorted(df["tedarikci"].dropna().unique().tolist())
    secili = c1.selectbox("\U0001f3ec Tedarik\u00e7i / Bayi", secenek)
    ara = c2.text_input("\U0001f50d \u00dcr\u00fcn ad\u0131 veya barkod ara", "")
    d1, d2 = st.columns([1, 2])
    durum = d1.selectbox("Stok durumu", ["T\u00fcm\u00fc", "Stokta", "T\u00fckenen", f"Kritik (\u2264{esik})", "Elle s\u0131f\u0131rlananlar"])
    gorunum = d2.radio("G\u00f6r\u00fcn\u00fcm", ["Tablo (kayd\u0131rmal\u0131)", "Kart (k\u00fc\u00e7\u00fck g\u00f6rsel)"], horizontal=True)

    f = df
    if secili != "T\u00fcm Bayiler":
        f = f[f["tedarikci"] == secili]
    if ara:
        n = tr_norm(ara)
        f = f[f["urun_adi"].astype(str).map(tr_norm).str.contains(n, regex=False) | f["barkod"].astype(str).map(tr_norm).str.contains(n, regex=False)]
    if durum == "Stokta":
        f = f[f["stok"] > 0]
    elif durum == "T\u00fckenen":
        f = f[f["stok"] <= 0]
    elif durum.startswith("Kritik"):
        f = f[f["stok"].between(1, esik)]
    elif durum == "Elle s\u0131f\u0131rlananlar":
        f = f[f["barkod"].astype(str).isin(kilit)]
    f = f.reset_index(drop=True)

    top1, top2 = st.columns([2, 1])
    top1.info(f"Toplam **{len(f):,}** \u00fcr\u00fcn listeleniyor. Elle s\u0131f\u0131rlanm\u0131\u015f: **{len(kilit):,}**")
    if gen(top2.button, "\U0001f504 Stoklar\u0131 tedarik\u00e7iden \u00e7ek", key="urun_stok_cek",
           help="Se\u00e7ili bayinin (ya da t\u00fcm bayilerin) XML'ini yeniler ve stoklar\u0131 g\u00fcncel haline getirir."):
        with st.spinner("Tedarik\u00e7i stoklar\u0131 \u00e7ekiliyor..."):
            if secili != "T\u00fcm Bayiler" and secili in ayarlar["tedarikciler"]:
                try:
                    sayi = tedarikci_senkron(secili, ayarlar["tedarikciler"][secili], esik, _i(ayarlar.get("stok_ust_sinir"), 50))
                    log_yaz(secili, "OK", f"{sayi} \u00fcr\u00fcn g\u00fcncellendi")
                    st.session_state["urun_senk_sonuc"] = [(secili, True, f"{sayi} \u00fcr\u00fcn")]
                except Exception as e:
                    st.session_state["urun_senk_sonuc"] = [(secili, False, str(e))]
            else:
                st.session_state["urun_senk_sonuc"] = tumunu_senkronla(oto=False)
        st.rerun()

    if gorunum.startswith("Tablo"):
        v = pd.DataFrame({
            "G\u00f6rsel": f["gorsel"].where(f["gorsel"].astype(str).str.startswith("http"), None),
            "\u00dcr\u00fcn": f["urun_adi"], "Barkod": f["barkod"], "Tedarik\u00e7i": f["tedarikci"], "Stok": f["stok"],
            "Al\u0131\u015f": f["alis_fiyati"].map(_f).round(2), "Sat\u0131\u015f": f["satis_fiyati"].map(_f).round(2),
            "Kilit": f["barkod"].astype(str).isin(kilit).map({True: "\U0001f512", False: ""}),
        })
        ayar_kol = {
            "G\u00f6rsel": st.column_config.ImageColumn("G\u00f6rsel", width="small"),
            "\u00dcr\u00fcn": st.column_config.TextColumn("\u00dcr\u00fcn", width="large"),
            "Al\u0131\u015f": st.column_config.NumberColumn("Al\u0131\u015f", format="%.2f \u20ba"),
            "Sat\u0131\u015f": st.column_config.NumberColumn("Sat\u0131\u015f", format="%.2f \u20ba"),
        }
        secilen = []
        try:
            olay = st.dataframe(v, hide_index=True, height=620, column_config=ayar_kol,
                                on_select="rerun", selection_mode="multi-row", key="urun_tablo")
            secilen = list(olay.selection.rows)
        except TypeError:
            st.dataframe(v, hide_index=True, height=620, column_config=ayar_kol)
            st.caption("Bu Streamlit s\u00fcr\u00fcm\u00fcnde sat\u0131r se\u00e7imi yok; stok s\u0131f\u0131rlamak i\u00e7in barkodu a\u015fa\u011f\u0131ya yaz\u0131n.")
        st.caption("Sat\u0131r\u0131n solundaki kutuyla \u00fcr\u00fcn se\u00e7in (birden fazla se\u00e7ebilirsiniz). Kayd\u0131rd\u0131k\u00e7a t\u00fcm liste a\u00e7\u0131l\u0131r; sayfa numaras\u0131 yok.")
        sec_barkod = [str(f.loc[i, "barkod"]) for i in secilen if i < len(f)]
        if not sec_barkod:
            elle = st.text_input("veya sto\u011funu s\u0131f\u0131rlamak istedi\u011finiz barkodlar (virg\u00fclle)", key="sifir_elle")
            sec_barkod = [x.strip() for x in elle.split(",") if x.strip()]
        if sec_barkod:
            with st.container(border=True):
                st.write(f"Se\u00e7ili \u00fcr\u00fcn: **{len(sec_barkod)}**")
                gonder = st.checkbox("Ba\u011fl\u0131 pazar yerlerine de hemen g\u00f6nder", value=True, key="sifir_gonder")
                onay = st.checkbox("Onayl\u0131yorum", key="sifir_onay")
                k1, k2 = st.columns(2)
                if gen(k1.button, "\U0001f512 Sto\u011fu s\u0131f\u0131rla ve kilitle", key="sifir_btn", disabled=not onay):
                    sonuc = stok_sifirla(ayarlar, sec_barkod, gonder)
                    st.session_state["urun_sifir_sonuc"] = [f"{len(sec_barkod)} \u00fcr\u00fcn\u00fcn sto\u011fu s\u0131f\u0131rland\u0131 ve kilitlendi."] + [
                        f"{ad}: {ok} g\u00f6nderildi" + (f", hata: {h}" if h else "") for ad, ok, h in sonuc]
                    st.rerun()
                if gen(k2.button, "\U0001f513 Kilidi kald\u0131r", key="kilit_kaldir_btn"):
                    n = stok_kilidi_kaldir(ayarlar, sec_barkod)
                    st.session_state["urun_sifir_sonuc"] = [f"{n} \u00fcr\u00fcn\u00fcn kilidi kald\u0131r\u0131ld\u0131. Stok, bir sonraki tedarik\u00e7i \u00e7eki\u015finde geri gelir ('Stoklar\u0131 tedarik\u00e7iden \u00e7ek')."]
                    st.rerun()
    else:
        st.caption("K\u00fc\u00e7\u00fck g\u00f6rselli kart g\u00f6r\u00fcn\u00fcm\u00fc; daha fazlas\u0131 i\u00e7in a\u015fa\u011f\u0131daki d\u00fc\u011fmeyi kullan\u0131n.")
        sayi = st.session_state.setdefault("urun_kart_sayi", 24)
        for idx, row in f.head(sayi).iterrows():
            with st.container(border=True):
                g, y = st.columns([1, 4])
                img = row.get("gorsel", "")
                if img and str(img).startswith("http"):
                    g.image(img, width=70)
                else:
                    g.write("\U0001f4f7")
                alis, satis = _f(row.get("alis_fiyati")), _f(row.get("satis_fiyati"))
                kil = " \U0001f512" if str(row.get("barkod")) in kilit else ""
                ad_k = row.get("urun_adi") or "\u0130simsiz \u00dcr\u00fcn"
                y.markdown(f"**{ad_k}**{kil}")
                y.caption(f"Barkod `{row.get('barkod', '-')}` \u00b7 {row.get('tedarikci', '-')} \u00b7 Stok **{row.get('stok', 0)}** \u00b7 Al\u0131\u015f {alis:.2f} \u20ba \u00b7 Sat\u0131\u015f {satis:.2f} \u20ba")
        if len(f) > sayi and gen(st.button, f"\u2b07\ufe0f Daha fazla g\u00f6ster ({min(sayi, len(f))}/{len(f)})", key="urun_daha_fazla"):
            st.session_state["urun_kart_sayi"] = sayi + 48
            st.rerun()
    if kilit:
        with st.expander(f"\U0001f512 Elle s\u0131f\u0131rlanm\u0131\u015f \u00fcr\u00fcnler ({len(kilit)})"):
            kd = pd.DataFrame({"Barkod": sorted(kilit), "Kilit zaman\u0131": [ayarlar["stok_sifir"][b] for b in sorted(kilit)]})
            st.dataframe(kd, hide_index=True)


def anasayfa():
    st.title("\U0001f985 \u015eahEntegre - Ma\u011faza ve Pazar Yeri \u00d6zeti")
    df = urunleri_oku()
    esik = _i(ayarlar.get("kritik_esik")) or 3
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Toplam \u00dcr\u00fcn", f"{len(df):,}")
    c2.metric("Stokta Olanlar", f"{int((df['stok'] > 0).sum()):,}" if not df.empty else "0")
    c3.metric(f"Kritik Stok (\u2264{esik})", f"{int(df['stok'].between(1, esik).sum()):,}" if not df.empty else "0")
    c4.metric("Tedarik\u00e7i", len(ayarlar["tedarikciler"]))
    st.markdown("### \U0001f6d2 Pazar Yeri Ba\u011flant\u0131 Durumlar\u0131")
    liste = list(PAZAR.items())
    for i in range(0, len(liste), 2):
        cols = st.columns(2)
        for j in range(2):
            if i + j >= len(liste):
                continue
            pid_, p_ = liste[i + j]
            with cols[j]:
                bagli = pazar_bagli(ayarlar, pid_)
                renk = "#d1fae5" if bagli else "#fee2e2"
                durum = "\U0001f7e2 Anahtarlar tan\u0131ml\u0131" if bagli else "\U0001f534 API Bilgileri Eksik"
                st.markdown(
                    f'<div style="background:{renk}; border-radius:14px; padding:14px; border-left:6px solid {p_["renk"]}; margin-bottom:10px;">'
                    f'<h4 style="margin:0; color:#1e293b; font-size:16px;">{p_["ikon"]} {p_["ad"]}</h4>'
                    f'<p style="margin:6px 0 0 0; font-weight:600; color:#475569; font-size:13px;">{durum}</p></div>',
                    unsafe_allow_html=True,
                )
                if gen(st.button, "Y\u00f6net / \u0130\u015flemler", key=f"kutu_git_{pid_}"):
                    git_pazar(pid_, "islemler")
                    st.rerun()
    st.caption("Not: 'Anahtarlar tan\u0131ml\u0131' yaln\u0131zca bilgilerin girildi\u011fini g\u00f6sterir; ger\u00e7ek do\u011frulama i\u00e7in Genel Ayarlar'daki Ba\u011flant\u0131 Testi'ni kullan\u0131n.")


def main():
    global ayarlar
    db_olustur()
    arka_plan_baslat()
    ayarlar = ayar_oku()  # her \u00e7al\u0131\u015fmada taze: arka plan ve di\u011fer oturumlarla tutarl\u0131

    sifre = sifre_al()
    if "giris_ok" not in st.session_state:
        st.session_state.giris_ok = False
    if not sifre:
        st.session_state.giris_ok = True
    elif not st.session_state.giris_ok and jeton_gecerli(st.query_params.get("t", ""), sifre):
        st.session_state.giris_ok = True
    if not st.session_state.giris_ok:
        giris_ekrani(sifre)

    st.markdown(tema_css(), unsafe_allow_html=True)
    st.session_state.setdefault("sayfa", "Anasayfa")
    st.session_state.setdefault("acik_pazar", None)

    st.sidebar.title("\U0001f985 \u015eahEntegre")
    if sifre:
        gen(st.sidebar.button, "\U0001f6aa \u00c7\u0131k\u0131\u015f Yap", key="btn_cikis_yap", type="secondary", on_click=cikis_yap)
    else:
        st.sidebar.warning("\u26a0\ufe0f APP_PASSWORD tan\u0131ml\u0131 de\u011fil: panel \u015fifresiz a\u00e7\u0131k! API anahtarlar\u0131 risk alt\u0131nda.")
    st.sidebar.markdown("---")
    for kid, etk, _ in ANA_MENU:
        gen(st.sidebar.button, etk, key=f"nav_{kid}", type="primary" if st.session_state["sayfa"] == kid else "secondary", on_click=git, args=(kid,))
    for pid, p in PAZAR.items():
        acik = st.session_state["acik_pazar"] == pid
        ok_ikon = "\u25be" if acik else "\u25b8"
        gen(st.sidebar.button, f"{p['ikon']} {p['ad']}  {ok_ikon}", key=f"navp_{pid}", on_click=ac_kapa, args=(pid,))
        if acik:
            for alt, etk, ik in ALT:
                sid = f"{pid}:{alt}"
                gen(st.sidebar.button, f"{ik} {p['ad']} {etk}", key=f"sub_{pid}_{alt}",
                    type="primary" if st.session_state["sayfa"] == sid else "secondary", on_click=git, args=(sid,))
    gen(st.sidebar.button, "\u2699\ufe0f Ayarlar", key="nav_Ayarlar", type="primary" if st.session_state["sayfa"] == "Ayarlar" else "secondary", on_click=git, args=("Ayarlar",))

    sayfa = st.session_state["sayfa"]
    if sayfa == "Anasayfa":
        anasayfa()
    elif sayfa == "Bildirim":
        st.title("\U0001f514 Bildirimler")
        gunluk_sayfasi()
    elif sayfa == "Urunler":
        urunler_sayfasi()
    elif sayfa == "Kritik":
        st.title("\U0001f504 Oto Kritik Stok")
        st.caption("Bu e\u015fik, her tedarik\u00e7i senkronizasyonunda uygulan\u0131r: stok e\u015fi\u011fin alt\u0131ndaysa 0 g\u00f6nderilir.")
        esik = st.number_input("Kritik stok e\u015fi\u011fi:", 0, 50, _i(ayarlar.get("kritik_esik")))
        if int(esik) != _i(ayarlar.get("kritik_esik")):
            ayarlar["kritik_esik"] = int(esik)
            ayar_yaz(ayarlar)
            st.rerun()
    elif sayfa == "Ayarlar":
        st.title("\u2699\ufe0f Ayarlar")
        t1, t2, t3 = st.tabs(["Tedarik\u00e7iler & XML", "Genel & Yedek", "Senkron G\u00fcnl\u00fc\u011f\u00fc"])
        with t1:
            tedarikci_sayfasi()
        with t2:
            genel_ayarlar(sifre)
        with t3:
            gunluk_sayfasi()
    elif ":" in sayfa:
        pid_, alt_ = sayfa.split(":", 1)
        if pid_ in PAZAR:
            {"siparis": pazar_siparis, "islemler": pazar_islemler, "ayar": pazar_ayar}.get(alt_, pazar_islemler)(pid_)


if __name__ == "__main__":
    main()
