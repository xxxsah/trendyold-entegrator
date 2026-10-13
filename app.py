import base64
import gzip
import json
import random
import sqlite3
import time
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="ŞahEntegre", page_icon="👑", layout="wide")

# ---------------------------------------------------------------
# VERİTABANI (SQLITE) YÖNETİMİ
# ---------------------------------------------------------------
DB_DOSYA = Path(__file__).parent / "metentegre.db"

def baglanti_kur():
    conn = sqlite3.connect(DB_DOSYA)
    return conn

def veritabani_olustur():
    conn = baglanti_kur()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS urunler (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tedarikci TEXT,
            barkod TEXT,
            urun_adi TEXT,
            stok INTEGER,
            alis_fiyati REAL,
            satis_fiyati REAL,
            gorsel TEXT,
            kategori TEXT
        )
    """)
    conn.commit()
    conn.close()

veritabani_olustur()

# ---------------------------------------------------------------
# XML OKUMA FONKSİYONLARI
# ---------------------------------------------------------------
def etiket(tag):
    return tag.split("}", 1)[-1]


def indir(url):
    istek = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 Chrome/120 Safari/537.36",
            "Accept": "application/xml,text/xml,*/*",
            "Accept-Encoding": "gzip",
        },
    )
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
    sayac = Counter()
    for el in kok.iter():
        if len(el) > 0:
            sayac[etiket(el.tag)] += 1
    adaylar = {t for t, n in sayac.items() if n >= 2 and t != etiket(kok.tag)}

    def ic_icede(el):
        p = ebeveyn.get(el)
        while p is not None:
            if etiket(p.tag) in adaylar:
                return True
            p = ebeveyn.get(p)
        return False

    dis = {etiket(el.tag) for el in kok.iter()
           if etiket(el.tag) in adaylar and not ic_icede(el)}
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
        raise ValueError(f"Bu geçerli bir XML değil. Gelen içerik: {ilk}")
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
    adaylar += [c for c in df.columns
                if c != secili and "image" in c.lower() and "count" not in c.lower()]
    sonuc = pd.Series([""] * len(df), index=df.index)
    for c in adaylar:
        deger = df[c].astype(str).str.split("|").str[0].str.strip()
        sonuc = sonuc.where(sonuc != "", deger)
    return sonuc.str.replace("http://", "https://", regex=False)


def normalle(tedarikci, df, harita, marj, sabit_ek):
    def kol(ad):
        return df[harita[ad]] if harita[ad] != "(yok)" else pd.Series([""] * len(df))

    alis = kol("fiyat").map(sayi)
    satis = (alis * (1 + marj / 100)) + sabit_ek
    
    kat_kolon = harita.get("kategori", "(yok)")
    kategori_seri = df[kat_kolon].astype(str) if kat_kolon in df.columns and kat_kolon != "(yok)" else pd.Series(["Genel"] * len(df))

    return pd.DataFrame({
        "Tedarikçi": tedarikci,
        "Barkod/SKU": kol("kod").astype(str),
        "Ürün Adı": kol("ad").astype(str),
        "Stok": kol("stok").map(sayi).astype(int),
        "Alış Fiyatı": alis.round(2),
        "Satış Fiyatı": satis.round(2),
        "Görsel": ilk_gorsel(df, harita["gorsel"]),
        "Kategori": kategori_seri
    })


# ---------------------------------------------------------------
# KALICI AYARLAR
# ---------------------------------------------------------------
AYAR_DOSYA = Path(__file__).parent / "ayarlar.json"

OZEL_SABITLER = [
    "trendruum_key", "trendruum_secret", 
    "trendruum_category", "trendruum_brand",
    "idefix_satici_id", "idefix_token", "idefix_secret"
]

VARSAYILAN_AYARLAR = {
    "HepsiBayi": {
        "link": "https://hepsicdn.com.tr/xml/MTAyMXwzNDUxMDQwNjU2NA==.87dc64ceb93877f2445185e59ef953febddfb61c01c326e4a4fc364220b20905", 
        "harita": {}, 
        "marj": 30.0,
        "sabit_ek": 0.0
    },
    "trendruum_key": "A2f857dc-4829-4be0-b8f0-e75f23ef15c2",
    "trendruum_secret": "AItjHiLTDCdF47NmxT9fvvppo3UGGpxLAa7eV0ZS",
    "trendruum_category": "689f312ebc7c381f4a07f47f",
    "trendruum_brand": "689f57d8bef381990805c0c0",
    "idefix_satici_id": "27837",
    "idefix_token": "929c122e-87bd-4aba-a293-0c731bf4e5ff",
    "idefix_secret": "8c510c89-9d4c-4d36-b411-9024c0b7f42d"
}

def ayar_oku():
    try:
        if AYAR_DOSYA.exists():
            veri = json.loads(AYAR_DOSYA.read_text(encoding="utf-8"))
            degisti = False
            for k in OZEL_SABITLER:
                if k not in veri:
                    veri[k] = VARSAYILAN_AYARLAR[k]
                    degisti = True
            for k, v in VARSAYILAN_AYARLAR.items():
                if k not in veri:
                    veri[k] = v
                    degisti = True
            if degisti:
                ayar_yaz(veri)
            return veri
        else:
            ayar_yaz(VARSAYILAN_AYARLAR)
            return VARSAYILAN_AYARLAR
    except Exception:
        return VARSAYILAN_AYARLAR


def ayar_yaz(ayarlar):
    try:
        AYAR_DOSYA.write_text(
            json.dumps(ayarlar, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        st.warning(f"Ayarlar diske yazılamadı: {e}")


def sifre_al():
    try:
        return st.secrets["APP_PASSWORD"]
    except Exception:
        return None


# ---------------------------------------------------------------
# ŞİFRE KORUMASI
# ---------------------------------------------------------------
sifre = sifre_al()
if sifre:
    if not st.session_state.get("giris_ok"):
        st.markdown("""
            <style>
            .stApp {
                background: linear-gradient(135deg, #1f1c2c 0%, #928dab 100%);
            }
            .login-card {
                background: rgba(255, 255, 255, 0.08);
                padding: 40px;
                border-radius: 20px;
                box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
                backdrop-filter: blur(8px);
                -webkit-backdrop-filter: blur(8px);
                border: 1px solid rgba(255, 255, 255, 0.18);
                text-align: center;
                max-width: 450px;
                margin: 80px auto;
            }
            .sah-title {
                font-size: 42px;
                font-weight: 800;
                color: #ffffff;
                letter-spacing: 1px;
                margin-bottom: 10px;
            }
            .sah-logo {
                font-size: 60px;
                margin-bottom: -10px;
            }
            </style>
            
            <div class="login-card">
                <div class="sah-logo">👑</div>
                <div class="sah-title"><span style="color: #ffd700; font-size: 50px;">Ş</span>ahEntegre</div>
                <p style="color: #e0e0e0; font-size: 15px; margin-bottom: 25px;">Yönetim Paneli Giriş Ekranı</p>
            </div>
        """, unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns([1, 1.2, 1])
        with col2:
            girilen = st.text_input("🔑 Yönetici Şifresi", type="password")
            if st.button("Sisteme Giriş Yap", type="primary", use_container_width=True):
                if girilen == sifre:
                    st.session_state.giris_ok = True
                    st.rerun()
                else:
                    st.error("❌ Hatalı şifre, lütfen tekrar deneyin.")
        st.stop()


# ---------------------------------------------------------------
# AÇILIR / KAPANIR SOL YAN MENÜ
# ---------------------------------------------------------------
if "ayarlar" not in st.session_state:
    st.session_state.ayarlar = ayar_oku()
ayarlar = st.session_state.ayarlar

st.sidebar.title("👑 ŞahEntegre")

sayfa = st.sidebar.radio("Menü", [
    "Anasayfa & Hızlı İşlemler",
    "Ürünler (Veritabanı)", 
    "Tedarikçiler & XML", 
    "Trendruum Entegrasyonu", 
    "Hepsiburada Entegrasyonu", 
    "İdefix Entegrasyonu",
    "🤖 ŞahAI Asistanı"
])

st.sidebar.markdown("---")
st.sidebar.subheader("💾 Yedekleme")
st.sidebar.download_button(
    "Ayarları İndir (.json)",
    json.dumps(ayarlar, ensure_ascii=False, indent=2).encode("utf-8"),
    "sahentegre_ayarlar.json",
    "application/json",
    use_container_width=True
)

# ---------------------------------------------------------------
# 0. SAYFA: ANASAYFA & PAZAR YERİ KUTULARI (ÜSTTE)
# ---------------------------------------------------------------
if sayfa == "Anasayfa & Hızlı İşlemler":
    st.title("👑 Mağaza ve Pazar Yeri Özeti")

    st.subheader("🛒 Pazar Yeri Sipariş Durumları")
    col_p1, col_p2, col_p3 = st.columns(3)

    with col_p1:
        with st.container(border=True):
            st.markdown("### 🟠 HEPSİBURADA")
            st.caption("Bekleyen Sipariş Yok")
            if st.button("Hepsiburada Detayları", key="btn_hb"):
                st.session_state["pazar_detay"] = "Hepsiburada"

        with st.container(border=True):
            st.markdown("### 🟤 PTT AVM")
            st.caption("Bekleyen Sipariş Yok")
            if st.button("PTT AVM Detayları", key="btn_ptt"):
                st.session_state["pazar_detay"] = "PTT AVM"

    with col_p2:
        with st.container(border=True):
            st.markdown("### 🔴 TRENDYOL")
            st.caption("Bekleyen Sipariş Yok")
            if st.button("Trendyol Detayları", key="btn_ty"):
                st.session_state["pazar_detay"] = "Trendyol"

        with st.container(border=True):
            st.markdown("### 🔴 N11")
            st.caption("Bekleyen Sipariş Yok")
            if st.button("N11 Detayları", key="btn_n11"):
                st.session_state["pazar_detay"] = "N11"

    with col_p3:
        with st.container(border=True):
            st.markdown("### 🌸 ÇİÇEKSEPETİ")
            st.caption("Bekleyen Sipariş Yok")
            if st.button("Çiçeksepeti Detayları", key="btn_cs"):
                st.session_state["pazar_detay"] = "Çiçeksepeti"

        with st.container(border=True):
            st.markdown("### 🟢 İDEFİX")
            st.caption("Aktif / Bağlantı Bekleniyor")
            if st.button("İdefix Detayları", key="btn_ide"):
                st.session_state["pazar_detay"] = "İdefix"

    if "pazar_detay" in st.session_state:
        secilen_pazar = st.session_state["pazar_detay"]
        st.info(f"📍 **{secilen_pazar}** entegrasyon canlıya alındığında siparişleriniz doğrudan buraya dökülecektir.")

    st.markdown("---")

    st.subheader("⚡ Hızlı İşlem Araçları")
    if st.button("⚠️ Kritik Stokları Sıfırla (0 Yap)", type="primary", use_container_width=True):
        conn = baglanti_kur()
        cursor = conn.cursor()
        cursor.execute("SELECT barkod, urun_adi FROM urunler WHERE stok > 0 AND stok <= 2")
        etkilenenler = cursor.fetchall()
        
        cursor.execute("UPDATE urunler SET stok = 0 WHERE stok > 0 AND stok <= 2")
        conn.commit()
        conn.close()

        st.markdown("### 🚨 Kritik Stok Sıfırlama Raporu")
        if etkilenenler:
            for barkod, urun_adi in etkilenenler:
                st.markdown(f"✅ **Patron, {barkod}** Barkodlu Ürün Stok Eşiğinde — Mağazada Stok **0** Ladım! 🎯")
            st.success(f"Tamamlandı! **{len(etkilenenler)}** ürün stok 0 yapıldı — harika patron!")
        else:
            st.info("Kritik eşikte (stok 1 veya 2 olan) güncellenecek ürün bulunamadı.")

# ---------------------------------------------------------------
# 1. SAYFA: ÜRÜNLER (VERİTABANI LİSTESİ)
# ---------------------------------------------------------------
elif sayfa == "Ürünler (Veritabanı)":
    st.title("Ürün Yönetimi ve Stoklar")

    conn = baglanti_kur()
    df_db = pd.read_sql("SELECT * FROM urunler", conn)
    conn.close()

    if not df_db.empty:
        c1, c2, c3 = st.columns(3)
        c1.metric("Toplam Ürün", f"{len(df_db):,}")
        c2.metric("Stokta Olanlar", f"{(df_db['stok'] > 0).sum():,}")
        c3.metric("Tükenenler", f"{(df_db['stok'] <= 0).sum():,}")

        st.markdown("---")
        ara = st.text_input("🔍 Hızlı Ara (Ürün adı veya Barkod/SKU)")
        sadece_stok = st.checkbox("Sadece stokta olanları göster", value=False)
        goster = st.selectbox("Gösterilecek ürün sayısı", [50, 100, 250, 500, 1000], index=1)

        gorunum = df_db.copy()
        if ara:
            m = (gorunum["urun_adi"].str.contains(ara, case=False, na=False)
                 | gorunum["barkod"].str.contains(ara, case=False, na=False))
            gorunum = gorunum[m]
        if sadece_stok:
            gorunum = gorunum[gorunum["stok"] > 0]

        st.caption(f"Filtrelenen {len(gorunum):,} üründen ilk {min(goster, len(gorunum)):,} tanesi listeleniyor.")
        
        gosterim_cols = [c for c in ["gorsel", "tedarikci", "barkod", "urun_adi", "stok", "alis_fiyati", "satis_fiyati", "kategori"] if c in gorunum.columns]
        gosterim_df = gorunum[gosterim_cols].rename(columns={
            "gorsel": "Görsel",
            "tedarikci": "Tedarikçi",
            "barkod": "Barkod/SKU",
            "urun_adi": "Ürün Adı",
            "stok": "Stok",
            "alis_fiyati": "Alış",
            "satis_fiyati": "Satış",
            "kategori": "Kategori"
        })

        st.dataframe(
            gosterim_df.head(goster),
            column_config={"Görsel": st.column_config.ImageColumn("Görsel", width="small")},
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Veritabanında henüz ürün bulunmuyor. 'Tedarikçiler & XML' sekmesinden XML ekleyip senkronize edebilirsiniz.")

# ---------------------------------------------------------------
# 2. SAYFA: TEDARİKÇİLER & XML YÖNETİMİ
# ---------------------------------------------------------------
elif sayfa == "Tedarikçiler & XML":
    st.title("Tedarikçi ve XML Ayarları")

    with st.expander("➕ Yeni Tedarikçi Ekle", expanded=not any(k not in OZEL_SABITLER for k in ayarlar)):
        t_ad = st.text_input("Tedarikçi Adı", placeholder="Örn: HepsiBayi")
        t_link = st.text_input("XML Linki", placeholder="https://...")
        if st.button("Kaydet ve Ekle", type="primary"):
            if not t_ad or not t_link:
                st.error("Tedarikçi adı ve linki zorunludur.")
            else:
                ayarlar[t_ad] = {"link": t_link.strip(), "harita": {}, "marj": 30.0, "sabit_ek": 0.0}
                ayar_yaz(ayarlar)
                st.success(f"{t_ad} eklendi.")
                st.rerun()

    tedarikciler = {k: v for k, v in ayarlar.items() if k not in OZEL_SABITLER}
    if tedarikciler:
        st.markdown("---")
        if st.button("🔄 Tüm XML'leri Çek ve Veritabanını Güncelle", type="primary"):
            tum_veriler = []
            with st.spinner("XML'ler indiriliyor ve veritabanı güncelleniyor..."):
                for ad, bilgi in tedarikciler.items():
                    try:
                        ham_veri = indir(bilgi["link"])
                        df_hammadde = xml_oku(ham_veri)
                        marj = bilgi.get("marj", 30.0)
                        sabit_ek = bilgi.get("sabit_ek", 0.0)
                        islenmis = normalle(ad, df_hammadde, bilgi.get("harita", {}), marj, sabit_ek)
                        tum_veriler.append(islenmis)
                    except Exception as e:
                        st.error(f"{ad} çekilemedi: {e}")

                if tum_veriler:
                    birlesti = pd.concat(tum_veriler, ignore_index=True)
                    conn = baglanti_kur()
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM urunler")
                    
                    for _, row in birlesti.iterrows():
                        kat = row.get("Kategori", "Genel")
                        cursor.execute("""
                            INSERT INTO urunler (tedarikci, barkod, urun_adi, stok, alis_fiyati, satis_fiyati, gorsel, kategori)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (row["Tedarikçi"], row["Barkod/SKU"], row["Ürün Adı"], row["Stok"], row["Alış Fiyatı"], row["Satış Fiyatı"], row["Görsel"], kat))
                    
                    conn.commit()
                    conn.close()
                    st.success("Tüm stok ve fiyatlar kuralına göre güncellendi!")
                    st.rerun()

        st.markdown("---")
        st.subheader("Kayıtlı Tedarikçiler, Marj ve Sabit Kargo Ayarları")
        for ad, bilgi in list(tedarikciler.items()):
            with st.expander(f"⚙️ {ad} (Ayarları Yönet)"):
                st.text(f"Link: {bilgi.get('link')}")
                
                try:
                    ham = indir(bilgi["link"])
                    df_test = xml_oku(ham)
                    kolonlar = ["(yok)"] + list(df_test.columns)
                    eski_harita = bilgi.get("harita", {})

                    def sec(etiket_, anahtarlar, anahtar_id):
                        varsayilan = eski_harita.get(anahtar_id)
                        if varsayilan not in kolonlar:
                            varsayilan = tahmin(df_test.columns, anahtarlar)
                        return st.selectbox(
                            etiket_, kolonlar, index=kolonlar.index(varsayilan),
                            key=f"{ad}_{anahtar_id}",
                        )

                    harita = {
                        "kod": sec("Barkod / SKU", ["barkod", "barcode", "sku", "stokkod", "kod", "id"], "kod"),
                        "ad": sec("Ürün Adı", ["urunadi", "ürünadı", "name", "title", "ad", "baslik"], "ad"),
                        "stok": sec("Stok", ["stok", "stock", "quantity", "adet", "miktar"], "stok"),
                        "fiyat": sec("Alış Fiyatı", ["fiyat", "price", "alis", "alış"], "fiyat"),
                        "gorsel": sec("Görsel", ["image_1", "resim", "image", "gorsel", "görsel", "picture", "foto"], "gorsel"),
                        "kategori": sec("Kategori", ["kategori", "category", "cat", "tur", "grup"], "kategori")
                    }
                    
                    marj = st.number_input("Kâr Marjı (%)", 0.0, 500.0, float(bilgi.get("marj", 30.0)), 1.0, key=f"{ad}_marj")
                    sabit_ek = st.number_input("Sabit Ek Ücret / Kargo Bedeli (TL)", 0.0, 5000.0, float(bilgi.get("sabit_ek", 0.0)), 5.0, key=f"{ad}_sabit_ek")

                    if harita != eski_harita or marj != bilgi.get("marj") or sabit_ek != bilgi.get("sabit_ek"):
                        ayarlar[ad]["harita"] = harita
                        ayarlar[ad]["marj"] = marj
                        ayarlar[ad]["sabit_ek"] = sabit_ek
                        ayar_yaz(ayarlar)
                        st.success("Ayarlar kaydedildi.")

                except Exception as e:
                    st.warning(f"XML analiz edilemedi: {e}")

                if st.button(f"🗑️ {ad} Tedarikçisini Sil", key=f"sil_{ad}"):
                    ayarlar.pop(ad, None)
                    ayar_yaz(ayarlar)
                    st.rerun()

