from fastapi import FastAPI
from .routers import items, agents

app = FastAPI()

app.include_router(items.router)
app.include_router(agents.router)


@app.get("/")
async def root():
    return {"message": "Hello Bigger Applications!"}
