from fastapi import FastAPI
from app.core.wallapop_alert_worker import start_wallapop_alert_worker, stop_wallapop_alert_worker
from app.router import router

app = FastAPI()
app.include_router(router)


@app.on_event("startup")
async def startup_event():
    start_wallapop_alert_worker()


@app.on_event("shutdown")
async def shutdown_event():
    stop_wallapop_alert_worker()