# ---------------------------------------------------------------
# 3. SAYFA: TRENDRUUM ENTEGRASYONU (DİNAMİK KATEGORİ DESTEKLİ)
# ---------------------------------------------------------------
elif sayfa == "Trendruum Entegrasyonu":
    st.title("Trendruum Entegrasyonu ve Kolay ID Seçimi")
    st.markdown("Trendruum API anahtarlarınız ve kategori/marka seçim paneli.")

    t_api_key = st.text_input("Trendruum API Key (Client ID)", type="password", value=ayarlar.get("trendruum_key", "A2f857dc-4829-4be0-b8f0-e75f23ef15c2"))
    t_supplier_secret = st.text_input("Trendruum API Secret (Client Secret)", type="password", value=ayarlar.get("trendruum_secret", "AItjHiLTDCdF47NmxT9fvvppo3UGGpxLAa7eV0ZS"))
    
    st.caption("👇 **Aşağıdaki Kategori ID'si arama motorundan seçtiğiniz doğru kategorinin ID'sidir:**")
    t_category_id = st.text_input("Trendruum Category ID (24 haneli Object ID)", value=ayarlar.get("trendruum_category", "689f312ebc7c381f4a07f47f"))
    t_brand_id = st.text_input("Trendruum Brand ID (24 haneli Object ID)", value=ayarlar.get("trendruum_brand", "689f57d8bef381990805c0c0"))

    if (t_api_key != ayarlar.get("trendruum_key") or 
        t_supplier_secret != ayarlar.get("trendruum_secret") or
        t_category_id != ayarlar.get("trendruum_category") or
        t_brand_id != ayarlar.get("trendruum_brand")):
        ayarlar["trendruum_key"] = t_api_key
        ayarlar["trendruum_secret"] = t_supplier_secret
        ayarlar["trendruum_category"] = t_category_id
        ayarlar["trendruum_brand"] = t_brand_id
        ayar_yaz(ayarlar)

    st.markdown("---")
    
    # KATEGORİ VE MARKA BULUCU
    st.subheader("🔍 Kategori ve Marka Arama Aracı")
    st.info("💡 **İpucu:** Babydoll/Fantazi Giyim gibi ürünleri göndermeden önce Kategori Arama kutusuna örn: **Babydoll** veya **Giyim** yazıp 'Kategorileri Getir'e basın. Seçtiğiniz kategori otomatik kaydedilir.")
    col_kesif1, col_kesif2 = st.columns(2)

    with col_kesif1:
        st.markdown("##### 📂 Kategori Bul")
        kat_kelime = st.text_input("Kategori Kelimesi", value="Babydoll", key="kat_input")
        if st.button("Kategorileri Getir", key="btn_kat"):
            try:
                l_res = requests.post("https://api.trendruum.com/api/v1/integration/auth/login", 
                                      json={"client_id": t_api_key, "client_secret": t_supplier_secret}, timeout=15)
                l_json = {}
                try:
                    l_json = l_res.json() if l_res.text else {}
                except Exception:
                    pass
                
                token = ""
                if isinstance(l_json, dict):
                    token = l_json.get("data", {}).get("token") or l_json.get("token") or ""
                
                if token:
                    c_res = requests.get(f"https://api.trendruum.com/api/v1/integration/categories?name={kat_kelime}", 
                                         headers={"Authorization": f"Bearer {token}"}, timeout=20)
                    c_json = {}
                    try:
                        c_json = c_res.json() if c_res.text else {}
                    except Exception:
                        pass
                    
                    data = c_json.get("data", []) if isinstance(c_json, dict) else []
                    
                    if not data:
                        c_res_all = requests.get("https://api.trendruum.com/api/v1/integration/categories", 
                                                 headers={"Authorization": f"Bearer {token}"}, timeout=20)
                        c_all_json = {}
                        try:
                            c_all_json = c_res_all.json() if c_res_all.text else {}
                        except Exception:
                            pass
                        data = c_all_json.get("data", []) if isinstance(c_all_json, dict) else []

                    liste = []
                    def duz_oku(items):
                        for item in items:
                            if isinstance(item, dict):
                                _id = item.get("_id") or item.get("id")
                                _name = item.get("name") or item.get("title")
                                if _id and _name:
                                    liste.append({"ID (Kopyala)": _id, "Kategori Adı": _name})
                                if "children" in item and isinstance(item["children"], list):
                                    duz_oku(item["children"])

                    if isinstance(data, list):
                        duz_oku(data)

                    if liste:
                        df_kat = pd.DataFrame(liste)
                        st.dataframe(df_kat, use_container_width=True, hide_index=True)
                        secilen_cat = st.selectbox("Aşağıdan Doğru Kategoriyi Seçin", df_kat["ID (Kopyala)"] + " - " + df_kat["Kategori Adı"])
                        if secilen_cat:
                            yeni_cat_id = secilen_cat.split(" - ")[0]
                            ayarlar["trendruum_category"] = yeni_cat_id
                            ayar_yaz(ayarlar)
                            st.success(f"✅ Yeni Kategori ID ({yeni_cat_id}) başarıyla kaydedildi! Şimdi ürün gönderebilirsiniz.")
                    else:
                        st.warning("Hiç kategori bulunamadı.")
                else:
                    st.error("Giriş yapılamadı.")
            except Exception as e:
                st.error(f"Hata: {e}")

    with col_kesif2:
        st.markdown("##### 🏷️ Marka Bul")
        mar_kelime = st.text_input("Marka Kelimesi", value="Irmak", key="mar_input")
        if st.button("Markaları Getir", key="btn_mar"):
            try:
                l_res = requests.post("https://api.trendruum.com/api/v1/integration/auth/login", 
                                      json={"client_id": t_api_key, "client_secret": t_supplier_secret}, timeout=15)
                l_json = {}
                try:
                    l_json = l_res.json() if l_res.text else {}
                except Exception:
                    pass
                
                token = ""
                if isinstance(l_json, dict):
                    token = l_json.get("data", {}).get("token") or l_json.get("token") or ""
                
                if token:
                    b_res = requests.get(f"https://api.trendruum.com/api/v1/integration/brands?search={mar_kelime}", 
                                         headers={"Authorization": f"Bearer {token}"}, timeout=20)
                    b_json = {}
                    try:
                        b_json = b_res.json() if b_res.text else {}
                    except Exception:
                        pass
                    
                    data = b_json.get("data", []) if isinstance(b_json, dict) else []

                    liste = []
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict):
                                _id = item.get("_id") or item.get("id")
                                _name = item.get("name") or item.get("title")
                                if _id and _name:
                                    liste.append({"ID (Kopyala)": _id, "Marka Adı": _name})

                    if liste:
                        df_mar = pd.DataFrame(liste)
                        st.dataframe(df_mar, use_container_width=True, hide_index=True)
                        secilen_brand = st.selectbox("Aşağıdan Seçin", df_mar["ID (Kopyala)"] + " - " + df_mar["Marka Adı"])
                        if secilen_brand:
                            ayarlar["trendruum_brand"] = secilen_brand.split(" - ")[0]
                            ayar_yaz(ayarlar)
                            st.success("Brand ID kaydedildi.")
                    else:
                        st.warning("Marka bulunamadı.")
                else:
                    st.error("Giriş yapılamadı.")
            except Exception as e:
                st.error(f"Hata: {e}")

    st.markdown("---")
    c_sec1, c_sec2 = st.columns(2)
    
    with c_sec1:
        st.subheader("2. Toplu Ürün Gönder (/products/bulk)")
        gonderim_miktari = st.selectbox("Kaç Ürün Gönderilsin?", ["Sadece Tek Ürün (Test İçin)", "İlk 100 Ürün", "İlk 500 Ürün", "Tüm Veritabanı"], index=0)

        if st.button("📤 Trendruum'a Toplu Ürün Gönder", type="primary", key="create_tr_bulk"):
            if not t_api_key or not t_supplier_secret:
                st.error("Lütfen API Key ve Secret bilgilerini girin.")
            elif not t_category_id or not t_brand_id:
                st.error("Lütfen Category ID ve Brand ID alanlarını doldurun.")
            else:
                conn = baglanti_kur()
                df_db = pd.read_sql("SELECT * FROM urunler", conn)
                conn.close()

                if "Tek Ürün" in gonderim_miktari:
                    df_db = df_db.head(1)
                elif "100 Ürün" in gonderim_miktari:
                    df_db = df_db.head(100)
                elif "500 Ürün" in gonderim_miktari:
                    df_db = df_db.head(500)

                if df_db.empty:
                    st.warning("Veritabanında ürün bulunamadı.")
                else:
                    try:
                        login_url = "https://api.trendruum.com/api/v1/integration/auth/login"
                        login_res = requests.post(login_url, json={"client_id": t_api_key.strip(), "client_secret": t_supplier_secret.strip()}, timeout=30)
                        
                        login_json = {}
                        try:
                            login_json = login_res.json() if login_res.text else {}
                        except Exception:
                            pass

                        token = ""
                        if isinstance(login_json, dict):
                            token = login_json.get("data", {}).get("token") or login_json.get("token") or ""

                        if login_res.status_code == 200 and token:
                            target_url = "https://api.trendruum.com/api/v1/integration/products/bulk"
                            headers = {
                                "Authorization": f"Bearer {token}",
                                "Content-Type": "application/json",
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                            }
                            
                            tum_urunler = []
                            for idx, row in df_db.iterrows():
                                orijinal_kod = str(row["barkod"]).strip()
                                
                                temiz_barkod = "".join(filter(str.isdigit, orijinal_kod))
                                if len(temiz_barkod) < 8:
                                    temiz_barkod = f"869{abs(hash(orijinal_kod)) % 1000000000:09d}"

                                gorsel_url = str(row["gorsel"]).strip()
                                images_arr = [gorsel_url] if gorsel_url else ["https://via.placeholder.com/600"]
                                
                                tum_urunler.append({
                                    "name": str(row["urun_adi"]),
                                    "model_code": orijinal_kod,
                                    "category_id": t_category_id.strip(),
                                    "brand_id": t_brand_id.strip(),
                                    "children_products": [
                                        {
                                            "barcode": temiz_barkod,
                                            "stock_code": orijinal_kod,
                                            "price": float(row["satis_fiyati"]),
                                            "stock": int(row["stok"]),
                                            "tax": 20,
                                            "images": images_arr
                                        }
                                    ]
                                })
                            
                            paket_boyutu = 50
                            toplam_paket = (len(tum_urunler) + paket_boyutu - 1) // paket_boyutu
                            basarili_paket = 0
                            
                            prog_bar = st.progress(0)
                            status_text = st.empty()
                            log_box = st.empty()
                            
                            detay_loglar = []

                            for idx, i in enumerate(range(0, len(tum_urunler), paket_boyutu)):
                                paket = tum_urunler[i:i + paket_boyutu]
                                current_p = idx + 1
                                status_text.info(f"⏳ **Paket {current_p} / {toplam_paket} gönderiliyor...**")
                                
                                payload = {"products": paket}
                                try:
                                    response = requests.post(target_url, json=payload, headers=headers, timeout=30)
                                    if response.status_code in [200, 202]:
                                        basarili_paket += 1
                                        try:
                                            resp_json = response.json()
                                            resp_str = json.dumps(resp_json, ensure_ascii=False, indent=2)
                                        except Exception:
                                            resp_str = response.text
                                        detay_loglar.append(f"✅ Paket {current_p}: Başarılı (HTTP {response.status_code})\n{resp_str}")
                                    else:
                                        try:
                                            err_json = response.json()
                                            err_str = json.dumps(err_json, ensure_ascii=False, indent=2)
                                        except Exception:
                                            err_str = response.text
                                        detay_loglar.append(f"❌ Paket {current_p} HATA (HTTP {response.status_code}):\n{err_str}")
                                except Exception as inner_e:
                                    detay_loglar.append(f"⚠️ Paket {current_p} Bağlantı Hatası: {inner_e}")
                                
                                prog_bar.progress(current_p / toplam_paket)
                                log_box.code("\n\n".join(detay_loglar))
                                time.sleep(0.1)

                            status_text.success(f"🎉 **İşlem Tamamlandı!** Başarılı Paket: {basarili_paket} / {toplam_paket}")
                        else:
                            st.error(f"Giriş Yapılamadı (HTTP {login_res.status_code}). Yanıt: {login_res.text}")

                    except Exception as e:
                        st.error(f"Hata oluştu: {e}")

    with c_sec2:
        st.subheader("3. Stok ve Fiyat Güncelleme")
        if st.button("🔄 Trendruum Stok/Fiyat Güncelle", key="sync_tr"):
            st.info("Logları aşağıdan kontrol edebilirsiniz.")

