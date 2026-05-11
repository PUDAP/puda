from fastapi import FastAPI
from .routers import agents

app = FastAPI()
app.include_router(agents.router)

@app.get("/")
async def root():
    return {"message": "Welcome to the PUDA backend!"}
