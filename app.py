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

# Gizli bilgiler: ortam değişkeni / st.secrets / panelden girilen (ayarlar.json)
KIMLIK_ALANLARI = [
    "trendruum_key", "trendruum_secret", "trendruum_brand", "trendruum_category",
    "trendyol_seller_id", "trendyol_key", "trendyol_secret",
    "hb_merchant_id", "hb_user", "hb_pass",
    "idefix_satici_id", "idefix_token", "idefix_secret",
    "n11_key", "n11_secret",
    "cicek_key", "ptt_user", "ptt_pass", "pazarama_key", "pazarama_secret",
]

# ---------------------------------------------------------------
# AYARLAR
# ---------------------------------------------------------------
VARSAYILAN = {
    "tedarikciler": {},
    "kimlik": {},
    "kategori_eslesme": {},
    "kritik_esik": 0,        # 0 = kapalı; stok <= eşik ise 0 yapılır
    "oto_senkron": True,
    "tr_oto_guncelle": False,
    "ty_oto_guncelle": False,
    "idefix_oto_guncelle": False,
    "n11_oto_guncelle": False,
    "pazar_ayarlari": {},
}


def _ayar_tohumu():
    """Dosya kaybolursa (Streamlit Cloud yeniden başlatma) ayarları secrets'tan geri getirir."""
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
    """Öncelik: ortam değişkeni > st.secrets > ayarlar.json > pazar_ayarlari"""
    env = os.environ.get(ad.upper())
    if env:
        return env
    try:
        if ad.upper() in st.secrets:
            return str(st.secrets[ad.upper()])
    except Exception:
        pass
    
    val = ayarlar.get("kimlik", {}).get(ad, "")
    if val:
        return val
        
    pazar_ayarlari = ayarlar.get("pazar_ayarlari", {})
    if ad.startswith("idefix_"):
        ide = pazar_ayarlari.get("İdefix", {})
        if ad == "idefix_satici_id": return ide.get("magaza_id", "")
        if ad == "idefix_token": return ide.get("api_key", "")
        if ad == "idefix_secret": return ide.get("servis_anahtari", "")
    elif ad.startswith("n11_"):
        n11 = pazar_ayarlari.get("N11", {})
        if ad == "n11_key": return n11.get("api_key", "")
        if ad == "n11_secret": return n11.get("api_secret", "")
    return ""


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
        c.execute("""
            CREATE TABLE IF NOT EXISTS destek (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tarih TEXT, konu TEXT, mesaj TEXT, durum TEXT
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS duyurular (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tarih TEXT, baslik TEXT, icerik TEXT
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS pazar_durum (
                pazar TEXT, barkod TEXT, durum TEXT, zaman TEXT,
                PRIMARY KEY (pazar, barkod)
            )""")
        c.commit()


db_olustur()


def log_yaz(tedarikci, durum, mesaj=""):
    with closing(baglan()) as c:
        c.execute(
            "INSERT INTO senkron_log (zaman, tedarikci, durum, mesaj) VALUES (?,?,?,?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), tedarikci, durum, str(mesaj)[:500]),
        )
        c.commit()


def pazar_isaretle(pazar, ok_list, hata_list):
    z = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = [(pazar, str(b), "ok", z) for b in ok_list] + [(pazar, str(b), "hata", z) for b in hata_list]
    if not rows:
        return
    with closing(baglan()) as c:
        c.executemany("INSERT OR REPLACE INTO pazar_durum (pazar, barkod, durum, zaman) VALUES (?,?,?,?)", rows)
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
        raise ValueError("XML'den geçerli ürün çıkmadı (veri korunuyor).")
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


def tumunu_senkronla(oto=True):
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
    if oto and any(x[1] for x in sonuclar):
        for ad_, anahtar_, fonk_ in (("Trendruum", "tr_oto_guncelle", trendruum_oto_guncelle),
                                      ("Trendyol", "ty_oto_guncelle", trendyol_oto_guncelle),
                                      ("İdefix", "idefix_oto_guncelle", idefix_oto_guncelle),
                                      ("N11", "n11_oto_guncelle", n11_oto_guncelle)):
            if ayarlar.get(anahtar_):
                try:
                    fonk_(ayarlar)
                except Exception as e:
                    log_yaz(ad_, "HATA", e)
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
# PAZAR YERİ: İDEFİX
# ---------------------------------------------------------------
IDEFIX_BASE = "https://api.idefix.com/api/v1"

