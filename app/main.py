from fastapi import FastAPI, HTTPException, Header, Depends, status, Request
from fastapi.responses import JSONResponse
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
try:
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "43200"))
except:
    ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30

# Bcrypt'teki 72 byte bug'ını aşmak için pbkdf2_sha256'yı ana şema yaptık.
pwd_context = CryptContext(schemes=["pbkdf2_sha256", "bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login", auto_error=False)

app = FastAPI(title="OtoLog API - Engine Fix V6")
prisma = Prisma() # Global Prisma instance

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"CRITICAL ERROR: {str(exc)}")
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": f"Engine Error: {str(exc)}", "trace": traceback.format_exc()}
    )

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- MODELLER ---
class LocationPointCreate(BaseModel):
    latitude: float
    longitude: float
    timestamp: Optional[datetime] = None

class BulkLocationUpdate(BaseModel):
    locations: List[LocationPointCreate]

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
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    if not token:
        raise HTTPException(status_code=401, detail="Auth token missing")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id: raise HTTPException(status_code=401)
        return user_id
    except:
        raise HTTPException(status_code=401, detail="Invalid session")

# --- ENDPOINTLER ---

@app.get("/health")
async def health():
    return {"status": "ok", "version": "v6-engine-fix", "timestamp": datetime.now()}

@app.post("/device-login")
async def device_login(request: Request, x_device_id: Optional[str] = Header(None, alias="X-Device-ID")):
    dev_id = x_device_id or request.headers.get("x-device-id")
    if not dev_id:
        raise HTTPException(status_code=400, detail="X-Device-ID header missing")
        
    try:
        if not prisma.is_connected():
            await prisma.connect()
            
        user = await prisma.user.find_unique(
            where={"deviceId": dev_id},
            include={"vehicles": True}
        )
        
        if not user:
            print(f"Auto-registering device: {dev_id}")
            safe_id = "".join(c for c in dev_id if c.isalnum())[:10]
            email = f"u_{safe_id}_{datetime.now().strftime('%M%S')}@stitched.app"
            # SHA256 kullandığımız için artık uzunluk hatası yok
            hashed_pwd = pwd_context.hash(dev_id) 
            
            user = await prisma.user.create(
                data={
                    "email": email,
                    "password": hashed_pwd,
                    "name": "Stitched Driver",
                    "deviceId": dev_id
                }
            )
            
            await prisma.vehicle.create(
                data={
                    "brand": "BMW",
                    "model": "1.16",
                    "isDefault": True,
                    "userId": user.id
                }
            )
            user = await prisma.user.find_unique(where={"id": user.id}, include={"vehicles": True})

        default_vehicle = next((v for v in user.vehicles if v.isDefault), user.vehicles[0] if user.vehicles else None)
        token = create_access_token(data={"sub": user.id})
        
        return {
            "status": "success",
            "access_token": token,
            "user": {"id": user.id, "email": user.email, "name": user.name},
            "defaultVehicleId": default_vehicle.id if default_vehicle else None
        }
    except Exception as e:
        traceback.print_exc()
        raise e

@app.get("/dashboard/summary")
async def get_summary(userId: Optional[str] = None, current_user_id: str = Depends(get_current_user)):
    active_id = userId if (userId and userId != "undefined") else current_user_id
    if active_id != current_user_id: raise HTTPException(status_code=403)
    
    try:
        if not prisma.is_connected(): await prisma.connect()
        trips = await prisma.trip.find_many(where={"userId": active_id, "isActive": False})
        fuel = await prisma.fuellog.find_many(where={"userId": active_id})
        
        t_km = sum(t.distanceKm or 0 for t in trips)
        t_price = sum(f.totalPrice for f in fuel)
        t_liters = sum(f.liters for f in fuel)
        
        return {
            "total_km": round(t_km, 2),
            "total_spend": round(t_price, 2),
            "avg_consumption": round((t_liters / (t_km / 100)), 2) if t_km > 0 else 0,
            "trip_count": len(trips)
        }
    except Exception as e:
        traceback.print_exc()
        raise e

@app.post("/trips/start")
async def start_trip(data: TripStart, current_user_id: str = Depends(get_current_user)):
    if data.userId != current_user_id: raise HTTPException(status_code=403)
    try:
        if not prisma.is_connected(): await prisma.connect()
        return await prisma.trip.create(
            data={
                "userId": data.userId,
                "vehicleId": data.vehicleId,
                "startKm": data.startKm,
                "isActive": True
            }
        )
    except Exception as e:
        traceback.print_exc()
        raise e

@app.on_event("startup")
async def startup():
    if not prisma.is_connected():
        await prisma.connect()

@app.on_event("shutdown")
async def shutdown():
    if prisma.is_connected():
        await prisma.disconnect()
