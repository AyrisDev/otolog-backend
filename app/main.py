from fastapi import FastAPI, HTTPException, Header, Depends, status
from prisma import Prisma
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
from passlib.context import CryptContext
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
import traceback
import os
from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv()

# --- GÜVENLİK AYARLARI ---
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "7b8d4b7d-a7c7-4824-8d74-7e6489378878-STITCHED-OtoLog")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", str(60 * 24 * 30)))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login", auto_error=False)

app = FastAPI(title="OtoLog API - Silent Auth Fix")
prisma = Prisma()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- MODELLER (Pydantic) - En üstte olmalı ---

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

# --- YARDIMCI FONKSİYONLAR ---

def create_access_token(data: dict):
    try:
        to_encode = data.copy()
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
    except Exception as e:
        print(f"TOKEN CREATE ERROR: {e}")
        return None

async def get_current_user(token: str = Depends(oauth2_scheme)):
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Oturum süresi dolmuş veya geçersiz.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Geçersiz token.")
        return user_id
    except JWTError:
        raise HTTPException(status_code=401, detail="Oturum doğrulanamadı.")

# --- ENDPOINTLER ---

@app.get("/health")
async def health():
    return {"status": "ok", "version": "v4-silent-fix", "timestamp": datetime.now()}

@app.post("/device-login")
async def device_login(x_device_id: Optional[str] = Header(None)):
    if not x_device_id:
        raise HTTPException(status_code=400, detail="Cihaz kimliği eksik.")
        
    print(f"DEVICE LOGIN REQUEST: {x_device_id}")
    try:
        # Önce bu cihazla kayıtlı kullanıcı var mı bak
        user = await prisma.user.find_unique(
            where={"deviceId": x_device_id},
            include={"vehicles": True}
        )
        
        # Eğer kullanıcı yoksa, SESSİZ KAYIT (Silent Register) yap
        if not user:
            print(f"Silent registration starting for device: {x_device_id}")
            # Benzersiz bir e-posta üret (cihaz id bazlı, güvenli karakterlerle)
            safe_id = "".join(c for c in x_device_id if c.isalnum())
            dummy_email = f"u_{safe_id[:12]}@stitched.app"
            
            # Email çakışması kontrolü (çok nadir ama güvenlik için)
            existing_email = await prisma.user.find_unique(where={"email": dummy_email})
            if existing_email:
                dummy_email = f"u_{safe_id[:12]}_{datetime.now().strftime('%M%S')}@stitched.app"

            # Şifreyi 72 byte limitine göre kırp
            dummy_password_raw = x_device_id[:72]
            hashed_password = pwd_context.hash(dummy_password_raw)
            
            print(f"Creating user for email: {dummy_email}")
            user = await prisma.user.create(
                data={
                    "email": dummy_email,
                    "password": hashed_password,
                    "name": "Stitched Driver",
                    "deviceId": x_device_id
                }
            )
            
            # Default araç ekle
            print(f"Creating default vehicle for user: {user.id}")
            await prisma.vehicle.create(
                data={
                    "brand": "BMW",
                    "model": "1.16",
                    "isDefault": True,
                    "userId": user.id
                }
            )
            
            # İlişkileri ile beraber kullanıcıyı tekrar yükle
            user = await prisma.user.find_unique(
                where={"id": user.id}, 
                include={"vehicles": True}
            )
            print("Silent registration completed successfully")
            
        if not user:
            raise HTTPException(status_code=500, detail="Kullanıcı bulunamadı veya oluşturulamadı.")

        default_vehicle = next((v for v in user.vehicles if v.isDefault), user.vehicles[0] if user.vehicles else None)
        
        access_token = create_access_token(data={"sub": user.id})
        if not access_token:
            raise HTTPException(status_code=500, detail="JWT token üretilemedi.")

        return {
            "status": "success",
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "email": user.email,
                "name": user.name
            },
            "defaultVehicleId": default_vehicle.id if default_vehicle else None
        }
    except Exception as e:
        print(f"DEVICE AUTO-LOGIN CRITICAL ERROR: {str(e)}")
        traceback.print_exc()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Sistem hatası: {str(e)}")

