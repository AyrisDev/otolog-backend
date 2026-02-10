from prisma import Prisma
import asyncio

async def check():
    prisma = Prisma()
    print("Available attributes in Prisma object:")
    attrs = [a for a in dir(prisma) if not a.startswith('_')]
    for a in attrs:
        print(f" - {a}")

asyncio.run(check())
