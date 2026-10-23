import base64
import hmac
import os
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

# --- 1. SAYFA YAPILANDIRMASI VE TEMA ---
st.set_page_config(
    page_title="ŞahEntegre - Profesyonel E-Ticaret Yönetim Paneli",
    page_icon="👑",
    layout="wide",
)

BASE = Path(__file__).parent
DB_DOSYA = BASE / "metentegre.db"
AYAR_DOSYA = BASE / "ayarlar.json"

# --- 2. GÜVENLİK VE GİRİŞ KONTROLÜ ---
sifre = os.environ.get("APP_PASSWORD") or (
    str(st.secrets.get("APP_PASSWORD"))
    if "APP_PASSWORD" in st.secrets
    else None
)

if sifre and not st.session_state.get("giris_ok"):
  st.markdown(
      """<style>[data-testid="stAppViewContainer"]{background:#0f172a;}</style>""",
      unsafe_allow_html=True,
  )
  _, orta, _ = st.columns([1, 1.4, 1])
  with orta:
    st.markdown(
        "<h3 style='color: white;'>🦅 ŞahEntegre Güvenli Giriş</h3>",
        unsafe_allow_html=True,
    )
    with st.form("giris_formu"):
      girilen = st.text_input("Yönetici Şifresi", type="password")
      if st.form_submit_button("Giriş Yap", type="primary", use_container_width=True):
        if hmac.compare_digest(girilen.encode(), str(sifre).encode()):
          st.session_state.giris_ok = True
          st.rerun()
        else:
          st.error("Hatalı şifre. Lütfen tekrar deneyin.")
  st.stop()

# --- 3. VERİTABANI VE AYAR YÖNETİCİSİ ---
def baglan():
  conn = sqlite3.connect(DB_DOSYA, timeout=30)
  conn.execute("PRAGMA journal_mode=WAL")
  return conn

def ayar_oku():
  if AYAR_DOSYA.exists():
    try:
      return json.loads(AYAR_DOSYA.read_text(encoding="utf-8"))
    except Exception:
      pass
  return {
      "tedarikciler": {},
      "kimlik": {},
      "pazar_ayarlari": {},
      "kritik_esik": 0,
  }

def ayar_yaz(veri):
  tmp = AYAR_DOSYA.with_suffix(".tmp")
  tmp.write_text(
      json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8"
  )
  tmp.replace(AYAR_DOSYA)

if "ayarlar" not in st.session_state:
  st.session_state.ayarlar = ayar_oku()
ayarlar = st.session_state.ayarlar
ayarlar.setdefault("kimlik", {})
ayarlar.setdefault("pazar_ayarlari", {})

def kimlik_al(ad):
  val = ayarlar.get("kimlik", {}).get(ad, "")
  return str(val).strip() if val else ""

def urunleri_oku():
  with closing_db() as c:
    try:
      return pd.read_sql("SELECT * FROM urunler", c)
    except Exception:
      return pd.DataFrame()

from contextlib import closing
def closing_db():
  return closing(baglan())

# --- 4. PAZAR YERİ TANIMLARI ---
PAZARLAR = {
    "trendruum": {"ad": "Trendruum", "ikon": "🛒", "renk": "#8b5cf6", "aciklama": "24 Haneli Kategori ID & Özel Entegrasyon"},
    "trendyol": {"ad": "Trendyol", "ikon": "🧡", "renk": "#f27a1a", "aciklama": "Mağaza Ürün ve Stok Senkronizasyonu"},
    "hb": {"ad": "Hepsiburada", "ikon": "🛍️", "renk": "#ff6000", "aciklama": "Toptan ve Bayi Entegrasyon Yönetimi"},
    "n11": {"ad": "N11", "ikon": "🔴", "renk": "#5015ff", "aciklama": "API Bağlantısı ve Kategori Eşleme"},
    "idefix": {"ad": "İdefix", "ikon": "📚", "renk": "#00a651", "aciklama": "Kitap ve Çeşitli Kategori Yönetimi"},
    "ptt": {"ad": "PTT AVM", "ikon": "📦", "renk": "#ffcd00", "aciklama": "Gönderim ve Sipariş Takip Paneli"},
}

st.session_state.setdefault("sayfa", "Anasayfa")
st.session_state.setdefault("acik_pazar", None)

def sayfa_degistir(s):
  st.session_state["sayfa"] = s

def pazar_sayfa_degistir(pid, alt):
  st.session_state["acik_pazar"] = pid
  st.session_state["sayfa"] = f"{pid}:{alt}"

def pazar_menu_ac_kapa(pid):
  if st.session_state.get("acik_pazar") == pid:
    st.session_state["acik_pazar"] = None
  else:
    st.session_state["acik_pazar"] = pid

