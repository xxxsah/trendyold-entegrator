"""ŞahEntegre - E-Ticaret Yönetim Paneli (düzeltilmiş sürüm)

Çalıştırma:  streamlit run app.py
Gizli bilgiler için öncelik sırası: ortam değişkeni > st.secrets > ayarlar.json
Önerilen: APP_PASSWORD ortam değişkenini mutlaka tanımlayın.
"""
import base64
import gzip
import zlib
import hashlib
import hmac
import html
import ipaddress
import copy
import json
import math
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree.ElementTree import ParseError

try:  # Güvenli XML ayrıştırıcı (billion-laughs vb. saldırılara karşı)
    from defusedxml import ElementTree as ET
except ImportError:  # pragma: no cover
    import xml.etree.ElementTree as ET

import numpy as np
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
    "fiyat_sistemi": {},
    "zarar_korumasi": True,
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


# --------------------------------------------------------------------------
# Ayarlar
# --------------------------------------------------------------------------
class AyarSozluk(dict):
    """ayar_oku() sonucu. Okunduğu andaki hali (_taban) saklanır; ayar_yaz yalnızca BU nesnede gerçekten değişen anahtarları yazar,
    böylece uzun süren/eski bir oturum, kullanıcının o sırada kaydettiği diğer ayarları (acil durdur, fiyat sistemi vb.) ezemez."""
    _taban = None


def ayar_oku():
    veri = _ayar_oku_ham()
    sonuc = AyarSozluk(veri)
    try:
        sonuc._taban = copy.deepcopy(dict(veri))
    except Exception:
        sonuc._taban = None
    return sonuc


def _ayar_oku_ham():
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
    if not veri.get("senkron_dk_v1"):  # tek seferlik: 6 saatlik aralik yerine 10 dakika
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
    if not veri.get("fiyat_sistemi"):  # ayar dosyası bir şekilde eski haline döndüyse son kaydedilen fiyat sistemini geri getir
        yedek = kv_oku("fiyat_sistemi_yedek")
        if isinstance(yedek, dict) and yedek:
            veri["fiyat_sistemi"] = yedek
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


def _ayar_birlestir(ayar):
    """Eski bir nesneyle yazılıyorsa: yalnızca bu nesnede DEĞİŞEN anahtarları diskteki güncel ayara uygular."""
    taban = getattr(ayar, "_taban", None)
    if not isinstance(taban, dict):
        return ayar
    guncel = _ayar_oku_ham()
    degisen = 0
    for k in set(ayar) | set(taban):
        yeni, eski = ayar.get(k, _YOK), taban.get(k, _YOK)
        if json.dumps(yeni, sort_keys=True, default=str) == json.dumps(eski, sort_keys=True, default=str):
            continue
        degisen += 1
        if yeni is _YOK:
            guncel.pop(k, None)
        else:
            guncel[k] = yeni
    if degisen == 0 and guncel is not None:
        pass
    sonuc = AyarSozluk(guncel)
    sonuc._taban = copy.deepcopy(dict(guncel))
    return sonuc


_YOK = object()


