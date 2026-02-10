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

import requests

# .env dosyasını yükle
load_dotenv()

# --- GÜVENLİK AYARLARI ---
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "7b8d4b7d-a7c7-4824-8d74-7e6489378878-STITCHED-OtoLog")
ALGORITHM = "HS256"
try:
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", str(60 * 24 * 30)))
except:
    ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30

app = FastAPI(title="OtoLog API - Car Search V8")
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
    return {"status": "ok", "version": "v9-car-add-db", "timestamp": datetime.now()}

@app.get("/cars/makes")
async def get_car_makes():
    if not prisma.is_connected(): await prisma.connect()
    try:
        makes = await prisma.carlibrary.find_many(
            distinct=['brand'],
            order={'brand': 'asc'}
        )
        return [m.brand for m in makes if m.brand]
    except Exception as e:
        print(f"Error fetching makes: {e}")
        return []

@app.get("/cars/models")
async def get_car_models(make: str):
    if not prisma.is_connected(): await prisma.connect()
    try:
        models = await prisma.carlibrary.find_many(
            where={'brand': {'equals': make, 'mode': 'insensitive'}},
            distinct=['model'],
            order={'model': 'asc'}
        )
        return [m.model for m in models if m.model]
    except Exception as e:
        print(f"Error fetching models: {e}")
        return []

@app.get("/cars/years")
async def get_car_years(make: str, model: str):
    if not prisma.is_connected(): await prisma.connect()
    try:
        years = await prisma.carlibrary.find_many(
            where={
                'brand': {'equals': make, 'mode': 'insensitive'},
                'model': {'equals': model, 'mode': 'insensitive'}
            },
            distinct=['year'],
            order={'year': 'desc'}
        )
        return [str(y.year) for y in years if y.year]
    except Exception as e:
        print(f"Error fetching years: {e}")
        return []

@app.get("/cars/search-and-save")
async def search_and_save(make: str, model: str, year: int):
    # 1. Önce kendi DB'mizde var mı bak?
    if not prisma.is_connected(): await prisma.connect()
    
    existing_car = await prisma.carlibrary.find_first(
        where={
            "brand": {"equals": make, "mode": "insensitive"},
            "model": {"equals": model, "mode": "insensitive"},
            "year": year
        }
    )
    
    if existing_car:
        return existing_car

    # 2. DB'de yoksa Ninja API'ye git
    headers = {'X-Api-Key': 'jgIJMKCsES3XVItWOMmqrjv6OyQAGIMwVQ7nde05'}
    url = f'https://api.api-ninjas.com/v1/cars?make={make}&model={model}&year={year}'
    
    print(f"Searching for car: {make} {model} {year} at {url}")

    try:
        response = requests.get(url, headers=headers, timeout=10)
        print(f"Ninja API Status: {response.status_code}")
        
        if response.status_code == 200:
            data_list = response.json()
            if not data_list:
                print("Ninja API returned empty list.")
                raise HTTPException(status_code=404, detail="Araç veritabanında bulunamadı.")
                 
            api_data = data_list[0]
            print(f"Car found: {api_data}")

            # MPG -> L/100km formülü: 235.21 / MPG
            mpg = api_data.get('combination_mpg')
            consumption = round(235.21 / float(mpg), 2) if mpg else None
            
            new_car = await prisma.carlibrary.create(
                data={
                    "brand": api_data.get('make', make).capitalize(),
                    "model": api_data.get('model', model).capitalize(),
                    "year": year,
                    "fuelType": api_data.get('fuel_type'),
                    "transmission": api_data.get('transmission'),
                    "cylinders": api_data.get('cylinders'),
                    "combinationMpg": float(mpg) if mpg else None,
                    "avgConsumption": consumption
                }
            )
            return new_car
    except Exception as e:
        print(f"CAR API ERROR: {e}")
        traceback.print_exc()
        if isinstance(e, HTTPException): raise e
        
    raise HTTPException(status_code=404, detail="Araç bulunamadı.")

# --- ARAÇ YÖNETİMİ ENDPOINTLERİ ---

@app.get("/vehicles")
async def get_my_vehicles(current_user_id: str = Depends(get_current_user)):
    try:
        if not prisma.is_connected(): await prisma.connect()
        return await prisma.vehicle.find_many(
            where={"userId": current_user_id},
            order={"createdAt": "desc"}
        )
    except Exception as e:
        print(f"GET VEHICLES ERROR: {e}")
        raise HTTPException(status_code=500, detail="Araçlarınız listelenemedi.")

class VehicleAdd(BaseModel):
    brand: str
    model: str
    year: int
    fuelType: Optional[str] = None
    transmission: Optional[str] = None
    avgConsumption: Optional[float] = None
    
@app.post("/vehicles/add")
async def add_vehicle(data: VehicleAdd, current_user_id: str = Depends(get_current_user)):
    try:
        if not prisma.is_connected(): await prisma.connect()
        
        # Eğer bu ilk araçsa direct default yap
        count = await prisma.vehicle.count(where={"userId": current_user_id})
        is_default = (count == 0)
        
        new_vehicle = await prisma.vehicle.create(
            data={
                "userId": current_user_id,
                "brand": data.brand,
                "model": data.model,
                "year": data.year,
                "fuelType": data.fuelType,
                "transmission": data.transmission,
                "avgConsumption": data.avgConsumption,
                "isDefault": is_default
            }
        )
        return new_vehicle
    except Exception as e:
        print(f"ADD VEHICLE ERROR: {e}")
        raise HTTPException(status_code=500, detail="Araç eklenemedi.")

@app.patch("/vehicles/{vehicle_id}/default")
async def set_default_vehicle(vehicle_id: str, current_user_id: str = Depends(get_current_user)):
    try:
        if not prisma.is_connected(): await prisma.connect()
        
        async with prisma.tx() as transaction:
            # 1. Önce kullanıcının tüm araçlarının default'unu false yap
            await transaction.vehicle.update_many(
                where={"userId": current_user_id},
                data={"isDefault": False}
            )
            
            # 2. Seçilen aracı true yap
            updated = await transaction.vehicle.update(
                where={"id": vehicle_id},
                data={"isDefault": True}
            )
            return updated
    except Exception as e:
        print(f"SET DEFAULT ERROR: {e}")
        # Transaction hatası oluşursa
        raise HTTPException(status_code=500, detail="Varsayılan araç güncellenemedi.")

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
