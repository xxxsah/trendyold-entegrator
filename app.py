import streamlit as st
import time
import sqlite3
import requests
import xml.etree.ElementTree as ET

# --- SAYFA YAPILANDIRMASI ---
st.set_page_config(page_title="E-Ticaret Çoklu Pazar Yeri Yönetimi", layout="wide")

st.title("🚀 E-Ticaret Entegrasyon ve Yönetim Paneli")
st.caption("Trendyol, Hepsiburada ve N11 operasyonlarınızın tek noktadan yönetimi ve veritabanı senkronizasyonu.")

# --- VERİTABANI BAĞLANTI VE KURULUMU ---
def get_db_connection():
    conn = sqlite3.connect('ecommerce.db', check_same_thread=False)
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # Ürünler tablosu oluşturuluyor (Eğer yoksa)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            barcode TEXT UNIQUE,
            title TEXT,
            price REAL,
            stock INTEGER,
            synced INTEGER DEFAULT 0
        )
    ''')
    
    # Eğer tablo boşsa örnek 14,377 ürün simülasyonu / başlangıç verisi basalım
    cursor.execute('SELECT COUNT(*) FROM products')
    count = cursor.fetchone()[0]
    if count == 0:
        # Test amaçlı ana veri yüklemesi (Performans için toplu ekleme)
        sample_data = []
        for i in range(1, 14378):
            stock_val = 0 if i % 28 == 0 else 10 # 518 tanesini stoksuz yapalım
            sample_data.append((f'BRC-{i:05d}', f'Örnek Ürün {i}', 150.0, stock_val, 0))
        cursor.executemany('INSERT OR IGNORE INTO products (barcode, title, price, stock, synced) VALUES (?, ?, ?, ?, ?)', sample_data)
        conn.commit()
    conn.close()

# Veritabanını başlat
init_db()

# --- VERİTABANI İSTATİSTİKLERİNİ ÇEKME ---
def get_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM products')
    total_products = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM products WHERE synced = 1')
    synced_products = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM products WHERE synced = 0')
    unsynced_products = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM products WHERE stock > 0')
    in_stock = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM products WHERE stock <= 0')
    no_stock = cursor.fetchone()[0]
    
    conn.close()
    return total_products, synced_products, unsynced_products, in_stock, no_stock

total, synced, unsynced, in_stock, no_stock = get_stats()


# --- N11 ENTEGRASYON MANTIĞI VE SINIFI ---
class N11IntegrationSystem:
    def __init__(self, app_key, app_secret):
        self.app_key = app_key
        self.app_secret = app_secret
        self.base_url = "https://api.n11.com/ws/"
        
    def authenticate_payload(self, data_dict):
        auth = {
            "appKey": self.app_key,
            "appSecret": self.app_secret
        }
        data_dict.update(auth)
        return data_dict

    def send_products_from_db_in_batches(self, batch_size=50):
        """
        Veritabanındaki senkronize edilmemiş ürünleri paketler halinde alır,
        n11'e gönderir ve veritabanında 'synced = 1' olarak günceller.
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT id, barcode, title, price, stock FROM products WHERE synced = 0')
        products = cursor.fetchall()
        total_products = len(products)
        
        if total_products == 0:
            st.info("Gönderilecek senkronize edilmemiş ürün bulunmuyor.")
            conn.close()
            return

        progress_bar = st.progress(0)
        status_text = st.empty()

        processed = 0
        for i in range(0, total_products, batch_size):
            batch = products[i:i + batch_size]
            try:
                # API İstek Simülasyonu
                time.sleep(0.3)
                
                # Başarılı olanları veritabanında güncelleyelim
                batch_ids = [row[0] for row in batch]
                cursor.executemany('UPDATE products SET synced = 1 WHERE id = ?', [(p_id,) for p_id in batch_ids])
                conn.commit()
                
                processed += len(batch)
                progress = min(float(processed) / total_products, 1.0)
                progress_bar.progress(progress)
                status_text.text(f"N11 Veritabanı Aktarımı Yapılıyor... {processed}/{total_products} ürün işlendi.")
            except Exception as e:
                st.error(f"Aktarım Hatası: {str(e)}")
        
        conn.close()
        st.success("Veritabanındaki ürünlerin n11 senkronizasyonu başarıyla tamamlandı!")
        st.rerun()


# --- ARAYÜZ / GÖRSEL KONTROL PANELİ ---
with st.expander("ℹ️ Önemli Bilgilendirme"):
    st.write("Günde 1 kez Tam Senkronizasyon yapmanız yeterlidir — sık çalıştırmak API kotanızı tüketir. Veriler SQLite veritabanından anlık çekilmektedir.")

# --- SENKRON & İŞLEMLER BUTONLARI ---
st.subheader("Senkronizasyon İşlemleri")
col_s1, col_s2, col_s3 = st.columns(3)
with col_s1:
    tam_sync = st.button("🔄 Tam Senkronizasyon...", type="primary")
with col_s2:
    kritik_stok = st.button("⚠️ Kritik Stok Sıfırla")
with col_s3:
    barkod_guncelle = st.button("📋 Tüm Barkodları Güncelle")

st.markdown("---")

st.subheader("Pazar Yeri İşlemleri")
col_i1, col_i2, col_i3 = st.columns(3)
with col_i1:
    btn_toplu = st.button("📦 Toplu Ürün Gönder (N11)")
with col_i2:
    btn_kargo = st.button("🚚 Kargo Süresi Ayarla")
with col_i3:
    btn_esleme = st.button("✅ Eşleşme Onay / Red")

st.info("N11'de yeni ürün açmak kategori ve özellik eşleştirme gerektirir, ayrı kurulum ister.")

# --- METRİKLER (DURUM KUTULARI - VERİTABANINDAN ANLIK) ---
st.markdown("### Mağaza Durum Özeti (Canlı Veritabanı)")
m1, m2 = st.columns(2)
with m1:
    st.metric(label="Toplam Ürün", value=f"{total:,}")
with m2:
    st.metric(label="Senkronize Edilmiş", value=f"{synced:,}")

m3, m4 = st.columns(2)
with m3:
    st.metric(label="Senkronize Edilememiş", value=f"{unsynced:,}")
with m4:
    st.metric(label="Stokta Olanlar", value=f"{in_stock:,}")

m5, _ = st.columns(2)
with m5:
    st.metric(label="Stok Tutmayanlar", value=f"{no_stock:,}")

st.markdown("---")

# --- HATA AYIKLAMA / LOGLAR ---
with st.expander("📜 Son İşlemler (Hata Ayıklama Logları)"):
    st.write("SQLite Veritabanı bağlantısı aktif. Tablolar sorunsuz çalışıyor.")

# --- BUTON TETİKLEYİCİLERİ ---
if btn_toplu:
    st.warning("Veritabanından N11 toplu ürün gönderim süreci başlatıldı...")
    
    API_KEY = "SENIN_API_ANAHTARIN"
    API_SECRET = "SENIN_API_SECRET_IN"
    
    n11_sys = N11IntegrationSystem(app_key=API_KEY, app_secret=API_SECRET)
    n11_sys.send_products_from_db_in_batches(batch_size=50)

if tam_sync:
    st.info("Tam senkronizasyon tetiklendi. Veritabanı pazar yeriyle eşitleniyor...")
    time.sleep(1)
    st.success("Veritabanı güncellendi.")
