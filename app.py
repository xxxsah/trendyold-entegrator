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
    "kritik_esik": 0,
    "oto_senkron": True,
    "tr_oto_guncelle": False,
}

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
    if env:
        return env
    try:
        if ad.upper() in st.secrets:
            return str(st.secrets[ad.upper()])
    except Exception:
        pass
    return ayarlar.get("kimlik", {}).get(ad, "")

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
        c.commit()

db_olustur()

def log_yaz(tedarikci, durum, mesaj=""):
    with closing(baglan()) as c:
        c.execute(
            "INSERT INTO senkron_log (zaman, tedarikci, durum, mesaj) VALUES (?,?,?,?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), tedarikci, durum, str(mesaj)[:500]),
        )
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
        raise ValueError("XML'den geçerli ürün çıkmadı.")
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

def tumunu_senkronla():
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
    if ayarlar.get("tr_oto_guncelle") and any(x[1] for x in sonuclar):
        try:
            trendruum_oto_guncelle(ayarlar)
        except Exception as e:
            log_yaz("Trendruum", "HATA", e)
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
# TRENDRUUM
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
                cakisan = set(re.findall(r"(\d{6,})\W{0,4}barkodu", metin))
                var = [u for u in grup if u["children_products"][0]["barcode"] in cakisan]
                if var:
                    var_olan += [u["model_code"] for u in var]
                    grup = [u for u in grup if u not in var]
                    loglar.append(f"ℹ️ Paket {no}: {len(var)} ürün mağazada zaten kayıtlı, atlandı")
                    continue
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 * (deneme + 1))
                continue
            loglar.append(f"❌ Paket {no}: HTTP {r.status_code} {r.text[:500]}")
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
    items = [{"barcode": sabit_barkod(r["barkod"]), "price": float(r["satis_fiyati"]),
              "stock": int(r["stok"])} for _, r in df.iterrows() if r["satis_fiyati"] > 0]
    toplam = max(1, (len(items) + 999) // 1000)
    guncel, hata, ornek, loglar = 0, 0, [], []
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
        elif r.status_code == 200:
            try:
                d = r.json().get("data") or {}
            except Exception:
                d = {}
            guncel += int(d.get("updated_count", 0))
            hata += int(d.get("failed_count", 0))
            ornek += [str(e)[:200] for e in (d.get("errors") or [])[:3]]
            loglar.append(f"✅ Paket {no}: {d.get('updated_count', 0)} güncellendi, {d.get('failed_count', 0)} hata")
        else:
            hata += len(grup)
            loglar.append(f"❌ Paket {no}: HTTP {r.status_code} {r.text[:500]}")
        if ilerleme:
            ilerleme(no / toplam)
    return guncel, hata, ornek[:5], loglar

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
    log_yaz("Trendruum", "OK", f"{g} ürün güncellendi, {h} hata/bulunamadı")

# ---------------------------------------------------------------
# TRENDYOL
# ---------------------------------------------------------------
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
    ok, log = 0, []
    for i in range(0, len(items), 1000):
        r = requests.post(f"{TY_BASE}/inventory/sellers/{seller}/products/price-and-inventory",
                          json={"items": items[i:i + 1000]},
                          headers=trendyol_header(seller, key, secret), timeout=60)
        if r.status_code == 200:
            ok += len(items[i:i + 1000])
            log.append(f"✅ {i // 1000 + 1}. paket gönderildi")
        else:
            log.append(f"❌ {i // 1000 + 1}. paket HTTP {r.status_code}: {r.text[:300]}")
    return ok, log

# ---------------------------------------------------------------
# ŞİFRE KORUMASI
# ---------------------------------------------------------------
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

# ---------------------------------------------------------------
# YAN MENÜ
# ---------------------------------------------------------------
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

st.sidebar.title("👑 ŞahEntegre")
st.sidebar.caption("Sürüm: v7 (Stabil)")

TEMA_CSS = """
<style>
[data-testid="stHeader"]{background:#1e2a4a;}
[data-testid="stHeader"] button svg{fill:#fff;color:#fff;}
[data-testid="stSidebar"]{background:#f4f7fb;}
[data-testid="stSidebar"] div[role="radiogroup"]{gap:8px;}
[data-testid="stSidebar"] div[role="radiogroup"] > label{
  border-radius:10px;padding:12px 14px;margin:0;width:100%;
  box-shadow:0 1px 3px rgba(0,0,0,.10);border:1px solid rgba(0,0,0,.04);}
[data-testid="stSidebar"] div[role="radiogroup"] > label div:first-child{display:none;}
[data-testid="stSidebar"] div[role="radiogroup"] > label p{font-weight:600;color:#1e293b;font-size:15px;}
[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked){
  background:linear-gradient(90deg,#2563eb,#4f46e5) !important;}
[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) p{color:#fff !important;}
h1,h2,h3{color:#1e3a8a;}
[data-testid="stMetric"]{background:#fff;border-radius:14px;padding:14px 16px;
  box-shadow:0 2px 8px rgba(30,64,175,.14);border-left:5px solid #2563eb;}
.stButton>button{border-radius:10px;font-weight:600;}
.stButton>button[kind="primary"]{background:linear-gradient(90deg,#2563eb,#4f46e5);border:0;color:#fff;}
</style>
"""
st.markdown(TEMA_CSS, unsafe_allow_html=True)

MENU_IKON = {
    "Anasayfa": "🏠", "Ürünler": "📦", "Tedarikçiler & XML": "🔗", "Trendruum": "🛒",
    "Trendyol": "🔴", "Hepsiburada": "🟠", "İdefix": "🟢", "Senkron Günlüğü": "📋", "🤖 ŞahAI": "🤖"
}
sayfa = st.sidebar.radio(
    "Menü",
    ["Anasayfa", "Ürünler", "Tedarikçiler & XML", "Trendruum", "Trendyol",
     "Hepsiburada", "İdefix", "Senkron Günlüğü", "🤖 ŞahAI"],
    format_func=lambda x: f"{MENU_IKON.get(x, '')}  {x}".strip(),
    label_visibility="collapsed",
)
st.sidebar.markdown("---")
yedek = {k: v for k, v in ayarlar.items() if k != "kimlik"}
st.sidebar.download_button("Ayar Yedeği (.json)",
                           json.dumps(yedek, ensure_ascii=False, indent=2).encode("utf-8"),
                           "sahentegre_ayarlar.json", "application/json", use_container_width=True)

def urunleri_oku():
    with closing(baglan()) as c:
        return pd.read_sql("SELECT * FROM urunler", c)

# ---------------------------------------------------------------
# ANASAYFA
# ---------------------------------------------------------------
if sayfa == "Anasayfa":
    st.title("👑 Mağaza ve Pazar Yeri Özeti")
    df = urunleri_oku()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Toplam Ürün", f"{len(df):,}")
    c2.metric("Stokta", f"{(df['stok'] > 0).sum():,}" if not df.empty else "0")
    c3.metric("Kritik (1-2 adet)", f"{df['stok'].between(1, 2).sum():,}" if not df.empty else "0")
    c4.metric("Tedarikçi", len(ayarlar["tedarikciler"]))

    st.subheader("🛒 Pazar Yeri Siparişleri")
    ty_s, ty_k, ty_x = (kimlik(ayarlar, "trendyol_seller_id"), kimlik(ayarlar, "trendyol_key"), kimlik(ayarlar, "trendyol_secret"))
    tr_k, tr_x = kimlik(ayarlar, "trendruum_key"), kimlik(ayarlar, "trendruum_secret")
    if st.button("🔄 Siparişleri Yenile"):
        yeni_ozet = {}
        if ty_s and ty_k and ty_x:
            try:
                yeni_ozet["Trendyol"] = len(trendyol_siparisler(ty_s, ty_k, ty_x))
            except Exception as e:
                yeni_ozet["Trendyol"] = str(e)[:50]
        if tr_k and tr_x:
            try:
                j = trendruum_siparisler(trendruum_token(tr_k, tr_x), "new")
                veri = j.get("data", j)
                if isinstance(veri, dict):
                    veri = next((v for v in veri.values() if isinstance(v, list)), [])
                yeni_ozet["Trendruum"] = len(veri)
            except Exception as e:
                yeni_ozet["Trendruum"] = str(e)[:50]
        st.session_state["sip_ozet"] = yeni_ozet
    ozet = st.session_state.get("sip_ozet", {})

    def durum_html(ad, bagli):
        if not bagli:
            return '<div class="pz-yakin">Bağlantı bekleniyor</div>'
        v = ozet.get(ad)
        if v is None:
            return '<div class="pz-yok">Yenile\'ye basın</div>'
        if isinstance(v, str):
            return f'<div class="pz-chip pz-kirmizi">⚠️ {v}</div>'
        if v == 0:
            return '<div class="pz-yok">Sipariş yok</div>'
        return f'<div class="pz-chip pz-mavi">🚚 {v} Yeni Sipariş</div>'

    yakin = '<div class="pz-yakin">Çok yakında</div>'
    kartlar = [
        ("HEPSİBURADA", "#f97316", "🛍️", yakin),
        ("TRENDYOL", "#e5391c", "🧡", durum_html("Trendyol", bool(ty_s and ty_k and ty_x))),
        ("ÇİÇEKSEPETİ", "#db2777", "🌸", yakin),
        ("PTT AVM", "#ea8a0c", "📮", yakin),
        ("N11", "#e0392b", "🔴", yakin),
        ("PAZARAMA", "#0e86d4", "🏪", yakin),
        ("İDEFİX", "#1a9a4a", "📚", yakin),
        ("TRENDRUUM", "#7c3aed", "🛒", durum_html("Trendruum", bool(tr_k and tr_x))),
    ]
    kart_css = """<style>
    .pz-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:12px;}
    .pz{border:2px solid #1f2937;border-radius:10px;overflow:hidden;background:#fff;box-shadow:0 2px 6px rgba(0,0,0,.22);min-height:105px;}
    .pz-h{color:#fff;font-weight:800;padding:8px;font-size:13px;}
    .pz-b{padding:8px;}
    .pz-yok{color:#94a3b8;font-style:italic;font-size:13px;}
    .pz-yakin{border:1px dashed #cbd5e1;border-radius:6px;padding:8px;text-align:center;color:#334155;font-size:13px;font-weight:600;background:#f8fafc;}
    .pz-chip{border-radius:6px;padding:6px 8px;font-size:13px;font-weight:700;}
    .pz-mavi{background:#dbeafe;color:#1d4ed8;border:1px solid #93c5fd;}
    .pz-kirmizi{background:#fee2e2;color:#b91c1c;border:1px solid #fca5a5;}
    </style>"""
    html = "".join(f'<div class="pz"><div class="pz-h" style="background:{renk}">{ikon} {ad}</div><div class="pz-b">{govde}</div></div>' for ad, renk, ikon, govde in kartlar)
    st.markdown(kart_css + f'<div class="pz-grid">{html}</div>', unsafe_allow_html=True)

# ---------------------------------------------------------------
# ÜRÜNLER
# ---------------------------------------------------------------
elif sayfa == "Ürünler":
    st.title("Ürün Yönetimi ve Stoklar")
    df = urunleri_oku()
    if df.empty:
        st.info("Henüz ürün yok.")
    else:
        a, b, c = st.columns(3)
        a.metric("Toplam", f"{len(df):,}")
        b.metric("Stokta", f"{(df['stok'] > 0).sum():,}")
        c.metric("Tükenen", f"{(df['stok'] <= 0).sum():,}")
        ara = st.text_input("🔍 Ara (ad / barkod)")
        sadece = st.checkbox("Sadece stokta olanlar")
        goster = st.selectbox("Kaç ürün gösterilsin", [50, 100, 250, 500, 1000], index=1)
        g = df
        if ara:
            g = g[g["urun_adi"].str.contains(ara, case=False, na=False, regex=False) | g["barkod"].str.contains(ara, case=False, na=False, regex=False)]
        if sadece:
            g = g[g["stok"] > 0]
        st.dataframe(g.head(goster).drop(columns=["id"]).rename(columns={
            "gorsel": "Görsel", "tedarikci": "Tedarikçi", "barkod": "Barkod", "urun_adi": "Ürün Adı",
            "stok": "Stok", "alis_fiyati": "Alış", "satis_fiyati": "Satış", "kategori": "Kategori"}),
            column_config={"Görsel": st.column_config.ImageColumn("Görsel", width="small")},
            use_container_width=True, hide_index=True)

# ---------------------------------------------------------------
# TEDARİKÇİLER & XML
# ---------------------------------------------------------------
elif sayfa == "Tedarikçiler & XML":
    st.title("Tedarikçi ve XML Ayarları")
    tedarikciler = ayarlar["tedarikciler"]
    with st.expander("➕ Yeni Tedarikçi", expanded=not tedarikciler):
        t_ad = st.text_input("Tedarikçi Adı")
        t_link = st.text_input("XML Linki")
        if st.button("Kaydet", type="primary"):
            if t_ad.strip() and t_link.strip():
                tedarikciler[t_ad.strip()] = {"link": t_link.strip(), "harita": {}, "marj": 30.0, "sabit_ek": 0.0}
                ayar_yaz(ayarlar)
                st.rerun()

    if tedarikciler:
        if st.button("🔄 Tümünü Şimdi Senkronla", type="primary"):
            with st.spinner("Güncelleniyor..."):
                for ad, ok, msg in tumunu_senkronla():
                    (st.success if ok else st.error)(f"{ad}: {msg}")

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
                        "kod": sec("Barkod / SKU", ["barkod", "barcode", "sku", "kod"], "kod"),
                        "ad": sec("Ürün Adı", ["urunadi", "name", "title", "ad"], "ad"),
                        "stok": sec("Stok", ["stok", "stock", "quantity"], "stok"),
                        "fiyat": sec("Alış Fiyatı", ["fiyat", "price", "alis"], "fiyat"),
                        "gorsel": sec("Görsel", ["image", "resim", "gorsel"], "gorsel"),
                        "kategori": sec("Kategori", ["kategori", "category", "grup"], "kategori"),
                    }
                    marj = st.number_input("Kâr Marjı (%)", 0.0, 500.0, float(bilgi.get("marj", 30.0)), key=f"{ad}_marj")
                    sabit = st.number_input("Sabit Ek / Kargo (TL)", 0.0, 5000.0, float(bilgi.get("sabit_ek", 0.0)), key=f"{ad}_sabit")
                    if harita != eski or marj != bilgi.get("marj") or sabit != bilgi.get("sabit_ek"):
                        bilgi.update({"harita": harita, "marj": marj, "sabit_ek": sabit})
                        ayar_yaz(ayarlar)
                        st.success("Kaydedildi.")
                except Exception as e:
                    st.warning(f"XML analiz edilemedi: {e}")
                if st.button(f"🗑️ {ad} sil", key=f"sil_{ad}"):
                    tedarikciler.pop(ad, None)
                    ayar_yaz(ayarlar)
                    st.rerun()