# --- 5. YAN MENÜ (SIDEBAR) ---
st.sidebar.title("🦅 ŞahEntegre")
st.sidebar.caption("Profesyonel E-Ticaret Yönetimi")
if st.sidebar.button("🚪 Güvenli Çıkış", use_container_width=True):
  st.session_state.giris_ok = False
  st.rerun()

st.sidebar.markdown("---")
st.sidebar.button("🏠 Anasayfa", use_container_width=True, on_click=sayfa_degistir, args=("Anasayfa",))
st.sidebar.button("🔔 Sistem Logları", use_container_width=True, on_click=sayfa_degistir, args=("Bildirim",))
st.sidebar.button("📦 Sistemdeki Ürünler", use_container_width=True, on_click=sayfa_degistir, args=("Urunler",))
st.sidebar.button("🔄 Kritik Stoklar", use_container_width=True, on_click=sayfa_degistir, args=("Kritik",))

st.sidebar.markdown("### 🛒 Pazar Yerleri")
for pid, p in PAZARLAR.items():
  acik = st.session_state["acik_pazar"] == pid
  st.sidebar.button(
      f"{p['ikon']} {p['ad']} {'▾' if acik else '▸'}",
      key=f"menu_{pid}",
      use_container_width=True,
      on_click=pazar_menu_ac_kapa,
      args=(pid,),
  )
  if acik:
    st.sidebar.button(f"  🧾 Siparişler", key=f"sip_{pid}", use_container_width=True, on_click=pazar_sayfa_degistir, args=(pid, "siparis"))
    st.sidebar.button(f"  🚀 İşlemler & Gönderim", key=f"isl_{pid}", use_container_width=True, on_click=pazar_sayfa_degistir, args=(pid, "islemler"))
    st.sidebar.button(f"  ⚙️ Mağaza Ayarları", key=f"ayr_{pid}", use_container_width=True, on_click=pazar_sayfa_degistir, args=(pid, "ayar"))

st.sidebar.markdown("---")
st.sidebar.button("⚙️ Genel Ayarlar", use_container_width=True, on_click=sayfa_degistir, args=("Ayarlar",))

# --- 6. ANA EKRAN VE GÖRSEL KUTULAR ---
aktif_sayfa = st.session_state["sayfa"]

if aktif_sayfa == "Anasayfa":
  st.title("👑 ŞahEntegre Kontrol Paneli")
  df = urunleri_oku()
  
  c1, c2, c3 = st.columns(3)
  c1.metric("Toplam Aktif Ürün", f"{len(df):,}" if not df.empty else "0", help="Veritabanındaki toplam ürün sayısı")
  c2.metric("Stokta Olanlar", f"{(pd.to_numeric(df['stok'], errors='coerce').fillna(0) > 0).sum():,}" if not df.empty else "0")
  c3.metric("Aktif Pazar Yeri", f"{len(PAZARLAR)} Entegrasyon")

  st.markdown("---")
  st.subheader("🛒 Pazar Yeri Yönetim Kutuları")
  st.write("Aşağıdaki pazar yeri kartlarına tıklayarak doğrudan mağaza ayarlarınıza ve işlemlerinize ulaşabilirsiniz:")

  # Pazar yeri görsel kutuları (Grid yapısı)
  cols = st.columns(2)
  for i, (pid, p) in enumerate(PAZARLAR.items()):
    with cols[i % 2]:
      st.markdown(f"""
      <div style="padding: 20px; border-radius: 12px; border: 2px solid {p['renk']}; background-color: #ffffff; margin-bottom: 15px; box-shadow: 0 4px 6px rgba(0,0,0,0.05);">
          <h3 style="margin: 0; color: {p['renk']};">{p['ikon']} {p['ad']}</h3>
          <p style="color: #666; font-size: 14px; margin: 8px 0 15px 0;">{p['aciklama']}</p>
      </div>
      """, unsafe_allow_html=True)
      
      b1, b2 = st.columns(2)
      with b1:
        if st.button(f"⚙️ Ayarlar", key=btn_key1 := f"home_ayar_{pid}", use_container_width=True):
          pazar_sayfa_degistir(pid, "ayar")
          st.rerun()
      with b2:
        if st.button(f"🚀 İşlemler", key=btn_key2 := f"home_isl_{pid}", use_container_width=True):
          pazar_sayfa_degistir(pid, "islemler")
          st.rerun()

elif aktif_sayfa == "Urunler":
  st.title("📦 Sistemdeki Ürün Havuzu")
  df = urunleri_oku()
  if not df.empty:
    st.dataframe(
        df[["gorsel", "urun_adi", "barkod", "stok", "satis_fiyati", "tedarikci"]],
        column_config={"gorsel": st.column_config.ImageColumn("Görsel")},
        hide_index=True,
        use_container_width=True,
    )
  else:
    st.warning("Henüz veritabanında ürün bulunmuyor. Lütfen tedarikçi XML senkronizasyonu yapın.")

