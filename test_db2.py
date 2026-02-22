import asyncio
from prisma import Prisma
from datetime import datetime
import json

async def test():
    prisma = Prisma()
    await prisma.connect()
    
    trip = await prisma.trip.find_first()
    if not trip:
        print("No trip found")
        await prisma.disconnect()
        return

    record_data = [
        {
            "tripId": trip.id,
            "latitude": 39.0,
            "longitude": 35.0,
            "speed": 10.0,
            "timestamp": datetime.now()
        }
    ]

    try:
        count = await prisma.locationpoint.create_many(data=record_data)
        print("create_many success:", count)
    except Exception as e:
        print("create_many error:", e)

    await prisma.disconnect()

asyncio.run(test())
