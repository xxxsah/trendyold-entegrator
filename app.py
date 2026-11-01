"""ŞahEntegre - E-Ticaret Yönetim Paneli (ARAYÜZ).

Çalıştırma: streamlit run app.py
İş mantığı cekirdek.py içindedir; bu dosya yalnızca Streamlit arayüzünü içerir.
Gizli bilgiler için öncelik sırası: ortam değişkeni > st.secrets > ayarlar.json
Önerilen: APP_PASSWORD ortam değişkenini mutlaka tanımlayın.
Bildirim için (isteğe bağlı): TELEGRAM_TOKEN ve TELEGRAM_CHAT.
"""
import json
import threading
import time
from contextlib import closing
from datetime import datetime

import pandas as pd
import streamlit as st

import cekirdek as ck
from cekirdek import (  # noqa: F401  (arayüzün kullandığı çekirdek adları)
    AYAR_UYARI, GUNCELLEYICI, OTO_ANAHTAR, OTO_BAYRAK, PAZAR, PAZAR_AD, PAZAR_KIMLIK, VARSAYILAN_HEDEF,
    VARSAYILAN_KADEME, DURUM_ETIKET, DOVIZ_SON,
    _f, _i, acil_durdur_uygula, arka_plan_dongusu, ayar_oku, ayar_yaz,
    baglan, baglanti_testi, bildir, db_olustur, fiyat_artis_uygula, fiyat_sabit_kaldir, fiyat_sabit_sozluk,
    fiyat_sabitle, fiyat_yeniden_hesapla, giris_engeli_kalan, giris_hata_kaydet, giris_hata_sifirla,
    hb_agac_yukle, hb_kategori_sema, hb_oto_dugumler, hb_urun_gonder, hb_urun_listesi, hedef_fiyat,
    idefix_agac_yukle, idefix_batch_sorgula, idefix_gonder, idefix_marka_ara, idefix_marka_getir,
    idefix_oto_dugumler, idefix_onayla, idefix_sonuc_ozet, idefix_urun_listesi, indir, jeton_gecerli,
    kademe_temizle, kademeli_marj, kara_liste_maskesi, kat_sec, kategori_oner, kategori_siralama, kimlik,
    kv_oku, log_yaz, n11_urun_gonder, n11_urun_listesi, net_kar_hesapla, objectid_mi, oturum_jetonu,
    oturumlari_iptal, para_metni, pa_al, pazar_bagli, pazar_yetim_barkodlar, pazar_yetim_sifirla,
    pazara_gonder, ptt_kategori_agaci, ptt_kategori_duzlestir, ptt_kategori_getir, ptt_sonuc_ozet,
    ptt_sonuc_sorgula, ptt_urun_gonder, ptt_urun_listesi, sabit_barkod, senkron_dk_degeri,
    senkron_gecikme_dk, siparis_cek, sifre_al, sifre_dogru_mu, stok_kilidi_kaldir, stok_sifir_kume,
    stok_sifirla, stok_ust_degeri, stoklari_yeniden_hesapla, tahmin, takip_oku, tedarikci_senkron,
    tr_norm, trendruum_agac_yukle, trendruum_gonder, trendruum_kategori_ara, trendruum_kategori_duzlestir,
    trendruum_kategori_sema, trendruum_urun_listesi, tumunu_senkronla, url_guvenli, urun_ara,
    urunleri_oku, xml_oku, yedek_coz, yedek_sifrele, kayit_listesi, siparis_stok_kontrol,
)

st.set_page_config(page_title="ŞahEntegre - E-Ticaret Yönetim Paneli", page_icon="👑", layout="wide")

ayarlar = {}  # main() içinde her çalışmada diskten yüklenir


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


def kod_goster(yer, metin_):
    """Uzun log satırlarını kaydırmadan okunsun diye satır kaydırmalı gösterir."""
    try:
        yer.code(metin_, wrap_lines=True)
    except TypeError:
        yer.code(metin_)


@st.cache_data(ttl=600, show_spinner=False)
def xml_onizleme(url, okuma_sn=300):
    return xml_oku(indir(url, okuma_sn))


@st.cache_resource
def arka_plan_baslat():
    t = threading.Thread(target=arka_plan_dongusu, daemon=True)
    t.start()
    return t


ANA_MENU = [
    ("Anasayfa", "🏠 Anasayfa", "#dbeafe"),
    ("Bildirim", "🔔 Bildirimler", "#fef3c7"),
    ("Urunler", "📦 Sistemdeki Ürünler", "#f8fafc"),
    ("Kritik", "🔄 Oto Kritik Stok", "#dbeafe"),
]
ALT = [("siparis", "Siparişler", "🧾"), ("islemler", "Tüm İşlemleri", "🔗"), ("ayar", "Genel Ayarları", "⚙️")]


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


def git(sayfa_id):
    st.session_state["sayfa"] = sayfa_id


def git_pazar(pid, alt):
    st.session_state["acik_pazar"] = pid
    st.session_state["sayfa"] = f"{pid}:{alt}"


def ac_kapa(pid):
    st.session_state["acik_pazar"] = None if st.session_state.get("acik_pazar") == pid else pid


def cikis_yap():
    oturumlari_iptal()  # eski jetonlar (URL'deki ?t=) artık geçersiz
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
            kalan = giris_engeli_kalan()  # sunucu tarafı sayaç: yeni sekme/oturum açmak sıfırlamaz
            if kalan > 0:
                st.error(f"⏳ Çok fazla hatalı deneme. {kalan} saniye sonra tekrar deneyin.")
            elif sifre_dogru_mu(girilen, sifre):
                giris_hata_sifirla()
                st.session_state.giris_ok = True
                st.query_params["t"] = oturum_jetonu(sifre)
                st.rerun()
            else:
                giris_hata_kaydet()
                st.error("❌ Hatalı şifre.")
    st.stop()


def secili_urunler(df, anahtar):
    if df.empty or "tedarikci" not in df.columns:
        return df
    liste = sorted(df["tedarikci"].dropna().unique().tolist())
    sec = st.multiselect("Gönderilecek Tedarikçileri Seçin", liste, default=liste, key=f"{anahtar}_ted_sec")
    return df[df["tedarikci"].isin(sec)] if sec else df.iloc[0:0]


