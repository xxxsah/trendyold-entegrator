import gzip
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter

import pandas as pd
import streamlit as st

st.set_page_config(page_title="MetEntegre", page_icon="📦", layout="wide")


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
    sayac = Counter()
    for el in kok.iter():
        if len(el) > 0:
            sayac[etiket(el.tag)] += 1
    adaylar = [(t, n) for t, n in sayac.items() if n >= 2 and t != etiket(kok.tag)]
    if not adaylar:
        return None

    def puan(a):
        tag, n = a
        ornek = next(e for e in kok.iter() if etiket(e.tag) == tag)
        return n * len(list(ornek.iter()))

    return max(adaylar, key=puan)[0]


def xml_oku(veri):
    """Ham XML baytlarından ürün tablosu (DataFrame) üretir."""
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
    """'1.234,56' ve '12.5' gibi fiyatları sayıya çevirir."""
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
    """Kolon adlarından en olası eşleşmeyi bulur."""
    for a in anahtarlar:
        for k in kolonlar:
            if a in k.lower():
                return k
    return "(yok)"


def normalle(tedarikci, df, harita, marj):
    def kol(ad):
        return df[harita[ad]] if harita[ad] != "(yok)" else pd.Series([""] * len(df))

    alis = kol("fiyat").map(sayi)
    return pd.DataFrame({
        "Tedarikçi": tedarikci,
        "Barkod/SKU": kol("kod").astype(str),
        "Ürün Adı": kol("ad").astype(str),
        "Stok": kol("stok").map(sayi).astype(int),
        "Alış Fiyatı": alis.round(2),
        "Satış Fiyatı": (alis * (1 + marj / 100)).round(2),
        "Görsel": kol("gorsel").astype(str).str.split("|").str[0],
    })


# ---------------------------------------------------------------
# ARAYÜZ
# ---------------------------------------------------------------
if "ham" not in st.session_state:
    st.session_state.ham = {}

st.sidebar.title("📦 MetEntegre")
sayfa = st.sidebar.radio("Menü", ["Ürünler (XML)", "Pazaryerleri"])

if sayfa == "Ürünler (XML)":
    st.title("Ürünler ve Tedarikçi XML")

    with st.expander("➕ Tedarikçi ekle", expanded=not st.session_state.ham):
        t_ad = st.text_input("Tedarikçi adı", placeholder="Örn: Yeni Toptancı")
        t_link = st.text_input("XML linki", placeholder="https://...")
        if st.button("XML'i çek", type="primary"):
            if not t_ad or not t_link:
                st.error("Tedarikçi adı ve XML linki gerekli.")
            else:
                try:
                    with st.spinner("XML indiriliyor..."):
                        df = xml_oku(indir(t_link.strip()))
                    st.session_state.ham[t_ad] = df
                    st.success(f"{len(df):,} ürün çekildi.")
                except Exception as e:
                    st.error(f"Çekilemedi: {e}")

    tumu = []
    for ad, df in st.session_state.ham.items():
        with st.expander(f"⚙️ {ad} - alan eşleştirme ({len(df):,} ürün)"):
            kolonlar = ["(yok)"] + list(df.columns)

            def sec(etiket_, anahtarlar, anahtar_id):
                varsayilan = tahmin(df.columns, anahtarlar)
                return st.selectbox(
                    etiket_, kolonlar, index=kolonlar.index(varsayilan),
                    key=f"{ad}_{anahtar_id}",
                )

            harita = {
                "kod": sec("Barkod / SKU", ["barkod", "barcode", "sku", "stokkod", "kod", "id"], "kod"),
                "ad": sec("Ürün adı", ["urunadi", "ürünadı", "name", "title", "ad", "baslik"], "ad"),
                "stok": sec("Stok", ["stok", "stock", "quantity", "adet", "miktar"], "stok"),
                "fiyat": sec("Alış fiyatı", ["fiyat", "price", "alis", "alış"], "fiyat"),
                "gorsel": sec("Görsel", ["resim", "image", "gorsel", "görsel", "picture", "foto"], "gorsel"),
            }
            marj = st.number_input("Kâr marjı (%)", 0.0, 500.0, 30.0, 1.0, key=f"{ad}_marj")
            if st.button(f"{ad} tedarikçisini sil", key=f"{ad}_sil"):
                del st.session_state.ham[ad]
                st.rerun()
        tumu.append(normalle(ad, df, harita, marj))

    if tumu:
        urunler = pd.concat(tumu, ignore_index=True)
        c1, c2 = st.columns(2)
        c1.metric("Toplam ürün", f"{len(urunler):,}")
        c2.metric("Stokta olan", f"{(urunler['Stok'] > 0).sum():,}")

        ara = st.text_input("🔍 Ara (ürün adı veya barkod)")
        sadece_stok = st.checkbox("Sadece stokta olanlar", value=False)
        gorunum = urunler
        if ara:
            m = (gorunum["Ürün Adı"].str.contains(ara, case=False, na=False)
                 | gorunum["Barkod/SKU"].str.contains(ara, case=False, na=False))
            gorunum = gorunum[m]
        if sadece_stok:
            gorunum = gorunum[gorunum["Stok"] > 0]

        st.dataframe(
            gorunum,
            column_config={"Görsel": st.column_config.ImageColumn("Görsel", width="small")},
            use_container_width=True,
            hide_index=True,
        )
        st.download_button(
            "⬇️ CSV indir",
            gorunum.to_csv(index=False, sep=";").encode("utf-8-sig"),
            "urunler.csv",
            "text/csv",
        )
    else:
        st.info("Henüz tedarikçi eklenmedi. Yukarıdan XML linkini ekleyin.")

else:
    st.title("Pazaryerleri")
    st.warning(
        "Hepsiburada, n11 ve PTT AVM bağlantıları henüz yazılmadı. "
        "Önce ürün çekme kısmının sorunsuz çalıştığından emin olalım."
    )
    st.markdown("Sıradaki adım: tek pazaryeri (Hepsiburada) API bağlantısı.")