# ---------------------------------------------------------------
# 4. SAYFA: HEPSİBURADA ENTEGRASYONU
# ---------------------------------------------------------------
elif sayfa == "Hepsiburada Entegrasyonu":
    st.title("Hepsiburada Entegrasyonu")
    hb_merchant_id = st.text_input("Hepsiburada Merchant ID", value=ayarlar.get("hb_merchant_id", ""))
    hb_user = st.text_input("Hepsiburada API Kullanıcı Adı", value=ayarlar.get("hb_user", ""))
    hb_pass = st.text_input("Hepsiburada API Şifresi", type="password", value=ayarlar.get("hb_pass", ""))

    if st.button("Bilgileri Kaydet", key="save_hb"):
        ayarlar["hb_merchant_id"] = hb_merchant_id
        ayarlar["hb_user"] = hb_user
        ayarlar["hb_pass"] = hb_pass
        ayar_yaz(ayarlar)
        st.success("Hepsiburada bilgileri kaydedildi.")

# ---------------------------------------------------------------
# 5. SAYFA: İDEFİX ENTEGRASYONU
# ---------------------------------------------------------------
elif sayfa == "İdefix Entegrasyonu":
    st.title("İdefix Entegrasyonu ve Ürün Yükleme")
    idefix_satici_id = st.text_input("İdefix Tedarikçi / Satıcı ID", value=ayarlar.get("idefix_satici_id", "27837"))
    idefix_token = st.text_input("İdefix API Token / Key", type="password", value=ayarlar.get("idefix_token", "929c122e-87bd-4aba-a293-0c731bf4e5ff"))
    idefix_secret = st.text_input("İdefix API Secret", type="password", value=ayarlar.get("idefix_secret", "8c510c89-9d4c-4d36-b411-9024c0b7f42d"))

    if (idefix_satici_id != ayarlar.get("idefix_satici_id") or 
        idefix_token != ayarlar.get("idefix_token") or 
        idefix_secret != ayarlar.get("idefix_secret")):
        ayarlar["idefix_satici_id"] = idefix_satici_id
        ayarlar["idefix_token"] = idefix_token
        ayarlar["idefix_secret"] = idefix_secret
        ayar_yaz(ayarlar)

# ---------------------------------------------------------------
# 6. SAYFA: ŞahAI ASİSTANI
# ---------------------------------------------------------------
else:
    st.title("🤖 ŞahAI - Akıllı Entegrasyon Asistanı")
    st.markdown("Sisteminize bağlı yapay zekâ asistanı ile konuşun.")

    if "mesajlar" not in st.session_state:
        st.session_state.mesajlar = [
            {"rol": "asistan", "icerik": "Merhaba! Ben ŞahAI. Kategori eşleme rehberliği güncellendi."}
        ]

    for mesaj in st.session_state.mesajlar:
        with st.chat_message(mesaj["rol"]):
            st.markdown(mesaj["icerik"])

    kullanici_girdisi = st.chat_input("ŞahAI'ye bir şeyler sorun...")
    if kullanici_girdisi:
        st.session_state.mesajlar.append({"rol": "kullanici", "icerik": kullanici_girdisi})
        with st.chat_message("kullanici"):
            st.markdown(kullanici_girdisi)

        cevap = "ŞahEntegre sisteminiz tam gaz çalışıyor!"
        st.session_state.mesajlar.append({"rol": "asistan", "icerik": cevap})
        with st.chat_message("asistan"):
            st.markdown(cevap)
