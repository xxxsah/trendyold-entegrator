import sqlite3
import pandas as pd

DB_NAME = "sahentegre.db"


def init_db():
  conn = sqlite3.connect(DB_NAME, check_same_thread=False)
  cursor = conn.cursor()

  # Ürünler Tablosu
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS urunler (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gorsel TEXT,
            barkod TEXT UNIQUE,
            urun_adi TEXT,
            kategori TEXT,
            alis_fiyati REAL,
            satis_fiyati REAL,
            stok INTEGER,
            durum TEXT
        )
    """)

  # Siparişler Tablosu
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS siparisler (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            siparis_no TEXT UNIQUE,
            pazaryeri TEXT,
            musteri TEXT,
            urun TEXT,
            tutar TEXT,
            durum TEXT
        )
    """)

  # Ayarlar Tablosu
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS ayarlar (
            anahtar TEXT PRIMARY KEY,
            deger TEXT
        )
    """)

  conn.commit()

  # Eğer veritabanı boşsa örnek verileri ekle
  cursor.execute("SELECT COUNT(*) FROM urunler")
  if cursor.fetchone()[0] == 0:
    ornek_urunler = [
        (
            (
                "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=100"
            ),
            "8680001122331",
            "Kablosuz Hızlı Şarj Cihazı 15W",
            "Elektronik > Aksesuar",
            250.0,
            396.75,
            142,
            "Aktif",
        ),
        (
            (
                "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=100"
            ),
            "8680001122332",
            "Bluetooth 5.0 Kulaklık",
            "Elektronik > Ses",
            600.0,
            952.20,
            85,
            "Aktif",
        ),
        (
            (
                "https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=100"
            ),
            "8680001122333",
            "Ortopedik Spor Ayakkabı",
            "Spor > Giyim",
            450.0,
            714.15,
            12,
            "Kritik Stok",
        ),
    ]
    cursor.executemany(
        """
            INSERT OR IGNORE INTO urunler (gorsel, barkod, urun_adi, kategori, alis_fiyati, satis_fiyati, stok, durum)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ornek_urunler,
    )

  cursor.execute("SELECT COUNT(*) FROM siparisler")
  if cursor.fetchone()[0] == 0:
    ornek_siparisler = [
        ("SAH-88412", "Trendyol", "Ahmet Yılmaz", "Kablosuz Şarj", "396.75 TL", "Yeni"),
        ("SAH-88413", "Hepsiburada", "Zeynep Demir", "Kulaklık", "952.20 TL", "Kargolandı"),
    ]
    cursor.executemany(
        """
            INSERT OR IGNORE INTO siparisler (siparis_no, pazaryeri, musteri, urun, tutar, durum)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
        ornek_siparisler,
    )

  conn.commit()
  conn.close()


def get_connection():
  return sqlite3.connect(DB_NAME, check_same_thread=False)


def load_data(query, params=()):
  conn = get_connection()
  df = pd.read_sql(query, conn, params=params)
  conn.close()
  return df
