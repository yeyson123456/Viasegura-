"""POST /reports: receive a detection, re-check it on the server and apply consensus."""

import asyncio
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from bson import ObjectId
from fastapi import APIRouter, Depends, Request, Response
from pydantic import ValidationError
from pymongo.errors import DuplicateKeyError

from app.config import Settings
from app.dependencies import get_app_settings, get_consensus, get_db, get_detector, get_storage
from app.errors import ApiError
from app.schemas.reports import ReportIn, ReportResult, ServerCheck
from app.services.consensus import ConsensusService
from app.services.detector import HazardDetector
from app.services.images import ALLOWED_CONTENT_TYPES, InvalidImageError, decode_image, encode_jpeg
from app.services.storage import MediaStorage

router = APIRouter(tags=["reports"])

_MAX_JSON_BYTES = 16_384
_CLOCK_SKEW = timedelta(minutes=5)

_REQUEST_BODY = {
    "required": True,
    "content": {
        "application/json": {"schema": {"$ref": "#/components/schemas/ReportIn"}},
        "multipart/form-data": {
            "schema": {
                "type": "object",
                "required": ["report"],
                "properties": {
                    "report": {"type": "string", "description": "ReportIn as a JSON string"},
                    "image": {
                        "type": "string",
                        "format": "binary",
                        "description": "Privacy-filtered photo (JPEG/PNG/WebP)",
                    },
                },
            }
        },
    },
}


def _parse_report(raw: str | bytes) -> ReportIn:
    try:
        return ReportIn.model_validate_json(raw)
    except ValidationError as exc:
        details = exc.errors(include_url=False, include_context=False)
        raise ApiError(422, "validation_error", "Invalid report", details) from exc


async def _read_request(request: Request, settings: Settings) -> tuple[ReportIn, bytes | None]:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        body = await request.body()
        if len(body) > _MAX_JSON_BYTES:
            raise ApiError(413, "payload_too_large", "Report JSON is too large")
        return _parse_report(body), None
    if content_type.startswith("multipart/form-data"):
        form = await request.form(
            max_files=1, max_fields=4, max_part_size=settings.max_image_bytes + 1
        )
        raw_report = form.get("report")
        if not isinstance(raw_report, str):
            raise ApiError(422, "validation_error", "Multipart field 'report' (JSON) is required")
        report = _parse_report(raw_report)
        upload = form.get("image")
        if upload is None or isinstance(upload, str):
            return report, None
        if upload.content_type not in ALLOWED_CONTENT_TYPES:
            raise ApiError(415, "unsupported_media_type", "Image must be JPEG, PNG or WebP")
        data = await upload.read(settings.max_image_bytes + 1)
        if len(data) > settings.max_image_bytes:
            raise ApiError(413, "payload_too_large", "Image is too large")
        return report, data or None
    raise ApiError(415, "unsupported_media_type", "Use application/json or multipart/form-data")


def _check_rules(report: ReportIn, settings: Settings, now: datetime) -> None:
    if report.confidence < settings.min_report_confidence:
        raise ApiError(
            422, "low_confidence", f"Confidence below {settings.min_report_confidence:.2f}"
        )
    if report.ts > now + _CLOCK_SKEW:
        raise ApiError(422, "timestamp_in_future", "Report timestamp is in the future")
    if report.ts < now - timedelta(hours=settings.report_max_age_h):
        raise ApiError(422, "timestamp_too_old", "Report is older than the accepted age")


async def _server_check(
    image_data: bytes, report: ReportIn, detector: HazardDetector | None, settings: Settings
) -> tuple[dict[str, Any], Any]:
    try:
        image = decode_image(image_data)
    except InvalidImageError as exc:
        raise ApiError(422, "invalid_image", "The uploaded file is not a valid image") from exc
    if detector is None:
        return {"status": "skipped", "reason": "detector_unavailable"}, image
    detections = await asyncio.to_thread(
        detector.detect, image, settings.server_check_min_confidence
    )
    matching = [d.confidence for d in detections if d.type == report.type]
    if matching:
        return {"status": "confirmed", "confidence": round(max(matching), 4)}, image
    status = "rejected" if settings.server_check_rejects else "unconfirmed"
    return {"status": status, "reason": "hazard_not_found_on_server"}, image


