import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request, Response

from app import registration_service as service
from app.os_layer.layer_config import OSLayerConfig
from app.os_layer.request_pipeline import QUEUE_FULL, SHUTTING_DOWN, OSConcurrencyLayer
from app.schemas import RegistrationRequest, RegistrationResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

HTTP_STATUS = {
    service.SUCCESS: 201,
    service.DUPLICATE: 409,
    service.FULL: 409,
    service.STUDENT_NOT_FOUND: 404,
    service.SECTION_NOT_FOUND: 404,
    service.ERROR: 500,
    # PROVISIONAL. The Master MD leaves the response for a full queue undecided.
    # 503 is only a placeholder so the request gets an answer; change it here once decided.
    QUEUE_FULL: 503,
    SHUTTING_DOWN: 503,
}

router = APIRouter()


@router.post("/registrations", response_model=RegistrationResponse)
async def create_registration(request: RegistrationRequest, response: Response, http_request: Request):
    # The HTTP layer only hands the request over and waits for the answer. The queue,
    # the workers and the database work all happen on other threads (see os_layer/).
    layer = http_request.app.state.os_layer
    result = await asyncio.wrap_future(layer.submit(request.student_id, request.section_id))
    response.status_code = HTTP_STATUS[result.code]
    return RegistrationResponse(success=result.success, message=result.message)


@router.get("/os-layer/status")
async def os_layer_status(http_request: Request):
    """Read-only counters of the OS layer, for measurements. Not part of the registration contract."""
    return http_request.app.state.os_layer.snapshot()


def create_app(os_config=None):
    """Build the application. If `os_config` is None the settings come from environment variables."""

    @asynccontextmanager
    async def lifespan(app):
        layer = OSConcurrencyLayer(os_config or OSLayerConfig.from_environment())
        layer.start()
        app.state.os_layer = layer
        try:
            yield
        finally:
            await asyncio.to_thread(layer.stop)  # waits for accepted requests to finish

    application = FastAPI(title="ConcurrentReg", lifespan=lifespan)
    application.include_router(router)
    return application


app = create_app()
