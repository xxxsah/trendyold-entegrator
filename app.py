import streamlit as st
import sqlite3
import requests
from bs4 import BeautifulSoup

# Sayfa Yapılandırması
st.set_page_config(
    page_title="Trendyol XML Entegrasyon Paneli",
    page_icon="📦",
    layout="wide"
)

st.title("📦 Trendyol XML Entegrasyon Paneli")
st.write("Bu panel sayesinde Trendyol API bilgilerinizi girerek XML senkronizasyon işlemlerinizi 7/24 kesintisiz yürütebilirsiniz.")

# Yan Menü / Ayarlar Alanı
st.sidebar.header("⚙️ Ayarlar & API Bilgileri")
supplier_id = st.sidebar.text_input("Trendyol Satıcı ID (Supplier ID)")
api_key = st.sidebar.text_input("Trendyol API Key", type="password")
api_secret = st.sidebar.text_input("Trendyol API Secret", type="password")
xml_url = st.sidebar.text_input("Tedarikçi XML Linki")

sync_button = st.sidebar.button("🚀 Senkronizasyonu Başlat")

# Ana Ekran - Loglar ve Durum
st.subheader("📋 Geçmiş Senkronizasyon Logları")

# Veritabanı ve Log Yapısı
def init_db():
    conn = sqlite3.connect('sync_logs.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS logs 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, message TEXT, status TEXT)''')
    conn.commit()
    conn.close()

init_db()

def get_logs():
    conn = sqlite3.connect('sync_logs.db')
    c = conn.cursor()
    c.execute("SELECT timestamp, message, status FROM logs ORDER BY id DESC LIMIT 50")
    rows = c.fetchall()
    conn.close()
    return rows

if sync_button:
    if not supplier_id or not api_key or not api_secret or not xml_url:
        st.sidebar.error("Lütfen tüm alanları eksiksiz doldurun!")
    else:
        st.sidebar.success("Bilgiler alındı, senkronizasyon simülasyonu başlatılıyor...")

logs = get_logs()
if logs:
    for log in logs:
        st.text(f"[{log[0]}] {log[2].upper()}: {log[1]}")
else:
    st.info("Henüz kayıtlı bir log bulunmuyor. Ayarları girip senkronizasyonu başlatabilirsiniz.")
