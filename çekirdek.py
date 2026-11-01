"""ŞahEntegre ÇEKİRDEK (arayüzden bağımsız iş mantığı).

Bu dosya Streamlit arayüzünü İÇERMEZ; arayüz app.py içindedir.
Gizli bilgiler için öncelik sırası: ortam değişkeni > st.secrets > ayarlar.json

Bu sürümdeki başlıca stok güvenliği düzeltmeleri:
  * Toplu stok sıfırlama artık ENGELLENMEZ (eskiden "fren" yüzünden pazarda stoksuz ürün kalıyordu).
    Bunun yerine şüpheli/bozuk XML (ürün sayısı ya da stoklu ürün oranı çok düştüyse) senkronu
    baştan reddedilir ve eski veri korunur.
  * Fiyatı 0 gelen ürünün STOĞU yine de pazara gider (son gönderilen fiyat ya da yalnız stok).
  * Tükenen ürünler her gönderimde ilk pakete konur (hız limitine takılsa bile önce onlar gider).
  * Yeni siparişte tedarikçi stoğu yetersizse uyarı (günlük + Telegram) üretilir.
  * Bayat stok koruması: senkron çok gecikirse (isteğe bağlı) tüm pazarlarda stok otomatik 0'lanır.
  * Ham tedarikçi stoğu (stok_ham) ayrı tutulur; kritik eşik değişince yeniden hesaplanır.
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
import zlib
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree.ElementTree import ParseError

try:  # Güvenli XML ayrıştırıcı (billion-laughs vb. saldırılara karşı)
    from defusedxml import ElementTree as ET
except ImportError:  # pragma: no cover
    import xml.etree.ElementTree as ET

import pandas as pd
import requests

try:  # st.secrets desteği (arayüz olmadan da çalışsın)
    import streamlit as st
except ImportError:  # pragma: no cover
    st = None

BASE = Path(__file__).parent
VERI_KLASORU = Path(os.environ.get("SAHENTEGRE_VERI", BASE))
DB_DOSYA = VERI_KLASORU / "metentegre.db"
AYAR_DOSYA = VERI_KLASORU / "ayarlar.json"
KILIT = threading.Lock()
SENKRON_KILIDI = threading.Lock()
DOVIZ_KILIDI = threading.Lock()
MAKS_XML_BOYUT = 300 * 1024 * 1024
OTURUM_SURESI = 12 * 3600
AYAR_UYARI = {"bozuk_yedek": ""}  # bozuk ayar dosyası yedeklendiyse arayüz uyarı gösterir

KIMLIK_ALANLARI = [
    "trendruum_key", "trendruum_secret", "trendruum_brand", "trendruum_category",
    "trendyol_seller_id", "trendyol_key", "trendyol_secret",
    "hb_merchant_id", "hb_user", "hb_pass",
    "idefix_satici_id", "idefix_token", "idefix_secret",
    "n11_key", "n11_secret",
    "cicek_key", "ptt_key", "ptt_token",
    "pazarama_key", "pazarama_secret",
    "telegram_token", "telegram_chat",
]
VARSAYILAN = {
    "tedarikciler": {},
    "kimlik": {},
    "kategori_eslesme": {},
    "kritik_esik": 0,
    "stok_ust_sinir": 0,
    "senkron_saat": 6,
    "senkron_dk": 10,
    "stok_guvenlik_payi": 1,
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
    # --- yeni güvenlik ayarları ---
    "xml_dusus_siniri": 30,        # tedarikçi ürün sayısı bu yüzdeden fazla düşerse senkron reddedilir
    "stok_dusus_siniri": 70,       # stoklu ürün sayısı bu yüzdeden fazla düşerse senkron reddedilir
    "bayat_otomatik_durdur": False,  # senkron çok gecikirse tüm pazarlarda stok 0
    "bayat_durdur_dk": 120,
    "siparis_stok_uyari": True,    # yeni siparişte tedarikçi stoğu yetersizse uyar
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
            # Bozuk dosyayı SESSİZCE ezme: önce yedekle ve arayüzde uyar.
            try:
                yedek = AYAR_DOSYA.with_name(f"ayarlar.bozuk-{int(time.time())}.json")
                AYAR_DOSYA.replace(yedek)
                AYAR_UYARI["bozuk_yedek"] = yedek.name
            except Exception:
                pass
            veri = {}
    if "tedarikciler" not in veri:
        veri["tedarikciler"] = {
            k: v for k, v in veri.items() if isinstance(v, dict) and "link" in v
        }
    for k, v in VARSAYILAN.items():
        veri.setdefault(k, json.loads(json.dumps(v)))
    if not veri.get("senkron_dk_v1"):  # tek seferlik: 6 saatlik aralık yerine 10 dakika
        veri["senkron_dk"] = 10
        veri["senkron_dk_v1"] = True
    if not veri.get("stok_sinirsiz_v1"):  # tek seferlik: eski 50'lik stok sınırı kalktı (0 = sınırsız)
        veri["stok_ust_sinir"] = 0
        veri["stok_sinirsiz_v1"] = True
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


def gizli(ad):
    """Ortam değişkeni > st.secrets (büyük harfli ad)."""
    env = os.environ.get(ad.upper())
    if env and str(env).strip():
        return str(env).strip()
    if st is not None:
        try:
            if ad.upper() in st.secrets and str(st.secrets[ad.upper()]).strip():
                return str(st.secrets[ad.upper()]).strip()
        except Exception:
            pass
    return ""


def kimlik(ayar, ad):
    g = gizli(ad)
    if g:
        return g
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
            alis_fiyati REAL, satis_fiyati REAL, kategori TEXT, stok_ham INTEGER)""")
        kolonlar = {r[1] for r in c.execute("PRAGMA table_info(urunler)")}
        if "stok_ham" not in kolonlar:  # eski veritabanı: ham tedarikçi stoğu kolonu ekle
            c.execute("ALTER TABLE urunler ADD COLUMN stok_ham INTEGER")
            c.execute("UPDATE urunler SET stok_ham = stok")
        c.execute("""CREATE TABLE IF NOT EXISTS senkron_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, zaman TEXT, tedarikci TEXT, durum TEXT, mesaj TEXT)""")
        c.execute("CREATE INDEX IF NOT EXISTS ix_urun ON urunler(tedarikci, barkod)")
        c.execute("CREATE INDEX IF NOT EXISTS ix_urun_barkod ON urunler(barkod)")
        c.execute("""CREATE TABLE IF NOT EXISTS pazar_durum (
            pazar TEXT, barkod TEXT, durum TEXT, zaman TEXT, PRIMARY KEY (pazar, barkod))""")
        c.execute("""CREATE TABLE IF NOT EXISTS pazar_son (
            pazar TEXT, barkod TEXT, stok INTEGER, fiyat REAL, zaman TEXT, PRIMARY KEY (pazar, barkod))""")
        c.execute("""CREATE TABLE IF NOT EXISTS durum_kv (anahtar TEXT PRIMARY KEY, deger TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS siparis_goruldu (
            pazar TEXT, siparis TEXT, zaman TEXT, PRIMARY KEY (pazar, siparis))""")
        c.commit()


def kv_oku(anahtar, varsayilan=None):
    """Arka plan ve arayüzün birlikte kullandığı küçük durum deposu (ayarlar.json yarışını önler)."""
    with closing(baglan()) as c:
        r = c.execute("SELECT deger FROM durum_kv WHERE anahtar = ?", (anahtar,)).fetchone()
    if not r:
        return varsayilan
    try:
        return json.loads(r[0])
    except (TypeError, ValueError):
        return varsayilan


def kv_yaz(anahtar, deger):
    with closing(baglan()) as c:
        c.execute("INSERT OR REPLACE INTO durum_kv (anahtar, deger) VALUES (?, ?)", (anahtar, json.dumps(deger)))
        c.commit()


def takip_oku(ad, ayar=None):
    """İdefix batchRequestId / PTT trackingId listeleri (eski ayarlar.json değeri yedek olarak okunur)."""
    eski = (ayar or {}).get(ad) or []
    return list(kv_oku(f"takip:{ad}", eski) or [])


def takip_ekle(ad, idler, en_fazla=50):
    liste = [str(i) for i in idler if i]
    if not liste:
        return
    onceki = [i for i in takip_oku(ad) if i not in liste]
    kv_yaz(f"takip:{ad}", (onceki + liste)[-en_fazla:])


def log_yaz(tedarikci, durum, mesaj=""):
    with closing(baglan()) as c:
        cur = c.execute(
            "INSERT INTO senkron_log (zaman, tedarikci, durum, mesaj) VALUES (?,?,?,?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), tedarikci, durum, str(mesaj)[:500]),
        )
        if (cur.lastrowid or 0) % 200 == 0:  # her kayıtta değil, ara sıra temizle
            c.execute("DELETE FROM senkron_log WHERE id <= (SELECT MAX(id) FROM senkron_log) - 3000")
        c.commit()