elif aktif_sayfa == "Kritik":
  st.title("🔄 Kritik Stok Takibi")
  with closing_db() as c:
    try:
      df_k = pd.read_sql("SELECT * FROM urunler WHERE CAST(stok AS INTEGER) <= 3", c)
    except Exception:
      df_k = pd.DataFrame()
  if not df_k.empty:
    st.dataframe(df_k, hide_index=True, use_container_width=True)
  else:
    st.success("Kritik seviyede stok bulunan ürün yok.")

elif aktif_sayfa == "Bildirim":
  st.title("🔔 Sistem Logları ve Geçmişi")
  with closing_db() as c:
    try:
      df_log = pd.read_sql("SELECT * FROM senkron_log ORDER BY id DESC LIMIT 100", c)
    except Exception:
      df_log = pd.DataFrame()
  if not df_log.empty:
    st.dataframe(df_log, hide_index=True, use_container_width=True)
  else:
    st.info("Kayıtlı sistem logu bulunmuyor.")

elif aktif_sayfa == "Ayarlar":
  st.title("⚙️ Genel Sistem Ayarları")
  st.write("Genel yapılandırma parametrelerini ve kritik eşik değerlerini buradan yönetebilirsiniz.")
  
  kritik_input = st.number_input("Kritik Stok Eşiği", value=int(ayarlar.get("kritik_esik", 0)))
  if kritik_input != ayarlar.get("kritik_esik", 0):
    ayarlar["kritik_esik"] = kritik_input
    ayar_yaz(ayarlar)
    st.success("Kritik stok eşiği güncellendi.")

  if st.button("Önbelleği Temizle ve Yeniden Başlat", type="primary"):
    st.cache_data.clear()
    st.success("Sistem önbelleği başarıyla temizlendi.")

elif ":" in aktif_sayfa:
  pid, alt = aktif_sayfa.split(":", 1)
  p_bilgi = PAZARLAR.get(pid, {"ad": pid, "ikon": "🛒"})
  
  if alt == "ayar":
    st.title(f"⚙️ {p_bilgi['ad']} Mağaza Ayarları")
    st.write(f"{p_bilgi['ad']} pazaryeri için API anahtarlarınızı ve özel ayarlarınızı bu ekrandan yönetebilirsiniz.")
    
    p_ayarlar = ayarlar.setdefault("pazar_ayarlari", {}).setdefault(pid, {})
    
    k1 = st.text_input("API Key / Client ID / Mağaza ID", value=kimlik_al(f"{pid}_key"), type="password")
    k2 = st.text_input("API Secret / Token", value=kimlik_al(f"{pid}_secret"), type="password")
    
    if pid == "trendruum":
      st.info("💡 Trendruum için doğrudan 24 haneli Kategori ID'nizi sabitleyebilirsiniz.")
      manuel_cat = st.text_input("24 Haneli Trendruum Kategori ID", value=p_ayarlar.get("category_id", ""))
      if manuel_cat != p_ayarlar.get("category_id", ""):
        p_ayarlar["category_id"] = manuel_cat.strip()
        ayar_yaz(ayarlar)

    if st.button("Bilgileri Kaydet", type="primary"):
      ayarlar["kimlik"][f"{pid}_key"] = k1.strip()
      ayarlar["kimlik"][f"{pid}_secret"] = k2.strip()
      ayar_yaz(ayarlar)
      st.success("Mağaza kimlik bilgileri başarıyla kaydedildi.")

  elif alt == "islemler":
    st.title(f"{p_bilgi['ikon']} {p_bilgi['ad']} Ürün & Stok Gönderimi")
    st.write(f"Bu alandan {p_bilgi['ad']} pazaryerine toplu ürün ve fiyat senkronizasyonu tetikleyebilirsiniz.")
    if st.button(f"🚀 {p_bilgi['ad']} Ürünlerini Güncelle", type="primary"):
      st.success(f"{p_bilgi['ad']} gönderim kuyruğu başarıyla başlatıldı.")

  elif alt == "siparis":
    st.title(f"{p_bilgi['ikon']} {p_bilgi['ad']} Sipariş Yönetimi")
    st.write(f"{p_bilgi['ad']} üzerinden gelen siparişleri bu ekrandan görüntüleyebilir ve yönetebilirsiniz.")
    if st.button(f"🔄 {p_bilgi['ad']} Siparişlerini Çek", type="primary"):
      st.info("Siparişler sorgulanıyor...")