# --------------------------------------------------------------------------
# Güvenlik / uyarı paneli
# --------------------------------------------------------------------------
def son_log_mesaji(durum, parca, saat=24):
    """Son 'saat' içindeki en yeni günlük kaydı (durum ve mesajda geçen parça) ya da None."""
    with closing(baglan()) as c:
        r = c.execute("SELECT zaman, tedarikci, mesaj FROM senkron_log WHERE durum = ? AND mesaj LIKE ? ORDER BY id DESC LIMIT 1",
                      (durum, f"%{parca}%")).fetchone()
    try:
        if r and (datetime.now() - datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S")).total_seconds() < saat * 3600:
            return r
    except (TypeError, ValueError):
        pass
    return None


def guvenlik_paneli():
    """Her sayfanın üstünde: bozuk ayar, stok/sipariş uyarıları, acil durdurma ve bayat stok uyarıları."""
    if AYAR_UYARI.get("bozuk_yedek"):
        st.error(f"🛑 ayarlar.json bozuktu; {AYAR_UYARI['bozuk_yedek']} adıyla yedeklendi ve BOŞ ayarlarla başlandı. "
                 "API anahtarlarınızı/ayarlarınızı bu yedekten ya da bir yedek dosyasından geri yükleyin.")
    sip = son_log_mesaji("UYARI", "siparişte stok sorunu")
    if sip:
        st.error(f"📦 SİPARİŞTE STOK SORUNU ({sip[0]}): {sip[2]}")
    sup = son_log_mesaji("HATA", "XML şüpheli")
    if sup:
        st.error(f"🧯 {sup[1]}: tedarikçi XML'i şüpheli bulundu, senkron durduruldu (eski veri korunuyor). {sup[2][:250]}")
    tukenen = son_log_mesaji("UYARI", "TÜKENEN ürünün stoğu")
    if tukenen:
        st.warning(f"⚠️ {tukenen[1]}: {tukenen[2]}")
    for m in st.session_state.pop("acil_sonuc", []) or []:
        st.info(m)
    if ayarlar.get("acil_durdur"):
        st.error("🚨 ACİL DURDURMA AÇIK: pazar yerlerine tüm ürünlerde stok 0 gönderiliyor, satış alınmaz. "
                 "Kapatmak için kenar çubuğundaki düğmeyi kullanın.")
    if ayarlar.get("tedarikciler"):
        dk, bayat = senkron_gecikme_dk(ayarlar)
        if not ayarlar.get("oto_senkron", True):
            st.warning("⚠️ Otomatik stok senkronu KAPALI. Stoklar tedarikçiden otomatik gelmiyor, stoksuz satış riski var. "
                       "Ayarlar > Tedarikçiler'den açın.")
        elif bayat:
            gecen = "hiç yapılmamış" if dk is None else (f"{int(dk)} dakika önce" if dk < 120 else f"{dk / 60:.1f} saat önce")
            st.warning(f"⚠️ Son başarılı stok senkronu {gecen}. Stoklar eski olabilir. "
                       "Ayarlar > Tedarikçiler'den 'Tümünü Şimdi Senkronla'ya basın.")


def acil_kontrol_kenar():
    st.sidebar.markdown("---")
    if ayarlar.get("acil_durdur"):
        st.sidebar.error("🚨 ACİL DURDURMA AÇIK")
        if gen(st.sidebar.button, "✅ Satışa geri aç", key="acil_kapat"):
            with st.spinner("Gerçek stoklar pazar yerlerine gönderiliyor..."):
                sonuc = acil_durdur_uygula(ayarlar, False)
            st.session_state["acil_sonuc"] = ["Acil durdurma kapatıldı."] + [
                f"{ad}: {ok} gönderildi" + (f", hata: {h}" if h else "") for ad, ok, h in sonuc]
            st.rerun()
    else:
        with st.sidebar.expander("🚨 Acil durdur"):
            st.caption("Tüm pazar yerlerinde tüm ürünlerin stoğunu 0 yapar (satış alınmaz). Stok güvenilmezken kullanın.")
            onay = st.checkbox("Onaylıyorum", key="acil_onay")
            if gen(st.button, "Tüm pazarlarda stoğu 0'la", key="acil_ac", disabled=not onay):
                with st.spinner("Stoklar sıfırlanıyor..."):
                    sonuc = acil_durdur_uygula(ayarlar, True)
                st.session_state["acil_sonuc"] = ["Acil durdurma AÇILDI."] + [
                    f"{ad}: {ok} gönderildi" + (f", hata: {h}" if h else "") for ad, ok, h in sonuc]
                st.rerun()


# --------------------------------------------------------------------------
# Kategori / marka bulucular ve eşleştirme (arayüz)
# --------------------------------------------------------------------------
def varsayilan_kategori_yaz(pid, cid):
    """Varsayılan kategori ID'sini kaydeder; formun yeni değeri göstermesi için sayfayı yeniler."""
    pa_al(ayarlar, pid)["category_id"] = str(cid).strip()
    ayar_yaz(ayarlar)
    st.session_state[f"vk_bilgi_{pid}"] = str(cid).strip()
    st.rerun()


def marka_id_yaz(pid, marka_id):
    pa_al(ayarlar, pid)["brand_id"] = str(marka_id).strip()
    ayar_yaz(ayarlar)
    st.session_state[f"marka_bilgi_{pid}"] = str(marka_id).strip()
    st.rerun()


def kategoriye_ata_paneli(pid, secilen):
    """Bulucuda seçilen pazar yeri kategorisini, bir tedarikçi kategorisine tek tıkla atar."""
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
    etiket_ = {}
    for k in adet.index:
        etiket_[f"{k} ({int(adet[k])} ürün){isaret if mevcut.get(k) else ''}"] = k
    sec = st.selectbox("Bu kategoriyi şu tedarikçi kategorisine ata", list(etiket_), key=f"ata_sec_{pid}")
    if gen(st.button, "Seçili kategoriyi bu tedarikçi kategorisine ata", key=f"ata_btn_{pid}"):
        k = etiket_[sec]
        yeni = dict(mevcut)
        yeni[k] = str(secilen)
        pa_al(ayarlar, pid)["kategori_eslesme"] = yeni
        ayar_yaz(ayarlar)
        st.session_state[f"ata_bilgi_{pid}"] = (f"'{k}' kategorisi artık {secilen} ID'sine eşleşti. Önceki gönderilmiş ürünler "
                                                "değişmez; gerekirse silip yeniden gönderin.")
        st.rerun()


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
                "liste": ptt_kategori_duzlestir(j) if j is not None else [], "json": j,
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
            varsayilan_kategori_yaz("ptt", sec.split(" — ")[0].strip())
    else:
        st.warning("Listede kategori okunamadı; ham yanıtı aşağıdan inceleyebilirsiniz.")
        with st.expander("Ham yanıt"):
            if g.get("json") is not None:
                st.json(g["json"])
            else:
                st.text(g["ham"])


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


def hb_kategori_bulucu():
    if not pazar_bagli(ayarlar, "hb"):
        st.caption("Kategori aramak için önce Hepsiburada API bilgilerini kaydedin.")
        return
    st.caption("Önce 'Kategorileri yükle'ye basın (bir kez, birkaç yüz satır olabilir), sonra ürün tipini yazıp arayın. "
               "Seçeceğiniz kategori ürünün gerçek (uç) kategorisi olmalı.")
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
    st.dataframe(pd.DataFrame(bulunan), hide_index=True)
    secenek = [f"{k['ID']} — {k['Kategori']}" for k in bulunan]
    sec = st.selectbox("Listeden seçin", secenek, key="hbk_sec")
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


def idefix_marka_bulucu():
    if not pazar_bagli(ayarlar, "idefix"):
        st.caption("Marka aramak için önce İdefix API bilgilerini kaydedin.")
        return
    st.caption("Ürünler bu markayla yüklenir. 'Özel marka = evet' olan markalara yetkiniz yoksa İdefix ürünü "
               "VENDOR_BRAND_ACCESS_DENIED ile reddeder.")
    kayitli = str(pa_al(ayarlar, "idefix").get("brand_id", "") or "").strip()
    if kayitli and gen(st.button, f"Kayıtlı Marka ID ({kayitli}) hangi marka?", key="idm_kontrol"):
        try:
            m = idefix_marka_getir(ayarlar, kayitli)
            st.info(f"{m['ID']} = {m['Marka']} (özel marka: {m['Özel marka']}, tür: {m['Tür']})")
        except Exception as e:
            st.error(f"Hata: {e}")
    ad = st.text_input("Marka adı", key="idm_ara")
    if gen(st.button, "Marka ara", key="idm_ara_btn"):
        try:
            st.session_state["idm_sonuc"] = idefix_marka_ara(ayarlar, ad)
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
    secenek = [f"{m['ID']} — {m['Marka']} (özel: {m['Özel marka']})" for m in liste]
    sec = st.selectbox("Listeden seçin", secenek, key="idm_sec")
    secilen = sec.split(" — ")[0].strip()
    if gen(st.button, "Bu markayı Marka ID olarak kaydet", key="idm_kaydet"):
        marka_id_yaz("idefix", secilen)


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
    sec = st.selectbox("Listeden seçin", secenek, key="idk_sec")
    secilen = sec.split(" — ")[0].strip()
    mevcut_vk = pa_al(ayarlar, "idefix").get("category_id") or "(boş)"
    st.caption(f"Şu an kayıtlı varsayılan kategori ID: {mevcut_vk}")
    kategoriye_ata_paneli("idefix", secilen)
    if gen(st.button, "Varsayılan kategori yap", key="idk_varsayilan"):
        varsayilan_kategori_yaz("idefix", secilen)


def oto_esleme(pid, pa, adet, mevcut):
    st.markdown("**Otomatik öneri**")
    pazar_ad = {"trendruum": "Trendruum", "hb": "Hepsiburada", "idefix": "İdefix"}.get(pid, pid)
    st.caption(f"{pazar_ad} kategori listesini çekip tedarikçi kategorilerinize en yakın kategoriyi önerir. "
               "Hiçbir şey kendiliğinden kaydedilmez; işaretlediğiniz satırlar kaydedilir.")
    bildirim = st.session_state.pop(f"oto_bildirim_{pid}", None)
    if bildirim:
        st.success(bildirim)
    tek_tus = gen(st.button, "⚡ Tek tuş: hepsini bul, yüksek güvenlileri kaydet", key=f"oto_tek_{pid}", type="primary")
    if gen(st.button, "Önerileri hazırla (önce ben bakayım)", key=f"oto_hazirla_{pid}") or tek_tus:
        try:
            with st.spinner("Kategori listesi alınıyor..."):
                dugumler = {"trendruum": trendruum_agac_yukle, "hb": hb_oto_dugumler, "idefix": idefix_oto_dugumler}[pid](ayarlar)
            satirlar = []
            for k in adet.index:
                if mevcut.get(k):
                    continue
                i, y, g = kategori_oner(k, dugumler)
                satirlar.append({"Onayla": g == "yuksek", "Tedarikçi kategorisi": k, "Ürün": int(adet[k]),
                                 "Önerilen kategori": y,
                                 "Güven": {"yuksek": "Yüksek", "orta": "Orta", "dusuk": "Düşük"}.get(g, "Yok"), "ID": i})
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
    st.caption(f"{len(sat)} eşleşmemiş kategori için öneri hazır. 'Yüksek' güvenliler işaretli geldi; "
               "'Orta/Düşük' olanları kendiniz kontrol edip işaretleyin.")
    duz = st.data_editor(d, hide_index=True, key=f"oto_{pid}_{len(d)}",
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
    if pid in ("trendruum", "hb", "idefix"):
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
    duz = st.data_editor(tablo, hide_index=True, disabled=["Tedarikçi kategorisi", "Ürün sayısı"],
                         key=f"kat_edit_{pid}_{ara}_{sadece_bos}")
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
                yeni["stok_kodu_barkod"] = c2.checkbox("Geçerli barkodu olmayan ürünlerde stok kodunu barkod yerine kullan",
                                                       value=bool(pa.get("stok_kodu_barkod")))
            if pid == "hb":
                yeni["urun_endpoint"] = st.text_input("Ürün oluşturma adresi (tam https URL, Hepsiburada dokümanından)",
                                                      value=str(pa.get("urun_endpoint", "") or ""),
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
                yeni["gecici_barkod"] = st.checkbox("Geçerli barkodu olmayan ürünlere kalıcı geçici barkod üret (869…)",
                                                    value=bool(pa.get("gecici_barkod", True)))
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
# Tedarikçi sayfası
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
    st.caption("Her turda tedarikçi XML'i yenilenir ve stok/fiyat pazar yerlerine gönderilir. Aralık değişikliği bir sonraki "
               "döngüde geçerli olur. Çok kısa aralık pazar yerinde sınır aşımına yol açabilir.")
    ust = st.number_input("Stok üst sınırı (0 = sınırsız; tedarikçinin stoğu aynen gider)", 0, 1000000, stok_ust_degeri(ayarlar))
    pay = st.number_input("Güvenlik payı (pazar yerine giden stoktan düşülecek adet)", 0, 100,
                          _i(ayarlar.get("stok_guvenlik_payi")),
                          help="Tedarikçide 3 varsa ve pay 2 ise pazar yerine 1 gider; stok payın altına düşünce 0 gider. "
                               "Stoksuz satış riskini azaltır. Önerilen: 1 veya 2.")
    tavan = st.number_input("Pazar yerinde en fazla gösterilecek stok (0 = sınırsız)", 0, 100000,
                            _i(ayarlar.get("pazar_stok_tavani")),
                            help="Tedarikçide 100 olsa da pazar yerinde en fazla bu kadar görünür. Tedarikçi stoğu aniden "
                                 "biterse en fazla bu kadar stoksuz satış olur.")
    oto = st.toggle(f"🤖 Otomatik senkronizasyon ({int(dk)} dakikada bir)", value=ayarlar.get("oto_senkron", True))
    if (oto, int(dk), int(ust), int(pay), int(tavan)) != (
            ayarlar.get("oto_senkron", True), int(senkron_dk_degeri(ayarlar)), stok_ust_degeri(ayarlar),
            _i(ayarlar.get("stok_guvenlik_payi")), _i(ayarlar.get("pazar_stok_tavani"))):
        ayarlar.update({"oto_senkron": oto, "senkron_dk": int(dk), "stok_ust_sinir": int(ust),
                        "stok_guvenlik_payi": int(pay), "pazar_stok_tavani": int(tavan)})
        ayar_yaz(ayarlar)
        if int(ust) != stok_ust_degeri(ayarlar):
            pass

    with st.expander("🛡️ Stok güvenliği (stoksuz satışı önleyen korumalar)", expanded=True):
        g1, g2 = st.columns(2)
        dus = g1.number_input("Ürün sayısı en fazla % kaç düşebilir?", 5, 100, _i(ayarlar.get("xml_dusus_siniri"), 30),
                              help="Tedarikçi XML'inde ürün sayısı bundan fazla azalırsa XML yarım inmiş sayılır; senkron reddedilir, "
                                   "eski veri korunur.")
        sdus = g2.number_input("Stoklu ürün sayısı en fazla % kaç düşebilir?", 5, 100, _i(ayarlar.get("stok_dusus_siniri"), 70),
                               help="Stoklu ürün sayısı bundan fazla düşerse XML şüpheli sayılır. Gerçek toplu tükenme "
                                    "olduysa aşağıdaki 'Düşüşü kabul et' ile senkronlayın.")
        sip = st.checkbox("Yeni siparişte tedarikçi stoğu yetersizse uyar (panel + Telegram)",
                          value=bool(ayarlar.get("siparis_stok_uyari", True)))
        bay = st.checkbox("Senkron çok gecikirse tüm pazarlarda stoğu otomatik 0'la (senkron düzelince geri açılır)",
                          value=bool(ayarlar.get("bayat_otomatik_durdur")))
        bdk = st.number_input("Bu kadar dakika senkron olmazsa durdur", 30, 1440, _i(ayarlar.get("bayat_durdur_dk"), 120))
        yeni_g = {"xml_dusus_siniri": int(dus), "stok_dusus_siniri": int(sdus), "siparis_stok_uyari": sip,
                  "bayat_otomatik_durdur": bay, "bayat_durdur_dk": int(bdk)}
        if any(ayarlar.get(k) != v for k, v in yeni_g.items()):
            ayarlar.update(yeni_g)
            ayar_yaz(ayarlar)
            st.success("Güvenlik ayarları kaydedildi.")
        st.caption("Telegram bildirimi için Genel Ayarlar > Bildirim bölümünü doldurun.")

    b1, b2 = st.columns(2)
    if b1.button("🔄 Tümünü Şimdi Senkronla", type="primary"):
        with st.spinner("Güncelleniyor..."):
            for ad, ok, msg in tumunu_senkronla(oto=False):
                (st.success if ok else st.error)(f"{ad}: {msg}")
    if b2.button("⚠️ Düşüşü kabul et ve senkronla", help="XML şüpheli bulunduysa ve tedarikçi gerçekten ürün/stok "
                                                     "azalttıysa kullanın."):
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
                st.download_button("💾 XML Kaydet", data=st.session_state[f"xml_yedek_{ad}"],
                                   file_name=f"{ad}_yedek.xml", mime="application/xml", key=f"xml_kaydet_{ad}")
            with c2:
                onay = st.checkbox("Silmeyi onayla", key=f"sil_onay_{ad}")
                if st.button("🗑️ Tedarikçiyi Sil", key=f"sil_{ad}", disabled=not onay):
                    tedarikciler.pop(ad, None)
                    ayar_yaz(ayarlar)
                    with closing(baglan()) as c:
                        c.execute("DELETE FROM urunler WHERE tedarikci=?", (ad,))
                        c.commit()
                    st.rerun()
            zs = st.number_input("XML bekleme süresi (sn)", 30, 1800, int(_f(bilgi.get("zaman_asimi"), 300.0)), 30,
                                 key=f"{ad}_zs", help="Yavaş yanıt veren tedarikçiler için artırın.")
            if float(zs) != _f(bilgi.get("zaman_asimi"), 300.0):
                bilgi["zaman_asimi"] = float(zs)
                ayar_yaz(ayarlar)

            st.markdown("**💱 Fiyat / Para Birimi**")
            kdv_e = st.checkbox("Fiyata KDV ekle (XML'deki KDV alanından, yoksa %20)", bool(bilgi.get("kdv_ekle")), key=f"{ad}_kdv_ekle")
            dv_k = st.checkbox("Para birimi kontrolü (urun_doviz: TL / USD)", bool(bilgi.get("doviz_kontrol")), key=f"{ad}_dvk",
                               help="Açıkken USD ürünler dolar kuruyla TL'ye çevrilir. TL/USD dışı ya da boş para birimli "
                                    "ürünler gönderilmez.")
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
                st.caption("Alan eşleştirmesini düzenlemek için yukarıdaki düğmeyle XML'i yükleyin. Kayıtlı eşleştirme "
                           "senkronizasyonda aynen kullanılır.")
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
                "fiyat": sec("Alış Fiyatı", ["fiyat", "price", "alis", "alış"], "fiyat"),
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
                    st.success(f"Kaydedildi. {n_f:,} ürünün satış fiyatı yeni marj/kargo ile yeniden hesaplandı. Pazar "
                               "yerlerine göndermek için 'Tüm Stok/Fiyatları Güncelle'ye basın.")
                else:
                    st.success("Kaydedildi. Alan eşleştirmesi bir sonraki senkronizasyonda uygulanır.")
            st.markdown("**📊 Kademeli kâr marjı (alış fiyatına göre)**")
            kad_a = st.checkbox("Kademeli marjı kullan (açıkken yukarıdaki tek marj yerine geçer)",
                                bool(bilgi.get("kademe_aktif")), key=f"{ad}_kad_a")
            mevcut = kademe_temizle(bilgi.get("kademe")) or [list(r) for r in VARSAYILAN_KADEME]
            tablo = pd.DataFrame([{"Alış fiyatı bu TL'ye kadar (boş = üstü hepsi)": r[0], "Marj %": r[1]} for r in mevcut])
            duz = st.data_editor(tablo, num_rows="dynamic", hide_index=True, key=f"{ad}_kad_t")
            yeni_k = kademe_temizle([[(None if r.iloc[0] != r.iloc[0] else r.iloc[0]), r.iloc[1]] for _, r in duz.iterrows()])
            if kad_a != bool(bilgi.get("kademe_aktif")) or yeni_k != kademe_temizle(bilgi.get("kademe")):
                bilgi.update({"kademe_aktif": kad_a, "kademe": yeni_k or [list(r) for r in VARSAYILAN_KADEME]})
                ayar_yaz(ayarlar)
                n_f = fiyat_yeniden_hesapla(ad, bilgi)
                st.success(f"Kademe kaydedildi. {n_f:,} ürünün satış fiyatı yeniden hesaplandı. Pazar yerlerine göndermek "
                           "için 'Tüm Stok/Fiyatları Güncelle'ye basın.")
            if kad_a:
                ozet_k = ", ".join(("üstü" if r[0] is None else f"{int(r[0])} TL'ye kadar") + f" %{r[1]:g}"
                                   for r in kademe_temizle(bilgi.get("kademe")))
                st.caption("Örnek: " + ozet_k)
            st.markdown("**🎯 Hedef net kâr ile fiyatlama (zarar etmeden)**")
            st.caption("Komisyon, kargo ve vergiler düşüldükten sonra cebinizde kalacak NET kârı siz belirlersiniz; satış "
                       "fiyatı buna göre hesaplanır. Açıkken yukarıdaki marj ve kademe yerine geçer. Alış fiyatı KDV dahil "
                       "kabul edilir; XML fiyatı KDV hariçse 'Fiyata KDV ekle'yi açın.")
            h_aktif = st.checkbox("Hedef net kâr ile fiyatla", bool(bilgi.get("hedef_aktif")), key=f"{ad}_h_aktif")
            hc1, hc2, hc3 = st.columns(3)
            h_kargo = hc1.number_input("Kargo maliyeti (TL)", 0.0, 3000.0, _f(bilgi.get("h_kargo"), 150.0), 5.0, key=f"{ad}_h_kargo")
            h_bayi = hc2.number_input("Bayi kargo/işlem (TL)", 0.0, 1000.0, _f(bilgi.get("h_bayi_kargo"), 15.0), 1.0, key=f"{ad}_h_bayi")
            h_ek = hc3.number_input("Paketleme vb. gider (TL)", 0.0, 1000.0, _f(bilgi.get("h_ek_gider"), 0.0), 1.0, key=f"{ad}_h_ek")
            hd1, hd2, hd3 = st.columns(3)
            h_kom = hd1.number_input("Komisyon % (KDV dahil)", 0.0, 60.0, _f(bilgi.get("h_komisyon"), 20.0), 0.5, key=f"{ad}_h_kom")
            h_kdv = hd2.number_input("Satış KDV %", 0.0, 40.0, _f(bilgi.get("h_kdv"), 20.0), 1.0, key=f"{ad}_h_kdv")
            h_ver = hd3.number_input("Kâr vergisi %", 0.0, 60.0, _f(bilgi.get("h_vergi"), 0.0), 1.0, key=f"{ad}_h_ver",
                                     help="Kâr üzerinden ödenecek gelir/kurumlar vergisi. Muhasebecinize sorun; 0 yazarsanız "
                                          "hesaba katılmaz.")
            hmev = kademe_temizle(bilgi.get("hedef_kademe")) or [list(r) for r in VARSAYILAN_HEDEF]
            htablo = pd.DataFrame([{"Alış fiyatı bu TL'ye kadar (boş = üstü hepsi)": r[0], "Hedef net kâr (TL)": r[1]} for r in hmev])
            hduz = st.data_editor(htablo, num_rows="dynamic", hide_index=True, key=f"{ad}_h_t")
            h_kad = kademe_temizle([[(None if r.iloc[0] != r.iloc[0] else r.iloc[0]), r.iloc[1]] for _, r in hduz.iterrows()])
            yeni_h = {"hedef_aktif": h_aktif, "h_kargo": h_kargo, "h_bayi_kargo": h_bayi, "h_ek_gider": h_ek,
                      "h_komisyon": h_kom, "h_kdv": h_kdv, "h_vergi": h_ver,
                      "hedef_kademe": h_kad or [list(r) for r in VARSAYILAN_HEDEF]}
            if any(bilgi.get(k) != v for k, v in yeni_h.items() if k != "hedef_kademe") or \
                    kademe_temizle(bilgi.get("hedef_kademe")) != kademe_temizle(yeni_h["hedef_kademe"]):
                eski_aktif = bool(bilgi.get("hedef_aktif"))
                bilgi.update(yeni_h)
                ayar_yaz(ayarlar)
                if h_aktif or eski_aktif:
                    n_f = fiyat_yeniden_hesapla(ad, bilgi)
                    st.success(f"Kaydedildi. {n_f:,} ürünün satış fiyatı yeniden hesaplandı. Pazar yerlerine göndermek "
                               "için 'Tüm Stok/Fiyatları Güncelle'ye basın.")
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
                st.error("Bazı alış fiyatlarında bu ayarla ZARAR ediyorsunuz (Net kâr negatif). Hedef net kâr yöntemini "
                         "açın ya da marjı artırın.")
            if gen(st.button, "💲 Fiyatları şimdi yeniden hesapla", key=f"{ad}_fiyat_hesapla",
                   help="Kayıtlı alış fiyatlarından, yukarıdaki güncel marj/kargo/kademe ile satış fiyatlarını yeniden "
                        "hesaplar. XML indirmez, hızlıdır."):
                n_f = fiyat_yeniden_hesapla(ad, bilgi)
                st.success(f"{n_f:,} ürünün satış fiyatı güncel ayarla yeniden hesaplandı. Pazar yerlerine göndermek için "
                           "pazar yerinin işlemler sayfasında 'Tüm Stok/Fiyatları Güncelle'ye basın.")


# --------------------------------------------------------------------------
# Genel ayarlar, yedek, günlük
# --------------------------------------------------------------------------
def ayarlari_geri_yukle(veri_y):
    if not isinstance(veri_y, dict):
        raise ValueError("Dosya bir JSON nesnesi olmalı.")
    for k in ck.VARSAYILAN:  # yalnızca bilinen alanlar geri yüklenir
        if k == "kimlik" and isinstance(veri_y.get(k), dict):
            for ka in ck.KIMLIK_ALANLARI:
                if isinstance(veri_y[k].get(ka), str) and veri_y[k][ka].strip():
                    ayarlar["kimlik"][ka] = veri_y[k][ka]
        elif k in veri_y and isinstance(veri_y[k], type(ck.VARSAYILAN[k])):
            ayarlar[k] = veri_y[k]
    ayar_yaz(ayarlar)


def yedek_isaretle():
    ayarlar["son_yedek"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    ayar_yaz(ayarlar)


def genel_ayarlar(sifre):
    st.subheader("🔔 Bildirim (Telegram)")
    st.caption("Stoksuz satış riski, şüpheli XML, siparişte stok sorunu ve gecikmiş senkron için anında telefona haber verir. "
               "Telegram'da @BotFather ile bot oluşturup token'ı, botunuza mesaj atıp chat ID'nizi girin. "
               "Alternatif: TELEGRAM_TOKEN ve TELEGRAM_CHAT ortam değişkenleri.")
    with st.form("telegram_form"):
        tk = st.text_input("Bot token", value=ayarlar["kimlik"].get("telegram_token", ""), type="password")
        ch = st.text_input("Chat ID", value=ayarlar["kimlik"].get("telegram_chat", ""))
        if gen(st.form_submit_button, "💾 Kaydet", type="primary"):
            ayarlar["kimlik"]["telegram_token"] = tk.strip()
            ayarlar["kimlik"]["telegram_chat"] = ch.strip()
            ayar_yaz(ayarlar)
            st.success("Kaydedildi.")
    if gen(st.button, "📨 Test bildirimi gönder", key="tg_test"):
        if bildir("Test bildirimi: ŞahEntegre bildirimleri çalışıyor."):
            st.success("Gönderildi.")
        else:
            st.error("Gönderilemedi. Token ve Chat ID'yi kontrol edin (önce bota bir mesaj atmış olmalısınız).")
    st.divider()
    st.subheader("🚫 Kara liste")
    st.caption("Her satıra bir kelime. Adı, kategorisi veya barkodu bu kelimeyi içeren ürünler yeni ürün olarak "
               "HİÇBİR pazara gönderilmez; pazarda zaten varsa stok/fiyat güncellemesinde stoğu 0 yapılır (satıştan kalkar).")
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
        st.warning("Henüz yedek almadınız. Sunucu yeniden başlarsa ayarlarınız/anahtarlarınız silinebilir; yedek indirip "
                   "güvenli bir yerde saklayın.")
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
                               f"sahentegre_sifreli_yedek_{datetime.now():%Y%m%d}.json", "application/json",
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
            AYAR_UYARI["bozuk_yedek"] = ""
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


# --------------------------------------------------------------------------
# Toplu ürün oluşturma paneli
# --------------------------------------------------------------------------
def atlama_nedenleri(df, pid):
    """Gönderilemeyen ürünlerin nedenlerini sayar (kullanıcıya göstermek için)."""
    pa = pa_al(ayarlar, pid)
    say = {}

    def ekle(k):
        say[k] = say.get(k, 0) + 1

    for r in kayit_listesi(df):
        if not str(r.get("gorsel", "")).strip():
            ekle("görseli yok")
        elif pid == "hb" and not str(r.get("gorsel", "")).strip().startswith("https"):
            ekle("görsel adresi https değil")
        if _f(r.get("satis_fiyati")) <= 0:
            ekle("fiyatı 0")
        cat = kat_sec(pa, ayarlar, r.get("kategori"), pid)
        if not cat:
            ekle("kategorisi eşleştirilmemiş (varsayılan kategori kapalı)")
        elif pid == "trendruum" and not objectid_mi(cat):
            ekle("kategori ID geçersiz")
    return ", ".join(f"{k}: {v}" for k, v in say.items())


def ilk_gonderilebilir(df, pid, uretici, en_fazla=500):
    """Test modunda listenin ilk değil, gönderilebilen ilk ürününü bulur."""
    for i in range(min(len(df), en_fazla)):
        satir = df.iloc[[i]]
        liste, _ = uretici(satir, ayarlar)
        if liste:
            return satir, i
    return None, -1


def kategori_secimi_uygula(pid, df):
    """Gönderilecek kategorileri alt alta işaretlettirir; df'yi buna göre süzer."""
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
        st.caption(f"{len(eslesmeyen)} kategori ({int(adet[eslesmeyen].sum())} ürün) pazar yeri kategorisine eşleştirilmediği "
                   "için listede yok ve gönderilmez.")
    if not gosterilen:
        st.warning("Eşleştirilmiş kategori yok. Genel Ayarlar > Kategori eşleştirme bölümünden eşleştirin.")
        return df.iloc[0:0]
    st.markdown("**Gönderilecek kategoriler**")
    tumu = st.checkbox("Tüm kategorileri işaretle", value=True, key=f"{pid}_kat_tumu")
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
    return df[ana.isin(secilen).values]


def toplu_urun_paneli(pid):
    """Ürün OLUŞTURMA (N11, İdefix, Trendruum, PTT, Hepsiburada)."""
    ad = PAZAR_AD[pid]
    if not pazar_bagli(ayarlar, pid):
        st.warning(f"{ad} API bilgileri eksik. 'Genel Ayarları' sayfasından girin.")
        return
    st.info("Marka/kategori/KDV ayarları ve kategori eşleştirmesi için 'Genel Ayarları' sayfasını kullanın.")
    df = secili_urunler(urunleri_oku(), pid)
    if not df.empty and st.checkbox("Sadece stokta olanlar", value=True, key=f"{pid}_stoklu"):
        df = df[df["stok"] > 0]
    kara = kara_liste_maskesi(ayarlar, df)
    if kara.any():
        st.caption(f"🚫 Kara listedeki {int(kara.sum())} ürün gönderim dışı bırakıldı.")
        df = df[~kara]
    df = kategori_secimi_uygula(pid, df)
    mod = st.selectbox("Gönderim Modu", ["Tek ürün (Test)", "Tüm Ürünler"], key=f"{pid}_mod")
    df = fiyat_artis_uygula(ayarlar, pid, df)
    uretici = {"n11": n11_urun_listesi, "idefix": idefix_urun_listesi, "trendruum": trendruum_urun_listesi,
               "ptt": ptt_urun_listesi, "hb": hb_urun_listesi}[pid]
    if mod.startswith("Tek"):
        aranan = st.text_input("Test için ürün ara (ad veya barkod)", key=f"{pid}_tek_ara",
                               help="Boş bırakırsanız listenin gönderilebilen ilk ürünü seçilir.")
        if aranan.strip():
            q = tr_norm(aranan.strip())
            eslesen = df[df["urun_adi"].map(tr_norm).str.contains(q, regex=False) |
                         df["barkod"].astype(str).map(tr_norm).str.contains(q, regex=False)]
            if eslesen.empty:
                st.warning("Aramaya uyan ürün yok (stokta olmayanlar ve kara listedekiler listede olmaz).")
                return
            eslesen = eslesen.head(50)
            etiketler = [f"{r['urun_adi'][:70]} | {r['barkod']} | {r['satis_fiyati']:.2f} TL | stok {int(r['stok'])}"
                         for _, r in eslesen.iterrows()]
            secim = st.selectbox(f"{len(eslesen)} ürün bulundu, birini seçin", range(len(etiketler)),
                                 format_func=lambda i: etiketler[i], key=f"{pid}_tek_sec")
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
    if atlanan:
        neden = atlama_nedenleri(df, pid)
        if neden:
            st.caption("Atlanma nedenleri: " + neden)
    if not liste:
        if mod.startswith("Tek"):
            st.warning("Gönderilebilir ürün bulunamadı. Kategori eşleştirmesini yapın ya da Genel Ayarlar'da 'Eşleşmesi "
                       "olmayan ürünleri de varsayılan kategoriye koy'u açıp tek ürünle deneyin.")
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
            gonder = {"n11": n11_urun_gonder, "idefix": idefix_gonder, "trendruum": trendruum_gonder,
                      "ptt": ptt_urun_gonder, "hb": hb_urun_gonder}[pid]
            ok, hata, loglar = gonder(ayarlar, liste, ilerleme)
        except Exception as e:
            log_yaz(ad, "HATA", f"Ürün gönderimi: {e}")
            st.error(f"Hata: {e}")
            return
        dur = [x for x in loglar if x.startswith("⛔")]
        if dur:
            st.error(dur[0])
        log_yaz(ad, "OK" if hata == 0 else ("KISMİ" if ok else "HATA"), f"Ürün oluşturma: {ok} ürün iletildi, {hata} ürün hatalı.")
        (st.success if hata == 0 else st.warning)(
            f"{ok} ürün iletildi, {hata} ürün hatalı. (API kabulü = ürün onayı değildir; pazar yeri panelinden kontrol edin.)")


# --------------------------------------------------------------------------
# Pazar yeri sayfaları
# --------------------------------------------------------------------------
def pazar_ozet(pid):
    """Sistem kayıtlarına göre pazar yeri özeti (pazar yerinin canlı sayımı değildir)."""
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
            st.warning("Gönderilecek ürün bulunamadı (önce tedarikçi senkronizasyonu yapın).")
        else:
            (st.success if hata == 0 else st.warning)(
                f"{ad}: {ok} ürün iletildi, {hata} hata. (API kabulü = pazar yerinde işlendi demek değildir.)")
    except Exception as e:
        st.error(f"Hata: {e}")


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
    if gen(c1.button, "🔄 Tam Senkronizasyon", key=f"b1_{pid}", type="primary", disabled=not bagli,
           help="Önce tedarikçi XML'lerini yeniler, sonra stok/fiyatı bu pazara gönderir."):
        st.session_state[k] = None
        with st.spinner("Tedarikçiler güncelleniyor..."):
            for tad, ok_, msg in tumunu_senkronla(oto=False):
                (st.success if ok_ else st.error)(f"{tad}: {msg}")
        gonder_ve_goster(pid, secili_ted)
    if gen(c2.button, "⚠️ Kritik Stok Sıfırla", key=f"b2_{pid}"):
        st.session_state[k] = "kritik"
    if gen(c3.button, "🔢 Tüm Stok/Fiyatları Güncelle", key=f"b3_{pid}", disabled=not bagli,
           help="Veritabanındaki mevcut stok/fiyatı bu pazara gönderir."):
        st.session_state[k] = None
        gonder_ve_goster(pid, secili_ted)
    if pid in ("n11", "idefix", "trendruum", "ptt", "hb"):
        if gen(st.button, "📤 Toplu Ürün Oluştur / Gönder", key=f"b4_{pid}"):
            st.session_state[k] = "toplu"
    if bagli and pid in GUNCELLEYICI:
        y_liste = pazar_yetim_barkodlar(ayarlar, pid)
        if y_liste:
            st.warning(f"Tedarikçi listesinde artık olmayan {len(y_liste):,} ürün {PAZAR_AD.get(pid, pid)}'da eski stokla "
                       "satışta kalmış olabilir.")
            with st.expander("Bu ürünlerin barkodları (kontrol edin)"):
                st.dataframe(pd.DataFrame({"Barkod": y_liste[:500]}), hide_index=True)
            y_onay = st.checkbox("Bu ürünlerin tedarikçide artık olmadığını kontrol ettim", key=f"yetim_onay_{pid}")
            if gen(st.button, f"🧹 Bu {len(y_liste):,} ürünün stoğunu {PAZAR_AD.get(pid, pid)}'da 0'la",
                   key=f"yetim_{pid}", disabled=not y_onay):
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
            st.caption("Not: Veritabanındaki stoklar da 0'lanır; bir sonraki tedarikçi senkronizasyonunda tedarikçi stoğuna "
                       "göre yeniden hesaplanır.")
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
    if pid == "idefix" and bagli:
        with st.expander("📋 İdefix gönderim sonucunu sorgula (batchRequestId)", expanded=True):
            st.caption("İdefix ürün oluşturmayı hemen yapmaz; ürün önce havuza alınır. Neden görünmediğini bu sonuç söyler.")
            kayitli = list(reversed(takip_oku("idefix_takip", ayarlar)))
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
                    st.write(", ".join(f"{k_}: {n}" for k_, n in oz["sayim"].items()))
                if oz["satirlar"]:
                    st.dataframe(pd.DataFrame(oz["satirlar"]).drop(columns=["_durum"]), hide_index=True)
                    bekleyen = [r["Barkod"] for r in oz["satirlar"] if r["_durum"] == "waiting_vendor_approve" and r["Barkod"]]
                    if bekleyen:
                        st.warning(f"{len(bekleyen)} ürün İdefix kataloğunda zaten var ve onayınızı bekliyor. Onaylamadan "
                                   "önce eşleşen ürünün doğru olduğunu İdefix panelinden kontrol edin.")
                        onay_a = st.checkbox("Eşleşmeleri kontrol ettim, bu ürünleri onaylıyorum", key="idefix_onay_cb")
                        if gen(st.button, f"✅ Bekleyen {len(bekleyen)} ürünü onayla", key="idefix_onay_btn", disabled=not onay_a):
                            ok_k, hata_k, lg = idefix_onayla(ayarlar, bekleyen)
                            log_yaz("İdefix", "OK" if not hata_k else "KISMİ", f"Ürün onayı: {len(ok_k)} onaylandı, {len(hata_k)} hata.")
                            (st.success if not hata_k else st.warning)(f"{len(ok_k)} ürün onaylandı, {len(hata_k)} hata. " + " ".join(lg[-2:]))
                with st.expander("Ham yanıt"):
                    st.code(ham)
    if pid == "ptt" and bagli:
        with st.expander("📋 PTT gönderim sonucunu sorgula (trackingId)"):
            kayitli = list(takip_oku("ptt_takip", ayarlar))
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
    st.caption("Güvenlik için anahtarları ortam değişkeni (örn. N11_KEY) veya Streamlit secrets ile de verebilirsiniz; "
               "bunlar dosyadakinden önceliklidir.")
    if gen(st.button, "🔌 Bağlantı Testi", key=f"bt_{pid}"):
        ok_, msg_ = baglanti_testi(ayarlar, pid)
        (st.success if ok_ else st.error)(msg_)
    st.divider()
    bayrak = OTO_BAYRAK[pid]
    oto = st.toggle(f"🤖 {p['ad']} stok/fiyatı her senkronizasyondan sonra otomatik güncelle",
                    value=bool(ayarlar.get(bayrak)), key=f"oto_{pid}")
    if oto != bool(ayarlar.get(bayrak)):
        ayarlar[bayrak] = oto
        ayar_yaz(ayarlar)
    if not oto:
        st.warning("Bu seçenek kapalıyken stok değişiklikleri bu pazara OTOMATİK gitmez; tükenen ürünler satışta kalır. "
                   "Canlı satış yapıyorsanız açık tutun.")
    st.divider()
    pazar_ayar_formu(pid)
    if pid == "ptt":
        with st.expander("🔎 PTT kategori ID bulucu (kategori adından ID bul)"):
            ptt_kategori_bulucu()
    if pid == "idefix":
        with st.expander("🏷️ İdefix marka ID bulucu (marka adından ID bul)"):
            idefix_marka_bulucu()
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
    stok_harita = {}
    try:
        _u = urunleri_oku()
        if not _u.empty:
            kol = "stok_ham" if "stok_ham" in _u.columns else "stok"
            stok_harita = _u.groupby("barkod")[kol].max().to_dict()  # ham tedarikçi stoğu (eşik/pay uygulanmamış)
    except Exception:
        pass
    onek = str(pa_al(ayarlar, "hb").get("sku_prefix", "") or "") if pid == "hb" else ""
    yok = "(bilgi yok)"
    for o in liste:
        with st.container(border=True):
            baslik_no = o.get("no") or o.get("paket_no") or "-"
            st.markdown(f"### Sipariş {baslik_no} · {o['tarih']}")
            tutar_m = para_metni(o.get("tutar"))
            st.markdown(f"**Durum:** {DURUM_ETIKET.get(o['durum'], o['durum'])} | **Alıcı:** {o['alici'] or yok} | **Tutar:** {tutar_m}")
            adres_m = o.get("adres") or yok
            tel_m = f" · Tel: {o['telefon']}" if o.get("telefon") else ""
            st.markdown(f"**Adres:** {adres_m}{tel_m}")
            if o.get("paket_no"):
                st.caption(f"Paket no: {o['paket_no']}")
            if o.get("kargo") or o.get("barkod"):
                st.markdown(f"**Kargo:** {o.get('kargo', '')} {o.get('barkod', '')}")
            for u in o.get("urunler", []):
                sku = str(u.get("sku") or "")
                ham_sku = sku[len(onek):] if (onek and sku.startswith(onek)) else sku
                stok_n = stok_harita.get(ham_sku, stok_harita.get(sku))
                adet = max(_i(u.get("adet"), 1), 1)
                if stok_n is None:
                    stok_m = "tedarikçi stoğu: bulunamadı"
                elif int(stok_n) < adet:
                    stok_m = f"⚠️ **tedarikçi stoğu: {int(stok_n)} (YETERSİZ, hemen kontrol edin)**"
                else:
                    stok_m = f"tedarikçi stoğu: {int(stok_n)}"
                fiyat_m = f" · {para_metni(u['fiyat'])}" if u.get("fiyat") else ""
                st.markdown(f"- {u['ad']} — `{sku}` × {u['adet']}{fiyat_m} · {stok_m}")
            if o.get("ham"):
                with st.expander("Ham veri (kontrol için)"):
                    st.json(o["ham"])


# --------------------------------------------------------------------------
# Ürünler, anasayfa, ana akış
# --------------------------------------------------------------------------
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
    gorunum = d2.radio("Görünüm", ["Tablo (kaydırmalı)", "Kart (küçük görsel)"], horizontal=True)
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
                    sayi_ = tedarikci_senkron(secili, ayarlar["tedarikciler"][secili], _i(ayarlar.get("kritik_esik")), stok_ust_degeri(ayarlar))
                    log_yaz(secili, "OK", f"{sayi_} ürün güncellendi")
                    st.session_state["urun_senk_sonuc"] = [(secili, True, f"{sayi_} ürün")]
                except Exception as e:
                    st.session_state["urun_senk_sonuc"] = [(secili, False, str(e))]
            else:
                st.session_state["urun_senk_sonuc"] = tumunu_senkronla(oto=False)
        st.rerun()
    if gorunum.startswith("Tablo"):
        v = pd.DataFrame({
            "Görsel": f["gorsel"].where(f["gorsel"].astype(str).str.startswith("http"), None),
            "Ürün": f["urun_adi"], "Barkod": f["barkod"],
            "Pazar barkodu": [(b if b and b != k else "") for k, b in zip(f["barkod"].astype(str), f["barkod"].astype(str).map(lambda k: sabit_barkod(k, True) or ""))],
            "Tedarikçi": f["tedarikci"], "Stok": f["stok"],
            "Alış": f["alis_fiyati"].map(_f).round(2), "Satış": f["satis_fiyati"].map(_f).round(2),
            "Kilit": [("🔒" if b in kilit else "") + ("💲" if b in fiyat_kilit else "") for b in f["barkod"].astype(str)],
        })
        ayar_kol = {
            "Görsel": st.column_config.ImageColumn("Görsel", width="small"),
            "Ürün": st.column_config.TextColumn("Ürün", width="large"),
            "Alış": st.column_config.NumberColumn("Alış", format="%.2f ₺"),
            "Satış": st.column_config.NumberColumn("Satış", format="%.2f ₺"),
        }
        secilen = []
        try:
            olay = st.dataframe(v, hide_index=True, height=620, column_config=ayar_kol,
                                on_select="rerun", selection_mode="multi-row", key="urun_tablo")
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
                    st.session_state["urun_sifir_sonuc"] = [
                        f"{n} ürünün kilidi kaldırıldı. Stok, bir sonraki tedarikçi çekişinde geri gelir ('Stokları tedarikçiden çek')."]
                    st.rerun()
        if sec_barkod:
            with st.container(border=True):
                st.markdown("**💲 Satış fiyatını değiştir**")
                ilk = f[f["barkod"].astype(str).isin(sec_barkod)]
                mevcut_fiyat = float(_f(ilk["satis_fiyati"].iloc[0])) if len(ilk) else 0.0
                alis_en_yuksek = float(ilk["alis_fiyati"].map(_f).max()) if len(ilk) else 0.0
                yeni_fiyat = st.number_input("Yeni satış fiyatı (₺) — pazar yerlerine bu fiyat gider", min_value=0.0,
                                             value=round(mevcut_fiyat, 2), step=1.0, format="%.2f", key="fiyat_yeni")
                st.caption(f"Seçili {len(sec_barkod)} ürün · en yüksek alış fiyatı {alis_en_yuksek:.2f} ₺. Bu fiyat marj, "
                           "kargo ve komisyon hesabından sonra kesin fiyattır; tedarikçi senkronunda da korunur.")
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
                    st.session_state["urun_sifir_sonuc"] = [
                        f"{n} ürünün elle fiyatı kaldırıldı. Otomatik fiyat, bir sonraki tedarikçi çekişinde ('Stokları tedarikçiden çek') geri gelir."]
                    st.rerun()
    else:
        st.caption("Küçük görselli kart görünümü; daha fazlası için aşağıdaki düğmeyi kullanın.")
        sayi_k = st.session_state.setdefault("urun_kart_sayi", 24)
        for _, row in f.head(sayi_k).iterrows():
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
                y.caption(f"Barkod `{row.get('barkod', '-')}` · {row.get('tedarikci', '-')} · Stok **{row.get('stok', 0)}** · "
                          f"Alış {alis:.2f} ₺ · Satış {satis:.2f} ₺")
        if len(f) > sayi_k and gen(st.button, f"⬇️ Daha fazla göster ({min(sayi_k, len(f))}/{len(f)})", key="urun_daha_fazla"):
            st.session_state["urun_kart_sayi"] = sayi_k + 48
            st.rerun()
    if kilit:
        with st.expander(f"🔒 Elle sıfırlanmış ürünler ({len(kilit)})"):
            kd = pd.DataFrame({"Barkod": sorted(kilit), "Kilit zamanı": [ayarlar["stok_sifir"][b] for b in sorted(kilit)]})
            st.dataframe(kd, hide_index=True)


def anasayfa():
    st.title("🦅 ŞahEntegre - Mağaza ve Pazar Yeri Özeti")
    df = urunleri_oku()
    esik = _i(ayarlar.get("kritik_esik")) or 3
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Toplam Ürün", f"{len(df):,}")
    c2.metric("Stokta Olanlar", f"{int((df['stok'] > 0).sum()):,}" if not df.empty else "0")
    c3.metric(f"Kritik Stok (≤{esik})", f"{int(df['stok'].between(1, esik).sum()):,}" if not df.empty else "0")
    c4.metric("Tedarikçi", len(ayarlar["tedarikciler"]))
    dk, _ = senkron_gecikme_dk(ayarlar)
    if dk is not None:
        st.caption(f"Son başarılı stok senkronu: {int(dk)} dakika önce.")
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
                oto_acik = bool(ayarlar.get(OTO_BAYRAK[pid_]))
                oto_m = "🤖 Oto stok güncelleme AÇIK" if oto_acik else "⏸️ Oto stok güncelleme KAPALI"
                st.markdown(
                    f'<div style="background:{renk}; border-radius:14px; padding:14px; border-left:6px solid {p_["renk"]}; margin-bottom:10px;">'
                    f'<h4 style="margin:0; color:#1e293b; font-size:16px;">{p_["ikon"]} {p_["ad"]}</h4>'
                    f'<p style="margin:6px 0 0 0; font-weight:600; color:#475569; font-size:13px;">{durum} · {oto_m}</p></div>',
                    unsafe_allow_html=True,
                )
                if gen(st.button, "Yönet / İşlemler", key=f"kutu_git_{pid_}"):
                    git_pazar(pid_, "islemler")
                    st.rerun()
    st.caption("Not: 'Anahtarlar tanımlı' yalnızca bilgilerin girildiğini gösterir; gerçek doğrulama için Genel Ayarlar'daki "
               "Bağlantı Testi'ni kullanın.")


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
        gen(st.sidebar.button, etk, key=f"nav_{kid}", type="primary" if st.session_state["sayfa"] == kid else "secondary",
            on_click=git, args=(kid,))
    for pid, p in PAZAR.items():
        acik = st.session_state["acik_pazar"] == pid
        ok_ikon = "▾" if acik else "▸"
        gen(st.sidebar.button, f"{p['ikon']} {p['ad']} {ok_ikon}", key=f"navp_{pid}", on_click=ac_kapa, args=(pid,))
        if acik:
            for alt, etk, ik in ALT:
                sid = f"{pid}:{alt}"
                gen(st.sidebar.button, f"{ik} {p['ad']} {etk}", key=f"sub_{pid}_{alt}",
                    type="primary" if st.session_state["sayfa"] == sid else "secondary", on_click=git, args=(sid,))
    gen(st.sidebar.button, "⚙️ Ayarlar", key="nav_Ayarlar",
        type="primary" if st.session_state["sayfa"] == "Ayarlar" else "secondary", on_click=git, args=("Ayarlar",))
    acil_kontrol_kenar()
    guvenlik_paneli()
    sayfa = st.session_state["sayfa"]
    if sayfa == "Anasayfa":
        anasayfa()
    elif sayfa == "Bildirim":
        st.title("🔔 Bildirimler")
        if gen(st.button, "🔍 Siparişlerde stok kontrolünü şimdi çalıştır", key="sip_kontrol_simdi"):
            with st.spinner("Siparişler kontrol ediliyor..."):
                uyarilar = siparis_stok_kontrol(ayarlar)
            if uyarilar:
                for u in uyarilar:
                    st.error(u)
            else:
                st.success("Yeni siparişlerde stok sorunu bulunmadı.")
        gunluk_sayfasi()
    elif sayfa == "Urunler":
        urunler_sayfasi()
    elif sayfa == "Kritik":
        st.title("🔄 Oto Kritik Stok")
        st.caption("Bu eşik, her tedarikçi senkronizasyonunda uygulanır: stok eşiğin altındaysa 0 gönderilir. "
                   "Eşiği değiştirince stoklar, XML indirmeden ham tedarikçi stoğundan hemen yeniden hesaplanır.")
        esik = st.number_input("Kritik stok eşiği:", 0, 50, _i(ayarlar.get("kritik_esik")))
        if int(esik) != _i(ayarlar.get("kritik_esik")):
            ayarlar["kritik_esik"] = int(esik)
            ayar_yaz(ayarlar)
            stoklari_yeniden_hesapla(ayarlar)
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
