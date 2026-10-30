"""Consistent API error type. Every error response has the shape
{"error": {"code": str, "message": str, "details": any}}.
"""


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details=None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details

    def body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


def not_found(entity: str, ident) -> ApiError:
    return ApiError(404, "NOT_FOUND", f"{entity} {ident} not found")