async def _result_for(
    document: dict[str, Any], db: Any, consensus: ConsensusService, duplicate: bool
) -> ReportResult:
    incident_status, devices = None, 0
    if document.get("incidentId"):
        incident = await db["incidents"].find_one({"_id": document["incidentId"]})
        if incident:
            incident_status = incident["status"]
            devices = len(await consensus.distinct_devices(incident["_id"], document["ts"]))
    return ReportResult(
        report_id=str(document["_id"]),
        duplicate=duplicate,
        accepted=document["accepted"],
        incident_id=str(document["incidentId"]) if document.get("incidentId") else None,
        incident_status=incident_status,
        distinct_devices=devices,
        required_devices=consensus.rules.min_devices,
        server_check=ServerCheck(**document["serverCheck"]),
        image_url=document.get("imageUrl"),
    )


@router.post(
    "/reports",
    response_model=ReportResult,
    status_code=201,
    summary="Submit a hazard report (JSON, or multipart with an optional photo)",
    responses={200: {"model": ReportResult, "description": "Duplicate (already received)"}},
    openapi_extra={"requestBody": _REQUEST_BODY},
)
async def create_report(
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[Any, Depends(get_db)],
    consensus: Annotated[ConsensusService, Depends(get_consensus)],
    detector: Annotated[HazardDetector | None, Depends(get_detector)],
    storage: Annotated[MediaStorage, Depends(get_storage)],
) -> ReportResult:
    report, image_data = await _read_request(request, settings)
    now = datetime.now(UTC)
    _check_rules(report, settings, now)

    reports = db["reports"]
    key = {"deviceId": report.device_id, "clientReportId": report.client_report_id}
    existing = await reports.find_one(key)
    if existing:  # offline queues retry; the second copy must not count twice
        response.status_code = 200
        return await _result_for(existing, db, consensus, duplicate=True)

    report_id = ObjectId()
    server_check: dict[str, Any] = {"status": "skipped", "reason": "no_image"}
    image_url = None
    if image_data:
        server_check, image = await _server_check(image_data, report, detector, settings)
        if server_check["status"] != "rejected":
            # Unguessable name; re-encoding drops EXIF/GPS metadata as a second privacy layer.
            name = f"reports/{now:%Y/%m/%d}/{report_id}-{secrets.token_hex(6)}.jpg"
            await storage.save(name, await asyncio.to_thread(encode_jpeg, image), "image/jpeg")
            image_url = f"/media/{name}"

    document = {
        "_id": report_id,
        **key,
        "type": report.type,
        "confidence": report.confidence,
        "location": report.location.model_dump(),
        "accuracyM": report.accuracy_m,
        "headingDeg": report.heading_deg,
        "speedKmh": report.speed_kmh,
        "ts": report.ts,
        "receivedAt": now,
        "modelVersion": report.model_version,
        "imageUrl": image_url,
        "serverCheck": server_check,
        "accepted": server_check["status"] != "rejected",
        "incidentId": None,
    }
    try:
        await reports.insert_one(document)
    except DuplicateKeyError:  # two retries raced each other
        response.status_code = 200
        return await _result_for(await reports.find_one(key), db, consensus, duplicate=True)

    if not document["accepted"]:
        return await _result_for(document, db, consensus, duplicate=False)
    outcome = await consensus.process(document)
    return ReportResult(
        report_id=str(report_id),
        duplicate=False,
        accepted=True,
        incident_id=str(outcome.incident_id),
        incident_status=outcome.status,
        distinct_devices=outcome.distinct_devices,
        required_devices=consensus.rules.min_devices,
        server_check=ServerCheck(**server_check),
        image_url=image_url,
    )
