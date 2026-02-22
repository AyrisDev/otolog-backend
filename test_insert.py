import asyncio
from prisma import Prisma
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class LocationPointCreate(BaseModel):
    latitude: float
    longitude: float
    speed: Optional[float] = 0
    timestamp: Optional[datetime] = None

async def test():
    prisma = Prisma()
    await prisma.connect()
    
    trip = await prisma.trip.find_first()
    if not trip:
        print("No trip found")
        await prisma.disconnect()
        return

    payload = {
        "latitude": 39.0,
        "longitude": 35.0,
        "speed": 10.0,
        "timestamp": "2023-11-09T08:15:30.000Z"
    }

    try:
        data = LocationPointCreate(**payload)
        print("Pydantic success:", data)
    except Exception as e:
        print("Pydantic parsing error:", e)

    try:
        point = await prisma.locationpoint.create(
            data={
                "tripId": trip.id,
                "latitude": data.latitude,
                "longitude": data.longitude,
                "speed": data.speed or 0,
                "timestamp": data.timestamp or datetime.now()
            }
        )
        print("Created successfully:", point.id)
    except Exception as e:
        print("Prisma create error:", e)

    await prisma.disconnect()

asyncio.run(test())
