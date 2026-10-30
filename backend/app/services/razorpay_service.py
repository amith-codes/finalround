"""Small server-side client for Razorpay's fixed-amount UPI QR API."""
import base64
import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from app import config
from app.services.errors import ApiError

API_ROOT = "https://api.razorpay.com/v1"


def configured() -> bool:
    return bool(config.RAZORPAY_KEY_ID and config.RAZORPAY_KEY_SECRET)


def _request(path: str, *, method: str = "GET", payload: dict | None = None) -> dict:
    if not configured():
        raise ApiError(
            503,
            "RAZORPAY_NOT_CONFIGURED",
            "Razorpay is not configured. Set the backend Razorpay test or live API credentials and restart the server.",
        )

    credentials = base64.b64encode(
        f"{config.RAZORPAY_KEY_ID}:{config.RAZORPAY_KEY_SECRET}".encode("utf-8")
    ).decode("ascii")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{API_ROOT}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
            message = body.get("error", {}).get("description") or "Razorpay rejected the payment request."
        except (ValueError, AttributeError):
            message = "Razorpay rejected the payment request."
        raise ApiError(502, "RAZORPAY_REQUEST_FAILED", message[:250]) from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise ApiError(502, "RAZORPAY_UNAVAILABLE", "Could not reach Razorpay. The booking is saved; retry payment shortly.") from exc


def create_upi_qr(*, amount_rupees: float, job_number: str, job_id: int) -> dict:
    """Create a single-use, fixed INR UPI QR code for a DispatchGrid booking."""
    amount_paise = int(round(amount_rupees * 100))
    if amount_paise <= 0:
        raise ApiError(422, "INVALID_PAYMENT_AMOUNT", "A Razorpay QR requires a booking amount greater than zero.")
    close_by = int(time.time()) + (2 * 60 * 60)
    result = _request(
        "/payments/qr_codes",
        method="POST",
        payload={
            "type": "upi_qr",
            "name": f"Dispatcher {job_number}"[:40],
            "usage": "single_use",
            "fixed_amount": True,
            "payment_amount": amount_paise,
            "description": f"Electrician service booking {job_number}"[:255],
            "close_by": close_by,
            "notes": {"dispatchgrid_job_id": str(job_id), "job_number": job_number},
        },
    )
    if not result.get("id") or not result.get("image_url"):
        raise ApiError(502, "RAZORPAY_INVALID_RESPONSE", "Razorpay did not return a usable payment QR code.")
    return result


def fetch_qr_payments(qr_code_id: str) -> list[dict]:
    result = _request(f"/payments/qr_codes/{quote(qr_code_id, safe='')}/payments?count=100")
    return result.get("items", []) if isinstance(result, dict) else []