def ayar_yaz(ayar):
    with KILIT:
        birlesik = _ayar_birlestir(ayar)
        if birlesik is not ayar:
            try:  # bellekteki nesneyi de güncel hale getir (sonraki yazmalar doğru tabandan başlasın)
                ayar.clear()
                ayar.update(birlesik)
                ayar._taban = birlesik._taban
            except Exception:
                pass
            ayar = birlesik
        tmp = AYAR_DOSYA.with_name(f"ayarlar.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(ayar, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)  # API anahtarları sadece sahibi tarafından okunabilsin
        except OSError:
            pass
        tmp.replace(AYAR_DOSYA)


def ayar_kismi_yaz(degistir, ayar_bellek=None):
    """Arka plan/uzun işlemlerde ESKİ kalmış 'ayar' nesnesini tümüyle diske yazmak, kullanıcının o sırada kaydettiği ayarları (ör. fiyat sistemi) ezer.
    Bunun yerine diskteki güncel ayarı okur, yalnızca ilgili alanı değiştirir ve yazar."""
    taze = ayar_oku()
    degistir(taze)
    ayar_yaz(taze)
    if ayar_bellek is not None:
        degistir(ayar_bellek)


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
        c.execute("""CREATE TABLE IF NOT EXISTS pazar_son (
            pazar TEXT, barkod TEXT, stok INTEGER, fiyat REAL, zaman TEXT, PRIMARY KEY (pazar, barkod))""")
        c.execute("""CREATE TABLE IF NOT EXISTS stok_yedek (
            tedarikci TEXT, barkod TEXT, stok INTEGER, zaman TEXT, PRIMARY KEY (tedarikci, barkod))""")
        c.execute("""CREATE TABLE IF NOT EXISTS senkron_ozet (
            id INTEGER PRIMARY KEY AUTOINCREMENT, zaman TEXT, tedarikci TEXT, urun INTEGER, stoklu INTEGER,
            toplam_stok INTEGER, ornek TEXT, sonuc TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS durum_kv (anahtar TEXT PRIMARY KEY, deger TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS siparis_goruldu (
            pazar TEXT, siparis TEXT, zaman TEXT, PRIMARY KEY (pazar, siparis))""")
        c.commit()


def log_yaz(tedarikci, durum, mesaj=""):
    with closing(baglan()) as c:
        c.execute(
            "INSERT INTO senkron_log (zaman, tedarikci, durum, mesaj) VALUES (?,?,?,?)",
            (simdi_tr().strftime("%Y-%m-%d %H:%M:%S"), tedarikci, durum, str(mesaj)[:500]),
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


def stok_sifirla(ayar, barkodlar, pazarlara_gonder=True, pazarlar=None):
    """Barkodlari kilitler, veritabaninda stogu 0 yapar ve istenirse bagli pazar yerlerine hemen gonderir.
    Donus: [(pazar_adi, ok, hata_ya_da_mesaj), ...]"""
    barkodlar = sorted({str(b).strip() for b in barkodlar if str(b).strip()})
    if not barkodlar:
        return []
    z = simdi_tr().strftime("%Y-%m-%d %H:%M:%S")
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
        for pid in (pazarlar or GUNCELLEYICI):
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
    z = simdi_tr().strftime("%Y-%m-%d %H:%M:%S")
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
                d_ = zlib.decompressobj(16 + zlib.MAX_WBITS)  # sınırlı açma: sıkıştırılmış dev dosya belleği şişirmesin
                veri = d_.decompress(veri, MAKS_XML_BOYUT)
                if d_.unconsumed_tail:
                    raise ValueError("Sıkıştırılmış XML açıldığında çok büyük (300 MB üstü).")
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


def stok_ust_degeri(ayar):
    """Stok ust siniri; 0 ya da bos = sinirsiz."""
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
    """Hedef NET kar icin satis fiyati: P = (alis + giderler + hedef*(1+kdv)/(1-vergi)) / (1-komisyon).
    Alis fiyati KDV dahil kabul edilir; komisyon KDV dahil orandir."""
    c, t, kdv, gider = hedef_parametreleri(bilgi)
    hedef = kademeli_marj(alis, bilgi.get("hedef_kademe") or VARSAYILAN_HEDEF, _f(bilgi.get("hedef_net"), 100.0))
    return ((alis + gider + hedef * (1 + kdv) / (1 - t)) / (1 - c)).round(2)


def net_kar_hesapla(satis, alis, bilgi):
    """Verilen satis fiyatinda komisyon, kargo, KDV ve vergi dusuldukten sonra kalan net kar (TL)."""
    c, t, kdv, gider = hedef_parametreleri(bilgi)
    m = satis * (1 - c) - alis - gider
    vergi_sonrasi = m / (1 + kdv)
    return vergi_sonrasi.where(m <= 0, vergi_sonrasi * (1 - t)).round(2)


def ad_temizle(x):
    t = html.unescape(html.unescape(str(x)))
    return re.sub(r"\s+", " ", t).strip()


DOVIZ_TL = {"TL", "TRY", "TRL", "₺"}
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


PERAKENDE_IPUCU = ("perakende", "retail", "piyasa", "liste", "pesin", "etiket")
BAYI_IPUCU = ("bayi", "toptan", "dealer", "wholesale", "maliyet", "alis", "alış")


def bayi_fiyat_alani(kolonlar, secili):
    """Seçili fiyat alanı perakende/liste fiyatıysa ve XML'de bayi/toptan fiyat alanı da varsa onu döndürür; yoksa None.
    (Alış fiyatı olarak perakende fiyatı okunursa tüm satış fiyatları şişer.)"""
    sl = str(secili or "").lower()
    if not any(i in sl for i in PERAKENDE_IPUCU):
        return None
    adaylar = [k for k in kolonlar if any(i in str(k).lower() for i in BAYI_IPUCU)
               and "fiyat" in str(k).lower() and "." not in str(k) and "variant" not in str(k).lower()]
    return adaylar[0] if adaylar else None


def normalle(tedarikci, df, harita, marj, sabit_ek, kritik_esik=0, stok_ust=0, bilgi=None):
    bilgi = dict(bilgi or {})
    _fk0 = (harita or {}).get("fiyat", "(yok)")
    _bayi = bayi_fiyat_alani(df.columns, _fk0)
    if _bayi:  # yanlış (perakende) fiyat alanı seçilmiş: bayi/toptan alanını kullan
        harita = dict(harita)
        harita["fiyat"] = _bayi
        if "kdv_ekle" not in bilgi and any(str(k).lower() in ("kdvorani", "kdv", "vat") for k in df.columns):
            bilgi["kdv_ekle"] = True  # bayi fiyatı KDV hariç gelir; KDV alanı varsa eklenir (ayarda kdv_ekle'yi kapatırsanız uygulanmaz)
        try:
            log_yaz(tedarikci, "BILGI", f"Fiyat alanı '{_fk0}' (perakende) yerine '{_bayi}' (bayi/toptan) kullanıldı.")
        except Exception:
            pass

    def kol(ad):
        k = harita.get(ad, "(yok)")
        if k == "(yok)" or k not in df.columns:
            return pd.Series([""] * len(df), index=df.index)
        return df[k]

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
    if bilgi.get("hedef_aktif"):
        satis = hedef_fiyat(alis, bilgi).where((~bilinmeyen) & (alis > 0), 0.0)
    else:
        satis = (alis * (1 + marj_s / 100) + sabit_ek).where(~bilinmeyen, 0.0)
    ust_s = int(stok_ust) if stok_ust and int(stok_ust) > 0 else None  # None = sinirsiz
    stok = kol("stok").map(sayi).clip(lower=0, upper=ust_s).astype(int)
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


BEKLEYEN_SIFIR = {}  # tedarikci -> (barkod kümesi, ilk görülme zamanı): ani toplu sıfırlama teyidi bekliyor


def kv_oku(anahtar, varsayilan=None):
    """Küçük kalıcı durum deposu (bildirim bekleme süresi vb.)."""
    try:
        with closing(baglan()) as c:
            r = c.execute("SELECT deger FROM durum_kv WHERE anahtar = ?", (anahtar,)).fetchone()
        return json.loads(r[0]) if r else varsayilan
    except Exception:
        return varsayilan


def kv_yaz(anahtar, deger):
    try:
        with closing(baglan()) as c:
            c.execute("INSERT OR REPLACE INTO durum_kv (anahtar, deger) VALUES (?, ?)", (anahtar, json.dumps(deger)))
            c.commit()
    except Exception:
        pass


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
                    if (simdi_tr() - datetime.strptime(son, "%Y-%m-%d %H:%M:%S")).total_seconds() < bekleme_dk * 60:
                        return False
                except ValueError:
                    pass
            kv_yaz(f"bildirim:{tekil}", simdi_tr().strftime("%Y-%m-%d %H:%M:%S"))
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": f"ŞahEntegre: {mesaj}"[:3500]}, timeout=15)
        return r.status_code == 200
    except Exception:
        return False


def sifir_teyit(ad, eski, yeni, simdi=None):
    """Orta büyüklükte ANİ toplu sıfırlamayı (tedarikçi XML'i geçici bozuk/boş stok verdiğinde olur) hemen uygulamaz:
    aynı ürünler en az 4 dakika sonraki bir sonraki turda da sıfır gelirse gerçek kabul edilir.
    Küçük sıfırlamalar (birkaç ürün) bekletilmeden uygulanır. Dönüş: bekletme nedeni metni ya da None."""
    if eski is None or eski.empty or yeni.empty:
        BEKLEYEN_SIFIR.pop(ad, None)
        return None
    pozitif = eski[eski["stok"].map(_i) > 0]
    if len(pozitif) < 20:
        BEKLEYEN_SIFIR.pop(ad, None)
        return None
    yeni_stok = yeni.assign(_b=yeni["barkod"].astype(str)).groupby("_b")["stok"].max()
    eb = pozitif["barkod"].astype(str)
    simdi_stok = eb.map(yeni_stok)
    sifirlanan = set(eb[(simdi_stok == 0)])
    esik = max(10, int(0.03 * len(pozitif)))
    if len(sifirlanan) < esik:
        BEKLEYEN_SIFIR.pop(ad, None)
        return None
    t = simdi if simdi is not None else time.time()
    onceki = BEKLEYEN_SIFIR.get(ad)
    if onceki and len(sifirlanan & onceki[0]) >= 0.8 * len(sifirlanan):
        if t - onceki[1] >= 240:
            BEKLEYEN_SIFIR.pop(ad, None)
            return None  # teyit edildi: gerçek
        BEKLEYEN_SIFIR[ad] = (sifirlanan, onceki[1])
    else:
        BEKLEYEN_SIFIR[ad] = (sifirlanan, t)
    return f"{len(sifirlanan)} ürünün stoğu aniden 0 geldi; bir sonraki turda da aynı gelirse uygulanacak (geçici XML hatalarına karşı koruma)"


def son_fiyatlar(pid):
    """Bu pazara en son başarıyla gönderilen fiyatlar {barkod: fiyat}; fiyatı olmayan üründe stok yine de gidebilsin."""
    with closing(baglan()) as c:
        return {str(r[0]): float(r[1]) for r in c.execute(
            "SELECT barkod, fiyat FROM pazar_son WHERE pazar = ? AND barkod != '__tam__' AND fiyat > 0", (pid,))}


def fiyat_belirle(r, son):
    f = round(_f(r.get("satis_fiyati")), 2)
    if f > 0:
        return f
    return round(son.get(str(r["barkod"]), 0.0), 2)


def son_log_uyari(parca, saat=24):
    """Son 'saat' içinde UYARI durumunda, mesajı 'parca' içeren en yeni günlük kaydı (zaman, tedarikci, mesaj) ya da None."""
    try:
        with closing(baglan()) as c:
            r = c.execute("SELECT zaman, tedarikci, mesaj FROM senkron_log WHERE durum = 'UYARI' AND mesaj LIKE ? ORDER BY id DESC LIMIT 1",
                          (f"%{parca}%",)).fetchone()
        if r and (simdi_tr() - datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S")).total_seconds() < saat * 3600:
            return r
    except Exception:
        pass
    return None


def senkron_supheli_mi(eski, yeni):
    """Yeni XML eskisine gore mantiksiz degismis mi? (kismi/bozuk XML, tedarikci stoklari sifirladi vb.) -> neden metni ya da None."""
    if eski is None or eski.empty or len(eski) < 30 or yeni.empty:
        return None
    eb = eski["barkod"].astype(str)
    yeni_stok = yeni.assign(_b=yeni["barkod"].astype(str)).groupby("_b")["stok"].max()
    eksik = int((~eb.isin(set(yeni_stok.index))).sum())
    if eksik > 0.25 * len(eski):
        return f"XML'deki ürün sayısı aniden düştü (eski {len(eski)}, yeni {len(yeni)}; {eksik} ürün yok)"
    pozitif = eski[eski["stok"].map(_i) > 0]
    if len(pozitif) >= 20:
        simdi = pozitif["barkod"].astype(str).map(yeni_stok)
        sifirlanan = int((simdi == 0).sum())
        if sifirlanan > 0.40 * len(pozitif):
            return f"stoğu olan {len(pozitif)} üründen {sifirlanan} tanesi aynı anda 0'a düştü"
    return None


def senkron_ozeti_yaz(ad, df, ornek, sonuc):
    """Her senkronun ozetini kaydeder (stoklar neden sifirlandi sorusunun KANITI)."""
    try:
        with closing(baglan()) as c:
            c.execute("INSERT INTO senkron_ozet (zaman, tedarikci, urun, stoklu, toplam_stok, ornek, sonuc) VALUES (?,?,?,?,?,?,?)",
                      (simdi_tr().strftime("%Y-%m-%d %H:%M:%S"), ad, int(len(df)), int((df["stok"] > 0).sum()),
                       int(df["stok"].sum()), str(ornek)[:200], str(sonuc)[:300]))
            c.execute("DELETE FROM senkron_ozet WHERE id NOT IN (SELECT id FROM senkron_ozet ORDER BY id DESC LIMIT 300)")
            c.commit()
    except Exception:
        pass


def stok_yedegi_al(ad, df):
    """Saglikli (urunlerin en az %20'si stoklu) senkron sonrasi stoklarin yedegini alir."""
    if len(df) < 50 or int((df["stok"] > 0).sum()) < 0.2 * len(df):
        return False
    z = simdi_tr().strftime("%Y-%m-%d %H:%M:%S")
    with closing(baglan()) as c:
        c.execute("DELETE FROM stok_yedek WHERE tedarikci = ?", (ad,))
        c.executemany("INSERT OR REPLACE INTO stok_yedek (tedarikci, barkod, stok, zaman) VALUES (?,?,?,?)",
                      [(ad, str(b), int(sk), z) for b, sk in zip(df["barkod"], df["stok"])])
        c.commit()
    return True


def stok_saglik():
    """(toplam urun, stoklu urun, yedekte stoklu urun)"""
    with closing(baglan()) as c:
        toplam = c.execute("SELECT COUNT(*) FROM urunler").fetchone()[0]
        stoklu = c.execute("SELECT COUNT(*) FROM urunler WHERE CAST(stok AS INTEGER) > 0").fetchone()[0]
        yedek = c.execute("SELECT COUNT(*) FROM stok_yedek WHERE stok > 0").fetchone()[0]
    return int(toplam), int(stoklu), int(yedek)


def stok_sorunlu_mu(toplam, stoklu, yedek):
    """Urunlerin %85'inden fazlasi 0 gorunuyor ama yedekte ciddi stok var -> bozulma."""
    return toplam >= 100 and stoklu < 0.15 * toplam and yedek >= 0.30 * toplam


def stok_yedekten_geri_yukle(ayar, pazarlara_gonder=True):
    """Son SAGLIKLI senkrondaki stoklari geri yukler; elle kilitli urunler 0 kalir. Donus: (guncellenen, [(pazar, ok, hata)])"""
    with closing(baglan()) as c:
        n = c.execute("""UPDATE urunler SET stok = (SELECT y.stok FROM stok_yedek y WHERE y.tedarikci = urunler.tedarikci AND y.barkod = urunler.barkod)
                         WHERE EXISTS (SELECT 1 FROM stok_yedek y WHERE y.tedarikci = urunler.tedarikci AND y.barkod = urunler.barkod)""").rowcount
        kilit = sorted(stok_sifir_kume(ayar))
        for i in range(0, len(kilit), 500):
            parca = kilit[i:i + 500]
            c.execute(f"UPDATE urunler SET stok = 0 WHERE barkod IN ({','.join('?' * len(parca))})", parca)
        c.commit()
    sonuc = []
    if pazarlara_gonder:
        df = urunleri_oku()
        for pid in GUNCELLEYICI:
            if pazar_bagli(ayar, pid):
                try:
                    ok, hata, _ = pazara_gonder(ayar, pid, df)
                    sonuc.append((PAZAR_AD.get(pid, pid), ok, hata))
                except Exception as e:
                    sonuc.append((PAZAR_AD.get(pid, pid), 0, str(e)))
    return int(n), sonuc


def tedarikci_senkron(ad, bilgi, kritik_esik=0, stok_ust=0, zorla=False):
    df_ham = xml_oku(indir(bilgi["link"], _f(bilgi.get("zaman_asimi"), 300.0)))
    _sk = (bilgi.get("harita") or {}).get("stok")
    ham_ornek = ", ".join(str(x) for x in df_ham[_sk].head(8).tolist()) if (_sk and _sk in df_ham.columns) else "(stok alanı XML'de yok)"
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
        raise ValueError("XML'den geçerli ürün çıkmadı. Alan eşleştirmesini kontrol edin.")
    if not zorla:  # otomatik turda bozuk/kismi XML pazar yerlerini topluca kapatmasin
        eski_urunler = urunleri_oku()
        eski_urunler = eski_urunler[eski_urunler["tedarikci"] == ad]
        neden = senkron_supheli_mi(eski_urunler, df)
        if neden:
            senkron_ozeti_yaz(ad, df, ham_ornek, "REDDEDİLDİ: " + neden)
            log_yaz(ad, "UYARI", f"Toplu stok değişimi algılandı: {neden}. Şüpheli XML uygulanmadı, eski veri korundu. Doğruysa Ayarlar > Tedarikçiler'deki '⚠️ Düşüşü kabul et ve senkronla' düğmesiyle uygulayın.")
            bildir(f"{ad}: toplu stok değişimi algılandı ({neden}). Şüpheli XML uygulanmadı, pazar yerleri korundu.", tekil=f"supheli:{ad}", bekleme_dk=120)
            raise ValueError(f"Toplu stok değişimi algılandı: {neden}. Eski veri korundu. Doğruysa Ayarlar > Tedarikçiler'den 'Düşüşü kabul et ve senkronla'ya basın.")
        teyit = sifir_teyit(ad, eski_urunler, df)
        if teyit:
            senkron_ozeti_yaz(ad, df, ham_ornek, "BEKLETİLDİ: " + teyit)
            log_yaz(ad, "UYARI", f"Ani toplu sıfırlama bekletildi: {teyit}. Eski stoklar korundu.")
            raise ValueError(f"{teyit}. Eski veri korundu.")
    kilit = stok_sifir_kume(ayar_oku())
    if kilit:  # elle sifirlanan urunler tedarikci stogu gelse bile 0 kalir
        df.loc[df["barkod"].astype(str).isin(kilit), "stok"] = 0
    df = fiyat_override_uygula(ayar_oku(), df)  # elle belirlenen satis fiyatlari senkronda ezilmez
    sutunlar = ["gorsel", "tedarikci", "barkod", "urun_adi", "stok", "alis_fiyati", "satis_fiyati", "kategori"]
    kayip = 0
    with closing(baglan()) as c:
        try:
            c.execute("BEGIN IMMEDIATE")
            # Tedarikci XML'inden cikan ama pazar yerine gonderilmis urunleri SILME: stok 0 olarak tut ki pazarlar da 0'lansin.
            eski_df = pd.read_sql("SELECT gorsel, tedarikci, barkod, urun_adi, stok, alis_fiyati, satis_fiyati, kategori FROM urunler WHERE tedarikci = ?", c, params=(ad,))
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
            c.execute("DELETE FROM urunler WHERE tedarikci = ?", (ad,))
            c.executemany(
                "INSERT INTO urunler (gorsel, tedarikci, barkod, urun_adi, stok, alis_fiyati, satis_fiyati, kategori) VALUES (?,?,?,?,?,?,?,?)",
                df[sutunlar].itertuples(index=False, name=None),
            )
            if kayip:
                c.executemany(
                    "INSERT INTO urunler (gorsel, tedarikci, barkod, urun_adi, stok, alis_fiyati, satis_fiyati, kategori) VALUES (?,?,?,?,?,?,?,?)",
                    kayip_df[sutunlar].itertuples(index=False, name=None),
                )
            c.commit()
        except Exception:
            c.rollback()
            raise
    if kayip:
        log_yaz(ad, "BILGI", f"{kayip} ürün tedarikçi XML'inde artık yok; pazar yerlerinde satışta kalmasın diye stokları 0 yapıldı.")
    yedeklendi = False
    if zorla:  # 'Düşüşü kabul et': eski sağlıklı yedek artık geçersiz, geri yüklenmesin
        try:
            with closing(baglan()) as c_y:
                c_y.execute("DELETE FROM stok_yedek WHERE tedarikci = ?", (ad,))
                c_y.commit()
        except Exception:
            pass
    try:
        yedeklendi = stok_yedegi_al(ad, df)
    except Exception:
        pass
    senkron_ozeti_yaz(ad, df, ham_ornek, "uygulandı" + (" (yedek alındı)" if yedeklendi else " (stoklu ürün az: YEDEK ALINMADI)"))
    return len(df)


# --------------------------------------------------------------------------
# Fiyat kuralları ve ortak yardımcılar
# --------------------------------------------------------------------------
UST_KADEME_VARSAYILAN = [[2000, 400], [3000, 500], [4000, 600], [5000, 700], [6000, 800], [7000, 900], [10000, 1000]]
FIYAT_VARSAYILAN = {"aktif": False, "gider": 140.0, "net_kar_yuzde": 30.0, "yuzde_siniri": 1000.0,
                    "ust_kademe": UST_KADEME_VARSAYILAN, "tedarikci_yuzde": {}, "pazar": {}}


def fiyat_sistemi(ayar):
    """Genel fiyat sistemi: aktifse ve kaydedilmişse sözlüğü döndürür."""
    fs = ayar.get("fiyat_sistemi") or {}
    if not fs:  # hiç kaydedilmemiş / ayar dosyası sıfırlanmış: tedarikçi fiyatı ASLA pazara gitmesin, varsayılan sistem devrede olsun
        fs = json.loads(json.dumps(FIYAT_VARSAYILAN))
        fs["aktif"] = True
    return fs if fs.get("aktif") else None


def ust_kademe_temizle(kademe):
    out = []
    for r in (kademe or []):
        try:
            a_, n_ = float(r[0]), float(r[1])
        except (TypeError, ValueError, IndexError):
            continue
        if a_ == a_ and n_ == n_ and a_ > 0 and n_ >= 0:
            out.append([a_, n_])
    out.sort()
    return out


def net_kar_hesapla_alis(alis, yuzde, fs):
    """Alış ≤ yüzde sınırı: alış × yüzde. Üstü: kademe tablosundaki noktalar arasında doğrusal ara değer
    (sınırdaki nokta = sınır × yüzde; son noktanın ötesinde son net kâr sabit kalır)."""
    alis = pd.Series(alis, dtype=float)
    yuzde = pd.Series(yuzde, index=alis.index, dtype=float)
    esik = _f(fs.get("yuzde_siniri"), 1000.0)
    net = alis * yuzde / 100
    tablo = [r for r in ust_kademe_temizle(fs.get("ust_kademe")) if r[0] > esik]
    ust = alis > esik
    if ust.any() and tablo:
        xs0 = [esik] + [r[0] for r in tablo]
        for y_ in yuzde[ust].unique():
            m = ust & (yuzde == y_)
            ys = [esik * y_ / 100] + [r[1] for r in tablo]
            net[m] = np.interp(alis[m].values, xs0, ys)
    return net


def fiyat_sistemi_hesapla(alis, tedarikci, pid, fs):
    """Satış = (alış + sabit gider + net kâr) / (1 - komisyon). Komisyon satış fiyatından kesildiği için fiyatın içine baştan katılır;
    net kâr tüm kesintiler sonrası cebe kalan paradır."""
    alis = pd.Series(alis, dtype=float)
    pz = (fs.get("pazar") or {}).get(pid) or {}
    kom = min(max(_f(pz.get("komisyon"), 20.0), 0.0), 80.0) / 100
    carpan = max(_f(pz.get("carpan"), 100.0), 0.0) / 100
    yz_t = fs.get("tedarikci_yuzde") or {}
    genel = _f(fs.get("net_kar_yuzde"), 30.0)
    if tedarikci is None:
        yuzde = pd.Series(genel, index=alis.index)
    else:
        tadi = pd.Series(tedarikci, index=alis.index)
        yuzde = tadi.map(lambda t: _f(yz_t.get(t), genel) if (t in yz_t and str(yz_t.get(t)).strip() != "") else genel).astype(float)
    net = net_kar_hesapla_alis(alis, yuzde, fs) * carpan
    fiyat = (alis + _f(fs.get("gider"), 140.0) + net) / (1 - kom)
    return fiyat.map(lambda x: float(math.ceil(x)) if x == x else x), net


def _fiyat_sistemi_uygula(ayar, pid, fs, df):
    df = df.copy()
    anahtar = df["barkod"].astype(str)
    if "alis_fiyati" in df.columns and "tedarikci" in df.columns:
        alis = df["alis_fiyati"].map(_f)
        tadi = df["tedarikci"]
    else:
        with closing(baglan()) as c:
            ref = pd.read_sql("SELECT barkod, tedarikci, alis_fiyati FROM urunler", c)
        ref["barkod"] = ref["barkod"].astype(str)
        ref = ref.drop_duplicates("barkod").set_index("barkod")
        alis = anahtar.map(ref["alis_fiyati"]).map(_f)
        tadi = anahtar.map(ref["tedarikci"])
    yeni, _net = fiyat_sistemi_hesapla(alis.values, tadi.values, pid, fs)
    yeni.index = df.index
    df["satis_fiyati"] = yeni.where(alis > 0, df["satis_fiyati"]).round(2)
    return df


def _fiyat_artis_ham(ayar, pid, df):
    _fs = fiyat_sistemi(ayar)
    if _fs and not df.empty and "satis_fiyati" in df.columns and "barkod" in df.columns:
        return _fiyat_sistemi_uygula(ayar, pid, _fs, df)
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
    """Tedarikcinin guncel marj/kargo/kademe ayariyla satis fiyatlarini, XML indirmeden, kayitli alis fiyatindan yeniden hesaplar."""
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
    d = fiyat_override_uygula(ayar_oku(), d)  # elle belirlenen fiyatlar korunur
    eski = df.loc[d.index, "satis_fiyati"].map(_f)
    degisen = d[(d["satis_fiyati"].map(_f) - eski).abs() > 0.004]
    with closing(baglan()) as c:
        c.executemany("UPDATE urunler SET satis_fiyati = ? WHERE tedarikci = ? AND barkod = ?",
                      [(float(r["satis_fiyati"]), ad, str(r["barkod"])) for _, r in degisen.iterrows()])
        c.commit()
    return len(degisen)


def urun_ara(f, ara):
    """Ad, tedarikci barkodu ya da PAZAR YERINE GIDEN barkod (uretilen/duzeltilen) ile arar."""
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
    """Elle belirlenen (sabit) satis fiyatlari, marj/kargo/artis hesabindan sonra kesin fiyat olur."""
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
    """Secilen urunlerin satis fiyatini elle sabitler; istenirse bagli pazar yerlerine hemen gonderir."""
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


_CAKISMA_ONBELLEK = {"zaman": 0.0, "kume": set()}


def _barkod_cakisanlar():
    """Rakamları ayıklanınca AYNI barkoda dönüşen farklı stok kodlarını bulur (ör. CLZ174-83034 ve CLZ17-483034 -> 17483034).
    Pazar yerleri barkodun benzersiz olmasını ister; çakışanlara benzersiz (hash) barkod verilir."""
    simdi = time.time()
    if simdi - _CAKISMA_ONBELLEK["zaman"] < 600:
        return _CAKISMA_ONBELLEK["kume"]
    kume = set()
    try:
        with closing(baglan()) as c:
            kodlar = [str(r[0]) for r in c.execute("SELECT DISTINCT barkod FROM urunler")]
        harita = {}
        for k in kodlar:
            if gecerli_barkod(k):
                continue
            t = "".join(ch for ch in k if ch.isdigit())
            if 8 <= len(t) <= 14:
                harita.setdefault(t, []).append(k)
        for lst in harita.values():
            if len(lst) > 1:
                kume.update(lst)
    except Exception:
        pass
    _CAKISMA_ONBELLEK.update({"zaman": simdi, "kume": kume})
    return kume


def sabit_barkod(kod, uret=False):
    """Aynı koddan her zaman aynı barkodu üretir (Python hash() KULLANILMAZ)."""
    g = gecerli_barkod(kod)
    if g:
        return g
    if not uret:
        return None
    temiz = "".join(ch for ch in str(kod) if ch.isdigit())
    if 8 <= len(temiz) <= 14 and str(kod) not in _barkod_cakisanlar():
        return temiz
    h = int(hashlib.md5(str(kod).encode()).hexdigest(), 16) % 10**9
    return f"869{h:09d}"


SON_PAKET = {"ok": [], "hata": []}  # son paketle() çağrısının başarılı/hatalı anahtarları


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
    SON_PAKET["ok"], SON_PAKET["hata"] = list(ok_k), list(hata_k)
    return ok_k, hata_k, loglar


def _sonuc(pid, ok_k, hata_k, loglar, atlanan=0, tukenen_atlanan=0):
    try:
        pazar_isaretle(pid, ok_k, hata_k)
    except Exception:
        pass
    if atlanan:
        loglar.append(f"ℹ️ {atlanan} ürün eksik bilgi (fiyat/barkod) nedeniyle atlandı.")
    if tukenen_atlanan:  # en tehlikeli durum: stoğu 0 olan ürün gönderilemedi, pazarda eski stokla satışta kalabilir
        mesaj_ = (f"{PAZAR_AD.get(pid, pid)}: {tukenen_atlanan} TÜKENEN ürünün stoğu fiyat/barkod bilgisi olmadığı için "
                  "pazar yerine GÖNDERİLEMEDİ; bu ürünler pazarda eski stokla satışta kalmış olabilir.")
        loglar.append("⚠️ " + mesaj_)
        log_yaz(PAZAR_AD.get(pid, pid), "UYARI", mesaj_)
        bildir(mesaj_, tekil=f"tukenen_atlandi:{pid}", bekleme_dk=120)
    return len(ok_k), len(hata_k), loglar


def https_yap(url):
    """http:// adreslerini https:// yapar (N11/HB/İdefix yalnızca https görsel kabul eder; çoğu CDN iki biçimi de sunar)."""
    u = str(url or "").strip()
    return "https://" + u[7:] if u.lower().startswith("http://") else u


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


def trendyol_siparisler(seller, key, secret, durum="Created", boyut=50, sayfa_siniri=4):
    sonuc = []
    for sayfa in range(sayfa_siniri):
        r = http(
            "GET", f"{TY_BASE}/order/sellers/{seller}/orders",
            params={"status": durum, "size": boyut, "page": sayfa, "orderByField": "PackageLastModifiedDate", "orderByDirection": "DESC"},
            headers=trendyol_header(seller, key, secret), timeout=30,
        )
        r.raise_for_status()
        icerik = r.json().get("content", []) or []
        sonuc += icerik
        if len(icerik) < boyut:
            break
    return sonuc


def trendyol_guncelle(ayar, df, ilerleme=None):
    s, k, x = (kimlik(ayar, a) for a in ("trendyol_seller_id", "trendyol_key", "trendyol_secret"))
    kayit, atlanan, tukenen_atlanan = [], 0, 0
    son = son_fiyatlar("trendyol")
    for r in kayit_listesi(df):
        fiyat = fiyat_belirle(r, son)
        stok = int(min(max(_i(r.get("stok")), 0), 20000))
        b = str(r["barkod"])
        govde = {"barcode": b, "quantity": stok}
        if fiyat > 0:
            govde["salePrice"] = fiyat
            govde["listPrice"] = fiyat
        elif stok > 0:
            atlanan += 1  # fiyatsız ve stoklu ürün satışa açılmaz
            continue
        # fiyatsız + stok 0: yalnız stok (0) gider; ürün satıştan kalkar
        kayit.append((b, govde))

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
    kayit, atlanan, tukenen_atlanan = [], 0, 0
    son = son_fiyatlar("n11")
    for r in kayit_listesi(df):
        fiyat = fiyat_belirle(r, son)
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

    ok_k, hata_k, loglar = paketle(kayit, 1000, gonder, ilerleme, "N11")
    return _sonuc("n11", ok_k, hata_k, loglar, atlanan, tukenen_atlanan)


def n11_urun_listesi(df, ayar):
    pa = pa_al(ayar, "n11")
    cat_varsayilan = _i(pa.get("category_id"))
    atr = pa.get("attributes") or []
    sablon = str(pa.get("shipment_template", "") or "").strip()
    if not sablon:
        raise ValueError("N11 için 'Kargo şablonu' ayarı boş. Genel Ayarlar'dan girin.")
    liste, atlanan = [], 0
    for r in kayit_listesi(df):
        gorsel = https_yap(str(r.get("gorsel", "")).strip())
        kod = str(r["barkod"]).strip()
        fiyat = round(_f(r.get("satis_fiyati")), 2)
        cat = _i(kat_sec(pa, ayar, r.get("kategori"), "n11"))
        if not gorsel.startswith("https") or fiyat <= 0 or not kod or cat <= 0:
            atlanan += 1
            continue
        ad = str(r["urun_adi"]).strip()
        u_ = {
            "title": ad[:100], "description": ad, "categoryId": cat, "currencyType": "TL",
            "productMainId": kod, "preparingDay": _i(pa.get("preparing_day"), 3) or 3,
            "shipmentTemplate": sablon, "stockCode": kod,
            "barcode": gecerli_barkod(kod), "quantity": max(_i(r.get("stok")), 0),
            "images": [{"url": gorsel, "order": 1}], "attributes": atr,
            "salePrice": fiyat, "listPrice": fiyat, "vatRate": _i(pa.get("kdv"), 20),
        }
        liste.append({k_: v_ for k_, v_ in u_.items() if v_ is not None})  # null alanlar N11'de doğrulama hatası verebilir
    return liste, atlanan


def n11_urun_gonder(ayar, liste, ilerleme=None):
    h = n11_header(kimlik(ayar, "n11_key"), kimlik(ayar, "n11_secret"))
    kayit = [(u["stockCode"], u) for u in liste]

    def gonder(grup):
        r = http("POST", f"{N11_BASE}/ms/product/tasks/product-create", headers=h, timeout=120, tries=2,
                 json={"payload": {"integrator": "SahEntegre", "skus": grup}})
        ozet = yanit_ozet(r)
        ok = r.status_code == 200
        try:
            j = r.json()
        except Exception:
            j = None
        if isinstance(j, dict):
            if j.get("errors"):
                ok = False  # HTTP 200 olsa bile gövdede hata varsa başarılı sayma
            tid = j.get("id") or j.get("taskId")
            if not tid and isinstance(j.get("data"), dict):
                tid = j["data"].get("id") or j["data"].get("taskId")
            if tid and ok:
                n11_takip_ekle(tid)
                ozet += f" | görev no: {tid} (kabul = ürün onayı değildir; sonucu 'N11 görev sonucu'ndan sorgulayın)"
        return ok, ozet

    ok_k, hata_k, loglar = paketle(kayit, 100, gonder, ilerleme, "N11", durdur=6)
    return len(ok_k), len(hata_k), loglar


def n11_gorev_ozet(j):
    """N11 görev yanıtından (biçimi bilinmediği için genel tarama) durum sayıları ve en sık hata mesajları."""
    durum, mesaj = Counter(), Counter()
    ornek = {}

    def gez(x, bag=None):
        if isinstance(x, dict):
            d = str(x.get("importStatus") or x.get("status") or x.get("state") or "").strip()
            ms = []
            for k in ("reasons", "reason", "errors", "error", "message", "errorMessage", "failReasons", "failReason", "importMessages", "validationResults", "rejectReasonsMessages"):
                v = x.get(k)
                if isinstance(v, str) and v.strip():
                    ms.append(v.strip())
                elif isinstance(v, list):
                    for e in v:
                        ms.append(str(e.get("message") or e.get("reason") or e) if isinstance(e, dict) else str(e))
            kod = str(x.get("itemCode") or x.get("stockCode") or x.get("merchantSku") or x.get("sku") or "")
            if d and (ms or kod):
                durum[d] += 1
            for m in ms:
                mesaj[m[:220]] += 1
                ornek.setdefault(m[:220], kod)
            _mesaj_anahtar = ("reasons", "reason", "errors", "error", "message", "errorMessage", "failReasons", "failReason", "importMessages", "validationResults", "rejectReasonsMessages")
            for k_, v in x.items():
                if k_ not in _mesaj_anahtar and isinstance(v, (dict, list)):
                    gez(v)
        elif isinstance(x, list):
            for e in x:
                gez(e)

    gez(j)
    return durum, mesaj, ornek


def n11_gorev_ozet_goster(ayar, tid):
    try:
        kod_, j_, ham_ = n11_gorev_sorgula(ayar, tid)
    except Exception as e:
        st.error(f"Görev sorgulanamadı: {e}")
        return
    (st.success if kod_ == 200 else st.error)(f"N11 görev {tid}: HTTP {kod_}")
    if j_ is None:
        st.code(ham_)
        return
    durum, mesaj, ornek = n11_gorev_ozet(j_)
    if durum:
        st.write("Durumlar: " + ", ".join(f"**{k}**: {n}" for k, n in durum.most_common()))
    if mesaj:
        st.error("N11'in ürünleri REDDETME nedenleri (en sık):")
        st.dataframe(pd.DataFrame([{"Neden": m, "Adet": n, "Örnek stok kodu": ornek.get(m, "")} for m, n in mesaj.most_common(15)]), hide_index=True)
    elif durum:
        st.info("Hata mesajı görünmüyor; görev hâlâ işleniyor olabilir. Birkaç dakika sonra tekrar sorgulayın.")
    with st.expander("Ham yanıt"):
        st.json(j_)


def n11_takip_ekle(tid, en_fazla=30):
    liste = [str(x) for x in (kv_oku("takip:n11", []) or []) if str(x) != str(tid)]
    kv_yaz("takip:n11", (liste + [str(tid)])[-en_fazla:])


def n11_gorev_sorgula(ayar, tid):
    """N11 ürün görevi sonucu: POST /ms/product/task-details/page-query. Dönüş: (http_kod, json_ya_da_None, ham_metin)."""
    tid = str(tid or "").strip()
    if not tid.isdigit():
        raise ValueError("Görev no sayı olmalı.")
    h = n11_header(kimlik(ayar, "n11_key"), kimlik(ayar, "n11_secret"))
    r = http("POST", f"{N11_BASE}/ms/product/task-details/page-query", headers=h, timeout=60, tries=1,
             json={"taskId": int(tid), "pageable": {"page": 0, "size": 250}})
    try:
        j = r.json()
    except Exception:
        j = None
    return r.status_code, j, (r.text or "")[:4000]


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
    kayit, atlanan, tukenen_atlanan = [], 0, 0
    son = son_fiyatlar("idefix")
    for r in kayit_listesi(df):
        bk = idefix_barkod(r["barkod"], ayar)
        fiyat = fiyat_belirle(r, son)
        stok = max(_i(r.get("stok")), 0)
        if not bk or fiyat <= 0:
            atlanan += 1
            if bk and stok == 0:
                tukenen_atlanan += 1
            continue
        kayit.append((str(r["barkod"]), {
            "barcode": bk, "price": fiyat, "comparePrice": fiyat,
            "inventoryQuantity": stok,
        }))

    def gonder(grup):
        r = http("POST", f"{ID_BASE}/pim/catalog/{v}/inventory-upload", json={"items": grup}, headers=h, timeout=120)
        return r.status_code in (200, 201, 202), yanit_ozet(r)

    ok_k, hata_k, loglar = paketle(kayit, 500, gonder, ilerleme, "İdefix")
    return _sonuc("idefix", ok_k, hata_k, loglar, atlanan, tukenen_atlanan)


MARKA_ALANLARI = (("hb", "marka", "Hepsiburada marka adı"), ("ptt", "marka", "PTT AVM marka adı"),
                  ("idefix", "brand_id", "İdefix marka ID"), ("trendruum", "brand_id", "Trendruum marka ID"))


def tedarikci_marka(ayar, tedarikci, pid, alan, varsayilan=""):
    """Tedarikçiye özel marka tanımlıysa onu, yoksa pazar yerinin genel markasını döndürür."""
    bilgi = (ayar.get("tedarikciler") or {}).get(str(tedarikci)) or {}
    v = ((bilgi.get("markalar") or {}).get(pid) or {}).get(alan)
    v = str(v).strip() if v is not None else ""
    return v or str(varsayilan or "").strip()


def tedarikci_marka_var_mi(ayar, pid, alan):
    return any(str((((b or {}).get("markalar") or {}).get(pid) or {}).get(alan) or "").strip()
               for b in (ayar.get("tedarikciler") or {}).values())


def idefix_urun_listesi(df, ayar):
    pa = pa_al(ayar, "idefix")
    brand_gen = _i(pa.get("brand_id"))
    if brand_gen <= 0 and not tedarikci_marka_var_mi(ayar, "idefix", "brand_id"):
        raise ValueError("İdefix için 'Marka ID' ayarı boş. Genel Ayarlar'dan ya da tedarikçi ayarından girin.")
    cat_varsayilan = _i(pa.get("category_id"))
    atr = pa.get("attributes") or []
    kdv = _i(pa.get("kdv"), 20)
    sure = _i(pa.get("teslim_suresi"), 3) or 1
    liste, atlanan = [], 0
    for r in kayit_listesi(df):
        gorsel = https_yap(str(r.get("gorsel", "")).strip())
        kod = str(r["barkod"]).strip()
        bk = idefix_barkod(kod, ayar)
        fiyat = round(_f(r.get("satis_fiyati")), 2)
        cat = _i(kat_sec(pa, ayar, r.get("kategori"), "idefix"))
        brand = _i(tedarikci_marka(ayar, r.get("tedarikci"), "idefix", "brand_id", pa.get("brand_id")))
        if not gorsel.startswith("https") or fiyat <= 0 or not bk or cat <= 0 or brand <= 0:
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
                def _d(a, b=b):
                    takip = a.setdefault("idefix_takip", [])
                    takip.append(b)
                    del takip[:-50]
                ayar_kismi_yaz(_d, ayar)
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
    """failureReasons metin, liste ya da {message, description} sozlugu olabilir; hata kodlarini duz listeler."""
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
    """batch-result yanitini okunur satirlara cevirir (alan adlari esnek okunur)."""
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
        satirlar.append({
            "Barkod": str(x.get("barcode") or x.get("vendorStockCode") or ""),
            "Ürün": str(x.get("title") or x.get("name") or "")[:60],
            "Durum": IDEFIX_DURUM.get(anahtar, durum),
            "Hata sebebi": sebep_tr,
            "Eşleşen İdefix ürünü": str(mp.get("name") or ""),
            "_durum": anahtar,
        })
        sayim[IDEFIX_DURUM.get(anahtar, durum) or "Bilinmiyor"] = sayim.get(IDEFIX_DURUM.get(anahtar, durum) or "Bilinmiyor", 0) + 1
    ust = str(j.get("status") or "") if isinstance(j, dict) else ""
    return {"ust": ust, "satirlar": satirlar, "sayim": sayim}


def idefix_onayla(ayar, barkodlar):
    """Katalogda eslesen (waiting_vendor_approve) urunleri onaylar: POST /pim/pool/{vendorId}/approve-item."""
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
            ayar_kismi_yaz(lambda a, i=i: pa_al(a, "hb").__setitem__("kombi", i), ayar)
            return True, "✅ Hepsiburada girişi başarılı."
    return False, "❌ Hepsiburada girişi reddedildi (kullanıcı adı / servis anahtarı / merchant ID kontrol edin)."


HB_YUKLEME_PAKETI = 1000  # tek yuklemedeki SKU sayisi (dokuman: 5 bekleyen islem limiti icin daha buyuk paket onerilir)


def hb_guncelle(ayar, df, ilerleme=None):
    m = kimlik(ayar, "hb_merchant_id")
    onek = str(pa_al(ayar, "hb").get("sku_prefix", "") or "")
    kayit, atlanan = [], 0
    for r in kayit_listesi(df):
        fiyat = round(_f(r.get("satis_fiyati")), 2)  # fiyat 0 ise sadece STOK gider (tukenen urun satista kalmasin)
        sku = onek + str(r["barkod"]).strip()
        f_deg = bool(r.get("_fiyat_degisti", True))
        s_deg = bool(r.get("_stok_degisti", True))
        kayit.append((str(r["barkod"]), (sku, fiyat, max(_i(r.get("stok")), 0), f_deg, s_deg)))

    def gonder(grup):
        h = hb_header(ayar)
        url = f"{HB_BASE}/listings/merchantid/{m}"
        fiyatli = [{"merchantSku": s_, "price": f_} for s_, f_, _, fd, _ in grup if f_ > 0 and fd]
        stoklu = [{"merchantSku": s_, "availableStock": a_} for s_, _, a_, _, sd in grup if sd]
        yanitlar = []

        def istek(adres, liste):
            # Dokuman: ayni anda bekleyen/devam eden listing guncelleme islemi 5'i gecemez. Bekleyenler bitince acilir:
            # 429'da bekleyip yeniden denenir; hala 429 ise tur durdurulur, kalanlar sonraki turda gider.
            r_ = None
            for deneme in range(4):
                r_ = http("POST", adres, json=liste, headers=h, timeout=60, tries=1)
                if r_.status_code != 429:
                    return r_
                if deneme < 3:
                    time.sleep(45)
            return r_

        for ad_, liste in (("fiyat", fiyatli), ("stok", stoklu)):
            if not liste:
                continue
            r_ = istek(f"{url}/{'price' if ad_ == 'fiyat' else 'stock'}-uploads", liste)
            SON_YANIT[f"hb_{ad_}"] = {"istek_ornek": liste[:3], "kod": r_.status_code, "yanit": (r_.text or "")[:3000]}
            if r_.status_code == 429:
                return False, "HIZ_LIMITI " + yanit_ozet(r_)
            yanitlar.append((ad_, r_))
        ok = all(r_.status_code in (200, 201, 202) for _, r_ in yanitlar)
        ozet = " | ".join(f"{ad_}: {yanit_ozet(r_)}" for ad_, r_ in yanitlar) or "değişiklik yok"
        return ok, ozet

    ok_k, hata_k, loglar = paketle(kayit, HB_YUKLEME_PAKETI, gonder, ilerleme, "Hepsiburada", bekle=1.0)
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


HB_YASAKLI_VARSAYILAN = ["fiyat", "fiyatı", "fiyatına", "fiyatlı", "indirim", "indirimli", "kampanya", "kampanyalı", "ücretsiz", "bedava"]


def hb_baslik_temizle(ad, ayar):
    """Hepsiburada ürün adında yasaklı kelimeleri (ör. 'fiyat') çıkarır; 'Ürün adında yasaklı kelime(ler) bulunmaktadır' hatasını önler."""
    ek = [x.strip() for x in str(pa_al(ayar, "hb").get("yasakli_kelimeler", "") or "").replace("\n", ",").split(",") if x.strip()]
    kelimeler = {tr_norm(x) for x in HB_YASAKLI_VARSAYILAN + ek}
    parca = [w for w in str(ad).split() if tr_norm(w.strip(".,;:!?()[]-/\"'")) not in kelimeler]
    return " ".join(parca) or str(ad)


def hb_urun_listesi(df, ayar):
    """Hepsiburada 'Urun Bilgisi Gonderme' (POST /product/api/products/import) bicimi:
    [{categoryId, merchant, attributes:{merchantSku, VaryantGroupID, Barcode, UrunAdi, UrunAciklamasi, Marka,
    GarantiSuresi, kg, tax_vat_rate, price, stock, Image1..}}] -- dosya (integrator.json) olarak yuklenir."""
    hb_urun_adresi(ayar)
    pa = pa_al(ayar, "hb")
    merchant = kimlik(ayar, "hb_merchant_id")
    if not merchant:
        raise ValueError("Hepsiburada Merchant ID kayıtlı değil.")
    marka_gen = str(pa.get("marka", "") or "").strip()
    if not marka_gen and not tedarikci_marka_var_mi(ayar, "hb", "marka"):
        raise ValueError("Hepsiburada için Marka adı gerekli (Genel Ayarlar > Marka adı ya da tedarikçi ayarı).")
    ek = hb_ek_ozellikler(pa)
    onek = str(pa.get("sku_prefix", "") or "")
    kdv = _i(pa.get("kdv"), 20)
    garanti = _i(pa.get("garanti"), 24)
    kg = _f(pa.get("kg"), 1.0) or 1.0
    uret = bool(pa.get("gecici_barkod", True))
    liste, atlanan = [], 0
    for r in kayit_listesi(df):
        gorsel = https_yap(str(r.get("gorsel", "")).strip())
        kod = str(r["barkod"]).strip()
        barkod = sabit_barkod(kod, uret)
        fiyat = round(_f(r.get("satis_fiyati")), 2)
        cat = kat_sec(pa, ayar, r.get("kategori"), "hb")
        marka = tedarikci_marka(ayar, r.get("tedarikci"), "hb", "marka", marka_gen)
        if not gorsel.startswith("https") or fiyat <= 0 or not barkod or not cat or not marka:
            atlanan += 1
            continue
        ad = hb_baslik_temizle(str(r["urun_adi"]).strip(), ayar)
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
        try:
            jj = r.json()
        except Exception:
            jj = None
        if ok and isinstance(jj, dict) and (jj.get("success") is False or jj.get("errors")):
            ok = False  # HTTP 200 olsa bile gövde 'başarısız' diyorsa başarılı sayma
        if ok:
            t = re.search(r'"trackingId"\s*:\s*"([^"]+)"', r.text or "")
            if t:
                log_yaz("Hepsiburada", "OK", f"Ürün yükleme izleme kodu: {t.group(1)}")
                ozet += f" | izleme kodu: {t.group(1)}"
                liste_ = [str(x) for x in (kv_oku("takip:hb", []) or []) if str(x) != t.group(1)]
                kv_yaz("takip:hb", (liste_ + [t.group(1)])[-30:])
            else:
                ok = False
                ozet += " | UYARI: yanıtta izleme kodu (trackingId) yok; Hepsiburada dosyayı işleme almamış olabilir."
        return ok, ozet

    ok_k, hata_k, loglar = paketle(kayit, 100, gonder, ilerleme, "Hepsiburada", durdur=3)
    return len(ok_k), len(hata_k), loglar


def hb_yukleme_durumu(ayar, tur, uid):
    """Hepsiburada fiyat/stok yükleme sonucu: GET /listings/merchantid/{m}/{price|stock}-uploads/id/{id}. Dönüş: (http_kod, ham metin)."""
    m = kimlik(ayar, "hb_merchant_id")
    r = http("GET", f"{HB_BASE}/listings/merchantid/{m}/{'price' if tur == 'fiyat' else 'stock'}-uploads/id/{uid}", headers=hb_header(ayar), timeout=60, tries=1)
    return r.status_code, (r.text or "")[:4000]


def hb_urun_sonuc_sorgula(ayar, tid):
    """Hepsiburada ürün yükleme sonucu: GET <ürün adresi tabanı>/products/status/{trackingId}. Dönüş: (http_kod, json_ya_da_None, ham)."""
    tid = str(tid or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9\-_]{6,80}", tid):
        raise ValueError("Geçersiz izleme kodu.")
    taban = hb_urun_adresi(ayar).rstrip("/")
    taban = taban[: -len("/products/import")]
    r = http("GET", f"{taban}/products/status/{tid}", headers=hb_header(ayar), timeout=60, tries=1)
    try:
        j = r.json()
    except Exception:
        j = None
    return r.status_code, j, (r.text or "")[:4000]


def hb_toplu_ozet(ayar, adet=20, en_fazla_sayfa=12, ilerleme=None):
    """Son 'adet' yüklemenin tüm sayfalarını okuyup importStatus ve neden sayımı çıkarır; hbSku'su olanları (katalogda zaten var) ayırır."""
    kodlar = list(reversed(kv_oku("takip:hb", []) or []))[:adet]
    durum, mesaj, ornek = Counter(), Counter(), {}
    var_olan, okunan, toplam_urun, ham_ornek = {}, 0, 0, {}
    taban = hb_urun_adresi(ayar).rstrip("/")[:-len("/products/import")]
    for i, tid in enumerate(kodlar):
        for sayfa in range(en_fazla_sayfa):
            r = http("GET", f"{taban}/products/status/{tid}", params={"page": sayfa, "size": 100}, headers=hb_header(ayar), timeout=60, tries=1)
            try:
                j = r.json()
            except Exception:
                break
            if r.status_code != 200 or not isinstance(j, dict):
                break
            veri = j.get("data") or []
            okunan += 1
            for u in veri:
                if not isinstance(u, dict):
                    continue
                toplam_urun += 1
                d_, m_, o_ = n11_gorev_ozet(u)
                durum.update(d_)
                for m0, n0 in m_.items():
                    m1 = re.sub(r"\d{4,}", "#", m0)  # barkod/SKU numaraları nedeniyle aynı hata ayrı satırlara bölünmesin
                    mesaj[m1] += n0
                    ornek.setdefault(m1, o_.get(m0, ""))
                    ham_ornek.setdefault(m1, u)
                if u.get("hbSku") and any("matched or in catalog" in x for x in m_):
                    var_olan[str(u.get("merchantSku"))] = str(u.get("hbSku"))
            if j.get("last", True) or not veri:
                break
        if ilerleme:
            ilerleme((i + 1) / max(len(kodlar), 1))
    return {"durum": durum, "mesaj": mesaj, "ornek": ornek, "var_olan": var_olan, "kod": len(kodlar), "sayfa": okunan, "urun": toplam_urun, "ham": ham_ornek}


def hb_sonuc_goster(ayar, tid):
    try:
        kod_, j_, ham_ = hb_urun_sonuc_sorgula(ayar, tid)
    except Exception as e:
        st.error(f"Sorgulanamadı: {e}")
        return
    (st.success if kod_ == 200 else st.error)(f"Hepsiburada yükleme {tid}: HTTP {kod_}")
    if j_ is None:
        st.code(ham_)
        return
    durum, mesaj, ornek = n11_gorev_ozet(j_)
    if durum:
        st.write("Durumlar: " + ", ".join(f"**{k}**: {n}" for k, n in durum.most_common()))
    if mesaj:
        st.error("Hepsiburada'nın ürünleri REDDETME / uyarı nedenleri (en sık):")
        st.dataframe(pd.DataFrame([{"Neden": m, "Adet": n, "Örnek SKU": ornek.get(m, "")} for m, n in mesaj.most_common(15)]), hide_index=True)
    with st.expander("Ham yanıt", expanded=not mesaj):
        st.json(j_)


HB_OMS = "https://oms-external.hepsiburada.com"
SIPARIS_TANI = {}  # son siparis cekme ayrintilari (sorun giderme icin)


def _hb_liste_cek(ayar, yol, params_ek, etiket, sayfa_boyu=50, en_fazla_sayfa=40):
    """HB oms-external liste servisleri (limit/offset zorunlu); ayrintilari SIPARIS_TANI'ya yazar."""
    m = kimlik(ayar, "hb_merchant_id")
    url = f"{HB_OMS}/{yol}/merchantid/{urllib.parse.quote(str(m), safe='')}"
    hepsi, son_kod, ornek = [], None, ""
    for sayfa in range(en_fazla_sayfa):
        prm = dict(params_ek)
        prm.update({"limit": sayfa_boyu, "Offset" if yol == "packages" else "offset": sayfa * sayfa_boyu})
        r = http("GET", url, params=prm, headers=hb_header(ayar), timeout=30, tries=2)
        son_kod = r.status_code
        if sayfa == 0:
            ornek = (getattr(r, "text", "") or "")[:1500]
        r.raise_for_status()
        j = r.json() or []
        if isinstance(j, dict):
            j = j.get("items") or j.get("data") or j.get("packages") or j.get("content") or []
        hepsi += j
        if len(j) < sayfa_boyu:
            break
    SIPARIS_TANI[etiket] = {"http": son_kod, "adet": len(hepsi), "adres": url, "ornek_yanit": ornek}
    return hepsi


def hb_siparisler(ayar, saat=96, sayfa_boyu=50, en_fazla_sayfa=40):
    """GET /packages/merchantid/{id}: paketlenmis siparisler (limit/offset zorunlu)."""
    m = kimlik(ayar, "hb_merchant_id")
    if not m:
        return []
    return _hb_liste_cek(ayar, "packages", {"timespan": saat}, "paketler", sayfa_boyu, en_fazla_sayfa)


def hb_paketleri_topla(ayar, saat=96):
    """Paketlenmiş (Gönderime Hazır) siparişleri farklı parametre biçimleriyle dener ve birleştirir.
    HB bazı hesaplarda 'timespan' ile boş döner; tarih penceresi (begindate/enddate, 'yyyy-MM-dd HH:mm') ya da
    parametresiz çağrı sonuç verebilir. Her denemenin sonucu SIPARIS_TANI'ya yazılır."""
    if not kimlik(ayar, "hb_merchant_id"):
        return []
    bulunan = {}

    def dene(ad, prm):
        try:
            liste = _hb_liste_cek(ayar, "packages", prm, f"paketler:{ad}")
        except Exception as e:
            SIPARIS_TANI[f"paketler:{ad}"] = {"hata": str(e)[:300]}
            return
        for p in liste:
            if isinstance(p, dict):
                anahtar = str(p.get("packageNumber") or p.get("packageId") or p.get("id") or id(p))
                bulunan.setdefault(anahtar, p)

    dene("timespan", {"timespan": min(max(int(saat), 1), 96)})
    dene("parametresiz", {})
    simdi = simdi_tr()
    for g in range(min(max(int(saat) // 24 + 1, 3), 8)):  # 24 saatlik pencereler, bugünden geriye
        bit = simdi - timedelta(days=g)
        bas = bit - timedelta(days=1)
        dene(f"pencere{g}", {"begindate": bas.strftime("%Y-%m-%d %H:%M"), "enddate": bit.strftime("%Y-%m-%d %H:%M")})
    SIPARIS_TANI["paketler"] = {"toplam_benzersiz_paket": len(bulunan)}
    return list(bulunan.values())


def hb_yeni_siparis_kalemleri(ayar, sayfa_boyu=100, en_fazla_sayfa=40):
    """GET /orders/merchantid/{id}: henuz paketlenmemis YENI siparis kalemleri."""
    if not kimlik(ayar, "hb_merchant_id"):
        return []
    return _hb_liste_cek(ayar, "orders", {}, "yeni_siparisler", sayfa_boyu, en_fazla_sayfa)


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
    tekil, atlanan, tukenen_atlanan = {}, 0, 0
    son = son_fiyatlar("ptt")
    for r in kayit_listesi(df):
        fiyat = fiyat_belirle(r, son)  # fiyatı yoksa son gönderilen fiyatla STOK yine de gider
        if fiyat <= 1:  # PTT KDV dahil fiyatın 1'den büyük olmasını ister
            atlanan += 1
            if _i(r.get("stok")) <= 0:
                tukenen_atlanan += 1
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
    marka_gen = str(pa.get("marka", "") or "").strip()
    desi = _f(pa.get("desi"), 1.0) or 1.0
    desi = int(desi) if float(desi).is_integer() else desi
    kargo = str(pa.get("kargo_profil", "") or "").strip()
    aktif = bool(pa.get("aktif_gonder", False))
    liste, atlanan = [], 0
    for r in kayit_listesi(df):
        gorsel = https_yap(str(r.get("gorsel", "")).strip())
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
        marka = tedarikci_marka(ayar, r.get("tedarikci"), "ptt", "marka", marka_gen)
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
    def _d(a):
        onceki = [i for i in (a.get("ptt_takip") or []) if i not in liste]
        a["ptt_takip"] = (liste + onceki)[:20]
    ayar_kismi_yaz(_d, ayar)


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


def ptt_kategori_gez():
    """Ağaç çalışmazsa: ana kategorilerden başlayıp ID ile alt kategorilere inerek gezme."""
    st.markdown("**Ana kategorilerden gezerek bul**")
    c1, c2 = st.columns(2)
    istek = None
    if gen(c1.button, "📂 Ana kategorileri getir", key="ptt_kat_main"):
        istek = "main"
    hedef = c2.text_input("Kategori ID (içindekileri görmek için)", key="ptt_kat_gez_id")
    if gen(c2.button, "➡️ Bu kategoriyi aç", key="ptt_kat_ac"):
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
    (st.success if g["kod"] == 200 else st.error)(f"'{g['yol']}' için PTT yanıtı: HTTP {g['kod']}")
    if g["liste"]:
        d = pd.DataFrame(g["liste"]).head(300)
        st.dataframe(d[["ID", "Kategori"]], hide_index=True)
        secenek = [f"{r.ID} — {r.Kategori}" for r in d.itertuples()]
        sec = st.selectbox("Bu listeden seç", secenek, key="ptt_kat_gez_sec")
        k1, k2 = st.columns(2)
        if gen(k1.button, "📂 Seçileni aç (alt kategorileri)", key="ptt_kat_gez_ac"):
            st.session_state["ptt_kat_gez_id"] = sec.split(" — ")[0].strip()
            st.rerun()
        if gen(k2.button, "✅ Seçileni varsayılan yap", key="ptt_kat_gez_varsayilan"):
            secilen = sec.split(" — ")[0].strip()
            varsayilan_kategori_yaz("ptt", secilen)
    else:
        st.warning("Listede kategori okunamadı; ham yanıtı aşağıdan inceleyebilirsiniz.")
    with st.expander("Ham yanıt"):
        if g.get("json") is not None:
            st.json(g["json"])
        else:
            st.text(g["ham"])


def ptt_oto_dugumler(ayar):
    """PTT uç kategorileri (otomatik öneri için). Ağaç ucu 400 verirse ana kategorilerden paralel inerek gezer.
    Sonuç diske de kaydedilir (yeniden başlatmada tekrar taranmaz)."""
    import concurrent.futures as cf
    import time as _t
    onbellek = st.session_state.get("ptt_oto_agac")
    if onbellek:
        return onbellek
    dosya = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ptt_kategori_onbellek.json")
    liste = []
    try:
        with open(dosya, encoding="utf-8") as f:
            liste = json.load(f)
    except Exception:
        liste = []
    if not liste:
        try:
            liste = ptt_kategori_duzlestir(ptt_kategori_agaci(ayar))
        except Exception:
            liste = []
    if not liste:
        kod, j, _ham = ptt_kategori_getir(ayar, "main")
        if kod != 200 or j is None:
            raise RuntimeError(f"PTT ana kategori listesi alınamadı (HTTP {kod}). API bilgilerini kontrol edin.")
        seviye = [(x["ID"], x["Kategori"]) for x in ptt_kategori_duzlestir(j) if str(x["ID"]).isdigit()]
        gorulen = set()
        bitis = _t.time() + 150  # en çok 2,5 dk

        def ac(oge):
            cid, yol = oge
            try:
                kod_, j_, _h = ptt_kategori_getir(ayar, cid)
            except Exception:
                return oge, None
            if kod_ != 200 or j_ is None:
                return oge, None
            return oge, [x for x in ptt_kategori_duzlestir(j_) if x["ID"] != str(cid)]

        while seviye and _t.time() < bitis:
            seviye = [o for o in seviye if o[0] not in gorulen]
            gorulen.update(o[0] for o in seviye)
            sonraki = []
            with cf.ThreadPoolExecutor(max_workers=8) as ex:
                for oge, alt in ex.map(ac, seviye):
                    if alt is None:
                        continue  # alınamadı: ne uç ne ara düğüm say
                    if not alt:
                        liste.append({"ID": str(oge[0]), "Kategori": oge[1], "Alt kategorisi var": False})
                        continue
                    for x in alt:
                        if str(x["ID"]).isdigit():
                            sonraki.append((x["ID"], oge[1] + " > " + x["Kategori"].split(" > ")[-1]))
            seviye = sonraki
        if liste:
            try:
                with open(dosya, "w", encoding="utf-8") as f:
                    json.dump(liste, f, ensure_ascii=False)
            except Exception:
                pass
    out = []
    for k in liste:
        if k.get("Alt kategorisi var"):
            continue
        out.append({"ID": k["ID"], "yol": k["Kategori"], "son": kat_belirtec(k["Kategori"].split(">")[-1]), "tum": kat_belirtec(k["Kategori"])})
    if not out:
        raise RuntimeError("PTT kategori listesi okunamadı (ana kategoriler alındı ama alt kategoriler gelmedi). "
                           "'Ana kategorileri getir' ile bir kategori açıp ekran görüntüsünü gönderin.")
    st.session_state["ptt_oto_agac"] = out
    return out


def ptt_kategori_bulucu():
    if not pazar_bagli(ayarlar, "ptt"):
        st.caption("Kategori aramak için önce PTT API bilgilerini kaydedin.")
        return
    ptt_kategori_gez()
    st.divider()
    st.markdown("**Tüm kategori ağacı (PTT bu hesapta hata verebilir)**")
    if gen(st.button, "📥 Kategorileri PTT'den yükle", key="ptt_kat_yukle"):
        try:
            with st.spinner("PTT kategori ağacı alınıyor..."):
                veri = ptt_kategori_agaci(ayarlar)
            st.session_state["ptt_kat_ham"] = json.dumps(veri, ensure_ascii=False)[:60000]
            st.session_state["ptt_kat"] = ptt_kategori_duzlestir(veri)
        except Exception as e:
            st.error(f"Hata: {e}")
    kat = st.session_state.get("ptt_kat")
    if kat is None:
        return
    if not kat:
        st.warning("Kategori listesi okunamadı. Aşağıdaki ham yanıtın ilk kısmını bana gönderin, okuyucuyu ona göre düzelteyim.")
        ham = str(st.session_state.get("ptt_kat_ham", ""))[:3000]
        try:
            st.json(json.loads(ham))
        except Exception:
            st.text(ham)
        return
    ara = st.text_input("Kategori ara (örn. elbise)", key="ptt_kat_ara")
    yaprak = st.checkbox("Sadece en alt (yaprak) kategoriler", value=True, key="ptt_kat_yaprak")
    d = pd.DataFrame(kat)
    if yaprak:
        d = d[~d["Alt kategorisi var"]]
    if ara.strip():
        d = d[d["Kategori"].map(tr_norm).str.contains(tr_norm(ara.strip()), regex=False)]
    st.caption(f"{len(d):,} sonuç" + (" (ilk 300 gösteriliyor)" if len(d) > 300 else ""))
    d = d.head(300)
    st.dataframe(d[["ID", "Kategori"]], hide_index=True)
    secenek = [f"{r.ID} — {r.Kategori}" for r in d.itertuples()]
    if secenek:
        sec = st.selectbox("Varsayılan yapmak istediğiniz kategori", secenek, key="ptt_kat_sec")
        if gen(st.button, "✅ Bunu varsayılan kategori yap", key="ptt_kat_varsayilan"):
            secilen_id = sec.split(" — ")[0].strip()
            pa_al(ayarlar, "ptt")["category_id"] = secilen_id
            ayar_yaz(ayarlar)
            st.success(f"Varsayılan kategori ID: {secilen_id}")


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
    """PTT 'Ürün Güncelleme Kontrol': POST /products/tracking-result/{trackingId}. Dönüş: (http_durum, metin)."""
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
        raise RuntimeError(f"Trendruum girişi başarısız (HTTP {r.status_code})")
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


def _tr_aciklama(r):
    """Trendruum 'açıklama' alanını zorunlu tutar: tedarikçi açıklaması varsa onu (HTML temizlenmiş), yoksa ürün adını kullanır."""
    ad = str(r.get("urun_adi") or "").strip()
    for alan in ("aciklama", "description", "detay"):
        ham = str(r.get(alan) or "").strip()
        if ham and ham.lower() != "nan":
            temiz = re.sub(r"<[^>]+>", " ", ham)
            temiz = re.sub(r"\s+", " ", html.unescape(temiz)).strip()
            if len(temiz) >= 10:
                return temiz[:4000]
    return ad if len(ad) >= 10 else (ad + " - ürün açıklaması")


def trendruum_urun_listesi(df, ayar):
    pa = pa_al(ayar, "trendruum")
    brand_gen, cat_varsayilan, uret, kdv = trendruum_ayar(ayar)
    if not objectid_mi(brand_gen) and not tedarikci_marka_var_mi(ayar, "trendruum", "brand_id"):
        raise ValueError("Trendruum 'Marka ID' geçersiz/boş (24 karakterlik ID olmalı). Genel Ayarlar'dan ya da tedarikçi ayarından girin.")
    liste, atlanan = [], 0
    for r in kayit_listesi(df):
        gorsel = https_yap(str(r.get("gorsel", "")).strip())
        kod = str(r["barkod"]).strip()
        barkod = sabit_barkod(kod, uret)
        fiyat = _f(r.get("satis_fiyati"))
        cat = kat_sec(pa, ayar, r.get("kategori"), "trendruum")
        brand = tedarikci_marka(ayar, r.get("tedarikci"), "trendruum", "brand_id", brand_gen)
        if not objectid_mi(brand):
            brand = brand_gen  # tedarikçiye özel marka geçersizse genel marka ID'sine dön
        if not gorsel or fiyat <= 0 or not barkod or not objectid_mi(cat) or not objectid_mi(brand):
            atlanan += 1
            continue
        liste.append({
            "name": str(r["urun_adi"]), "description": _tr_aciklama(r), "model_code": kod, "category_id": cat, "brand_id": brand,
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
    m = tr_norm(t).translate(str.maketrans("çğöşü", "cgosu"))
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
    isaret = " ✓"
    etiket = {}
    for k in adet.index:
        etiket[f"{k} ({int(adet[k])} ürün){isaret if mevcut.get(k) else ''}"] = k
    sec = st.selectbox("Bu kategoriyi şu tedarikçi kategorisine ata", list(etiket), key=f"ata_sec_{pid}")
    if gen(st.button, "Seçili kategoriyi bu tedarikçi kategorisine ata", key=f"ata_btn_{pid}"):
        k = etiket[sec]
        yeni = dict(mevcut)
        yeni[k] = str(secilen)
        pa_al(ayarlar, pid)["kategori_eslesme"] = yeni
        ayar_yaz(ayarlar)
        st.session_state[f"ata_bilgi_{pid}"] = f"'{k}' kategorisi artık {secilen} ID'sine eşleşti. Önceki gönderilmiş ürünler değişmez; gerekirse silip yeniden gönderin."
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
    st.caption(f"{len(g['liste'])} sonuç; aranan ada en yakın olanlar üstte.")
    st.dataframe(d, hide_index=True)
    secenek = [f"{r.ID} — {r.Kategori}" for r in d.itertuples()]
    sec = st.selectbox("Listeden sec", secenek, key="trk_sec")
    secilen = sec.split(" — ")[0].strip()
    mevcut_vk = pa_al(ayarlar, "trendruum").get("category_id") or "(boş)"
    st.caption(f"Şu an kayıtlı varsayılan kategori ID: {mevcut_vk}")
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


SON_YANIT = {}  # pazar -> son güncelleme isteğinin ham yanıtı (teşhis için)


def trendruum_guncelle(ayar, df, ilerleme=None):
    token = trendruum_token(kimlik(ayar, "trendruum_key"), kimlik(ayar, "trendruum_secret"))
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
        if fiyat > 0:  # fiyati olmayan urunde sadece STOK gider (tukenen urun satista kalmasin)
            govde["price"] = fiyat
        kayit.append((str(r["barkod"]), govde))

    def gonder(grup):
        parcalar = [[p for p in grup if "price" in p], [p for p in grup if "price" not in p]]
        toplam, guncel_top, mesajlar = 0, 0, []
        for parca in parcalar:
            if not parca:
                continue
            r = http("POST", f"{TR_BASE}/products/bulk-update", json={"products": parca}, headers=h, timeout=120)
            SON_YANIT["trendruum"] = {"istek_ornek": parca[:3], "kod": r.status_code, "yanit": (r.text or "")[:3000]}
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
    """Eslesmis kategori ID'si; yoksa varsayilan SADECE 'varsayilan kategoriyi kullan' acikken."""
    v = kategori_id(pa, ayar, kategori, pid)
    if v and (pid != "trendruum" or objectid_mi(v)):  # geçersiz (24 karakterlik ID olmayan) eşleştirme yok sayılır, varsayılana düşer
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
# Gönderim orkestrasyonu
# --------------------------------------------------------------------------
GUNCELLEYICI = {
    "trendruum": trendruum_guncelle, "trendyol": trendyol_guncelle, "hb": hb_guncelle,
    "n11": n11_guncelle, "idefix": idefix_guncelle, "ptt": ptt_guncelle,
}


def pazar_yetim_barkodlar(ayar, pid):
    """Pazar yerine gonderilmis ama artik hicbir tedarikcide olmayan (silinmis) urunlerin barkodlari."""
    with closing(baglan()) as c:
        anahtarlar = [str(r[0]) for r in c.execute("SELECT DISTINCT barkod FROM pazar_durum WHERE pazar = ? AND durum = 'ok'", (pid,))]
        mevcut = {str(r[0]) for r in c.execute("SELECT DISTINCT barkod FROM urunler")}
    if len(mevcut) < 100:  # veritabani bos/yeni ise (ornegin uygulama yeniden kurulduysa) hicbir urun yetim sayilmaz
        return []
    onek = str(pa_al(ayar, "hb").get("sku_prefix", "") or "") if pid == "hb" else ""
    yetim = set()
    for k in anahtarlar:
        ham = k[len(onek):] if (onek and k.startswith(onek)) else k
        if ham and ham not in mevcut:
            yetim.add(ham)
    return sorted(yetim)


def pazar_yetim_sifirla(ayar, pid, ilerleme=None):
    """Tedarikcide kalmayan urunlerin stogunu pazar yerinde 0'lar. Donus: (ok, hata, yetim_sayisi)."""
    if pid not in GUNCELLEYICI or not pazar_bagli(ayar, pid):
        return 0, 0, 0
    yetim = pazar_yetim_barkodlar(ayar, pid)
    if not yetim:
        return 0, 0, 0
    df = pd.DataFrame({"barkod": yetim, "stok": 0, "satis_fiyati": 0.0})
    ok, hata, loglar = GUNCELLEYICI[pid](ayar, df, ilerleme)
    log_yaz(PAZAR_AD.get(pid, pid), "OK" if hata == 0 else "KISMİ", f"Tedarikçide kalmayan {len(yetim)} ürünün stoğu 0'landı: {ok} gönderildi, {hata} hata.")
    if ok > 0 and hata == 0:
        onek = str(pa_al(ayar, "hb").get("sku_prefix", "") or "") if pid == "hb" else ""
        anahtarlar = list(yetim) + ([onek + b for b in yetim] if onek else [])
        with closing(baglan()) as c:
            for i in range(0, len(anahtarlar), 500):
                parca = anahtarlar[i:i + 500]
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


def oncelik_sirala(d):
    """Once stoku 0 olanlar (stoksuz satis riski en yuksek), sonra kritik (<=5), sonra digerleri."""
    if d is None or d.empty or "stok" not in d.columns:
        return d
    sk = d["stok"].map(_i)
    o = sk.map(lambda x: 0 if x <= 0 else (1 if x <= 5 else 2))
    return d.assign(_o=o).sort_values("_o", kind="stable").drop(columns=["_o"])


def degisenleri_sec(ayar, pid, df, simdi=None):
    """Otomatik turda yalnizca son basarili gonderimden BERI DEGISEN urunleri secer (pazar yeri hiz limitine takilmamak icin).
    Donus: (df, tam_tur_mu, frenlenen_sayi). Ilk tur ve her 6 saatte bir TAM gonderim yapilir."""
    simdi = simdi or simdi_tr()
    snap = snapshot_oku(pid)
    tam_z = son_tam_zamani(pid)
    if not snap or (tam_z is not None and (simdi - tam_z) > timedelta(hours=6)):
        return oncelik_sirala(df), True, 0
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
    esik = max(300, int(0.30 * len(snap)))
    fren = 0
    if int(sifirlanan.sum()) > esik:
        fren = 0  # ENGELLEME YOK: tedarikçi stoğu biten ürün pazarda satışta kalırsa stoksuz sipariş gelir.
        # Bozuk XML koruması senkron aşamasındadır (senkron_supheli_mi + sifir_teyit); buraya gelen sıfırlamalar onaylıdır.
        mesaj_ = (f"{PAZAR_AD.get(pid, pid)}: {int(sifirlanan.sum())} ürünün stoğu aynı anda 0'a düşüyor ve pazara bildiriliyor. "
                  "Beklenmedik bir düşüşse tedarikçi XML'ini kontrol edin.")
        log_yaz(PAZAR_AD.get(pid, pid), "BILGI", mesaj_)
        bildir(mesaj_, tekil=f"toplu_sifir:{pid}", bekleme_dk=120)
    d["_stok_degisti"] = s_deg
    d["_fiyat_degisti"] = f_deg
    d = d[secil]
    # ilk yukleme tamamlanmadiysa (tam zamani yok) kaldigi yerden devam eder; bitince tam isaretlenir
    return oncelik_sirala(d), tam_z is None, fren


def snapshot_guncelle(pid, df_gonder, baslangic, tam_tur, hata):
    """Basarili gonderilen urunlerin son gonderilen stok/fiyatini kaydeder."""
    if df_gonder is None or df_gonder.empty:
        return 0
    with closing(baglan()) as c:
        okset = {str(r[0]) for r in c.execute("SELECT barkod FROM pazar_durum WHERE pazar = ? AND durum = 'ok' AND zaman >= ?", (pid, baslangic))}
        z = simdi_tr().strftime("%Y-%m-%d %H:%M:%S")
        eski_fiyat = {str(r[0]): float(r[1]) for r in c.execute("SELECT barkod, fiyat FROM pazar_son WHERE pazar = ?", (pid,))}
        satirlar = [(pid, str(b), _i(sk), (round(_f(fy), 2) if _f(fy) > 0 else eski_fiyat.get(str(b), 0.0)), z)
                    for b, sk, fy in zip(df_gonder["barkod"], df_gonder["stok"], df_gonder["satis_fiyati"]) if str(b) in okset]
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
        try:
            taze = ayar_oku()
            for _k in ("fiyat_sistemi", "fiyat_sabit", "acil_durdur", "zarar_korumasi", "stok_sifir", "kara_liste"):
                if _k in taze:
                    ayar[_k] = taze[_k]
        except Exception:
            pass
        if pid not in GUNCELLEYICI:
            raise RuntimeError(f"{ad} için entegrasyon yok.")
        if not pazar_bagli(ayar, pid):
            raise RuntimeError(f"{ad} API bilgileri eksik.")
        if not df.empty and "barkod" in df.columns and df["barkod"].duplicated().any():  # aynı barkod iki tedarikçide: stoğu yüksek olan tek kayıt gitsin
            _sk = pd.to_numeric(df.get("stok"), errors="coerce").fillna(0) if "stok" in df.columns else 0
            df = df.assign(_sk=_sk).sort_values("_sk", ascending=False, kind="stable").drop_duplicates("barkod", keep="first").drop(columns="_sk").reset_index(drop=True)
        df = fiyat_artis_uygula(ayar, pid, df)
        kara = kara_liste_maskesi(ayar, df) | stok_sifir_maskesi(ayar, df)
        if kara.any():  # kara listedeki ürünler pazarda satıştan kalksın (stok 0)
            df = df.copy()
            df.loc[kara, "stok"] = 0
        if ayar.get("zarar_korumasi", True) and "alis_fiyati" in df.columns and "stok" in df.columns and not df.empty:
            zarar = (df["alis_fiyati"].map(_f) > 0) & (df["satis_fiyati"].map(_f) <= df["alis_fiyati"].map(_f) * 1.03) & (df["stok"].map(_i) > 0)
            if zarar.any():  # satış fiyatı alış fiyatına (bayi fiyatına) eşit/altında: kargo+komisyon yüzünden zarar. Satıştan kaldır.
                df = df.copy()
                df.loc[zarar, "stok"] = 0
                log_yaz(ad, "UYARI", f"ZARAR KORUMASI: {int(zarar.sum())} ürünün satış fiyatı alış fiyatına yakın/altında olduğu için stoğu 0 gönderildi. "
                                     "Genel & Yedek > Fiyatlandırma'yı açıp kaydedin ve yeniden gönderin.")
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
        baslangic = simdi_tr().strftime("%Y-%m-%d %H:%M:%S")
        tam_tur, df_gonder = True, df
        if tam is None:  # otomatik tur: yalnizca degisenler
            df_gonder, tam_tur, _fren = degisenleri_sec(ayar, pid, df)
            if df_gonder.empty:
                return 0, 0, "Değişen ürün yok; gönderim gerekmedi."
        df_gonder = oncelik_sirala(df_gonder)
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
    return ok, hata, "\n".join(loglar[-8:])


def son_senkron_zamani():
    """Son basarili tedarikci senkronunun zamani (senkron_log'dan)."""
    with closing(baglan()) as c:
        r = c.execute("SELECT MAX(zaman) FROM senkron_log WHERE durum = 'OK' AND mesaj LIKE '% ürün güncellendi'").fetchone()
    try:
        return datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S") if r and r[0] else None
    except (TypeError, ValueError):
        return None


def senkron_gecikme_dk(ayar, simdi=None):
    """(dakika, bayat_mi). Hic senkron yoksa (None, True)."""
    z = son_senkron_zamani()
    if z is None:
        return None, True
    dk = ((simdi or simdi_tr()) - z).total_seconds() / 60
    return dk, dk > max(2 * senkron_dk_degeri(ayar), 30.0)


def acil_durdur_uygula(ayar, aktif):
    """Acil durdur: tum bagli pazar yerlerine stok 0 gonderir. Kapatinca gercek stoklar yeniden gider."""
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
    log_yaz("Sistem", "UYARI" if aktif else "OK", "ACİL DURDURMA açıldı: tüm pazar yerlerinde stok 0." if aktif else "Acil durdurma kapatıldı: gerçek stoklar yeniden gönderildi.")
    return sonuc


def son_fren_uyarisi():
    with closing(baglan()) as c:
        r = c.execute("SELECT zaman, mesaj FROM senkron_log WHERE durum = 'UYARI' AND mesaj LIKE 'Toplu stok%' ORDER BY id DESC LIMIT 1").fetchone()
    try:
        if r and (simdi_tr() - datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S")).total_seconds() < 86400:
            return r[1]
    except (TypeError, ValueError):
        pass
    return None


def guvenlik_paneli():
    """Her sayfanin ustunde: acil durdurma ve bayat stok uyarilari."""
    try:
        t_, s_, y_ = stok_saglik()
    except Exception:
        t_, s_, y_ = 0, 0, 0
    if stok_sorunlu_mu(t_, s_, y_):
        st.error(f"🚨 Ürünlerin %{100 - int(100 * s_ / max(t_, 1))}'inin stoğu 0 görünüyor ({s_:,}/{t_:,} stoklu), ama son sağlıklı kayıtta {y_:,} ürün stoklu idi. Pazar yerlerinde satıştan kalkmış olabilirler.")
        if gen(st.button, "↩️ Son sağlıklı stokları geri yükle ve pazar yerlerine gönder", key="stok_geri_yukle", type="primary"):
            with st.spinner("Stoklar geri yükleniyor ve pazar yerlerine gönderiliyor..."):
                n_g, sonuc_g = stok_yedekten_geri_yukle(ayarlar)
            st.session_state["acil_sonuc"] = [f"{n_g:,} ürünün stoğu son sağlıklı kayıttan geri yüklendi."] + [
                f"{ad}: {ok} gönderildi" + (f", hata: {h}" if h else "") for ad, ok, h in sonuc_g]
            st.rerun()
    fren = son_fren_uyarisi()
    if fren:
        st.warning("🛑 " + fren)
    sip_u = son_log_uyari("siparişte stok sorunu")
    if sip_u:
        st.error(f"📦 SİPARİŞTE STOK SORUNU ({sip_u[0]}): {sip_u[2]}")
    tuk_u = son_log_uyari("TÜKENEN ürünün stoğu")
    if tuk_u:
        st.warning(f"⚠️ {tuk_u[1]}: {tuk_u[2]}")
    for m in st.session_state.pop("acil_sonuc", []) or []:
        st.info(m)
    if ayarlar.get("acil_durdur"):
        st.error("🚨 ACİL DURDURMA AÇIK: pazar yerlerine tüm ürünlerde stok 0 gönderiliyor, satış alınmaz. Kapatmak için kenar çubuğundaki düğmeyi kullanın.")
    if ayarlar.get("tedarikciler"):
        dk, bayat = senkron_gecikme_dk(ayarlar)
        if not ayarlar.get("oto_senkron", True):
            st.warning("⚠️ Otomatik stok senkronu KAPALI. Stoklar tedarikçiden otomatik gelmiyor, stoksuz satış riski var. Ayarlar > Tedarikçiler'den açın.")
        elif bayat:
            gecen = "hiç yapılmamış" if dk is None else (f"{int(dk)} dakika önce" if dk < 120 else f"{dk / 60:.1f} saat önce")
            st.warning(f"⚠️ Son başarılı stok senkronu {gecen}. Stoklar eski olabilir. Ayarlar > Tedarikçiler'den 'Tümünü Şimdi Senkronla'ya basın.")


def acil_kontrol_kenar():
    st.sidebar.markdown("---")
    with st.sidebar.expander("📜 Senkron geçmişi (kanıt)"):
        st.caption("Her tedarikçi senkronunun özeti: kaç ürün, kaçı stoklu, XML'deki ham stok örnekleri ve sonuç. Stoklar sıfırlanırsa nedenini bu kayıt gösterir.")
        try:
            with closing(baglan()) as c:
                gecmis = pd.read_sql("SELECT zaman AS Zaman, tedarikci AS Tedarikçi, urun AS Ürün, stoklu AS Stoklu, toplam_stok AS 'Toplam stok', ornek AS 'XML stok örnekleri', sonuc AS Sonuç FROM senkron_ozet ORDER BY id DESC LIMIT 40", c)
            st.dataframe(gecmis, hide_index=True)
        except Exception as e:
            st.caption(f"Kayıt okunamadı: {e}")
    if ayarlar.get("acil_durdur"):
        st.sidebar.error("🚨 ACİL DURDURMA AÇIK")
        if gen(st.sidebar.button, "✅ Satışa geri aç", key="acil_kapat"):
            with st.spinner("Gerçek stoklar pazar yerlerine gönderiliyor..."):
                sonuc = acil_durdur_uygula(ayarlar, False)
            st.session_state["acil_sonuc"] = ["Acil durdurma kapatıldı."] + [f"{ad}: {ok} gönderildi" + (f", hata: {h}" if h else "") for ad, ok, h in sonuc]
            st.rerun()
    else:
        with st.sidebar.expander("🚨 Acil durdur"):
            st.caption("Tüm pazar yerlerinde tüm ürünlerin stoğunu 0 yapar (satış alınmaz). Stok güvenilmezken kullanın.")
            onay = st.checkbox("Onaylıyorum", key="acil_onay")
            if gen(st.button, "Tüm pazarlarda stoğu 0'la", key="acil_ac", disabled=not onay):
                with st.spinner("Stoklar sıfırlanıyor..."):
                    sonuc = acil_durdur_uygula(ayarlar, True)
                st.session_state["acil_sonuc"] = ["Acil durdurma AÇILDI."] + [f"{ad}: {ok} gönderildi" + (f", hata: {h}" if h else "") for ad, ok, h in sonuc]
                st.rerun()


def tumunu_senkronla(oto=True, zorla=False):
    if not SENKRON_KILIDI.acquire(blocking=False):
        return [("Sistem", False, "Başka bir senkronizasyon zaten çalışıyor.")]
    try:
        ayar = ayar_oku()
        sonuclar = []
        for ad, bilgi in ayar["tedarikciler"].items():
            try:
                n = tedarikci_senkron(ad, bilgi, _i(ayar.get("kritik_esik")), stok_ust_degeri(ayar), zorla=zorla)
                log_yaz(ad, "OK", f"{n} ürün güncellendi")
                sonuclar.append((ad, True, f"{n} ürün"))
            except Exception as e:
                log_yaz(ad, "HATA", e)
                sonuclar.append((ad, False, str(e)))
        kurtarildi = False
        if oto and not ayar.get("oto_stok_kurtarma", False):  # varsayılan KAPALI: tedarikçide gerçekten biten stoklar eski haline döndürülmesin
            try:
                toplam_, stoklu_, yedek_ = stok_saglik()
                if stok_sorunlu_mu(toplam_, stoklu_, yedek_):
                    log_yaz("Sistem", "UYARI", "Ürünlerin çoğu 0 stoklu görünüyor ama son sağlıklı kayıtta çok ürün stoklu idi. Otomatik geri yükleme KAPALI; doğruysa Ana Sayfa'daki 'Son sağlıklı stokları geri yükle' düğmesini kullanın.")
                    bildir("Ürünlerin çoğu 0 stoklu görünüyor. Otomatik geri yükleme kapalı; panelden kontrol edin.", tekil="stok_sifir_uyari", bekleme_dk=180)
            except Exception:
                pass
        if oto and ayar.get("oto_stok_kurtarma", False):
            try:
                toplam_, stoklu_, yedek_ = stok_saglik()
                if stok_sorunlu_mu(toplam_, stoklu_, yedek_):
                    n_k, _ = stok_yedekten_geri_yukle(ayar, pazarlara_gonder=False)
                    kurtarildi = n_k > 0
                    log_yaz("Sistem", "UYARI", f"Toplu stok değişimi: ürünlerin %{100 - int(100 * stoklu_ / max(toplam_, 1))}'i 0 görünüyordu; son sağlıklı yedekten {n_k} ürünün stoğu OTOMATİK geri yüklendi.")
            except Exception as e:
                log_yaz("Sistem", "HATA", f"Otomatik stok kurtarma başarısız: {e}")
        if oto and (any(x[1] for x in sonuclar) or kurtarildi):
            for _, anahtar_, pid_ in OTO_ANAHTAR:
                ayar = ayar_oku()  # senkron dakikalar sürer: kullanıcının bu arada kaydettiği fiyat sistemi/ayarlar ezilmesin
                if ayar.get(anahtar_) and pazar_bagli(ayar, pid_):
                    try:
                        pazara_gonder(ayar, pid_, urunleri_oku(), tam=None)
                    except Exception:
                        pass  # pazara_gonder zaten günlüğe yazdı
        return sonuclar
    finally:
        SENKRON_KILIDI.release()


def senkron_dk_degeri(ayar):
    return max(5.0, _f(ayar.get("senkron_dk"), 10.0) or 10.0)


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
                siparis_stok_kontrol(ayar_oku())
            except Exception as e:
                log_yaz("Sistem", "HATA", f"Sipariş stok kontrolü: {e}")
        except Exception:
            pass
        time.sleep(dk * 60)


@st.cache_resource
def arka_plan_baslat():
    t = threading.Thread(target=arka_plan_dongusu, daemon=True)
    t.start()
    return t


def baglanti_testi(ayar, pid):
    try:
        if not pazar_bagli(ayar, pid):
            return False, "Eksik bilgi: tüm kimlik alanlarını doldurup kaydedin."
        if pid == "trendruum":
            trendruum_token(kimlik(ayar, "trendruum_key"), kimlik(ayar, "trendruum_secret"))
            return True, "✅ Trendruum girişi başarılı."
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
            return True, "✅ Bağlantı başarılı (HTTP 200)"
        return False, f"❌ Bağlantı başarısız ({yanit_ozet(r)})"
    except Exception as e:
        return False, f"Bağlantı kurulamadı: {e}"


# --------------------------------------------------------------------------
# Sipariş normalleştirme
# --------------------------------------------------------------------------
TR_TZ = timezone(timedelta(hours=3))  # Turkiye: UTC+3, yaz/kis saati yok


def simdi_tr():
    """Turkiye saati (sunucu UTC olsa da)."""
    return datetime.now(TR_TZ).replace(tzinfo=None)


def tr_tarih(v):
    try:
        if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
            n = float(v)
            n = n / 1000 if n > 1e11 else n
            return datetime.fromtimestamp(n, TR_TZ).strftime("%d.%m.%Y %H:%M")
        if v:
            t = str(v).strip()
            if "T" in t and (t.endswith("Z") or "+" in t[10:]):  # UTC/ofsetli ISO tarihi Turkiye saatine cevrilir
                try:
                    return datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(TR_TZ).strftime("%Y-%m-%d %H:%M")
                except ValueError:
                    pass
            return t[:16].replace("T", " ")
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
    if not isinstance(adr, dict):
        adr = {}
    gecmis = [g for g in (p.get("packageHistories") or []) if isinstance(g, dict)]
    ilk = (gecmis[0].get("createdDate") if gecmis else None) or p.get("lastModifiedDate") or p.get("orderDate") or p.get("createdDate")
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
    """Tutari okunur yazar: {'currency','amount'} sozlugu, sayi ya da metin -> '1.222,01 ₺'."""
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
    """(adres, telefon) -> HB adres nesnesini duzgun yaziya cevirir."""
    if isinstance(a, dict):
        satir = [a.get("address") or a.get("addressDetail") or a.get("fullAddress"), a.get("town") or a.get("district"), a.get("city")]
        return ", ".join(str(x) for x in satir if x), str(a.get("phoneNumber") or a.get("phone") or "")
    return (str(a) if a else ""), ""


def hb_kargo_adi(x):
    if isinstance(x, dict):
        return str(x.get("name") or x.get("shortName") or "")
    return str(x or "")


def siparis_normalle_hb_coklu(p):
    """HB paketini siparis(+musteri) bazinda ayirir: musteri adi, siparis no ve adres KALEMLERIN icindedir."""
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
        uyari = "Bu paket birden fazla siparişi/müşteriyi içeriyor; ürünler aşağıda siparişe göre ayrıldı, kargo etiketini kontrol edin." if len(gruplar) > 1 else ""
        cikti.append({
            "pid": "hb", "id": paket_no, "no": no, "paket_no": paket_no,
            "tarih": tr_tarih(ilk.get("orderDate") or p.get("orderDate")), "durum": HB_DURUM.get(durum, "yeni"),
            "alici": alici, "telefon": tel, "adres": adres,
            "urunler": [{"ad": it.get("productName") or "Ürün", "sku": it.get("merchantSku") or "", "adet": it.get("quantity", 1),
                         "fiyat": it.get("price")} for it in grup],
            "tutar": toplam, "kargo": hb_kargo_adi(p.get("cargoCompany") or ilk.get("cargoCompanyModel") or ilk.get("cargoCompany")),
            "barkod": str(p.get("barcode") or p.get("cargoBarcode") or p.get("trackingNumber") or ""),
            "teslim_son": tr_tarih(ilk.get("dueDate")), "uyari": uyari,
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


def siparis_stok_kontrol(ayar):
    """Yeni (açık) siparişlerde ürünün sistemdeki stoğu yetersizse uyarı üretir (günlük + Telegram).
    İlk çalıştırmada mevcut açık siparişler yalnızca 'görüldü' işaretlenir (uyarı yağmuru olmasın). Dönüş: uyarı listesi."""
    u = urunleri_oku()
    if u.empty:
        return []
    ham = u.groupby("barkod")["stok"].max().to_dict()
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
        z = simdi_tr().strftime("%Y-%m-%d %H:%M:%S")
        if yeni:
            with closing(baglan()) as c:
                c.executemany("INSERT OR IGNORE INTO siparis_goruldu (pazar, siparis, zaman) VALUES (?,?,?)", [(pid, a, z) for a, _ in yeni])
                c.commit()
        if ilk:
            continue
        onek = str(pa_al(ayar, "hb").get("sku_prefix", "") or "") if pid == "hb" else ""
        for _, o in yeni:
            for ur in o.get("urunler", []):
                sku = str(ur.get("sku") or "")
                ham_sku = sku[len(onek):] if (onek and sku.startswith(onek)) else sku
                adet = max(_i(ur.get("adet"), 1), 1)
                stok = ham.get(ham_sku, ham.get(sku, uretilen.get(sku)))
                if stok is None:
                    sorun_ = "sistemde bulunamadı"
                elif stok < adet:
                    sorun_ = f"sistem stoğu {int(stok)}, sipariş adedi {adet}"
                else:
                    continue
                uyarilar.append(f"{PAZAR_AD[pid]} sipariş {o.get('no') or o.get('id')}: {str(ur.get('ad'))[:60]} ({sku}) — {sorun_}")
    if uyarilar:
        log_yaz("Sistem", "UYARI", f"{len(uyarilar)} siparişte stok sorunu: " + " || ".join(uyarilar)[:400])
        bildir("Yeni siparişte STOK SORUNU! Tedarikçiyi kontrol edin ya da siparişi iptal edin:\n" + "\n".join(uyarilar[:8]),
               tekil="siparis_stok:" + hashlib.md5("".join(uyarilar).encode()).hexdigest()[:10], bekleme_dk=1440)
    return uyarilar


def siparis_cek(ayar, pid, saat=None):
    if pid == "trendyol":
        s_, k_, x_ = (kimlik(ayar, a) for a in ("trendyol_seller_id", "trendyol_key", "trendyol_secret"))
        gorulen, sonuc, hatalar = set(), [], []
        for durum in ("Created", "Picking", "Invoiced", "Shipped"):
            try:
                paketler_ = trendyol_siparisler(s_, k_, x_, durum, 100)
            except Exception as e:  # tek durum sorgusu patlasa bile diğerleri gelsin
                hatalar.append(f"{durum}: {e}")
                continue
            for p_ in paketler_:
                if p_.get("id") not in gorulen:
                    gorulen.add(p_.get("id"))
                    sonuc.append(siparis_normalle_ty(p_))
        if hatalar:
            log_yaz("Trendyol", "HATA", "Sipariş çekme (kısmi): " + " | ".join(hatalar)[:400])
            if not sonuc and len(hatalar) == 4:
                raise RuntimeError("Trendyol siparişleri alınamadı: " + hatalar[0])
        return sonuc
    if pid == "n11":
        k_, x_ = kimlik(ayar, "n11_key"), kimlik(ayar, "n11_secret")
        gorulen, sonuc, hatalar = set(), [], []
        for durum in ("Created", "Picking", "Shipped"):
            try:
                paketler_ = n11_siparisler(k_, x_, durum)
            except Exception as e:  # tek durum sorgusu patlasa bile diğerleri gelsin
                hatalar.append(f"{durum}: {e}")
                continue
            for p_ in paketler_:
                if p_.get("id") not in gorulen:
                    gorulen.add(p_.get("id"))
                    sonuc.append(siparis_normalle_n11(p_))
        if hatalar:
            log_yaz("N11", "HATA", "Sipariş çekme (kısmi): " + " | ".join(hatalar)[:400])
            if not sonuc and len(hatalar) == 3:
                raise RuntimeError("N11 siparişleri alınamadı: " + hatalar[0])
        return sonuc
    if pid == "hb":
        SIPARIS_TANI.clear()
        sonuc = []
        paketler = hb_paketleri_topla(ayar, int(saat) if saat else 96)
        for x in paketler:
            sonuc += siparis_normalle_hb_coklu(x)
        try:  # henuz paketlenmemis yeni siparisler ayri servisten gelir
            kalemler = hb_yeni_siparis_kalemleri(ayar)
        except requests.RequestException as e:
            kalemler = []
            SIPARIS_TANI["yeni_siparisler_hata"] = str(e)
        if kalemler:
            gorulen = {(o["no"], tuple(sorted(str(u.get("sku", "")) for u in o["urunler"]))) for o in sonuc}
            for o in siparis_normalle_hb_coklu({"items": kalemler, "status": ""}):
                if (o["no"], tuple(sorted(str(u.get("sku", "")) for u in o["urunler"]))) not in gorulen:
                    sonuc.append(o)
        SIPARIS_TANI["toplam_siparis"] = len(sonuc)
        return sonuc
    if pid == "trendruum":
        return [siparis_normalle_tr(x) for x in trendruum_siparisler(ayar)]
    raise RuntimeError(f"{PAZAR_AD.get(pid, pid)} için sipariş çekme desteklenmiyor.")


# --------------------------------------------------------------------------
# Oturum (sayfa yenilense de açık kalır; imzalı, süreli jeton)
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


def _oturum_surumu():
    try:
        return str(kv_oku("oturum_surumu", 0))
    except Exception:
        return "0"


def _imza(sifre, ts):
    return hmac.new(str(sifre).encode(), f"oturum:{ts}:{_oturum_surumu()}".encode(), hashlib.sha256).hexdigest()


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
# Arayüz yardımcıları
# --------------------------------------------------------------------------
def gen(fn, *a, **kw):
    """Streamlit sürümleri arasında 'tam genişlik' parametresi uyumu."""
    for ek in ({"width": "stretch"}, {"use_container_width": True}, {}):
        try:
            return fn(*a, **kw, **ek)
        except TypeError:
            continue
        except Exception as e:  # eski sürümde width='stretch' farklı hata verebilir
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
    ("Anasayfa", "🏠 Anasayfa", "#dbeafe"),
    ("Bildirim", "🔔 Bildirimler", "#fef3c7"),
    ("Urunler", "📦 Sistemdeki Ürünler", "#f8fafc"),
    ("Kritik", "🔄 Oto Kritik Stok", "#dbeafe"),
]
ALT = [("siparis", "Siparişler", "🧾"), ("islemler", "Tüm İşlemleri", "🔗"), ("ayar", "Genel Ayarları", "⚙️")]


def git(sayfa_id):
    st.session_state["sayfa"] = sayfa_id


def git_pazar(pid, alt):
    st.session_state["acik_pazar"] = pid
    st.session_state["sayfa"] = f"{pid}:{alt}"


def ac_kapa(pid):
    st.session_state["acik_pazar"] = None if st.session_state.get("acik_pazar") == pid else pid


def cikis_yap():
    st.session_state.giris_ok = False
    try:  # çıkışta daha önce verilmiş tüm giriş bağlantıları (?t=...) geçersiz olsun
        kv_yaz("oturum_surumu", int(kv_oku("oturum_surumu", 0) or 0) + 1)
    except Exception:
        pass
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
            '<div class="login-card"><div class="login-title">🦅 ŞahEntegre</div>'
            '<div class="login-sub">E-Ticaret Yönetim Paneli</div></div>',
            unsafe_allow_html=True,
        )
        with st.form("giris_formu"):
            girilen = st.text_input("🔑 Yönetici Şifresi", type="password", placeholder="••••••••")
            buton = gen(st.form_submit_button, "Giriş Yap", type="primary")
        if buton:
            simdi_g = time.time()
            son_hatalar = [t_ for t_ in (kv_oku("giris_hatalari", []) or []) if simdi_g - float(t_) < 900]
            if len(son_hatalar) >= 10:  # 15 dakikada 10 hatalı deneme: yeni sekme açmak sayacı sıfırlamaz
                st.error("⛔ Çok fazla hatalı deneme. 15 dakika sonra tekrar deneyin.")
                st.stop()
            hatalar = st.session_state.get("hatali_giris", 0)
            if hatalar >= 5:  # kaba kuvvet yavaşlatma
                time.sleep(min(2 ** (hatalar - 4), 30))
            if hmac.compare_digest(girilen.encode(), str(sifre).encode()):
                st.session_state.hatali_giris = 0
                st.session_state.giris_ok = True
                st.query_params["t"] = oturum_jetonu(sifre)
                st.rerun()
            else:
                st.session_state.hatali_giris = hatalar + 1
                try:
                    kv_yaz("giris_hatalari", son_hatalar + [simdi_g])
                except Exception:
                    pass
                st.error("❌ Hatalı şifre.")
    st.stop()


def secili_urunler(df, anahtar):
    if df.empty or "tedarikci" not in df.columns:
        return df
    liste = sorted(df["tedarikci"].dropna().unique().tolist())
    sec = st.multiselect("Gönderilecek Tedarikçileri Seçin", liste, default=liste, key=f"{anahtar}_ted_sec")
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
        st.caption("Kategori aramak için önce Hepsiburada API bilgilerini kaydedin.")
        return
    st.caption("Önce 'Kategorileri yükle'ye basın (bir kez, birkaç yüz satır olabilir), sonra ürün tipini yazıp arayın. Seçeceğiniz kategori ürünün gerçek (uç) kategorisi olmalı.")
    if gen(st.button, "Kategorileri yükle", key="hbk_yukle"):
        try:
            with st.spinner("Hepsiburada kategorileri alınıyor..."):
                st.session_state["hbk_liste"] = hb_agac_yukle(ayarlar)
        except Exception as e:
            st.session_state["hbk_liste"] = None
            st.error(f"Hata: {e}")
    liste = st.session_state.get("hbk_liste")
    if not liste:
        return
    st.caption(f"{len(liste):,} uç kategori yüklendi.")
    ad = st.text_input("Kategori adı (birden çok kelime yazabilirsiniz)", key="hbk_ara")
    kel = tr_norm(ad).split()
    bulunan = kategori_siralama([k for k in liste if kel and all(w in tr_norm(k["Kategori"]) for w in kel)], ad)[:100]
    if not kel:
        return
    if not bulunan:
        st.warning("Sonuç bulunamadı; daha kısa ya da farklı bir kelime deneyin.")
        return
    d = pd.DataFrame(bulunan)
    st.dataframe(d, hide_index=True)
    secenek = [f"{k['ID']} — {k['Kategori']}" for k in bulunan]
    sec = st.selectbox("Listeden seç", secenek, key="hbk_sec")
    secilen = sec.split(" — ")[0].strip()
    mevcut_vk = pa_al(ayarlar, "hb").get("category_id") or "(boş)"
    st.caption(f"Şu an kayıtlı varsayılan kategori ID: {mevcut_vk}")
    kategoriye_ata_paneli("hb", secilen)
    k1, k2 = st.columns(2)
    if gen(k1.button, "Varsayılan kategori yap", key="hbk_varsayilan"):
        varsayilan_kategori_yaz("hb", secilen)
    if gen(k2.button, "Zorunlu alanları göster", key="hbk_sema"):
        try:
            st.session_state["hbk_sema_sonuc"] = (secilen,) + hb_kategori_sema(ayarlar, secilen)
        except Exception as e:
            st.error(f"Hata: {e}")
    sm = st.session_state.get("hbk_sema_sonuc")
    if sm and sm[0] == secilen:
        st.caption(f"Yanıt: HTTP {sm[1]}")
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


def genel_kategori_ayikla(j):
    """Kategori yanitini (ic ice 'children' ya da duz 'parentId' listesi) [{ID, Kategori, Uc kategori}] yapar."""
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
            kayit.append({"ID": str(cid), "yol": yol, "ust": al(dugum, "parentId", "parent_id", "parentCategoryId"),
                          "uc": not alt})
        for x in (alt or []):
            yuru(x, yol, derinlik + 1)

    for d in (kok if isinstance(kok, list) else []):
        yuru(d, [])
    # duz listede ust-alt iliskisi parentId ile kurulur
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
    """Dokumandaki marka servisleri: /pim/brand/by-name, olmazsa /pim/brand/search-by-name."""
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


def marka_id_yaz(pid, marka_id):
    pa_al(ayarlar, pid)["brand_id"] = str(marka_id).strip()
    ayar_yaz(ayarlar)
    st.session_state[f"marka_bilgi_{pid}"] = str(marka_id).strip()
    st.rerun()


def idefix_marka_bulucu():
    if not pazar_bagli(ayarlar, "idefix"):
        st.caption("Marka aramak için önce İdefix API bilgilerini kaydedin.")
        return
    st.caption("Ürünler bu markayla yüklenir. 'Özel marka = evet' olan markalara yetkiniz yoksa İdefix ürünü VENDOR_BRAND_ACCESS_DENIED ile reddeder.")
    kayitli = str(pa_al(ayarlar, "idefix").get("brand_id", "") or "").strip()
    if kayitli and gen(st.button, f"Kayıtlı Marka ID ({kayitli}) hangi marka?", key="idm_kontrol"):
        try:
            m = idefix_marka_getir(ayarlar, kayitli)
            ozel_m, tur_m = m["Özel marka"], m["Tür"]
            st.info(f"{m['ID']} = {m['Marka']} (özel marka: {ozel_m}, tür: {tur_m})")
        except Exception as e:
            st.error(f"Hata: {e}")
    ad = st.text_input("Marka adı", key="idm_ara")
    if gen(st.button, "Marka ara", key="idm_ara_btn"):
        try:
            st.session_state["idm_sonuc"] = idefix_marka_ara(ayarlar, ad)
            st.session_state["idm_aranan"] = ad
        except Exception as e:
            st.session_state["idm_sonuc"] = None
            st.error(f"Hata: {e}")
    liste = st.session_state.get("idm_sonuc")
    if liste is None:
        return
    if not liste:
        st.warning("Bu isimle marka bulunamadı. Marka İdefix'te kayıtlı değilse İdefix destekten marka ekletmeniz gerekir.")
        return
    st.dataframe(pd.DataFrame(liste), hide_index=True)
    secenek = []
    for m in liste:
        ozel_m = m["Özel marka"]
        secenek.append(f"{m['ID']} — {m['Marka']} (özel: {ozel_m})")
    sec = st.selectbox("Listeden seç", secenek, key="idm_sec")
    secilen = sec.split(" — ")[0].strip()
    if gen(st.button, "Bu markayı Marka ID olarak kaydet", key="idm_kaydet"):
        marka_id_yaz("idefix", secilen)


def n11_agac_yukle(ayar):
    """GET /cdn/categories: tum kategori agaci (subCategories null = en alt kategori)."""
    r = http("GET", f"{N11_BASE}/cdn/categories", headers=n11_header(kimlik(ayar, "n11_key"), kimlik(ayar, "n11_secret")), timeout=120, tries=2)
    if r.status_code != 200:
        raise RuntimeError("N11 kategori listesi alınamadı: " + yanit_ozet(r))
    try:
        j = r.json()
    except Exception:
        raise RuntimeError("N11 kategori yanıtı okunamadı: " + (r.text or "")[:400])
    liste = genel_kategori_ayikla(j)
    if not liste:
        raise RuntimeError("N11 kategori yanıtı tanınamadı. Yanıtın başı: " + (r.text or "")[:500])
    return liste


def n11_oto_dugumler(ayar):
    out = []
    for k in n11_agac_yukle(ayar):
        if k["Uc kategori"] != "evet":
            continue
        out.append({"ID": k["ID"], "yol": k["Kategori"], "son": kat_belirtec(k["Kategori"].split(">")[-1]), "tum": kat_belirtec(k["Kategori"])})
    return out


def n11_kategori_sema(ayar, cid):
    """GET /cdn/category/{id}/attribute: kategorinin ozellikleri (isMandatory true olanlar urun bazinda gonderilmeli)."""
    r = http("GET", f"{N11_BASE}/cdn/category/{urllib.parse.quote(str(cid), safe='')}/attribute",
             headers=n11_header(kimlik(ayar, "n11_key"), kimlik(ayar, "n11_secret")), timeout=60, tries=1)
    try:
        j = r.json()
    except Exception:
        j = None
    return r.status_code, j, (r.text or "")[:3000]


def n11_kategori_bulucu():
    if not pazar_bagli(ayarlar, "n11"):
        st.caption("Kategori aramak için önce N11 API bilgilerini kaydedin.")
        return
    st.caption("Önce 'Kategorileri yükle'ye basın, sonra ürün tipini yazıp arayın. N11 ürün eklemede yalnızca EN ALT düzey kategoriler kullanılır ('Uç kategori = evet').")
    if gen(st.button, "Kategorileri yükle", key="n11k_yukle"):
        try:
            with st.spinner("N11 kategorileri alınıyor..."):
                st.session_state["n11k_liste"] = n11_agac_yukle(ayarlar)
        except Exception as e:
            st.session_state["n11k_liste"] = None
            st.error(f"Hata: {e}")
    liste = st.session_state.get("n11k_liste")
    if not liste:
        return
    st.caption(f"{len(liste):,} kategori yüklendi.")
    ad = st.text_input("Kategori adı (birden çok kelime yazabilirsiniz)", key="n11k_ara")
    kel = tr_norm(ad).split()
    if not kel:
        return
    bulunan = kategori_siralama([k for k in liste if all(w in tr_norm(k["Kategori"]) for w in kel)], ad)[:100]
    if not bulunan:
        st.warning("Sonuç bulunamadı; daha kısa ya da farklı bir kelime deneyin.")
        return
    st.dataframe(pd.DataFrame(bulunan), hide_index=True)
    secenek = [f"{k['ID']} — {k['Kategori']}" for k in bulunan]
    sec = st.selectbox("Listeden seç", secenek, key="n11k_sec")
    secilen = sec.split(" — ")[0].strip()
    mevcut_vk = pa_al(ayarlar, "n11").get("category_id") or "(boş)"
    st.caption(f"Şu an kayıtlı varsayılan kategori ID: {mevcut_vk}")
    kategoriye_ata_paneli("n11", secilen)
    k1, k2 = st.columns(2)
    if gen(k1.button, "Varsayılan kategori yap", key="n11k_varsayilan"):
        varsayilan_kategori_yaz("n11", secilen)
    if gen(k2.button, "Zorunlu alanları göster", key="n11k_sema"):
        try:
            st.session_state["n11k_sema_sonuc"] = (secilen,) + n11_kategori_sema(ayarlar, secilen)
        except Exception as e:
            st.error(f"Hata: {e}")
    sm = st.session_state.get("n11k_sema_sonuc")
    if sm and sm[0] == secilen:
        st.caption(f"Yanıt: HTTP {sm[1]}")
        j = sm[2] if isinstance(sm[2], dict) else {}
        ozellikler = [x for x in (j.get("categoryAttributes") or []) if isinstance(x, dict)]
        for x in ozellikler:
            etiketler = []
            if x.get("isMandatory"):
                etiketler.append("ZORUNLU")
            if x.get("isVariant"):
                etiketler.append("varyant")
            if not x.get("isCustomValue"):
                etiketler.append("listeden değer seçilmeli")
            eklenti = " - " + ", ".join(etiketler) if etiketler else ""
            st.write(f"- {x.get('attributeName')} (id {x.get('attributeId')}){eklenti}")
        if not ozellikler:
            st.text(sm[3])


def idefix_kategori_bulucu():
    if not pazar_bagli(ayarlar, "idefix"):
        st.caption("Kategori aramak için önce İdefix API bilgilerini kaydedin.")
        return
    st.caption("Önce 'Kategorileri yükle'ye basın, sonra ürün tipini yazıp arayın. Yalnızca 'Uç kategori = evet' olanları seçin.")
    if gen(st.button, "Kategorileri yükle", key="idk_yukle"):
        try:
            with st.spinner("İdefix kategorileri alınıyor..."):
                st.session_state["idk_liste"] = idefix_agac_yukle(ayarlar)
        except Exception as e:
            st.session_state["idk_liste"] = None
            st.error(f"Hata: {e}")
    liste = st.session_state.get("idk_liste")
    if not liste:
        return
    st.caption(f"{len(liste):,} kategori yüklendi.")
    ad = st.text_input("Kategori adı (birden çok kelime yazabilirsiniz)", key="idk_ara")
    kel = tr_norm(ad).split()
    if not kel:
        return
    bulunan = kategori_siralama([k for k in liste if all(w in tr_norm(k["Kategori"]) for w in kel)], ad)[:100]
    if not bulunan:
        st.warning("Sonuç bulunamadı; daha kısa ya da farklı bir kelime deneyin.")
        return
    st.dataframe(pd.DataFrame(bulunan), hide_index=True)
    secenek = [f"{k['ID']} — {k['Kategori']}" for k in bulunan]
    sec = st.selectbox("Listeden seç", secenek, key="idk_sec")
    secilen = sec.split(" — ")[0].strip()
    mevcut_vk = pa_al(ayarlar, "idefix").get("category_id") or "(boş)"
    st.caption(f"Şu an kayıtlı varsayılan kategori ID: {mevcut_vk}")
    kategoriye_ata_paneli("idefix", secilen)
    if gen(st.button, "Varsayılan kategori yap", key="idk_varsayilan"):
        varsayilan_kategori_yaz("idefix", secilen)


def oto_esleme(pid, pa, adet, mevcut):
    st.markdown("**Otomatik öneri**")
    pazar_ad = {"trendruum": "Trendruum", "hb": "Hepsiburada", "idefix": "İdefix", "n11": "N11", "ptt": "PTT AVM"}.get(pid, pid)
    st.caption(f"{pazar_ad} kategori listesini çekip tedarikçi kategorilerinize en yakın kategoriyi önerir. "
               "Hiçbir şey kendiliğinden kaydedilmez; işaretlediğiniz satırlar kaydedilir.")
    bildirim = st.session_state.pop(f"oto_bildirim_{pid}", None)
    if bildirim:
        st.success(bildirim)
    tek_tus = gen(st.button, "⚡ Tek tuş: hepsini bul, yüksek güvenlileri kaydet", key=f"oto_tek_{pid}", type="primary")
    if gen(st.button, "Önerileri hazırla (önce ben bakayım)", key=f"oto_hazirla_{pid}") or tek_tus:
        try:
            with st.spinner("Kategori listesi alınıyor..."):
                dugumler = {"trendruum": trendruum_agac_yukle, "hb": hb_oto_dugumler, "idefix": idefix_oto_dugumler, "n11": n11_oto_dugumler, "ptt": ptt_oto_dugumler}[pid](ayarlar)
            satirlar = []
            for k in adet.index:
                if mevcut.get(k):
                    continue
                i, y, g = kategori_oner(k, dugumler)
                satirlar.append({"Onayla": g == "yuksek", "Tedarikçi kategorisi": k, "Ürün": int(adet[k]),
                                 "Önerilen kategori": y, "Güven": {"yuksek": "Yüksek", "orta": "Orta", "dusuk": "Düşük"}.get(g, "Yok"),
                                 "ID": i})
            if tek_tus:
                yeni_esl = dict(mevcut)
                kayit = 0
                for r in satirlar:
                    if r["Güven"] == "Yüksek" and str(r["ID"]).strip():
                        yeni_esl[str(r["Tedarikçi kategorisi"])] = str(r["ID"])
                        kayit += 1
                pa["kategori_eslesme"] = yeni_esl
                ayar_yaz(ayarlar)
                satirlar = [r for r in satirlar if not (r["Güven"] == "Yüksek" and str(r["ID"]).strip())]
                for r in satirlar:
                    r["Onayla"] = False
                st.session_state[f"oto_bildirim_{pid}"] = (
                    f"{kayit} kategori otomatik eşleştirildi ve kaydedildi. {len(satirlar)} kategori için güveni düşük "
                    "öneri aşağıda; kontrol edip işaretleyin. Büyük kategorileri tabloda mutlaka gözden geçirin.")
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
    st.caption(f"{len(sat)} eşleşmemiş kategori için öneri hazır. 'Yüksek' güvenliler işaretli geldi; 'Orta/Düşük' olanları kendiniz kontrol edip işaretleyin.")
    sv = f"oto_surum_{pid}"
    b1, b2, b3 = st.columns(3)
    toplu = None
    if gen(b1.button, "☑️ Tümünü işaretle", key=f"oto_tum_{pid}"):
        toplu = "tum"
    if gen(b2.button, "☑️ Orta ve yükseği işaretle", key=f"oto_orta_{pid}"):
        toplu = "orta"
    if gen(b3.button, "⬜ Hiçbirini işaretleme", key=f"oto_hic_{pid}"):
        toplu = "hic"
    if toplu:
        for r in sat:
            var = bool(str(r.get("ID", "")).strip())  # önerisi olmayan satır işaretlenmez
            r["Onayla"] = var and (toplu == "tum" or (toplu == "orta" and r.get("Güven") in ("Yüksek", "Orta")))
        st.session_state[sv] = st.session_state.get(sv, 0) + 1
        st.rerun()
    duz = st.data_editor(d, hide_index=True, key=f"oto_{pid}_{len(d)}_{st.session_state.get(sv, 0)}",
                         disabled=["Tedarikçi kategorisi", "Ürün", "Önerilen kategori", "Güven", "ID"])
    if gen(st.button, "İşaretlenenleri kaydet", key=f"oto_kaydet_{pid}"):
        yeni = dict(mevcut)
        n = 0
        for _, r in duz.iterrows():
            if r["Onayla"] and str(r["ID"]).strip():
                yeni[str(r["Tedarikçi kategorisi"])] = str(r["ID"])
                n += 1
        pa["kategori_eslesme"] = yeni
        ayar_yaz(ayarlar)
        st.session_state[f"oneri_{pid}"] = None
        st.success(f"{n} kategori eşleştirmesi kaydedildi (toplam {len(yeni)}).")
        st.rerun()
    st.divider()


def kategori_esleme_editoru(pid):
    pa = pa_al(ayarlar, pid)
    df = urunleri_oku()
    if df.empty or "kategori" not in df.columns:
        st.caption("Kategori eşleştirmesi için önce tedarikçi senkronizasyonu yapın.")
        return
    mevcut = pa.get("kategori_eslesme") or {}
    ana = df["kategori"].dropna().astype(str).map(lambda k: k.split(">>>")[0].strip())
    adet = ana[ana != ""].value_counts()
    st.caption(f"{len(adet)} farklı tedarikçi kategorisi var; eşleşmemiş ürünler (varsayılan kapalıyken) gönderilmez.")
    if pa.get("varsayilan_kategori_kullan"):
        st.error("⚠️ 'Eşleşmesi olmayan ürünleri de varsayılan kategoriye koy' AÇIK: ID'si girilmemiş her kategori "
                 f"({pa.get('category_id') or 'varsayılan'}) kategorisine gider. Bunu kapatın (Genel Ayarlar); eşleşmeyenler gönderilmeden atlanır.")
    if pid in ("trendruum", "hb", "idefix", "n11", "ptt"):
        oto_esleme(pid, pa, adet, mevcut)
    st.markdown("**Elle eşleştirme**")
    ara = st.text_input("Kategori ara (filtre)", key=f"kat_ara_{pid}")
    liste = [k for k in adet.index if not ara.strip() or tr_norm(ara) in tr_norm(k)]
    sadece_bos = st.checkbox("Sadece ID'si girilmemişleri göster", key=f"kat_bos_{pid}")
    if sadece_bos:
        liste = [k for k in liste if not mevcut.get(k)]
    liste = liste[:300]
    tablo = pd.DataFrame({
        "Tedarikçi kategorisi": liste,
        "Ürün sayısı": [int(adet[k]) for k in liste],
        "Pazar yeri kategori ID": [str(mevcut.get(k, "")) for k in liste],
    })
    duz = st.data_editor(tablo, hide_index=True, disabled=["Tedarikçi kategorisi", "Ürün sayısı"], key=f"kat_edit_{pid}_{ara}_{sadece_bos}")
    if gen(st.button, "Eşleştirmeyi kaydet", key=f"kat_kaydet_{pid}"):
        yeni = dict(mevcut)  # filtrede görünmeyen eşleştirmeler korunur
        for _, r in duz.iterrows():
            k, v = str(r["Tedarikçi kategorisi"]), str(r["Pazar yeri kategori ID"]).strip()
            if v:
                yeni[k] = v
            else:
                yeni.pop(k, None)
        if pid == "trendruum":
            gecersiz = [k for k, v in yeni.items() if not objectid_mi(v)]
            if gecersiz:
                st.error(f"Trendruum kategori ID'si 24 karakterlik olmalı. Hatalı: {', '.join(gecersiz[:5])}")
                return
        pa["kategori_eslesme"] = yeni
        ayar_yaz(ayarlar)
        st.success(f"Toplam {len(yeni)} kategori eşleştirmesi kayıtlı.")


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
        st.success(f"Varsayılan kategori ID kaydedildi: {bilgi}")
    mb = st.session_state.pop(f"marka_bilgi_{pid}", None)
    if mb:
        st.success(f"Marka ID kaydedildi: {mb}")
    with st.form(f"ayar_form_{pid}"):
        st.markdown("**Fiyat kuralları (bu pazar yeri için)**")
        c1, c2, c3 = st.columns(3)
        marj = c1.number_input("Kâr marjı % (0 = tedarikçi değeri)", 0.0, 500.0, _f(pa.get("kar_marji")), 1.0)
        kargo = c2.number_input("Sabit kargo TL (0 = tedarikçi değeri)", 0.0, 5000.0, _f(pa.get("sabit_kargo")), 5.0)
        artis = c3.number_input("Ek fiyat artışı % (komisyon vb.)", 0.0, 200.0, _f(pa.get("fiyat_artis")), 0.5)
        yeni = {"kar_marji": marj, "sabit_kargo": kargo, "fiyat_artis": artis}
        hata = None
        if pid == "hb":
            yeni["sku_prefix"] = st.text_input("Merchant SKU öneki (varsa)", value=str(pa.get("sku_prefix", "") or ""))
        if pid in ("n11", "idefix", "trendruum", "ptt", "hb"):
            st.markdown("**Ürün oluşturma ayarları**")
            c1, c2, c3 = st.columns(3)
            yeni["category_id"] = c1.text_input("Varsayılan kategori ID", value=str(pa.get("category_id", "") or ""),
                                                key=f"vk_alan_{pid}_{pa.get('category_id', '')}")
            yeni["varsayilan_kategori_kullan"] = st.checkbox(
                "Eşleşmesi olmayan ürünleri de varsayılan kategoriye koy",
                value=bool(pa.get("varsayilan_kategori_kullan", False)),
                help="Kapalıyken (önerilen) yalnızca 'Kategori eşleştirme'de ID'si girilmiş ürünler gönderilir; "
                     "diğerleri atlanır. Açıkken tüm ürünler varsayılan kategoriye düşer.")
            if pid in ("idefix", "trendruum"):
                yeni["brand_id"] = c2.text_input("Marka ID", value=str(pa.get("brand_id", "") or (kimlik(ayarlar, "trendruum_brand") if pid == "trendruum" else "")),
                                                 key=f"marka_alan_{pid}_{pa.get('brand_id', '')}")
            kdv_liste = [20, 10, 1, 0]
            kdv_now = _i(pa.get("kdv"), 20)
            yeni["kdv"] = c3.selectbox("KDV %", kdv_liste, index=kdv_liste.index(kdv_now) if kdv_now in kdv_liste else 0)
        if pid == "n11":
            c1, c2 = st.columns(2)
            yeni["shipment_template"] = c1.text_input("Kargo şablonu adı", value=str(pa.get("shipment_template", "") or ""))
            yeni["preparing_day"] = int(c2.number_input("Hazırlık süresi (gün)", 1, 30, _i(pa.get("preparing_day"), 3) or 3))
        if pid == "idefix":
            c1, c2 = st.columns(2)
            yeni["teslim_suresi"] = int(c1.number_input("Teslim süresi (gün)", 1, 30, _i(pa.get("teslim_suresi"), 3) or 3))
            yeni["stok_kodu_barkod"] = c2.checkbox("Geçerli barkodu olmayan ürünlerde stok kodunu barkod yerine kullan", value=bool(pa.get("stok_kodu_barkod")))
        if pid == "hb":
            yeni["urun_endpoint"] = st.text_input("Ürün oluşturma adresi (tam https URL, Hepsiburada dokümanından)", value=str(pa.get("urun_endpoint", "") or ""),
                                                  help="https://….hepsiburada.com/… biçiminde; boşsa ürün oluşturma kapalı kalır.")
            yeni["marka"] = st.text_input("Marka adı", value=str(pa.get("marka", "") or ""))
        if pid == "ptt":
            c1, c2, c3 = st.columns(3)
            yeni["marka"] = c1.text_input("Marka adı (isteğe bağlı)", value=str(pa.get("marka", "") or ""))
            yeni["desi"] = c2.number_input("Desi", 0.1, 500.0, _f(pa.get("desi"), 1.0) or 1.0, 0.5)
            yeni["kargo_profil"] = c3.text_input("Kargo profil ID (isteğe bağlı)", value=str(pa.get("kargo_profil", "") or ""))
            yeni["aktif_gonder"] = st.checkbox("Ürünleri aktif (satışta) olarak gönder", value=bool(pa.get("aktif_gonder", False)),
                                               help="Kapalıyken ürünler pasif oluşturulur; PTT panelinden kontrol edip aktifleştirebilirsiniz (önerilen).")
        if pid in ("trendruum", "ptt", "hb"):
            yeni["gecici_barkod"] = st.checkbox("Geçerli barkodu olmayan ürünlere kalıcı geçici barkod üret (869…)", value=bool(pa.get("gecici_barkod", True)))
        if pid == "hb":
            h1, h2 = st.columns(2)
            yeni["garanti"] = int(h1.number_input("Garanti süresi (ay)", 0, 120, _i(pa.get("garanti"), 24)))
            yeni["kg"] = h2.number_input("Ağırlık (kg)", 0.01, 500.0, _f(pa.get("kg"), 1.0) or 1.0, 0.1)
            ek_metin = st.text_area("Ek ürün özellikleri (JSON nesnesi; kategorinin istediği alanlar)",
                                    value=json.dumps(pa.get("ek_ozellik") or {}, ensure_ascii=False),
                                    help='Örnek: {"renk_variant_property": "Siyah"}. Kategorinin zorunlu alanlarını kategori bulucudaki "Zorunlu alanları göster" ile görebilirsiniz.')
            try:
                ek = json.loads(ek_metin.strip() or "{}")
                if not isinstance(ek, dict):
                    raise ValueError("nesne olmalı")
                yeni["ek_ozellik"] = ek
            except ValueError as e:
                hata = f"Ek özellikler geçerli bir JSON nesnesi olmalı: {e}"
        if pid in ("n11", "idefix"):
            atr_metin = st.text_area("Zorunlu özellikler (JSON listesi, boş bırakılabilir)",
                                     value=json.dumps(pa.get("attributes") or [], ensure_ascii=False))
            try:
                atr = json.loads(atr_metin.strip() or "[]")
                if not isinstance(atr, list):
                    raise ValueError("liste olmalı")
                yeni["attributes"] = atr
            except ValueError as e:
                hata = f"Özellikler geçerli bir JSON listesi olmalı: {e}"
        if gen(st.form_submit_button, "💾 Ayarları kaydet", type="primary"):
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
    with st.expander("➕ Yeni Tedarikçi Ekle", expanded=not tedarikciler):
        t_ad = st.text_input("Tedarikçi Adı")
        t_link = st.text_input("XML İndirme Linki (URL)")
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
    st.markdown("### ⏱️ Otomatik Güncelleme")
    dk = st.number_input("Senkronizasyon aralığı (dakika)", 5, 1440, int(senkron_dk_degeri(ayarlar)))
    st.caption("Her turda tedarikçi XML'i yenilenir ve stok/fiyat pazar yerlerine gönderilir. Aralık değişikliği bir sonraki döngüde geçerli olur. Çok kısa aralık pazar yerinde sınır aşımına yol açabilir.")
    ust = st.number_input("Stok üst sınırı (0 = sınırsız; tedarikçinin stoğu aynen gider)", 0, 1000000, stok_ust_degeri(ayarlar))
    pay = st.number_input("Güvenlik payı (pazar yerine giden stoktan düşülecek adet)", 0, 100, _i(ayarlar.get("stok_guvenlik_payi")),
                          help="Tedarikçide 3 varsa ve pay 2 ise pazar yerine 1 gider; stok payın altına düşünce 0 gider. Stoksuz satış riskini azaltır.")
    tavan = st.number_input("Pazar yerinde en fazla gösterilecek stok (0 = sınırsız)", 0, 100000, _i(ayarlar.get("pazar_stok_tavani")),
                            help="Tedarikçide 100 olsa da pazar yerinde en fazla bu kadar görünür. Tedarikçi stoğu aniden biterse en fazla bu kadar stoksuz satış olur.")
    oto = st.toggle(f"🤖 Otomatik senkronizasyon ({int(dk)} dakikada bir)", value=ayarlar.get("oto_senkron", True))
    if (oto, int(dk), int(ust), int(pay), int(tavan)) != (ayarlar.get("oto_senkron", True), int(senkron_dk_degeri(ayarlar)), stok_ust_degeri(ayarlar), _i(ayarlar.get("stok_guvenlik_payi")), _i(ayarlar.get("pazar_stok_tavani"))):
        ayarlar.update({"oto_senkron": oto, "senkron_dk": int(dk), "stok_ust_sinir": int(ust), "stok_guvenlik_payi": int(pay), "pazar_stok_tavani": int(tavan)})
        ayar_yaz(ayarlar)

    b1_, b2_ = st.columns(2)
    if b1_.button("🔄 Tümünü Şimdi Senkronla", type="primary"):
        with st.spinner("Güncelleniyor..."):
            for ad, ok, msg in tumunu_senkronla(oto=False):
                (st.success if ok else st.error)(f"{ad}: {msg}")
    if b2_.button("⚠️ Düşüşü kabul et ve senkronla", help="Koruma 'şüpheli XML' dediyse ve tedarikçi gerçekten ürün/stok azalttıysa kullanın."):
        with st.spinner("Güncelleniyor (koruma devre dışı)..."):
            for ad, ok, msg in tumunu_senkronla(oto=False, zorla=True):
                (st.success if ok else st.error)(f"{ad}: {msg}")

    st.markdown("---")
    for ad, bilgi in list(tedarikciler.items()):
        with st.expander(f"🏢 {ad}"):
            st.text(f"Link: {bilgi['link'][:70]}{'...' if len(bilgi['link']) > 70 else ''}")
            c1, c2 = st.columns(2)
            if c1.button("📥 XML'i yedek olarak hazırla", key=f"xml_indir_{ad}"):
                try:
                    st.session_state[f"xml_yedek_{ad}"] = indir(bilgi["link"], _f(bilgi.get("zaman_asimi"), 300.0))
                except Exception as e:
                    st.error(f"İndirilemedi: {e}")
            if f"xml_yedek_{ad}" in st.session_state:
                st.download_button("💾 XML Kaydet", data=st.session_state[f"xml_yedek_{ad}"], file_name=f"{ad}_yedek.xml", mime="application/xml", key=f"xml_kaydet_{ad}")
            with c2:
                onay = st.checkbox("Silmeyi onayla", key=f"sil_onay_{ad}")
                if st.button("🗑️ Tedarikçiyi Sil", key=f"sil_{ad}", disabled=not onay):
                    tedarikciler.pop(ad, None)
                    ayar_yaz(ayarlar)
                    with closing(baglan()) as c:
                        c.execute("DELETE FROM urunler WHERE tedarikci=?", (ad,))
                        c.commit()
                    st.rerun()
            zs = st.number_input("XML bekleme süresi (sn)", 30, 1800, int(_f(bilgi.get("zaman_asimi"), 300.0)), 30, key=f"{ad}_zs",
                                 help="Yavaş yanıt veren tedarikçiler için artırın.")
            if float(zs) != _f(bilgi.get("zaman_asimi"), 300.0):
                bilgi["zaman_asimi"] = float(zs)
                ayar_yaz(ayarlar)
            st.markdown("**🏷️ Bu tedarikçinin ürünleri hangi markayla gitsin?**")
            st.caption("Boş bırakılan alan için pazar yerinin genel markası kullanılır. Yalnızca YENİ ürün oluşturmada geçerlidir; pazarda zaten açılmış ürünün markası değişmez.")
            mk_eski = bilgi.get("markalar") or {}
            mk_yeni = {}
            mc = st.columns(2)
            for i_m, (pid_m, alan_m, etk_m) in enumerate(MARKA_ALANLARI):
                mevcut_m = str(((mk_eski.get(pid_m) or {}).get(alan_m)) or "")
                v_m = mc[i_m % 2].text_input(etk_m, value=mevcut_m, key=f"{ad}_mk_{pid_m}").strip()
                if v_m:
                    mk_yeni.setdefault(pid_m, {})[alan_m] = v_m
            if mk_yeni != {k: v for k, v in mk_eski.items() if v}:
                bilgi["markalar"] = mk_yeni
                ayar_yaz(ayarlar)
                st.success("Marka ayarı kaydedildi. Yeni ürün gönderiminden itibaren geçerli.")
            with st.expander("📉 Bu tedarikçinin ürünlerini satıştan kaldır (stok sıfırla ve kilitle)"):
                st.caption("Tedarikçinin TÜM ürünlerinin stoğu 0 yapılır ve kilitlenir (senkron stoğu geri açmaz). Seçtiğin pazar yerlerine 0 stok hemen gönderilir; ürünler satışa kapanır ama silinmez. "
                           "Geri açmak için 'Kilidi kaldır' düğmesini kullan.")
                with closing(baglan()) as c_t:
                    t_bk = [str(r_[0]) for r_ in c_t.execute("SELECT DISTINCT barkod FROM urunler WHERE tedarikci=?", (ad,))]
                kilit_t = stok_sifir_kume(ayarlar)
                bagli_p = [pid for pid in GUNCELLEYICI if pazar_bagli(ayarlar, pid)]
                sec_p = st.multiselect("Hangi pazar yerlerinde sıfırlansın?", bagli_p, default=[p_ for p_ in ("hb",) if p_ in bagli_p],
                                       format_func=lambda x: PAZAR_AD.get(x, x), key=f"{ad}_sifir_pazar")
                st.write(f"Etkilenecek ürün: **{len(t_bk):,}**")
                t_onay = st.checkbox(f"{len(t_bk):,} ürünün stoğunu sıfırlamayı onaylıyorum", key=f"{ad}_sifir_onay")
                z1, z2 = st.columns(2)
                if z1.button("🔒 Hepsini sıfırla ve kilitle", key=f"{ad}_sifir_btn", disabled=not (t_onay and sec_p and t_bk)):
                    with st.spinner("Sıfırlanıyor ve pazar yerlerine gönderiliyor..."):
                        sonuc_t = stok_sifirla(ayarlar, t_bk, True, sec_p)
                    st.success(f"{len(t_bk):,} ürünün stoğu sıfırlandı ve kilitlendi.")
                    for ad_p, ok_p, h_p in sonuc_t:
                        (st.error if h_p else st.info)(f"{ad_p}: {ok_p} gönderildi" + (f", hata: {h_p}" if h_p else ""))
                kilitli_t = [b for b in t_bk if b in kilit_t]
                if z2.button(f"🔓 Kilidi kaldır ({len(kilitli_t):,})", key=f"{ad}_kilit_btn", disabled=not kilitli_t):
                    n_k = stok_kilidi_kaldir(ayarlar, kilitli_t)
                    st.success(f"{n_k:,} ürünün kilidi kaldırıldı. 'Tümünü Şimdi Senkronla'ya bas; stoklar tedarikçiden geri gelir ve pazar yerine gider.")
            st.markdown("**💱 Fiyat / Para Birimi**")
            kdv_e = st.checkbox("Fiyata KDV ekle (XML'deki KDV alanından, yoksa %20)", bool(bilgi.get("kdv_ekle")), key=f"{ad}_kdv_ekle")
            dv_k = st.checkbox("Para birimi kontrolü (urun_doviz: TL / USD)", bool(bilgi.get("doviz_kontrol")), key=f"{ad}_dvk",
                               help="Açıkken USD ürünler dolar kuruyla TL'ye çevrilir. TL/USD dışı ya da boş para birimli ürünler gönderilmez.")
            kur_g = st.number_input("Dolar kuru (TL)", 0.0, 1000.0, _f(bilgi.get("usd_kuru")), 0.05, key=f"{ad}_kur",
                                    help="Elle girin ve düzenli güncelleyin.")
            usd_b = st.checkbox("USD ürün bekleniyor (hiç gelmezse senkronizasyonu durdur)", bool(bilgi.get("usd_bekle")), key=f"{ad}_usdb")
            yeni_d = {"kdv_ekle": kdv_e, "doviz_kontrol": dv_k, "usd_kuru": float(kur_g), "usd_bekle": usd_b}
            if any(bilgi.get(k) != v for k, v in yeni_d.items()):
                bilgi.update(yeni_d)
                ayar_yaz(ayarlar)
                st.success("Kaydedildi. Senkronizasyondan sonra fiyatlara uygulanır.")
            oz = DOVIZ_SON.get(ad)
            if oz:
                st.dataframe(pd.DataFrame([{"TL": oz["tl"], "USD": oz["usd"], "Belirsiz (gönderilmez)": oz["bilinmeyen"]}]), hide_index=True)
                if oz["bilinmeyen_degerler"]:
                    st.warning(f"Belirsiz para birimi değerleri: {oz['bilinmeyen_degerler']}")
                for o in oz.get("ornek_usd") or []:
                    st.caption(f"USD örnek: {o}")
                if oz["usd"] == 0:
                    st.warning("Hiç USD ürün yok. Tedarikçi para birimi alanını henüz düzeltmemiş olabilir.")
            onizleme = st.session_state.get(f"onizleme_{ad}")
            if gen(st.button, "🔍 XML alanlarını yükle / yenile", key=f"onizle_{ad}"):
                try:
                    with st.spinner("XML indiriliyor ve analiz ediliyor..."):
                        df_t = xml_onizleme(bilgi["link"], float(zs))
                    onizleme = {"kolonlar": list(df_t.columns), "ornek": df_t.head(5)}
                    st.session_state[f"onizleme_{ad}"] = onizleme
                except Exception as e:
                    st.warning(f"XML analiz edilemedi: {e}")
            if not onizleme:
                st.caption("Alan eşleştirmesini düzenlemek için yukarıdaki düğmeyle XML'i yükleyin. Kayıtlı eşleştirme senkronizasyonda aynen kullanılır.")
                continue
            st.caption("XML'deki tüm alanlar: " + ", ".join(str(k) for k in onizleme["kolonlar"]))
            marka_alani = [k for k in onizleme["kolonlar"] if any(w in str(k).lower() for w in ("brand", "marka", "manufactur", "vendor", "uretici"))]
            if marka_alani:
                st.success("Marka alanı bulundu: " + ", ".join(str(k) for k in marka_alani))
            else:
                st.warning("Bu XML'de marka/brand adında bir alan görünmüyor.")
            with st.expander("Ham XML önizleme (ilk 5 ürün)"):
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
                "ad": sec("Ürün Adı", ["urunadi", "ürünadı", "name", "title", "ad", "baslik"], "ad"),
                "stok": sec("Stok", ["stok", "stock", "quantity", "adet", "miktar"], "stok"),
                "fiyat": sec("Alış Fiyatı", ["bayi", "toptan", "dealer", "wholesale", "alis", "alış", "fiyat", "price"], "fiyat"),
                "gorsel": sec("Görsel", ["image_1", "resim", "image", "gorsel", "görsel", "picture", "foto"], "gorsel"),
                "kategori": sec("Kategori", ["kategori", "category", "cat", "tur", "grup", "maincategory"], "kategori"),
            }
            marj = st.number_input("Kâr Marjı (%)", 0.0, 500.0, float(bilgi.get("marj", 30.0)), 1.0, key=f"{ad}_marj")
            sabit = st.number_input("Sabit Ek / Kargo (TL)", 0.0, 5000.0, float(bilgi.get("sabit_ek", 0.0)), 5.0, key=f"{ad}_sabit")
            if harita != eski or marj != bilgi.get("marj") or sabit != bilgi.get("sabit_ek"):
                fiyat_degisti = marj != bilgi.get("marj") or sabit != bilgi.get("sabit_ek")
                bilgi.update({"harita": harita, "marj": marj, "sabit_ek": sabit})
                ayar_yaz(ayarlar)
                if fiyat_degisti:
                    n_f = fiyat_yeniden_hesapla(ad, bilgi)
                    st.success(f"Kaydedildi. {n_f:,} ürünün satış fiyatı yeni marj/kargo ile yeniden hesaplandı. Pazar yerlerine göndermek için 'Tüm Stok/Fiyatları Güncelle'ye basın.")
                else:
                    st.success("Kaydedildi. Alan eşleştirmesi bir sonraki senkronizasyonda uygulanır.")
            st.markdown("**📊 Kademeli kâr marjı (alış fiyatına göre)**")
            kad_a = st.checkbox("Kademeli marjı kullan (açıkken yukarıdaki tek marj yerine geçer)", bool(bilgi.get("kademe_aktif")), key=f"{ad}_kad_a")
            mevcut = kademe_temizle(bilgi.get("kademe")) or [list(r) for r in VARSAYILAN_KADEME]
            tablo = pd.DataFrame([{"Alış fiyatı bu TL'ye kadar (boş = üstü hepsi)": r[0], "Marj %": r[1]} for r in mevcut])
            duz = st.data_editor(tablo, num_rows="dynamic", hide_index=True, key=f"{ad}_kad_t")
            yeni_k = kademe_temizle([[(None if r.iloc[0] != r.iloc[0] else r.iloc[0]), r.iloc[1]] for _, r in duz.iterrows()])
            if kad_a != bool(bilgi.get("kademe_aktif")) or yeni_k != kademe_temizle(bilgi.get("kademe")):
                bilgi.update({"kademe_aktif": kad_a, "kademe": yeni_k or [list(r) for r in VARSAYILAN_KADEME]})
                ayar_yaz(ayarlar)
                n_f = fiyat_yeniden_hesapla(ad, bilgi)
                st.success(f"Kademe kaydedildi. {n_f:,} ürünün satış fiyatı yeniden hesaplandı. Pazar yerlerine göndermek için 'Tüm Stok/Fiyatları Güncelle'ye basın.")
            if kad_a:
                ozet_k = ", ".join(("üstü" if r[0] is None else f"{int(r[0])} TL'ye kadar") + f" %{r[1]:g}" for r in kademe_temizle(bilgi.get("kademe")))
                st.caption("Örnek: " + ozet_k)

            st.markdown("**🎯 Hedef net kâr ile fiyatlama (zarar etmeden)**")
            st.caption("Komisyon, kargo ve vergiler düşüldükten sonra cebinizde kalacak NET kârı siz belirlersiniz; satış fiyatı buna göre hesaplanır. Açıkken yukarıdaki marj ve kademe yerine geçer. Alış fiyatı KDV dahil kabul edilir; XML fiyatı KDV hariçse 'Fiyata KDV ekle'yi açın.")
            h_aktif = st.checkbox("Hedef net kâr ile fiyatla", bool(bilgi.get("hedef_aktif")), key=f"{ad}_h_aktif")
            hc1, hc2, hc3 = st.columns(3)
            h_kargo = hc1.number_input("Kargo maliyeti (TL)", 0.0, 3000.0, _f(bilgi.get("h_kargo"), 150.0), 5.0, key=f"{ad}_h_kargo")
            h_bayi = hc2.number_input("Bayi kargo/işlem (TL)", 0.0, 1000.0, _f(bilgi.get("h_bayi_kargo"), 15.0), 1.0, key=f"{ad}_h_bayi")
            h_ek = hc3.number_input("Paketleme vb. gider (TL)", 0.0, 1000.0, _f(bilgi.get("h_ek_gider"), 0.0), 1.0, key=f"{ad}_h_ek")
            hd1, hd2, hd3 = st.columns(3)
            h_kom = hd1.number_input("Komisyon % (KDV dahil)", 0.0, 60.0, _f(bilgi.get("h_komisyon"), 20.0), 0.5, key=f"{ad}_h_kom")
            h_kdv = hd2.number_input("Satış KDV %", 0.0, 40.0, _f(bilgi.get("h_kdv"), 20.0), 1.0, key=f"{ad}_h_kdv")
            h_ver = hd3.number_input("Kâr vergisi %", 0.0, 60.0, _f(bilgi.get("h_vergi"), 0.0), 1.0, key=f"{ad}_h_ver",
                                     help="Kâr üzerinden ödenecek gelir/kurumlar vergisi. Muhasebecinize sorun; 0 yazarsanız hesaba katılmaz.")
            hmev = kademe_temizle(bilgi.get("hedef_kademe")) or [list(r) for r in VARSAYILAN_HEDEF]
            htablo = pd.DataFrame([{"Alış fiyatı bu TL'ye kadar (boş = üstü hepsi)": r[0], "Hedef net kâr (TL)": r[1]} for r in hmev])
            hduz = st.data_editor(htablo, num_rows="dynamic", hide_index=True, key=f"{ad}_h_t")
            h_kad = kademe_temizle([[(None if r.iloc[0] != r.iloc[0] else r.iloc[0]), r.iloc[1]] for _, r in hduz.iterrows()])
            yeni_h = {"hedef_aktif": h_aktif, "h_kargo": h_kargo, "h_bayi_kargo": h_bayi, "h_ek_gider": h_ek,
                      "h_komisyon": h_kom, "h_kdv": h_kdv, "h_vergi": h_ver,
                      "hedef_kademe": h_kad or [list(r) for r in VARSAYILAN_HEDEF]}
            if any(bilgi.get(k) != v for k, v in yeni_h.items() if k != "hedef_kademe") or kademe_temizle(bilgi.get("hedef_kademe")) != kademe_temizle(yeni_h["hedef_kademe"]):
                eski_aktif = bool(bilgi.get("hedef_aktif"))
                bilgi.update(yeni_h)
                ayar_yaz(ayarlar)
                if h_aktif or eski_aktif:
                    n_f = fiyat_yeniden_hesapla(ad, bilgi)
                    st.success(f"Kaydedildi. {n_f:,} ürünün satış fiyatı yeniden hesaplandı. Pazar yerlerine göndermek için 'Tüm Stok/Fiyatları Güncelle'ye basın.")
                else:
                    st.success("Kaydedildi (hedef net kâr yöntemi kapalı).")
            ornek_alis = pd.Series([50.0, 100.0, 300.0, 1000.0, 5000.0, 20000.0])
            if bilgi.get("hedef_aktif"):
                ornek_satis = hedef_fiyat(ornek_alis, bilgi)
                yontem = "Hedef net kâr"
            else:
                ornek_marj = kademeli_marj(ornek_alis, bilgi.get("kademe") if bilgi.get("kademe_aktif") else None, _f(bilgi.get("marj"), 30.0))
                ornek_satis = (ornek_alis * (1 + ornek_marj / 100) + _f(bilgi.get("sabit_ek"))).round(2)
                yontem = "Şu anki marj/kargo"
            ornek_net = net_kar_hesapla(ornek_satis, ornek_alis, bilgi)
            st.caption(f"Örnek hesap ({yontem} yöntemi). Net kâr: komisyon, kargo, KDV ve vergi düşüldükten sonra kalan tutar.")
            st.dataframe(pd.DataFrame({"Alış (TL)": ornek_alis, "Satış (TL)": ornek_satis, "Net kâr (TL)": ornek_net}), hide_index=True)
            if (ornek_net < 0).any():
                st.error("Bazı alış fiyatlarında bu ayarla ZARAR ediyorsunuz (Net kâr negatif). Hedef net kâr yöntemini açın ya da marjı artırın.")

            if gen(st.button, "💲 Fiyatları şimdi yeniden hesapla", key=f"{ad}_fiyat_hesapla",
                   help="Kayıtlı alış fiyatlarından, yukarıdaki güncel marj/kargo/kademe ile satış fiyatlarını yeniden hesaplar. XML indirmez, hızlıdır."):
                n_f = fiyat_yeniden_hesapla(ad, bilgi)
                st.success(f"{n_f:,} ürünün satış fiyatı güncel ayarla yeniden hesaplandı. Pazar yerlerine göndermek için pazar yerinin işlemler sayfasında 'Tüm Stok/Fiyatları Güncelle'ye basın.")


def ayarlari_geri_yukle(veri_y):
    if not isinstance(veri_y, dict):
        raise ValueError("Dosya bir JSON nesnesi olmalı.")
    for k in VARSAYILAN:  # yalnızca bilinen alanlar geri yüklenir
        if k == "kimlik" and isinstance(veri_y.get(k), dict):
            for ka in KIMLIK_ALANLARI:
                if isinstance(veri_y[k].get(ka), str) and veri_y[k][ka].strip():
                    ayarlar["kimlik"][ka] = veri_y[k][ka]
        elif k in veri_y and isinstance(veri_y[k], type(VARSAYILAN[k])):
            ayarlar[k] = veri_y[k]
    ayar_yaz(ayarlar)


def yedek_isaretle():
    ayarlar["son_yedek"] = simdi_tr().strftime("%Y-%m-%d %H:%M")
    ayar_yaz(ayarlar)


def fiyat_sistemi_paneli():
    st.subheader("💰 Fiyatlandırma (tüm pazar yerleri)")
    fs = dict(FIYAT_VARSAYILAN, **(ayarlar.get("fiyat_sistemi") or {}))
    st.caption("Satış fiyatı = (alış + sabit gider + net kâr) ÷ (1 − komisyon). Net kâr, kargo, komisyon ve diğer masraflar çıktıktan sonra cebinde kalan paradır. "
               "Alış fiyatı belirli bir sınıra kadar yüzde ile, sınırın üstünde aşağıdaki tablodaki net kâr ile hesaplanır; tablodaki noktaların arası otomatik doldurulur. "
               "Açıkken tüm pazarlara bu hesapla fiyat gider.")
    aktif = st.checkbox("Bu fiyat sistemini kullan", value=bool(fs.get("aktif")), key="fs_aktif")
    c1, c2, c3 = st.columns(3)
    gider = c1.number_input("Sabit gider ₺ (kargo + diğer masraflar)", 0.0, 3000.0, _f(fs.get("gider"), 140.0), 5.0, key="fs_gider")
    yuzde = c2.number_input("Net kâr % (alış fiyatının)", 0.0, 300.0, _f(fs.get("net_kar_yuzde"), 30.0), 1.0, key="fs_yuzde")
    siniri = c3.number_input("Yüzde şu alış fiyatına kadar geçerli ₺", 1.0, 100000.0, _f(fs.get("yuzde_siniri"), 1000.0), 100.0, key="fs_sinir")
    st.markdown(f"**{siniri:,.0f} ₺ üstündeki ürünler için net kâr tablosu** (alış fiyatı → cebe kalacak net kâr; satır ekleyip silebilirsin)")
    tb = pd.DataFrame(ust_kademe_temizle(fs.get("ust_kademe")) or UST_KADEME_VARSAYILAN, columns=["Alış fiyatı ₺", "Net kâr ₺"])
    tb = st.data_editor(tb, num_rows="dynamic", hide_index=True, key="fs_ust", use_container_width=True)
    ust_k = ust_kademe_temizle(tb.values.tolist())
    st.markdown("**Tedarikçiye göre net kâr %** (boş bırakılan genel yüzdeyi kullanır)")
    ted_ad = sorted((ayarlar.get("tedarikciler") or {}).keys())
    yz_eski = fs.get("tedarikci_yuzde") or {}
    td = st.data_editor(pd.DataFrame({"Tedarikçi": ted_ad, "Net kâr %": [(_f(yz_eski[t]) if t in yz_eski else None) for t in ted_ad]}),
                        hide_index=True, disabled=["Tedarikçi"], key="fs_ted", use_container_width=True)
    st.markdown("**Pazar yerine göre komisyon** (kampanya olan pazarda kâr çarpanını düşür; 100 = olduğu gibi)")
    pz_eski = fs.get("pazar") or {}
    pids = list(PAZAR.keys())
    pd_ = st.data_editor(pd.DataFrame({"Pazar": [PAZAR_AD.get(p_, p_) for p_ in pids],
                                       "Komisyon %": [_f((pz_eski.get(p_) or {}).get("komisyon"), 25.0 if p_ == "ptt" else 20.0) for p_ in pids],
                                       "Kâr çarpanı %": [_f((pz_eski.get(p_) or {}).get("carpan"), 100.0) for p_ in pids]}),
                         hide_index=True, disabled=["Pazar"], key="fs_pazar", use_container_width=True)
    yeni = {"aktif": aktif, "gider": gider, "net_kar_yuzde": yuzde, "yuzde_siniri": siniri, "ust_kademe": ust_k,
            "tedarikci_yuzde": {str(r["Tedarikçi"]): float(r["Net kâr %"]) for _, r in td.iterrows() if pd.notna(r["Net kâr %"])},
            "pazar": {p_: {"komisyon": float(pd_.iloc[i]["Komisyon %"]), "carpan": float(pd_.iloc[i]["Kâr çarpanı %"])} for i, p_ in enumerate(pids)}}
    st.markdown("**Hesap tablosu** (seçtiğin pazar için; kaydetmeden önce kontrol et)")
    sec_p = st.selectbox("Pazar", pids, format_func=lambda x: PAZAR_AD.get(x, x), key="fs_ornek_pazar")
    ornek = sorted(set([50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000] + [int(r[0]) for r in ust_k] + [1500, 2500]))
    sat, net = fiyat_sistemi_hesapla(ornek, None, sec_p, yeni)
    kom_oran = _f(((yeni["pazar"].get(sec_p)) or {}).get("komisyon"), 20.0)
    st.dataframe(pd.DataFrame({"Alış ₺": ornek, "Net kâr ₺": net.round(0).values, "Kargo+gider ₺": [gider] * len(ornek),
                               "Komisyon ₺": (sat * kom_oran / 100).round(0).values, "Satış ₺": sat.values,
                               "Satış / alış": (sat / pd.Series(ornek, dtype=float)).round(2).values}), hide_index=True)
    zk = st.checkbox("🛡️ Zarar koruması: satış fiyatı alış (bayi) fiyatına yakın ya da altındaysa o ürünün stoğunu 0 gönder",
                     value=bool(ayarlar.get("zarar_korumasi", True)), key="fs_zarar")
    if st.button("💾 Fiyat sistemini kaydet", key="fs_kaydet", type="primary"):
        ayarlar["fiyat_sistemi"] = yeni
        ayarlar["zarar_korumasi"] = bool(zk)
        ayar_yaz(ayarlar)
        kv_yaz("fiyat_sistemi_yedek", yeni)
        st.success("Kaydedildi. Aşağıdaki düğmeyle tüm pazarlara hemen gönderebilirsin.")
    toplu_stok_fiyat_paneli("fiyat")
    st.divider()


def genel_ayarlar(sifre):
    fiyat_sistemi_paneli()
    st.subheader("🔔 Bildirim (Telegram)")
    st.caption("Stoksuz satış riski, şüpheli XML ve siparişte stok sorunu için telefona anında haber verir. Telegram'da @BotFather ile bot "
               "oluşturup token'ı, bota bir mesaj atıp chat ID'nizi girin. Alternatif: TELEGRAM_TOKEN ve TELEGRAM_CHAT ortam değişkenleri.")
    with st.form("telegram_form"):
        tk_ = st.text_input("Bot token", value=ayarlar["kimlik"].get("telegram_token", ""), type="password")
        ch_ = st.text_input("Chat ID", value=ayarlar["kimlik"].get("telegram_chat", ""))
        if gen(st.form_submit_button, "💾 Kaydet", type="primary"):
            ayarlar["kimlik"]["telegram_token"] = tk_.strip()
            ayarlar["kimlik"]["telegram_chat"] = ch_.strip()
            ayar_yaz(ayarlar)
            st.success("Kaydedildi.")
    if gen(st.button, "📨 Test bildirimi gönder", key="tg_test"):
        if bildir("Test bildirimi: ŞahEntegre bildirimleri çalışıyor."):
            st.success("Gönderildi.")
        else:
            st.error("Gönderilemedi. Token ve Chat ID'yi kontrol edin (önce bota bir mesaj atmış olmalısınız).")
    st.divider()
    st.subheader("🚫 Kara liste")
    st.caption("Her satıra bir kelime. Adı, kategorisi veya barkodu bu kelimeyi içeren ürünler yeni ürün olarak HİÇBİR pazara gönderilmez; "
               "pazarda zaten varsa stok/fiyat güncellemesinde stoğu 0 yapılır (satıştan kalkar).")
    kl = st.text_area("Yasaklı kelimeler", value=str(ayarlar.get("kara_liste", "") or ""), height=120, key="kara_liste_alan")
    if gen(st.button, "💾 Kara listeyi kaydet", key="kara_kaydet"):
        ayarlar["kara_liste"] = kl
        ayar_yaz(ayarlar)
        st.success("Kara liste kaydedildi.")
    st.divider()

    st.subheader("💾 Yedekleme")
    if ayarlar.get("son_yedek"):
        st.caption(f"Son indirilen yedek: {ayarlar['son_yedek']}")
    else:
        st.warning("Henüz yedek almadınız. Sunucu yeniden başlarsa ayarlarınız/anahtarlarınız silinebilir; yedek indirip güvenli bir yerde saklayın.")
    st.markdown("**🔐 Şifreli TAM yedek (API anahtarları, tedarikçiler, kategori eşleştirmeleri, tüm ayarlar)**")
    try:
        import cryptography  # noqa: F401
        sifreleme_var = True
    except ImportError:
        sifreleme_var = False
        st.error("Şifreli yedek için 'cryptography' paketi gerekli (requirements.txt içinde var; sunucuyu yeniden başlatın).")
    if sifreleme_var:
        p1 = st.text_input("Yedek parolası (en az 8 karakter)", type="password", key="yedek_p1")
        p2 = st.text_input("Yedek parolası (tekrar)", type="password", key="yedek_p2")
        if p1 and (len(p1) < 8 or p1 != p2):
            st.info("Parola en az 8 karakter olmalı ve iki alan aynı olmalı.")
        elif p1:
            st.download_button("⬇️ Şifreli yedeği indir", yedek_sifrele(ayarlar, p1),
                               f"sahentegre_sifreli_yedek_{simdi_tr():%Y%m%d}.json", "application/json",
                               on_click=yedek_isaretle)
            st.caption("Parolayı kaybederseniz yedek açılamaz; parola bu dosyada saklanmaz.")
    guvenli = {k: v for k, v in ayarlar.items() if k != "kimlik"}
    guvenli["kimlik"] = {}
    st.download_button("📄 Yedek (API anahtarları HARİÇ, şifresiz)", json.dumps(guvenli, ensure_ascii=False, indent=2).encode("utf-8"),
                       "sahentegre_yedek.json", "application/json")

    yuklenen = st.file_uploader("♻️ Yedek dosyasını geri yükle (.json — şifreli veya düz)", type="json", key="yedek_yukle")
    geri_parola = st.text_input("Şifreli yedekse parolası", type="password", key="yedek_geri_parola")
    if yuklenen is not None and st.button("Geri Yükle", key="yedek_btn"):
        try:
            ham = yuklenen.getvalue()
            veri_y = json.loads(ham.decode("utf-8"))
            if isinstance(veri_y, dict) and veri_y.get("sahentegre_yedek"):
                if not geri_parola:
                    raise ValueError("Bu yedek şifreli; parolayı girin.")
                veri_y = yedek_coz(ham, geri_parola)
            ayarlari_geri_yukle(veri_y)
            st.success("Geri yüklendi.")
            st.rerun()
        except Exception as e:
            st.error(f"Hata: {e}")


def gunluk_sayfasi():
    with closing(baglan()) as c:
        lg = pd.read_sql("SELECT zaman, tedarikci, durum, mesaj FROM senkron_log ORDER BY id DESC LIMIT 200", c)
    if lg.empty:
        st.info("Kayıt yok.")
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
            ekle("görseli yok")
        elif not str(r.get("gorsel", "")).strip().lower().startswith("http"):
            ekle("görsel adresi geçersiz (http/https değil)")
        if _f(r.get("satis_fiyati")) <= 0:
            ekle("fiyatı 0")
        cat = kat_sec(pa, ayarlar, r.get("kategori"), pid)
        if not cat:
            ekle("kategorisi eşleştirilmemiş (varsayılan kategori kapalı)")
        elif pid == "trendruum" and not objectid_mi(cat):
            ekle("kategori ID geçersiz (24 karakter olmalı)")
        if pid == "trendruum":
            _b = tedarikci_marka(ayarlar, r.get("tedarikci"), "trendruum", "brand_id", trendruum_ayar(ayarlar)[0])
            if not objectid_mi(_b) and not objectid_mi(trendruum_ayar(ayarlar)[0]):
                ekle("marka ID geçersiz/boş")
            if not sabit_barkod(str(r.get("barkod", "")).strip(), trendruum_ayar(ayarlar)[2]):
                ekle("barkodu yok (geçici barkod kapalı)")
    return ", ".join(f"{k}: {v}" for k, v in say.items())


def ilk_gonderilebilir(df, pid, uretici, en_fazla=500):
    """Test modunda listenin ilk degil, gonderilebilen ilk urununu bulur."""
    for i in range(min(len(df), en_fazla)):
        satir = df.iloc[[i]]
        liste, _ = uretici(satir, ayarlar)
        if liste:
            return satir, i
    return None, -1


def kategori_secimi_uygula(pid, df, varsayilan_isaret=True):
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
        st.caption(f"{len(eslesmeyen)} kategori ({int(adet[eslesmeyen].sum())} ürün) pazar yeri kategorisine eşleştirilmediği için listede yok ve gönderilmez.")
    if not gosterilen:
        st.warning("Eşleştirilmiş kategori yok. Genel Ayarlar > Kategori eşleştirme bölümünden eşleştirin.")
        return df.iloc[0:0]
    st.markdown("**Gönderilecek kategoriler**")
    tumu = st.checkbox("Tüm kategorileri işaretle", value=varsayilan_isaret, key=f"{pid}_kat_tumu_{varsayilan_isaret}")
    tablo = pd.DataFrame({
        "Gönder": [bool(tumu)] * len(gosterilen),
        "Kategori": gosterilen,
        "Ürün": [int(adet[k]) for k in gosterilen],
        "Eşleşme": ["Kayıtlı" if esl.get(k) else "Varsayılan" for k in gosterilen],
    })
    duz = st.data_editor(tablo, hide_index=True, height=min(420, 40 + 35 * len(tablo)),
                         disabled=["Kategori", "Ürün", "Eşleşme"], key=f"{pid}_kat_ed_{bool(tumu)}")
    secilen = set(duz.loc[duz["Gönder"], "Kategori"])
    st.caption(f"{len(secilen)}/{len(gosterilen)} kategori işaretli. Yalnızca işaretlenenler gönderilir.")
    if not secilen:
        st.info("Göndermek istediğiniz kategorilerin 'Gönder' kutusunu işaretleyin.")
    return df[ana.isin(secilen).values]


def toplu_urun_paneli(pid):
    """Ürün OLUŞTURMA (N11, İdefix, Trendruum)."""
    ad = PAZAR_AD[pid]
    if not pazar_bagli(ayarlar, pid):
        st.warning(f"{ad} API bilgileri eksik. 'Genel Ayarları' sayfasından girin.")
        return
    st.info("Marka/kategori/KDV ayarları ve kategori eşleştirmesi için 'Genel Ayarları' sayfasını kullanın.")
    df = secili_urunler(urunleri_oku(), pid)
    huni = [("Seçili tedarikçilerdeki ürün", len(df))]
    if not df.empty and st.checkbox("Sadece stokta olanlar", value=True, key=f"{pid}_stoklu"):
        df = df[df["stok"] > 0]
        huni.append(("Stoğu olanlar ('Sadece stokta olanlar' açık)", len(df)))
    kara = kara_liste_maskesi(ayarlar, df)
    if kara.any():
        st.caption(f"🚫 Kara listedeki {int(kara.sum())} ürün gönderim dışı bırakıldı.")
        df = df[~kara]
        huni.append(("Kara liste dışında kalanlar", len(df)))
    mod = st.selectbox("Gönderim Modu", ["Tek ürün (Test)", "Kategori seç", "Tüm Ürünler"], key=f"{pid}_mod",
                       help="Kategori seç: yalnızca işaretlediğiniz kategorilerdeki ürünler gönderilir. Tüm Ürünler: kategorisi eşleşmiş bütün ürünler.")
    if mod.startswith("Kategori"):
        df = kategori_secimi_uygula(pid, df, varsayilan_isaret=False)
    huni.append(("İşaretli kategorilerdeki ürün" if mod.startswith("Kategori") else "Kategori seçimi sonrası", len(df)))
    df = fiyat_artis_uygula(ayarlar, pid, df)
    if not df.empty and "alis_fiyati" in df.columns:  # ZARAR KORUMASI (ürün oluşturma): fiyatı alışa yakın/altında olan ürün asla yüklenmesin
        _zarar = (df["alis_fiyati"].map(_f) > 0) & (df["satis_fiyati"].map(_f) <= df["alis_fiyati"].map(_f) * 1.15)
        if _zarar.any():
            st.error(f"🛡️ {int(_zarar.sum())} ürünün hesaplanan fiyatı alış fiyatına çok yakın/altında; zarar etmemek için bu ürünler gönderim listesinden ÇIKARILDI. "
                     "Genel Ayarlar > Fiyatlandırma'yı açıp kaydedin.")
            df = df[~_zarar]
            huni.append(("Zarar koruması sonrası", len(df)))
    if not mod.startswith("Tek") and not df.empty:
        gonderildi_ = {str(x) for x in (kv_oku(f"olusturuldu:{pid}", []) or [])}
        onek_ = str(pa_al(ayarlar, "hb").get("sku_prefix", "") or "") if pid == "hb" else ""
        if onek_:
            gonderildi_ |= {k[len(onek_):] for k in gonderildi_ if k.startswith(onek_)}
        with st.expander("🛠️ Daha önce gönderdiklerimi sisteme tanıt (tek seferlik)"):
            st.caption("Bu özellikten önce gönderdiğin ürünler kayıtlı değil. Pazar yeri ilk N ürünü almışsa (ör. N11'de ilk ~6.000), listenin ilk N ürününü 'gönderilmiş' sayabilirsin. "
                       "Sayıyı pazar yeri panelindeki ürün sayısına göre tahmin et; fazla yazarsan o ürünler atlanır, az yazarsan birkaç ürün tekrar gönderilir (zararsız).")
            n_say = st.number_input("Listenin ilk kaç ürününü gönderilmiş sayayım?", min_value=0, value=0, step=500, key=f"{pid}_say_n")
            if st.button("Gönderilmiş say", key=f"{pid}_say_btn") and n_say > 0:
                ilk_ = {str(b_) for b_ in df["barkod"].astype(str).head(int(n_say))}
                kv_yaz(f"olusturuldu:{pid}", sorted(gonderildi_ | ilk_))
                st.success(f"{len(ilk_):,} ürün gönderilmiş sayıldı. Sayfayı yenileyince listeden düşer.")
                st.rerun()
        onceki_ = int(df["barkod"].astype(str).isin(gonderildi_).sum())
        atla_ = st.checkbox(f"⏭️ Daha önce {ad}'e başarıyla gönderilenleri atla (kaldığın yerden devam et)", value=True, key=f"{pid}_atla",
                            help="Limit yüzünden yarım kalan gönderimi tekrar başlatınca ilk ürünleri yeniden göndermez; sadece henüz gönderilmeyenleri gönderir.")
        if atla_ and onceki_:
            df = df[~df["barkod"].astype(str).isin(gonderildi_)]
            huni.append(("Daha önce gönderilenler çıkarıldıktan sonra kalan", len(df)))
            st.caption(f"✅ Daha önce gönderilmiş {onceki_:,} ürün atlandı. Gönderilmeyi bekleyen: **{len(df):,}**")
        limit_ = st.number_input("Bu seferde en fazla kaç ürün gönderilsin? (0 = hepsi)", min_value=0, value=0, step=500, key=f"{pid}_limit",
                                 help="Pazar yerinin saatlik/günlük limiti varsa buraya limite uygun bir sayı yazın (ör. 4000). Kalanlar sonraki gönderimde devam eder.")
        if limit_ and len(df) > int(limit_):
            st.caption(f"Bu seferde ilk {int(limit_):,} ürün gönderilecek; kalan {len(df) - int(limit_):,} ürün sonraki gönderimde.")
            df = df.head(int(limit_))
            huni.append(("Bu seferki limit sonrası", len(df)))
    uretici = {
        "n11": n11_urun_listesi, "idefix": idefix_urun_listesi, "trendruum": trendruum_urun_listesi,
        "ptt": ptt_urun_listesi, "hb": hb_urun_listesi,
    }[pid]
    if mod.startswith("Tek"):
        aranan = st.text_input("Test için ürün ara (ad veya barkod)", key=f"{pid}_tek_ara",
                               help="Örnek: ASUS ya da Depo2-006.NOTE.ASUS.B1-I5-3D. Boş bırakırsanız listenin ilk ürünü seçilir.")
        if aranan.strip():
            q = tr_norm(aranan.strip())
            eslesen = df[df["urun_adi"].map(tr_norm).str.contains(q, regex=False) | df["barkod"].astype(str).map(tr_norm).str.contains(q, regex=False)]
            if eslesen.empty:
                st.warning("Aramaya uyan ürün yok (stokta olmayanlar ve kara listedekiler listede olmaz).")
                return
            eslesen = eslesen.head(50)
            etiketler = [f"{r['urun_adi'][:70]} | {r['barkod']} | {r['satis_fiyati']:.2f} TL | stok {int(r['stok'])}" for _, r in eslesen.iterrows()]
            secim = st.selectbox(f"{len(eslesen)} ürün bulundu, birini seçin", range(len(etiketler)), format_func=lambda i: etiketler[i], key=f"{pid}_tek_sec")
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
                    st.caption(f"Listenin ilk {sira} ürünü gönderilemediği için gönderilebilen ilk ürün seçildi.")
            else:
                df = df.head(1)
    try:
        liste, atlanan = uretici(df, ayarlar)
    except ValueError as e:
        st.error(str(e))
        return
    st.write(f"Gönderilecek ürün: **{len(liste):,}** (Atlanan: {atlanan} — görsel/fiyat/barkod/kategori eksik)")
    huni.append(("Eksiksiz, gönderilebilir ürün", len(liste)))
    if not mod.startswith("Tek"):
        with st.expander(f"📉 Ürünler neden azalıyor? ({huni[0][1]:,} → {len(liste):,})", expanded=len(liste) < 0.9 * max(huni[0][1], 1)):
            for ad_, n_ in huni:
                st.write(f"• {ad_}: **{n_:,}**")
            st.caption("Her adımda sayı düşüyorsa nedeni o satırdadır: stoğu biten ürünler, işaretlenmeyen/eşleşmeyen kategoriler ve fiyatı, görseli ya da barkodu eksik ürünler gönderilmez.")
    if atlanan:
        neden = atlama_nedenleri(df, pid)
        if neden:
            st.caption("Atlanma nedenleri: " + neden)
        try:
            pa_ = pa_al(ayarlar, pid)
            eslesmeyen = df[df["kategori"].map(lambda k: not kat_sec(pa_, ayarlar, k, pid))]
            if len(eslesmeyen):
                ana_ = eslesmeyen["kategori"].astype(str).map(lambda k: k.split(">>>")[0].strip())
                tablo_ = ana_.value_counts().head(25).rename_axis("Eşleşmemiş ana kategori").reset_index(name="Ürün sayısı")
                with st.expander(f"🧩 Kategorisi eşleşmeyen {len(eslesmeyen):,} ürün ({ana_.nunique()} ana kategori) — önce bunları eşleştirin", expanded=True):
                    st.dataframe(tablo_, hide_index=True)
                    st.caption("Kategori eşleştirmesini 'Kategori eşleştirme' bölümünden bu kategoriler için yapın; en çok ürünü olandan başlayın.")
        except Exception:
            pass
    if not liste:
        if mod.startswith("Tek"):
            st.warning("Gönderilebilir ürün bulunamadı. Kategori eşleştirmesini yapın ya da Genel Ayarlar'da 'Eşleşmesi olmayan ürünleri de varsayılan kategoriye koy'u açıp tek ürünle deneyin.")
        return
    with st.expander("🔎 İlk ürünün gönderilecek JSON'u (pazar yeri dokümanıyla karşılaştırın)"):
        st.json(liste[0])
    onay = st.checkbox("Göndermeyi onaylıyorum", key=f"{pid}_onay")
    if gen(st.button, f"🚀 {ad}'e Ürünleri Gönder", type="primary", key=f"{pid}_toplu_btn", disabled=not onay):
        pbar, log_k = st.progress(0.0), st.empty()

        def ilerleme(p, loglar):
            pbar.progress(min(p, 1.0))
            kod_goster(log_k, "\n".join(loglar[-12:]))

        try:
            gonder = {"n11": n11_urun_gonder, "idefix": idefix_gonder, "trendruum": trendruum_gonder, "ptt": ptt_urun_gonder, "hb": hb_urun_gonder}[pid]
            SON_PAKET["ok"], SON_PAKET["hata"] = [], []
            ok, hata, loglar = gonder(ayarlar, liste, ilerleme)
            try:  # başarıyla iletilen ürünleri hatırla: sonraki gönderimde (limit nedeniyle yarım kaldıysa) atlanır
                onek_k = str(pa_al(ayarlar, "hb").get("sku_prefix", "") or "") if pid == "hb" else ""
                yeni_ok = {(k[len(onek_k):] if onek_k and str(k).startswith(onek_k) else str(k)) for k in SON_PAKET["ok"]}
                if yeni_ok:
                    kv_yaz(f"olusturuldu:{pid}", sorted({str(x) for x in (kv_oku(f"olusturuldu:{pid}", []) or [])} | yeni_ok))
            except Exception:
                pass
        except Exception as e:
            log_yaz(ad, "HATA", f"Ürün gönderimi: {e}")
            st.error(f"Hata: {e}")
            return
        dur = [x for x in loglar if x.startswith("⛔")]
        if dur:
            st.error(dur[0])
        log_yaz(ad, "OK" if hata == 0 else ("KISMİ" if ok else "HATA"), f"Ürün oluşturma: {ok} ürün iletildi, {hata} ürün hatalı.")
        (st.success if hata == 0 else st.warning)(f"{ok} ürün iletildi, {hata} ürün hatalı. (API kabulü = ürün onayı değildir; pazar yeri panelinden kontrol edin.)")
        if pid == "n11" and ok:
            son_g = (kv_oku("takip:n11", []) or [])[-1:]
            if son_g:
                st.info("N11 ürünleri hemen oluşturmaz. Birkaç dakika bekleyip aşağıdaki 'N11 görev sonucu' bölümünden sonucu getirin; reddedilen ürünlerin nedeni orada özetlenir.")


def pazar_ozet(pid):
    """Sistem kayitlarina gore pazar yeri ozeti (pazar yerinin canli sayimi degildir)."""
    with closing(baglan()) as c:
        d = pd.read_sql("SELECT barkod, durum, zaman FROM pazar_durum WHERE pazar=?", c, params=(pid,))
    if d.empty:
        st.caption("Bu pazar yerine henüz ürün gönderilmedi; gönderimden sonra burada durum özeti çıkacak.")
        return
    u = urunleri_oku()
    stok = u.groupby("barkod")["stok"].max() if not u.empty else pd.Series(dtype=int)
    m = d.copy()
    m["stok"] = m["barkod"].astype(str).map(stok)
    esik = _i(ayarlar.get("kritik_esik")) or 3
    ok = m[m["durum"] == "ok"]
    st.markdown("**📊 Durum özeti** (sistem kayıtlarına göre)")
    a, b, c3, d4, e5 = st.columns(5)
    a.metric("Gönderilen", f"{len(ok):,}")
    b.metric("Hatalı", f"{int((m['durum'] == 'hata').sum()):,}")
    c3.metric("Tükenen", f"{int((ok['stok'] == 0).sum()):,}")
    d4.metric(f"Az kalan (≤{esik})", f"{int(ok['stok'].between(1, esik).sum()):,}")
    e5.metric("Sistemde yok", f"{int(ok['stok'].isna().sum()):,}")
    son = ok["zaman"].max() if not ok.empty else None
    gonderilmeyen = max(int(u["barkod"].nunique()) - len(ok), 0) if not u.empty else 0
    st.caption(f"Son başarılı gönderim: {son or '-'} · Sistemde olup bu pazara hiç gitmeyen: {gonderilmeyen:,}")


def pazar_islemler(pid):
    p = PAZAR[pid]
    ad = p["ad"]
    bagli = pazar_bagli(ayarlar, pid)
    st.title(f"{p['ikon']} {ad} İşlemleri")
    if not bagli:
        st.warning("API bilgileri eksik: 'Genel Ayarları' sayfasından girip kaydedin.")
    pazar_ozet(pid)

    k = f"islem_{pid}"
    with closing(baglan()) as c:
        ted_liste = [r[0] for r in c.execute("SELECT DISTINCT tedarikci FROM urunler WHERE tedarikci IS NOT NULL ORDER BY 1")]
    secili_ted = None
    if ted_liste:
        secili_ted = st.multiselect("Stok/fiyat gönderilecek tedarikçiler", ted_liste, default=ted_liste, key=f"{pid}_gond_ted")
    c1, c2, c3 = st.columns(3)
    if gen(c1.button, "🔄 Tam Senkronizasyon", key=f"b1_{pid}", type="primary", disabled=not bagli, help="Önce tedarikçi XML'lerini yeniler, sonra stok/fiyatı bu pazara gönderir."):
        st.session_state[k] = None
        with st.spinner("Tedarikçiler güncelleniyor..."):
            for tad, ok_, msg in tumunu_senkronla(oto=False):
                (st.success if ok_ else st.error)(f"{tad}: {msg}")
        gonder_ve_goster(pid, secili_ted)
    if gen(c2.button, "⚠️ Kritik Stok Sıfırla", key=f"b2_{pid}"):
        st.session_state[k] = "kritik"
    if gen(c3.button, "🔢 Tüm Stok/Fiyatları Güncelle", key=f"b3_{pid}", disabled=not bagli, help="Veritabanındaki mevcut stok/fiyatı bu pazara gönderir."):
        st.session_state[k] = None
        gonder_ve_goster(pid, secili_ted)

    if pid in ("n11", "idefix", "trendruum", "ptt", "hb"):
        if gen(st.button, "📤 Toplu Ürün Oluştur / Gönder", key=f"b4_{pid}"):
            st.session_state[k] = "toplu"
    if bagli and pid in GUNCELLEYICI:
        y_liste = pazar_yetim_barkodlar(ayarlar, pid)
        if y_liste:
            st.warning(f"Tedarikçi listesinde artık olmayan {len(y_liste):,} ürün {PAZAR_AD.get(pid, pid)}'da eski stokla satışta kalmış olabilir.")
            with st.expander("Bu ürünlerin barkodları (kontrol edin)"):
                st.dataframe(pd.DataFrame({"Barkod": y_liste[:500]}), hide_index=True)
            y_onay = st.checkbox("Bu ürünlerin tedarikçide artık olmadığını kontrol ettim", key=f"yetim_onay_{pid}")
            if gen(st.button, f"🧹 Bu {len(y_liste):,} ürünün stoğunu {PAZAR_AD.get(pid, pid)}'da 0'la", key=f"yetim_{pid}", disabled=not y_onay):
                y_ok, y_hata, _ = pazar_yetim_sifirla(ayarlar, pid)
                (st.success if y_hata == 0 else st.warning)(f"{y_ok} ürünün stoğu 0'landı, {y_hata} hata.")

    islem = st.session_state.get(k)
    if islem == "kritik":
        with st.container(border=True):
            esik = st.number_input("Kritik stok eşiği", 1, 50, _i(ayarlar.get("kritik_esik")) or 3, key=f"ke_{pid}")
            with closing(baglan()) as c:
                df_k = pd.read_sql(
                    "SELECT barkod, stok, satis_fiyati FROM urunler WHERE CAST(stok AS INTEGER) > 0 AND CAST(stok AS INTEGER) <= ?",
                    c, params=(int(esik),))
            st.write(f"Etkilenecek ürün: **{len(df_k):,}**")
            st.caption("Not: Veritabanındaki stoklar da 0'lanır; bir sonraki tedarikçi senkronizasyonunda tedarikçi stoğuna göre yeniden hesaplanır.")
            onay = st.checkbox("Onaylıyorum", key=f"ko_{pid}")
            if st.button("Sıfırla ve Gönder", key=f"kg_{pid}", disabled=not (onay and bagli and len(df_k) > 0)):
                try:
                    df_k["barkod"] = df_k["barkod"].astype(str)
                    df_k["stok"] = 0
                    ok, hata, _ = pazara_gonder(ayarlar, pid, df_k)
                    if ok > 0:  # önce pazara gitsin; başarısızsa veritabanını değiştirme
                        with closing(baglan()) as c:
                            c.execute("UPDATE urunler SET stok = 0 WHERE CAST(stok AS INTEGER) > 0 AND CAST(stok AS INTEGER) <= ?", (int(esik),))
                            c.commit()
                    (st.success if hata == 0 else st.warning)(f"{ok} ürün sıfırlandı, {hata} hata.")
                except Exception as e:
                    st.error(f"Hata: {e}")
    elif islem == "toplu":
        toplu_urun_paneli(pid)

    if pid == "hb" and bagli:
        with st.expander("📋 Hepsiburada ürün yükleme sonucu (ürünler neden düşmüyor?)", expanded=True):
            st.caption("Hepsiburada dosyayı kabul etse bile ürünleri sonradan işler ve hatalı olanları reddeder. Neden düşmediği burada yazar. "
                       "Ayrıca yeni ürünler Hepsiburada'da katalog onayından geçer; Satıcı Paneli > Ürünler / Katalog'da 'onay bekleyen' bölümüne de bakın.")
            kayitli_hb = list(reversed(kv_oku("takip:hb", []) or []))
            sec_hb = st.selectbox("Son yüklemelerin izleme kodları", [""] + kayitli_hb, key="hb_takip_sec")
            elle_hb = st.text_input("veya izleme kodu yapıştırın", key="hb_takip_elle")
            if gen(st.button, "🔎 Sonucu getir", key="hb_takip_btn"):
                hb_sonuc_goster(ayarlar, (elle_hb or sec_hb))
            st.markdown("**Toplu özet:** son yüklemelerin hepsini tarar; kaç ürün başarılı, kaç ürün neden reddedilmiş gösterir.")
            adet_hb = st.number_input("Kaç yükleme taransın?", 1, 60, 15, key="hb_toplu_adet")
            if st.button("📊 Toplu özeti çıkar", key="hb_toplu_ozet_dugme"):
                pb_ = st.progress(0.0)
                try:
                    st.session_state["hb_toplu_sonuc"] = hb_toplu_ozet(ayarlar, int(adet_hb), ilerleme=lambda p: pb_.progress(min(p, 1.0)))
                except Exception as e:
                    st.session_state["hb_toplu_sonuc"] = None
                    st.error(f"Hata: {e}")
            ts_ = st.session_state.get("hb_toplu_sonuc")
            if ts_:
                st.write(f"{ts_['kod']} yükleme, {ts_['sayfa']} sayfa, **{ts_['urun']:,}** ürün kaydı tarandı.")
                if ts_["durum"]:
                    st.write("Durumlar: " + ", ".join(f"**{k}**: {n:,}" for k, n in ts_["durum"].most_common()))
                if ts_["mesaj"]:
                    st.dataframe(pd.DataFrame([{"Neden": m, "Adet": n, "Örnek SKU": ts_["ornek"].get(m, "")} for m, n in ts_["mesaj"].most_common(15)]), hide_index=True)
                if ts_.get("ham"):
                    sec_neden = st.selectbox("Bir nedenin örnek kaydını (ham) göster", list(ts_["ham"].keys()), key="hb_ham_neden")
                    st.json(ts_["ham"].get(sec_neden))
                if ts_["var_olan"]:
                    st.info(f"{len(ts_['var_olan']):,} ürün Hepsiburada'da zaten katalogla eşleşmiş ya da katalog işleminde. "
                            "Bu ürünler tekrar 'ürün oluştur' ile yüklenemez (hata: 'Can not update product in matched or in catalog progress status'). "
                            "Bunlar için ürün oluşturmayı bırakıp fiyat/stok güncellemesini kullanın.")
    if pid == "n11" and bagli:
        with st.expander("📋 N11 görev sonucu (ürün gönderimi neden görünmüyor?)"):
            st.caption("N11 ürünleri hemen oluşturmaz; önce görev sırasına alır. Hata varsa burada görünür. "
                       "(Bu sorgu N11'in 'task-details' servisini kullanır; yanıt beklenmedikse ham yanıtı bana gönderin.)")
            kayitli_ = list(reversed(kv_oku("takip:n11", []) or []))
            sec_ = st.selectbox("Son gönderimlerin görev numaraları", [""] + kayitli_, key="n11_takip_sec")
            elle_ = st.text_input("veya görev no yazın", key="n11_takip_elle")
            if gen(st.button, "🔎 Sonucu getir", key="n11_takip_btn"):
                n11_gorev_ozet_goster(ayarlar, (elle_ or sec_))
    if pid == "idefix" and bagli:
        with st.expander("📋 İdefix gönderim sonucunu sorgula (batchRequestId)", expanded=True):
            st.caption("İdefix ürün oluşturmayı hemen yapmaz; ürün önce havuza alınır. Neden görünmediğini bu sonuç söyler.")
            kayitli = list(reversed(ayarlar.get("idefix_takip") or []))
            sec = st.selectbox("Son gönderimlerin batchRequestId'leri", [""] + kayitli, key="idefix_takip_sec")
            elle = st.text_input("veya batchRequestId yapıştırın", key="idefix_takip_elle")
            if gen(st.button, "🔎 Sonucu getir", key="idefix_takip_btn"):
                try:
                    bid = (elle or sec).strip()
                    if not bid:
                        raise ValueError("Bir batchRequestId seçin ya da yapıştırın.")
                    kod, j, ham = idefix_batch_sorgula(ayarlar, bid)
                    st.session_state["idefix_sonuc"] = (bid, kod, j, ham)
                except Exception as e:
                    st.session_state["idefix_sonuc"] = None
                    st.error(f"Hata: {e}")
            gs = st.session_state.get("idefix_sonuc")
            if gs:
                bid, kod, j, ham = gs
                (st.success if kod == 200 else st.error)(f"HTTP {kod} (batch {bid})")
                oz = idefix_sonuc_ozet(j)
                if oz["ust"]:
                    st.write(f"Batch durumu: **{oz['ust']}**")
                if oz["sayim"]:
                    st.write(", ".join(f"{k}: {n}" for k, n in oz["sayim"].items()))
                if oz["satirlar"]:
                    st.dataframe(pd.DataFrame(oz["satirlar"]).drop(columns=["_durum"]), hide_index=True)
                    bekleyen = [r["Barkod"] for r in oz["satirlar"] if r["_durum"] == "waiting_vendor_approve" and r["Barkod"]]
                    if bekleyen:
                        st.warning(f"{len(bekleyen)} ürün İdefix kataloğunda zaten var ve onayınızı bekliyor. Onaylamadan önce eşleşen ürünün doğru olduğunu İdefix panelinden kontrol edin.")
                        onay_a = st.checkbox("Eşleşmeleri kontrol ettim, bu ürünleri onaylıyorum", key="idefix_onay_cb")
                        if gen(st.button, f"✅ Bekleyen {len(bekleyen)} ürünü onayla", key="idefix_onay_btn", disabled=not onay_a):
                            ok_k, hata_k, lg = idefix_onayla(ayarlar, bekleyen)
                            log_yaz("İdefix", "OK" if not hata_k else "KISMİ", f"Ürün onayı: {len(ok_k)} onaylandı, {len(hata_k)} hata.")
                            (st.success if not hata_k else st.warning)(f"{len(ok_k)} ürün onaylandı, {len(hata_k)} hata. " + " ".join(lg[-2:]))
                with st.expander("Ham yanıt"):
                    st.code(ham)

    if pid == "ptt" and bagli:
        with st.expander("📋 PTT gönderim sonucunu sorgula (trackingId)"):
            kayitli = list(ayarlar.get("ptt_takip") or [])
            sec = st.selectbox("Son gönderimlerin trackingId'leri", [""] + kayitli, key="ptt_takip_sec")
            elle = st.text_input("veya trackingId yapıştırın", key="ptt_takip_elle")
            if gen(st.button, "🔎 Sonucu getir", key="ptt_takip_btn"):
                try:
                    kod, metin_ = ptt_sonuc_sorgula(ayarlar, elle or sec)
                    (st.success if kod == 200 else st.error)(f"HTTP {kod}")
                    oz = ptt_sonuc_ozet(metin_)
                    if oz:
                        st.write(oz["ozet"])
                        if oz["satirlar"]:
                            st.dataframe(pd.DataFrame(oz["satirlar"]), hide_index=True)
                    with st.expander("Ham yanıt"):
                        st.code(metin_)
                except Exception as e:
                    st.error(f"Hata: {e}")

    with closing(baglan()) as c:
        d = pd.read_sql("SELECT durum, COUNT(*) AS adet FROM pazar_durum WHERE pazar=? GROUP BY durum", c, params=(pid,))
    if not d.empty:
        st.caption("Son gönderim durumu (barkod bazında): " + ", ".join(f"{r.durum}: {r.adet}" for r in d.itertuples()))


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
                st.warning("Hiç tedarikçi seçilmedi.")
                return
            df_g = df_g[df_g["tedarikci"].isin(tedarikciler)]
        with st.spinner(f"{ad} stok/fiyat gönderiliyor..."):
            ok, hata, _ = pazara_gonder(ayarlar, pid, df_g, ilerleme)
        if ok == 0 and hata == 0:
            st.warning("Gönderilecek ürün bulunamadı (önce tedarikçi senkronizasyonu yapın / fiyatı olmayan ürünler atlanır).")
        else:
            (st.success if hata == 0 else st.warning)(f"{ad}: {ok} ürün iletildi, {hata} hata. (API kabulü = pazar yerinde işlendi demek değildir.)")
    except Exception as e:
        st.error(f"Hata: {e}")


def toplu_stok_fiyat_paneli(anahtar):
    """Tüm (ya da seçili) pazar yerlerine stok + fiyatı tek düğmeyle gönderir."""
    with st.container(border=True):
        st.markdown("### 🚀 Tüm pazarlara stok + fiyat gönder")
        bagli = [p_ for p_ in GUNCELLEYICI if pazar_bagli(ayarlar, p_)]
        if not bagli:
            st.info("Bağlı pazar yeri yok.")
            return
        if not fiyat_sistemi(ayarlar):
            st.warning("⚠️ Fiyat sistemi KAPALI: pazarlara tedarikçideki satış fiyatı gider (marj 0 ise alış fiyatı!). "
                       "Önce Genel & Yedek > Fiyatlandırma'yı aç ve kaydet.")
        sec = st.multiselect("Hangi pazarlara gönderilsin?", bagli, default=bagli, format_func=lambda x: PAZAR_AD.get(x, x), key=f"tp_sec_{anahtar}")
        yenile = st.checkbox("Önce tedarikçi XML'lerini yenile (daha uzun sürer)", value=False, key=f"tp_yenile_{anahtar}")
        onay = st.checkbox("Onaylıyorum: seçili pazarlardaki tüm ürünlerin stok ve fiyatı güncellenecek", key=f"tp_onay_{anahtar}")
        if st.button("🚀 Hepsini gönder", key=f"tp_btn_{anahtar}", type="primary", disabled=not (onay and sec)):
            if yenile:
                with st.spinner("Tedarikçiler güncelleniyor..."):
                    for tad, ok_, msg in tumunu_senkronla(oto=False):
                        (st.success if ok_ else st.error)(f"{tad}: {msg}")
            for p_ in sec:
                st.markdown(f"**{PAZAR_AD.get(p_, p_)}**")
                gonder_ve_goster(p_)
            st.info("Bitti. Sonuçlar Senkron Günlüğü'ne de yazıldı.")


def pazar_ayar(pid):
    p = PAZAR[pid]
    st.title(f"⚙️ {p['ad']} Genel Ayarları")
    st.subheader("🔑 API Kimlik Bilgileri")
    with st.form(f"kimlik_form_{pid}"):
        yeni = {}
        for etk, anahtar, parola in PAZAR_KIMLIK[pid]:
            yeni[anahtar] = st.text_input(etk, value=ayarlar["kimlik"].get(anahtar, ""), type="password" if parola else "default")
        if gen(st.form_submit_button, "💾 Kimlik bilgilerini kaydet", type="primary"):
            for a, v in yeni.items():
                ayarlar["kimlik"][a] = v.strip()
            ayar_yaz(ayarlar)
            st.success("Kaydedildi.")
    st.caption("Güvenlik için anahtarları ortam değişkeni (örn. N11_KEY) veya Streamlit secrets ile de verebilirsiniz; bunlar dosyadakinden önceliklidir.")
    if gen(st.button, "🔌 Bağlantı Testi", key=f"bt_{pid}"):
        ok_, msg_ = baglanti_testi(ayarlar, pid)
        (st.success if ok_ else st.error)(msg_)

    st.divider()
    bayrak = OTO_BAYRAK[pid]
    oto = st.toggle(f"🤖 {p['ad']} stok/fiyatı her senkronizasyondan sonra otomatik güncelle", value=bool(ayarlar.get(bayrak)), key=f"oto_{pid}")
    if oto != bool(ayarlar.get(bayrak)):
        ayarlar[bayrak] = oto
        ayar_yaz(ayarlar)
    st.divider()
    pazar_ayar_formu(pid)
    if pid == "ptt":
        with st.expander("🔎 PTT kategori ID bulucu (kategori adından ID bul)"):
            ptt_kategori_bulucu()
    if pid == "idefix":
        with st.expander("🏷️ İdefix marka ID bulucu (marka adından ID bul)"):
            idefix_marka_bulucu()
    if pid == "n11":
        with st.expander("🔎 N11 kategori ID bulucu (kategori adından ID bul)"):
            n11_kategori_bulucu()
    if pid == "idefix":
        with st.expander("🔎 İdefix kategori ID bulucu (kategori adından ID bul)"):
            idefix_kategori_bulucu()
    if pid == "hb":
        with st.expander("🔎 Hepsiburada kategori ID bulucu (kategori adından ID bul)"):
            hb_kategori_bulucu()
    if pid == "trendruum":
        with st.expander("🔎 Trendruum kategori ID bulucu (kategori adından ID bul)"):
            trendruum_kategori_bulucu()
    if pid in ("n11", "idefix", "trendruum", "ptt", "hb"):
        with st.expander("🗂️ Kategori eşleştirme (tedarikçi kategorisi → pazar yeri kategori ID)"):
            kategori_esleme_editoru(pid)


def tarih_nesnesi(t):
    t = str(t or "").strip()
    for bicim, uz in (("%d.%m.%Y %H:%M", 16), ("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(t[:uz], bicim)
        except ValueError:
            continue
    return None


def siparis_stok_metni(u, stok_harita, onek):
    sku = str(u.get("sku") or "")
    ham_sku = sku[len(onek):] if (onek and sku.startswith(onek)) else sku
    n = stok_harita.get(ham_sku, stok_harita.get(sku))
    if n is None:
        return "tedarikçi stoğu: bulunamadı"
    if int(n) <= 0:
        return "⚠️ **tedarikçi stoğu: 0 (STOK YOK, hemen kontrol edin)**"
    return f"tedarikçi stoğu: {int(n)}"


KUTU_RENK = {
    "hb": ("#ff5a1f", "#ff9a3c"), "trendyol": ("#f59e0b", "#fcd34d"), "n11": ("#5b21b6", "#8b5cf6"),
    "idefix": ("#059669", "#34d399"), "ptt": ("#0369a1", "#38bdf8"), "trendruum": ("#db2777", "#f472b6"),
}
DURUM_RENK = {"yeni": "#2563eb", "hazir": "#ea580c", "kargoda": "#7c3aed", "teslim": "#16a34a", "iptal": "#dc2626"}
PANEL_ADRES = {
    "hb": "https://merchant.hepsiburada.com/", "trendyol": "https://partner.trendyol.com/",
    "n11": "https://so.n11.com/", "trendruum": "https://www.trendruum.com/", "idefix": "https://merchant.idefix.com/",
    "ptt": "https://merchant.pttavm.com/",
}
SIPARIS_PAZARLARI = ("hb", "trendyol", "n11", "trendruum")


def _e(x):
    return html.escape(str(x if x is not None else ""))


def siparis_karti_css():
    return """<style>
.sc{border-radius:16px;overflow:hidden;background:#fff;border:1px solid #e2e8f0;box-shadow:0 4px 14px rgba(15,23,42,.10);margin-bottom:6px}
.sc .bas{padding:12px 16px;color:#fff}
.sc .bas b{font-size:1.15rem;letter-spacing:.3px}
.sc .bas small{display:block;opacity:.92;margin-top:2px}
.sc .chip{display:inline-block;color:#fff;border-radius:999px;padding:3px 12px;font-weight:700;font-size:.8rem;margin-top:6px}
.sc .alici{padding:12px 16px;background:#eff6ff;border-bottom:1px solid #dbeafe;font-size:.9rem;line-height:1.5}
.sc .alici span{display:inline-block;min-width:58px;font-weight:700;color:#1e3a8a}
.sc .urun{margin:12px 16px;padding:10px 12px;border-left:5px solid #2563eb;background:#f8fafc;border-radius:8px;font-size:.88rem}
.sc .urun b{color:#0f172a}
.sc .urun .sku{color:#475569;font-size:.8rem}
.sc .ok{color:#15803d;font-weight:600}.sc .kotu{color:#b91c1c;font-weight:700}
.sc .alt{padding:4px 16px 12px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px}
.sc .tutar{font-size:1.3rem;font-weight:800;color:#c2410c}
.sc .son{background:#fff7ed;color:#9a3412;border-radius:8px;padding:3px 10px;font-weight:600;font-size:.82rem}
.sc .kargo{padding:0 16px 8px;font-size:.9rem;color:#334155}
.sc .uy{margin:0 16px 10px;padding:8px 10px;background:#fef9c3;border-radius:8px;color:#854d0e;font-size:.82rem}
.ab{display:inline-block;padding:7px 12px;border-radius:9px;color:#fff!important;font-weight:700;font-size:.82rem;text-decoration:none!important;margin:2px 4px 2px 0}
.kutu{border-radius:16px;padding:14px 16px;color:#fff;box-shadow:0 4px 14px rgba(15,23,42,.18);margin-bottom:6px}
.kutu h4{margin:0;color:#fff;font-size:1.05rem;letter-spacing:.5px}
.kutu .say{margin-top:8px;font-size:.9rem;line-height:1.55}
.kutu .say b{background:rgba(255,255,255,.25);border-radius:8px;padding:2px 9px;margin-right:4px}
</style>"""


_SIP_TED = {}  # barkod -> tedarikçi adı (sipariş kartında "kimden alınacak" göstermek için)


def siparis_ted_doldur(urunler_df):
    """Sipariş sayfaları açılırken çağrılır; ürünlerin hangi tedarikçiden geldiğini hafızaya alır."""
    _SIP_TED.clear()
    try:
        if urunler_df is not None and not urunler_df.empty:
            _SIP_TED.update(urunler_df.groupby("barkod")["tedarikci"].first().astype(str).to_dict())
    except Exception:
        pass


def siparis_stok_html(u, stok_harita, onek):
    t = siparis_stok_metni(u, stok_harita, onek).replace("**", "").replace("⚠️ ", "")
    sinif = "ok" if (": " in t and t.split(": ")[-1].strip().isdigit() and int(t.split(": ")[-1]) > 0) else "kotu"
    sku = str(u.get("sku") or "")
    ham_sku = sku[len(onek):] if (onek and sku.startswith(onek)) else sku
    ted = _SIP_TED.get(ham_sku) or _SIP_TED.get(sku)
    ted_html = f' · <b>🏬 Tedarikçi: {_e(ted)}</b>' if ted else ""
    return f'<span class="{sinif}">{_e(t)}</span>{ted_html}'


def siparis_aktar_metni(o):
    """Başka bir sisteme (ör. Colezium) elle aktarmak için sipariş özeti."""
    satir = [f"Pazar: {PAZAR_AD.get(o.get('pid'), o.get('pid'))}", f"Sipariş no: {o.get('no')}", f"Paket no: {o.get('paket_no', '')}",
             f"Tarih: {o.get('tarih')}", f"Alıcı: {o.get('alici')}", f"Telefon: {o.get('telefon', '')}", f"Adres: {o.get('adres')}",
             f"Kargo: {o.get('kargo', '')}", f"Kargo barkodu: {o.get('barkod', '')}", f"Tutar: {para_metni(o.get('tutar'))}", "Ürünler:"]
    for u in o.get("urunler", []):
        satir.append(f"  - {u.get('ad')} | SKU {u.get('sku', '')} | adet {u.get('adet')}")
    return "\n".join(satir)


def siparis_karti(o, stok_harita, onek, anahtar="k"):
    pid = o.get("pid") or "hb"
    c1, c2 = KUTU_RENK.get(pid, ("#334155", "#64748b"))
    durum = o.get("durum", "yeni")
    etiket = DURUM_ETIKET.get(durum, durum)
    no = o.get("no") or o.get("paket_no") or "-"
    urunler = ""
    for u in o.get("urunler", []):
        fiyat = f" · {_e(para_metni(u['fiyat']))}" if u.get("fiyat") else ""
        urunler += (f'<div class="urun"><b>{_e(u.get("ad"))}</b><br>'
                    f'<span class="sku">SKU: {_e(u.get("sku", ""))} | Adet: <b>{_e(u.get("adet"))}</b>{fiyat}</span><br>'
                    f'{siparis_stok_html(u, stok_harita, onek)}</div>')
    kargo = " · ".join(x for x in (o.get("kargo", ""),) if x)
    uyari = f'<div class="uy">⚠️ {_e(o["uyari"])}</div>' if o.get("uyari") else ""
    son = f'<span class="son">⏰ {_e(o["teslim_son"])}</span>' if o.get("teslim_son") else ""
    kart = (
        f'<div class="sc"><div class="bas" style="background:linear-gradient(135deg,{c1},{c2})">'
        f'<b>📦 {_e(no)}</b><small>{_e(PAZAR_AD.get(pid, pid))} · {_e(o.get("tarih"))}'
        f'{(" · Paket " + _e(o["paket_no"])) if o.get("paket_no") and o.get("paket_no") != no else ""}</small>'
        f'<span class="chip" style="background:{DURUM_RENK.get(durum, "#334155")}">{_e(etiket)}</span></div>'
        f'<div class="alici"><span>Alıcı:</span> <b>{_e(o.get("alici") or "(bilgi yok)")}</b><br>'
        f'<span>Adres:</span> {_e(o.get("adres") or "(bilgi yok)")}'
        f'{("<br><span>Telefon:</span> " + _e(o["telefon"])) if o.get("telefon") else ""}</div>'
        f'{uyari}{urunler}'
        f'<div class="alt"><span class="tutar">{_e(para_metni(o.get("tutar")))}</span>{son}</div>'
        f'{("<div class=kargo>🚚 " + _e(kargo) + "</div>") if kargo else ""}</div>'
    )
    st.markdown(siparis_karti_css(), unsafe_allow_html=True)
    st.markdown(kart, unsafe_allow_html=True)
    if o.get("barkod"):
        st.caption("Kargo barkodu (sağdaki simgeyle kopyalayın)")
        st.code(str(o["barkod"]), language=None)
    panel = PANEL_ADRES.get(pid, "#")
    ad_p = PAZAR_AD.get(pid, pid)
    dugmeler = "".join(
        f'<a class="ab" style="background:{renk}" href="{panel}" target="_blank" rel="noopener">{etk}</a>'
        for etk, renk in (("🏷️ Kargo Etiketi", "#ea580c"), ("🚚 Kargo Değiştir", "#0ea5e9"),
                          ("✂️ Paketi Böl", "#a16207"), ("✖ İptal", "#dc2626")))
    st.markdown(dugmeler, unsafe_allow_html=True)
    st.caption(f"Bu işlemler şimdilik {ad_p} satıcı panelinde yapılır (düğmeler paneli açar). Paket no: {o.get('paket_no') or no}")
    st.download_button("📋 Siparişi Aktar (metin dosyası)", siparis_aktar_metni(o).encode("utf-8"),
                       file_name=f"siparis_{pid}_{no}.txt", mime="text/plain", key=f"aktar_{anahtar}_{pid}_{no}")
    if o.get("ham"):
        with st.expander("Ham veri (kontrol için)"):
            st.json(o["ham"])


def ana_siparisleri_yukle(zorla=False):
    """Bağlı pazarların siparişlerini oturumda önbelleğe alır (5 dk); hata bir pazarı diğerlerinden ayırmaz."""
    onbellek = st.session_state.setdefault("ana_sip", {})
    simdi = time.time()
    bekleyen = [p for p in SIPARIS_PAZARLARI if pazar_bagli(ayarlar, p)
                and (zorla or p not in onbellek or simdi - onbellek[p]["t"] > 300)]
    if not bekleyen:
        return onbellek
    with st.spinner("Siparişler çekiliyor..."):
        for pid in bekleyen:
            try:
                onbellek[pid] = {"liste": siparis_cek(ayarlar, pid, 72), "hata": None, "t": simdi}
            except Exception as e:
                onbellek[pid] = {"liste": [], "hata": str(e)[:200], "t": simdi}
    return onbellek


def ana_siparis_kutulari():
    st.markdown(siparis_karti_css(), unsafe_allow_html=True)
    b1, b2 = st.columns([4, 1])
    b1.markdown("### 🧾 Siparişler")
    zorla = bool(gen(b2.button, "🔄 Yenile", key="ana_sip_yenile"))
    veri = ana_siparisleri_yukle(zorla)
    stok_harita = {}
    try:
        _u = urunleri_oku()
        if not _u.empty:
            stok_harita = _u.groupby("barkod")["stok"].max().to_dict()
        siparis_ted_doldur(_u)
    except Exception:
        pass
    kutular = list(PAZAR.keys())
    secili = st.session_state.get("ana_sec")
    for i in range(0, len(kutular), 3):
        kol = st.columns(3)
        for j, pid in enumerate(kutular[i:i + 3]):
            with kol[j]:
                c1, c2 = KUTU_RENK[pid]
                ad = PAZAR_AD[pid]
                ikon = PAZAR[pid]["ikon"]
                d = veri.get(pid)
                if pid not in SIPARIS_PAZARLARI:
                    icerik = "Sipariş çekme bu pazar için desteklenmiyor."
                    aktif = []
                elif not pazar_bagli(ayarlar, pid):
                    icerik = "API bilgileri eksik."
                    aktif = []
                elif d and d["hata"]:
                    icerik = f"⚠️ Hata: {_e(d['hata'])}"
                    aktif = []
                else:
                    liste = d["liste"] if d else []
                    yeni = [o for o in liste if o["durum"] in ("yeni", "hazir")]
                    kargo = [o for o in liste if o["durum"] == "kargoda"]
                    aktif = yeni
                    if not liste:
                        icerik = "Sipariş yok"
                    else:
                        parcalar = []
                        n_y = sum(1 for o in liste if o["durum"] == "yeni")
                        n_h = sum(1 for o in liste if o["durum"] == "hazir")
                        if n_y:
                            parcalar.append(f"<b>{n_y}</b> Yeni")
                        if n_h:
                            parcalar.append(f"<b>{n_h}</b> Gönderime Hazır")
                        if kargo:
                            parcalar.append(f"<b>{len(kargo)}</b> Kargoda")
                        icerik = "<br>".join(parcalar) or "Bekleyen sipariş yok"
                st.markdown(f'<div class="kutu" style="background:linear-gradient(135deg,{c1},{c2})"><h4>{ikon} {_e(ad.upper())}</h4>'
                            f'<div class="say">{icerik}</div></div>', unsafe_allow_html=True)
                for k, o in enumerate(aktif[:8]):
                    anahtar = f"{pid}|{o.get('id')}|{o.get('no')}"
                    ozet = f"{o.get('no') or o.get('paket_no')} · {str(o.get('alici') or '')[:18]} · {para_metni(o.get('tutar'))}"
                    if gen(st.button, ozet, key=f"ana_sip_{pid}_{k}", type="primary" if secili == anahtar else "secondary"):
                        st.session_state["ana_sec"] = anahtar
                        st.rerun()
                if len(aktif) > 8:
                    st.caption(f"+{len(aktif) - 8} sipariş daha: {ad} > Siparişlerim")
    if secili:
        bulunan = None
        for pid, d in veri.items():
            for o in d["liste"]:
                if f"{pid}|{o.get('id')}|{o.get('no')}" == secili:
                    bulunan = o
        if bulunan:
            with st.container(border=True):
                kapat = gen(st.button, "✖ Detayı kapat", key="ana_sip_kapat")
                onek = str(pa_al(ayarlar, "hb").get("sku_prefix", "") or "") if bulunan.get("pid") == "hb" else ""
                siparis_karti(bulunan, stok_harita, onek, anahtar="ana")
                if kapat:
                    st.session_state.pop("ana_sec", None)
                    st.rerun()


def pazar_siparis(pid):
    p = PAZAR[pid]
    st.title(f"{p['ikon']} {p['ad']} Siparişlerim")
    if pid not in ("trendyol", "n11", "hb", "trendruum"):
        st.info(f"{p['ad']} için sipariş çekme henüz desteklenmiyor.")
        return
    bugun = simdi_tr().date()
    with st.container(border=True):
        c1, c2, c3 = st.columns([2, 2, 2])
        bas = c1.date_input("Başlangıç", bugun - timedelta(days=7), key=f"sp_bas_{pid}")
        bit = c2.date_input("Bitiş", bugun, key=f"sp_bit_{pid}")
        c3.write("")
        if gen(c3.button, "🔄 Siparişleri Çek", type="primary", key=f"sp_cek_{pid}"):
            try:
                saat = max(1, int((simdi_tr() - datetime.combine(bas, datetime.min.time())).total_seconds() // 3600) + 1)
                with st.spinner("Siparişler çekiliyor..."):
                    st.session_state[f"sip_{pid}"] = siparis_cek(ayarlar, pid, saat)
                st.session_state[f"sip_zaman_{pid}"] = simdi_tr().strftime("%d.%m.%Y %H:%M")
                st.session_state[f"sip_say_{pid}"] = 24
            except Exception as e:
                st.error(f"Hata: {e}")
    liste = st.session_state.get(f"sip_{pid}")
    if liste is None:
        st.info("Tarih aralığını seçip 'Siparişleri Çek' düğmesine tıklayın.")
        return
    if pid == "hb" and SIPARIS_TANI:
        if not liste:
            st.warning("Hepsiburada bu çekimde hiç sipariş döndürmedi. Aşağıdaki ayrıntı nedenini gösterir; siparişleriniz 'teslim edildi' ya da 'iptal' ise bu servislerde görünmeyebilir.")
        with st.expander("🔎 Çekme ayrıntısı (sipariş görünmüyorsa buraya bakın)", expanded=not liste):
            st.caption("Hepsiburada'nın döndürdüğü ham sonuç. Sipariş sayısı 0 ise ve beklediğiniz sipariş varsa bu bölümün ekran görüntüsünü gönderin.")
            st.json(dict(SIPARIS_TANI))
    liste = [o for o in liste if (tarih_nesnesi(o.get("tarih")) is None) or (bas <= tarih_nesnesi(o.get("tarih")).date() <= bit)]
    gruplar = {"Tüm Siparişler": None, "Bekleyen": ("yeni", "hazir"), "Kargoda": ("kargoda",),
               "Tamamlandı": ("teslim",), "İptal / Sorunlu": ("iptal",)}
    sayilar = {ad: (len(liste) if d is None else sum(1 for o in liste if o["durum"] in d)) for ad, d in gruplar.items()}
    secenekler = [f"{ad} ({n})" for ad, n in sayilar.items()]
    pills = getattr(st, "pills", None)
    secim = pills("Durum", secenekler, default=secenekler[0], key=f"sp_durum_{pid}", label_visibility="collapsed") if pills else \
        st.radio("Durum", secenekler, horizontal=True, key=f"sp_durum_{pid}", label_visibility="collapsed")
    secim = secim or secenekler[0]
    ad_secim = list(gruplar)[secenekler.index(secim)]
    ara = st.text_input("🔍 Sipariş no, müşteri, ürün, barkod ara", key=f"sp_ara_{pid}")
    f = liste if gruplar[ad_secim] is None else [o for o in liste if o["durum"] in gruplar[ad_secim]]
    if ara.strip():
        n_ = tr_norm(ara)
        f = [o for o in f if n_ in tr_norm(" ".join([str(o.get("no", "")), str(o.get("paket_no", "")), str(o.get("alici", ""))] +
             [str(u.get("ad", "")) + " " + str(u.get("sku", "")) for u in o.get("urunler", [])]))]
    m1, m2, m3 = st.columns(3)
    m1.metric("Listelenen sipariş", len(f))
    m2.metric("Bekleyen", sayilar["Bekleyen"])
    m3.metric("Toplam tutar", para_metni(sum(_f(o.get("tutar")) for o in f)))
    z = st.session_state.get(f"sip_zaman_{pid}")
    if z:
        st.caption(f"Son çekilme: {z}")
    if not f:
        st.info("Bu filtreyle sipariş bulunamadı.")
        if pid == "hb":
            st.caption("Not: Hepsiburada'nın sipariş servisleri yalnızca (1) paketlenmeyi bekleyen ÖDEMESİ TAMAMLANMIŞ yeni siparişleri ve (2) gönderime hazır paketleri listeler. Kargoya verilmiş, teslim edilmiş ya da iptal olmuş siparişler bu servislerde görünmez; onları Hepsiburada satıcı panelinden izleyin.")
        return
    stok_harita = {}
    try:
        _u = urunleri_oku()
        if not _u.empty:
            stok_harita = _u.groupby("barkod")["stok"].max().to_dict()
        siparis_ted_doldur(_u)
    except Exception:
        pass
    onek = str(pa_al(ayarlar, "hb").get("sku_prefix", "") or "") if pid == "hb" else ""
    sirali = sorted(f, key=lambda o: tarih_nesnesi(o.get("tarih")) or datetime.min, reverse=True)
    sayi = st.session_state.setdefault(f"sip_say_{pid}", 24)
    gorunen = sirali[:sayi]
    for i in range(0, len(gorunen), 2):
        kol = st.columns(2)
        for j, o in enumerate(gorunen[i:i + 2]):
            with kol[j]:
                siparis_karti(o, stok_harita, onek, anahtar=f"{pid}_{i}_{j}")
    if len(sirali) > sayi and gen(st.button, f"⬇️ Daha fazla göster ({sayi}/{len(sirali)})", key=f"sip_daha_{pid}"):
        st.session_state[f"sip_say_{pid}"] = sayi + 24
        st.rerun()


def _satir_yuksekligi():
    """Streamlit sürümü destekliyorsa tablo satırlarını yükseltir (görseller büyük ve net görünür)."""
    try:
        import inspect
        if "row_height" in inspect.signature(st.dataframe).parameters:
            return {"row_height": 76}
    except Exception:
        pass
    return {}


def galeri_goster(f, kilit, sayfa_boy=24):
    """Büyük, ortalanmış, net ve canlı görselli ürün ızgarası (yalnızca gösterim)."""
    import html as _html
    if f.empty:
        st.info("Gösterilecek ürün yok.")
        return
    toplam = len(f)
    sayfa_say = max((toplam + sayfa_boy - 1) // sayfa_boy, 1)
    sayfa = int(st.number_input("Sayfa", min_value=1, max_value=sayfa_say, value=1, step=1, key="galeri_sayfa"))
    parca = f.iloc[(sayfa - 1) * sayfa_boy: sayfa * sayfa_boy]
    st.markdown("""<style>
.sg{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:14px}
.sk{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:10px;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,.06)}
.sk .im{height:170px;display:flex;align-items:center;justify-content:center;background:#f8fafc;border-radius:10px;overflow:hidden}
.sk img{max-width:100%;max-height:100%;object-fit:contain;image-rendering:auto;filter:saturate(1.18) contrast(1.06) brightness(1.03)}
.sk .ad{font-size:.82rem;font-weight:600;margin:8px 0 2px;line-height:1.25;height:2.5em;overflow:hidden;color:#111827}
.sk .bk{font-size:.74rem;color:#2563eb}
.sk .st{font-size:.78rem;color:#374151;margin-top:3px}
.sk .t{color:#dc2626;font-weight:700}
</style>""", unsafe_allow_html=True)
    kartlar = []
    for _, row in parca.iterrows():
        img = str(row.get("gorsel", "") or "")
        im = (f'<img src="{_html.escape(img, quote=True)}" loading="lazy" referrerpolicy="no-referrer">'
              if img.startswith("http") else "📷")
        stok = _i(row.get("stok"))
        stok_h = f'<span class="t">TÜKENDİ</span>' if stok <= 0 else f"Stok <b>{stok}</b>"
        kil = " 🔒" if str(row.get("barkod")) in kilit else ""
        kartlar.append(
            f'<div class="sk"><div class="im">{im}</div>'
            f'<div class="ad">{_html.escape(str(row.get("urun_adi") or "İsimsiz Ürün"))}{kil}</div>'
            f'<div class="bk">{_html.escape(str(row.get("barkod", "-")))}</div>'
            f'<div class="st">{stok_h} · {_f(row.get("satis_fiyati")):.2f} ₺</div></div>')
    st.markdown('<div class="sg">' + "".join(kartlar) + "</div>", unsafe_allow_html=True)
    st.caption(f"Sayfa {sayfa}/{sayfa_say} · {toplam:,} ürün")


# Gerçek ürün/üretici markaları: başlığın başında geçiyorsa ürün o markanındır (marka alanı farklıysa risk)
URETICI_MARKALAR = (
    "dux ducis", "baseus", "ugreen", "anker", "hoco", "remax", "torima", "gor", "jbl", "sony", "philips", "logitech", "razer",
    "dyson", "braun", "tefal", "bosch", "arzum", "karaca", "stanley", "nike", "adidas", "puma", "lacoste", "gucci", "louis vuitton",
    "chanel", "versace", "calvin klein", "tommy", "levi", "converse", "rolex", "casio", "fossil", "lego", "disney", "marvel",
    "barbie", "hello kitty", "mattel", "hasbro", "playmobil", "canon", "nikon", "gopro",
)
# Telefon / cihaz marka-model adları: çoğu 'iPhone 15 kılıf', 'Vivo Y20 cam' gibi uyumluluk bilgisidir; varsayılan olarak taranmaz
CIHAZ_MARKALARI = (
    "apple", "iphone", "airpods", "samsung", "xiaomi", "redmi", "huawei", "oppo", "realme", "vivo", "oneplus", "honor",
    "lg", "hp", "lenovo", "asus", "dell", "nintendo", "playstation", "xbox",
)
RISKLI_MARKALAR = URETICI_MARKALAR + CIHAZ_MARKALARI


def marka_risk_tara(df, ilk_kelime=4, cihaz_dahil=False):
    """Başlığında bilinen marka adı geçen ürünleri bulur. ilk_kelime: yalnız başlığın ilk N kelimesine bakar; 0 = tüm başlık.
    cihaz_dahil=False iken telefon/cihaz adları (iPhone, Samsung, Vivo...) sayılmaz. Dönüş: {marka: [(barkod, başlık), ...]}"""
    liste = RISKLI_MARKALAR if cihaz_dahil else URETICI_MARKALAR
    kalip = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(m) for m in sorted(liste, key=len, reverse=True)) + r")(?![a-z0-9])")
    out = {}
    for barkod, ad in zip(df["barkod"].astype(str), df["urun_adi"].astype(str)):
        n = tr_norm(ad)
        if ilk_kelime:
            n = " ".join(n.split()[:ilk_kelime])
        for m in set(kalip.findall(n)):
            out.setdefault(m, []).append((barkod, ad))
    return out


def marka_risk_tarayici(df):
    with st.expander("⚠️ Marka riski tarayıcı (başlığında tanınmış marka adı geçen ürünler)"):
        st.caption("Başka bir markanın adını taşıyan ürünler, pazar yerlerinde 'hatalı marka / orijinal olmayan ürün' ihlaline yol açabilir. "
                   "Bu araç başlıklarda bilinen marka adlarını arar. Çıkan her ürün sorunlu değildir (örneğin 'Samsung uyumlu kılıf'); listeye bakıp karar verin. "
                   "Seçtiğiniz markaların ürünleri satıştan kaldırılır (stok 0 + kilit); ürün silinmez, istediğinizde kilit kaldırılır.")
        k1, k2 = st.columns([2, 1])
        dar = k1.checkbox("Sadece başlığın ilk 4 kelimesinde geçenler", value=True, key="mr_dar")
        cihaz = k1.checkbox("Telefon/cihaz adlarını da say (iPhone, Samsung, Vivo...; çoğu sadece uyumluluk bilgisidir)", value=False, key="mr_cihaz")
        if gen(k2.button, "🔍 Tara", key="mr_tara"):
            with st.spinner("Taranıyor..."):
                st.session_state["mr_sonuc"] = marka_risk_tara(df, 4 if dar else 0, cihaz)
        sonuc = st.session_state.get("mr_sonuc")
        if sonuc is None:
            return
        if not sonuc:
            st.success("Bilinen marka adı taşıyan ürün bulunmadı.")
            return
        tablo = pd.DataFrame({"Marka": list(sonuc), "Ürün": [len(v) for v in sonuc.values()],
                              "Örnek başlık": [v[0][1][:90] for v in sonuc.values()]}).sort_values("Ürün", ascending=False).reset_index(drop=True)
        st.dataframe(tablo, hide_index=True, use_container_width=True)
        secili = st.multiselect("Satıştan kaldırılacak markalar", list(tablo["Marka"]), key="mr_sec")
        barkodlar = sorted({b for m in secili for b, _ in sonuc[m]})
        if barkodlar:
            st.warning(f"{len(barkodlar):,} ürünün stoğu 0 yapılıp kilitlenecek ve bağlı pazar yerlerine gönderilecek.")
            onay = st.checkbox("Onaylıyorum", key="mr_onay")
            if gen(st.button, "🔒 Seçili markaların ürünlerini satıştan kaldır", key="mr_btn", disabled=not onay):
                sonuc_g = stok_sifirla(ayarlar, barkodlar, True)
                st.session_state["urun_sifir_sonuc"] = [f"{len(barkodlar):,} ürünün stoğu sıfırlandı ve kilitlendi."] + [
                    f"{ad}: {ok} gönderildi" + (f", hata: {h}" if h else "") for ad, ok, h in sonuc_g]
                st.session_state.pop("mr_sonuc", None)
                st.rerun()


def urunler_sayfasi():
    st.title("📦 Sistemdeki Ürünler")
    for mesaj in st.session_state.pop("urun_senk_sonuc", []) or []:
        (st.success if mesaj[1] else st.error)(f"{mesaj[0]}: {mesaj[2]}")
    for mesaj in st.session_state.pop("urun_sifir_sonuc", []) or []:
        st.info(mesaj)
    df = urunleri_oku()
    if df.empty:
        st.warning("Sistemde henüz kayıtlı ürün bulunmuyor.")
        if gen(st.button, "🔄 Stokları tedarikçiden çek", key="urun_stok_cek_bos"):
            st.session_state["urun_senk_sonuc"] = tumunu_senkronla(oto=False)
            st.rerun()
        return
    kilit = stok_sifir_kume(ayarlar)
    fiyat_kilit = fiyat_sabit_sozluk(ayarlar)
    esik = _i(ayarlar.get("kritik_esik")) or 3
    c1, c2 = st.columns([1, 2])
    secenek = ["Tüm Bayiler"] + sorted(df["tedarikci"].dropna().unique().tolist())
    secili = c1.selectbox("🏬 Tedarikçi / Bayi", secenek)
    ara = c2.text_input("🔍 Ürün adı veya barkod ara", "")
    d1, d2 = st.columns([1, 2])
    durum = d1.selectbox("Stok durumu", ["Tümü", "Stokta", "Tükenen", f"Kritik (≤{esik})", "Elle sıfırlananlar"])
    gorunum = d2.radio("Görünüm", ["Tablo (kaydırmalı)", "Galeri (büyük görsel)", "Kart (küçük görsel)"], horizontal=True)

    f = df
    if secili != "Tüm Bayiler":
        f = f[f["tedarikci"] == secili]
    if ara:
        f = urun_ara(f, ara)
    if durum == "Stokta":
        f = f[f["stok"] > 0]
    elif durum == "Tükenen":
        f = f[f["stok"] <= 0]
    elif durum.startswith("Kritik"):
        f = f[f["stok"].between(1, esik)]
    elif durum == "Elle sıfırlananlar":
        f = f[f["barkod"].astype(str).isin(kilit)]
    f = f.reset_index(drop=True)

    top1, top2 = st.columns([2, 1])
    top1.info(f"Toplam **{len(f):,}** ürün listeleniyor. Elle sıfırlanmış: **{len(kilit):,}**")
    if gen(top2.button, "🔄 Stokları tedarikçiden çek", key="urun_stok_cek",
           help="Seçili bayinin (ya da tüm bayilerin) XML'ini yeniler ve stokları güncel haline getirir."):
        with st.spinner("Tedarikçi stokları çekiliyor..."):
            if secili != "Tüm Bayiler" and secili in ayarlar["tedarikciler"]:
                try:
                    sayi = tedarikci_senkron(secili, ayarlar["tedarikciler"][secili], esik, stok_ust_degeri(ayarlar))
                    log_yaz(secili, "OK", f"{sayi} ürün güncellendi")
                    st.session_state["urun_senk_sonuc"] = [(secili, True, f"{sayi} ürün")]
                except Exception as e:
                    st.session_state["urun_senk_sonuc"] = [(secili, False, str(e))]
            else:
                st.session_state["urun_senk_sonuc"] = tumunu_senkronla(oto=False)
        st.rerun()

    _fs_acik = bool(fiyat_sistemi(ayarlar))
    if not _fs_acik:
        st.error("⚠️ FİYAT SİSTEMİ KAPALI: pazarlara tedarikçi (alış) fiyatı gider! Pazar Yerleri → Genel Ayarlar → Fiyat sistemi'ni açıp Kaydet'e basın.")
    # Her bağlı pazar için ayrı fiyat sütunu (hangi pazara hangi fiyat gittiği yan yana görünsün)
    _pazar_fiyat = {}
    _sira = ["hb", "trendyol", "n11", "idefix", "ptt", "trendruum"]
    for _pz in [x for x in _sira if x in GUNCELLEYICI and pazar_bagli(ayarlar, x)]:
        try:
            if len(f):
                _pazar_fiyat[f"{PAZAR_AD.get(_pz, _pz)} fiyatı"] = fiyat_artis_uygula(ayarlar, _pz, f.copy())["satis_fiyati"].map(_f).round(2).values
        except Exception:
            pass
    if gorunum.startswith("Tablo"):
        v = pd.DataFrame({
            "Görsel": f["gorsel"].where(f["gorsel"].astype(str).str.startswith("http"), None),
            "Ürün": f["urun_adi"], "Barkod": f["barkod"],
            "Pazar barkodu": [(b if b and b != k else "") for k, b in zip(f["barkod"].astype(str), f["barkod"].astype(str).map(lambda k: sabit_barkod(k, True) or ""))],
            "Tedarikçi": f["tedarikci"], "Stok": f["stok"],
            "Alış": f["alis_fiyati"].map(_f).round(2), "Satış": f["satis_fiyati"].map(_f).round(2),
            "Kilit": [("🔒" if b in kilit else "") + ("💲" if b in fiyat_kilit else "")
                      for b in f["barkod"].astype(str)],
        })
        _yer = v.columns.get_loc("Satış") + 1
        for _sn, (_ad, _deg) in enumerate(_pazar_fiyat.items()):
            v.insert(_yer + _sn, _ad, _deg)
        ayar_kol = {
            **{_ad: st.column_config.NumberColumn(_ad, format="%.2f ₺", help="Bu pazar yerine gönderilecek hesaplanmış satış fiyatı (o pazarın komisyonuyla)") for _ad in _pazar_fiyat},
            "Görsel": st.column_config.ImageColumn("Görsel", width="small"),
            "Ürün": st.column_config.TextColumn("Ürün", width="large"),
            "Alış": st.column_config.NumberColumn("Alış", format="%.2f ₺"),
            "Satış": st.column_config.NumberColumn("Satış", format="%.2f ₺"),
        }
        secilen = []
        try:
            olay = st.dataframe(v, hide_index=True, height=620, column_config=ayar_kol,
                                on_select="rerun", selection_mode="multi-row", key="urun_tablo", **_satir_yuksekligi())
            secilen = list(olay.selection.rows)
        except TypeError:
            st.dataframe(v, hide_index=True, height=620, column_config=ayar_kol)
            st.caption("Bu Streamlit sürümünde satır seçimi yok; stok sıfırlamak için barkodu aşağıya yazın.")
        st.caption("Satırın solundaki kutuyla ürün seçin (birden fazla seçebilirsiniz). Kaydırdıkça tüm liste açılır; sayfa numarası yok.")
        sec_barkod = [str(f.loc[i, "barkod"]) for i in secilen if i < len(f)]
        if not sec_barkod:
            elle = st.text_input("veya stoğunu sıfırlamak istediğiniz barkodlar (virgülle)", key="sifir_elle")
            sec_barkod = [x.strip() for x in elle.split(",") if x.strip()]
        if sec_barkod:
            with st.container(border=True):
                st.write(f"Seçili ürün: **{len(sec_barkod)}**")
                gonder = st.checkbox("Bağlı pazar yerlerine de hemen gönder", value=True, key="sifir_gonder")
                onay = st.checkbox("Onaylıyorum", key="sifir_onay")
                k1, k2 = st.columns(2)
                if gen(k1.button, "🔒 Stoğu sıfırla ve kilitle", key="sifir_btn", disabled=not onay):
                    sonuc = stok_sifirla(ayarlar, sec_barkod, gonder)
                    st.session_state["urun_sifir_sonuc"] = [f"{len(sec_barkod)} ürünün stoğu sıfırlandı ve kilitlendi."] + [
                        f"{ad}: {ok} gönderildi" + (f", hata: {h}" if h else "") for ad, ok, h in sonuc]
                    st.rerun()
                if gen(k2.button, "🔓 Kilidi kaldır", key="kilit_kaldir_btn"):
                    n = stok_kilidi_kaldir(ayarlar, sec_barkod)
                    st.session_state["urun_sifir_sonuc"] = [f"{n} ürünün kilidi kaldırıldı. Stok, bir sonraki tedarikçi çekişinde geri gelir ('Stokları tedarikçiden çek')."]
                    st.rerun()
        if sec_barkod:
            with st.container(border=True):
                st.markdown("**💲 Satış fiyatını değiştir**")
                ilk = f[f["barkod"].astype(str).isin(sec_barkod)]
                mevcut_fiyat = float(_f(ilk["satis_fiyati"].iloc[0])) if len(ilk) else 0.0
                alis_en_yuksek = float(ilk["alis_fiyati"].map(_f).max()) if len(ilk) else 0.0
                yeni_fiyat = st.number_input("Yeni satış fiyatı (₺) — pazar yerlerine bu fiyat gider", min_value=0.0,
                                             value=round(mevcut_fiyat, 2), step=1.0, format="%.2f", key="fiyat_yeni")
                st.caption(f"Seçili {len(sec_barkod)} ürün · en yüksek alış fiyatı {alis_en_yuksek:.2f} ₺. "
                           "Bu fiyat marj, kargo ve komisyon hesabından sonra kesin fiyattır; tedarikçi senkronunda da korunur.")
                zarar = yeni_fiyat > 0 and yeni_fiyat < alis_en_yuksek
                zarar_onay = True
                if zarar:
                    st.warning("Yeni fiyat alış fiyatının altında; bu fiyatla satarsanız zarar edersiniz.")
                    zarar_onay = st.checkbox("Zararına satışı onaylıyorum", key="fiyat_zarar")
                fg = st.checkbox("Bağlı pazar yerlerine de hemen gönder", value=True, key="fiyat_gonder")
                p1, p2 = st.columns(2)
                if gen(p1.button, "💲 Fiyatı kaydet", key="fiyat_btn", disabled=(yeni_fiyat <= 0 or not zarar_onay)):
                    try:
                        sonuc = fiyat_sabitle(ayarlar, sec_barkod, yeni_fiyat, fg)
                        st.session_state["urun_sifir_sonuc"] = [f"{len(sec_barkod)} ürünün satış fiyatı {yeni_fiyat:.2f} ₺ yapıldı."] + [
                            f"{ad}: {ok} gönderildi" + (f", hata: {h}" if h else "") for ad, ok, h in sonuc]
                    except ValueError as e:
                        st.session_state["urun_sifir_sonuc"] = [str(e)]
                    st.rerun()
                if gen(p2.button, "↩️ Elle fiyatı kaldır", key="fiyat_kaldir_btn"):
                    n = fiyat_sabit_kaldir(ayarlar, sec_barkod)
                    st.session_state["urun_sifir_sonuc"] = [f"{n} ürünün elle fiyatı kaldırıldı. Otomatik fiyat, bir sonraki tedarikçi çekişinde ('Stokları tedarikçiden çek') geri gelir."]
                    st.rerun()
    elif gorunum.startswith("Galeri"):
        galeri_goster(f, kilit)
    else:
        st.caption("Küçük görselli kart görünümü; daha fazlası için aşağıdaki düğmeyi kullanın.")
        sayi = st.session_state.setdefault("urun_kart_sayi", 24)
        for idx, row in f.head(sayi).iterrows():
            with st.container(border=True):
                g, y = st.columns([1, 4])
                img = row.get("gorsel", "")
                if img and str(img).startswith("http"):
                    g.image(img, width=70)
                else:
                    g.write("📷")
                alis, satis = _f(row.get("alis_fiyati")), _f(row.get("satis_fiyati"))
                kil = " 🔒" if str(row.get("barkod")) in kilit else ""
                ad_k = row.get("urun_adi") or "İsimsiz Ürün"
                y.markdown(f"**{ad_k}**{kil}")
                y.caption(f"Barkod `{row.get('barkod', '-')}` · {row.get('tedarikci', '-')} · Stok **{row.get('stok', 0)}** · Alış {alis:.2f} ₺ · Satış {satis:.2f} ₺")
        if len(f) > sayi and gen(st.button, f"⬇️ Daha fazla göster ({min(sayi, len(f))}/{len(f)})", key="urun_daha_fazla"):
            st.session_state["urun_kart_sayi"] = sayi + 48
            st.rerun()
    marka_risk_tarayici(df)
    with st.expander("🔎 Stok neden 0? (teşhis)"):
        st.caption("Tedarikçi başına stok dağılımı: 'Stok 0' çoksa ya XML'de stok gerçekten yok, ya kritik eşik/kilit/kara liste sıfırlıyor.")
        dag = tedarikci_stok_dagilimi(_i(ayarlar.get("kritik_esik")))
        if not dag.empty:
            st.dataframe(dag)
        bk_t = st.text_input("Barkod yaz, nedenini göstereyim", key="teshis_barkod")
        if bk_t.strip():
            for satir in stok_teshis(ayarlar, bk_t):
                st.write("• " + satir)
            st.markdown("**Canlı deneme:** bu tek ürünü seçtiğin pazara şimdi gönderir ve pazaryerinin verdiği ham yanıtı gösterir.")
            pz_dene = st.selectbox("Pazar", [p_ for p_ in GUNCELLEYICI if pazar_bagli(ayarlar, p_)], format_func=lambda p_: PAZAR_AD.get(p_, p_), key="teshis_pazar")
            if st.button("🧪 Bu ürünü şimdi bu pazara gönder", key="teshis_gonder_dugme"):
                try:
                    df_d = urunleri_oku()
                    df_d = df_d[df_d["barkod"].astype(str) == bk_t.strip()].head(1)
                    if df_d.empty:
                        st.error("Bu barkod ürün listesinde yok.")
                    else:
                        planli = fiyat_artis_uygula(ayarlar, pz_dene, df_d)
                        st.write(f"Gönderilecek fiyat: **{_f(planli['satis_fiyati'].iloc[0]):.2f} ₺** · stok: {_i(planli['stok'].iloc[0])}"
                                 + (" (acil durdur açık: stok 0 gider)" if ayarlar.get("acil_durdur") else ""))
                        SON_YANIT.pop("trendruum", None); SON_YANIT.pop("hb_fiyat", None); SON_YANIT.pop("hb_stok", None)
                        ok_, hata_, ozet_ = pazara_gonder(ayarlar, pz_dene, df_d)
                        st.write(f"Sonuç: {ok_} gönderildi, {hata_} hata")
                        st.code(ozet_)
                        for ad_y, v_y in SON_YANIT.items():
                            st.write(f"**{ad_y}** ham yanıt (HTTP {v_y.get('kod')}):")
                            st.code(v_y.get("yanit", ""))
                            with st.expander("Gönderilen istek (örnek)"):
                                st.json(v_y.get("istek_ornek"))
                        if pz_dene == "hb":
                            time.sleep(6)  # Hepsiburada isteği sıraya alır; sonucu birkaç saniye sonra verir
                            for ad_y, tur_ in (("hb_fiyat", "fiyat"), ("hb_stok", "stok")):
                                mt_ = re.search(r'"id"\s*:\s*"([^"]+)"', (SON_YANIT.get(ad_y) or {}).get("yanit", ""))
                                if mt_:
                                    kod_s, ham_s = hb_yukleme_durumu(ayarlar, tur_, mt_.group(1))
                                    st.write(f"**Hepsiburada {tur_} yükleme SONUCU** (HTTP {kod_s}) — gerçek sonuç bu:")
                                    st.code(ham_s)
                except Exception as e:
                    st.error(f"Hata: {e}")
    if kilit:
        with st.expander(f"🔒 Elle sıfırlanmış ürünler ({len(kilit)})"):
            kd = pd.DataFrame({"Barkod": sorted(kilit), "Kilit zamanı": [ayarlar["stok_sifir"][b] for b in sorted(kilit)]})
            st.dataframe(kd, hide_index=True)


def stok_teshis(ayar, barkod):
    """Bir ürünün stoğunun neden 0 görünebileceğini sıralar (bulgu listesi döndürür)."""
    barkod = str(barkod).strip()
    df = urunleri_oku()
    r = df[df["barkod"] == barkod]
    if r.empty:
        return ["Bu barkod sistemde yok (tedarikçi XML'inde bulunmuyor ya da hiç çekilmemiş)."]
    r = r.iloc[0]
    bulgu = [f"Sistemdeki stok: {int(r['stok'])} · tedarikçi: {r.get('tedarikci')} · satış fiyatı: {_f(r.get('satis_fiyati')):.2f} ₺"]
    if barkod in stok_sifir_kume(ayar):
        bulgu.append(f"🔒 ELLE KİLİTLİ: stoğu sıfırlanıp kilitlenmiş ({ayar['stok_sifir'].get(barkod)}). Tedarikçi ayarında 'Kilidi kaldır'a bas.")
    one = df.iloc[[r.name]] if r.name in df.index else df[df["barkod"] == barkod]
    if kara_liste_maskesi(ayar, one).any():
        bulgu.append("🚫 KARA LİSTE: adı/kategorisi/barkodu kara liste kelimesini içeriyor; pazara hep stok 0 gider (Genel & Yedek > Kara liste).")
    if ayar.get("acil_durdur"):
        bulgu.append("🛑 ACİL DURDUR AÇIK: tüm pazarlara stok 0 gönderiliyor.")
    alis_ = _f(r.get("alis_fiyati"))
    fs_ = fiyat_sistemi(ayar)
    bulgu.append(f"💲 Alış fiyatı: {alis_:.2f} ₺ · Fiyat sistemi: {'AÇIK' if fs_ else 'KAPALI (pazara tedarikçideki satış fiyatı gider)'} · "
                 f"elle sabit fiyat: {ayar.get('fiyat_sabit', {}).get(barkod, 'yok')}")
    if alis_ > 0:
        d1 = df[df["barkod"] == barkod].head(1)
        for pid_ in GUNCELLEYICI:
            if pazar_bagli(ayar, pid_):
                try:
                    hf = _f(fiyat_artis_uygula(ayar, pid_, d1)["satis_fiyati"].iloc[0])
                    bulgu.append(f"💲 {PAZAR_AD.get(pid_, pid_)}'e GİDECEK hesaplanan fiyat: {hf:.2f} ₺" + (" ⚠️ alış fiyatına yakın!" if hf <= alis_ * 1.03 else ""))
                except Exception as e:
                    bulgu.append(f"{PAZAR_AD.get(pid_, pid_)} fiyat hesabı yapılamadı: {e}")
    esik = _i(ayar.get("kritik_esik"))
    if int(r["stok"]) == 0 and esik > 0:
        bulgu.append(f"⚠️ Kritik stok eşiği {esik}: tedarikçide stoğu {esik} ve altında olan ürünler 0 sayılır. Ham stok {esik} veya altındaysa 0'ın nedeni bu.")
    elif 0 < int(r["stok"]) <= _i(ayar.get("stok_guvenlik_payi")):
        bulgu.append(f"⚠️ Güvenlik payı {_i(ayar.get('stok_guvenlik_payi'))}: pazara stoktan bu kadar eksik gider; sonuç 0.")
    if _i(ayar.get("pazar_stok_tavani")) > 0:
        bulgu.append(f"ℹ️ Pazar stok tavanı {_i(ayar.get('pazar_stok_tavani'))} adet uygulanıyor.")
    with closing(baglan()) as c:
        for pid in GUNCELLEYICI:
            x = c.execute("SELECT stok, fiyat, zaman FROM pazar_son WHERE pazar=? AND barkod=?", (pid, barkod)).fetchone()
            if x:
                bulgu.append(f"{PAZAR_AD.get(pid, pid)}'e son gönderilen: stok {x[0]}, fiyat {x[1]} ({x[2]})")
    if len(bulgu) == 1:
        bulgu.append("Panelde stoğu sıfırlayan bir ayar bulunamadı. Stok sistemde sıfır değilse pazara gönderim yapılmamış olabilir: pazarın İşlemler sayfasında 'Tam Senkronizasyon'a bas.")
    return bulgu


def tedarikci_stok_dagilimi(esik):
    df = urunleri_oku()
    if df.empty:
        return pd.DataFrame()
    g = df.groupby("tedarikci")["stok"]
    return pd.DataFrame({"Ürün": g.size(), "Stok 0": g.apply(lambda x: int((x <= 0).sum())),
                         f"Stok 1-{max(esik, 1)}": g.apply(lambda x: int(((x > 0) & (x <= max(esik, 1))).sum())),
                         f"Stok >{max(esik, 1)}": g.apply(lambda x: int((x > max(esik, 1)).sum()))})


def anasayfa():
    st.title("🦅 ŞahEntegre - Mağaza ve Pazar Yeri Özeti")
    df = urunleri_oku()
    esik = _i(ayarlar.get("kritik_esik")) or 3
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Toplam Ürün", f"{len(df):,}")
    c2.metric("Stokta Olanlar", f"{int((df['stok'] > 0).sum()):,}" if not df.empty else "0")
    c3.metric(f"Kritik Stok (≤{esik})", f"{int(df['stok'].between(1, esik).sum()):,}" if not df.empty else "0")
    c4.metric("Tedarikçi", len(ayarlar["tedarikciler"]))
    ana_siparis_kutulari()
    toplu_stok_fiyat_paneli("ana")
    st.markdown("### 🛒 Pazar Yeri Bağlantı Durumları")
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
                durum = "🟢 Anahtarlar tanımlı" if bagli else "🔴 API Bilgileri Eksik"
                st.markdown(
                    f'<div style="background:{renk}; border-radius:14px; padding:14px; border-left:6px solid {p_["renk"]}; margin-bottom:10px;">'
                    f'<h4 style="margin:0; color:#1e293b; font-size:16px;">{p_["ikon"]} {p_["ad"]}</h4>'
                    f'<p style="margin:6px 0 0 0; font-weight:600; color:#475569; font-size:13px;">{durum}</p></div>',
                    unsafe_allow_html=True,
                )
                if gen(st.button, "Yönet / İşlemler", key=f"kutu_git_{pid_}"):
                    git_pazar(pid_, "islemler")
                    st.rerun()
    st.caption("Not: 'Anahtarlar tanımlı' yalnızca bilgilerin girildiğini gösterir; gerçek doğrulama için Genel Ayarlar'daki Bağlantı Testi'ni kullanın.")


def main():
    global ayarlar
    db_olustur()
    arka_plan_baslat()
    ayarlar = ayar_oku()  # her çalışmada taze: arka plan ve diğer oturumlarla tutarlı

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

    kapali_oto = [adx for adx, anah, pidx in OTO_ANAHTAR if pazar_bagli(ayarlar, pidx) and not ayarlar.get(anah)]
    if kapali_oto:
        st.warning("⚠️ Otomatik stok/fiyat güncelleme KAPALI: " + ", ".join(kapali_oto)
                   + ". Tedarikçiden stok gelse bile bu pazarlara kendiliğinden gitmez. Açmak için o pazarın 'Genel Ayarları' sayfasındaki 'her senkronizasyondan sonra otomatik güncelle' düğmesini açın.")
    st.sidebar.title("🦅 ŞahEntegre")
    if sifre:
        gen(st.sidebar.button, "🚪 Çıkış Yap", key="btn_cikis_yap", type="secondary", on_click=cikis_yap)
    else:
        st.sidebar.warning("⚠️ APP_PASSWORD tanımlı değil: panel şifresiz açık! API anahtarları risk altında.")
    st.sidebar.markdown("---")
    for kid, etk, _ in ANA_MENU:
        gen(st.sidebar.button, etk, key=f"nav_{kid}", type="primary" if st.session_state["sayfa"] == kid else "secondary", on_click=git, args=(kid,))
    for pid, p in PAZAR.items():
        acik = st.session_state["acik_pazar"] == pid
        ok_ikon = "▾" if acik else "▸"
        gen(st.sidebar.button, f"{p['ikon']} {p['ad']}  {ok_ikon}", key=f"navp_{pid}", on_click=ac_kapa, args=(pid,))
        if acik:
            for alt, etk, ik in ALT:
                sid = f"{pid}:{alt}"
                gen(st.sidebar.button, f"{ik} {p['ad']} {etk}", key=f"sub_{pid}_{alt}",
                    type="primary" if st.session_state["sayfa"] == sid else "secondary", on_click=git, args=(sid,))
    gen(st.sidebar.button, "⚙️ Ayarlar", key="nav_Ayarlar", type="primary" if st.session_state["sayfa"] == "Ayarlar" else "secondary", on_click=git, args=("Ayarlar",))

    acil_kontrol_kenar()
    guvenlik_paneli()
    sayfa = st.session_state["sayfa"]
    if sayfa == "Anasayfa":
        anasayfa()
    elif sayfa == "Bildirim":
        st.title("🔔 Bildirimler")
        gunluk_sayfasi()
    elif sayfa == "Urunler":
        urunler_sayfasi()
    elif sayfa == "Kritik":
        st.title("🔄 Oto Kritik Stok")
        st.caption("Bu eşik, her tedarikçi senkronizasyonunda uygulanır: stok eşiğe eşit ya da eşiğin altındaysa 0 gönderilir (ör. eşik 3 ise 3 adet de 0 gider).")
        esik = st.number_input("Kritik stok eşiği:", 0, 50, _i(ayarlar.get("kritik_esik")))
        if int(esik) != _i(ayarlar.get("kritik_esik")):
            ayarlar["kritik_esik"] = int(esik)
            ayar_yaz(ayarlar)
            st.rerun()
    elif sayfa == "Ayarlar":
        st.title("⚙️ Ayarlar")
        t1, t2, t3 = st.tabs(["Tedarikçiler & XML", "Genel & Yedek", "Senkron Günlüğü"])
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
