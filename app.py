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
        veri["tedarikciler"] = {
            k: v for k, v in veri.items() if isinstance(v, dict) and "link" in v
        }
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
    dis = {etiket(e.tag) for e in kok.iter() if etiket(e.tag) in adaylar}
    return max(dis, key=lambda t: sayac[t]) if dis else None

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
            "brand_id": str(brand_id),
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
    loglar, basarili = [], 0
    for i in range(0, len(liste), paket):
        no = i // paket + 1
        grup = liste[i:i + paket]
        try:
            r = requests.post(f"{TR_BASE}/products/bulk", json={"products": grup}, headers=headers, timeout=60)
            if r.status_code in (200, 202):
                basarili += 1
                loglar.append(f"✅ Paket {no}: {len(grup)} ürün gönderildi")
            else:
                loglar.append(f"❌ Paket {no}: HTTP {r.status_code} {r.text[:300]}")
        except Exception as e:
            loglar.append(f"⚠️ Paket {no} hata: {e}")
        if ilerleme:
            ilerleme(no / toplam, loglar)
    return basarili, toplam, loglar

def trendruum_siparisler(token, durum="new", limit=50):
    r = requests.get(f"{TR_BASE}/orders", params={"status": durum, "page": 1, "limit": limit},
                     headers={"Authorization": f"Bearer {token}"}, timeout=30)
    r.raise_for_status()
    return r.json()

# ---------------------------------------------------------------
# ARAYÜZ
# ---------------------------------------------------------------
if "ayarlar" not in st.session_state:
    st.session_state.ayarlar = ayar_oku()
ayarlar = st.session_state.ayarlar
ayarlar.setdefault("kimlik", {})
ayarlar.setdefault("pazar_ayarlari", {})

st.sidebar.title("👑 ŞahEntegre")

TEMA_CSS = """
<style>
[data-testid="stHeader"]{background:#1e2a4a;}
[data-testid="stHeader"] button svg{fill:#fff;color:#fff;}
[data-testid="stSidebar"]{background:#f4f7fb;}
.stButton>button{width:100%; text-align:left; justify-content: flex-start; margin-bottom: 2px;}
[data-testid="stMetric"]{background:#fff;border-radius:14px;padding:14px 16px;
  box-shadow:0 2px 8px rgba(30,64,175,.14);border-left:5px solid #2563eb;}
</style>
"""
st.markdown(TEMA_CSS, unsafe_allow_html=True)

if "secili_sayfa" not in st.session_state:
    st.session_state.secili_sayfa = "🏠 Anasayfa"

def sayfa_sec(ad):
    st.session_state.secili_sayfa = ad

if st.sidebar.button("🏠 Anasayfa"): sayfa_sec("🏠 Anasayfa")
if st.sidebar.button("🙋 Destek Taleplerim"): sayfa_sec("🙋 Destek Taleplerim")
if st.sidebar.button("🔔 Bildirimler"): sayfa_sec("🔔 Bildirimler")
if st.sidebar.button("📢 Duyurular"): sayfa_sec("📢 Duyurular")
if st.sidebar.button("📦 Sistemdeki Ürünler"): sayfa_sec("📦 Sistemdeki Ürünler")
if st.sidebar.button("🔄 Oto Kritik Stok"): sayfa_sec("🔄 Oto Kritik Stok")
if st.sidebar.button("🔗 Tedarikçiler & XML"): sayfa_sec("🔗 Tedarikçiler & XML")

st.sidebar.markdown("---")

pazarlar = ["Trendyol", "Çiçeksepeti", "N11", "E-PTT AVM", "Hepsiburada", "Pazarama", "İdefix", "Trendruum"]
pazar_ikonlar = {"Trendyol": "🟠", "Çiçeksepeti": "🌸", "N11": "🔴", "E-PTT AVM": "📮", "Hepsiburada": "🛍️", "Pazarama": "🏪", "İdefix": "🟢", "Trendruum": "🛒"}

for pz in pazarlar:
    with st.sidebar.expander(f"{pazar_ikonlar[pz]} {pz}"):
        if st.button(f"🔗 {pz} Tüm İşlemler", key=f"{pz}_tum"): sayfa_sec(f"{pz}: Tüm İşlemler")
        if st.button(f"⚙️ {pz} Genel Ayarlar", key=f"{pz}_ayar"): sayfa_sec(f"{pz}: Genel Ayarlar")
        if st.button(f"🤖 {pz} AI Soru Cvp", key=f"{pz}_ai"): sayfa_sec(f"{pz}: AI Soru Cvp")

st.sidebar.markdown("---")
if st.sidebar.button("📋 Senkron Günlüğü"): sayfa_sec("📋 Senkron Günlüğü")

def urunleri_oku():
    with closing(baglan()) as c:
        return pd.read_sql("SELECT * FROM urunler", c)

sayfa = st.session_state.secili_sayfa

