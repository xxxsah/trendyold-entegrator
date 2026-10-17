import json

DURUM_ETIKET = {
    "yeni": "🟢 Yeni Sipariş",
    "hazirlaniyor": "🟡 Hazırlanıyor",
    "kargoda": "🚚 Kargoda",
    "tamamlandi": "✅ Tamamlandı",
    "iptal": "❌ İptal Edildi",
}


def metin(x):
    return str(x).strip() if x is not None else ""


def getp(d, *yollar):
    for y in yollar:
        parca = y.split(".")
        cur = d
        ok = True
        for p in parca:
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            else:
                ok = False
                break
        if ok and cur is not None:
            return cur
    return None


def tr_tarih(t):
    return metin(t)


def durum_kodu(s):
    s = str(s).lower()
    if s in ("created", "new", "beklemede"):
        return "yeni"
    if s in ("picking", "approved", "processing", "hazirlaniyor"):
        return "hazirlaniyor"
    if s in ("shipped", "kargoda"):
        return "kargoda"
    if s in ("delivered", "completed", "tamamlandi"):
        return "tamamlandi"
    return "iptal"


def siparis_normalle_ty(o):
    satirlar = []
    for line in o.get("lines", []):
        satirlar.append({"lineId": line.get("id"), "quantity": line.get("quantity", 1)})
    urunler = [{"ad": l.get("productName", ""), "sku": l.get("sku", ""), "adet": l.get("quantity", 1)} for l in o.get("lines", [])]
    return {
        "pid": "trendyol", "id": o.get("id"), "no": o.get("orderNumber"),
        "tarih": str(o.get("orderDate", "")), "durum": durum_kodu(o.get("status")),
        "alici": f"{o.get('customerFirstName', '')} {o.get('customerLastName', '')}".strip(),
        "adres": f"{getp(o, 'shipmentAddress.address1', 'deliveryAddress.address1', '')}, {getp(o, 'shipmentAddress.city', 'deliveryAddress.city', '')}",
        "tutar": o.get("totalPrice"), "urunler": urunler, "satirlar": satirlar,
    }


def siparis_normalle_n11(o):
    return {
        "pid": "n11", "id": o.get("id") or o.get("packageId"),
        "no": o.get("orderNumber") or o.get("shipmentPackageNumber"),
        "tarih": str(o.get("createdDate", "")), "durum": durum_kodu(o.get("status")),
        "alici": getp(o, "buyer.name", "shippingAddress.fullName", "Alıcı"),
        "adres": getp(o, "shippingAddress.address", ""),
        "tutar": getp(o, "totalPrice", "price"),
        "urunler": [{"ad": i.get("productName", ""), "sku": i.get("sku", ""), "adet": i.get("quantity", 1)} for i in o.get("items", [])],
        "satirlar": [],
    }


def siparis_normalle_tr(o):
    return {
        "pid": "trendruum", "id": o.get("_id") or o.get("id"),
        "no": o.get("order_number") or o.get("orderNumber"),
        "tarih": str(o.get("created_at", "")), "durum": durum_kodu(o.get("status")),
        "alici": getp(o, "shipping_address.name", "customer.name", "Alıcı"),
        "adres": getp(o, "shipping_address.address", ""),
        "tutar": o.get("total_price") or o.get("totalPrice"),
        "urunler": [{"ad": x.get("name", ""), "sku": x.get("barcode", ""), "adet": x.get("quantity", 1)} for x in o.get("products", [])],
        "satirlar": [],
    }
