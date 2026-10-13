from fastapi import HTTPException


class ApiError(HTTPException):
    def __init__(self, status: int, code: str, message: str, headers: dict | None = None):
        super().__init__(status, message, headers=headers)
        self.code = code