# ---------------------------------------------------------------
# TRENDRUUM
# ---------------------------------------------------------------
elif sayfa == "Trendruum":
    st.title("Trendruum Entegrasyonu")
    key = gizli_input("API Key (Client ID)", "trendruum_key")
    secret = gizli_input("API Secret", "trendruum_secret")
    brand = gizli_input("Brand ID", "trendruum_brand", parola=False)
    cat = gizli_input("Varsayılan Kategori ID", "trendruum_category", parola=False)

    miktar = st.selectbox("Gönderilecek ürün", ["Tek ürün (test)", "İlk 100", "İlk 500", "Tümü"])
    if st.button("📤 Trendruum'a Gönder", type="primary"):
        if not (key and secret and brand and cat):
            st.error("Key, Secret, Brand ID ve Kategori ID zorunlu.")
        else:
            df = urunleri_oku()
            df = df.head({"Tek ürün (test)": 1, "İlk 100": 100, "İlk 500": 500}.get(miktar, len(df)))
            if df.empty:
                st.warning("Gönderilecek ürün yok.")
            else:
                try:
                    token = trendruum_token(key, secret)
                    liste, atlanan = trendruum_urun_listesi(df, ayarlar, brand, cat)
                    bar, kutu = st.progress(0), st.empty()
                    ok, top, loglar = trendruum_gonder(liste, token, lambda p, l: (bar.progress(p), kutu.code("\n".join(l[-15:]))))
                    st.success(f"Tamamlandı: {ok}/{top} paket başarılı.")
                except Exception as e:
                    st.error(f"Hata: {e}")

    st.subheader("🔄 Stok / Fiyat Güncelle")
    if st.button("Stok/Fiyatı Şimdi Gönder"):
        if not (key and secret):
            st.error("API Key ve Secret gerekli.")
        else:
            try:
                token = trendruum_token(key, secret)
                bar = st.progress(0)
                g, h, ornek, loglar = trendruum_guncelle(urunleri_oku(), token, lambda p: bar.progress(p))
                st.success(f"{g} ürün güncellendi, {h} hatalı/bulunamadı.")
                if loglar:
                    st.code("\n".join(loglar[-10:]))
            except Exception as e:
                st.error(f"Hata: {e}")

