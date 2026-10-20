import json
import re
import uuid
import requests
import streamlit as st

# ==========================================
# 1. HEPSİBURADA (HB KATALOG) MODÜLÜ
# ==========================================

MPOP = "https://mpop.hepsiburada.com"
TEMEL = {"merchantsku", "varyantgroupid", "barcode", "urunadi", "urunaciklamasi", "marka",
         "garantisuresi", "kg", "tax_vat_rate", "price", "stock"}


def _h(h):
    return {k: v for k, v in h.items() if k.lower() != "content-type"}


def kategoriler(h):
    sonuc, sayfa = [], 0
    while sayfa < 80:
        r = requests.get(f"{MPOP}/product/api/categories/get-all-categories", headers=_h(h), timeout=90,
                         params={"leaf": "true", "status": "ACTIVE", "available": "true",
                                 "page": sayfa, "size": 1000, "version": 1})
        r.raise_for_status()
        j = r.json()
        veri = j.get("data") if isinstance(j, dict) else j
        if not veri:
            break
        for c in veri:
            cid = c.get("categoryId") or c.get("id")
            ad = str(c.get("displayName") or c.get("name") or "")
            yol = [str(x) for x in (c.get("paths") or [])]
            if ad and (not yol or yol[-1] != ad):
                yol.append(ad)
            if cid:
                sonuc.append({"id": cid, "yol": " > ".join(yol)})
        if not isinstance(j, dict) or sayfa + 1 >= int(j.get("totalPages", 1) or 1):
            break
        sayfa += 1
    return sonuc


def degerler(h, cid, aid):
    r = requests.get(f"{MPOP}/product/api/categories/{cid}/attribute/{aid}/values", headers=_h(h), timeout=60,
                     params={"page": 0, "size": 1000, "version": 1})
    r.raise_for_status()
    return [str(x.get("value") or x.get("name")) for x in (r.json().get("data") or []) if isinstance(x, dict)]


def _n(t):
    t = str(t)
    for x, y in (("İ", "i"), ("I", "ı"), ("ı", "i"), ("ç", "c"), ("Ç", "c"), ("ş", "s"), ("Ş", "s"),
                 ("ğ", "g"), ("Ğ", "g"), ("ö", "o"), ("Ö", "o"), ("ü", "u"), ("Ü", "u")):
        t = t.replace(x, y)
    return t.lower()


def ara_kat(kats, q):
    k = _n(q).split()
    if not k:
        return [], ""
    ad = [(c, _n(c["yol"])) for c in kats]
    bul = [c for c, y in ad if all(w in y for w in k)]
    if bul:
        return bul[:50], ""
    bul = [c for c, y in ad if any(w in y for w in k if len(w) >= 3)]
    if bul:
        return bul[:50], "Tam eşleşme yok, benzer sonuçlar:"
    p = k[0][:3]
    return [c for c, y in ad if p in y][:50], f"'{q}' bulunamadı, '{p}' içerenler:"


def ozellikler(h, cid):
    r = requests.get(f"{MPOP}/product/api/categories/{cid}/attributes", headers=_h(h), timeout=60)
    r.raise_for_status()
    d = r.json().get("data") or {}
    tum = (d.get("baseAttributes") or []) + (d.get("attributes") or []) + (d.get("variantAttributes") or [])
    zor = []
    for a in tum:
        aid = str(a.get("id", ""))
        if not a.get("mandatory") or aid.lower() in TEMEL or re.fullmatch(r"image\d+", aid.lower()):
            continue
        if "enum" in str(a.get("type", "")).lower():
            try:
                a["_v"] = degerler(h, cid, aid)
            except Exception:
                a["_v"] = []
        zor.append(a)
    return zor, d


def gecerli_barkod(kod):
    return kod if kod.isdigit() and 8 <= len(kod) <= 14 else None


def _on(df, n):
    return df["kategori"].astype(str).map(lambda x: " >>> ".join(p.strip() for p in x.split(">>>")[:n]))


def _bul(esle, kategori):
    p = [x.strip() for x in str(kategori).split(">>>")]
    for n in range(len(p), 0, -1):
        k = " >>> ".join(p[:n])
        if k in esle:
            return esle[k]
    return None


