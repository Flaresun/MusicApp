from fastapi import FastAPI
from app.routers.api_v1 import v1_router

# Docs : http://localhost:8000/docs#/
app = FastAPI(
    title="MusicAPI",
    version="1.0.0"
)

app.include_router(v1_router, prefix="/api/v1")

@app.get("/health")
def health_check():
    return {"status": "healthy"}

@app.get("/")
def read_root():
    return {"message": "Welcome to the MusicAPI app"}