import json
import re

import requests
import streamlit as st

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


def urun_listesi(df, pa, merchant):
  pre = pa.get("sku_prefix", "")
  ek = pa.get("ozellikler") or {}
  liste, atlanan = [], 0
  for _, r in df.iterrows():
    gorsel, kod = str(r["gorsel"]).strip(), str(r["barkod"]).strip()
    if not gorsel.startswith("https") or r["satis_fiyati"] <= 0 or not kod:
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
    liste.append({"categoryId": int(pa["kat_id"]), "merchant": merchant, "attributes": a})
  return liste, atlanan


def gonder(h, liste, ilerleme=None, paket=100):
  toplam = max(1, (len(liste) + paket - 1) // paket)
  ok, idler, loglar = 0, [], []
  for i in range(0, len(liste), paket):
    no, grup = i // paket + 1, liste[i:i + paket]
    try:
      r = requests.post(f"{MPOP}/product/api/products/import", headers=_h(h), timeout=120,
                        files={"integrationFile": ("urunler.json", json.dumps(grup, ensure_ascii=False).encode("utf-8"),
                                                   "application/json")})
    except Exception as e:
      loglar.append(f"⚠️ Paket {no}: {e}")
      continue
    if r.status_code in (200, 201, 202):
      try:
        tid = ((r.json() or {}).get("data") or {}).get("trackingId")
      except Exception:
        tid = None
      ok += 1
      if tid:
        idler.append(tid)
      loglar.append(f"✅ Paket {no}: {len(grup)} ürün gönderildi (takip: {tid})")
    else:
      loglar.append(f"❌ Paket {no}: HTTP {r.status_code} {r.text[:500]}")
    if ilerleme:
      ilerleme(min(no / toplam, 1.0), loglar)
  return ok, toplam, idler, loglar


def durum(h, tid):
  r = requests.get(f"{MPOP}/product/api/products/status/{tid}", headers=_h(h), timeout=60,
                   params={"version": 1, "page": 0, "size": 100})
  return r.status_code, r.text


def panel(g):
  ayarlar, kaydet = g["ayarlar"], g["ayar_yaz"]
  h, merchant = g["hb_header"](ayarlar), g["kimlik"](ayarlar, "hb_merchant_id")
  kayit = g["_kayit"]().setdefault("hbk", [])
  pa = ayarlar.setdefault("pazar_ayarlari", {}).setdefault("hb", {})
  st.caption("Hepsiburada'da YENİ ürün oluşturur. Ürünler Hepsiburada katalog onayına gider. "
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

  miktar = st.selectbox("Gönderilecek ürün", ["Tek ürün (test)", "İlk 100", "İlk 500", "Tümü"], key="hbk_miktar")
  tek_stok = st.checkbox("Sadece stokta olanları gönder", value=True, key="hbk_stok")
  kat = g["kategori_sec"]("hbk_tkat")
  ara = st.text_input("Ürün adında/barkodda ara (isteğe bağlı)", key="hbk_urun_ara").strip().lower()
  if st.button("📤 Hepsiburada'ya Ürün Oluştur", type="primary", key="hbk_gonder"):
    eksik = [ad for ad, v in (("Kategori", pa.get("kat_id")), ("Marka", pa.get("marka"))) if not v]
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
    liste, atlanan = urun_listesi(df, pa, merchant)
    if atlanan:
      st.info(f"{atlanan} ürün atlandı (https görsel yok ya da fiyat 0).")
    if not liste:
      st.warning("Gönderilecek geçerli ürün kalmadı.")
      return
    bar, kutu = st.progress(0), st.empty()
    ok, top, idler, loglar = gonder(h, liste, lambda p, l: (bar.progress(p), kutu.code("\n".join(l[-10:]))))
    kayit.extend(idler)
    del kayit[:-20]
    g["log_yaz"]("Hepsiburada", "OK" if ok else "HATA", f"{ok}/{top} paket gönderildi. {len(liste)} ürün (katalog).")
    (st.success if ok else st.error)(f"{ok}/{top} paket kabul edildi. Sonucu aşağıdan sorgulayın.")
  if kayit and st.button("🔍 Son gönderimlerin durumunu sorgula", key="hbk_durum"):
    for tid in kayit[-3:]:
      try:
        kod, metin = durum(h, tid)
        st.caption(f"{tid} · HTTP {kod}")
        st.code(metin[:1800])
      except Exception as e:
        st.error(f"{tid}: {e}")
