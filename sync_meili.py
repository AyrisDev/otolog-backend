import asyncio
import meilisearch
from prisma import Prisma

# Meilisearch ayarları
MEILI_URL = 'https://search.ayris.tech'
MEILI_KEY = 'qGufJ9zmsd4bgsml2I35z8MjUFGjTlwo'

async def main():
    prisma = None
    try:
        print("1. Meilisearch'e bağlanılıyor...")
        client = meilisearch.Client(MEILI_URL, MEILI_KEY)
        
        # Test connection
        stats = client.health()
        print(f"Meilisearch Bağlantısı Başarılı: {stats}")

        print("2. Veritabanına bağlanılıyor...")
        prisma = Prisma()
        await prisma.connect()

        print("3. Bütün CarLibrary verileri çekiliyor...")
        cars = await prisma.carlibrary.find_many()
        
        print(f"Buldum! Toplam {len(cars)} araç var. Meilisearch'e fırlatılıyor...")

        # Meilisearch sadece JSON formatını sever (Python Dict)
        documents = []
        for car in cars:
            documents.append({
                "id": car.id,
                "brand": car.brand,
                "model": car.model,
                "year": car.year,
                "fuelType": car.fuelType,
                "transmission": car.transmission,
                "avgConsumption": car.avgConsumption,
                "searchField": f"{car.brand} {car.model} {car.year}"
            })

        # Toplu şekilde index'e ekle
        index = client.index('cars')
        
        print("4. Filtre ve Arama kuralları ayarlanıyor (Typo toleransı vb)...")
        index.update_searchable_attributes([
            'brand',
            'model',
            'searchField'
        ])
        index.update_filterable_attributes([
            'brand',
            'year',
            'fuelType'
        ])
        
        # 1000'erli yollamak daha sağlıklı olabilir
        batch_size = 5000
        for i in range(0, len(documents), batch_size):
            batch = documents[i:i+batch_size]
            task = index.add_documents(batch)
            print(f"Batch {i} to {i+len(batch)} eklendi! Görev ID: {task.task_uid}")

        print("Tebrikler! Bütün göç işlemi başarıyla tamamlandı.")
        
    except Exception as e:
        print(f"Bir hata oluştu: {e}")
    finally:
        if prisma:
            await prisma.disconnect()

if __name__ == '__main__':
    asyncio.run(main())
