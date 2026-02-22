import asyncio
from prisma import Prisma
from app.main import LocationsBulk, LocationPointCreate
from datetime import datetime

async def test():
    prisma = Prisma()
    await prisma.connect()
    
    trip = await prisma.trip.find_first()
    if not trip:
        print("No trip found")
        await prisma.disconnect()
        return

    payload = {
        "locations": [
            {
                "latitude": 39.0,
                "longitude": 35.0,
                "speed": 10.0,
                "timestamp": "2023-11-09T08:15:30.000Z"
            }
        ]
    }

    try:
        data = LocationsBulk(**payload)
        print("Pydantic success:", data)
    except Exception as e:
        print("Pydantic parsing error:", e)
        
    try:
        record_data = [
            {
                "tripId": trip.id,
                "latitude": loc.latitude,
                "longitude": loc.longitude,
                "speed": loc.speed or 0,
                "timestamp": loc.timestamp or datetime.now()
            }
            for loc in data.locations
        ]
        
        count = await prisma.locationpoint.create_many(data=record_data)
        print("Created successfully:", count)
    except Exception as e:
        print("Prisma create_many error:", e)

    await prisma.disconnect()

asyncio.run(test())
