import asyncio
from prisma import aioprisma

async def main():
    prisma = aioprisma.Prisma()
    await prisma.connect()
    user_id = "cmly0yux10006p4xkd6fom6m7" # Will just grab first user
    user = await prisma.user.find_first()
    trips = await prisma.trip.find_many(where={"userId": user.id})
    print("User:", user.id)
    print("Trips count:", len(trips))
    for t in trips:
        print(f"Trip {t.id} - active: {t.isActive} - distance: {t.distanceKm}")
    
    fuels = await prisma.fuellog.find_many(where={"userId": user.id})
    for f in fuels:
        print(f"Fuel {f.id} - liters: {f.liters} - price: {f.totalPrice} - currentKm: {f.currentKm}")
        
    await prisma.disconnect()

asyncio.run(main())
