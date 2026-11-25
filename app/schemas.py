from pydantic import BaseModel


class RegistrationRequest(BaseModel):
    student_id: str
    section_id: int


class RegistrationResponse(BaseModel):
    success: bool
    message: str
