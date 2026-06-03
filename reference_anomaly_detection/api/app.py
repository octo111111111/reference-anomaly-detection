from __future__ import annotations

import logging

from fastapi import FastAPI

from reference_anomaly_detection.api.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(
    title="Reference Anomaly Detection API",
    description="参考文献异常检测微服务：DOI 校验与撤稿检测",
    version="0.5.0",
)
app.include_router(router)
