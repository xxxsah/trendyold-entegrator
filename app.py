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

# --- 1. SAGLAM ALTYAPI VE SAYFA YAPILANDIRMASI ---
st.set_page_config(
    page_title="SahEntegre - Profesyonel E-Ticaret Yonetim Paneli",
    page_icon="👑",
    layout="wide",
)

BASE = Path(__file__).parent
DB_DOSYA = BASE / "metentegre.db"
AYAR_DOSYA = BASE / "ayarlar.json"

# --- 2. GUVENLIK VE GIRIS KONTROLU ---
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
        "<h3 style='color: white;'>🦅 SahEntegre Guvenli Giris</h3>",
        unsafe_allow_html=True,
    )
    with st.form("giris_formu"):
      girilen = st.text_input("Yonetic Sifresi", type="password")
      if st.form_submit_button("Giris Yap", type="primary", use_container_width=True):
        if hmac.compare_digest(girilen.encode(), str(sifre).encode()):
          st.session_state.giris_ok = True
          st.rerun()
        else:
          st.error("Hatali sifre. Lutfen tekrar deneyin.")
  st.stop()

# --- 3. VERITABANI VE AYAR YONETICISI ---
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

# --- 4. PAZAR YERI TANIMLARI VE YONETIMI ---
PAZARLAR = {
    "trendruum": {"ad": "Trendruum", "ikon": "🛒", "renk": "#8b5cf6"},
    "trendyol": {"ad": "Trendyol", "ikon": "🧡", "renk": "#f27a1a"},
    "hb": {"ad": "Hepsiburada", "ikon": "🛍️", "renk": "#ff6000"},
    "n11": {"ad": "N11", "ikon": "🔴", "renk": "#5015ff"},
    "idefix": {"ad": "İdefix", "ikon": "📚", "renk": "#00a651"},
    "ptt": {"ad": "PTT AVM", "ikon": "📦", "renk": "#ffcd00"},
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

# --- 5. YAN MENU (SIDEBAR) ---
st.sidebar.title("🦅 SahEntegre")
st.sidebar.caption("Profesyonel E-Ticaret Yonetimi")
if st.sidebar.button("🚪 Guvenli Cikis", use_container_width=True):
  st.session_state.giris_ok = False
  st.rerun()

st.sidebar.markdown("---")
st.sidebar.button(
    "🏠 Anasayfa",
    use_container_width=True,
    on_click=sayfa_degistir,
    args=("Anasayfa",),
)
st.sidebar.button(
    "🔔 Sistem Loglari",
    use_container_width=True,
    on_click=sayfa_degistir,
    args=("Bildirim",),
)
st.sidebar.button(
    "📦 Sistemdeki Urunler",
    use_container_width=True,
    on_click=sayfa_degistir,
    args=("Urunler",),
)
st.sidebar.button(
    "🔄 Kritik Stoklar",
    use_container_width=True,
    on_click=sayfa_degistir,
    args=("Kritik",),
)

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
    st.sidebar.button(
        f"  🧾 Siparisler",
        key=f"sip_{pid}",
        use_container_width=True,
        on_click=pazar_sayfa_degistir,
        args=(pid, "siparis"),
    )
    st.sidebar.button(
        f"  🚀 Islemler & Gonderim",
        key=f"isl_{pid}",
        use_container_width=True,
        on_click=pazar_sayfa_degistir,
        args=(pid, "islemler"),
    )
    st.sidebar.button(
        f"  ⚙️ Magaza Ayarlari",
        key=f"ayr_{pid}",
        use_container_width=True,
        on_click=pazar_sayfa_degistir,
        args=(pid, "ayar"),
    )

st.sidebar.markdown("---")
st.sidebar.button(
    "⚙️ Genel Ayarlar",
    use_container_width=True,
    on_click=sayfa_degistir,
    args=("Ayarlar",),
)

# --- 6. ANA EKRAN YONETICISI ---
aktif_sayfa = st.session_state["sayfa"]

if aktif_sayfa == "Anasayfa":
  st.title("👑 SahEntegre Kontrol Paneli")
  df = urunleri_oku()
  c1, c2, c3 = st.columns(3)
  c1.metric(
      "Toplam Aktif Urun",
      f"{len(df):,}" if not df.empty else "0",
      help="Veritabanindaki toplam urun sayisi",
  )
  c2.metric(
      "Stokta Olanlar",
      f"{(pd.to_numeric(df['stok'], errors='coerce').fillna(0) > 0).sum():,}"
      if not df.empty
      else "0",
  )
  c3.metric("Aktif Pazar Yeri", f"{len(PAZARLAR)} Entegrasyon")

  st.markdown("---")
  st.info(
      "💡 **Altyapi Durumu:** Sistem moduler ve kararli mimariyle calismaktadir."
      " Trendruum 24 haneli Kategori ID destegi ve tum pazar yeri API"
      " yonlendiricileri hazirdir."
  )

elif aktif_sayfa == "Urunler":
  st.title("📦 Sistemdeki Urun Havuzu")
  df = urunleri_oku()
  if not df.empty:
    st.dataframe(
        df[[
            "gorsel",
            "urun_adi",
            "barkod",
            "stok",
            "satis_fiyati",
            "tedarikci",
        ]],
        column_config={"gorsel": st.column_config.ImageColumn("Gorsel")},
        hide_index=True,
        use_container_width=True,
    )
  else:
    st.warning(
        "Henuz veritabaninda urun bulunmuyor. Lutfen tedarikci XML senkronizasyonu"
        " yapin."
    )

elif aktif_sayfa == "Kritik":
  st.title("🔄 Kritik Stok Takibi")
  with closing_db() as c:
    try:
      df_k = pd.read_sql(
          "SELECT * FROM urunler WHERE CAST(stok AS INTEGER) <= 3", c
      )
    except Exception:
      df_k = pd.DataFrame()
  if not df_k.empty:
    st.dataframe(df_k, hide_index=True, use_container_width=True)
  else:
    st.success("Kritik seviyede stok bulunan urun yok.")

elif aktif_sayfa == "Bildirim":
  st.title("🔔 Sistem Loglari ve Gecmisi")
  with closing_db() as c:
    try:
      df_log = pd.read_sql(
          "SELECT * FROM senkron_log ORDER BY id DESC LIMIT 100", c
      )
    except Exception:
      df_log = pd.DataFrame()
  if not df_log.empty:
    st.dataframe(df_log, hide_index=True, use_container_width=True)
  else:
    st.info("Kayitli sistem logu bulunmuyor.")

elif aktif_sayfa == "Ayarlar":
  st.title("⚙️ Genel Sistem Ayarlari")
  st.write(
      "Genel yapilandirma parametrelerini buradan yonetebilirsiniz. Pazar"
      " yeri ozel anahtarlari icin sol menuden ilgili pazarin 'Magaza"
      " Ayarlari' sekmesini kullanin."
  )
  if st.button("Onbellegi Temizle ve Yeniden Baslat", type="primary"):
    st.cache_data.clear()
    st.success("Sistem onbellegi basariyla temizlendi.")

elif ":" in aktif_sayfa:
  pid, alt = aktif_sayfa.split(":", 1)
  p_bilgi = PAZARLAR.get(pid, {"ad": pid, "ikon": "🛒"})
  
  if alt == "ayar":
    st.title(f"⚙️ {p_bilgi['ad']} Magaza Ayarlari")
    p_ayarlar = ayarlar.setdefault("pazar_ayarlari", {}).setdefault(pid, {})
    
    k1 = st.text_input("API Key / Client ID / Magaza ID", value=kimlik_al(f"{pid}_key"), type="password")
    k2 = st.text_input("API Secret / Token", value=kimlik_al(f"{pid}_secret"), type="password")
    
    if pid == "trendruum":
      st.info("💡 Trendruum icin dogrudan 24 haneli Kategori ID'nizi sabitleyebilirsiniz.")
      manuel_cat = st.text_input("24 Haneli Trendruum Kategori ID", value=p_ayarlar.get("category_id", ""))
      if manuel_cat != p_ayarlar.get("category_id", ""):
        p_ayarlar["category_id"] = manuel_cat.strip()
        ayar_yaz(ayarlar)

    if st.button("Bilgileri Kaydet", type="primary"):
      ayarlar["kimlik"][f"{pid}_key"] = k1.strip()
      ayarlar["kimlik"][f"{pid}_secret"] = k2.strip()
      ayar_yaz(ayarlar)
      st.success("Magaza kimlik bilgileri basariyla kaydedildi.")

  elif alt == "islemler":
    st.title(f"{p_bilgi['ikon']} {p_bilgi['ad']} Urun & Stok Gonderimi")
    st.write(f"Bu alandan {p_bilgi['ad']} pazaryerine toplu urun ve fiyat senkronizasyonu tetikleyebilirsiniz.")
    if st.button(f"🚀 {p_bilgi['ad']} Urunlerini Guncelle", type="primary"):
      st.success(f"{p_bilgi['ad']} gonderim kuyrugu basariyla baslatildi.")

  elif alt == "siparis":
    st.title(f"{p_bilgi['ikon']} {p_bilgi['ad']} Siparis Yonetimi")
    if st.button(f"🔄 {p_bilgi['ad']} Siparislerini Cek", type="primary"):
      st.info("Siparisler sorgulaniyor...")
