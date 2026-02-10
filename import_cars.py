import pandas as pd
import asyncio
from prisma import Prisma

# L/100km hesaplama fonksiyonu (MPG -> L/100km)
def convert_to_l100(mpg):
    if mpg > 0:
        return round(235.21 / mpg, 2)
    return 0

async def main():
    prisma = Prisma()
    await prisma.connect()

    print("Veri okunuyor...")
    # Örnek: 'vehicles.csv' dosyasını okuyoruz
    try:
        df = pd.read_csv('vehicles.csv', low_memory=False)
    except Exception as e:
        print(f"Hata: {e}")
        return

    # 1. 2000 yılı ve sonrasını filtrele
    if 'year' in df.columns:
        df_filtered = df[df['year'] >= 2000]
    else:
        print("'year' kolonu bulunamadı.")
        return

    # 2. Gereksiz sütunları at, ihtiyacımız olanları seç
    # 'make', 'model', 'year', 'comb08' (MPG verisi)
    cars_to_add = []
    
    print(f"Toplam {len(df_filtered)} satır işlenecek.")
    
    for index, row in df_filtered.iterrows():
        try:
            mpg = float(row.get('comb08', 0))
            consumption = convert_to_l100(mpg) # Ortalama tüketim
            
            # EPA datasında 'fuelType1' genelde ana yakıt tipidir
            ft = row.get('fuelType1', row.get('fuelType', 'Petrol'))
            
            cars_to_add.append({
                "brand": str(row['make']).capitalize(),
                "model": str(row['model']).capitalize(),
                "year": int(row['year']),
                "fuelType": str(ft),
                "avgConsumption": consumption,
                "combinationMpg": mpg
            })
        except Exception as e:
            continue

    # 3. Veritabanına Bas (Toplu işlem hızı için chunking yapıyoruz)
    count = 0
    print("Veritabanına yazılıyor...")
    
    # Batch size 50
    batch_size = 50
    for i in range(0, len(cars_to_add), batch_size):
        batch = cars_to_add[i:i+batch_size]
        
        # Upsert mantığı kurmak zor (Unique constraint yoksa), create kullanıyoruz
        # create_many destekleniyorsa onu kullanalım, yoksa loop
        # SQLite/Postgres create_many destekler ama Python client bazen kısıtlı.
        # Loop ile yapalım, user kodu öyleydi.
        
        for car in batch:
            try:
                # Mükerrer kaydı önlemek için basit kontrol (bu yavaşlatır ama güvenli)
                exists = await prisma.carlibrary.find_first(
                    where={
                        "brand": car["brand"],
                        "model": car["model"],
                        "year": car["year"]
                    }
                )
                if not exists:
                    await prisma.carlibrary.create(data=car)
                    count += 1
            except Exception as e:
                # print(f"Yazma hatası: {e}")
                pass
                
        if i % 100 == 0:
            print(f"📦 {i} araç işlendi... (Eklenen: {count})")

    print(f"✅ İşlem tamamlandı! Toplam {count} yeni araç eklendi.")
    await prisma.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
