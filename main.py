from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import random
from sqlalchemy import create_engine, Column, Integer, String, Float
from sqlalchemy.orm import sessionmaker, declarative_base
import requests
import base64
import os

EBAY_CLIENT_ID = os.getenv("EBAY_CLIENT_ID")
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET")

def get_ebay_token():
    credentials = f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()

    url = "https://api.ebay.com/identity/v1/oauth2/token"

    headers = {
        "Authorization": f"Basic {encoded_credentials}",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    data = {
        "grant_type": "client_credentials",
        "scope": "https://api.ebay.com/oauth/api_scope"
    }

    response = requests.post(url, headers=headers, data=data)
    json_response = response.json()

    print("eBay token response:", json_response)

    if "access_token" not in json_response:
        raise Exception(f"Failed to get token: {json_response}")

    return json_response["access_token"]

DATABASE_URL = "sqlite:///./prices.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class Price(Base):
    __tablename__ = "prices"

    id = Column(Integer, primary_key=True, index=True)
    product_name = Column(String, index=True)
    retailer = Column(String)
    price = Column(Float)


class TrackedProduct(Base):
    __tablename__ = "tracked_products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)

Base.metadata.create_all(bind=engine)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
gpu_data = [
    {"product_name": "RTX 4070", "retailer": "Amazon", "price": 549},
    {"product_name": "RTX 4070", "retailer": "eBay", "price": 529},
    {"product_name": "RTX 4070", "retailer": "Newegg", "price": 539},
    {"product_name": "RTX 4080", "retailer": "Amazon", "price": 999},
    {"product_name": "RTX 4080", "retailer": "eBay", "price": 949},
]
@app.get("/")
def home():
    return {"message": "Deal API is running"}


@app.get("/gpu")
def get_gpu_prices(search: str):
    token = get_ebay_token()

    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"

    headers = {
        "Authorization": f"Bearer {token}"
    }

    params = {
        "q": search,
        "limit": 5
    }

    response = requests.get(url, headers=headers, params=params)
    data = response.json()

    db = SessionLocal()
    results = []

    if "itemSummaries" in data:
        for item in data["itemSummaries"]:
            title = item.get("title", "No Title")
            price_value = float(item["price"]["value"])

            # Save to database
            new_price = Price(
                product_name=title,
                retailer="eBay",
                price=price_value
            )
            db.add(new_price)

            results.append({
                "product_name": title,
                "retailer": "eBay",
                "price": price_value
            })

    db.commit()
    db.close()

    sorted_results = sorted(results, key=lambda x: x["price"])
    return sorted_results

@app.get("/history")
def get_price_history():
    db = SessionLocal()
    prices = db.query(Price).all()
    db.close()

    return [
        {
            "product_name": p.product_name,
            "retailer": p.retailer,
            "price": p.price
        }
        for p in prices
    ]

@app.post("/track")
def add_tracked_product(name: str):
    db = SessionLocal()

    existing = db.query(TrackedProduct).filter(TrackedProduct.name == name).first()
    if existing:
        db.close()
        return {"message": "Product already tracked"}

    new_product = TrackedProduct(name=name)
    db.add(new_product)
    db.commit()
    db.close()

    return {"message": f"{name} added to tracking"}

@app.post("/update-tracked")
def update_tracked_products():
    db = SessionLocal()
    tracked_products = db.query(TrackedProduct).all()

    token = get_ebay_token()
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"

    headers = {
        "Authorization": f"Bearer {token}"
    }

    total_saved = 0

    for product in tracked_products:
        params = {
            "q": product.name,
            "limit": 5
        }

        response = requests.get(url, headers=headers, params=params)
        data = response.json()

        if "itemSummaries" in data:
            for item in data["itemSummaries"]:
                title = item.get("title", "No Title")
                price_value = float(item["price"]["value"])

                new_price = Price(
                    product_name=title,
                    retailer="eBay",
                    price=price_value
                )
                db.add(new_price)
                total_saved += 1

    db.commit()
    db.close()

    return {"message": f"Updated tracked products. Saved {total_saved} price entries."}

scheduler = BackgroundScheduler()

def scheduled_update():
    print("Running scheduled update...")
    update_tracked_products()

scheduler.add_job(scheduled_update, "interval", minutes=10)
scheduler.start()