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
SENKRON_ARALIK = 6 * 3600
KILIT = threading.Lock()

KIMLIK_ALANLARI = [
    "trendruum_key", "trendruum_secret", "trendruum_brand", "trendruum_category",
    "trendyol_seller_id", "trendyol_key", "trendyol_secret",
    "hb_merchant_id", "hb_user", "hb_pass",
    "idefix_satici_id", "idefix_token", "idefix_secret",
]

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
        veri["tedarikciler"] = {k: v for k, v in veri.items() if isinstance(v, dict) and "link" in v}
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
        c.commit()

db_olustur()

def log_yaz(tedarikci, durum, mesaj=""):
    with closing(baglan()) as c:
        c.execute("INSERT INTO senkron_log (zaman, tedarikci, durum, mesaj) VALUES (?,?,?,?)",
                  (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), tedarikci, durum, str(mesaj)[:500]))
        c.commit()

def etiket(tag):
    return tag.split("}", 1)[-1]

def indir(url):
    istek = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/xml,text/xml,*/*", "Accept-Encoding": "gzip",
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
        else:
            duzlestir(cocuk, yol + ".", cikti)
    return cikti

def urun_dugumu_bul(kok):
    ebeveyn = {c: p for p in kok.iter() for c in p}
    sayac = Counter(etiket(e.tag) for e in kok.iter() if len(e) > 0)
    adaylar = {t for t, n in sayac.items() if n >= 2 and t != etiket(kok.tag)}
    dis = {etiket(e.tag) for e in kok.iter() if etiket(e.tag) in adaylar}
    return max(dis, key=lambda t: sayac[t]) if dis else None

def xml_oku(veri):
    kok = ET.fromstring(veri)
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
    for a in anahtarlar:
        for k in kolonlar:
            if k.lower() == a:
                return k
    return "(yok)"

def ilk_gorsel(df, secili):
    adaylar = [secili] if secili != "(yok)" else []
    adaylar += [c for c in df.columns if c != secili and "image" in c.lower() and "count" not in c.lower()]
    sonuc = pd.Series([""] * len(df), index=df.index)
    for c in adaylar:
        if c in df.columns:
            deger = df[c].astype(str).str.split("|").str[0].str.strip()
            sonuc = sonuc.where(sonuc != "", deger)
    return sonuc.str.replace("http://", "https://", regex=False)

def normalle(tedarikci, df, harita, marj, sabit_ek, kritik_esik=0):
    def kol(ad):
        k = harita.get(ad, "(yok)")
        return df[k] if k != "(yok)" and k in df.columns else pd.Series([""] * len(df), index=df.index)

    alis = kol("fiyat").map(sayi)
    satis = alis * (1 + marj / 100) + sabit_ek
    stok = kol("stok").map(sayi).clip(lower=0).astype(int)
    if kritik_esik and kritik_esik > 0:
        stok = stok.where(stok > kritik_esik, 0)
    kk = harita.get("kategori", "(yok)")
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
    return out[(out["barkod"] != "") & (out["urun_adi"] != "")].drop_duplicates(subset=["barkod"], keep="first")

def tedarikci_senkron(ad, bilgi, kritik_esik=0):
    df_ham = xml_oku(indir(bilgi["link"]))
    df = normalle(ad, df_ham, bilgi.get("harita", {}), float(bilgi.get("marj", 30.0)),
                  float(bilgi.get("sabit_ek", 0.0)), kritik_esik)
    if df.empty:
        raise ValueError("XML'den ürün çıkmadı.")
    with closing(baglan()) as c:
        c.execute("BEGIN")
        c.execute("DELETE FROM urunler WHERE tedarikci = ?", (ad,))
        c.executemany(
            "INSERT INTO urunler (tedarikci,barkod,urun_adi,stok,alis_fiyati,satis_fiyati,gorsel,kategori) VALUES (?,?,?,?,?,?,?,?)",
            df[["tedarikci", "barkod", "urun_adi", "stok", "alis_fiyati", "satis_fiyati", "gorsel", "kategori"]].itertuples(index=False, name=None)
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
    return sonuclar

# ---------------------------------------------------------------
# TRENDRUUM API & TRENDYOL
# ---------------------------------------------------------------
TR_BASE = "https://api.trendruum.com/api/v1/integration"

def sabit_barkod(kod):
    temiz = "".join(ch for ch in str(kod) if ch.isdigit())
    if len(temiz) >= 8:
        return temiz
    h = int(hashlib.md5(str(kod).encode()).hexdigest(), 16) % 10**9
    return f"869{h:09d}"

def trendruum_token(key, secret):
    r = requests.post(f"{TR_BASE}/auth/login", json={"client_id": key.strip(), "client_secret": secret.strip()}, timeout=30)
    j = r.json() if r.text else {}
    token = (j.get("data") or {}).get("token") or j.get("token") or ""
    if r.status_code != 200 or not token:
        raise RuntimeError(f"Giriş başarısız: {r.text[:200]}")
    return token

def trendruum_siparisler(token, durum="new"):
    r = requests.get(f"{TR_BASE}/orders", params={"status": durum}, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    r.raise_for_status()
    return r.json()

TY_BASE = "https://apigw.trendyol.com/integration"
def trendyol_header(seller, key, secret):
    tok = base64.b64encode(f"{key}:{secret}".encode()).decode()
    return {"Authorization": f"Basic {tok}", "User-Agent": f"{seller} - SelfIntegration", "Content-Type": "application/json"}

def trendyol_siparisler(seller, key, secret, durum="Created"):
    r = requests.get(f"{TY_BASE}/order/sellers/{seller}/orders", params={"status": durum}, headers=trendyol_header(seller, key, secret), timeout=30)
    r.raise_for_status()
    return r.json().get("content", [])

# ---------------------------------------------------------------
# ARAYÜZ (MetEntegre Tarzı Yan Menü ve Alt Kırılımlar)
# ---------------------------------------------------------------
if "ayarlar" not in st.session_state:
    st.session_state.ayarlar = ayar_oku()
ayarlar = st.session_state.ayarlar
ayarlar.setdefault("kimlik", {})

def gizli_input(etiket_, ad, parola=True):
    v = st.text_input(etiket_, value=ayarlar["kimlik"].get(ad, ""), type="password" if parola else "default")
    if v.strip() != ayarlar["kimlik"].get(ad, ""):
        ayarlar["kimlik"][ad] = v.strip()
        ayar_yaz(ayarlar)
    return v.strip()

st.sidebar.title("👑 ŞahEntegre")

# MetEntegre tarzı hiyerarşik yan menü yapısı
menu_secimi = st.sidebar.radio("Ana Menü", [
    "🏠 Anasayfa",
    "📦 Sistemdeki Ürünler",
    "🔗 Tedarikçiler & XML",
    "🔄 Oto Kritik Stok",
    "🟠 Trendyol",
    "🟠 Trendyol: Tüm İşlemler",
    "⚙️ Trendyol: Genel Ayarlar",
    "🤖 Trendyol: AI Soru Cvp",
    "🛒 Trendruum",
    "🛒 Trendruum: Tüm İşlemler",
    "⚙️ Trendruum: Genel Ayarlar",
    "🛍️ Hepsiburada",
    "🛍️ Hepsiburada: Tüm İşlemler",
    "⚙️ Hepsiburada: Genel Ayarlar",
    "🟢 İdefix",
    "📋 Senkron Günlüğü"
])

def urunleri_oku():
    with closing(baglan()) as c:
        return pd.read_sql("SELECT * FROM urunler", c)

# ---------------------------------------------------------------
# SAYFA YÖNETİMLERİ
# ---------------------------------------------------------------
if menu_secimi == "🏠 Anasayfa":
    st.title("👑 Mağaza ve Pazar Yeri Özeti")
    df = urunleri_oku()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Toplam Ürün", f"{len(df):,}")
    c2.metric("Stokta (>0)", f"{(df['stok'] > 0).sum():,}" if not df.empty else "0")
    c3.metric("Tükenmiş (<=0)", f"{(df['stok'] <= 0).sum():,}" if not df.empty else "0")
    c4.metric("Tedarikçi", len(ayarlar["tedarikciler"]))

elif menu_secimi == "📦 Sistemdeki Ürünler":
    st.title("📦 Sistemdeki Ürün Analizi")
    df = urunleri_oku()
    if st.button("📦 Stokları Çek ve Yenile", type="primary"):
        with st.spinner("XML'ler taranıyor..."):
            tumunu_senkronla()
        st.success("Stoklar güncellendi!")
        st.rerun()
    
    if not df.empty:
        ara = st.text_input("🔍 Ürün Adı veya Barkod Ara")
        goruntu = df.copy()
        if ara:
            goruntu = goruntu[goruntu["urun_adi"].str.contains(ara, case=False, na=False) | goruntu["barkod"].str.contains(ara, case=False, na=False)]
        
        st.dataframe(
            goruntu.head(100),
            column_config={"gorsel": st.column_config.ImageColumn("Görsel", width="small")},
            use_container_width=True, hide_index=True
        )
    else:
        st.info("Veritabanında ürün bulunamadı.")

elif menu_secimi == "🔗 Tedarikçiler & XML":
    st.title("Tedarikçi ve XML Yönetimi")
    t_ad = st.text_input("Tedarikçi Adı")
    t_link = st.text_input("XML Linki")
    if st.button("Tedarikçi Ekle"):
        if t_ad and t_link:
            ayarlar["tedarikciler"][t_ad] = {"link": t_link, "harita": {}, "marj": 30.0, "sabit_ek": 0.0}
            ayar_yaz(ayarlar)
            st.success("Eklendi.")
            st.rerun()

elif menu_secimi in ["🟠 Trendyol: Tüm İşlemler", "🛒 Trendruum: Tüm İşlemler", "🛍️ Hepsiburada: Tüm İşlemler"]:
    pazar = menu_secimi.split(":")[0].replace("🟠 ", "").replace("🛒 ", "").replace("🛍️ ", "")
    st.title(f"🚀 {pazar} - Tüm İşlemler ve Sipariş Yönetimi")
    
    c_btn1, c_btn2, c_btn3 = st.columns(3)
    c_btn1.button("🔄 Tam Senkronizasyon", type="primary")
    c_btn2.button("⚠️ Kritik Stok Sıfırla")
    c_btn3.button("📤 Toplu Ürün Gönder")

    st.markdown("---")
    tab_tum, tab_yeni, tab_isleme, tab_kargo, tab_iptal = st.tabs([
        "Tüm Siparişler", "Yeni Sipariş", "İşleme Alınan", "Taşıma Durumu", "İptal"
    ])
    with tab_tum:
        st.info(f"{pazar} için gelen aktif sipariş bulunamadı[span_7](start_span)[span_7](end_span).")

elif menu_secimi in ["⚙️ Trendyol: Genel Ayarlar", "⚙️ Trendruum: Genel Ayarlar", "⚙️ Hepsiburada: Genel Ayarlar"]:
    pazar = menu_secimi.split(":")[0].replace("⚙️ ", "")
    st.title(f"⚙️ {pazar} - Genel Ayarlar")
    gizli_input(f"{pazar} API Key / Client ID", f"{pazar.lower()}_key")
    gizli_input(f"{pazar} API Secret", f"{pazar.lower()}_secret", parola=True)

elif menu_secimi == "🤖 Trendyol: AI Soru Cvp":
    st.title("🤖 Müşteri Soru & Cevap Yönetimi")
    st.info("Trendyol mağazanıza gelen sorular burada listelenir.")

elif menu_secimi == "📋 Senkron Günlüğü":
    st.title("Senkronizasyon Günlüğü")
    with closing(baglan()) as c:
        lg = pd.read_sql("SELECT * FROM senkron_log ORDER BY id DESC LIMIT 100", c)
    st.dataframe(lg, use_container_width=True, hide_index=True)

else:
    st.title("👑 ŞahEntegre Kontrol Paneli")
    st.info("Sol menüden dilediğiniz pazar yeri modülünü veya alt işlemi seçebilirsiniz.")
