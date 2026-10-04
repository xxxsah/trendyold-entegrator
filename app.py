import streamlit as str_lib
import pandas as pd

# Sayfa Konfigürasyonu
str_lib.set_page_config(
    page_title="MetEntegre - E-Ticaret Yönetim Paneli",
    page_icon="📦",
    layout="wide"
)

# Oturum Durumu Yönetimi
if "aktif_sayfa" not in str_lib.session_state:
    str_lib.session_state.aktif_sayfa = "🏠 Anasayfa"

# ==========================================
# SOL MENÜ (Orijinal Sistem Menüsü)
# ==========================================
str_lib.sidebar.title("📌 MetEntegre Menü")
secim = str_lib.sidebar.selectbox(
    "Sayfa Seçin",
    [
        "🏠 Anasayfa",
        "💬 Destek Taleplerim",
        "🔔 Bildirimler",
        "📢 Duyurular",
        "📦 Sistemdeki Ürünler",
        "⚡ Oto Kritik Stok",
        "🧡 Trendyol Tüm İşlemler",
        "🌸 Çiçeksepeti Tüm İşlemler",
        "🔴 N11 Tüm İşlemler",
        "📦 E-PTT AVM Tüm İşlemler",
        "🟠 Hepsiburada Tüm İşlemler",
        "🔵 Pazarama Tüm İşlemler",
        "📚 İdefix Tüm İşlemler",
        "⚙️ Fiyat & Barkod Ayarları",
        "⚙️ Hesap ve API Ayarları"
    ],
    index=0
)

