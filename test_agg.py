import asyncio
from prisma import Client

async def main():
    prisma = Client()
    await prisma.connect()
    
    speed_stats = await prisma.locationpoint.group_by(
        by=['tripId'],
        avg={'speed': True},
        max={'speed': True},
    )
    print(speed_stats)
    
    await prisma.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
