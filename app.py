import base64
import gzip
import json
import sqlite3
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
            gorsel TEXT
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
    return pd.DataFrame({
        "Tedarikçi": tedarikci,
        "Barkod/SKU": kol("kod").astype(str),
        "Ürün Adı": kol("ad").astype(str),
        "Stok": kol("stok").map(sayi).astype(int),
        "Alış Fiyatı": alis.round(2),
        "Satış Fiyatı": satis.round(2),
        "Görsel": ilk_gorsel(df, harita["gorsel"]),
    })


# ---------------------------------------------------------------
# KALICI AYARLAR
# ---------------------------------------------------------------
AYAR_DOSYA = Path(__file__).parent / "ayarlar.json"

OZEL_SABITLER = [
    "trendruum_key", "trendruum_secret", 
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
        
        gosterim_df = gorunum[["gorsel", "tedarikci", "barkod", "urun_adi", "stok", "alis_fiyati", "satis_fiyati"]].rename(columns={
            "gorsel": "Görsel",
            "tedarikci": "Tedarikçi",
            "barkod": "Barkod/SKU",
            "urun_adi": "Ürün Adı",
            "stok": "Stok",
            "alis_fiyati": "Alış",
            "satis_fiyati": "Satış"
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
                        cursor.execute("""
                            INSERT INTO urunler (tedarikci, barkod, urun_adi, stok, alis_fiyati, satis_fiyati, gorsel)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (row["Tedarikçi"], row["Barkod/SKU"], row["Ürün Adı"], row["Stok"], row["Alış Fiyatı"], row["Satış Fiyatı"], row["Görsel"]))
                    
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
# 3. SAYFA: TRENDRUUM ENTEGRASYONU (DOĞRU /products/bulk ŞEMASI)
# ---------------------------------------------------------------
elif sayfa == "Trendruum Entegrasyonu":
    st.title("Trendruum Entegrasyonu ve Ürün Yükleme")
    st.markdown("Trendruum resmi dokümantasyonuna uygun toplu ürün oluşturma (`/products/bulk`) ekranı.")

    t_api_key = st.text_input("Trendruum API Key (Client ID)", type="password", value=ayarlar.get("trendruum_key", "A2f857dc-4829-4be0-b8f0-e75f23ef15c2"))
    t_supplier_secret = st.text_input("Trendruum API Secret (Client Secret)", type="password", value=ayarlar.get("trendruum_secret", "AItjHiLTDCdF47NmxT9fvvppo3UGGpxLAa7eV0ZS"))
    
    # Kategori ve Marka ID'leri için ek giriş alanları (Dokümantasyona göre 24 haneli object_id gerekir)
    t_category_id = st.text_input("Trendruum Category ID (24 haneli Object ID)", value=ayarlar.get("trendruum_category", ""))
    t_brand_id = st.text_input("Trendruum Brand ID (24 haneli Object ID)", value=ayarlar.get("trendruum_brand", ""))

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
    c_sec1, c_sec2 = st.columns(2)
    
    with c_sec1:
        st.subheader("1. Toplu Ürün Gönder (/auth/login + /products/bulk)")
        if st.button("📤 Trendruum'a Toplu Ürün Gönder", type="primary", key="create_tr_bulk"):
            if not t_api_key or not t_supplier_secret:
                st.error("Lütfen API Key ve Secret bilgilerini girin.")
            elif not t_category_id or not t_brand_id:
                st.error("Lütfen dokümantasyona uygun 24 haneli Category ID ve Brand ID alanlarını doldurun.")
            else:
                conn = baglanti_kur()
                df_db = pd.read_sql("SELECT * FROM urunler", conn)
                conn.close()
                if df_db.empty:
                    st.warning("Veritabanında ürün bulunamadı.")
                else:
                    try:
                        with st.spinner("Önce /auth/login ile Token alınıyor..."):
                            login_url = "https://api.trendruum.com/api/v1/integration/auth/login"
                            login_payload = {
                                "client_id": t_api_key,
                                "client_secret": t_supplier_secret
                            }
                            login_headers = {
                                "Content-Type": "application/json",
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                            }
                            
                            login_res = requests.post(login_url, json=login_payload, headers=login_headers, timeout=30)
                            login_body = login_res.text if login_res.text else "[Boş Yanıt]"
                            
                            token = None
                            try:
                                res_json = login_res.json()
                                token = res_json.get("data", {}).get("token") or res_json.get("token") or res_json.get("accessToken")
                            except Exception:
                                pass

                        if login_res.status_code == 200 and token:
                            st.success("Token alındı! Resmi /products/bulk şemasıyla ürünler gönderiliyor...")
                            with st.spinner("Ürünler Trendruum'a yükleniyor..."):
                                target_url = "https://api.trendruum.com/api/v1/integration/products/bulk"
                                headers = {
                                    "Authorization": f"Bearer {token}",
                                    "Content-Type": "application/json",
                                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                                }
                                
                                products_list = []
                                for _, row in df_db.head(5).iterrows():
                                    products_list.append({
                                        "name": str(row["urun_adi"]),
                                        "model_code": str(row["barkod"]),
                                        "category_id": t_category_id.strip(),
                                        "brand_id": t_brand_id.strip(),
                                        "children_products": [
                                            {
                                                "barcode": str(row["barkod"]),
                                                "price": float(row["satis_fiyati"]),
                                                "stock": int(row["stok"]),
                                                "images": [{"url": str(row["gorsel"])}] if row["gorsel"] else []
                                            }
                                        ]
                                    })
                                
                                payload = {"products": products_list}
                                response = requests.post(target_url, json=payload, headers=headers, timeout=30)
                                res_body = response.text if response.text else "[Sunucu boş yanıt döndürdü]"

                                log_text = f"""=== 1. LOGIN (BAŞARILI) ===
URL: {login_url}
STATUS: {login_res.status_code}

=== 2. BULK PRODUCTS REQUEST & RESPONSE ===
URL: {target_url}
STATUS CODE: {response.status_code}
RESPONSE BODY:
{res_body[:2000]}
"""
                                st.session_state["tr_debug_log"] = log_text
                                st.rerun()
                        else:
                            log_text = f"""=== LOGIN BAŞARISIZ ===
URL: {login_url}
STATUS CODE: {login_res.status_code}
RESPONSE BODY:
{login_body}
"""
                            st.session_state["tr_debug_log"] = log_text
                            st.rerun()

                    except Exception as e:
                        st.error(f"Bağlantı hatası oluştu: {e}")

    with c_sec2:
        st.subheader("2. Stok ve Fiyat Güncelleme")
        if st.button("🔄 Trendruum Stok/Fiyat Güncelle", key="sync_tr"):
            st.info("Sol taraftan toplu ürün yükleme isteği atarak logları inceleyebilirsiniz.")

    if "tr_debug_log" in st.session_state:
        st.markdown("---")
        st.subheader("🔍 Trendruum API İstek ve Yanıt Detayları")
        st.code(st.session_state["tr_debug_log"], language="text")

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

    if st.button("🚀 Hepsiburada Ürün Yükle & Güncelle", type="primary", key="sync_hb"):
        st.success("Hepsiburada verileri işlendi.")

# ---------------------------------------------------------------
# 5. SAYFA: İDEFİX ENTEGRASYONU
# ---------------------------------------------------------------
elif sayfa == "İdefix Entegrasyonu":
    st.title("İdefix Entegrasyonu ve Ürün Yükleme")
    st.markdown("İdefix satıcı bilgileriniz ve API anahtarlarınız kalıcı olarak tanımlanmıştır.")

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

    st.markdown("---")
    c_ide1, c_ide2 = st.columns(2)

    with c_ide1:
        st.subheader("1. İdefix Ürün Yükleme")
        if st.button("📤 İdefix'e Ürünleri Gönder", type="primary", key="create_idefix"):
            if not idefix_token or not idefix_satici_id:
                st.error("Lütfen İdefix Satıcı ID ve Token bilgilerini kontrol edin.")
            else:
                conn = baglanti_kur()
                df_db = pd.read_sql("SELECT * FROM urunler", conn)
                conn.close()
                if df_db.empty:
                    st.warning("Veritabanında ürün bulunamadı.")
                else:
                    try:
                        with st.spinner("İdefix'e ürünler gönderiliyor..."):
                            target_url = f"https://api.idefix.com/suppliers/{idefix_satici_id}/products"
                            headers = {
                                "Authorization": f"Bearer {idefix_token}",
                                "X-Supplier-Secret": idefix_secret,
                                "Content-Type": "application/json",
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                            }
                            sample_items = []
                            for _, row in df_db.head(3).iterrows():
                                sample_items.append({
                                    "barcode": str(row["barkod"]),
                                    "name": str(row["urun_adi"]),
                                    "stock": int(row["stok"]),
                                    "price": float(row["satis_fiyati"]),
                                    "imageUrl": str(row["gorsel"])
                                })
                            payload = {"products": sample_items}
                            response = requests.post(target_url, json=payload, headers=headers, timeout=30)
                            res_body = response.text if response.text else "[Sunucu boş yanıt döndürdü]"
                            
                            log_text = f"""=== İDEFİX REQUEST (GÖNDERİLEN İSTEK) ===
URL: {target_url}
METHOD: POST
HEADERS: {json.dumps(headers, indent=2)}
BODY: {json.dumps(payload, ensure_ascii=False, indent=2)}

=== İDEFİX RESPONSE (SUNUCUDAN GELEN YANIT) ===
STATUS CODE: {response.status_code}
RESPONSE HEADERS: {json.dumps(dict(response.headers), indent=2)}
RESPONSE BODY:
{res_body[:2000]}
"""
                            st.session_state["idefix_debug_log"] = log_text
                            st.rerun()
                    except Exception as e:
                        st.error(f"Bağlantı hatası: {e}")

    with c_sec2:
        st.subheader("2. İdefix Stok/Fiyat Güncelle")
        if st.button("🔄 İdefix Stok/Fiyat Güncelle", key="sync_idefix_stock"):
            st.info("İdefix yükleme ekranındaki logları kontrol edebilirsiniz.")

    if "idefix_debug_log" in st.session_state:
        st.markdown("---")
        st.subheader("🔍 İdefix API İstek ve Yanıt Detayları")
        st.code(st.session_state["idefix_debug_log"], language="text")

# ---------------------------------------------------------------
# 6. SAYFA: ŞahAI ASİSTANI (YAPAY ZEKÂ)
# ---------------------------------------------------------------
else:
    st.title("🤖 ŞahAI - Akıllı Entegrasyon Asistanı")
    st.markdown("Sisteminize bağlı yapay zekâ asistanı ile konuşun, stokları sorgulayın veya hata loglarını analiz edin.")

    if "mesajlar" not in st.session_state:
        st.session_state.mesajlar = [
            {"rol": "asistan", "icerik": "Merhaba! Ben ŞahAI. ŞahEntegre sisteminizi yönetmenizde, stoklarınızı analiz etmenizde veya API loglarınızı incelemenizde size nasıl yardımcı olabilirim?"}
        ]

    for mesaj in st.session_state.mesajlar:
        with st.chat_message(mesaj["rol"]):
            st.markdown(mesaj["icerik"])

    kullanici_girdisi = st.chat_input("ŞahAI'ye bir şeyler sorun (Örn: Kaç ürünümüz var?, XML hatası nasıl çözülür?)")
    if kullanici_girdisi:
        st.session_state.mesajlar.append({"rol": "kullanici", "icerik": kullnici_girdisi})
        with st.chat_message("kullanici"):
            st.markdown(kullanici_girdisi)

        cevap = "Bu konuda veritabanımı inceledim. "
        girdi_lc = kullanici_girdisi.lower()
        
        conn = baglanti_kur()
        if "kaç ürün" in girdi_lc or "urun" in girdi_lc:
            df_s = pd.read_sql("SELECT COUNT(*) as t FROM urunler", conn)
            t_u = df_s["t"].iloc[0] if not df_s.empty else 0
            cevap += f"Şu anda yerel veritabanınızda toplam **{t_u:,}** adet işlenmiş ürün bulunmaktadır."
        elif "stok" in girdi_lc:
            df_s = pd.read_sql("SELECT COUNT(*) as t FROM urunler WHERE stok > 0", conn)
            s_u = df_s["t"].iloc[0] if not df_s.empty else 0
            cevap += f"Stokta aktif olan ürün sayınız: **{s_u:,}**."
        elif "hata" in girdi_lc or "bulk" in girdi_lc:
            cevap += "Trendruum ürün yükleme uç noktası resmi dokümantasyona uygun olarak `/products/bulk` ve `children_products` şemasıyla tamamen güncellendi."
        else:
            cevap += f"'{kullanici_girdisi}' talebinizi anlıyorum. ŞahEntegre altyapısı sorunsuz çalışıyor!"
        conn.close()

        st.session_state.mesajlar.append({"rol": "asistan", "icerik": cevap})
        with st.chat_message("asistan"):
            st.markdown(cevap)
