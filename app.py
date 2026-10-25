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


def ptt_header(ayar):
    return {
        "access-token": kimlik(ayar, "ptt_token"), "api-key": kimlik(ayar, "ptt_key"),
        "Accept": "application/json", "Content-Type": "application/json",
    }


def ptt_test(key, token):
    if not key or not token:
        return False, "API Key (Shop ID) veya Token eksik."
    try:
        h = {"access-token": token, "api-key": key, "Accept": "application/json"}
        r = requests.get(f"{PTT_BASE}/categories/main", headers=h, timeout=15)
        if r.status_code in (200, 201):
            return True, f"✅ PTT AVM bağlantısı başarılı (HTTP {r.status_code})"
        return False, f"❌ PTT AVM bağlantısı başarısız ({yanit_ozet(r)})"
    except Exception as e:
        return False, f"Bağlantı hatası: {e}"


def ptt_guncelle(ayar, df, ilerleme=None):
    if not (kimlik(ayar, "ptt_key") and kimlik(ayar, "ptt_token")):
        raise RuntimeError("PTT API Key / Token eksik.")
    h = ptt_header(ayar)
    kayit, atlanan = [], 0
    for r in kayit_listesi(df):
        fiyat = _f(r.get("satis_fiyati"))
        if fiyat <= 0:  # satış fiyatı yoksa alış fiyatıyla GÖNDERME (zararına satış riski)
            atlanan += 1
            continue
        b = str(r["barkod"])
        kayit.append((b, {"Barcode": b, "Quantity": max(_i(r.get("stok")), 0), "Price": fiyat}))

    def gonder(grup):
        r = http("POST", f"{PTT_BASE}/product/price-stock-update", json={"items": grup}, headers=h, timeout=30)
        return r.status_code in (200, 201, 202), yanit_ozet(r)

    ok_k, hata_k, loglar = paketle(kayit, 100, gonder, ilerleme, "PTT")
    return _sonuc("ptt", ok_k, hata_k, loglar, atlanan)


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


def trendruum_urun_listesi(df, ayar):
    pa = pa_al(ayar, "trendruum")
    brand, cat_varsayilan, uret, kdv = trendruum_ayar(ayar)
    if not objectid_mi(brand):
        raise ValueError("Trendruum 'Marka ID' geçersiz/boş (24 karakterlik ID olmalı). Genel Ayarlar'dan girin.")
    liste, atlanan = [], 0
    for r in kayit_listesi(df):
        gorsel = str(r.get("gorsel", "")).strip()
        kod = str(r["barkod"]).strip()
        barkod = sabit_barkod(kod, uret)
        fiyat = _f(r.get("satis_fiyati"))
        cat = kategori_id(pa, ayar, r.get("kategori"), "trendruum") or cat_varsayilan
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


def trendruum_gonder(ayar, liste, ilerleme=None):
    token = trendruum_token(kimlik(ayar, "trendruum_key"), kimlik(ayar, "trendruum_secret"))
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    kayit = [(u["model_code"], u) for u in liste]

    def gonder(grup):
        r = http("POST", f"{TR_BASE}/products/bulk", json={"products": grup}, headers=h, timeout=60, tries=2)
        return r.status_code in (200, 201, 202), yanit_ozet(r)

    ok_k, hata_k, loglar = paketle(kayit, 50, gonder, ilerleme, "Trendruum")
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
        return True, f"güncellenen: {guncel if guncel is not None else len(grup)}"

    ok_k, hata_k, loglar = paketle(kayit, 1000, gonder, ilerleme, "Trendruum")
    return _sonuc("trendruum", ok_k, hata_k, loglar, atlanan)


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


def pazara_gonder(ayar, pid, df, ilerleme=None):
    """Stok + fiyat gönderir. Dönüş: (başarılı, hatalı, özet_metin)."""
    ad = PAZAR_AD.get(pid, pid)
    try:
        if pid not in GUNCELLEYICI:
            raise RuntimeError(f"{ad} için entegrasyon yok.")
        if not pazar_bagli(ayar, pid):
            raise RuntimeError(f"{ad} API bilgileri eksik.")
        df = fiyat_artis_uygula(ayar, pid, df)
        ok, hata, loglar = GUNCELLEYICI[pid](ayar, df, ilerleme)
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


