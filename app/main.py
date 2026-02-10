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
# .env'den gelen değeri güvenli bir şekilde int'e çevir
try:
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "43200"))
except:
    ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login", auto_error=False)

app = FastAPI(title="OtoLog API - Diagnostics V5")

# --- GLOBAL HATA YAKALAYICI (Tüm 500 hatalarını yakalayıp içeriğini döndürür) ---
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"CRITICAL ERROR CAUGHT: {str(exc)}")
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": f"Server Error: {str(exc)}", "trace": traceback.format_exc()}
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
        raise HTTPException(status_code=401, detail="Oturum yok.")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id: raise HTTPException(status_code=401)
        return user_id
    except:
        raise HTTPException(status_code=401, detail="Geçersiz oturum.")

# --- ENDPOINTLER ---

@app.get("/health")
async def health():
    return {"status": "ok", "version": "v5-diagnostics", "timestamp": datetime.now()}

@app.post("/device-login")
async def device_login(request: Request, x_device_id: Optional[str] = Header(None, alias="X-Device-ID")):
    # Header alias ekledik çünkü iOS büyük/küçük harf seçebilir
    dev_id = x_device_id or request.headers.get("x-device-id")
    
    if not dev_id:
        raise HTTPException(status_code=400, detail="Device ID (X-Device-ID) header'da bulunamadı.")
        
    print(f"Device Login Request for ID: {dev_id}")
    
    prisma = Prisma()
    await prisma.connect()
    
    try:
        user = await prisma.user.find_unique(
            where={"deviceId": dev_id},
            include={"vehicles": True}
        )
        
        if not user:
            print("User not found, starting silent registration...")
            # Güvenli email
            safe_id = "".join(c for c in dev_id if c.isalnum())[:12]
            dummy_email = f"u_{safe_id}_{datetime.now().strftime('%M%S')}@stitched.app"
            dummy_password = pwd_context.hash(dev_id[:72])
            
            user = await prisma.user.create(
                data={
                    "email": dummy_email,
                    "password": dummy_password,
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
            print("Silent registration success.")

        default_vehicle = next((v for v in user.vehicles if v.isDefault), user.vehicles[0] if user.vehicles else None)
        token = create_access_token(data={"sub": user.id})
        
        return {
            "status": "success",
            "access_token": token,
            "user": {"id": user.id, "email": user.email, "name": user.name},
            "defaultVehicleId": default_vehicle.id if default_vehicle else None
        }
    finally:
        await prisma.disconnect()

# --- DİĞER KORUMALI ENDPOINTLER ---

@app.get("/dashboard/summary")
async def get_summary(userId: Optional[str] = None, current_user_id: str = Depends(get_current_user)):
    active_id = userId if (userId and userId != "undefined") else current_user_id
    if active_id != current_user_id: raise HTTPException(status_code=403)
    
    p = Prisma(); await p.connect()
    try:
        trips = await p.trip.find_many(where={"userId": active_id, "isActive": False})
        fuel = await p.fuellog.find_many(where={"userId": active_id})
        
        t_km = sum(t.distanceKm or 0 for t in trips)
        t_price = sum(f.totalPrice for f in fuel)
        t_liters = sum(f.liters for f in fuel)
        
        return {
            "total_km": round(t_km, 2),
            "total_spend": round(t_price, 2),
            "avg_consumption": round((t_liters / (t_km / 100)), 2) if t_km > 0 else 0,
            "trip_count": len(trips)
        }
    finally: await p.disconnect()

@app.on_event("startup")
async def startup():
    # Global prisma instance startup'da bağlanır (yukarıdaki endpoint bağımsız v5 denemesi için)
    pass
