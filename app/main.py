from fastapi import FastAPI, HTTPException, Header, Depends, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prisma import Prisma
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
from jose import JWTError, jwt
import traceback
import os
from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv()

# --- GÜVENLİK AYARLARI ---
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "7b8d4b7d-a7c7-4824-8d74-7e6489378878-STITCHED-OtoLog")
ALGORITHM = "HS256"
try:
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", str(60 * 24 * 30)))
except:
    ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30

app = FastAPI(title="OtoLog API - Zero-Auth V7")
prisma = Prisma()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

class LocationPointCreate(BaseModel):
    latitude: float
    longitude: float
    timestamp: Optional[datetime] = None

# --- YARDIMCI FONKSİYONLAR ---

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Header(None, alias="Authorization")):
    if not token or not token.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Yetkisiz erişim: Token bulunamadı.")
    
    actual_token = token.split(" ")[1]
    try:
        payload = jwt.decode(actual_token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Geçersiz token.")
        return user_id
    except JWTError:
        raise HTTPException(status_code=401, detail="Oturum süresi dolmuş veya geçersiz.")

# --- ENDPOINTLER ---

@app.get("/health")
async def health():
    return {"status": "ok", "version": "v7-zero-auth", "timestamp": datetime.now()}

@app.post("/device-login")
async def device_login(request: Request, x_device_id: Optional[str] = Header(None, alias="X-Device-ID")):
    dev_id = x_device_id or request.headers.get("x-device-id")
    
    if not dev_id:
        raise HTTPException(status_code=400, detail="Cihaz kimliği (X-Device-ID) eksik.")
        
    try:
        if not prisma.is_connected():
            await prisma.connect()
            
        # Kullanıcıyı cihaz ID'si ile ara
        user = await prisma.user.find_unique(
            where={"deviceId": dev_id},
            include={"vehicles": True}
        )
        
        # Eğer böyle bir kullanıcı yoksa, sadece cihaz ID'si ile oluştur
        if not user:
            print(f"Creating zero-auth user for device: {dev_id}")
            user = await prisma.user.create(
                data={
                    "deviceId": dev_id,
                    "name": "Sürücü"
                }
            )
            
            # İlk araç kaydını otomatik yap (BMW 1.16)
            await prisma.vehicle.create(
                data={
                    "brand": "BMW",
                    "model": "1.16",
                    "isDefault": True,
                    "userId": user.id
                }
            )
            # Bilgileri tekrar çek
            user = await prisma.user.find_unique(where={"id": user.id}, include={"vehicles": True})
            print("Zero-auth user and default vehicle created.")

        # Varsayılan aracı belirle
        default_vehicle = next((v for v in user.vehicles if v.isDefault), user.vehicles[0] if user.vehicles else None)
        
        # Güvenli JWT üret (Identity = User ID)
        token = create_access_token(data={"sub": user.id})
        
        return {
            "status": "success",
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "name": user.name
            },
            "defaultVehicleId": default_vehicle.id if default_vehicle else None
        }
    except Exception as e:
        print(f"DEVICE LOGIN CRITICAL ERROR: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Otomatik giriş sistemi şu an kapalı.")

# --- DİĞER KORUMALI ENDPOINTLER ---

@app.get("/dashboard/summary")
async def get_summary(userId: Optional[str] = None, current_user_id: str = Depends(get_current_user)):
    # Güvenlik Kontrolü: Sadece kendi verisini görebilir
    active_id = userId if (userId and userId != "undefined") else current_user_id
    if active_id != current_user_id:
        raise HTTPException(status_code=403, detail="Yetkisiz veri erişimi.")
        
    try:
        if not prisma.is_connected(): await prisma.connect()
        trips = await prisma.trip.find_many(where={"userId": active_id, "isActive": False})
        fuel = await prisma.fuellog.find_many(where={"userId": active_id})
        
        total_km = sum(t.distanceKm or 0 for t in trips)
        total_spend = sum(f.totalPrice for f in fuel)
        total_liters = sum(f.liters for f in fuel)
        
        return {
            "total_km": round(total_km, 2),
            "total_spend": round(total_spend, 2),
            "avg_consumption": round((total_liters / (total_km / 100)), 2) if total_km > 0 else 0,
            "trip_count": len(trips)
        }
    except Exception as e:
        print(f"SUMMARY ERROR: {e}")
        raise HTTPException(status_code=500, detail="Özet raporu hazırlanamadı.")

@app.get("/trips")
async def get_trips(userId: Optional[str] = None, current_user_id: str = Depends(get_current_user)):
    active_id = userId if (userId and userId != "undefined") else current_user_id
    if active_id != current_user_id:
        raise HTTPException(status_code=403, detail="Yetkisiz erişim.")
    try:
        if not prisma.is_connected(): await prisma.connect()
        return await prisma.trip.find_many(
            where={"userId": active_id, "isActive": False},
            order={"startTime": "desc"}
        )
    except Exception as e:
        print(f"TRIPS ERROR: {e}")
        raise HTTPException(status_code=500, detail="Yolculuk geçmişi alınamadı.")

@app.on_event("startup")
async def startup():
    if not prisma.is_connected():
        await prisma.connect()

@app.on_event("shutdown")
async def shutdown():
    if prisma.is_connected():
        await prisma.disconnect()
