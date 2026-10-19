from pydantic import BaseModel, EmailStr
from typing import Optional
import datetime
from uuid import UUID

class UserSignup(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    avatar_url: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class MFATokenResponse(BaseModel):
    mfa_token: str

class MFARequest(BaseModel):
    mfa_token: str
    otp: str

class UserSession(BaseModel):
    user_id: UUID | str
    token: str
    expires_at: datetime.datetime

class MFASetup(BaseModel):
    user_id: UUID | str
    secret: str
    backup_codes: Optional[str] = None

class VerifyEmailRequest(BaseModel):
    email: EmailStr
    code: str
    # If set, backend completes sign-in after confirmation without custom email MFA (register → OTP → dashboard).
    password: Optional[str] = None

class CognitoTokenResponse(BaseModel):
    access_token: str
    id_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ConfirmForgotPasswordRequest(BaseModel):
    email: EmailStr
    code: str
    new_password: str

class PasswordChange(BaseModel):
    old_password: str
    new_password: str
