from fastapi import FastAPI, HTTPException
from prisma import Prisma
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

app = FastAPI(title="OtoLog API - Pro")
prisma = Prisma()


from typing import List
from datetime import datetime

# Yeni Model: Koordinat Paketi
class LocationPointCreate(BaseModel):
    latitude: float
    longitude: float
    timestamp: Optional[datetime] = None

class BulkLocationUpdate(BaseModel):
    locations: List[LocationPointCreate]

@app.post("/trips/{trip_id}/location")
async def add_location(trip_id: str, data: LocationPointCreate):
    # Tekil koordinat kaydı
    print(f"Adding location for trip {trip_id}: {data}")
    try:
        res = await prisma.locationpoint.create(
            data={
                "latitude": data.latitude,
                "longitude": data.longitude,
                "timestamp": data.timestamp if data.timestamp else datetime.now(),
                "tripId": trip_id
            }
        )
        return res
    except Exception as e:
        print(f"Error adding location: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/trips/{trip_id}/locations/bulk")
async def add_locations_bulk(trip_id: str, data: BulkLocationUpdate):
    # Tüm noktaları tek seferde veritabanına basıyoruz
    print(f"Bulk adding {len(data.locations)} points for trip {trip_id}")
    try:
        points = [
            {
                "latitude": loc.latitude,
                "longitude": loc.longitude,
                "timestamp": loc.timestamp if loc.timestamp else datetime.now(),
                "tripId": trip_id
            } 
            for loc in data.locations
        ]
        if points:
            # Note: create_many might have different syntax or limitations depending on Prisma version
            # Using a loop or transaction if create_many is problematic in this env
            for pt in points:
                await prisma.locationpoint.create(data=pt)
        return {"status": "success", "added": len(points)}
    except Exception as e:
        print(f"Error bulk adding locations: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/trips/{trip_id}/full-path")
async def get_trip_path(trip_id: str):
    # Haritaya dikişli (stitch) çizgi çizmek için tüm rotayı çeker
    return await prisma.trip.find_unique(
        where={"id": trip_id},
        include={"locations": True}
    )
@app.on_event("startup")
async def startup():
    await prisma.connect()

@app.on_event("shutdown")
async def shutdown():
    await prisma.disconnect()

# --- MODELLER (Pydantic) ---
class TripStart(BaseModel):
    startKm: Optional[float] = 0

class TripEnd(BaseModel):
    endKm: float
    distanceKm: float

class FuelCreate(BaseModel):
    liters: float
    totalPrice: float
    currentKm: float

# --- YOLCULUK ENDPOINTLERİ ---

@app.get("/trips")
async def get_trips():
    # Sadece tamamlanmış (aktif olmayan) yolculukları listeler
    return await prisma.trip.find_many(
        where={"isActive": False},
        include={"locations": True},
        order={"startTime": "desc"}
    )

@app.post("/trips/start")
async def start_trip(data: TripStart):
    return await prisma.trip.create(data={"startKm": data.startKm, "isActive": True})

@app.patch("/trips/end/{trip_id}")
async def end_trip(trip_id: str):
    # 1. Bu trip'e ait tüm koordinatları çek
    points = await prisma.locationpoint.find_many(
        where={"tripId": trip_id},
        order={"timestamp": "asc"}
    )
    
    # 2. Koordinatlar arası mesafe hesapla (Haversine Formülü veya Basit Toplam)
    # Şimdilik Expo'dan gelen veriyi kabul edebiliriz ama backend doğrulaması şart.
    
    return await prisma.trip.update(
        where={"id": trip_id},
        data={
            "isActive": False,
            "endTime": datetime.now()
        }
    )

# --- YAKIT ENDPOINTLERİ ---

@app.post("/fuel/add")
async def add_fuel(data: FuelCreate):
    return await prisma.fuellog.create(
        data={
            "liters": data.liters,
            "totalPrice": data.totalPrice,
            "currentKm": data.currentKm
        }
    )

# --- İSTATİSTİK ENDPOINTLERİ ---

@app.get("/dashboard/summary")
async def get_summary():
    trips = await prisma.trip.find_many(where={"isActive": False})
    fuel = await prisma.fuellog.find_many()
    
    total_km = sum(t.distanceKm for t in trips)
    total_spend = sum(f.totalPrice for f in fuel)
    # Ortalama Tüketim (Litre / 100km)
    total_liters = sum(f.liters for f in fuel)
    avg_consumption = (total_liters / (total_km / 100)) if total_km > 0 else 0
    
    return {
        "total_km": round(total_km, 2),
        "total_spend": round(total_spend, 2),
        "avg_consumption": round(avg_consumption, 2),
        "trip_count": len(trips)
    }