def urun_listesi(df, pa, merchant, sadece=False):
    pre = pa.get("sku_prefix", "")
    esle = pa.get("esle") or {}
    liste, atlanan = [], 0
    for _, r in df.iterrows():
        gorsel, kod = str(r["gorsel"]).strip(), str(r["barkod"]).strip()
        if not gorsel.startswith("https") or r["satis_fiyati"] <= 0 or not kod:
            atlanan += 1
            continue
        e = _bul(esle, r.get("kategori", ""))
        if e:
            cid, ek = e["id"], e.get("oz") or {}
        elif pa.get("kat_id") and not sadece:
            cid, ek = pa["kat_id"], pa.get("ozellikler") or {}
        else:
            atlanan += 1
            continue
        ad = str(r["urun_adi"]).strip()
        a = {"merchantSku": pre + kod, "VaryantGroupID": pre + kod, "UrunAdi": ad[:255], "UrunAciklamasi": ad,
             "Marka": pa.get("marka", ""), "GarantiSuresi": str(int(pa.get("garanti", 24))),
             "kg": str(pa.get("kg", "1")), "tax_vat_rate": str(int(pa.get("kdv", 20))),
             "price": f"{float(r['satis_fiyati']):.2f}".replace(".", ","),
             "stock": str(int(max(r["stok"], 0))), "Image1": gorsel}
        a["Barcode"] = kod
        a.update(ek)
        liste.append({"categoryId": int(cid), "merchant": merchant, "attributes": a})
    return liste, atlanan


