import asyncio; from prisma import Prisma; prisma=Prisma()
async def main():
    await prisma.connect()
    trips=await prisma.trip.find_many(include={'locations': True})
    empty_trips=[t.id for t in trips if len(t.locations)==0]
    print(f'Empty trips: {len(empty_trips)}/{len(trips)}')
    print('Total points:', await prisma.locationpoint.count())
    await prisma.disconnect()
asyncio.run(main())

