import sqlite3
import requests
from bs4 import BeautifulSoup
import streamlit as st

# Veritabani Kurulumu
def init_db():
  conn = sqlite3.connect("trendyol_sync.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS sync_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT,
            message TEXT
        )
    """)
  conn.commit()
  return conn, cursor

conn, cursor = init_db()

st.title("Trendyol XML Entegrasyon Paneli")
st.write("Bu panel sayesinde Trendyol API bilgilerinizi girerek XML senkronizasyon işlemlerinizi 7/24 kesintisiz yürütebilirsiniz.")

# Sidebar - Kimlik Dogrulama ve Ayarlar
st.sidebar.header("API Kimlik Bilgileri")
supplier_id = st.sidebar.text_input("Supplier ID")
api_key = st.sidebar.text_input("API Key", type="password")
api_secret = st.sidebar.text_input("API Secret", type="password")

st.sidebar.header("Islemler")
sync_button = st.sidebar.button("Senkronizasyonu Baslat")

if sync_button:
  if not supplier_id or not api_key or not api_secret:
    st.error("Lutfen tum API kimlik bilgilerini eksiksiz girin!")
  else:
    with st.spinner("Senkronizasyon gerceklestiriliyor..."):
      try:
        url = f"https://api.trendyol.com/sapigw/suppliers/{supplier_id}/products"
        headers = {"User-Agent": f"{supplier_id} - Self"}
        response = requests.get(url, headers=headers, auth=(api_key, api_secret))

        if response.status_code == 200:
          st.success("Senkronizasyon basariyla tamamlandi!")
          cursor.execute("INSERT INTO sync_logs (status, message) VALUES (?, ?)", ("BASARILI", "XML verileri basariyla senkronize edildi."))
          conn.commit()
        else:
          err_msg = f"API Hatasi! Durum Kodu: {response.status_code} - {response.text}"
          st.error(err_msg)
          cursor.execute("INSERT INTO sync_logs (status, message) VALUES (?, ?)", ("HATA", err_msg))
          conn.commit()

      except Exception as e:
        err_msg = f"Bir hata olustu: {str(e)}"
        st.error(err_msg)
        cursor.execute("INSERT INTO sync_logs (status, message) VALUES (?, ?)", ("HATA", err_msg))
        conn.commit()

# Gecmis Loglari Goster
st.subheader("Gecmis Senkronizasyon Loglari")
cursor.execute("SELECT timestamp, status, message FROM sync_logs ORDER BY id DESC LIMIT 10")
logs = cursor.fetchall()

if logs:
  for log in logs:
    st.text(f"[{log[0]}] {log[1]} - {log[2]}")
else:
  st.info("Henuz kayitli bir log bulunmuyor.")