def tumunu_senkronla(oto=True):
    if not SENKRON_KILIDI.acquire(blocking=False):
        return [("Sistem", False, "Başka bir senkronizasyon zaten çalışıyor.")]
    try:
        ayar = ayar_oku()
        sonuclar = []
        for ad, bilgi in ayar["tedarikciler"].items():
            try:
                n = tedarikci_senkron(ad, bilgi, _i(ayar.get("kritik_esik")), _i(ayar.get("stok_ust_sinir"), 50))
                log_yaz(ad, "OK", f"{n} ürün güncellendi")
                sonuclar.append((ad, True, f"{n} ürün"))
            except Exception as e:
                log_yaz(ad, "HATA", e)
                sonuclar.append((ad, False, str(e)))
        if oto and any(x[1] for x in sonuclar):
            for _, anahtar_, pid_ in OTO_ANAHTAR:
                if ayar.get(anahtar_) and pazar_bagli(ayar, pid_):
                    try:
                        pazara_gonder(ayar, pid_, urunleri_oku())
                    except Exception:
                        pass  # pazara_gonder zaten günlüğe yazdı
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


def siparis_normalle_hb(p):
    return {
        "pid": "hb", "id": str(p.get("packageId", "")), "no": str(p.get("orderNumber", "")),
        "tarih": tr_tarih(p.get("orderDate")), "durum": durum_kodu("hb", p.get("status")),
        "alici": p.get("recipientName", "Hepsiburada Müşterisi"), "adres": metin(p.get("shippingAddress")),
        "urunler": [{"ad": l.get("productName", "Ürün"), "sku": l.get("merchantSku", ""), "adet": l.get("quantity", 1)}
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
        return [siparis_normalle_hb(x) for x in hb_siparisler(ayar)]
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
                st.error("❌ Hatalı şifre.")
    st.stop()


def secili_urunler(df, anahtar):
    if df.empty or "tedarikci" not in df.columns:
        return df
    liste = sorted(df["tedarikci"].dropna().unique().tolist())
    sec = st.multiselect("Gönderilecek Tedarikçileri Seçin", liste, default=liste, key=f"{anahtar}_ted_sec")
    return df[df["tedarikci"].isin(sec)] if sec else df.iloc[0:0]


def kategori_esleme_editoru(pid):
    pa = pa_al(ayarlar, pid)
    df = urunleri_oku()
    if df.empty or "kategori" not in df.columns:
        st.caption("Kategori eşleştirmesi için önce tedarikçi senkronizasyonu yapın.")
        return
    anaklar = sorted({str(k).split(">>>")[0].strip() for k in df["kategori"].dropna() if str(k).strip()})[:300]
    mevcut = pa.get("kategori_eslesme") or {}
    tablo = pd.DataFrame({
        "Tedarikçi kategorisi": anaklar,
        "Pazar yeri kategori ID": [str(mevcut.get(k, "")) for k in anaklar],
    })
    duz = st.data_editor(tablo, hide_index=True, disabled=["Tedarikçi kategorisi"], key=f"kat_edit_{pid}")
    if gen(st.button, "Eşleştirmeyi kaydet", key=f"kat_kaydet_{pid}"):
        yeni = {str(r["Tedarikçi kategorisi"]): str(r["Pazar yeri kategori ID"]).strip()
                for _, r in duz.iterrows() if str(r["Pazar yeri kategori ID"]).strip()}
        if pid == "trendruum":
            gecersiz = [k for k, v in yeni.items() if not objectid_mi(v)]
            if gecersiz:
                st.error(f"Trendruum kategori ID'si 24 karakterlik olmalı. Hatalı: {', '.join(gecersiz[:5])}")
                return
        pa["kategori_eslesme"] = yeni
        ayar_yaz(ayarlar)
        st.success(f"{len(yeni)} kategori eşleştirmesi kaydedildi.")


def pazar_ayar_formu(pid):
    pa = pa_al(ayarlar, pid)
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
        if pid in ("n11", "idefix", "trendruum"):
            st.markdown("**Ürün oluşturma ayarları**")
            c1, c2, c3 = st.columns(3)
            yeni["category_id"] = c1.text_input("Varsayılan kategori ID", value=str(pa.get("category_id", "") or ""))
            if pid in ("idefix", "trendruum"):
                yeni["brand_id"] = c2.text_input("Marka ID", value=str(pa.get("brand_id", "") or (kimlik(ayarlar, "trendruum_brand") if pid == "trendruum" else "")))
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
        if pid == "trendruum":
            yeni["gecici_barkod"] = st.checkbox("Geçerli barkodu olmayan ürünlere kalıcı geçici barkod üret (869…)", value=bool(pa.get("gecici_barkod", True)))
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
    saat = st.number_input("Senkronizasyon aralığı (saat)", 1, 24, int(_f(ayarlar.get("senkron_saat"), 6.0)))
    st.caption("Aralık değişikliği bir sonraki döngüde geçerli olur.")
    ust = st.number_input("Stok üst sınırı (tedarikçi stoğu bu değerle sınırlanır)", 1, 100000, _i(ayarlar.get("stok_ust_sinir"), 50) or 50)
    oto = st.toggle(f"🤖 Otomatik senkronizasyon ({int(saat)} saatte bir)", value=ayarlar.get("oto_senkron", True))
    if (oto, int(saat), int(ust)) != (ayarlar.get("oto_senkron", True), _i(ayarlar.get("senkron_saat"), 6), _i(ayarlar.get("stok_ust_sinir"), 50)):
        ayarlar.update({"oto_senkron": oto, "senkron_saat": int(saat), "stok_ust_sinir": int(ust)})
        ayar_yaz(ayarlar)

    if st.button("🔄 Tümünü Şimdi Senkronla", type="primary"):
        with st.spinner("Güncelleniyor..."):
            for ad, ok, msg in tumunu_senkronla(oto=False):
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
                "fiyat": sec("Alış Fiyatı", ["fiyat", "price", "alis", "alış"], "fiyat"),
                "gorsel": sec("Görsel", ["image_1", "resim", "image", "gorsel", "görsel", "picture", "foto"], "gorsel"),
                "kategori": sec("Kategori", ["kategori", "category", "cat", "tur", "grup", "maincategory"], "kategori"),
            }
            marj = st.number_input("Kâr Marjı (%)", 0.0, 500.0, float(bilgi.get("marj", 30.0)), 1.0, key=f"{ad}_marj")
            sabit = st.number_input("Sabit Ek / Kargo (TL)", 0.0, 5000.0, float(bilgi.get("sabit_ek", 0.0)), 5.0, key=f"{ad}_sabit")
            if harita != eski or marj != bilgi.get("marj") or sabit != bilgi.get("sabit_ek"):
                bilgi.update({"harita": harita, "marj": marj, "sabit_ek": sabit})
                ayar_yaz(ayarlar)
                st.success("Kaydedildi. Yeni değerler bir sonraki senkronizasyonda ürünlere uygulanır.")


def genel_ayarlar(sifre):
    st.subheader("💾 Yedekleme")
    guvenli = {k: v for k, v in ayarlar.items() if k != "kimlik"}
    guvenli["kimlik"] = {}
    st.download_button("📄 Yedek (API anahtarları HARİÇ)", json.dumps(guvenli, ensure_ascii=False, indent=2).encode("utf-8"),
                       "sahentegre_yedek.json", "application/json")
    with st.expander("🔐 API anahtarları DAHİL yedek"):
        if not sifre:
            st.warning("Anahtarlı yedek için APP_PASSWORD tanımlı olmalı.")
        else:
            girilen = st.text_input("Yönetici şifresini tekrar girin", type="password", key="tam_yedek_sifre")
            if girilen and hmac.compare_digest(girilen.encode(), str(sifre).encode()):
                st.download_button("⬇️ TAM Yedek (gizli bilgiler içerir)", json.dumps(ayarlar, ensure_ascii=False, indent=2).encode("utf-8"),
                                   "sahentegre_tam_yedek.json", "application/json")
            elif girilen:
                st.error("Şifre hatalı.")
    yuklenen = st.file_uploader("♻️ Yedek dosyasını geri yükle (.json)", type="json", key="yedek_yukle")
    if yuklenen is not None and st.button("Geri Yükle", key="yedek_btn"):
        try:
            veri_y = json.loads(yuklenen.getvalue().decode("utf-8"))
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


def toplu_urun_paneli(pid):
    """Ürün OLUŞTURMA (N11, İdefix, Trendruum)."""
    ad = PAZAR_AD[pid]
    if not pazar_bagli(ayarlar, pid):
        st.warning(f"{ad} API bilgileri eksik. 'Genel Ayarları' sayfasından girin.")
        return
    st.info("Marka/kategori/KDV ayarları ve kategori eşleştirmesi için 'Genel Ayarları' sayfasını kullanın.")
    df = secili_urunler(urunleri_oku(), pid)
    if not df.empty and st.checkbox("Sadece stokta olanlar", value=True, key=f"{pid}_stoklu"):
        df = df[df["stok"] > 0]
    mod = st.selectbox("Gönderim Modu", ["Tek ürün (Test)", "Tüm Ürünler"], key=f"{pid}_mod")
    df = fiyat_artis_uygula(ayarlar, pid, df)
    if mod.startswith("Tek"):
        df = df.head(1)
    try:
        liste, atlanan = {
            "n11": n11_urun_listesi, "idefix": idefix_urun_listesi, "trendruum": trendruum_urun_listesi,
        }[pid](df, ayarlar)
    except ValueError as e:
        st.error(str(e))
        return
    st.write(f"Gönderilecek ürün: **{len(liste):,}** (Atlanan: {atlanan} — görsel/fiyat/barkod/kategori eksik)")
    if not liste:
        return
    onay = st.checkbox("Göndermeyi onaylıyorum", key=f"{pid}_onay")
    if gen(st.button, f"🚀 {ad}'e Ürünleri Gönder", type="primary", key=f"{pid}_toplu_btn", disabled=not onay):
        pbar, log_k = st.progress(0.0), st.empty()

        def ilerleme(p, loglar):
            pbar.progress(min(p, 1.0))
            log_k.code("\n".join(loglar[-12:]))

        try:
            gonder = {"n11": n11_urun_gonder, "idefix": idefix_gonder, "trendruum": trendruum_gonder}[pid]
            ok, hata, loglar = gonder(ayarlar, liste, ilerleme)
        except Exception as e:
            log_yaz(ad, "HATA", f"Ürün gönderimi: {e}")
            st.error(f"Hata: {e}")
            return
        log_yaz(ad, "OK" if hata == 0 else ("KISMİ" if ok else "HATA"), f"Ürün oluşturma: {ok} ürün iletildi, {hata} ürün hatalı.")
        (st.success if hata == 0 else st.warning)(f"{ok} ürün iletildi, {hata} ürün hatalı. (API kabulü = ürün onayı değildir; pazar yeri panelinden kontrol edin.)")


def pazar_islemler(pid):
    p = PAZAR[pid]
    ad = p["ad"]
    bagli = pazar_bagli(ayarlar, pid)
    st.title(f"{p['ikon']} {ad} İşlemleri")
    if not bagli:
        st.warning("API bilgileri eksik: 'Genel Ayarları' sayfasından girip kaydedin.")

    k = f"islem_{pid}"
    c1, c2, c3 = st.columns(3)
    if gen(c1.button, "🔄 Tam Senkronizasyon", key=f"b1_{pid}", type="primary", disabled=not bagli, help="Önce tedarikçi XML'lerini yeniler, sonra stok/fiyatı bu pazara gönderir."):
        st.session_state[k] = None
        with st.spinner("Tedarikçiler güncelleniyor..."):
            for tad, ok_, msg in tumunu_senkronla(oto=False):
                (st.success if ok_ else st.error)(f"{tad}: {msg}")
        gonder_ve_goster(pid)
    if gen(c2.button, "⚠️ Kritik Stok Sıfırla", key=f"b2_{pid}"):
        st.session_state[k] = "kritik"
    if gen(c3.button, "🔢 Tüm Stok/Fiyatları Güncelle", key=f"b3_{pid}", disabled=not bagli, help="Veritabanındaki mevcut stok/fiyatı bu pazara gönderir."):
        st.session_state[k] = None
        gonder_ve_goster(pid)

    if pid in ("n11", "idefix", "trendruum"):
        if gen(st.button, "📤 Toplu Ürün Oluştur / Gönder", key=f"b4_{pid}"):
            st.session_state[k] = "toplu"

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

    with closing(baglan()) as c:
        d = pd.read_sql("SELECT durum, COUNT(*) AS adet FROM pazar_durum WHERE pazar=? GROUP BY durum", c, params=(pid,))
    if not d.empty:
        st.caption("Son gönderim durumu (barkod bazında): " + ", ".join(f"{r.durum}: {r.adet}" for r in d.itertuples()))


def gonder_ve_goster(pid):
    ad = PAZAR_AD[pid]
    pbar, log_k = st.progress(0.0), st.empty()

    def ilerleme(p, loglar):
        pbar.progress(min(p, 1.0))
        log_k.code("\n".join(loglar[-8:]))

    try:
        with st.spinner(f"{ad} stok/fiyat gönderiliyor..."):
            ok, hata, _ = pazara_gonder(ayarlar, pid, urunleri_oku(), ilerleme)
        if ok == 0 and hata == 0:
            st.warning("Gönderilecek ürün bulunamadı (önce tedarikçi senkronizasyonu yapın / fiyatı olmayan ürünler atlanır).")
        else:
            (st.success if hata == 0 else st.warning)(f"{ad}: {ok} ürün iletildi, {hata} hata. (API kabulü = pazar yerinde işlendi demek değildir.)")
    except Exception as e:
        st.error(f"Hata: {e}")


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
    if pid in ("n11", "idefix", "trendruum"):
        with st.expander("🗂️ Kategori eşleştirme (tedarikçi kategorisi → pazar yeri kategori ID)"):
            kategori_esleme_editoru(pid)


def pazar_siparis(pid):
    p = PAZAR[pid]
    st.title(f"{p['ikon']} {p['ad']} Sipariş Yönetimi")
    if pid not in ("trendyol", "n11", "hb", "trendruum"):
        st.info(f"{p['ad']} için sipariş çekme henüz desteklenmiyor.")
        return
    if gen(st.button, "🔄 Siparişleri Yeniden Çek", type="primary", key=f"sp_cek_{pid}"):
        try:
            with st.spinner("Siparişler çekiliyor..."):
                st.session_state[f"sip_{pid}"] = siparis_cek(ayarlar, pid)
            st.success("Siparişler güncellendi.")
        except Exception as e:
            st.error(f"Hata: {e}")
    liste = st.session_state.get(f"sip_{pid}")
    if liste is None:
        st.info("Henüz sipariş çekilmedi.")
        return
    if not liste:
        st.info("Açık sipariş bulunamadı.")
        return
    st.metric("Sipariş sayısı", len(liste))
    for o in liste:
        with st.container(border=True):
            st.markdown(f"### Sipariş No: {o['no']} · {o['tarih']}")
            st.markdown(f"**Durum:** {DURUM_ETIKET.get(o['durum'], o['durum'])} | **Alıcı:** {o['alici']} | **Tutar:** {o.get('tutar')} ₺")
            st.markdown(f"**Adres:** {o['adres']}")
            if o.get("kargo") or o.get("barkod"):
                st.markdown(f"**Kargo:** {o.get('kargo', '')} {o.get('barkod', '')}")
            for u in o.get("urunler", []):
                st.markdown(f"- {u['ad']} — `{u['sku']}` × {u['adet']}")


def urunler_sayfasi():
    st.title("📦 Sistemdeki Ürünler")
    df = urunleri_oku()
    if df.empty:
        st.warning("Sistemde henüz kayıtlı ürün bulunmuyor.")
        return
    col_f1, col_f2 = st.columns([1, 2])
    with col_f1:
        secenek = ["Tüm Bayiler"] + sorted(df["tedarikci"].dropna().unique().tolist())
        secili = st.selectbox("🏬 Tedarikçi / Bayi Seçin", secenek)
    with col_f2:
        ara = st.text_input("🔍 Ürün Adı veya Barkod ile Ara", "")
    f = df
    if secili != "Tüm Bayiler":
        f = f[f["tedarikci"] == secili]
    if ara:
        f = f[f["urun_adi"].str.contains(ara, case=False, na=False, regex=False) | f["barkod"].str.contains(ara, case=False, na=False, regex=False)]
    sayfa_boyu = 20
    toplam_sayfa = max(1, -(-len(f) // sayfa_boyu))
    st.info(f"Toplam **{len(f):,}** ürün listeleniyor.")
    no = int(st.number_input("Sayfa", 1, toplam_sayfa, 1, key="urun_sayfa_no"))
    f = f.iloc[(no - 1) * sayfa_boyu: no * sayfa_boyu].reset_index(drop=True)
    cols = st.columns(2)
    for idx, row in f.iterrows():
        with cols[idx % 2]:
            with st.container(border=True):
                st.subheader(row.get("urun_adi", "İsimsiz Ürün"))
                img = row.get("gorsel", "")
                if img and str(img).startswith("http"):
                    gen(st.image, img)
                else:
                    st.write("📷 *Görsel Bulunamadı*")
                a, b = st.columns(2)
                with a:
                    st.write(f"**Barkod:** `{row.get('barkod', '-')}`")
                    st.write(f"**Tedarikçi:** `{row.get('tedarikci', '-')}`")
                    st.write(f"**Stok:** `{row.get('stok', 0)} adet`")
                with b:
                    alis, satis = _f(row.get("alis_fiyati")), _f(row.get("satis_fiyati"))
                    st.markdown(f"🔴 **Alış:** {alis:.2f} TL")
                    st.markdown(f"🟢 **Satış:** {satis:.2f} TL")
                    if satis > alis > 0:
                        st.caption(f"💡 Tahmini Kâr: +{satis - alis:.2f} TL")


def anasayfa():
    st.title("🦅 ŞahEntegre - Mağaza ve Pazar Yeri Özeti")
    df = urunleri_oku()
    esik = _i(ayarlar.get("kritik_esik")) or 3
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Toplam Ürün", f"{len(df):,}")
    c2.metric("Stokta Olanlar", f"{int((df['stok'] > 0).sum()):,}" if not df.empty else "0")
    c3.metric(f"Kritik Stok (≤{esik})", f"{int(df['stok'].between(1, esik).sum()):,}" if not df.empty else "0")
    c4.metric("Tedarikçi", len(ayarlar["tedarikciler"]))
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
        gen(st.sidebar.button, f"{p['ikon']} {p['ad']}  {'▾' if acik else '▸'}", key=f"navp_{pid}", on_click=ac_kapa, args=(pid,))
        if acik:
            for alt, etk, ik in ALT:
                sid = f"{pid}:{alt}"
                gen(st.sidebar.button, f"{ik} {p['ad']} {etk}", key=f"sub_{pid}_{alt}",
                    type="primary" if st.session_state["sayfa"] == sid else "secondary", on_click=git, args=(sid,))
    gen(st.sidebar.button, "⚙️ Ayarlar", key="nav_Ayarlar", type="primary" if st.session_state["sayfa"] == "Ayarlar" else "secondary", on_click=git, args=("Ayarlar",))

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
        st.caption("Bu eşik, her tedarikçi senkronizasyonunda uygulanır: stok eşiğin altındaysa 0 gönderilir.")
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
