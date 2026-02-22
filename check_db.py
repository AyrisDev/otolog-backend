import asyncio
from prisma import Client

async def main():
    prisma = Client()
    await prisma.connect()
    user = await prisma.user.find_first()
    if not user:
        print("No user found.")
        return
    trips = await prisma.trip.find_many(where={"userId": user.id})
    print("User:", user.id)
    print("Trips count:", len(trips))
    total_trip_km = 0
    for t in trips:
        print(f"Trip {t.id} - active: {t.isActive} - distance: {t.distanceKm}")
        total_trip_km += t.distanceKm or 0
    
    fuels = await prisma.fuellog.find_many(where={"userId": user.id}, order={"date": "asc"})
    total_fuel_km = 0
    total_liters = 0
    if len(fuels) > 1:
        total_fuel_km = fuels[-1].currentKm - fuels[0].currentKm
    for f in fuels:
        print(f"Fuel {f.id} - liters: {f.liters} - price: {f.totalPrice} - currentKm: {f.currentKm}")
        total_liters += f.liters
        
    print(f"Total Trip KM: {total_trip_km}")
    print(f"Total Fuel KM: {total_fuel_km}")
    await prisma.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
