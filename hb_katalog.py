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
    
    # Fiyat formatı JSON API için nokta (.) ayracı ile düzeltildi
    fiyat_str = f"{float(r['satis_fiyati']):.2f}"
    
    a = {
        "merchantSku": pre + kod,
        "VaryantGroupID": pre + kod,
        "UrunAdi": ad[:255],
        "UrunAciklamasi": ad,
        "Marka": pa.get("marka", ""),
        "GarantiSuresi": str(int(pa.get("garanti", 24))),
        "kg": str(pa.get("kg", "1")),
        "tax_vat_rate": str(int(pa.get("kdv", 20))),
        "price": fiyat_str,
        "stock": str(int(max(r["stok"], 0))),
        "Image1": gorsel
    }
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
      r = requests.post(
          f"{MPOP}/product/api/products/import",
          headers=_h(h),
          timeout=120,
          files={
              "integrationFile": (
                  "urunler.json",
                  json.dumps(grup, ensure_ascii=False).encode("utf-8"),
                  "application/json"
              )
          }
      )
    except Exception as e:
      loglar.append(f"⚠️ Paket {no}: Bağlantı hatası -> {e}")
      continue
      
    if r.status_code in (200, 201, 202):
      try:
        resp_json = r.json()
        tid = (resp_json.get("data") or {}).get("trackingId") or resp_json.get("trackingId")
      except Exception:
        tid = None
      ok += 1
      if tid:
        idler.append(tid)
      loglar.append(f"✅ Paket {no}: {len(grup)} ürün iletildi (takip ID: {tid})")
    else:
      loglar.append(f"❌ Paket {no}: HTTP {r.status_code} - {r.text[:300]}")
      
    if ilerleme:
      ilerleme(min(no / toplam, 1.0), loglar)
  return ok, toplam, idler, loglar
