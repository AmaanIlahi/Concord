from fastapi import FastAPI

from app.routers import datasets, eval, match

app = FastAPI(title="Concord")

app.include_router(datasets.router)
app.include_router(match.router)
app.include_router(eval.router)
