import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request, Response

from app import demo_api, iasl_api
from app import registration_service as service
from app.iasl.config import IASLConfig
from app.iasl.runtime import IASLRuntime
from app.os_layer.layer_config import OSLayerConfig
from app.os_layer.request_pipeline import ADMISSION_REJECTED, QUEUE_FULL, SHUTTING_DOWN, OSConcurrencyLayer
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
    # Only produced when IASL's admission controller is installed. Same status as a full queue (the client
    # should back off and retry) but a distinct message, so the two can be told apart in every experiment.
    ADMISSION_REJECTED: 503,
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


def create_app(os_config=None, iasl_config=None):
    """Build the application. If `os_config` / `iasl_config` is None the settings come from environment variables.

    IASL is OFF unless IASL_ENABLED is true: then no IASL object exists and nothing is installed on the layer.
    A bad IASL setting stops start-up and names the variable, like the OS-layer settings do.
    """

    @asynccontextmanager
    async def lifespan(app):
        layer = OSConcurrencyLayer(os_config or OSLayerConfig.from_environment())
        iasl_settings = iasl_config or IASLConfig.from_environment()
        iasl = None
        if iasl_settings.enabled:
            iasl = IASLRuntime(iasl_settings)
            iasl.attach(layer)   # strict: an impossible IASL_ADMISSION_* combination refuses to start
        layer.start()
        app.state.os_layer = layer
        app.state.iasl = iasl
        app.state.iasl_config = iasl_settings   # shown by GET /iasl/config even when IASL is off
        if iasl is not None:
            iasl.start()
        try:
            yield
        finally:
            if iasl is not None:
                await asyncio.to_thread(iasl.stop)   # stop adapting first, then drain the layer
            await asyncio.to_thread(layer.stop)  # waits for accepted requests to finish

    application = FastAPI(title="ConcurrentReg", lifespan=lifespan)
    application.include_router(router)
    # Demo controls for the dashboard. Only GET /demo/info works unless CREG_DEMO_CONTROLS=1 (see app/demo_api.py).
    application.include_router(iasl_api.router)   # read-only IASL monitoring: GET /iasl/status|metrics|decisions|config
    application.include_router(demo_api.info_router)
    application.include_router(demo_api.router)
    return application


app = create_app()