# ---------------------------------------------------------------
# TRENDYOL
# ---------------------------------------------------------------
elif sayfa == "Trendyol":
    st.title("Trendyol Entegrasyonu")
    seller = gizli_input("Satıcı (Seller) ID", "trendyol_seller_id", parola=False)
    key = gizli_input("API Key", "trendyol_key")
    secret = gizli_input("API Secret", "trendyol_secret")
    c1, c2 = st.columns(2)
    if c1.button("📦 Stok/Fiyat Gönder", type="primary"):
        if seller and key and secret:
            try:
                ok, log = trendyol_stok_fiyat(seller, key, secret, urunleri_oku())
                st.success(f"{ok} kalem gönderildi.")
                st.code("\n".join(log))
            except Exception as e:
                st.error(f"Hata: {e}")
    if c2.button("🧾 Yeni Siparişler"):
        try:
            sip = trendyol_siparisler(seller, key, secret)
            st.dataframe(pd.DataFrame([{"Sipariş": s.get("orderNumber"), "Tutar": s.get("totalPrice"), "Durum": s.get("status")} for s in sip]) if sip else pd.DataFrame())
        except Exception as e:
            st.error(f"Hata: {e}")

# ---------------------------------------------------------------
# DİĞER SAYFALAR
# ---------------------------------------------------------------
elif sayfa == "Hepsiburada":
    st.title("Hepsiburada")
    gizli_input("Merchant ID", "hb_merchant_id", parola=False)
    gizli_input("Kullanıcı Adı", "hb_user", parola=False)
    gizli_input("Şifre", "hb_pass")

elif sayfa == "İdefix":
    st.title("İdefix")
    gizli_input("Satıcı ID", "idefix_satici_id", parola=False)
    gizli_input("Token", "idefix_token")
    gizli_input("Secret", "idefix_secret")

elif sayfa == "Senkron Günlüğü":
    st.title("Senkronizasyon Günlüğü")
    with closing(baglan()) as c:
        lg = pd.read_sql("SELECT zaman, tedarikci, durum, mesaj FROM senkron_log ORDER BY id DESC LIMIT 200", c)
    st.dataframe(lg, use_container_width=True, hide_index=True)

else:
    st.title("🤖 ŞahAI Asistanı")
    q = st.chat_input("Stok veya ürün sorgula...")
    if q:
        df = urunleri_oku()
        cevap = f"Toplam {len(df):,} ürün kayıtlı, {(df['stok'] > 0).sum():,} ürün stokta."
        st.chat_message("user").markdown(q)
        st.chat_message("assistant").markdown(cevap)
