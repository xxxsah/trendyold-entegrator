import streamlit as st
import sqlite3
import requests
from datetime import datetime
import base64

st.set_page_config(
    page_title="Trendyol Stok & Fiyat Senkronizasyon Paneli",
    page_icon="📦",
    layout="wide"
)

st.title("📦 Trendyol Stok & Fiyat Senkronizasyon Paneli")
st.write("Trendyol API bilgilerinizi girerek stok ve fiyat güncellemelerinizi buradan yönetebilirsiniz.")

st.sidebar.header("⚙️ Trendyol API Bilgileri")
supplier_id = st.sidebar.text_input("Trendyol Satıcı ID (Cari ID)")
ref_code = st.sidebar.text_input("Entegrasyon Referans Kodu", type="password")
api_secret = st.sidebar.text_input("API Secret", type="password")

sync_button = st.sidebar.button("🚀 Senkronizasyonu Başlat")

st.subheader("📋 Geçmiş Senkronizasyon Logları")

def init_db():
    conn = sqlite3.connect('sync_logs.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS logs 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, message TEXT, status TEXT)''')
    conn.commit()
    conn.close()

init_db()

def add_log(message, status):
    conn = sqlite3.connect('sync_logs.db')
    c = conn.cursor()
    c.execute("INSERT INTO logs (message, status) VALUES (?, ?)", (message, status))
    conn.commit()
    conn.close()

def get_logs():
    conn = sqlite3.connect('sync_logs.db')
    c = conn.cursor()
    c.execute("SELECT timestamp, message, status FROM logs ORDER BY id DESC LIMIT 50")
    rows = c.fetchall()
    conn.close()
    return rows

if sync_button:
    if not supplier_id or not ref_code or not api_secret:
        st.sidebar.error("Lütfen tüm alanları eksiksiz girin!")
    else:
        with st.spinner("Trendyol API bağlantısı test ediliyor..."):
            try:
                url = f"https://api.trendyol.com/sapigw/suppliers/{supplier_id}/products?page=0&size=1"
                
                user_pass = f"{ref_code}:{api_secret}"
                encoded_credentials = base64.b64encode(user_pass.encode()).decode()
                
                # Trendyol'un kesinlikle istediği User-Agent formatı
                headers = {
                    "User-Agent": f"{supplier_id} - SelfIntegration",
                    "Authorization": f"Basic {encoded_credentials}",
                    "Content-Type": "application/json"
                }
                
                response = requests.get(url, headers=headers)
                
                if response.status_code == 200:
                    msg = "Trendyol API bağlantısı başarılı!"
                    st.sidebar.success(msg)
                    add_log(msg, "success")
                else:
                    msg = f"Hata Kodu: {response.status_code} | Yanıt: {response.text}"
                    st.sidebar.error(msg)
                    add_log(msg, "error")
            except Exception as e:
                msg = f"Hata: {str(e)}"
                st.sidebar.error(msg)
                add_log(msg, "error")

logs = get_logs()
if logs:
    for log in logs:
        status_color = "🟢" if log[2] == "success" else "🔴"
        st.text(f"[{log[0]}] {status_color} {log[2].upper()}: {log[1]}")
else:
    st.info("Henüz kayıtlı bir log bulunmuyor.")
