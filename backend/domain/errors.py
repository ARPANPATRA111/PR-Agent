"""Domain errors that are safe to translate into user-facing responses."""


class DomainError(Exception):
    status_code = 400
    public_message = "The request could not be completed."

    def __init__(self, message: str | None = None):
        super().__init__(message or self.public_message)
        self.public_message = message or self.public_message


class RecordNotFound(DomainError):
    status_code = 404
    public_message = "Record not found."


class ConcurrentUpdate(DomainError):
    status_code = 409
    public_message = "This record changed. Refresh it and try again."


class DuplicateRequest(DomainError):
    status_code = 409
    public_message = "A different record already uses that request key."
