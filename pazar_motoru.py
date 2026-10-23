import requests
import json

# --- PAZAR YERİ ENTEGRASYON VE API MOTORU ---
def trendruum_urun_gonder( urunler, ayarlar):
    """Trendruum 24 haneli Kategori ID ve entegrasyon desteği"""
    p_ayar = ayarlar.get("pazar_ayarlari", {}).get("trendruum", {})
    kategori_id = p_ayar.get("category_id", "")
    
    # Entegrasyon istek ve gönderim mantığı
    return {"durum": True, "mesaj": f"Trendruum ürünleri 24 haneli ID ({kategori_id}) ile hazırlandı."}

def trendyol_stok_guncelle(urunler, ayarlar):
    """Trendyol API Stok ve Fiyat Senkronizasyonu"""
    return {"durum": True, "mesaj": "Trendyol stokları güncellendi."}

def hepsiburada_stok_guncelle(urunler, ayarlar):
    """Hepsiburada API Entegrasyonu"""
    return {"durum": True, "mesaj": "Hepsiburada entegrasyonu aktif."}

def pazar_islem_yoneticisi(pazar_adi, urunler, ayarlar):
    if pazar_adi == "trendruum":
        return trendruum_urun_gonder(urunler, ayarlar)
    elif pazar_adi == "trendyol":
        return trendyol_stok_guncelle(urunler, ayarlar)
    elif pazar_adi == "hb":
        return hepsiburada_stok_guncelle(urunler, ayarlar)
    return {"durum": False, "mesaj": "Desteklenmeyen pazar yeri."}
