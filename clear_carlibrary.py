import asyncio
from prisma import Client

async def main():
    prisma = Client()
    await prisma.connect()
    
    deleted = await prisma.carlibrary.delete_many()
    print(f"Deleted {deleted} records from CarLibrary.")
    
    await prisma.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
