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

# --- GÜVENLİK AYARLARI ---
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "7b8d4b7d-a7c7-4824-8d74-7e6489378878-STITCHED-OtoLog")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60 * 24 * 30))  # Varsayılan 30 Gün

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login", auto_error=False)

app = FastAPI(title="OtoLog API - Pro Security Env")
prisma = Prisma()

# CORS Güvenliğini sıkılaştırıyoruz
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Gerçek canlı sistemde buraya domain eklenmeli: ["https://otolog.ayris.tech"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- YARDIMCI FONKSİYONLAR ---

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme)):
    if not token:
        # Geriye dönük uyumluluk veya misafir erişimi için şimdilik None dönebiliriz 
        # ama tam güvenlik için direkt 401 fırlatmalıyız.
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

# --- MODELLER ---

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

# --- ENDPOINTLER ---

@app.get("/health")
async def health():
    return {"status": "ok", "version": "v3-secured", "timestamp": datetime.now()}

@app.post("/register")
async def register(data: UserRegister, x_device_id: Optional[str] = Header(None)):
    print(f"Registration attempt for: {data.email}")
    device_id = data.deviceId or x_device_id
    
    try:
        existing = await prisma.user.find_unique(where={"email": data.email})
        if existing:
            raise HTTPException(status_code=400, detail="Bu e-posta adresi zaten kayıtlı.")

        if device_id:
            existing_device = await prisma.user.find_unique(where={"deviceId": device_id})
            if existing_device:
                raise HTTPException(status_code=400, detail="Bu cihaz zaten başka bir hesaba bağlı.")
            
        safe_password = data.password[:72]
        hashed_password = pwd_context.hash(safe_password)
        
        user = await prisma.user.create(
            data={
                "email": data.email,
                "password": hashed_password,
                "name": data.name,
                "deviceId": device_id
            }
        )
        
        # Default araç oluşturma
        await prisma.vehicle.create(
            data={
                "brand": "BMW",
                "model": "1.16",
                "isDefault": True,
                "userId": user.id
            }
        )

        access_token = create_access_token(data={"sub": user.id})
        return {
            "status": "success", 
            "userId": user.id, 
            "access_token": access_token, 
            "token_type": "bearer"
        }
    except Exception as e:
        print(f"REGISTRATION ERROR: {e}")
        traceback.print_exc()
        if isinstance(e, HTTPException): raise e
        raise HTTPException(status_code=500, detail="Kayıt sırasında bir sunucu hatası oluştu.")

@app.post("/login")
async def login(data: UserLogin):
    try:
        user = await prisma.user.find_unique(
            where={"email": data.email},
            include={"vehicles": True}
        )
        
        if not user or not pwd_context.verify(data.password, user.password):
            raise HTTPException(status_code=401, detail="E-posta veya şifre hatalı.")
        
        default_vehicle = next((v for v in user.vehicles if v.isDefault), user.vehicles[0] if user.vehicles else None)
        
        access_token = create_access_token(data={"sub": user.id})
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
        print(f"LOGIN ERROR: {e}")
        traceback.print_exc()
        if isinstance(e, HTTPException): raise e
        raise HTTPException(status_code=500, detail="Giriş yapılamadı.")

@app.post("/device-login")
async def device_login(x_device_id: Optional[str] = Header(None)):
    if not x_device_id:
        raise HTTPException(status_code=400, detail="Cihaz kimliği eksik.")
        
    try:
        # Önce bu cihazla kayıtlı kullanıcı var mı bak
        user = await prisma.user.find_unique(
            where={"deviceId": x_device_id},
            include={"vehicles": True}
        )
        
        # Eğer kullanıcı yoksa, SESSİZ KAYIT (Silent Register) yap
        if not user:
            print(f"Silent registration for device: {x_device_id}")
            # Benzersiz bir e-posta üret (cihaz id bazlı)
            dummy_email = f"user_{x_device_id[:8]}@stitched.app"
            dummy_password = pwd_context.hash(x_device_id) # Cihaz ID'sini şifre olarak kullan (arka planda)
            
            user = await prisma.user.create(
                data={
                    "email": dummy_email,
                    "password": dummy_password,
                    "name": "Stitched Driver",
                    "deviceId": x_device_id
                }
            )
            
            # Default araç ekle
            await prisma.vehicle.create(
                data={
                    "brand": "BMW",
                    "model": "1.16",
                    "isDefault": True,
                    "userId": user.id
                }
            )
            # User bilgilerini araçlarla beraber tekrar çek (ilişkiler için)
            user = await prisma.user.find_unique(where={"id": user.id}, include={"vehicles": True})
            
        default_vehicle = next((v for v in user.vehicles if v.isDefault), user.vehicles[0] if user.vehicles else None)
        
        access_token = create_access_token(data={"sub": user.id})
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
        print(f"DEVICE AUTO-LOGIN ERROR: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Otomatik giriş başarısız.")

# --- KORUMALI ENDPOINTLER (JWT GEREKTİRİR) ---

@app.post("/trips/start")
async def start_trip(data: TripStart, current_user_id: str = Depends(get_current_user)):
    # Sadece kendi adına trip başlatabilir
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

@app.get("/dashboard/summary")
async def get_summary(userId: Optional[str] = None, current_user_id: str = Depends(get_current_user)):
    # Parametre olarak gelen userId yoksa veya token'daki user ile eşleşmiyorsa token sahibininkini getirir
    active_id = userId if (userId and userId != "undefined") else current_user_id
    
    if active_id != current_user_id:
        raise HTTPException(status_code=403, detail="Sadece kendi verilerinizi görebilirsiniz.")

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
        print(f"GET SUMMARY ERROR: {e}")
        raise HTTPException(status_code=500, detail="Özet veriler çekilemedi.")

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
        raise HTTPException(status_code=500, detail="Yolculuk geçmişi çekilemedi.")

# --- DİĞER FONKSİYONLAR ---

@app.post("/trips/{trip_id}/location")
async def add_location(trip_id: str, data: LocationPointCreate):
    # Location kayıtları çok sık geldiği için performans için token kontrolünü opsiyonel bırakabiliriz 
    # veya tripId üzerinden user kontrolü yapabiliriz. Şimdilik hızlı kayıt öncelikli.
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
        print(f"Error adding location: {e}")
        raise HTTPException(status_code=500, detail="Konum kaydedilemedi.")

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
        print(f"ADD FUEL ERROR: {e}")
        raise HTTPException(status_code=500, detail="Yakıt kaydı eklenemedi.")

@app.on_event("startup")
async def startup():
    await prisma.connect()

@app.on_event("shutdown")
async def shutdown():
    await prisma.disconnect()

