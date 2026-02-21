import psycopg2

# Veritabanı URL'i
DB_URL = "postgres://postgres:6UuYjVZ13ZKfmgKRIsXiCqNjLriAkvugGG9awYqM4BXo78Sg39JypbyNgV72K0zY@65.109.236.58:5433/postgres"

def run_migration():
    conn = None
    try:
        print("--- Veritabanına bağlanılıyor... ---")
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        
        print("--- 'speed' kolonu kontrol ediliyor/ekleniyor... ---")
        # LocationPoint tablosuna speed kolonunu ekle
        alter_query = 'ALTER TABLE "LocationPoint" ADD COLUMN IF NOT EXISTS "speed" DOUBLE PRECISION DEFAULT 0;'
        
        cur.execute(alter_query)
        conn.commit()
        
        print("\n✅ BAŞARILI: 'LocationPoint' tablosuna 'speed' kolonu eklendi.")
        
        cur.close()
    except Exception as e:
        print(f"\n❌ HATA OLUŞTU: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    run_migration()