def gonder(h, liste, ilerleme=None, paket=100):
    toplam = max(1, (len(liste) + paket - 1) // paket)
    ok, idler, loglar = 0, [], []
    for i in range(0, len(liste), paket):
        no, grup = i // paket + 1, liste[i:i + paket]
        try:
            icerik = json.dumps(grup, ensure_ascii=False).encode("utf-8")
            for alan in ("integrationFile", "file", "files"):
                r = requests.post(f"{MPOP}/product/api/products/import", headers=_h(h), timeout=120,
                                  files={alan: ("urunler.json", icerik, "application/json")})
                try:
                    kod = (r.json() or {}).get("code")
                except Exception:
                    kod = None
                if kod != 3003:
                    break
        except Exception as e:
            loglar.append(f"⚠️ Paket {no}: {e}")
            continue
        if r.status_code in (200, 201, 202):
            try:
                tid = ((r.json() or {}).get("data") or {}).get("trackingId")
            except Exception:
                tid = None
            if tid:
                ok += 1
                idler.append(tid)
                loglar.append(f"✅ Paket {no}: {len(grup)} ürün gönderildi (takip: {tid}, alan: {alan})")
            else:
                loglar.append(f"⚠️ Paket {no}: HTTP {r.status_code} ama takip numarası yok (alan: {alan}): {r.text[:400]}")
        else:
            loglar.append(f"❌ Paket {no}: HTTP {r.status_code} {r.text[:500]}")
        if ilerleme:
            ilerleme(min(no / toplam, 1.0), loglar)
    return ok, toplam, idler, loglar


def durum(h, tid):
    r = requests.get(f"{MPOP}/product/api/products/status/{tid}", headers=_h(h), timeout=60,
                     params={"version": 1, "page": 0, "size": 100})
    return r.status_code, r.text


def ozet(metin):
    try:
        j = json.loads(metin)
        d = j.get("data")
        assert isinstance(d, list)
    except Exception:
        return metin[:800]
    sayim, nedenler = {}, {}
    for x in d:
        k = str(x.get("importStatus") or x.get("productStatus") or "?")
        sayim[k] = sayim.get(k, 0) + 1
        r = x.get("rejectReasonsMessages") or x.get("validationResults") or x.get("importMessages")
        if r:
            t = json.dumps(r, ensure_ascii=False)[:160]
            nedenler[t] = nedenler.get(t, 0) + 1
    satir = [f"Toplam: {j.get('totalElements', len(d))} kayıt (bu sayfada {len(d)})",
             "Durumlar: " + (", ".join(f"{k}: {v}" for k, v in sayim.items()) or "—")]
    satir += [f"{n}× {t}" for t, n in sorted(nedenler.items(), key=lambda a: -a[1])[:6]]
    return "\n".join(satir)


def goster(h, tid):
    try:
        kod, metin = durum(h, tid)
        st.caption(f"{tid} · HTTP {kod}")
        st.code(ozet(metin))
        with st.expander("Ham yanıt"):
            st.code(metin[:1800])
    except Exception as e:
        st.error(f"{tid}: {e}")


def panel_hb(g):
    ayarlar, kaydet = g["ayarlar"], g["ayar_yaz"]
    h, merchant = g["hb_header"](ayarlar), g["kimlik"](ayarlar, "hb_merchant_id")
    kayit = g["_kayit"]().setdefault("hbk", [])
    pa = ayarlar.setdefault("pazar_ayarlari", {}).setdefault("hb", {})
    st.caption("✅ hb_katalog SÜRÜM 10 · Hepsiburada'da YENİ ürün oluşturur, ürünler katalog onayına gider. "
               "Önce tek ürünle deneyin, sonra 'durumunu sorgula' ile hata nedenine bakın.")

    with st.expander("⚙️ Kategori / marka / zorunlu özellikler", expanded=not pa.get("kat_id")):
        st.caption(f"Kategori: {pa.get('kat_id') or '—'} · Marka: {pa.get('marka') or '—'} · "
                   f"Özellik: {len(pa.get('ozellikler') or {})}")
        if st.button("📥 Kategorileri yükle", key="hbk_kat_btn"):
            try:
                st.session_state["hbk_kat"] = kategoriler(h)
                st.success(f"{len(st.session_state['hbk_kat'])} kategori yüklendi.")
            except Exception as e:
                st.error(f"Hata: {e}")
        kats = st.session_state.get("hbk_kat", [])
        if kats:
            q = st.text_input("Kategori ara (yazıp Enter'a basın)", key="hbk_ara")
            if q.strip():
                bul, not_ = ara_kat(kats, q)
                if not bul:
                    st.warning("Sonuç yok. Daha kısa bir kelime deneyin.")
                else:
                    if not_:
                        st.info(not_)
                    st.caption(f"{len(bul)} sonuç")
                    k = st.selectbox("Sonuçlar", bul, format_func=lambda x: x["yol"], key="hbk_sec")
                    if st.button("Bu kategoriyi kullan", key="hbk_kullan"):
                        pa["kat_id"], pa["ozellikler"] = k["id"], {}
                        st.session_state.pop("hbk_oz", None)
                        kaydet(ayarlar)
                        st.rerun()
        st.session_state.setdefault("hbk_marka", pa.get("marka", ""))
        marka = st.text_input("Marka adı (Hepsiburada'daki yazılışıyla)", key="hbk_marka").strip()
        c1, c2, c3 = st.columns(3)
        kdv = c1.selectbox("KDV %", [0, 1, 10, 20], index=3, key="hbk_kdv")
        garanti = c2.number_input("Garanti (ay)", 0, 120, int(pa.get("garanti", 24)), key="hbk_gar")
        kg = c3.text_input("Ağırlık (kg)", value=str(pa.get("kg", "1")), key="hbk_kg").strip() or "1"
        yeni = (marka, int(kdv), int(garanti), kg)
        if yeni != (pa.get("marka", ""), pa.get("kdv", 20), pa.get("garanti", 24), pa.get("kg", "1")):
            pa["marka"], pa["kdv"], pa["garanti"], pa["kg"] = yeni
            kaydet(ayarlar)
        if pa.get("kat_id") and st.button("📋 Zorunlu özellikleri yükle", key="hbk_oz_btn"):
            try:
                st.session_state["hbk_oz"] = ozellikler(h, pa["kat_id"])
            except Exception as e:
                st.error(f"Hata: {e}")
        oz = st.session_state.get("hbk_oz")
        if oz:
            zor, ham = oz
            secim, eksik = {}, 0
            for a in zor:
                aid, ad = str(a.get("id")), a.get("name", a.get("id"))
                if a.get("_v"):
                    secim[aid] = st.selectbox(f"{ad} (zorunlu)", a["_v"], key=f"hbk_a_{aid}")
                else:
                    v = st.text_input(f"{ad} (zorunlu)", key=f"hbk_a_{aid}").strip()
                    secim[aid] = v
                    eksik += 0 if v else 1
            if not zor:
                st.info("Bu kategoride ek zorunlu özellik görünmüyor.")
            if st.button("Özellikleri kaydet", key="hbk_oz_kaydet", disabled=bool(eksik)):
                pa["ozellikler"] = secim
                kaydet(ayarlar)
                st.success("Özellikler kaydedildi.")
            if eksik:
                st.warning(f"{eksik} zorunlu özellik boş.")
            st.caption("Seçtiğiniz özellikler bu kategorideki TÜM ürünlere uygulanır.")
            with st.expander("Ham yanıt (hata ayıklama)"):
                ozet = [f"{a.get('id')} | {a.get('name')} | zorunlu={a.get('mandatory')} | {a.get('type')}"
                        for a in (ham.get("attributes") or []) + (ham.get("variantAttributes") or [])]
                st.code("\n".join(ozet[:40]) or "Kategoriye özel özellik listesi boş.")

    esle = pa.setdefault("esle", {})
    with st.expander(f"📂 Kategori eşleme ({len(esle)} eşleşti)"):
        st.caption("Her tedarikçi kategorisini bir kez Hepsiburada kategorisine eşleyin. 'Tümü' gönderimi her ürünü kendi kategorisine yollar. Geniş gruplarda (örn. ELEKTRONİK) düzeyi 2 ya da 3 yapıp alt kategorileri ayrı eşleyin; en özel eşleme geçerli olur.")
        duz = st.selectbox("Kategori düzeyi (1 = ana kategori, 2 = alt kategori, ...)", [1, 2, 3, 4], key="hbk_e_duz")
        sayim = _on(g["urunleri_oku"](), duz).value_counts()
        etk = {f"{'✅ ' if k in esle else ''}{k} ({n})": k for k, n in sayim.items()}
        kats2 = st.session_state.get("hbk_kat", [])
        if not etk:
            st.info("Önce tedarikçi ürünlerini senkronlayın.")
        elif not kats2:
            st.info("Önce yukarıdaki bölümden '📥 Kategorileri yükle'ye basın.")
        else:
            ted = etk[st.selectbox("Tedarikçi kategorisi", list(etk), key=f"hbk_e_ted_{duz}")]
            if ted in esle:
                st.caption(f"Şu an: {esle[ted]['yol']}")
            q2 = st.text_input("Hepsiburada kategorisi ara (Enter)", value=ted.split(">>>")[-1].strip(), key=f"hbk_e_ara_{ted}")
            bul2, not2 = ara_kat(kats2, q2) if q2.strip() else ([], "")
            if not bul2:
                st.warning("Sonuç yok, farklı bir kelime deneyin.")
            else:
                if not2:
                    st.info(not2)
                k2 = st.selectbox("Sonuçlar", bul2, format_func=lambda x: x["yol"], key=f"hbk_e_sec_{ted}")
                if st.button("📋 Zorunlu özellikleri yükle", key="hbk_e_oz_btn"):
                    try:
                        st.session_state["hbk_e_oz"] = (k2["id"], ozellikler(h, k2["id"])[0])
                    except Exception as e:
                        st.error(f"Hata: {e}")
                oz2 = st.session_state.get("hbk_e_oz")
                yuklendi = bool(oz2 and oz2[0] == k2["id"])
                secim2, eksik2 = {}, 0
                if yuklendi:
                    for a in oz2[1]:
                        aid, ad = str(a.get("id")), a.get("name", a.get("id"))
                        if a.get("_v"):
                            secim2[aid] = st.selectbox(f"{ad} (zorunlu)", a["_v"], key=f"hbk_e_a_{aid}")
                        else:
                            v = st.text_input(f"{ad} (zorunlu)", key=f"hbk_e_a_{aid}").strip()
                            secim2[aid] = v
                            eksik2 += 0 if v else 1
                    if not oz2[1]:
                        st.info("Bu kategoride ek zorunlu özellik yok.")
                else:
                    st.caption("Kaydetmeden önce zorunlu özellikleri yükleyin.")
                if st.button("💾 Eşlemeyi kaydet", key="hbk_e_kaydet", disabled=bool(eksik2) or not yuklendi):
                    esle[ted] = {"id": k2["id"], "yol": k2["yol"], "oz": secim2}
                    kaydet(ayarlar)
                    st.success("Eşleme kaydedildi.")
                    st.rerun()
            if ted in esle and st.button("🗑️ Bu eşlemeyi sil", key="hbk_e_sil"):
                esle.pop(ted)
                kaydet(ayarlar)
                st.rerun()

    miktar = st.selectbox("Gönderilecek ürün", ["Tek ürün (test)", "İlk 100", "İlk 500", "Tümü"], key="hbk_miktar")
    tek_stok = st.checkbox("Sadece stokta olanları gönder", value=True, key="hbk_stok")
    kat = g["kategori_sec"]("hbk_tkat")
    ara = st.text_input("Ürün adında/barkodda ara (isteğe bağlı)", key="hbk_urun_ara").strip().lower()
    sadece = st.checkbox("Kategorisi eşlenmemiş ürünleri atla", value=bool(esle), key="hbk_sadece")
    if st.button("📤 Hepsiburada'ya Ürün Oluştur", type="primary", key="hbk_gonder"):
        eksik = [ad for ad, v in (("Kategori (ya da kategori eşleme)", pa.get("kat_id") or esle), ("Marka", pa.get("marka"))) if not v]
        if eksik:
            st.error("Eksik: " + ", ".join(eksik) + ". Yukarıdaki ayarlardan doldurun.")
            return
        df = g["urunleri_oku"]()
        if tek_stok:
            df = df[df["stok"] > 0]
        if kat:
            df = df[g["ana_kat"](df) == kat]
        if ara:
            df = df[df["urun_adi"].str.lower().str.contains(ara, regex=False) | df["barkod"].str.lower().str.contains(ara, regex=False)]
        df = df.head({"Tek ürün (test)": 1, "İlk 100": 100, "İlk 500": 500}.get(miktar, len(df)))
        df = g["fiyat_artis_uygula"](ayarlar, "hb", df)
        liste, atlanan = urun_listesi(df, pa, merchant, sadece)
        if atlanan:
            st.info(f"{atlanan} ürün atlandı (https görsel yok, fiyat 0 ya da kategorisi eşlenmemiş).")
        if not liste:
            st.warning("Gönderilecek geçerli ürün kalmadı.")
            return
        with st.expander("Gönderilen ilk ürün (kontrol)"):
            st.code(json.dumps(liste[0], ensure_ascii=False, indent=1)[:1500])
        bar, kutu = st.progress(0), st.empty()
        ok, top, idler, loglar = gonder(h, liste, lambda p, l: (bar.progress(p), kutu.code("\n".join(l[-10:]))))
        kayit.extend(idler)
        del kayit[:-20]
        g["log_yaz"]("Hepsiburada", "OK" if ok else "HATA", f"{ok}/{top} paket gönderildi. {len(liste)} ürün (katalog).")
        (st.success if ok else st.error)(f"{ok}/{top} paket kabul edildi. Sonucu aşağıdan sorgulayın.")
    if kayit and st.button("🔍 Son gönderimlerin durumunu sorgula", key="hbk_durum"):
        for tid in kayit[-3:]:
            goster(h, tid)
    tid_el = st.text_input("Takip numarasıyla sorgula (uygulama yeniden başladıysa)", key="hbk_tid").strip()
    if tid_el and st.button("🔍 Bu takip numarasını sorgula", key="hbk_tid_btn"):
        goster(h, tid_el)


# ==========================================
# 2. PTT AVM MODÜLÜ
# ==========================================

BASE_PTT = "https://integration-api.pttavm.com/api/v1"


def _h_ptt(key, token):
    return {"Api-Key": key, "Access-Token": token, "X-Correlation-Id": str(uuid.uuid4()),
            "Content-Type": "application/json"}


def _j_ptt(r):
    try:
        return r.json()
    except Exception:
        return {}


def test_ptt(key, token):
    if not (key and token):
        return False, "API Key ve Token boş olamaz."
    try:
        r = requests.get(f"{BASE_PTT}/categories/category-tree", headers=_h_ptt(key, token), timeout=90)
    except Exception as e:
        return False, f"Bağlantı kurulamadı: {e}"
    if r.status_code == 200 and _j_ptt(r).get("success", True):
        return True, "✅ PTT AVM girişi başarılı."
    return False, f"HTTP {r.status_code}: {r.text[:300]}"


def kategoriler_ptt(key, token):
    r = requests.get(f"{BASE_PTT}/categories/category-tree", headers=_h_ptt(key, token), timeout=120)
    r.raise_for_status()
    j = _j_ptt(r)
    agac = j.get("category_tree") if isinstance(j, dict) else None
    if not agac:
        raise RuntimeError(f"Kategori listesi boş: {str(j)[:300]}")
    sonuc = []

    def gez(liste, yol):
        for k in liste or []:
            y = yol + [str(k.get("name", ""))]
            if k.get("children"):
                gez(k["children"], y)
            elif k.get("id") is not None:
                sonuc.append({"id": k["id"], "yol": " > ".join(y)})

    gez(agac, [])
    return sonuc


def guncelle_ptt(g, ayarlar, df):
    key, token = g["kimlik"](ayarlar, "ptt_key"), g["kimlik"](ayarlar, "ptt_token")
    pa = (ayarlar.get("pazar_ayarlari") or {}).get("ptt") or {}
    kdv = int(pa.get("kdv", 20))
    kayit = g["_kayit"]().setdefault("ptt", [])
    items = [{"barcode": str(r["barkod"]).strip(), "quantity": int(min(max(r["stok"], 0), 9999)),
              "priceWithVAT": round(float(r["satis_fiyati"]), 2), "vatRate": kdv}
             for _, r in df.iterrows() if r["satis_fiyati"] > 0 and str(r["barkod"]).strip()]
    ok, log, ok_b, hata_b = 0, [], [], []
    for i in range(0, len(items), 1000):
        grup, no = items[i:i + 1000], i // 1000 + 1
        bk = [x["barcode"] for x in grup]
        try:
            r = requests.post(f"{BASE_PTT}/products/stock-prices", headers=_h_ptt(key, token), json={"items": grup}, timeout=120)
            j = _j_ptt(r)
        except Exception as e:
            hata_b += bk
            log.append(f"⚠️ Paket {no}: {e}")
            continue
        if r.status_code == 200 and j.get("success") and j.get("trackingId"):
            ok += len(grup)
            ok_b += bk
            kayit.append(j["trackingId"])
            del kayit[:-20]
            log.append(f"✅ Paket {no}: {len(grup)} kalem iletildi (takip: {j['trackingId']})")
        else:
            hata_b += bk
            log.append(f"❌ Paket {no}: HTTP {r.status_code} {r.text[:300]}")
    try:
        g["pazar_isaretle"]("ptt", ok_b, hata_b)
    except Exception:
        pass
    return ok, log


def urun_listesi_ptt(df, pa, sadece=False):
    esle = pa.get("esle") or {}
    kdv = int(pa.get("kdv", 20))
    liste, atlanan = [], 0
    for _, r in df.iterrows():
        gorsel, kod = str(r["gorsel"]).strip(), str(r["barkod"]).strip()
        if not gorsel.startswith("http") or r["satis_fiyati"] <= 0 or not kod:
            atlanan += 1
            continue
        e = _bul(esle, r.get("kategori", ""))
        if e:
            cid = e["id"]
        elif pa.get("kat_id") and not sadece:
            cid = pa["kat_id"]
        else:
            atlanan += 1
            continue
        ad = str(r["urun_adi"]).strip()
        it = {"categoryId": int(cid), "barcode": kod, "ean": kod, "name": ad[:200],
              "priceWithVat": round(float(r["satis_fiyati"]), 2), "vatRate": kdv,
              "shortDescription": ad[:250], "longDescription": ad,
              "quantity": int(min(max(r["stok"], 0), 9999)), "images": [{"url": gorsel}], "active": True}
        if pa.get("marka"):
            it["brand"] = pa["marka"]
        if str(pa.get("desi", "")).strip():
            it["desi"] = float(str(pa["desi"]).replace(",", "."))
        if str(pa.get("kargo_profil", "")).strip():
            it["cargoProfileId"] = int(pa["kargo_profil"])
        liste.append(it)
    return liste, atlanan


def gonder_ptt(key, token, liste, ilerleme=None, paket=500):
    toplam = max(1, (len(liste) + paket - 1) // paket)
    ok, idler, loglar = 0, [], []
    for i in range(0, len(liste), paket):
        no, grup = i // paket + 1, liste[i:i + paket]
        try:
            r = requests.post(f"{BASE_PTT}/products/upsert", headers=_h_ptt(key, token), json={"items": grup}, timeout=120)
            j = _j_ptt(r)
        except Exception as e:
            loglar.append(f"⚠️ Paket {no}: {e}")
            continue
        if r.status_code == 200 and j.get("success") and j.get("trackingId"):
            ok += 1
            idler.append(j["trackingId"])
            loglar.append(f"✅ Paket {no}: {len(grup)} ürün gönderildi (takip: {j['trackingId']})")
        else:
            loglar.append(f"❌ Paket {no}: HTTP {r.status_code} {r.text[:400]}")
        if ilerleme:
            ilerleme(min(no / toplam, 1.0), loglar)
    return ok, toplam, idler, loglar


def ozet_ptt(j):
    if not isinstance(j, dict):
        return str(j)[:600]
    a = j.get("productsSubTrackingResult") or {}
    satir = [f"Durum: {j.get('status')} · ilerleme: %{j.get('progress')}",
             f"Toplam: {a.get('countOfTotalProducts')} · Tamam: {a.get('countOfCompletedProducts')} · "
             f"İptal: {a.get('countOfCancelledProducts')} · Bekleyen: {a.get('countOfWaitingProducts')} · "
             f"İşlenen: {a.get('countOfInProgressProducts')}"]
    nedenler = {}
    for p in a.get("productBasedInfos") or []:
        fr = p.get("failureReasons") or []
        if fr or str(p.get("status")).lower() == "cancelled":
            t = " | ".join(map(str, fr)) or str(p.get("message"))
            nedenler.setdefault(t[:200], []).append(str(p.get("barcode")))
    for t, b in sorted(nedenler.items(), key=lambda a: -len(a[1]))[:6]:
        satir.append(f"{len(b)}× {t} (örnek: {b[0]})")
    return "\n".join(satir)


def goster_ptt(key, token, tid):
    try:
        r = requests.post(f"{BASE_PTT}/products/tracking-result/{tid}", headers=_h_ptt(key, token), data="{}", timeout=60)
        st.caption(f"{tid} · HTTP {r.status_code}")
        st.code(ozet_ptt(_j_ptt(r)) if r.status_code == 200 else r.text[:600])
        with st.expander("Ham yanıt"):
            st.code(r.text[:1800])
    except Exception as e:
        st.error(f"{tid}: {e}")


def panel_ptt(g):
    ayarlar, kaydet, kimlik = g["ayarlar"], g["ayar_yaz"], g["kimlik"]
    key, token = kimlik(ayarlar, "ptt_key"), kimlik(ayarlar, "ptt_token")
    kayit = g["_kayit"]().setdefault("ptt", [])
    pa = ayarlar.setdefault("pazar_ayarlari", {}).setdefault("ptt", {})
    esle = pa.setdefault("esle", {})
    st.caption("✅ pttavm SÜRÜM 1 · PTT AVM'de YENİ ürün oluşturur. Önce tek ürünle deneyin, sonra durumunu sorgulayın.")

    with st.expander("⚙️ Kategori / marka / ayarlar", expanded=not (pa.get("kat_id") or esle)):
        st.caption(f"Varsayılan kategori: {pa.get('kat_id') or '—'} · Marka: {pa.get('marka') or '—'}")
        if st.button("📥 Kategorileri yükle", key="ptt_kat_btn"):
            try:
                st.session_state["ptt_kat"] = kategoriler_ptt(key, token)
                st.success(f"{len(st.session_state['ptt_kat'])} kategori yüklendi.")
            except Exception as e:
                st.error(f"Hata: {e}")
        kats = st.session_state.get("ptt_kat", [])
        if kats:
            q = st.text_input("Kategori ara (yazıp Enter'a basın)", key="ptt_ara")
            if q.strip():
                bul, not_ = ara_kat(kats, q)
                if not bul:
                    st.warning("Sonuç yok. Daha kısa bir kelime deneyin.")
                else:
                    if not_:
                        st.info(not_)
                    k = st.selectbox("Sonuçlar", bul, format_func=lambda x: x["yol"], key="ptt_sec")
                    if st.button("Bu kategoriyi kullan", key="ptt_kullan"):
                        pa["kat_id"] = k["id"]
                        kaydet(ayarlar)
                        st.rerun()
        marka = st.text_input("Marka adı", value=pa.get("marka", ""), key="ptt_marka").strip()
        c1, c2, c3 = st.columns(3)
        kd = [0, 1, 10, 20]
        kdv = c1.selectbox("KDV %", kd, index=kd.index(int(pa.get("kdv", 20))) if int(pa.get("kdv", 20)) in kd else 3, key="ptt_kdv")
        desi = c2.text_input("Desi (isteğe bağlı)", value=str(pa.get("desi", "")), key="ptt_desi").strip()
        kp = c3.text_input("Kargo profil ID (isteğe bağlı)", value=str(pa.get("kargo_profil", "")), key="ptt_kp").strip()
        yeni = (marka, int(kdv), desi, kp)
        if yeni != (pa.get("marka", ""), pa.get("kdv", 20), pa.get("desi", ""), pa.get("kargo_profil", "")):
            pa["marka"], pa["kdv"], pa["desi"], pa["kargo_profil"] = yeni
            kaydet(ayarlar)

    with st.expander(f"📂 Kategori eşleme ({len(esle)} eşleşti)"):
        st.caption("Her tedarikçi kategorisini bir kez PTT AVM kategorisine eşleyin. Geniş gruplarda düzeyi 2 ya da 3 yapın; en özel eşleme geçerli olur.")
        duz = st.selectbox("Kategori düzeyi (1 = ana kategori, 2 = alt kategori, ...)", [1, 2, 3, 4], key="ptt_e_duz")
        sayim = _on(g["urunleri_oku"](), duz).value_counts()
        etk = {f"{'✅ ' if k in esle else ''}{k} ({n})": k for k, n in sayim.items()}
        kats2 = st.session_state.get("ptt_kat", [])
        if not etk:
            st.info("Önce tedarikçi ürünlerini senkronlayın.")
        elif not kats2:
            st.info("Önce yukarıdaki bölümden '📥 Kategorileri yükle'ye basın.")
        else:
            ted = etk[st.selectbox("Tedarikçi kategorisi", list(etk), key=f"ptt_e_ted_{duz}")]
            if ted in esle:
                st.caption(f"Şu an: {esle[ted]['yol']}")
            q2 = st.text_input("PTT AVM kategorisi ara (Enter)", value=ted.split(">>>")[-1].strip(), key=f"ptt_e_ara_{ted}")
            bul2, not2 = ara_kat(kats2, q2) if q2.strip() else ([], "")
            if not bul2:
                st.warning("Sonuç yok, farklı bir kelime deneyin.")
            else:
                if not2:
                    st.info(not2)
                k2 = st.selectbox("Sonuçlar", bul2, format_func=lambda x: x["yol"], key=f"ptt_e_sec_{ted}")
                if st.button("💾 Eşlemeyi kaydet", key="ptt_e_kaydet"):
                    esle[ted] = {"id": k2["id"], "yol": k2["yol"]}
                    kaydet(ayarlar)
                    st.rerun()
            if ted in esle and st.button("🗑️ Bu eşlemeyi sil", key="ptt_e_sil"):
                esle.pop(ted)
                kaydet(ayarlar)
                st.rerun()

    miktar = st.selectbox("Gönderilecek ürün", ["Tek ürün (test)", "İlk 100", "İlk 500", "Tümü"], key="ptt_miktar")
    tek_stok = st.checkbox("Sadece stokta olanları gönder", value=True, key="ptt_stok")
    kat = g["kategori_sec"]("ptt_tkat")
    ara = st.text_input("Ürün adında/barkodda ara (isteğe bağlı)", key="ptt_urun_ara").strip().lower()
    sadece = st.checkbox("Kategorisi eşlenmemiş ürünleri atla", value=bool(esle), key="ptt_sadece")
    if st.button("📤 PTT AVM'ye Ürün Oluştur", type="primary", key="ptt_gonder"):
        if not (pa.get("kat_id") or esle):
            st.error("Eksik: kategori (ya da kategori eşleme). Yukarıdaki ayarlardan doldurun.")
            return
        df = g["urunleri_oku"]()
        if tek_stok:
            df = df[df["stok"] > 0]
        if kat:
            df = df[g["ana_kat"](df) == kat]
        if ara:
            df = df[df["urun_adi"].str.lower().str.contains(ara, regex=False) | df["barkod"].str.lower().str.contains(ara, regex=False)]
        df = df.head({"Tek ürün (test)": 1, "İlk 100": 100, "İlk 500": 500}.get(miktar, len(df)))
        df = g["fiyat_artis_uygula"](ayarlar, "ptt", df)
        liste, atlanan = urun_listesi_ptt(df, pa, sadece)
        if atlanan:
            st.info(f"{atlanan} ürün atlandı (görsel yok, fiyat 0 ya da kategorisi eşlenmemiş).")
        if not liste:
            st.warning("Gönderilecek geçerli ürün kalmadı.")
            return
        with st.expander("Gönderilen ilk ürün (kontrol)"):
            st.code(json.dumps(liste[0], ensure_ascii=False, indent=1)[:1500])
        bar, kutu = st.progress(0), st.empty()
        ok, top, idler, loglar = gonder_ptt(key, token, liste, lambda p, l: (bar.progress(p), kutu.code("\n".join(l[-10:]))))
        kayit.extend(idler)
        del kayit[:-20]
        g["log_yaz"]("PTT AVM", "OK" if ok else "HATA", f"{ok}/{top} paket gönderildi. {len(liste)} ürün.")
        (st.success if ok else st.error)(f"{ok}/{top} paket kabul edildi. Sonucu aşağıdan sorgulayın.")
    if kayit and st.button("🔍 Son işlemlerin durumunu sorgula", key="ptt_durum"):
        for tid in kayit[-3:]:
            goster_ptt(key, token, tid)
    tid_el = st.text_input("Takip numarasıyla sorgula (uygulama yeniden başladıysa)", key="ptt_tid").strip()
    if tid_el and st.button("🔍 Bu takip numarasını sorgula", key="ptt_tid_btn"):
        goster_ptt(key, token, tid_el)