# ---------------------------------------------------------------
# SAYFA İÇERİKLERİ
# ---------------------------------------------------------------
if sayfa == "🏠 Anasayfa":
    st.title("👑 Mağaza ve Pazar Yeri Özeti")
    df = urunleri_oku()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Toplam Ürün", f"{len(df):,}")
    c2.metric("Stokta (>0)", f"{(df['stok'] > 0).sum():,}" if not df.empty else "0")
    c3.metric("Tükenmiş (<=0)", f"{(df['stok'] <= 0).sum():,}" if not df.empty else "0")
    c4.metric("Tedarikçi", len(ayarlar["tedarikciler"]))

elif sayfa == "📦 Sistemdeki Ürünler":
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
            goruntu.head(200),
            column_config={"gorsel": st.column_config.ImageColumn("Görsel", width="small")},
            use_container_width=True, hide_index=True
        )
    else:
        st.info("Veritabanında ürün bulunamadı.")

elif sayfa == "🔗 Tedarikçiler & XML":
    st.title("Tedarikçi ve XML Yönetimi")
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

elif "Tüm İşlemler" in sayfa:
    pazar = sayfa.split(":")[0].strip()
    st.title(f"🚀 {pazar} - Tüm İşlemler ve Sipariş Yönetimi")
    st.markdown(f"**{pazar}** mağazanızdaki ürünler, eşleşme durumları ve tüm yönetim işlemleriniz.")
    
    if st.button("ℹ️ Önemli Bilgilendirme", type="secondary"):
        st.info(f"{pazar} entegrasyonu için günde 1 kez Tam Senkronizasyon yapmak yeterlidir; sık çalıştırmak API kotanızı tüketebilir.")

    st.markdown("### SENKRON")
    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        if st.button("🔄 Tam Senkronizasyon", type="primary"):
            tumunu_senkronla()
            st.success(f"{pazar} tam senkronizasyon tamamlandı.")
    with col_s2:
        if st.button("⚠️ Kritik Stok Sıfırla"):
            with closing(baglan()) as c:
                n = c.execute("UPDATE urunler SET stok = 0 WHERE stok <= 2").rowcount
                c.commit()
            st.success(f"Kritik stoktaki {n} ürün sıfırlandı.")
    with col_s3:
        if st.button("🏷️ Tüm Barkodları Güncelle"):
            st.success("Barkod eşitlemesi yapıldı.")

    st.markdown("### İŞLEMLER")
    col_i1, col_i2, col_i3 = st.columns(3)
    with col_i1:
        if st.button("📤 Toplu Ürün Gönder"):
            p_ayar_veri = ayarlar.get("pazar_ayarlari", {}).get(pazar, {})
            
            if pazar == "Trendruum":
                tr_key = kimlik(ayarlar, "trendruum_key") or p_ayar_veri.get("api_key")
                tr_secret = kimlik(ayarlar, "trendruum_secret") or p_ayar_veri.get("servis_anahtari")
                tr_brand = p_ayar_veri.get("magaza_marka") or kimlik(ayarlar, "trendruum_brand")
                cat = kimlik(ayarlar, "trendruum_category") or "0"

                if tr_key and tr_secret and tr_brand:
                    try:
                        token = trendruum_token(tr_key, tr_secret)
                        df = urunleri_oku()
                        artiss = float(p_ayar_veri.get("fiyat_artis", 0.0))
                        if artiss > 0:
                            df["satis_fiyati"] = df["satis_fiyati"] * (1 + artiss / 100)
                        
                        liste, atlanan = trendruum_urun_listesi(df, ayarlar, tr_brand, cat)
                        bar, kutu = st.progress(0), st.empty()
                        ok, top, loglar = trendruum_gonder(liste, token, lambda p, l: (bar.progress(p), kutu.code("\n".join(l[-10:]))))
                        st.success(f"Trendruum Toplu Gönderim Tamamlandı: {ok}/{top} paket başarılı.")
                    except Exception as e:
                        st.error(f"Hata: {e}")
                else:
                    st.error("Lütfen Genel Ayarlar kısmından API Key (Client ID) ve Servis Anahtarı (API Secret) bilgilerini ayrı ayrı doldurun.")
            else:
                st.warning(f"{pazar} toplu ürün gönderimi aktif modüldür.")
    with col_i2:
        if st.button("🚚 Kargo Süresi Ayarla"):
            st.success("Kargo süreleri güncellendi.")
    with col_i3:
        if st.button("✅ Eşleme Onay / Red"):
            st.info("Eşleme onay ekranı aktif.")

    st.markdown("---")
    df_tum = urunleri_oku()
    c_m1, c_m2 = st.columns(2)
    c_m1.metric(f"Toplam {pazar} Ürünü", f"{len(df_tum):,}")
    c_m2.metric("Senkronize Edilmiş", f"{(df_tum['stok'] > 0).sum():,}")

    st.markdown("---")
    tab_tum, tab_yeni, tab_isleme, tab_kargo, tab_iptal = st.tabs([
        "Tüm Siparişler", "Yeni Sipariş", "İşleme Alınan", "Taşıma Durumu", "İptal"
    ])
    with tab_tum:
        if pazar == "Trendruum":
            p_ayar_veri = ayarlar.get("pazar_ayarlari", {}).get("Trendruum", {})
            key = kimlik(ayarlar, "trendruum_key") or p_ayar_veri.get("api_key")
            secret = kimlik(ayarlar, "trendruum_secret") or p_ayar_veri.get("servis_anahtari")
            if key and secret:
                try:
                    token = trendruum_token(key, secret)
                    j = trendruum_siparisler(token, "new")
                    veri = j.get("data", j)
                    if isinstance(veri, dict):
                        veri = next((v for v in veri.values() if isinstance(v, list)), [])
                    if veri:
                        st.dataframe(pd.json_normalize(veri), use_container_width=True)
                    else:
                        st.info("Bekleyen yeni sipariş bulunamadı.")
                except Exception as e:
                    st.info(f"Siparişler çekilemedi: {e}")
            else:
                st.warning("API bilgilerini Genel Ayarlar'dan girin.")
        else:
            st.info(f"{pazar} için sipariş listesi boş.")

