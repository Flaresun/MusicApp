from fastapi import FastAPI

app = FastAPI(
    title="MusicAPI",
    version="1.0.0"
)

@app.get("/health")
def health_check():
    return {"status": "healthy"}

@app.get("/")
def read_root():
    return {"message": "Welcome to the Modular Monolith API"}