def bildir(mesaj, tekil=None, bekleme_dk=60):
    """Telegram bildirimi (TELEGRAM_TOKEN + TELEGRAM_CHAT ortam değişkeni, secrets ya da Genel Ayarlar).
    Aynı 'tekil' anahtarlı bildirim bekleme süresi dolmadan tekrar gönderilmez. Dönüş: gönderildi mi."""
    try:
        ayar = ayar_oku()
        token, chat = kimlik(ayar, "telegram_token"), kimlik(ayar, "telegram_chat")
        if not token or not chat:
            return False
        if tekil:
            son = kv_oku(f"bildirim:{tekil}")
            if son:
                try:
                    if (datetime.now() - datetime.strptime(son, "%Y-%m-%d %H:%M:%S")).total_seconds() < bekleme_dk * 60:
                        return False
                except ValueError:
                    pass
            kv_yaz(f"bildirim:{tekil}", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": f"ŞahEntegre: {mesaj}"[:3500]}, timeout=15)
        return r.status_code == 200
    except Exception:
        return False


def stok_sifir_kume(ayar):
    return {str(b) for b in (ayar.get("stok_sifir") or {})}


def stok_sifir_maskesi(ayar, df):
    """Elle 'stoku sıfır' yapılmış (kilitli) barkodlar için True döner."""
    if df.empty or "barkod" not in df.columns:
        return pd.Series(False, index=df.index)
    return df["barkod"].astype(str).isin(stok_sifir_kume(ayar))


def _parcala(liste, n=500):
    for i in range(0, len(liste), n):
        yield liste[i:i + n]


def stok_sifirla(ayar, barkodlar, pazarlara_gonder=True):
    """Barkodları kilitler, veritabanında stoğu 0 yapar ve istenirse bağlı pazar yerlerine hemen gönderir.
    Dönüş: [(pazar_adi, ok, hata_ya_da_mesaj), ...]"""
    barkodlar = sorted({str(b).strip() for b in barkodlar if str(b).strip()})
    if not barkodlar:
        return []
    z = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    kilit = ayar.setdefault("stok_sifir", {})
    for b in barkodlar:
        kilit[b] = z
    ayar_yaz(ayar)
    with closing(baglan()) as c:
        for parca in _parcala(barkodlar):
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
        if "stok_ham" in df.columns:
            df["stok_ham"] = pd.to_numeric(df["stok_ham"], errors="coerce").fillna(df["stok"]).astype(int)
    return df


def stoklari_yeniden_hesapla(ayar):
    """Kritik eşik / stok üst sınırı değişince, XML indirmeden ham tedarikçi stoğundan stokları yeniden kurar.
    Elle sıfırlanan (kilitli) ürünler 0 kalır. Dönüş: etkilenen ürün sayısı."""
    esik = max(_i(ayar.get("kritik_esik")), 0)
    ust = stok_ust_degeri(ayar)
    ust_sql = ust if ust > 0 else 2_000_000_000
    with closing(baglan()) as c:
        c.execute("""UPDATE urunler SET stok = CASE
                        WHEN COALESCE(stok_ham, 0) > ? THEN MIN(COALESCE(stok_ham, 0), ?) ELSE 0 END""",
                  (esik, ust_sql))
        kilit = sorted(stok_sifir_kume(ayar))
        for parca in _parcala(kilit):
            c.execute(f"UPDATE urunler SET stok = 0 WHERE barkod IN ({','.join('?' * len(parca))})", parca)
        n = c.execute("SELECT COUNT(*) FROM urunler").fetchone()[0]
        c.commit()
    return n


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
    """Yanıtı okunur özet yapar: JSON ise mesaj + hata metinleri (Türkçe karakterler çözülür)."""
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


def gzip_ac(veri):
    """gzip içeriği boyut sınırıyla açar (gzip bombasına karşı)."""
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    cikti = d.decompress(veri, MAKS_XML_BOYUT + 1)
    if len(cikti) > MAKS_XML_BOYUT:
        raise ValueError("Açılmış XML çok büyük (300 MB üstü).")
    return cikti


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
            adres = url
            for _ in range(6):  # yönlendirmeler elle izlenir; her adım ayrıca doğrulanır
                with requests.get(adres, headers=basliklar, timeout=(20, max(30, float(okuma_sn))),
                                  stream=True, allow_redirects=False) as r:
                    if r.status_code in (301, 302, 303, 307, 308):
                        yeni = r.headers.get("Location")
                        if not yeni:
                            raise ValueError("Yönlendirme adresi boş geldi.")
                        adres = urllib.parse.urljoin(adres, yeni)
                        url_guvenli(adres)
                        continue
                    r.raise_for_status()
                    for p in r.iter_content(1024 * 1024):
                        boyut += len(p)
                        if boyut > MAKS_XML_BOYUT:
                            raise ValueError("XML dosyası çok büyük (300 MB üstü).")
                        parcalar.append(p)
                veri = b"".join(parcalar)
                if veri[:2] == b"\x1f\x8b":
                    veri = gzip_ac(veri)
                return veri
            raise ValueError("Çok fazla yönlendirme.")
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


def stok_ust_degeri(ayar):
    """Stok üst sınırı; 0 ya da boş = sınırsız."""
    try:
        v = int(float(ayar.get("stok_ust_sinir") or 0))
    except (TypeError, ValueError):
        v = 0
    return max(v, 0)


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
    """[[ust_sinir, marj], ...] -> geçerli, sıralı liste. Son satır sınırsız (None) olur."""
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
    """Alış fiyatına göre marj (%) serisi döndürür. Kademe yoksa varsayılan marj."""
    kademe = kademe_temizle(kademe)
    if not kademe:
        return pd.Series([float(varsayilan)] * len(alis), index=alis.index)
    sonuc = pd.Series([kademe[-1][1]] * len(alis), index=alis.index, dtype=float)
    for ust, mj in reversed([r for r in kademe if r[0] is not None]):
        sonuc = sonuc.where(alis > ust, mj)
    return sonuc


VARSAYILAN_HEDEF = [[100, 40.0], [500, 80.0], [2000, 150.0], [None, 300.0]]


def hedef_parametreleri(bilgi):
    c = _f(bilgi.get("h_komisyon"), 20.0) / 100
    t = _f(bilgi.get("h_vergi"), 0.0) / 100
    kdv = _f(bilgi.get("h_kdv"), 20.0) / 100
    gider = _f(bilgi.get("h_kargo"), 150.0) + _f(bilgi.get("h_bayi_kargo"), 15.0) + _f(bilgi.get("h_ek_gider"), 0.0)
    if c >= 0.95 or t >= 0.95:
        raise ValueError("Komisyon ya da vergi oranı çok yüksek.")
    return c, t, kdv, gider


def hedef_fiyat(alis, bilgi):
    """Hedef NET kâr için satış fiyatı: P = (alis + giderler + hedef*(1+kdv)/(1-vergi)) / (1-komisyon).
    Alış fiyatı KDV dahil kabul edilir; komisyon KDV dahil orandır."""
    c, t, kdv, gider = hedef_parametreleri(bilgi)
    hedef = kademeli_marj(alis, bilgi.get("hedef_kademe") or VARSAYILAN_HEDEF, _f(bilgi.get("hedef_net"), 100.0))
    return ((alis + gider + hedef * (1 + kdv) / (1 - t)) / (1 - c)).round(2)


def net_kar_hesapla(satis, alis, bilgi):
    """Verilen satış fiyatında komisyon, kargo, KDV ve vergi düşüldükten sonra kalan net kâr (TL)."""
    c, t, kdv, gider = hedef_parametreleri(bilgi)
    m = satis * (1 - c) - alis - gider
    vergi_sonrasi = m / (1 + kdv)
    return vergi_sonrasi.where(m <= 0, vergi_sonrasi * (1 - t)).round(2)


def ad_temizle(x):
    t = html.unescape(html.unescape(str(x)))
    return re.sub(r"\s+", " ", t).strip()


DOVIZ_TL = {"TL", "TRY", "TRL", "₺"}
DOVIZ_USD = {"USD", "$"}
DOVIZ_SON = {}  # tedarikçi adı -> son senkronizasyondaki para birimi dağılımı


def kesin_sayi(x):
    """Nokta her zaman ondalık ayracıdır (örnek: 1282.275). Sadece kontrollü tedarikçilerde kullanılır."""
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
    """KDV'yi oran olarak döndürür: '20' -> 0.20, '0.2' -> 0.20, '1' -> 0.01 (yüzde 1)."""
    try:
        v = float(str(x).strip().replace(",", "."))
    except ValueError:
        return varsayilan
    if v >= 1:
        v = v / 100
    return v if 0 <= v <= 0.5 else varsayilan


def normalle(tedarikci, df, harita, marj, sabit_ek, kritik_esik=0, stok_ust=0, bilgi=None):
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
    usd = pd.Series([False] * len(df), index=df.index)
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
    if bilgi.get("hedef_aktif"):
        satis = hedef_fiyat(alis, bilgi).where((~bilinmeyen) & (alis > 0), 0.0)
    else:
        satis = (alis * (1 + marj_s / 100) + sabit_ek).where(~bilinmeyen, 0.0)
    ust_s = int(stok_ust) if stok_ust and int(stok_ust) > 0 else None  # None = sınırsız
    ham = kol("stok").map(sayi).clip(lower=0, upper=ust_s).astype(int)
    ham = ham.where(~bilinmeyen, 0)  # para birimi belirsiz ürün asla stokta görünmez
    stok = ham.copy()
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
        "stok_ham": ham,
    })
    out = out[(out["barkod"] != "") & (out["urun_adi"] != "")]
    out = out.drop_duplicates(subset=["barkod"], keep="first")
    out.attrs["doviz_ozet"] = ozet
    return out


def xml_supheli_mi(ayar, ad, df_yeni):
    """Yeni XML eskisine göre şüpheli derecede küçük/boş mu? Şüphe varsa neden metni döner (yoksa '').
    Amaç: yarım inen ya da tüm stokları 0 gelen bozuk XML yüzünden pazarda yanlış toplu işlem yapılmasını önlemek."""
    with closing(baglan()) as c:
        eski_n, eski_stoklu = c.execute(
            "SELECT COUNT(*), COALESCE(SUM(CASE WHEN COALESCE(stok_ham,0) > 0 THEN 1 ELSE 0 END), 0) FROM urunler WHERE tedarikci = ?",
            (ad,)).fetchone()
    yeni_n = len(df_yeni)
    yeni_stoklu = int((df_yeni["stok_ham"] > 0).sum()) if "stok_ham" in df_yeni.columns else int((df_yeni["stok"] > 0).sum())
    dusus = _f(ayar.get("xml_dusus_siniri"), 30.0) / 100
    stok_dusus = _f(ayar.get("stok_dusus_siniri"), 70.0) / 100
    if eski_n >= 50 and yeni_n < eski_n * (1 - dusus):
        return f"ürün sayısı {eski_n:,} → {yeni_n:,} düştü (sınır %{int(dusus * 100)})"
    if eski_stoklu >= 50 and yeni_stoklu < eski_stoklu * (1 - stok_dusus):
        return f"stoklu ürün sayısı {eski_stoklu:,} → {yeni_stoklu:,} düştü (sınır %{int(stok_dusus * 100)})"
    return ""