# ==========================================
# 1. ANASAYFA (Görseldeki Orijinal Tasarım)
# ==========================================
if secim == "🏠 Anasayfa":
    str_lib.title("🌐 MetEntegre - Kontrol Paneli")
    str_lib.markdown("#### Pazaryeri Durum Özetleri")
    
    # 1. Satır Kartlar (Hepsiburada, Trendyol, Çiçeksepeti)
    c1, c2, c3 = str_lib.columns(3)
    with c1:
        str_lib.markdown("""
            <div style='background-color: #ffffff; border: 2px solid #e65100; border-radius: 8px; padding: 10px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1);'>
                <div style='background-color: #e65100; color: white; padding: 8px; border-radius: 6px; font-weight: bold; margin-bottom: 8px;'>HEPSİBURADA</div>
                <div style='background-color: #e3f2fd; color: #0d47a1; padding: 6px; border-radius: 5px; font-size: 13px; margin-bottom: 5px; font-weight: bold;'>📦 6 Gönderime Hazır</div>
                <div style='background-color: #ffebee; color: #b71c1c; padding: 6px; border-radius: 5px; font-size: 13px; font-weight: bold;'>🚚 5 Kargoda</div>
            </div>
        """, unsafe_allow_html=True)
    with c2:
        str_lib.markdown("""
            <div style='background-color: #ffffff; border: 2px solid #f27a1a; border-radius: 8px; padding: 10px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1);'>
                <div style='background-color: #f27a1a; color: white; padding: 8px; border-radius: 6px; font-weight: bold; margin-bottom: 8px;'>TRENDYOL</div>
                <div style='color: #757575; font-size: 14px; padding: 22px;'>Sipariş yok</div>
            </div>
        """, unsafe_allow_html=True)
    with c3:
        str_lib.markdown("""
            <div style='background-color: #ffffff; border: 2px solid #e91e63; border-radius: 8px; padding: 10px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1);'>
                <div style='background-color: #e91e63; color: white; padding: 8px; border-radius: 6px; font-weight: bold; margin-bottom: 8px;'>ÇİÇEKSEPETİ</div>
                <div style='color: #757575; font-size: 14px; padding: 22px;'>Sipariş yok</div>
            </div>
        """, unsafe_allow_html=True)

    str_lib.markdown("<br>", unsafe_allow_html=True)
    
    # 2. Satır Kartlar (PTT AVM, N11, Pazarama)
    c4, c5, c6 = str_lib.columns(3)
    with c4:
        str_lib.markdown("""
            <div style='background-color: #ffffff; border: 2px solid #d84315; border-radius: 8px; padding: 10px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1);'>
                <div style='background-color: #d84315; color: white; padding: 8px; border-radius: 6px; font-weight: bold; margin-bottom: 8px;'>PTT AVM</div>
                <div style='background-color: #e8f5e9; color: #1b5e20; padding: 6px; border-radius: 5px; font-size: 13px; margin-bottom: 5px; font-weight: bold;'>🛍️ 1 Yeni Sipariş</div>
                <div style='background-color: #ede7f6; color: #311b92; padding: 6px; border-radius: 5px; font-size: 13px; font-weight: bold;'>📦 1 Kargo Bekliyor</div>
            </div>
        """, unsafe_allow_html=True)
    with c5:
        str_lib.markdown("""
            <div style='background-color: #ffffff; border: 2px solid #c62828; border-radius: 8px; padding: 10px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1);'>
                <div style='background-color: #c62828; color: white; padding: 8px; border-radius: 6px; font-weight: bold; margin-bottom: 8px;'>N11</div>
                <div style='color: #757575; font-size: 14px; padding: 22px;'>Sipariş yok</div>
            </div>
        """, unsafe_allow_html=True)
    with c6:
        str_lib.markdown("""
            <div style='background-color: #ffffff; border: 2px solid #0277bd; border-radius: 8px; padding: 10px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1);'>
                <div style='background-color: #0277bd; color: white; padding: 8px; border-radius: 6px; font-weight: bold; margin-bottom: 8px;'>PAZARAMA</div>
                <div style='background-color: #eceff1; color: #37474f; padding: 18px; border-radius: 5px; font-size: 14px; font-weight: bold;'>Çok yakında</div>
            </div>
        """, unsafe_allow_html=True)

    str_lib.markdown("<br>", unsafe_allow_html=True)
    
    # 3. Satır Kartlar (İdefix)
    c7, _, _ = str_lib.columns(3)
    with c7:
        str_lib.markdown("""
            <div style='background-color: #ffffff; border: 2px solid #2e7d32; border-radius: 8px; padding: 10px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1);'>
                <div style='background-color: #2e7d32; color: white; padding: 8px; border-radius: 6px; font-weight: bold; margin-bottom: 8px;'>İDEFİX</div>
                <div style='background-color: #eceff1; color: #37474f; padding: 18px; border-radius: 5px; font-size: 14px; font-weight: bold;'>Çok yakında</div>
            </div>
        """, unsafe_allow_html=True)

    str_lib.markdown("<br><hr><br>", unsafe_allow_html=True)
    
    # Fotoğraftaki Fatura Bilgileri Paneli (Birebir Tasarım)
    str_lib.markdown("""
        <div style='background-color: #ffffff; border: 2px solid #1565c0; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.1);'>
            <div style='background-color: #1565c0; color: white; padding: 12px; font-size: 16px; font-weight: bold; text-align: center;'>
                👤 Fatura Bilgileri
            </div>
            <div style='padding: 20px;'>
                <table style='width: 100%; font-size: 15px; border-collapse: collapse;'>
                    <tr style='border-bottom: 1px solid #e0e0e0;'>
                        <td style='padding: 12px; font-weight: bold; width: 25%; color: #333;'>👤 İsim:</td>
                        <td style='padding: 12px; color: #333;'>Şahin Yiğit</td>
                    </tr>
                    <tr style='border-bottom: 1px solid #e0e0e0;'>
                        <td style='padding: 12px; font-weight: bold; color: #333;'>✉️ Email:</td>
                        <td style='padding: 12px; color: #333;'>sah1357sah@gmail.com</td>
                    </tr>
                    <tr style='border-bottom: 1px solid #e0e0e0;'>
                        <td style='padding: 12px; font-weight: bold; color: #333;'>📞 Telefon:</td>
                        <td style='padding: 12px; color: #333;'>05346944235</td>
                    </tr>
                    <tr>
                        <td style='padding: 12px; font-weight: bold; color: #333;'>📍 Adres:</td>
                        <td style='padding: 12px; color: #333;'>Sevgi mah. 4642 sok no 4/1 Karabağlar İzmir[span_2](start_span)[span_2](end_span)</td>
                    </tr>
                </table>
            </div>
        </div>
    """, unsafe_allow_html=True)

# ==========================================
# 2. SİSTEMDEKİ ÜRÜNLER
# ==========================================
elif secim == "📦 Sistemdeki Ürünler":
    str_lib.title("📦 Sistemdeki Ürün Analizi")
    str_lib.write("Sisteminizdeki kayıtlı ürün ve stok durumları[span_3](start_span)[span_3](end_span).")
    
    col1, col2, col3 = str_lib.columns(3)
    col1.metric("Toplam Kategori", "4.009")
    col2.metric("Toplam Ürün", "131.401")
    col3.metric("Stoklu Ürün", "58.002")

# ==========================================
# 3. HEPSİBURADA TÜM İŞLEMLER
# ==========================================
elif secim == "🟠 Hepsiburada Tüm İşlemler":
    str_lib.title("🟠 Hepsiburada Tüm İşlemler")
    str_lib.write("Hepsiburada sipariş, kargo ve ürün senkronizasyon yönetimi.")
    str_lib.warning("⚠️ Günlük Tam Senkronizasyon sınırına dikkat ediniz[span_4](start_span)[span_4](end_span).")
    
    if str_lib.button("🔄 Tam Senkronizasyon Başlat"):
        str_lib.success("Hepsiburada senkronizasyonu tetiklendi!")

# ==========================================
# DİĞER MODÜLLER
# ==========================================
else:
    str_lib.title(f"📌 {secim}")
    str_lib.info("İlgili modül aktif olarak çalışmaktadır.")