# --- KORUMALI ENDPOINTLER ---

@app.get("/trips")
async def get_trips(userId: Optional[str] = None, current_user_id: str = Depends(get_current_user)):
    active_id = userId if (userId and userId != "undefined") else current_user_id
    if active_id != current_user_id:
        raise HTTPException(status_code=403, detail="Yetkisiz erişim.")
    try:
        return await prisma.trip.find_many(
            where={"userId": active_id, "isActive": False},
            include={"locations": True},
            order={"startTime": "desc"}
        )
    except Exception as e:
        print(f"GET TRIPS ERROR: {e}")
        raise HTTPException(status_code=500, detail="Yolculuklar çekilemedi.")

@app.post("/trips/start")
async def start_trip(data: TripStart, current_user_id: str = Depends(get_current_user)):
    if data.userId != current_user_id:
        raise HTTPException(status_code=403, detail="Yetkisiz işlem.")
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
        raise HTTPException(status_code=500, detail="Yolculuk başlatılamadı.")

@app.patch("/trips/end/{trip_id}")
async def end_trip(trip_id: str, data: TripEnd, current_user_id: str = Depends(get_current_user)):
    # Trip sahibini kontrol et
    trip = await prisma.trip.find_unique(where={"id": trip_id})
    if not trip or trip.userId != current_user_id:
        raise HTTPException(status_code=403, detail="Yetkisiz işlem.")
        
    try:
        return await prisma.trip.update(
            where={"id": trip_id},
            data={
                "isActive": False,
                "endTime": datetime.now(),
                "endKm": data.endKm,
                "distanceKm": data.distanceKm
            }
        )
    except Exception as e:
        print(f"END TRIP ERROR: {e}")
        raise HTTPException(status_code=500, detail="Yolculuk sonlandırılamadı.")

@app.post("/fuel/add")
async def add_fuel(data: FuelCreate, current_user_id: str = Depends(get_current_user)):
    if data.userId != current_user_id:
        raise HTTPException(status_code=403, detail="Yetkisiz işlem.")
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
        print(f"FUEL ADD ERROR: {e}")
        raise HTTPException(status_code=500, detail="Yakıt kaydı eklenemedi.")

@app.get("/dashboard/summary")
async def get_summary(userId: Optional[str] = None, current_user_id: str = Depends(get_current_user)):
    active_id = userId if (userId and userId != "undefined") else current_user_id
    if active_id != current_user_id:
        raise HTTPException(status_code=403, detail="Yetkisiz erişim.")
    try:
        trips = await prisma.trip.find_many(where={"userId": active_id, "isActive": False})
        fuel = await prisma.fuellog.find_many(where={"userId": active_id})
        
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
        print(f"SUMMARY ERROR: {e}")
        raise HTTPException(status_code=500, detail="Özet veriler çekilemedi.")

# --- KONUM KAYIT (PERFORMANS İÇİN TOKENSIZ) ---

@app.post("/trips/{trip_id}/location")
async def add_location(trip_id: str, data: LocationPointCreate):
    try:
        return await prisma.locationpoint.create(
            data={
                "latitude": data.latitude,
                "longitude": data.longitude,
                "timestamp": data.timestamp if data.timestamp else datetime.now(),
                "tripId": trip_id
            }
        )
    except Exception as e:
        print(f"LOCATION ERROR: {e}")
        raise HTTPException(status_code=500, detail="Konum kaydedilemedi.")

@app.post("/trips/{trip_id}/locations/bulk")
async def add_locations_bulk(trip_id: str, data: BulkLocationUpdate):
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
        print(f"BULK LOCATION ERROR: {e}")
        raise HTTPException(status_code=500, detail="Toplu konum kaydı başarısız.")

@app.on_event("startup")
async def startup():
    await prisma.connect()

@app.on_event("shutdown")
async def shutdown():
    await prisma.disconnect()