def tedarikci_senkron(ad, bilgi, kritik_esik=0, stok_ust=0, zorla=False):
    df_ham = xml_oku(indir(bilgi["link"], _f(bilgi.get("zaman_asimi"), 300.0)))
    df = normalle(
        ad, df_ham, bilgi.get("harita", {}),
        float(bilgi.get("marj", 30.0)), float(bilgi.get("sabit_ek", 0.0)),
        kritik_esik, stok_ust, bilgi,
    )
    ozet = df.attrs.get("doviz_ozet")
    if ozet:
        with DOVIZ_KILIDI:
            DOVIZ_SON[ad] = ozet
        log_yaz(ad, "BILGI", f"Para birimi: TL={ozet['tl']}, USD={ozet['usd']}, belirsiz={ozet['bilinmeyen']}")
        if bilgi.get("usd_bekle") and ozet["usd"] == 0:
            raise ValueError("USD urun beklenirken hic USD urun gelmedi. Tedarikci para birimi alanini henuz duzeltmemis olabilir; senkronizasyon durduruldu, eski veri korundu.")
    if df.empty:
        raise ValueError("XML'den geçerli ürün çıkmadı. Alan eşleştirmesini kontrol edin.")
    ayar_son = ayar_oku()
    if not zorla:
        sebep = xml_supheli_mi(ayar_son, ad, df)
        if sebep:
            mesaj = (f"XML şüpheli: {sebep}. Senkron DURDURULDU, eski stok/fiyat verisi korundu. "
                     "Tedarikçi gerçekten ürün kaldırdıysa Ayarlar > Tedarikçiler'den 'Düşüşü kabul et' ile senkronlayın.")
            bildir(f"{ad}: {mesaj}", tekil=f"xml_supheli:{ad}", bekleme_dk=180)
            raise ValueError(mesaj)
    kilit = stok_sifir_kume(ayar_son)
    if kilit:  # elle sıfırlanan ürünler tedarikçi stoğu gelse bile 0 kalır
        df.loc[df["barkod"].astype(str).isin(kilit), "stok"] = 0
    df = fiyat_override_uygula(ayar_son, df)  # elle belirlenen satış fiyatları senkronda ezilmez
    sutunlar = ["gorsel", "tedarikci", "barkod", "urun_adi", "stok", "alis_fiyati", "satis_fiyati", "kategori", "stok_ham"]
    insert_sql = ("INSERT INTO urunler (gorsel, tedarikci, barkod, urun_adi, stok, alis_fiyati, satis_fiyati, kategori, stok_ham) "
                  "VALUES (?,?,?,?,?,?,?,?,?)")
    kayip = 0
    with closing(baglan()) as c:
        try:
            c.execute("BEGIN IMMEDIATE")
            # Tedarikçi XML'inden çıkan ama pazar yerine gönderilmiş ürünleri SİLME: stok 0 olarak tut ki pazarlar da 0'lansın.
            eski_df = pd.read_sql("SELECT " + ", ".join(sutunlar) + " FROM urunler WHERE tedarikci = ?", c, params=(ad,))
            gonderilmis = {str(r[0]) for r in c.execute("SELECT DISTINCT barkod FROM pazar_durum WHERE durum = 'ok'")}
            yeni_b = set(df["barkod"].astype(str))
            if not eski_df.empty:
                eb = eski_df["barkod"].astype(str)
                kayip_df = eski_df[(~eb.isin(yeni_b)) & eb.isin(gonderilmis)].copy()
            else:
                kayip_df = eski_df
            kayip = len(kayip_df)
            if kayip:
                kayip_df["stok"] = 0
                kayip_df["stok_ham"] = 0
            c.execute("DELETE FROM urunler WHERE tedarikci = ?", (ad,))
            c.executemany(insert_sql, df[sutunlar].itertuples(index=False, name=None))
            if kayip:
                c.executemany(insert_sql, kayip_df[sutunlar].itertuples(index=False, name=None))
            c.commit()
        except Exception:
            c.rollback()
            raise
    if kayip:
        log_yaz(ad, "BILGI", f"{kayip} ürün tedarikçi XML'inde artık yok; pazar yerlerinde satışta kalmasın diye stokları 0 yapıldı.")
    kv_yaz(f"son_senkron:{ad}", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    kv_yaz(f"xml_hata:{ad}", 0)
    return len(df)


# --------------------------------------------------------------------------
# Fiyat kuralları ve ortak yardımcılar
# --------------------------------------------------------------------------
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
    """Tedarikçinin güncel marj/kargo/kademe ayarıyla satış fiyatlarını, XML indirmeden,
    kayıtlı alış fiyatından yeniden hesaplar."""
    df = urunleri_oku()
    d = df[df["tedarikci"] == ad].copy()
    if d.empty:
        return 0
    eski = d["satis_fiyati"].map(_f).copy()
    alis = d["alis_fiyati"].map(_f)
    marj_s = kademeli_marj(alis, bilgi.get("kademe") if bilgi.get("kademe_aktif") else None, _f(bilgi.get("marj"), 30.0))
    if bilgi.get("hedef_aktif"):
        yeni = hedef_fiyat(alis, bilgi)
    else:
        yeni = (alis * (1 + marj_s / 100) + _f(bilgi.get("sabit_ek"))).round(2)
    d["satis_fiyati"] = yeni.where(alis > 0, d["satis_fiyati"])
    d = fiyat_override_uygula(ayar_oku(), d)  # elle belirlenen fiyatlar korunur
    degisen = d[(d["satis_fiyati"].map(_f) - eski).abs() > 0.004]
    with closing(baglan()) as c:
        c.executemany("UPDATE urunler SET satis_fiyati = ? WHERE tedarikci = ? AND barkod = ?",
                      [(float(r["satis_fiyati"]), ad, str(r["barkod"])) for _, r in degisen.iterrows()])
        c.commit()
    return len(degisen)


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


def gecerli_barkod(kod):
    k = str(kod).strip()
    return k if k.isdigit() and 8 <= len(k) <= 14 else None


def objectid_mi(v):
    return bool(re.fullmatch(r"[0-9a-fA-F]{24}", str(v or "").strip()))


def urun_ara(f, ara):
    """Ad, tedarikçi barkodu ya da PAZAR YERİNE GİDEN barkod (üretilen/düzeltilen) ile arar."""
    n = tr_norm(ara)
    if not n:
        return f
    pb = f["barkod"].astype(str).map(lambda k: sabit_barkod(k, True) or "")
    esles = (f["urun_adi"].astype(str).map(tr_norm).str.contains(n, regex=False)
             | f["barkod"].astype(str).map(tr_norm).str.contains(n, regex=False)
             | pb.map(tr_norm).str.contains(n, regex=False))
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
    """Elle belirlenen (sabit) satış fiyatları, marj/kargo/artış hesabından sonra kesin fiyat olur."""
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
    """Seçilen ürünlerin satış fiyatını elle sabitler; istenirse bağlı pazar yerlerine hemen gönderir."""
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
        for parca in _parcala(barkodlar):
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


def paketle(kayitlar, paket, fn, ilerleme=None, ad="", durdur=0, bekle=0.0):
    """kayitlar: [(anahtar, veri)]. fn(veri_listesi) -> (basarili_mi, mesaj).
    Her paketin sonucu GERÇEK HTTP durumuna göre sayılır."""
    ok_k, hata_k, loglar = [], [], []
    ust_uste = 0
    toplam = max(1, -(-len(kayitlar) // paket))
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
                if kalan > 0:
                    loglar.append(f"⛔ {ad}: üst üste {durdur} paket hata aldı, gönderim DURDURULDU. "
                                  f"Gönderilmeyen kalan kayıt: {kalan}. Hata mesajını düzeltip tekrar deneyin.")
                if ilerleme:
                    ilerleme(1.0, loglar)
                break
        if ilerleme:
            ilerleme(no / toplam, loglar)
        if bekle and i + paket < len(kayitlar):
            time.sleep(bekle)
    return ok_k, hata_k, loglar


def _sonuc(pid, ok_k, hata_k, loglar, atlanan=0, tukenen_atlanan=0):
    try:
        pazar_isaretle(pid, ok_k, hata_k)
    except Exception:
        pass
    if atlanan:
        loglar.append(f"ℹ️ {atlanan} ürün eksik bilgi (fiyat/barkod) nedeniyle atlandı.")
    if tukenen_atlanan:
        # En tehlikeli durum: stoğu 0 olan ürün gönderilemedi, pazarda eski stokla satışta kalabilir.
        mesaj = (f"{PAZAR_AD.get(pid, pid)}: {tukenen_atlanan} TÜKENEN ürünün stoğu fiyat bilgisi olmadığı için "
                 "pazar yerine GÖNDERİLEMEDİ; bu ürünler pazarda eski stokla satışta kalmış olabilir.")
        loglar.append("⚠️ " + mesaj)
        log_yaz(PAZAR_AD.get(pid, pid), "UYARI", mesaj)
        bildir(mesaj, tekil=f"tukenen_atlandi:{pid}", bekleme_dk=120)
    return len(ok_k), len(hata_k), loglar


def kayit_listesi(df):
    return df.to_dict("records") if not df.empty else []


def son_fiyatlar(pid):
    """Bu pazara en son başarıyla gönderilen fiyatlar {barkod: fiyat}. Fiyatı olmayan (0) üründe
    stok yine de gönderilebilsin diye yedek fiyat olarak kullanılır."""
    with closing(baglan()) as c:
        return {str(r[0]): float(r[1]) for r in c.execute(
            "SELECT barkod, fiyat FROM pazar_son WHERE pazar = ? AND barkod != '__tam__' AND fiyat > 0", (pid,))}


def fiyat_belirle(r, son):
    """(fiyat, yedekten_mi): güncel fiyat yoksa son gönderilen fiyat; o da yoksa (0.0, True)."""
    f = round(_f(r.get("satis_fiyati")), 2)
    if f > 0:
        return f, False
    return round(son.get(str(r["barkod"]), 0.0), 2), True


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
    son = son_fiyatlar("trendyol")
    kayit, atlanan = [], 0
    for r in kayit_listesi(df):
        fiyat, yedek = fiyat_belirle(r, son)
        b = str(r["barkod"])
        govde = {"barcode": b, "quantity": int(min(max(_i(r.get("stok")), 0), 20000))}
        if fiyat > 0:
            govde["salePrice"] = fiyat
            govde["listPrice"] = fiyat
        elif _i(r.get("stok")) > 0:
            atlanan += 1  # fiyatsız ve stoklu: satışa açmayız
            continue
        # fiyatsız + stok 0: yalnız stok (0) gönderilir, böylece ürün satıştan kalkar
        kayit.append((b, govde))

    def gonder(grup):
        r = http("POST", f"{TY_BASE}/inventory/sellers/{s}/products/price-and-inventory",
                 json={"items": grup}, headers=trendyol_header(s, k, x), timeout=60)
        return r.status_code == 200, yanit_ozet(r)

    kayit = sirala_tukenen_once(kayit, lambda v: v.get("quantity", 0))
    ok_k, hata_k, loglar = paketle(kayit, 1000, gonder, ilerleme, "Trendyol")
    return _sonuc("trendyol", ok_k, hata_k, loglar, atlanan)


def sirala_tukenen_once(kayit, stok_fn):
    """Stoğu 0 olan kayıtları başa alır: hız limiti turu yarıda keserse önce tükenenler gitmiş olur."""
    return sorted(kayit, key=lambda kv: 0 if stok_fn(kv[1]) == 0 else 1)


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
    son = son_fiyatlar("n11")
    kayit, atlanan, tukenen_atlanan = [], 0, 0
    for r in kayit_listesi(df):
        fiyat, _ = fiyat_belirle(r, son)
        stok = max(_i(r.get("stok")), 0)
        if fiyat <= 0:
            atlanan += 1
            if stok == 0:
                tukenen_atlanan += 1
            continue
        kod = str(r["barkod"])
        kayit.append((kod, {
            "stockCode": kod, "listPrice": fiyat, "salePrice": fiyat,
            "quantity": stok, "currencyType": "TL",
        }))

    def gonder(grup):
        r = http("POST", f"{N11_BASE}/ms/product/tasks/price-stock-update",
                 json={"payload": {"integrator": "SahEntegre", "skus": grup}},
                 headers=n11_header(key, secret), timeout=120)
        return r.status_code == 200, yanit_ozet(r)

    kayit = sirala_tukenen_once(kayit, lambda v: v.get("quantity", 0))
    ok_k, hata_k, loglar = paketle(kayit, 1000, gonder, ilerleme, "N11")
    return _sonuc("n11", ok_k, hata_k, loglar, atlanan, tukenen_atlanan)


def n11_urun_listesi(df, ayar):
    pa = pa_al(ayar, "n11")
    atr = pa.get("attributes") or []
    sablon = str(pa.get("shipment_template", "") or "").strip()
    if not sablon:
        raise ValueError("N11 için 'Kargo şablonu' ayarı boş. Genel Ayarlar'dan girin.")
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
    son = son_fiyatlar("idefix")
    kayit, atlanan, tukenen_atlanan = [], 0, 0
    for r in kayit_listesi(df):
        bk = idefix_barkod(r["barkod"], ayar)
        fiyat, _ = fiyat_belirle(r, son)
        stok = max(_i(r.get("stok")), 0)
        if not bk or fiyat <= 0:
            atlanan += 1
            if bk and stok == 0:
                tukenen_atlanan += 1
            continue
        kayit.append((str(r["barkod"]), {
            "barcode": bk, "price": fiyat, "comparePrice": fiyat, "inventoryQuantity": stok,
        }))

    def gonder(grup):
        r = http("POST", f"{ID_BASE}/pim/catalog/{v}/inventory-upload", json={"items": grup}, headers=h, timeout=120)
        return r.status_code in (200, 201, 202), yanit_ozet(r)

    kayit = sirala_tukenen_once(kayit, lambda x: x.get("inventoryQuantity", 0))
    ok_k, hata_k, loglar = paketle(kayit, 500, gonder, ilerleme, "İdefix")
    return _sonuc("idefix", ok_k, hata_k, loglar, atlanan, tukenen_atlanan)


def idefix_urun_listesi(df, ayar):
    pa = pa_al(ayar, "idefix")
    brand = _i(pa.get("brand_id"))
    if brand <= 0:
        raise ValueError("İdefix için 'Marka ID' ayarı boş. Genel Ayarlar'dan girin.")
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
        ok = r.status_code in (200, 201, 202)
        ozet = yanit_ozet(r)
        if ok:
            b = idefix_batch_id(r.text)
            if b:
                takip_ekle("idefix_takip", [b])
                log_yaz("İdefix", "OK", f"Ürün yükleme batchRequestId: {b} (kabul = ürün onayı değildir; sonucu sorgulayın)")
                ozet += f" | batchRequestId: {b}"
            else:
                ozet += " | UYARI: batchRequestId dönmedi, sonuç sorgulanamaz"
        return ok, ozet

    ok_k, hata_k, loglar = paketle(kayit, 100, gonder, ilerleme, "İdefix", durdur=3)
    return len(ok_k), len(hata_k), loglar


IDEFIX_HATA = {
    "VENDOR_RETURN_ADDRESS_NOT_CORRECT": "İade adresi sistemdekiyle uyuşmuyor",
    "PRODUCT_IMAGE_MANDATORY_ONCREATE": "Ürün görseli zorunlu",
    "DATA_PARSE_ERROR": "Gönderilen veri okunamadı (biçim hatası)",
    "NO_BATCH_ID_EXIST": "Hatalı batch kimliği",
    "PRODUCT_POOL_ALREADY_EXIST": "Ürün zaten havuzunuzda var",
    "CATEGORY_FAILED_TO_MATCH": "Kategori eşleşmedi",
    "CATALOG_CATEGORY": "Ürün katalogda var; kategori katalogdakine göre belirlenir",
    "PRODUCT_BARCODE_NOT_EXIST": "Barkod İdefix kataloğunda yok",
    "VENDOR_CATEGORY_ACCESS_DENIED": "Bu kategoriye ürün ekleme yetkiniz yok",
    "BRAND_EXCLUSIVE_NOT_AUTHORIZED": "Bu markaya ürün ekleme yetkiniz yok",
    "PRODUCT_NOT_FOUND": "Barkod ürün havuzunuzda yok",
    "NO_PRICE": "Fiyat yok",
    "VENDOR_BRAND_ACCESS_DENIED": "Bu markaya ürün ekleme yetkiniz yok (Marka ID yanlış ya da marka yetkisi gerekli)",
    "CATALOG_PRICE_LOCKED": "Fiyat kilitli (İdefix destek ile görüşün)",
}
IDEFIX_DURUM = {
    "waiting_vendor_approve": "Onayınızı bekliyor (katalogda var)",
    "not_matched": "Katalogda eşleşmedi, İdefix inceliyor",
    "ready_for_sale": "Satışa hazır",
    "platform_declined": "İdefix reddetti",
    "auto_matched": "Otomatik eşleşti",
    "manuel_matched": "Elle eşleşti",
    "decline": "Hata (yüklenemedi)",
}


def idefix_sebep_kodlari(v, derinlik=0):
    """failureReasons metin, liste ya da {message, description} sözlüğü olabilir; hata kodlarını düz listeler."""
    if derinlik > 4 or v in (None, "", [], {}):
        return []
    if isinstance(v, str):
        return [k.strip() for k in re.split(r"[,;\s]+", v) if k.strip()]
    if isinstance(v, dict):
        cikti = []
        for a in ("message", "code", "reason", "description"):
            cikti += idefix_sebep_kodlari(v.get(a), derinlik + 1)
        return cikti
    if isinstance(v, (list, tuple)):
        cikti = []
        for e in v:
            cikti += idefix_sebep_kodlari(e, derinlik + 1)
        return cikti
    return [str(v)]


def idefix_batch_id(metin):
    m = re.search(r'"batchRequestId"\s*:\s*"([^"]+)"', metin or "")
    return m.group(1) if m else ""


def idefix_batch_sorgula(ayar, batch_id):
    v = kimlik(ayar, "idefix_satici_id")
    if not v:
        raise ValueError("İdefix Satıcı ID (vendorId) kayıtlı değil.")
    r = http("GET", f"{ID_BASE}/pim/pool/{urllib.parse.quote(str(v), safe='')}/batch-result/{urllib.parse.quote(str(batch_id).strip(), safe='')}",
             headers=idefix_header(ayar), timeout=60, tries=1)
    try:
        j = r.json()
    except Exception:
        j = None
    return r.status_code, j, (r.text or "")[:4000]


def idefix_sonuc_ozet(j):
    """batch-result yanıtını okunur satırlara çevirir (alan adları esnek okunur)."""
    ogeler = []
    if isinstance(j, dict):
        for a in ("items", "products", "data", "results"):
            if isinstance(j.get(a), list):
                ogeler = j[a]
                break
    elif isinstance(j, list):
        ogeler = j
    satirlar, sayim = [], {}
    for x in ogeler:
        if not isinstance(x, dict):
            continue
        durum = str(x.get("poolState") or x.get("status") or x.get("state") or "").strip()
        kodlar = idefix_sebep_kodlari(x.get("failureReasons") or x.get("failureReason") or x.get("errors") or "")
        sebep_tr = "; ".join(IDEFIX_HATA.get(k.split(":")[0], k) for k in kodlar)
        mp = x.get("matchedProduct") if isinstance(x.get("matchedProduct"), dict) else {}
        anahtar = durum.lower().replace(" ", "_")
        etiket_d = IDEFIX_DURUM.get(anahtar, durum)
        satirlar.append({
            "Barkod": str(x.get("barcode") or x.get("vendorStockCode") or ""),
            "Ürün": str(x.get("title") or x.get("name") or "")[:60],
            "Durum": etiket_d,
            "Hata sebebi": sebep_tr,
            "Eşleşen İdefix ürünü": str(mp.get("name") or ""),
            "_durum": anahtar,
        })
        sayim[etiket_d or "Bilinmiyor"] = sayim.get(etiket_d or "Bilinmiyor", 0) + 1
    ust = str(j.get("status") or "") if isinstance(j, dict) else ""
    return {"ust": ust, "satirlar": satirlar, "sayim": sayim}


def idefix_onayla(ayar, barkodlar):
    """Katalogda eşleşen (waiting_vendor_approve) ürünleri onaylar: POST /pim/pool/{vendorId}/approve-item."""
    h, v = idefix_header(ayar), kimlik(ayar, "idefix_satici_id")
    kayit = [(str(b), {"barcode": str(b)}) for b in barkodlar]

    def gonder(grup):
        r = http("POST", f"{ID_BASE}/pim/pool/{urllib.parse.quote(str(v), safe='')}/approve-item", json={"items": grup},
                 headers=h, timeout=60, tries=2)
        return r.status_code in (200, 201, 202), yanit_ozet(r)

    return paketle(kayit, 100, gonder, None, "İdefix onay")


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
        fiyat = round(_f(r.get("satis_fiyati")), 2)  # fiyat 0 ise sadece STOK gider (tükenen ürün satışta kalmasın)
        sku = onek + str(r["barkod"]).strip()
        f_deg = bool(r.get("_fiyat_degisti", True))
        s_deg = bool(r.get("_stok_degisti", True))
        kayit.append((str(r["barkod"]), (sku, fiyat, max(_i(r.get("stok")), 0), f_deg, s_deg)))
    kayit = sirala_tukenen_once(kayit, lambda v: v[2])

    def gonder(grup):
        h = hb_header(ayar)
        url = f"{HB_BASE}/listings/merchantid/{m}"
        fiyatli = [{"merchantSku": s_, "price": f_} for s_, f_, _, fd, _ in grup if f_ > 0 and fd]
        stoklu = [{"merchantSku": s_, "availableStock": a_} for s_, _, a_, _, sd in grup if sd]
        yanitlar = []
        # Önce STOK, sonra fiyat: hız limiti araya girerse en önemli olan (stok) gitmiş olur.
        for ad_, liste in (("stok", stoklu), ("fiyat", fiyatli)):
            if not liste:
                continue
            r_ = http("POST", f"{url}/{'price' if ad_ == 'fiyat' else 'stock'}-uploads", json=liste, headers=h, timeout=60, tries=1)
            if r_.status_code == 429:  # yükleme limiti: yeniden denemek limiti daha da doldurur, tur durdurulur
                return False, "HIZ_LIMITI " + yanit_ozet(r_)
            yanitlar.append((ad_, r_))
        ok = all(r_.status_code in (200, 201, 202) for _, r_ in yanitlar)
        ozet = " | ".join(f"{ad_}: {yanit_ozet(r_)}" for ad_, r_ in yanitlar) or "değişiklik yok"
        return ok, ozet

    ok_k, hata_k, loglar = paketle(kayit, 500, gonder, ilerleme, "Hepsiburada", bekle=1.0)
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
    if not pr.path.rstrip("/").endswith("/products/import"):
        raise ValueError("Hepsiburada ürün oluşturma adresi şu şekilde bitmeli: https://mpop.hepsiburada.com/product/api/products/import")
    return u


def hb_ek_ozellikler(pa):
    """Ayarlardaki ek özellikleri sözlüğe çevirir ({"renk_variant_property": "Siyah"} ya da [{"name":..,"value":..}])."""
    ek = pa.get("ek_ozellik")
    if isinstance(ek, dict):
        return {str(k): v for k, v in ek.items()}
    if isinstance(ek, list):
        return {str(x.get("name") or x.get("slug")): x.get("value") for x in ek
                if isinstance(x, dict) and (x.get("name") or x.get("slug"))}
    return {}


def hb_fiyat_metni(fiyat):
    """Dokümandaki örneğe göre ondalık ayracı virgül: 130,50"""
    return f"{round(float(fiyat), 2):.2f}".replace(".", ",")


def hb_urun_listesi(df, ayar):
    """Hepsiburada 'Ürün Bilgisi Gönderme' (POST /product/api/products/import) biçimi:
    [{categoryId, merchant, attributes:{merchantSku, VaryantGroupID, Barcode, UrunAdi, UrunAciklamasi, Marka,
    GarantiSuresi, kg, tax_vat_rate, price, stock, Image1..}}] -- dosya (integrator.json) olarak yüklenir."""
    hb_urun_adresi(ayar)
    pa = pa_al(ayar, "hb")
    merchant = kimlik(ayar, "hb_merchant_id")
    if not merchant:
        raise ValueError("Hepsiburada Merchant ID kayıtlı değil.")
    marka = str(pa.get("marka", "") or "").strip()
    if not marka:
        raise ValueError("Hepsiburada için Marka adı gerekli (Genel Ayarlar > Marka adı).")
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
    baslik = {k: v for k, v in hb_header(ayar).items() if k.lower() != "content-type"}  # multipart sınırını requests koyar

    def gonder(grup):
        govde = json.dumps(grup, ensure_ascii=False).encode("utf-8")
        r = http("POST", url, files={"file": ("integrator.json", govde, "application/json")},
                 headers=baslik, timeout=120, tries=2)
        ok = r.status_code in (200, 201, 202)
        ozet = yanit_ozet(r)
        if ok:
            t = re.search(r'"trackingId"\s*:\s*"([^"]+)"', r.text or "")
            if t:
                log_yaz("Hepsiburada", "OK", f"Ürün yükleme izleme kodu: {t.group(1)}")
                ozet += f" | izleme kodu: {t.group(1)}"
        return ok, ozet

    ok_k, hata_k, loglar = paketle(kayit, 100, gonder, ilerleme, "Hepsiburada", durdur=3)
    return len(ok_k), len(hata_k), loglar


HB_OMS = "https://oms-external.hepsiburada.com"


def hb_siparisler(ayar, saat=96, sayfa_boyu=50, en_fazla_sayfa=40):
    """GET /packages/merchantid/{id}: Hepsiburada dokümanı limit/offset kullanımını zorunlu kılar."""
    m = kimlik(ayar, "hb_merchant_id")
    if not m:
        return []
    url = f"{HB_OMS}/packages/merchantid/{urllib.parse.quote(str(m), safe='')}"
    hepsi = []
    for sayfa in range(en_fazla_sayfa):
        r = http("GET", url, params={"timespan": saat, "limit": sayfa_boyu, "Offset": sayfa * sayfa_boyu},
                 headers=hb_header(ayar), timeout=30)
        r.raise_for_status()
        j = r.json() or []
        if isinstance(j, dict):
            j = j.get("items") or j.get("data") or j.get("packages") or j.get("content") or []
        hepsi += j
        if len(j) < sayfa_boyu:
            break
    return hepsi


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
    takip_ekle("ptt_takip", idler, en_fazla=20)


def ptt_guncelle(ayar, df, ilerleme=None):
    """PTT 'Fiyat Stok Güncelle': POST /products/stock-prices (en çok 1000 ürün/istek; aynı istek 5 dk içinde
    tekrar gönderilemez; aynı barkod bir istekte tek kez; KDV dahil fiyat 1'den büyük olmalı)."""
    if not (kimlik(ayar, "ptt_key") and kimlik(ayar, "ptt_token")):
        raise RuntimeError("PTT API Key / Token eksik.")
    uret = bool(pa_al(ayar, "ptt").get("gecici_barkod", True))
    son = son_fiyatlar("ptt")
    tekil, atlanan, tukenen_atlanan = {}, 0, 0
    for r in kayit_listesi(df):
        fiyat, _ = fiyat_belirle(r, son)  # fiyatı yoksa son gönderilen fiyatla STOK yine de gider
        stok = max(_i(r.get("stok")), 0)
        if fiyat <= 1:  # PTT KDV dahil fiyatın 1'den büyük olmasını ister
            atlanan += 1
            if stok == 0:
                tukenen_atlanan += 1
            continue
        ptt_b = sabit_barkod(str(r["barkod"]).strip(), uret)  # ürün oluştururken kullanılan barkodla aynı
        if not ptt_b or len(ptt_b) > 250:
            atlanan += 1
            continue
        tekil[ptt_b] = (str(r["barkod"]), {"barcode": ptt_b, "quantity": stok, "priceWithVAT": fiyat})
    kayit = sirala_tukenen_once(list(tekil.values()), lambda v: v.get("quantity", 0))
    izler = []

    def gonder(grup):
        # tries=1: PTT aynı isteğin 5 dk içinde tekrarını reddeder; otomatik yeniden deneme anlamsız
        r = http("POST", f"{PTT_BASE}/products/stock-prices", json={"items": grup},
                 headers=ptt_header(ayar), timeout=60, tries=1)
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
    return _sonuc("ptt", ok_k, hata_k, loglar, atlanan, tukenen_atlanan)


def ptt_urun_listesi(df, ayar):
    """PTT AVM 'Ürün Ekleme Güncelleme' (POST /products/upsert) — varyantsız ürün.
    Alan adları PTT dokümanındaki örnek istekten alınmıştır. Doğrulanamayanlar (hangi alan zorunlu,
    KDV'li/KDV'siz fiyat kuralı) için önce 'Tek ürün (Test)' ile deneyip sonucu sorgulayın."""
    pa = pa_al(ayar, "ptt")
    cat_varsayilan = str(pa.get("category_id", "") or "").strip()
    if cat_varsayilan and not cat_varsayilan.isdigit():
        raise ValueError(f"PTT 'Varsayılan kategori ID' bir SAYI olmalı (örn. 55) ama şu yazılmış: '{cat_varsayilan[:60]}'. "
                         "Genel Ayarlar'dan düzeltin.")
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
        if gecerli_barkod(kod):  # yalnızca gerçek barkodlarda GTIN/EAN gönder
            u["ean"] = kod
            u["gtin"] = kod
        if marka:
            u["brand"] = marka
        if kargo:
            u["cargoProfileId"] = int(kargo) if kargo.isdigit() else kargo
        liste.append(u)
    return liste, atlanan


def ptt_urun_gonder(ayar, liste, ilerleme=None):
    if not (kimlik(ayar, "ptt_key") and kimlik(ayar, "ptt_token")):
        raise RuntimeError("PTT API Key / Token eksik.")
    kayit = [(u["productCode"], u) for u in liste]
    izler = []

    def gonder(grup):
        r = http("POST", f"{PTT_BASE}/{PTT_URUN_YOLU}", json={"items": grup},
                 headers=ptt_header(ayar), timeout=60, tries=2)
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
    """PTT 'Kategori Ağacı': GET /categories/category-tree."""
    r = http("GET", f"{PTT_BASE}/categories/category-tree", headers=ptt_header(ayar), timeout=90, tries=2)
    if r.status_code != 200:
        raise RuntimeError(f"Kategori ağacı alınamadı ({yanit_ozet(r)})")
    j = r.json()
    if isinstance(j, dict) and j.get("success") is False:
        ayrinti = j.get("error") or {k: v for k, v in j.items() if k != "category_tree"}
        raise RuntimeError("PTT kategori ağacını vermedi. PTT'nin yanıtı: " + json.dumps(ayrinti, ensure_ascii=False)[:800])
    return j


def ptt_kategori_duzlestir(veri):
    """Yanıt biçimi dökümanda görünmediği için toleranslı okur: id+ad taşıyan düğümleri ve alt listelerini gezer."""
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
    """PTT kategori uçları: 'main' (Ana Kategori Listesi) veya bir kategori ID'si (Kategori Bilgisi)."""
    yol = str(yol or "").strip()
    if yol != "main" and not yol.isdigit():
        raise ValueError("Kategori ID bir sayı olmalı.")
    r = http("GET", f"{PTT_BASE}/categories/{yol}", headers=ptt_header(ayar), timeout=60, tries=1)
    try:
        j = r.json()
    except Exception:
        j = None
    return r.status_code, j, (r.text or "")[:1500]


def ptt_sonuc_ozet(metin):
    """PTT tracking-result yanıtını (dokümandaki örnek biçim) okunur özete çevirir."""
    try:
        j = json.loads(metin)
    except Exception:
        return None
    if not isinstance(j, dict):
        return None
    d = j.get("data") if isinstance(j.get("data"), dict) and ("productsSubTrackingResult" in j["data"] or "status" in j["data"]) else j
    alt = d.get("productsSubTrackingResult") or {}
    ozet = (f"Durum: {d.get('status')} | İlerleme: {d.get('progress')} | Toplam: {alt.get('countOfTotalProducts')} | "
            f"Bekleyen: {alt.get('countOfWaitingProducts')} | İşlenen: {alt.get('countOfInProgressProducts')} | "
            f"Tamamlanan: {alt.get('countOfCompletedProducts')} | İptal/hatalı: {alt.get('countOfCancelledProducts')}")
    satirlar = []
    for b in (alt.get("productBasedInfos") or [])[:200]:
        if not isinstance(b, dict):
            continue
        neden = "; ".join(str(x) for x in (b.get("failureReasons") or []))
        satirlar.append({"Barkod": b.get("barcode"), "Durum": b.get("status"), "Mesaj": b.get("message"), "Hata nedenleri": neden})
    return {"ozet": ozet, "satirlar": satirlar}


def ptt_sonuc_sorgula(ayar, takip_id):
    """PTT 'Ürün Güncelleme Kontrol': tracking-result/{trackingId}. Dönüş: (http_durum, metin)."""
    tid = str(takip_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,100}", tid):
        raise ValueError("Geçersiz trackingId.")
    r = http("POST", f"{PTT_BASE}/products/tracking-result/{tid}", headers=ptt_header(ayar), timeout=30, tries=2)
    return r.status_code, r.text[:4000]


# --------------------------------------------------------------------------
# Trendruum
# --------------------------------------------------------------------------
TR_BASE = "https://api.trendruum.com/api/v1/integration"


def trendruum_token(key, secret):
    r = requests.post(f"{TR_BASE}/auth/login", json={"client_id": key.strip(), "client_secret": secret.strip()}, timeout=30)
    try:
        j = r.json()
    except Exception:
        j = {}
    token = (j.get("data") or {}).get("token") or j.get("token") or ""
    if r.status_code != 200 or not token:
        raise RuntimeError(f"Trendruum girişi başarısız (HTTP {r.status_code})")
    return token


def _tr_token(ayar):
    return trendruum_token(kimlik(ayar, "trendruum_key"), kimlik(ayar, "trendruum_secret"))


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
    brand, _cat_varsayilan, uret, kdv = trendruum_ayar(ayar)
    if not objectid_mi(brand):
        raise ValueError("Trendruum 'Marka ID' geçersiz/boş (24 karakterlik ID olmalı). Genel Ayarlar'dan girin.")
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
    """GET /categories yanıtını (liste ya da {data:[...]}, iç içe sub_categories) düz listeye çevirir."""
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
            cikti.append({"ID": cid, "Kategori": str(dugum.get("full_path") or ad), "Uc kategori": "evet" if not alt else "hayir"})
        for a in (alt or []):
            gez(a)

    for d in (j if isinstance(j, list) else []):
        gez(d)
    return cikti


def trendruum_kategori_ara(ayar, ad, limit=300):
    ad = str(ad or "").strip()
    if len(ad) < 2:
        raise ValueError("Aramak icin en az 2 harf yazin.")
    token = _tr_token(ayar)
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
    token = _tr_token(ayar)
    r = http("GET", f"{TR_BASE}/categories/{cid}", headers={"Authorization": f"Bearer {token}"}, timeout=60, tries=1)
    try:
        j = r.json()
    except Exception:
        j = None
    return r.status_code, j


def kat_belirtec(t):
    """Türkçe-güvenli, ekleri kabaca kırpılmış kelime kümesi (ilk 5 harf)."""
    m = tr_norm(t).translate(str.maketrans("çğöşü", "cgosu"))
    dur = {"ve", "ile", "icin", "diger"}
    return {w[:5] for w in re.findall(r"[a-z0-9]+", m) if len(w) > 1 and w not in dur}


def trendruum_agac_yukle(ayar):
    """GET /categories?limit=5000 -> uc kategorilerin duz listesi (tek istek)."""
    token = _tr_token(ayar)
    r = http("GET", f"{TR_BASE}/categories", params={"limit": 5000}, headers={"Authorization": f"Bearer {token}"}, timeout=120, tries=2)
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
    """Tedarikçi kategorisine en yakın pazar yeri uç kategorisi: (ID, yol, güven)."""
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
    """Aranan ada en yakın (son parçası kısa ve aranan içeren) uç kategorileri üste alır."""
    q = tr_norm(aranan).strip()

    def anahtar(k):
        son = tr_norm(k["Kategori"].split(">")[-1]).strip()
        icerir = all(w in son for w in q.split()) if q else False
        uc = 0 if k.get("Uc kategori", "evet") == "evet" else 1
        return (0 if icerir else 1, uc, abs(len(son) - len(q)), len(k["Kategori"]))

    return sorted(liste, key=anahtar)


def trendruum_gonder(ayar, liste, ilerleme=None):
    token = _tr_token(ayar)
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    kayit = [(u["model_code"], u) for u in liste]

    def gonder(grup):
        r = http("POST", f"{TR_BASE}/products/bulk", json={"products": grup}, headers=h, timeout=60, tries=2)
        return r.status_code in (200, 201, 202), yanit_ozet(r)

    ok_k, hata_k, loglar = paketle(kayit, 50, gonder, ilerleme, "Trendruum", durdur=3)
    return len(ok_k), len(hata_k), loglar


def trendruum_guncelle(ayar, df, ilerleme=None):
    token = _tr_token(ayar)
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    _, _, uret, _ = trendruum_ayar(ayar)
    kayit, atlanan = [], 0
    for r in kayit_listesi(df):
        fiyat = _f(r.get("satis_fiyati"))
        sb = sabit_barkod(r["barkod"], uret)
        if not sb:
            atlanan += 1
            continue
        govde = {"barcode": sb, "stock": max(_i(r.get("stok")), 0)}
        if fiyat > 0:  # fiyatı olmayan üründe sadece STOK gider (tükenen ürün satışta kalmasın)
            govde["price"] = fiyat
        kayit.append((str(r["barkod"]), govde))
    kayit = sirala_tukenen_once(kayit, lambda v: v.get("stock", 0))

    def gonder(grup):
        parcalar = [[p for p in grup if "price" in p], [p for p in grup if "price" not in p]]
        toplam, guncel_top, mesajlar = 0, 0, []
        for parca in parcalar:
            if not parca:
                continue
            r = http("POST", f"{TR_BASE}/products/bulk-update", json={"products": parca}, headers=h, timeout=120)
            if r.status_code != 200:
                return False, yanit_ozet(r)
            try:
                d = r.json().get("data") or {}
            except Exception:
                d = {}
            guncel = d.get("updated_count")
            toplam += len(parca)
            guncel_top += guncel if guncel is not None else len(parca)
            mesajlar.append(yanit_ozet(r))
        if guncel_top == 0 and toplam > 0:
            return False, f"0/{toplam} ürün güncellendi; barkodlar Trendruum mağazasında bulunamadı olabilir. " + " | ".join(mesajlar)
        uyari = f" (UYARI: {toplam - guncel_top} ürün güncellenmedi)" if guncel_top < toplam else ""
        return True, f"güncellenen: {guncel_top}/{toplam}{uyari}"

    ok_k, hata_k, loglar = paketle(kayit, 1000, gonder, ilerleme, "Trendruum")
    return _sonuc("trendruum", ok_k, hata_k, loglar, atlanan)


def kat_sec(pa, ayar, kategori, pid):
    """Eşleşmiş kategori ID'si; yoksa varsayılan SADECE 'varsayılan kategoriyi kullan' açıkken."""
    v = kategori_id(pa, ayar, kategori, pid)
    if v:
        return v
    if pa.get("varsayilan_kategori_kullan"):
        return str(pa.get("category_id") or "").strip()
    return ""


def kategori_id(pa, ayar, kategori, pid):
    ana = str(kategori or "").split(">>>")[0].strip()
    v = (pa.get("kategori_eslesme") or {}).get(ana)
    if not v and pid == "trendruum":  # eski sürümden kalan eşleştirme
        v = (ayar.get("kategori_eslesme") or {}).get(ana)
    return str(v).strip() if v else ""


# --------------------------------------------------------------------------
# Hepsiburada / İdefix kategori ve marka servisleri (arayüzsüz kısım)
# --------------------------------------------------------------------------
def hb_katalog_taban(ayar):
    """Katalog API tabanı: ürün adresindeki hepsiburada.com sunucusu, yoksa canlı sunucu."""
    u = str(pa_al(ayar, "hb").get("urun_endpoint", "") or "").strip()
    host = (urllib.parse.urlparse(u).hostname or "").lower() if u else ""
    if not (host == "hepsiburada.com" or host.endswith(".hepsiburada.com")):
        host = "mpop.hepsiburada.com"
    return f"https://{host}/product/api"


def hb_kategori_ayikla(j):
    """get-all-categories yanıtından [{ID, Kategori}] çıkarır (alan adları esnek okunur)."""
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
    """Tüm uç kategorileri sayfa sayfa çeker (leaf=true, status=ACTIVE, available=true)."""
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
            sayfali = False  # sayfalama parametreleri kabul edilmediyse yalnızca temel parametrelerle dene
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
    """Otomatik eşleştirme için Hepsiburada uç kategorilerini Trendruum'daki gibi hazırlar."""
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


def genel_kategori_ayikla(j):
    """Kategori yanıtını (iç içe 'children' ya da düz 'parentId' listesi) [{ID, Kategori, Uc kategori}] yapar."""
    kok = j
    if isinstance(j, dict):
        for a in ("data", "content", "items", "categories", "result", "results"):
            if isinstance(j.get(a), list):
                kok = j[a]
                break
        else:
            kok = [j]
    kayit, goruldu = [], set()

    def al(d, *anahtar):
        for a in anahtar:
            if d.get(a) not in (None, ""):
                return d[a]
        return None

    def yuru(dugum, ust, derinlik=0):
        if not isinstance(dugum, dict) or derinlik > 12:
            return
        cid = al(dugum, "id", "categoryId", "_id")
        ad = al(dugum, "name", "title", "categoryName", "displayName")
        alt = None
        for a in ("children", "subCategories", "sub_categories", "categories", "subs"):
            if isinstance(dugum.get(a), list):
                alt = dugum[a]
                break
        yol = ust + ([str(ad)] if ad else [])
        if cid is not None and ad and str(cid) not in goruldu:
            goruldu.add(str(cid))
            kayit.append({"ID": str(cid), "yol": yol, "ust": al(dugum, "parentId", "parent_id", "parentCategoryId"), "uc": not alt})
        for x in (alt or []):
            yuru(x, yol, derinlik + 1)

    for d in (kok if isinstance(kok, list) else []):
        yuru(d, [])
    # düz listede üst-alt ilişkisi parentId ile kurulur
    by_id = {k["ID"]: k for k in kayit}
    ustler = {str(k["ust"]) for k in kayit if k["ust"] not in (None, "", 0, "0")}
    if ustler:
        def zincir(k, n=0):
            u = k["ust"]
            if n > 12 or u in (None, "", 0, "0") or str(u) not in by_id:
                return [k["yol"][-1]] if k["yol"] else []
            return zincir(by_id[str(u)], n + 1) + [k["yol"][-1]]

        for k in kayit:
            if len(k["yol"]) <= 1:
                k["yol"] = zincir(k)
            k["uc"] = k["ID"] not in ustler
    return [{"ID": k["ID"], "Kategori": " > ".join(k["yol"]), "Uc kategori": "evet" if k["uc"] else "hayir"} for k in kayit]


def idefix_agac_yukle(ayar):
    r = http("GET", f"{ID_BASE}/pim/product-category", headers=idefix_header(ayar), timeout=120, tries=2)
    if r.status_code != 200:
        raise RuntimeError("İdefix kategori listesi alınamadı: " + yanit_ozet(r))
    try:
        j = r.json()
    except Exception:
        raise RuntimeError("İdefix kategori yanıtı okunamadı: " + (r.text or "")[:400])
    liste = genel_kategori_ayikla(j)
    if not liste:
        raise RuntimeError("İdefix kategori yanıtı tanınamadı. Yanıtın başı: " + (r.text or "")[:500])
    return liste


def idefix_oto_dugumler(ayar):
    out = []
    for k in idefix_agac_yukle(ayar):
        if k["Uc kategori"] != "evet":
            continue
        out.append({"ID": k["ID"], "yol": k["Kategori"], "son": kat_belirtec(k["Kategori"].split(">")[-1]), "tum": kat_belirtec(k["Kategori"])})
    return out


def _idefix_marka_listesi(j):
    ogeler = j if isinstance(j, list) else ([j] if isinstance(j, dict) else [])
    out = []
    for x in ogeler:
        if isinstance(x, dict) and x.get("id") not in (None, ""):
            out.append({"ID": str(x["id"]), "Marka": str(x.get("title") or ""),
                        "Özel marka": "evet" if x.get("exclusiveBrand") else "hayır",
                        "Tür": "Yayınevi" if x.get("bookPublisher") else "Marka"})
    return out


def idefix_marka_ara(ayar, ad):
    """Dokümandaki marka servisleri: /pim/brand/by-name, olmazsa /pim/brand/search-by-name."""
    ad = str(ad or "").strip()
    if len(ad) < 2:
        raise ValueError("Aramak için en az 2 harf yazın.")
    h = idefix_header(ayar)
    for yol in ("by-name", "search-by-name"):
        r = http("GET", f"{ID_BASE}/pim/brand/{yol}", params={"title": ad}, headers=h, timeout=60, tries=1)
        if r.status_code == 200:
            try:
                liste = _idefix_marka_listesi(r.json())
            except Exception:
                liste = []
            if liste:
                return liste
        elif r.status_code not in (400, 404):
            raise RuntimeError("İdefix marka araması başarısız: " + yanit_ozet(r))
    return []


def idefix_marka_getir(ayar, marka_id):
    r = http("GET", f"{ID_BASE}/pim/brand/{urllib.parse.quote(str(marka_id).strip(), safe='')}",
             headers=idefix_header(ayar), timeout=60, tries=1)
    if r.status_code != 200:
        raise RuntimeError("Bu Marka ID İdefix'te bulunamadı: " + yanit_ozet(r))
    liste = _idefix_marka_listesi(r.json())
    if not liste:
        raise RuntimeError("Marka bilgisi okunamadı.")
    return liste[0]


# --------------------------------------------------------------------------
# Gönderim orkestrasyonu
# --------------------------------------------------------------------------
GUNCELLEYICI = {
    "trendruum": trendruum_guncelle, "trendyol": trendyol_guncelle, "hb": hb_guncelle,
    "n11": n11_guncelle, "idefix": idefix_guncelle, "ptt": ptt_guncelle,
}


def pazar_yetim_barkodlar(ayar, pid):
    """Pazar yerine gönderilmiş ama artık hiçbir tedarikçide olmayan (silinmiş) ürünlerin barkodları."""
    with closing(baglan()) as c:
        anahtarlar = [str(r[0]) for r in c.execute("SELECT DISTINCT barkod FROM pazar_durum WHERE pazar = ? AND durum = 'ok'", (pid,))]
        mevcut = {str(r[0]) for r in c.execute("SELECT DISTINCT barkod FROM urunler")}
    if not mevcut:  # veritabanı tamamen boşsa (örneğin yeni kurulum) hiçbir ürün yetim sayılmaz
        return []
    onek = str(pa_al(ayar, "hb").get("sku_prefix", "") or "") if pid == "hb" else ""
    yetim = set()
    for k in anahtarlar:
        ham = k[len(onek):] if (onek and k.startswith(onek)) else k
        if ham and ham not in mevcut:
            yetim.add(ham)
    return sorted(yetim)


def pazar_yetim_sifirla(ayar, pid, ilerleme=None):
    """Tedarikçide kalmayan ürünlerin stoğunu pazar yerinde 0'lar. Dönüş: (ok, hata, yetim_sayisi)."""
    if pid not in GUNCELLEYICI or not pazar_bagli(ayar, pid):
        return 0, 0, 0
    yetim = pazar_yetim_barkodlar(ayar, pid)
    if not yetim:
        return 0, 0, 0
    df = pd.DataFrame({"barkod": yetim, "stok": 0, "satis_fiyati": 0.0})
    ok, hata, loglar = GUNCELLEYICI[pid](ayar, df, ilerleme)
    log_yaz(PAZAR_AD.get(pid, pid), "OK" if hata == 0 else "KISMİ",
            f"Tedarikçide kalmayan {len(yetim)} ürünün stoğu 0'landı: {ok} gönderildi, {hata} hata.")
    if ok > 0 and hata == 0:
        onek = str(pa_al(ayar, "hb").get("sku_prefix", "") or "") if pid == "hb" else ""
        anahtarlar = list(yetim) + ([onek + b for b in yetim] if onek else [])
        with closing(baglan()) as c:
            for parca in _parcala(anahtarlar):
                c.execute(f"UPDATE pazar_durum SET durum = 'sifirlandi' WHERE pazar = ? AND durum = 'ok' AND barkod IN ({','.join('?' * len(parca))})", [pid] + parca)
            c.commit()
    return ok, hata, len(yetim)


def snapshot_oku(pid):
    with closing(baglan()) as c:
        return {str(r[0]): (r[1], r[2]) for r in c.execute("SELECT barkod, stok, fiyat FROM pazar_son WHERE pazar = ? AND barkod != '__tam__'", (pid,))}


def son_tam_zamani(pid):
    with closing(baglan()) as c:
        r = c.execute("SELECT zaman FROM pazar_son WHERE pazar = ? AND barkod = '__tam__'", (pid,)).fetchone()
    try:
        return datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S") if r and r[0] else None
    except (TypeError, ValueError):
        return None


TAM_TUR_SAAT = 3  # otomatik turda her bu kadar saatte bir tüm ürünler yeniden gönderilir (eskiden 6)


def degisenleri_sec(ayar, pid, df, simdi=None):
    """Otomatik turda yalnızca son başarılı gönderimden BERİ DEĞİŞEN ürünleri seçer (hız limitine takılmamak için).
    Dönüş: (df, tam_tur_mu, sifirlanan_sayi). İlk tur ve her TAM_TUR_SAAT saatte bir TAM gönderim yapılır.

    ÖNEMLİ: Stoğu 0'a düşen ürünler HİÇBİR ZAMAN engellenmez ve her zaman listenin başındadır. Eskiden toplu
    sıfırlamalar 'fren' ile gönderilmiyordu; bu da pazarda stoksuz ürün satılmasına yol açıyordu. Bozuk XML
    koruması artık senkron aşamasında (xml_supheli_mi) yapılır."""
    simdi = simdi or datetime.now()
    snap = snapshot_oku(pid)
    tam_z = son_tam_zamani(pid)
    if not snap or tam_z is None or (simdi - tam_z) > timedelta(hours=TAM_TUR_SAAT):
        return df, True, 0
    d = df.copy()
    k = d["barkod"].astype(str)
    yeni_stok = d["stok"].map(_i).clip(lower=0)
    yeni_fiyat = d["satis_fiyati"].map(_f).round(2)
    onceki_stok = k.map(lambda x: snap.get(x, (None, None))[0])
    onceki_fiyat = k.map(lambda x: snap.get(x, (None, None))[1])
    yeni_urun = onceki_stok.isna()
    s_deg = yeni_urun | (onceki_stok.fillna(-1).astype(float) != yeni_stok.astype(float))
    f_deg = yeni_urun | ((onceki_fiyat.fillna(-1).astype(float) - yeni_fiyat).abs() > 0.004)
    secil = s_deg | f_deg
    sifirlanan = (yeni_stok == 0) & (onceki_stok.fillna(0).astype(float) > 0)
    n_sifir = int(sifirlanan.sum())
    esik = max(300, int(0.30 * len(snap)))
    if n_sifir > esik:  # engellemez, yalnızca haber verir
        mesaj = (f"{PAZAR_AD.get(pid, pid)}: {n_sifir} ürün aynı anda stoksuz oluyor ve pazara bildiriliyor. "
                 "Beklenmedik bir toplu düşüşse tedarikçi XML'ini kontrol edin.")
        log_yaz(PAZAR_AD.get(pid, pid), "UYARI", mesaj)
        bildir(mesaj, tekil=f"toplu_sifir:{pid}", bekleme_dk=120)
    d["_stok_degisti"] = s_deg
    d["_fiyat_degisti"] = f_deg
    d = d[secil]
    if not d.empty:  # önce stoku SIFIRA düşenler: stoksuz satış riski en yüksek olanlar
        d = d.assign(_o=(d["stok"].map(_i) != 0).astype(int)).sort_values("_o", kind="stable").drop(columns=["_o"])
    return d, False, n_sifir


def snapshot_guncelle(pid, df_gonder, baslangic, tam_tur, hata):
    """Başarılı gönderilen ürünlerin son gönderilen stok/fiyatını kaydeder."""
    if df_gonder is None or df_gonder.empty:
        return 0
    with closing(baglan()) as c:
        okset = {str(r[0]) for r in c.execute("SELECT barkod FROM pazar_durum WHERE pazar = ? AND durum = 'ok' AND zaman >= ?", (pid, baslangic))}
        z = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        eski_fiyat = {str(r[0]): float(r[1]) for r in c.execute("SELECT barkod, fiyat FROM pazar_son WHERE pazar = ?", (pid,))}
        satirlar = []
        for b, sk, fy in zip(df_gonder["barkod"], df_gonder["stok"], df_gonder["satis_fiyati"]):
            if str(b) not in okset:
                continue
            fiyat = round(_f(fy), 2)
            if fiyat <= 0:  # fiyatsız (yalnız stok giden) üründe bilinen son fiyat korunur
                fiyat = eski_fiyat.get(str(b), 0.0)
            satirlar.append((pid, str(b), _i(sk), fiyat, z))
        if satirlar:
            c.executemany("INSERT OR REPLACE INTO pazar_son (pazar, barkod, stok, fiyat, zaman) VALUES (?,?,?,?,?)", satirlar)
            if tam_tur and hata == 0 and len(satirlar) >= 0.99 * len(df_gonder):
                c.execute("INSERT OR REPLACE INTO pazar_son (pazar, barkod, stok, fiyat, zaman) VALUES (?,?,?,?,?)", (pid, "__tam__", 0, 0, z))
        c.commit()
    return len(satirlar)


def pazara_gonder(ayar, pid, df, ilerleme=None, tam=True):
    """Stok + fiyat gönderir. Dönüş: (başarılı, hatalı, özet_metin)."""
    ad = PAZAR_AD.get(pid, pid)
    try:
        if pid not in GUNCELLEYICI:
            raise RuntimeError(f"{ad} için entegrasyon yok.")
        if not pazar_bagli(ayar, pid):
            raise RuntimeError(f"{ad} API bilgileri eksik.")
        df = fiyat_artis_uygula(ayar, pid, df)
        kara = kara_liste_maskesi(ayar, df) | stok_sifir_maskesi(ayar, df)
        if kara.any():  # kara listedeki ürünler pazarda satıştan kalksın (stok 0)
            df = df.copy()
            df.loc[kara, "stok"] = 0
        pay, tavan, acil = _i(ayar.get("stok_guvenlik_payi")), _i(ayar.get("pazar_stok_tavani")), bool(ayar.get("acil_durdur"))
        if "stok" in df.columns and (pay > 0 or tavan > 0 or acil):
            df = df.copy()
            sk = df["stok"].map(_i).clip(lower=0)
            if pay > 0:
                sk = (sk - pay).clip(lower=0)
            if tavan > 0:
                sk = sk.clip(upper=tavan)
            if acil:
                sk = sk * 0
            df["stok"] = sk.astype(int)
        baslangic = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tam_tur, df_gonder = True, df
        if tam is None:  # otomatik tur: yalnızca değişenler
            df_gonder, tam_tur, _sifir = degisenleri_sec(ayar, pid, df)
            if df_gonder.empty:
                return 0, 0, "Değişen ürün yok; gönderim gerekmedi."
        if "stok" in df_gonder.columns and not df_gonder.empty:  # tükenenler her zaman ilk pakete
            df_gonder = df_gonder.assign(_o=(df_gonder["stok"].map(_i) != 0).astype(int)).sort_values("_o", kind="stable").drop(columns=["_o"])
        ok, hata, loglar = GUNCELLEYICI[pid](ayar, df_gonder, ilerleme)
        try:
            snapshot_guncelle(pid, df_gonder, baslangic, tam_tur, hata)
        except Exception:
            pass
    except Exception as e:
        log_yaz(ad, "HATA", f"Gönderilemedi: {e}")
        raise
    son = loglar[-1] if loglar else ""
    if ok == 0 and hata == 0:
        durum = "UYARI"
    elif hata == 0:
        durum = "OK"
    elif ok > 0:
        durum = "KISMİ"
    else:
        durum = "HATA"
    log_yaz(ad, durum, f"{ok} gönderildi, {hata} hata. {son}")
    if hata > 0 and ok == 0:
        bildir(f"{ad}: stok/fiyat gönderimi tamamen BAŞARISIZ ({hata} kayıt). {son[:200]}", tekil=f"gonderim_hata:{pid}", bekleme_dk=60)
    return ok, hata, "\n".join(loglar[-8:])


def son_senkron_zamani(ayar=None):
    """Tedarikçilerin son başarılı senkronlarından EN ESKİSİ (biri bile hiç senkronlanmadıysa None)."""
    ayar = ayar or ayar_oku()
    zamanlar = []
    for ad in (ayar.get("tedarikciler") or {}):
        t = kv_oku(f"son_senkron:{ad}")
        try:
            zamanlar.append(datetime.strptime(t, "%Y-%m-%d %H:%M:%S"))
        except (TypeError, ValueError):
            return None
    return min(zamanlar) if zamanlar else None


def senkron_dk_degeri(ayar):
    return max(5.0, _f(ayar.get("senkron_dk"), 10.0) or 10.0)


def senkron_gecikme_dk(ayar, simdi=None):
    """(dakika, bayat_mi). Hiç senkron yoksa (None, True)."""
    z = son_senkron_zamani(ayar)
    if z is None:
        return None, True
    dk = ((simdi or datetime.now()) - z).total_seconds() / 60
    return dk, dk > max(2 * senkron_dk_degeri(ayar), 30.0)


def acil_durdur_uygula(ayar, aktif, neden=""):
    """Acil durdur: tüm bağlı pazar yerlerine stok 0 gönderir. Kapatınca gerçek stoklar yeniden gider."""
    ayar["acil_durdur"] = bool(aktif)
    ayar_yaz(ayar)
    df = urunleri_oku()
    sonuc = []
    for _, _, pid in OTO_ANAHTAR:
        if pid in GUNCELLEYICI and pazar_bagli(ayar, pid):
            try:
                ok, hata, _ = pazara_gonder(ayar, pid, df)
                sonuc.append((PAZAR_AD.get(pid, pid), ok, hata))
            except Exception as e:
                sonuc.append((PAZAR_AD.get(pid, pid), 0, str(e)))
    log_yaz("Sistem", "UYARI" if aktif else "OK",
            ("ACİL DURDURMA açıldı: tüm pazar yerlerinde stok 0." if aktif else "Acil durdurma kapatıldı: gerçek stoklar yeniden gönderildi.")
            + (f" {neden}" if neden else ""))
    return sonuc


def bayat_koruma(ayar):
    """Senkron çok gecikirse (isteğe bağlı) tüm pazarlarda stoğu 0'lar; senkron düzelince otomatik geri açar."""
    if not ayar.get("tedarikciler"):
        return
    dk, _ = senkron_gecikme_dk(ayar)
    otomatik_kapali = bool(kv_oku("bayat_otomatik_durdurma", False))
    if (ayar.get("bayat_otomatik_durdur") and dk is not None and not ayar.get("acil_durdur")
            and dk >= _f(ayar.get("bayat_durdur_dk"), 120.0)):
        acil_durdur_uygula(ayar, True, f"Stok senkronu {int(dk)} dakikadır yapılamadı (otomatik koruma).")
        kv_yaz("bayat_otomatik_durdurma", True)
        bildir(f"Stok senkronu {int(dk)} dakikadır yapılamıyor; stoksuz satış olmasın diye TÜM pazarlarda stok 0'landı. "
               "Senkron düzelince otomatik geri açılacak.", tekil="bayat_durdur", bekleme_dk=60)
    elif otomatik_kapali:
        if not ayar.get("acil_durdur"):
            kv_yaz("bayat_otomatik_durdurma", False)  # kullanıcı elle açmış
        elif dk is not None and dk < max(2 * senkron_dk_degeri(ayar), 30.0):
            acil_durdur_uygula(ayar, False, "Senkron düzeldi (otomatik geri açma).")
            kv_yaz("bayat_otomatik_durdurma", False)
            bildir("Stok senkronu düzeldi; pazar yerlerinde gerçek stoklar yeniden gönderildi.", tekil="bayat_acildi", bekleme_dk=30)


def tumunu_senkronla(oto=True, zorla=False):
    if not SENKRON_KILIDI.acquire(blocking=False):
        return [("Sistem", False, "Başka bir senkronizasyon zaten çalışıyor.")]
    try:
        ayar = ayar_oku()
        sonuclar = []
        for ad, bilgi in ayar["tedarikciler"].items():
            try:
                n = tedarikci_senkron(ad, bilgi, _i(ayar.get("kritik_esik")), stok_ust_degeri(ayar), zorla)
                log_yaz(ad, "OK", f"{n} ürün güncellendi")
                sonuclar.append((ad, True, f"{n} ürün"))
            except Exception as e:
                log_yaz(ad, "HATA", e)
                sonuclar.append((ad, False, str(e)))
                try:
                    sayac = int(kv_oku(f"xml_hata:{ad}", 0) or 0) + 1
                    kv_yaz(f"xml_hata:{ad}", sayac)
                    if sayac >= 3:
                        bildir(f"{ad}: stok senkronu üst üste {sayac} kez BAŞARISIZ. Pazar yerlerinde eski stok kalıyor olabilir. Hata: {str(e)[:200]}",
                               tekil=f"senkron_hata:{ad}", bekleme_dk=90)
                except Exception:
                    pass
        if oto and any(x[1] for x in sonuclar):
            for _, anahtar_, pid_ in OTO_ANAHTAR:
                if ayar.get(anahtar_) and pazar_bagli(ayar, pid_):
                    try:
                        pazara_gonder(ayar, pid_, urunleri_oku(), tam=None)
                    except Exception:
                        pass  # pazara_gonder zaten günlüğe yazdı
        return sonuclar
    finally:
        SENKRON_KILIDI.release()


def baglanti_testi(ayar, pid):
    try:
        if not pazar_bagli(ayar, pid):
            return False, "Eksik bilgi: tüm kimlik alanlarını doldurup kaydedin."
        if pid == "trendruum":
            _tr_token(ayar)
            return True, "✅ Trendruum girişi başarılı."
        if pid == "hb":
            return hb_dene(ayar)
        if pid == "ptt":
            return ptt_test(kimlik(ayar, "ptt_key"), kimlik(ayar, "ptt_token"))
        if pid == "trendyol":
            s_, k_, x_ = (kimlik(ayar, a) for a in ("trendyol_seller_id", "trendyol_key", "trendyol_secret"))
            r = http("GET", f"{TY_BASE}/order/sellers/{s_}/orders", params={"size": 1}, headers=trendyol_header(s_, k_, x_), timeout=30)
        elif pid == "n11":
            r = http("GET", f"{N11_BASE}/rest/delivery/v1/shipmentPackages", params={"status": "Created", "page": 0, "size": 1},
                     headers=n11_header(kimlik(ayar, "n11_key"), kimlik(ayar, "n11_secret")), timeout=30)
        elif pid == "idefix":
            r = http("GET", f"{ID_BASE}/pim/product-category", headers=idefix_header(ayar), timeout=60)
        else:
            return False, "Desteklenmiyor."
        if r.status_code == 200:
            return True, "✅ Bağlantı başarılı (HTTP 200)"
        return False, f"❌ Bağlantı başarısız ({yanit_ozet(r)})"
    except Exception as e:
        return False, f"Bağlantı kurulamadı: {e}"


# --------------------------------------------------------------------------
# Sipariş normalleştirme
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
    "yeni": "🆕 Yeni", "hazir": "🚚 Gönderime Hazır", "kargoda": "🚛 Kargoda",
    "teslim": "✅ Teslim Edildi", "iptal": "❌ İptal",
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


HB_DURUM = {"open": "yeni", "unpacked": "yeni", "packaged": "hazir", "intransit": "kargoda", "in_transit": "kargoda",
            "delivered": "teslim", "cancelled": "iptal", "canceled": "iptal", "claimed": "iptal"}


def para_metni(x):
    """Tutarı okunur yazar: {'currency','amount'} sözlüğü, sayı ya da metin -> '1.222,01 ₺'."""
    birim = None
    if isinstance(x, dict):
        birim = x.get("currency")
        x = x.get("amount", x.get("value"))
    try:
        v = float(x)
    except (TypeError, ValueError):
        return str(x) if x not in (None, "") else "-"
    t = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    sembol = {"TRY": "₺", "TL": "₺", None: "₺"}.get(birim, str(birim))
    return f"{t} {sembol}"


def hb_adres_metni(a):
    """(adres, telefon) -> HB adres nesnesini düzgün yazıya çevirir."""
    if isinstance(a, dict):
        satir = [a.get("address") or a.get("addressDetail") or a.get("fullAddress"), a.get("town") or a.get("district"), a.get("city")]
        return ", ".join(str(x) for x in satir if x), str(a.get("phoneNumber") or a.get("phone") or "")
    return (str(a) if a else ""), ""


def hb_kargo_adi(x):
    if isinstance(x, dict):
        return str(x.get("name") or x.get("shortName") or "")
    return str(x or "")


def siparis_normalle_hb_coklu(p):
    """HB paketini sipariş(+müşteri) bazında ayırır: müşteri adı, sipariş no ve adres KALEMLERİN içindedir."""
    kalemler = [x for x in (p.get("items") or []) if isinstance(x, dict)]
    paket_no = str(p.get("packageNumber") or p.get("packageId") or p.get("id") or "")
    gruplar = {}
    for it in (kalemler or [{}]):
        no = str(it.get("orderNumber") or p.get("orderNumber") or "")
        musteri = str(it.get("customerName") or p.get("customerName") or p.get("recipientName") or "")
        gruplar.setdefault((no, musteri), []).append(it)
    cikti = []
    for (no, musteri), grup in gruplar.items():
        ilk = grup[0]
        adr_ham = ilk.get("shippingAddress") or ilk.get("deliveryAddress") or p.get("shippingAddress") or p.get("deliveryAddress")
        adres, tel = hb_adres_metni(adr_ham)
        alici = musteri or (adr_ham.get("name") if isinstance(adr_ham, dict) else "") or "Hepsiburada Müşterisi"
        toplam = 0.0
        for it in grup:
            tp = it.get("totalPrice")
            toplam += _f(tp.get("amount") if isinstance(tp, dict) else tp)
        if not toplam:
            tp = p.get("totalPrice")
            toplam = _f(tp.get("amount") if isinstance(tp, dict) else tp)
        durum = str(p.get("status") or ilk.get("status") or "").lower().replace(" ", "")
        cikti.append({
            "pid": "hb", "id": paket_no, "no": no, "paket_no": paket_no,
            "tarih": tr_tarih(ilk.get("orderDate") or p.get("orderDate")), "durum": HB_DURUM.get(durum, "yeni"),
            "alici": alici, "telefon": tel, "adres": adres,
            "urunler": [{"ad": it.get("productName") or "Ürün", "sku": it.get("merchantSku") or "", "adet": it.get("quantity", 1),
                         "fiyat": it.get("price")} for it in grup],
            "tutar": toplam, "kargo": hb_kargo_adi(p.get("cargoCompany") or ilk.get("cargoCompanyModel") or ilk.get("cargoCompany")),
            "barkod": str(p.get("barcode") or p.get("cargoBarcode") or p.get("trackingNumber") or ""),
            "ham": p,
        })
    return cikti


def siparis_normalle_hb(p):
    return siparis_normalle_hb_coklu(p)[0]


def siparis_normalle_tr(p):
    satirlar = p.get("items") or p.get("products") or []
    return {
        "pid": "trendruum", "id": str(p.get("id") or p.get("order_id") or ""),
        "no": str(p.get("order_number") or p.get("orderNo") or ""),
        "tarih": tr_tarih(p.get("created_at") or p.get("orderDate")),
        "durum": durum_kodu("trendruum", p.get("status")),
        "alici": p.get("customer_name") or p.get("recipient_name") or "Trendruum Müşterisi",
        "adres": metin(p.get("shipping_address") or p.get("address")),
        "urunler": [{"ad": l.get("name") or l.get("title") or "Ürün", "sku": l.get("barcode") or l.get("stock_code") or "",
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
        sonuc = []
        for x in hb_siparisler(ayar):
            sonuc += siparis_normalle_hb_coklu(x)
        return sonuc
    if pid == "trendruum":
        return [siparis_normalle_tr(x) for x in trendruum_siparisler(ayar)]
    raise RuntimeError(f"{PAZAR_AD.get(pid, pid)} için sipariş çekme desteklenmiyor.")


def siparis_stok_kontrol(ayar):
    """Yeni (açık) siparişlerde ürünün TEDARİKÇİ stoğu yetersizse uyarı üretir (günlük + Telegram).
    İlk çalıştırmada mevcut açık siparişler yalnızca 'görüldü' işaretlenir (uyarı yağmuru olmasın).
    Dönüş: uyarı metinleri listesi."""
    if not ayar.get("siparis_stok_uyari", True):
        return []
    u = urunleri_oku()
    if u.empty:
        return []
    kol = "stok_ham" if "stok_ham" in u.columns else "stok"
    ham = u.groupby("barkod")[kol].max().to_dict()
    uretilen = {}
    for b, v in ham.items():
        pb = sabit_barkod(b, True)
        if pb and pb != b:
            uretilen[pb] = v
    uyarilar = []
    for pid in ("trendyol", "n11", "hb", "trendruum"):
        if not pazar_bagli(ayar, pid):
            continue
        try:
            siparisler = siparis_cek(ayar, pid)
        except Exception as e:
            log_yaz(PAZAR_AD[pid], "HATA", f"Sipariş stok kontrolü: sipariş çekilemedi: {e}")
            continue
        with closing(baglan()) as c:
            ilk = c.execute("SELECT COUNT(*) FROM siparis_goruldu WHERE pazar = ?", (pid,)).fetchone()[0] == 0
            gorulen = {r[0] for r in c.execute("SELECT siparis FROM siparis_goruldu WHERE pazar = ?", (pid,))}
        yeni = []
        for o in siparisler:
            if o.get("durum") not in ("yeni", "hazir"):
                continue
            anahtar = f"{o.get('id') or ''}|{o.get('no') or ''}"
            if anahtar not in gorulen:
                yeni.append((anahtar, o))
        z = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if yeni:
            with closing(baglan()) as c:
                c.executemany("INSERT OR IGNORE INTO siparis_goruldu (pazar, siparis, zaman) VALUES (?,?,?)", [(pid, a, z) for a, _ in yeni])
                c.commit()
        if ilk:
            if yeni:
                log_yaz(PAZAR_AD[pid], "BILGI", f"Sipariş stok kontrolü başladı: {len(yeni)} mevcut açık sipariş görüldü olarak işaretlendi.")
            continue
        onek = str(pa_al(ayar, "hb").get("sku_prefix", "") or "") if pid == "hb" else ""
        for _, o in yeni:
            for ur in o.get("urunler", []):
                sku = str(ur.get("sku") or "")
                ham_sku = sku[len(onek):] if (onek and sku.startswith(onek)) else sku
                adet = max(_i(ur.get("adet"), 1), 1)
                stok = ham.get(ham_sku, ham.get(sku, uretilen.get(sku)))
                if stok is None:
                    sorun = "tedarikçi listesinde bulunamadı"
                elif stok < adet:
                    sorun = f"tedarikçi stoğu {int(stok)}, sipariş adedi {adet}"
                else:
                    continue
                uyarilar.append(f"{PAZAR_AD[pid]} sipariş {o.get('no') or o.get('id')}: {str(ur.get('ad'))[:60]} ({sku}) — {sorun}")
    if uyarilar:
        log_yaz("Sistem", "UYARI", f"{len(uyarilar)} siparişte stok sorunu: " + " || ".join(uyarilar)[:400])
        bildir("Yeni siparişte STOK SORUNU! Tedarikçiyi hemen kontrol edin veya siparişi iptal edin:\n" + "\n".join(uyarilar[:8]),
               tekil="siparis_stok:" + hashlib.md5("".join(uyarilar).encode()).hexdigest()[:10], bekleme_dk=1440)
    return uyarilar


# --------------------------------------------------------------------------
# Oturum (sayfa yenilense de açık kalır; imzalı, süreli jeton) ve giriş koruması
# --------------------------------------------------------------------------
def sifre_al():
    return gizli("APP_PASSWORD") or None


def _imza(sifre, ts):
    return hmac.new(str(sifre).encode(), f"oturum:{ts}".encode(), hashlib.sha256).hexdigest()


def oturum_jetonu(sifre):
    ts = str(int(time.time()))
    return f"{ts}.{_imza(sifre, ts)}"


def jeton_gecerli(jeton, sifre):
    try:
        ts, imza = str(jeton).split(".", 1)
        if not hmac.compare_digest(imza, _imza(sifre, ts)):
            return False
        if not (0 <= time.time() - int(ts) < OTURUM_SURESI):
            return False
        return int(ts) > int(kv_oku("oturum_iptal_ts", 0) or 0)  # çıkış yapılmışsa eski jetonlar geçersiz
    except Exception:
        return False


def oturumlari_iptal():
    """Çıkış: bu andan önce verilmiş tüm oturum jetonlarını geçersiz kılar."""
    kv_yaz("oturum_iptal_ts", int(time.time()))


def sifre_dogru_mu(girilen, sifre):
    return hmac.compare_digest(str(girilen).encode(), str(sifre).encode())


def giris_engeli_kalan():
    """Kaba kuvvet koruması (SUNUCU tarafı, oturumdan bağımsız): 5 hatadan sonra artan bekleme. Dönüş: kalan saniye."""
    d = kv_oku("giris_hata", {"n": 0, "ts": 0}) or {}
    n = int(d.get("n", 0))
    if n < 5:
        return 0
    bekle = min(5 * 2 ** (n - 5), 900)
    kalan = float(d.get("ts", 0)) + bekle - time.time()
    return int(kalan) + 1 if kalan > 0 else 0


def giris_hata_kaydet():
    d = kv_oku("giris_hata", {"n": 0, "ts": 0}) or {}
    kv_yaz("giris_hata", {"n": int(d.get("n", 0)) + 1, "ts": time.time()})


def giris_hata_sifirla():
    kv_yaz("giris_hata", {"n": 0, "ts": 0})


# --------------------------------------------------------------------------
# Arka plan döngüsü (arayüz bunu bir kez başlatır)
# --------------------------------------------------------------------------
def arka_plan_dongusu():
    time.sleep(30)
    while True:
        dk = 10.0
        try:
            ayar = ayar_oku()
            dk = senkron_dk_degeri(ayar)
            if ayar.get("oto_senkron", True):
                tumunu_senkronla()
            try:
                siparis_stok_kontrol(ayar)
            except Exception as e:
                log_yaz("Sistem", "HATA", f"Sipariş stok kontrolü: {e}")
            try:
                bayat_koruma(ayar_oku())
            except Exception as e:
                log_yaz("Sistem", "HATA", f"Bayat stok koruması: {e}")
        except Exception as e:
            try:
                log_yaz("Sistem", "HATA", f"Arka plan döngüsü: {e}")
            except Exception:
                pass
        time.sleep(dk * 60)