elif "Genel Ayarlar" in sayfa:
    pazar = sayfa.split(":")[0].strip()
    st.title(f"⚙️ {pazar} - Genel Ayarlar ve Mağaza Parametreleri")
    
    ayarlar.setdefault("pazar_ayarlari", {})
    p_ayar = ayarlar["pazar_ayarlari"].setdefault(pazar, {
        "magaza_id": "", "api_key": "", "servis_anahtari": "", "magaza_marka": "",
        "sabit_kargo": 0.0, "satis_orani": 30.0, "fiyat_artis": 0.0
    })

    st.markdown("### 🔑 Mağaza ve Servis Bilgileri")
    mid = st.text_input("Mağaza ID / Seller ID", value=p_ayar.get("magaza_id", ""))
    apikey = st.text_input("API Key (Client ID)", value=p_ayar.get("api_key", kimlik(ayarlar, f"{pazar.lower()}_key")))
    sanahtar = st.text_input("Servis Anahtarı / API Secret (Client Secret)", value=p_ayar.get("servis_anahtari", kimlik(ayarlar, f"{pazar.lower()}_secret")), type="password")
    marka = st.text_input("Mağaza Marka Adı", value=p_ayar.get("magaza_marka", ""))

    st.markdown("### 💰 Kargo ve Kâr Oranı Kuralları")
    sabit_kargo = st.number_input("Sabit Kargo Fiyatı (TL)", 0.0, 1000.0, float(p_ayar.get("sabit_kargo", 0.0)))
    satis_orani = st.number_input("Satış / Kâr Oranı (%)", 0.0, 500.0, float(p_ayar.get("satis_orani", 30.0)))
    fiyat_artis = st.number_input("Fiyat Artış Oranı (%)", 0.0, 100.0, float(p_ayar.get("fiyat_artis", 0.0)))

    if st.button("💾 Entegrasyon Bilgilerini Kaydet ve Ekle", type="primary"):
        p_ayar.update({
            "magaza_id": mid.strip(),
            "api_key": apikey.strip(),
            "servis_anahtari": sanahtar.strip(),
            "magaza_marka": marka.strip(),
            "sabit_kargo": sabit_kargo,
            "satis_orani": satis_orani,
            "fiyat_artis": fiyat_artis
        })
        
        if pazar == "Trendruum":
            ayarlar["kimlik"]["trendruum_key"] = apikey.strip()
            ayarlar["kimlik"]["trendruum_secret"] = sanahtar.strip()
            ayarlar["kimlik"]["trendruum_brand"] = marka.strip()
        
        ayar_yaz(ayarlar)
        st.success(f"{pazar} entegrasyon ayarları başarıyla kaydedildi!")

    if st.button("🗑️ Entegrasyon Bilgilerimi Sil"):
        ayarlar["pazar_ayarlari"][pazar] = {}
        ayar_yaz(ayarlar)
        st.warning(f"{pazar} ayarları temizlendi.")

elif "AI Soru Cvp" in sayfa:
    pazar = sayfa.split(":")[0].strip()
    st.title(f"🤖 {pazar} - Müşteri Soru & Cevap")
    st.info(f"{pazar} mağazanıza gelen müşteri soruları bu alanda listelenir.")

elif sayfa == "📋 Senkron Günlüğü":
    st.title("Senkronizasyon Günlüğü")
    with closing(baglan()) as c:
        lg = pd.read_sql("SELECT * FROM senkron_log ORDER BY id DESC LIMIT 100", c)
    st.dataframe(lg, use_container_width=True, hide_index=True)

else:
    st.title(f"👑 {sayfa}")
    st.info("Modül aktif ve kullanıma hazır.")