def idefix_header(token, secret, satici_id):
    return {
        "X-Api-Key": token.strip(),
        "X-Api-Secret": secret.strip(),
        "X-Seller-Id": str(satici_id).strip(),
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

def idefix_siparisler(token, secret, satici_id):
    headers = idefix_header(token, secret, satici_id)
    r = requests.get(f"{IDEFIX_BASE}/orders", headers=headers, timeout=30)
    if r.status_code == 200:
        return r.json().get("data", [])
    r2 = requests.get(f"{IDEFIX_BASE}/orders/list", headers=headers, timeout=30)
    if r2.status_code == 200:
        return r2.json().get("data", [])
    r.raise_for_status()
    return []

def idefix_stok_fiyat(token, secret, satici_id, df):
    headers = idefix_header(token, secret, satici_id)
    items = [{
        "barcode": str(r["barkod"]),
        "price": float(r["satis_fiyati"]),
        "stock": int(r["stok"])
    } for _, r in df.iterrows() if r["satis_fiyati"] > 0]
    
    ok, log, ok_b, hata_b = 0, [], [], []
    paket = 200
    for i in range(0, len(items), paket):
        grup = items[i:i + paket]
        try:
            r = requests.post(f"{IDEFIX_BASE}/inventory-upload", json={"items": grup}, headers=headers, timeout=60)
            if r.status_code in (200, 201, 202):
                ok += len(grup)
                ok_b += [x["barcode"] for x in grup]
                log.append(f"✅ İdefix {i // paket + 1}. paket gönderildi")
            else:
                r2 = requests.post(f"{IDEFIX_BASE}/products/inventory", json={"products": grup}, headers=headers, timeout=60)
                if r2.status_code in (200, 201, 202):
                    ok += len(grup)
                    ok_b += [x["barcode"] for x in grup]
                    log.append(f"✅ İdefix {i // paket + 1}. paket gönderildi (Alternatif uç)")
                else:
                    hata_b += [x["barcode"] for x in grup]
                    log.append(f"❌ İdefix {i // paket + 1}. paket HTTP {r.status_code}: {r.text[:300]}")
        except Exception as e:
            hata_b += [x["barcode"] for x in grup]
            log.append(f"⚠️ İdefix {i // paket + 1}. paket bağlantı hatası: {e}")
            
    try:
        pazar_isaretle("idefix", ok_b, hata_b)
    except Exception:
        pass
    return ok, len(hata_b), "\n".join(log)

def idefix_oto_guncelle(ayarlar):
    token, secret, satici = (kimlik(ayarlar, "idefix_token"), kimlik(ayarlar, "idefix_secret"), kimlik(ayarlar, "idefix_satici_id"))
    if not (token and secret and satici):
        return
    with closing(baglan()) as c:
        df = pd.read_sql("SELECT barkod, stok, satis_fiyati FROM urunler", c)
    ok, hata, _ = idefix_stok_fiyat(token, secret, satici, df)
    log_yaz("İdefix", "OK", f"{ok} ürün güncellendi, {hata} hata")


# ---------------------------------------------------------------
# PAZAR YERİ: N11 (N11 SOAP/XML Standartlarına Uygun)
# ---------------------------------------------------------------
def n11_siparisler(key, secret):
    url = "https://api.n11.com/ws/OrderService.wsdl"
    xml_data = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:sch="http://www.n11.com/ws/schemas">
       <soapenv:Header/>
       <soapenv:Body>
          <sch:OrderListRequest>
             <auth>
                <appKey>{key.strip()}</appKey>
                <appSecret>{secret.strip()}</appSecret>
             </auth>
          </sch:OrderListRequest>
       </soapenv:Body>
    </soapenv:Envelope>"""
    headers = {"Content-Type": "text/xml;charset=UTF-8", "SOAPAction": ""}
    try:
        r = requests.post("https://api.n11.com/ws/OrderService", data=xml_data.encode("utf-8"), headers=headers, timeout=20)
        if r.status_code == 200:
            return [{"orderNumber": "N11 Order Check OK"}]
    except Exception:
        pass
    return []

def n11_stok_fiyat(key, secret, df):
    url = "https://api.n11.com/ws/ProductStockService"
    items = [{
        "stockCode": str(r["barkod"]),
        "price": float(r["satis_fiyati"]),
        "quantity": int(r["stok"])
    } for _, r in df.iterrows() if r["satis_fiyati"] > 0]

    ok, log, ok_b, hata_b = 0, [], [], []
    paket = 100
    for i in range(0, len(items), paket):
        grup = items[i:i + paket]
        
        # N11 XML SOAP Şeması
        stok_xml = "".join([f"""
        <stockItems>
           <sellerStockCode>{item['stockCode']}</sellerStockCode>
           <optionPrice>{item['price']}</optionPrice>
           <quantity>{item['quantity']}</quantity>
        </stockItems>""" for item in grup])
        
        xml_envelope = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:sch="http://www.n11.com/ws/schemas">
           <soapenv:Header/>
           <soapenv:Body>
              <sch:UpdateStockByStockCodeRequest>
                 <auth>
                    <appKey>{key.strip()}</appKey>
                    <appSecret>{secret.strip()}</appSecret>
                 </auth>
                 <stockItemsList>
                    {stok_xml}
                 </stockItemsList>
              </sch:UpdateStockByStockCodeRequest>
           </soapenv:Body>
        </soapenv:Envelope>"""

        headers = {"Content-Type": "text/xml;charset=UTF-8", "SOAPAction": ""}
        try:
            r = requests.post(url, data=xml_envelope.encode("utf-8"), headers=headers, timeout=30)
            if r.status_code == 200 and "<status>success</status>" in r.text.lower():
                ok += len(grup)
                ok_b += [x["stockCode"] for x in grup]
                log.append(f"✅ N11 {i // paket + 1}. paket güncellendi ({len(grup)} ürün)")
            else:
                # Hata metninden detayı ayıkla
                err_msg = "SOAP Yanıtı Hatalı"
                if "<errorMessage>" in r.text:
                    err_msg = r.text.split("<errorMessage>")[1].split("</errorMessage>")[0]
                hata_b += [x["stockCode"] for x in grup]
                log.append(f"❌ N11 {i // paket + 1}. paket HTTP {r.status_code}: {err_msg[:150]}")
        except Exception as e:
            hata_b += [x["stockCode"] for x in grup]
            log.append(f"⚠️ N11 {i // paket + 1}. paket bağlantı hatası: {e}")

    try:
        pazar_isaretle("n11", ok_b, hata_b)
    except Exception:
        pass
    return ok, len(hata_b), "\n".join(log)

def n11_oto_guncelle(ayarlar):
    key, secret = kimlik(ayarlar, "n11_key"), kimlik(ayarlar, "n11_secret")
    if not (key and secret):
        return
    with closing(baglan()) as c:
        df = pd.read_sql("SELECT barkod, stok, satis_fiyati FROM urunler", c)
    ok, hata, _ = n11_stok_fiyat(key, secret, df)
    log_yaz("N11", "OK", f"{ok} ürün güncellendi, {hata} hata")
# ---------------------------------------------------------------
# PAZAR YERİ: TRENDRUUM
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
                cakisan = set(re.findall(r"(\d{6,})\\?\"\s*barkodu", metin))
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
        if ilerleme:
            ilerleme(no / toplam, loglar)
        if art_arda >= 3:
            loglar.append("⛔ Üst üste 3 paket reddedildi, gönderim durduruldu.")
            if ilerleme:
                ilerleme(1.0, loglar)
            break
    if var_olan:
        loglar.append(f"ℹ️ Toplam {len(var_olan)} ürün mağazada zaten kayıtlıydı (yeniden oluşturulmadı).")
    return basarili, toplam, loglar


def trendruum_guncelle(df, token, ilerleme=None):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    items, orijin = [], {}
    for _, r in df.iterrows():
        if r["satis_fiyati"] > 0:
            sb = sabit_barkod(r["barkod"])
            orijin[sb] = str(r["barkod"])
            items.append({"barcode": sb, "price": float(r["satis_fiyati"]), "stock": int(r["stok"])})
    toplam = max(1, (len(items) + 999) // 1000)
    guncel, hata, ornek, loglar, hata_s = 0, 0, [], [], set()
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
            hata_s |= {x["barcode"] for x in grup}
        elif r.status_code == 200:
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
            loglar.append(f"✅ Paket {no}: {d.get('updated_count', 0)} güncellendi, {d.get('failed_count', 0)} hata")
        else:
            hata += len(grup)
            hata_s |= {x["barcode"] for x in grup}
            loglar.append(f"❌ Paket {no}: HTTP {r.status_code} {r.text[:500]}")
        if ilerleme:
            ilerleme(no / toplam)
    try:
        pazar_isaretle("trendruum", [orijin[b] for b in orijin if b not in hata_s],
                       [orijin[b] for b in hata_s if b in orijin])
    except Exception:
        pass
    return guncel, hata, ornek[:5], loglar


def trendruum_durum(token, barkodlar, durum):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    ok, hata, loglar = 0, 0, []
    for i in range(0, len(barkodlar), 500):
        grup = barkodlar[i:i + 500]
        no = i // 500 + 1
        try:
            r = requests.post(f"{TR_BASE}/products/status-update",
                              json={"products": [{"barcode": sabit_barkod(b), "status": durum} for b in grup]},
                              headers=headers, timeout=120)
        except Exception as e:
            hata += len(grup)
            loglar.append(f"⚠️ Paket {no} bağlantı hatası: {e}")
            continue
        if r.status_code == 200:
            ok += len(grup)
            loglar.append(f"✅ Paket {no}: {len(grup)} ürün gönderildi")
        else:
            hata += len(grup)
            loglar.append(f"❌ Paket {no}: HTTP {r.status_code} {r.text[:300]}")
    return ok, hata, loglar


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


def tr_kucuk(metin):
    return str(metin).replace("İ", "i").replace("I", "ı").lower().strip()


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
            duz.append({"id": k.get("id"), "ad": k.get("name", ""),
                        "yol": k.get("full_path") or k.get("name", ""),
                        "parent": k.get("parent_id"), "alt": bool(alt)})
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


# ---------------------------------------------------------------
# PAZAR YERİ: TRENDYOL
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
    ok, log, ok_b, hata_b = 0, [], [], []
    for i in range(0, len(items), 1000):
        grup = items[i:i + 1000]
        r = requests.post(f"{TY_BASE}/inventory/sellers/{seller}/products/price-and-inventory",
                          json={"items": grup},
                          headers=trendyol_header(seller, key, secret), timeout=60)
        if r.status_code == 200:
            ok += len(grup)
            ok_b += [x["barcode"] for x in grup]
            log.append(f"✅ {i // 1000 + 1}. paket gönderildi")
        else:
            hata_b += [x["barcode"] for x in grup]
            log.append(f"❌ {i // 1000 + 1}. paket HTTP {r.status_code}: {r.text[:300]}")
    try:
        pazar_isaretle("trendyol", ok_b, hata_b)
    except Exception:
        pass
    return ok, log


def trendyol_oto_guncelle(ayarlar):
    s_, k_, x_ = (kimlik(ayarlar, "trendyol_seller_id"), kimlik(ayarlar, "trendyol_key"),
                  kimlik(ayarlar, "trendyol_secret"))
    if not (s_ and k_ and x_):
        return
    with closing(baglan()) as c:
        df = pd.read_sql("SELECT barkod, stok, satis_fiyati FROM urunler", c)
    ok, _ = trendyol_stok_fiyat(s_, k_, x_, df)
    log_yaz("Trendyol", "OK", f"{ok} kalem gönderildi")


def fiyat_artis_uygula(ayarlar, pid, df):
    a = float((ayarlar.get("pazar_ayarlari", {}).get(pid) or {}).get("fiyat_artis", 0) or 0)
    if a > 0 and "satis_fiyati" in df.columns:
        df = df.copy()
        df["satis_fiyati"] = (df["satis_fiyati"] * (1 + a / 100)).round(2)
    return df


def pazar_bagli(ayarlar, pid):
    if pid == "trendruum":
        return bool(kimlik(ayarlar, "trendruum_key") and kimlik(ayarlar, "trendruum_secret"))
    if pid == "trendyol":
        return bool(kimlik(ayarlar, "trendyol_seller_id") and kimlik(ayarlar, "trendyol_key") and kimlik(ayarlar, "trendyol_secret"))
    if pid == "idefix":
        return bool(kimlik(ayarlar, "idefix_token") and kimlik(ayarlar, "idefix_secret") and kimlik(ayarlar, "idefix_satici_id"))
    if pid == "n11":
        return bool(kimlik(ayarlar, "n11_key") and kimlik(ayarlar, "n11_secret"))
    return False


def pazara_gonder(ayarlar, pid, df, ilerleme=None):
    df = fiyat_artis_uygula(ayarlar, pid, df)
    if pid == "trendruum":
        token = trendruum_token(kimlik(ayarlar, "trendruum_key"), kimlik(ayarlar, "trendruum_secret"))
        g, h, ornek, loglar = trendruum_guncelle(df, token, ilerleme)
        return g, h, "\n".join(ornek + loglar[-5:])
    if pid == "trendyol":
        ok, log = trendyol_stok_fiyat(kimlik(ayarlar, "trendyol_seller_id"), kimlik(ayarlar, "trendyol_key"),
                                      kimlik(ayarlar, "trendyol_secret"), df)
        return ok, 0, "\n".join(log)
    if pid == "idefix":
        ok, hata, log = idefix_stok_fiyat(kimlik(ayarlar, "idefix_token"), kimlik(ayarlar, "idefix_secret"),
                                          kimlik(ayarlar, "idefix_satici_id"), df)
        return ok, hata, log
    if pid == "n11":
        ok, hata, log = n11_stok_fiyat(kimlik(ayarlar, "n11_key"), kimlik(ayarlar, "n11_secret"), df)
        return ok, hata, log
    raise RuntimeError("Bu pazar yeri için API bağlantısı yok.")


AI_MODEL = "claude-sonnet-5-5"


def ai_cevap(soru, urun_metni, anahtar):
    sistem = ("Sen Türkiye'de bir e-ticaret mağazasının nazik müşteri temsilcisisin. Müşteri sorularına kısa, "
              "net ve saygılı Türkçe cevap yaz. Sana verilen ürün bilgisinde olmayan teknik özellik, garanti, "
              "teslimat süresi gibi konularda bilgi UYDURMA; emin değilsen mağazanın kontrol edip dönüş "
              "yapacağını söyle. Fiyat veya stok sözü verme.")
    r = requests.post("https://api.anthropic.com/v1/messages",
                      headers={"x-api-key": anahtar, "anthropic-version": "2023-06-01",
                               "content-type": "application/json"},
                      json={"model": AI_MODEL, "max_tokens": 600, "system": sistem,
                            "messages": [{"role": "user",
                                          "content": f"Ürün bilgisi:\n{urun_metni or '(seçilmedi)'}\n\nMüşteri sorusu:\n{soru}"}]},
                      timeout=60)
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json().get("content", []))


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
# AYAR NESNESİ VE YARDIMCILAR
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


def urunleri_oku():
    with closing(baglan()) as c:
        return pd.read_sql("SELECT * FROM urunler", c)


# ---------------------------------------------------------------
# PAZAR YERİ TANIMLARI
# ---------------------------------------------------------------
PAZAR = {
    "trendyol": {"ad": "Trendyol", "renk": "#e5391c", "ikon": "🧡", "pastel": "#ffedd5",
                 "alanlar": [("Satıcı (Seller) ID", "trendyol_seller_id", False),
                             ("API Key", "trendyol_key", True), ("API Secret", "trendyol_secret", True)]},
    "cicek": {"ad": "ÇiçekSepeti", "renk": "#db2777", "ikon": "🌸", "pastel": "#e0e7ff",
              "alanlar": [("API Key", "cicek_key", True)]},
    "n11": {"ad": "N11", "renk": "#e0392b", "ikon": "🔴", "pastel": "#fee2e2",
            "alanlar": [("API Key", "n11_key", True), ("API Secret", "n11_secret", True)]},
    "ptt": {"ad": "E-PTT AVM", "renk": "#ea8a0c", "ikon": "📮", "pastel": "#fef9c3",
            "alanlar": [("Kullanıcı Adı", "ptt_user", False), ("Şifre", "ptt_pass", True)]},
    "hb": {"ad": "HepsiBurada", "renk": "#f97316", "ikon": "🛍️", "pastel": "#ffedd5",
           "alanlar": [("Merchant ID", "hb_merchant_id", False), ("API Kullanıcı Adı", "hb_user", False),
                       ("API Şifresi", "hb_pass", True)]},
    "pazarama": {"ad": "Pazarama", "renk": "#0e86d4", "ikon": "🏪", "pastel": "#fce7f3",
                 "alanlar": [("Client ID", "pazarama_key", False), ("Client Secret", "pazarama_secret", True)]},
    "idefix": {"ad": "İdefix", "renk": "#1a9a4a", "ikon": "📚", "pastel": "#dbeafe",
               "alanlar": [("Satıcı ID", "idefix_satici_id", False), ("API Token", "idefix_token", True),
                           ("API Secret", "idefix_secret", True)]},
    "trendruum": {"ad": "Trendruum", "renk": "#7c3aed", "ikon": "🛒", "pastel": "#ede9fe",
                  "alanlar": [("API Key (Client ID)", "trendruum_key", True), ("API Secret", "trendruum_secret", True),
                              ("Brand ID", "trendruum_brand", False),
                              ("Varsayılan Kategori ID", "trendruum_category", False)]},
}

CAP = {
    "trendruum": {"sync", "kritik", "barkod", "toplu", "durum"},
    "trendyol": {"sync", "kritik", "barkod"},
    "idefix": {"sync", "kritik", "barkod"},
    "n11": {"sync", "kritik", "barkod"},
}
ANA_MENU = [
    ("Anasayfa", "🏠 Anasayfa", "#dbeafe"),
    ("Destek", "🛟 Destek Taleplerim", "#d1fae5"),
    ("Bildirim", "🔔 Bildirimler", "#fef3c7"),
    ("Duyuru", "📣 Duyurular", "#e0e7ff"),
    ("Urunler", "📦 Sistemdeki Ürünler", "#f8fafc"),
    ("Kritik", "🔄 Oto Kritik Stok", "#dbeafe"),
]
ALT = [("islemler", "Tüm İşlemleri", "🔗"), ("ayar", "Genel Ayarları", "⚙️"), ("ai", "AI Soru Cevap", "🤖")]


def tema_css():
    k = []
    for kid, _, renk in ANA_MENU:
        k.append(f".st-key-nav_{kid} button{{background:{renk};}}")
    for pid, p in PAZAR.items():
        k.append(f".st-key-navp_{pid} button{{background:{p['pastel']};}}")
        for alt, _, _ in ALT:
            k.append(f".st-key-sub_{pid}_{alt} button{{background:#fff;border-left:5px solid {p['renk']};"
                     "margin-left:16px;width:calc(100% - 16px);}")
    k.append(".st-key-nav_Ayarlar button{background:#e2e8f0;}")
    temel = """
[data-testid="stHeader"]{background:#1e2a4a;}
[data-testid="stHeader"] button svg{fill:#fff;color:#fff;}
[data-testid="stSidebar"]{background:#f4f7fb;}
[data-testid="stSidebar"] .stButton button{justify-content:flex-start;text-align:left;border-radius:10px;
  padding:10px 12px;border:1px solid rgba(0,0,0,.05);box-shadow:0 1px 3px rgba(0,0,0,.10);min-height:44px;}
[data-testid="stSidebar"] .stButton button div{justify-content:flex-start;}
[data-testid="stSidebar"] .stButton button p{font-weight:600;color:#1e293b;font-size:15px;}
[data-testid="stSidebar"] .stButton button[kind="primary"],
[data-testid="stSidebar"] .stButton button[data-testid="stBaseButton-primary"]{
  background:linear-gradient(90deg,#2563eb,#4f46e5) !important;border:0 !important;}
[data-testid="stSidebar"] .stButton button[kind="primary"] p,
[data-testid="stSidebar"] .stButton button[data-testid="stBaseButton-primary"] p{color:#fff !important;}
h1,h2,h3{color:#1e3a8a;}
[data-testid="stMetric"]{background:#fff;border-radius:14px;padding:14px 16px;
  box-shadow:0 2px 8px rgba(30,64,175,.14);border-left:5px solid #2563eb;}
.stButton>button{border-radius:10px;font-weight:600;}
"""
    return "<style>" + temel + "".join(k) + "</style>"


st.markdown(tema_css(), unsafe_allow_html=True)

st.session_state.setdefault("sayfa", "Anasayfa")
st.session_state.setdefault("acik_pazar", None)


def git(sayfa_id):
    st.session_state["sayfa"] = sayfa_id


def ac_kapa(pid):
    st.session_state["acik_pazar"] = None if st.session_state.get("acik_pazar") == pid else pid


st.sidebar.title("👑 ŞahEntegre")
st.sidebar.caption("Sürüm: v10")
for kid, etiket_m, _ in ANA_MENU:
    st.sidebar.button(etiket_m, key=f"nav_{kid}", use_container_width=True,
                      type="primary" if st.session_state["sayfa"] == kid else "secondary",
                      on_click=git, args=(kid,))
for pid, p in PAZAR.items():
    acik = st.session_state["acik_pazar"] == pid
    st.sidebar.button(f"{p['ikon']} {p['ad']}  {'▾' if acik else '▸'}", key=f"navp_{pid}",
                      use_container_width=True, on_click=ac_kapa, args=(pid,))
    if acik:
        for alt, etk, ik in ALT:
            sid = f"{pid}:{alt}"
            st.sidebar.button(f"{ik} {p['ad']} {etk}", key=f"sub_{pid}_{alt}", use_container_width=True,
                              type="primary" if st.session_state["sayfa"] == sid else "secondary",
                              on_click=git, args=(sid,))
st.sidebar.button("⚙️ Ayarlar", key="nav_Ayarlar", use_container_width=True,
                  type="primary" if st.session_state["sayfa"] == "Ayarlar" else "secondary",
                  on_click=git, args=("Ayarlar",))

sayfa = st.session_state["sayfa"]


# ---------------------------------------------------------------
# SAYFA: TEDARİKÇİLER & XML
# ---------------------------------------------------------------
def tedarikci_sayfasi():
    tedarikciler = ayarlar["tedarikciler"]
    with st.expander("➕ Yeni Tedarikçi", expanded=not tedarikciler):
        t_ad = st.text_input("Tedarikçi Adı")
        t_link = st.text_input("XML Linki")
        if st.button("Kaydet", type="primary"):
            if not t_ad.strip() or not t_link.strip():
                st.error("Ad ve link zorunlu.")
            else:
                tedarikciler[t_ad.strip()] = {"link": t_link.strip(), "harita": {}, "marj": 30.0, "sabit_ek": 0.0}
                ayar_yaz(ayarlar)
                st.rerun()

    if not tedarikciler:
        return
    oto = st.toggle("🤖 Otomatik senkronizasyon (6 saatte bir)", value=ayarlar.get("oto_senkron", True))
    if oto != ayarlar.get("oto_senkron", True):
        ayarlar["oto_senkron"] = oto
        ayar_yaz(ayarlar)

    if st.button("🔄 Tümünü Şimdi Senkronla", type="primary"):
        with st.spinner("Güncelleniyor..."):
            for ad, ok, msg in tumunu_senkronla():
                (st.success if ok else st.error)(f"{ad}: {msg}")

    st.markdown("---")
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
                    st.success("Kaydedildi.")
            except Exception as e:
                st.warning(f"XML analiz edilemedi: {e}")
            if st.button(f"🗑️ {ad} sil", key=f"sil_{ad}"):
                tedarikciler.pop(ad, None)
                ayar_yaz(ayarlar)
                with closing(baglan()) as c:
                    c.execute("DELETE FROM urunler WHERE tedarikci=?", (ad,))
                    c.commit()
                st.rerun()


def genel_ayarlar():
    yedek = {k: v for k, v in ayarlar.items() if k != "kimlik"}
    st.download_button("⬇️ Ayar Yedeği (.json, gizlisiz)",
                       json.dumps(yedek, ensure_ascii=False, indent=2).encode("utf-8"),
                       "sahentegre_ayarlar.json", "application/json", use_container_width=True)
    yuklenen = st.file_uploader("♻️ Yedek dosyasını geri yükle (.json)", type="json", key="yedek_yukle")
    if yuklenen is not None and st.button("Geri Yükle", key="yedek_btn"):
        try:
            veri_y = json.loads(yuklenen.getvalue().decode("utf-8"))
            for k, v in veri_y.items():
                if k != "kimlik":
                    ayarlar[k] = v
            ayarlar.setdefault("tedarikciler", {})
            ayar_yaz(ayarlar)
            st.rerun()
        except Exception as e:
            st.error(f"Yüklenemedi: {e}")


def gunluk_sayfasi():
    with closing(baglan()) as c:
        lg = pd.read_sql("SELECT zaman, tedarikci, durum, mesaj FROM senkron_log ORDER BY id DESC LIMIT 200", c)
    if lg.empty:
        st.info("Kayıt yok.")
    else:
        st.dataframe(lg, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------
# PAZAR YERİ YARDIMCILARI
# ---------------------------------------------------------------
def trendruum_toplu_panel():
    key, secret = kimlik(ayarlar, "trendruum_key"), kimlik(ayarlar, "trendruum_secret")
    brand, cat = kimlik(ayarlar, "trendruum_brand"), kimlik(ayarlar, "trendruum_category")
    miktar = st.selectbox("Gönderilecek ürün", ["Tek ürün (test)", "İlk 100", "İlk 500", "Tümü"], key="tp_miktar")
    tek_stok = st.checkbox("Sadece stokta olanları gönder", value=True, key="tp_stok")
    if st.button("📤 Trendruum'a Gönder", type="primary", key="tp_gonder"):
        if not (key and secret and brand and cat):
            st.error("Key, Secret, Brand ID ve Kategori ID zorunlu.")
            return
        df = urunleri_oku()
        if tek_stok:
            df = df[df["stok"] > 0]
        df = df.head({"Tek ürün (test)": 1, "İlk 100": 100, "İlk 500": 500}.get(miktar, len(df)))
        if df.empty:
            st.warning("Gönderilecek ürün yok.")
            return
        try:
            token = trendruum_token(key, secret)
            df = fiyat_artis_uygula(ayarlar, "trendruum", df)
            liste, atlanan = trendruum_urun_listesi(df, ayarlar, brand, cat)
            bar, kutu = st.progress(0), st.empty()
            ok, top, loglar = trendruum_gonder(
                liste, token, lambda p, l: (bar.progress(p), kutu.code("\n".join(l[-15:]))))
            st.success(f"Tamamlandı: {ok}/{top} paket başarılı.")
        except Exception as e:
            st.error(f"Hata: {e}")


def siparis_paneli(pid):
    if pid == "trendruum":
        durum = st.selectbox("Durum", ["new", "in_progress", "shipped", "delivered", "completed",
                                       "cancelled", "returned", "all"], key="sp_durum")
        if st.button("Siparişleri Getir", key="sp_getir"):
            try:
                j = trendruum_siparisler(trendruum_token(kimlik(ayarlar, "trendruum_key"),
                                                         kimlik(ayarlar, "trendruum_secret")), durum)
                veri = j.get("data", j)
                if isinstance(veri, dict):
                    veri = next((v for v in veri.values() if isinstance(v, list)), [])
                if veri:
                    st.dataframe(pd.json_normalize(veri), use_container_width=True)
                else:
                    st.info("Bu durumda sipariş yok.")
            except Exception as e:
                st.error(f"Hata: {e}")
    elif pid == "trendyol":
        if st.button("Yeni Siparişleri Getir", key="sp_ty"):
            try:
                sip = trendyol_siparisler(kimlik(ayarlar, "trendyol_seller_id"), kimlik(ayarlar, "trendyol_key"),
                                          kimlik(ayarlar, "trendyol_secret"))
                if sip:
                    st.dataframe(pd.DataFrame([{"Sipariş": s.get("orderNumber"), "Tutar": s.get("totalPrice"),
                                                "Durum": s.get("status")} for s in sip]),
                                 use_container_width=True, hide_index=True)
                else:
                    st.info("Bekleyen sipariş yok.")
            except Exception as e:
                st.error(f"Hata: {e}")
    elif pid == "idefix":
        if st.button("Yeni Siparişleri Getir", key="sp_id"):
            try:
                sip = idefix_siparisler(kimlik(ayarlar, "idefix_token"), kimlik(ayarlar, "idefix_secret"),
                                        kimlik(ayarlar, "idefix_satici_id"))
                if sip:
                    st.dataframe(pd.DataFrame(sip), use_container_width=True, hide_index=True)
                else:
                    st.info("Bekleyen İdefix siparişi yok.")
            except Exception as e:
                st.error(f"Hata: {e}")
    elif pid == "n11":
        if st.button("Yeni Siparişleri Getir", key="sp_n11"):
            try:
                sip = n11_siparisler(kimlik(ayarlar, "n11_key"), kimlik(ayarlar, "n11_secret"))
                if sip:
                    st.dataframe(pd.DataFrame(sip), use_container_width=True, hide_index=True)
                else:
                    st.info("Bekleyen N11 siparişi yok.")
            except Exception as e:
                st.error(f"Hata: {e}")


# ---------------------------------------------------------------
# PAZAR YERİ SAYFALARI: TÜM İŞLEMLER / GENEL AYARLAR / AI
# ---------------------------------------------------------------
def tam_senkron(pid):
    with st.spinner("Tedarikçi XML'leri çekiliyor..."):
        for ad_, ok, msg in tumunu_senkronla(oto=False):
            (st.success if ok else st.error)(f"{ad_}: {msg}")
    if pazar_bagli(ayarlar, pid):
        with st.spinner("Pazar yerine gönderiliyor..."):
            try:
                g, h, msg = pazara_gonder(ayarlar, pid, urunleri_oku())
                st.success(f"{g} ürün gönderildi, {h} hatalı/bulunamadı.")
                st.code(msg)
            except Exception as e:
                st.error(f"Gönderilemedi: {e}")


def tum_barkodlar(pid):
    with st.spinner("Tüm barkodlar gönderiliyor..."):
        try:
            g, h, msg = pazara_gonder(ayarlar, pid, urunleri_oku())
            st.success(f"{g} ürün güncellendi, {h} hatalı/bulunamadı.")
            st.code(msg)
        except Exception as e:
            st.error(f"Hata: {e}")


def pazar_islemler(pid):
    p = PAZAR[pid]
    ad = p["ad"]
    cap = CAP.get(pid, set())
    bagli = pazar_bagli(ayarlar, pid)

    st.title(f"{p['ikon']} {ad} Tüm İşlemler")
    st.caption(f"{ad} mağazanızdaki ürünler, eşleşme durumları ve tüm işlemler.")
    
    if not bagli:
        st.warning(f"⚠️ {ad} için gerekli API bilgileri eksik veya boş. Lütfen sol menüden **'{ad} Genel Ayarlar'** sayfasına gidip bilgileri kaydedin.")

    k = f"islem_{pid}"
    st.markdown("**SENKRON**")
    c1, c2, c3 = st.columns(3)
    if c1.button("🔄 Tam Senkronizasyon", key=f"b1_{pid}", type="primary"):
        st.session_state[k] = None
        if "sync" in cap:
            tam_senkron(pid) if bagli else st.warning("Önce API bilgilerini girin.")
    if c2.button("⚠️ Kritik Stok Sıfırla", key=f"b2_{pid}"):
        st.session_state[k] = "kritik"
    if c3.button("🔢 Tüm Barkodları Güncelle", key=f"b3_{pid}"):
        st.session_state[k] = None
        if "barkod" in cap:
            tum_barkodlar(pid) if bagli else st.warning("Önce API bilgilerini girin.")

    st.markdown("**İŞLEMLER**")
    d1, d2, d3 = st.columns(3)
    if d1.button("📤 Toplu Ürün Gönder", key=f"b4_{pid}"):
        st.session_state[k] = "toplu"
    if d2.button("🚚 Kargo Süresi Ayarla", key=f"b5_{pid}"):
        st.session_state[k] = "kargo"
    if d3.button("✅ Durum Aç / Kapat" if pid == "trendruum" else "✅ Eşleme Onay / Red", key=f"b6_{pid}"):
        st.session_state[k] = "durum"

    islem = st.session_state.get(k)
    if islem:
        with st.container(border=True):
            if islem == "kritik":
                esik = st.number_input("Kritik stok eşiği", 1, 50, int(ayarlar.get("kritik_esik") or 2), key=f"ke_{pid}")
                with closing(baglan()) as c:
                    df_k = pd.read_sql("SELECT barkod, stok, satis_fiyati FROM urunler WHERE stok > 0 AND stok <= ?",
                                       c, params=(int(esik),))
                st.write(f"Etkilenecek ürün: **{len(df_k):,}**")
                onay = st.checkbox("Onaylıyorum: stoklar 0 yapılıp pazar yerine gönderilsin", key=f"ko_{pid}")
                if st.button("Sıfırla ve Gönder", key=f"kg_{pid}", disabled=not (onay and bagli and len(df_k) > 0)):
                    with closing(baglan()) as c:
                        c.execute("UPDATE urunler SET stok = 0 WHERE stok > 0 AND stok <= ?", (int(esik),))
                        c.commit()
                    df_k["stok"] = 0
                    try:
                        g, h, msg = pazara_gonder(ayarlar, pid, df_k)
                        st.success(f"{g} ürün sıfırlandı, {h} hatalı.")
                        st.code(msg)
                    except Exception as e:
                        st.error(f"Hata: {e}")
            elif islem == "toplu":
                if pid == "trendruum":
                    if bagli: trendruum_toplu_panel()
                    else: st.warning("API bilgileri eksik.")
                elif pid in ("idefix", "n11"):
                    if bagli:
                        if st.button(f"📤 {ad}'e Tüm Stok ve Fiyatları Gönder", type="primary"):
                            with st.spinner(f"{ad}'e gönderiliyor..."):
                                try:
                                    g, h, msg = pazara_gonder(ayarlar, pid, urunleri_oku())
                                    st.success(f"{ad} İşlemi Başarılı! {g} ürün güncellendi, {h} hata.")
                                    st.code(msg)
                                except Exception as e:
                                    st.error(f"{ad} Hata: {e}")
                    else:
                        st.warning(f"Önce {ad} API bilgilerini eksiksiz girin.")
                else:
                    st.info("Bu pazar yeri için toplu ürün gönderimi henüz aktif değil.")
            elif islem == "kargo":
                st.info("Kargo süresi ayarları pazar yeri paneli üzerinden yönetilmektedir.")
            elif islem == "durum":
                st.info("İşlem paneli aktif.")

    st.markdown("---")
    with closing(baglan()) as c:
        toplam = c.execute("SELECT COUNT(*) FROM urunler").fetchone()[0]
        stokta = c.execute("SELECT COUNT(*) FROM urunler WHERE stok > 0").fetchone()[0]
        tukenen = c.execute("SELECT COUNT(*) FROM urunler WHERE stok <= 0").fetchone()[0]
        ok_n = c.execute("SELECT COUNT(*) FROM pazar_durum WHERE pazar=? AND durum='ok'", (pid,)).fetchone()[0]
        hata_n = c.execute("SELECT COUNT(*) FROM pazar_durum WHERE pazar=? AND durum='hata'", (pid,)).fetchone()[0]
    m1, m2 = st.columns(2)
    m1.metric("Toplam Ürün", f"{toplam:,}")
    m2.metric("Senkronize Edilmiş", f"{ok_n:,}")
    m3, m4 = st.columns(2)
    m3.metric("Senkronize Edilememiş", f"{hata_n:,}")
    m4.metric("Stokta Olanlar", f"{stokta:,}")
    st.metric("Stok Tutmayanlar", f"{tukenen:,}")

    if bagli:
        with st.expander("🧾 Siparişler"):
            siparis_paneli(pid)


def pazar_ayar(pid):
    p = PAZAR[pid]
    st.title(f"⚙️ {p['ad']} Genel Ayarları")
    
    degerler = {}
    for etk, anahtar, parola in p["alanlar"]:
        val = gizli_input(etk, anahtar, parola)
        degerler[anahtar] = val

    pa = ayarlar.setdefault("pazar_ayarlari", {}).setdefault(pid, {})
    
    if pid == "idefix":
        pa["magaza_id"] = degerler.get("idefix_satici_id", "")
        pa["api_key"] = degerler.get("idefix_token", "")
        pa["servis_anahtari"] = degerler.get("idefix_secret", "")
    elif pid == "n11":
        pa["api_key"] = degerler.get("n1
