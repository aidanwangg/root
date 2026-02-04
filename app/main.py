
from fastapi import FastAPI
from app.db import engine


app = FastAPI()


@app.on_event("startup")
def startup():
    """
    tbd
    """
    with engine.connect() as conn:
        print("✅ Database connection successful")


@app.get("/health")
def health():
    """
    tbd
    """
    return {"status": "ok"}
