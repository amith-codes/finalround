"""Twilio SMS notifications for customer bookings."""
import base64
import logging
import re
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app import config

log = logging.getLogger("dispatchgrid.sms")


def normalize_phone_number(phone: str | None) -> str | None:
    """Convert common Indian mobile formats to E.164 for Twilio."""
    if not phone:
        return None
    raw = phone.strip()
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+"):
        normalized = digits
    elif digits.startswith("00"):
        normalized = digits[2:]
    elif len(digits) == 10:
        normalized = f"91{digits}"
    elif len(digits) == 11 and digits.startswith("0"):
        normalized = f"91{digits[1:]}"
    elif len(digits) == 12 and digits.startswith("91"):
        normalized = digits
    else:
        return None
    return f"+{normalized}" if 8 <= len(normalized) <= 15 else None


def send_booking_confirmation(
    *,
    phone: str | None,
    customer_name: str | None,
    job_number: str,
    service_title: str,
    window_start: datetime,
    window_end: datetime,
    electrician_name: str | None,
) -> bool:
    """Send a confirmation SMS after the booking is committed.

    SMS delivery is best-effort and never rolls back or fails a successful booking.
    Configure a Twilio account, token, and either a sender number or messaging service
    SID in the environment before running the API.
    """
    if not (config.TWILIO_ACCOUNT_SID and config.TWILIO_AUTH_TOKEN and
            (config.TWILIO_FROM_NUMBER or config.TWILIO_MESSAGING_SERVICE_SID)):
        log.info("Booking %s saved; Twilio SMS is not configured.", job_number)
        return False

    recipient = normalize_phone_number(phone)
    if recipient is None:
        log.warning("Booking %s saved; no valid customer mobile number was provided for SMS.", job_number)
        return False

    name = (customer_name or "there").strip() or "there"
    appointment = f"{window_start:%d %b %Y}, {window_start:%I:%M %p}–{window_end:%I:%M %p}"
    electrician = f" Your selected electrician is {electrician_name}." if electrician_name else ""
    message = (
        f"Hi {name}, your Dispatcher electrician service request {job_number} "
        f"for {service_title} is booked for {appointment}.{electrician} "
        "The request is awaiting electrician confirmation."
    )

    payload = {"To": recipient, "Body": message}
    if config.TWILIO_MESSAGING_SERVICE_SID:
        payload["MessagingServiceSid"] = config.TWILIO_MESSAGING_SERVICE_SID
    else:
        payload["From"] = config.TWILIO_FROM_NUMBER

    url = f"https://api.twilio.com/2010-04-01/Accounts/{config.TWILIO_ACCOUNT_SID}/Messages.json"
    credentials = base64.b64encode(
        f"{config.TWILIO_ACCOUNT_SID}:{config.TWILIO_AUTH_TOKEN}".encode("utf-8")
    ).decode("ascii")
    request = Request(
        url,
        data=urlencode(payload).encode("utf-8"),
        headers={"Authorization": f"Basic {credentials}",
                 "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=8) as response:
            if 200 <= response.status < 300:
                log.info("Booking confirmation SMS accepted by Twilio for %s.", job_number)
                return True
            log.error("Twilio returned HTTP %s for booking %s SMS.", response.status, job_number)
    except HTTPError as exc:
        log.error("Twilio returned HTTP %s for booking %s SMS.", exc.code, job_number)
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        log.warning("Twilio SMS could not be sent for booking %s (%s).", job_number, type(exc).__name__)
    return False
