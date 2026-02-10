from fastapi import FastAPI, HTTPException
from prisma import Prisma
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from passlib.context import CryptContext
from fastapi.middleware.cors import CORSMiddleware
app = FastAPI(title="OtoLog API - Pro")
prisma = Prisma()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now()}


from typing import List
from datetime import datetime

class LocationPointCreate(BaseModel):
    latitude: float
    longitude: float
    timestamp: Optional[datetime] = None

class BulkLocationUpdate(BaseModel):
    locations: List[LocationPointCreate]

class UserRegister(BaseModel):
    email: str
    password: str
    name: Optional[str] = None
    deviceId: Optional[str] = None

class UserLogin(BaseModel):
    email: str
    password: str
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
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
from fastapi import Header

@app.post("/register")
async def register(data: UserRegister, x_device_id: Optional[str] = Header(None)):
    print(f"Registration attempt for: {data.email}")
    # Use deviceId from header if not in body
    device_id = data.deviceId or x_device_id
    print(f"Device ID: {device_id}")
    
    try:
        # Check if user exists
        existing = await prisma.user.find_unique(where={"email": data.email})
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")

        # Device ID check (since it's unique in schema)
        if device_id:
            existing_device = await prisma.user.find_unique(where={"deviceId": device_id})
            if existing_device:
                # If this device is already registered, we could allow it or block it.
                # PRD says "deviceId should be unique". Let's return a clear error.
                raise HTTPException(status_code=400, detail="This device is already associated with another account")
            
        # Şifreyi hashle
        hashed_password = pwd_context.hash(data.password)
        
        # Kullanıcıyı oluştur
        user = await prisma.user.create(
            data={
                "email": data.email,
                "password": hashed_password,
                "name": data.name,
                "deviceId": device_id
            }
        )
        
        # Kayıtla beraber BMW 1.16'yı otomatik (default) olarak ekle
        await prisma.vehicle.create(
            data={
                "brand": "BMW",
                "model": "1.16",
                "isDefault": True,
                "userId": user.id
            }
        )
        print(f"User registered successfully: {user.id}")
        return {"status": "success", "userId": user.id}
    except Exception as e:
        print(f"REGISTRATION ERROR: {e}")
        import traceback
        traceback.print_exc()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/login")
async def login(data: UserLogin):
    user = await prisma.user.find_unique(
        where={"email": data.email},
        include={"vehicles": True}
    )
    
    if not user or not pwd_context.verify(data.password, user.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    # Find default vehicle
    default_vehicle = next((v for v in user.vehicles if v.isDefault), user.vehicles[0] if user.vehicles else None)
    
    return {
        "status": "success", 
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name
        },
        "defaultVehicleId": default_vehicle.id if default_vehicle else None
    }
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
    userId: str
    vehicleId: str
    startKm: Optional[float] = 0

class TripEnd(BaseModel):
    endKm: float
    distanceKm: float

class FuelCreate(BaseModel):
    userId: str
    liters: float
    totalPrice: float
    currentKm: float

# --- YOLCULUK ENDPOINTLERİ ---

@app.get("/trips")
async def get_trips(userId: Optional[str] = None):
    # Belirli bir kullanıcıya ait tamamlanmış yolculukları listeler
    where_clause = {"isActive": False}
    if userId:
        where_clause["userId"] = userId
        
    return await prisma.trip.find_many(
        where=where_clause,
        include={"locations": True},
        order={"startTime": "desc"}
    )

@app.post("/trips/start")
async def start_trip(data: TripStart):
    return await prisma.trip.create(
        data={
            "userId": data.userId,
            "vehicleId": data.vehicleId,
            "startKm": data.startKm,
            "isActive": True
        }
    )

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
            "userId": data.userId,
            "liters": data.liters,
            "totalPrice": data.totalPrice,
            "currentKm": data.currentKm
        }
    )

# --- İSTATİSTİK ENDPOINTLERİ ---

@app.get("/dashboard/summary")
async def get_summary(userId: Optional[str] = None):
    where_clause = {"isActive": False}
    if userId:
        where_clause["userId"] = userId
        
    trips = await prisma.trip.find_many(where=where_clause)
    
    fuel_where = {}
    if userId:
        fuel_where["userId"] = userId
    fuel = await prisma.fuellog.find_many(where=fuel_where)
    
    total_km = sum(t.distanceKm or 0 for t in trips)
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