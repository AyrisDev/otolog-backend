# Bir seferlik test verisi basma scripti
import asyncio
from prisma import Prisma

async def main():
    prisma = Prisma()
    await prisma.connect()

    # 1. Trip Oluştur
    trip = await prisma.trip.create(
        data={
            'id': 'test-trip-1',
            'startKm': 48000,
            'isActive': False,
            'distanceKm': 54.5
        }
    )

    # 2. Koordinatları Ekle
    await prisma.locationpoint.create_many(
        data=[
            {'latitude': 37.2150, 'longitude': 28.3636, 'tripId': 'test-trip-1'},
            {'latitude': 37.0945, 'longitude': 28.3912, 'tripId': 'test-trip-1'},
            {'latitude': 36.8550, 'longitude': 28.2733, 'tripId': 'test-trip-1'}
        ]
    )
    print("Muğla-Marmaris rotası yüklendi!")
    await prisma.disconnect()

asyncio.run(main())