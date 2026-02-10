from fastapi import FastAPI, HTTPException, Header
from prisma import Prisma
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from passlib.context import CryptContext
from fastapi.middleware.cors import CORSMiddleware
import traceback

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
    return {"status": "ok", "version": "v2", "timestamp": datetime.now()}


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
                raise HTTPException(status_code=400, detail="This device is already associated with another account")
            
        # Şifreyi hashle (bcrypt 72 byte sınırı var, bu yüzden gerekirse kırpıyoruz)
        safe_password = data.password[:72]
        print(f"Hashing password (length: {len(data.password)})")
        hashed_password = pwd_context.hash(safe_password)
        
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
        traceback.print_exc()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/login")
async def login(data: UserLogin):
    try:
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
    except Exception as e:
        print(f"LOGIN ERROR: {e}")
        traceback.print_exc()
        if isinstance(e, HTTPException):
            raise e
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
            for pt in points:
                await prisma.locationpoint.create(data=pt)
        return {"status": "success", "added": len(points)}
    except Exception as e:
        print(f"Error bulk adding locations: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/trips/{trip_id}/full-path")
async def get_trip_path(trip_id: str):
    # Haritaya dikişli (stitch) çizgi çizmek için tüm rotayı çeker
    try:
        return await prisma.trip.find_unique(
            where={"id": trip_id},
            include={"locations": True}
        )
    except Exception as e:
        print(f"GET TRIP PATH ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
    try:
        where_clause = {"isActive": False}
        if userId and userId != "undefined":
            where_clause["userId"] = userId
            
        return await prisma.trip.find_many(
            where=where_clause,
            include={"locations": True},
            order={"startTime": "desc"}
        )
    except Exception as e:
        print(f"GET TRIPS ERROR: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/trips/start")
async def start_trip(data: TripStart):
    try:
        return await prisma.trip.create(
            data={
                "userId": data.userId,
                "vehicleId": data.vehicleId,
                "startKm": data.startKm,
                "isActive": True
            }
        )
    except Exception as e:
        print(f"START TRIP ERROR: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/trips/end/{trip_id}")
async def end_trip(trip_id: str):
    try:
        return await prisma.trip.update(
            where={"id": trip_id},
            data={
                "isActive": False,
                "endTime": datetime.now()
            }
        )
    except Exception as e:
        print(f"END TRIP ERROR: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# --- YAKIT ENDPOINTLERİ ---

@app.post("/fuel/add")
async def add_fuel(data: FuelCreate):
    try:
        return await prisma.fuellog.create(
            data={
                "userId": data.userId,
                "liters": data.liters,
                "totalPrice": data.totalPrice,
                "currentKm": data.currentKm
            }
        )
    except Exception as e:
        print(f"ADD FUEL ERROR: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# --- İSTATİSTİK ENDPOINTLERİ ---

@app.get("/dashboard/summary")
async def get_summary(userId: Optional[str] = None):
    try:
        where_clause = {"isActive": False}
        if userId and userId != "undefined":
            where_clause["userId"] = userId
            
        trips = await prisma.trip.find_many(where=where_clause)
        
        fuel_where = {}
        if userId and userId != "undefined":
            fuel_where["userId"] = userId
        fuel = await prisma.fuellog.find_many(where=fuel_where)
        
        total_km = sum(t.distanceKm or 0 for t in trips)
        total_spend = sum(f.totalPrice for f in fuel)
        total_liters = sum(f.liters for f in fuel)
        avg_consumption = (total_liters / (total_km / 100)) if total_km > 0 else 0
        
        return {
            "total_km": round(total_km, 2),
            "total_spend": round(total_spend, 2),
            "avg_consumption": round(avg_consumption, 2),
            "trip_count": len(trips)
        }
    except Exception as e:
        print(f"GET SUMMARY ERROR: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))