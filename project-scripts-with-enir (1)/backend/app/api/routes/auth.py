from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database  import get_db
from app.core.security  import hash_password, verify_password, create_access_token, create_refresh_token, decode_token
from app.api.deps       import get_current_user
from app.models         import User, Organization, ProjectMember

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email:    EmailStr
    name:     str      = Field(min_length=2, max_length=255)
    password: str      = Field(min_length=8)
    org_name: str | None = None


class LoginRequest(BaseModel):
    email:    EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token:  str
    refresh_token: str
    token_type:    str = "bearer"
    user:          dict


class RefreshRequest(BaseModel):
    refresh_token: str


class MeUpdate(BaseModel):
    name:       str | None = None
    avatar_url: str | None = None


class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8)


def user_dict(user: User, role: str | None = None) -> dict:
    return {"id": user.id, "name": user.name, "email": user.email,
            "avatar_url": user.avatar_url, "role": role}


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    if await db.scalar(select(User).where(User.email == body.email)):
        raise HTTPException(400, "Email уже зарегистрирован")

    org_name = body.org_name or f"{body.name}'s workspace"
    org = Organization(
        id   = str(uuid4()),
        name = org_name,
        slug = org_name.lower().replace(" ", "-")[:90] + "-" + str(uuid4())[:8],
    )
    db.add(org)

    user = User(
        id              = str(uuid4()),
        organization_id = org.id,
        email           = body.email,
        name            = body.name,
        password_hash   = hash_password(body.password),
    )
    db.add(user)
    await db.commit()

    return TokenResponse(
        access_token  = create_access_token(user.id),
        refresh_token = create_refresh_token(user.id),
        user          = user_dict(user),
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.email == body.email))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Неверный email или пароль")
    if not user.is_active:
        raise HTTPException(403, "Аккаунт заблокирован")

    return TokenResponse(
        access_token  = create_access_token(user.id),
        refresh_token = create_refresh_token(user.id),
        user          = user_dict(user),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        payload = decode_token(body.refresh_token)
        if payload.get("type") != "refresh":
            raise ValueError
        user_id = payload["sub"]
    except Exception:
        raise HTTPException(401, "Refresh-токен недействителен")

    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(401)

    return TokenResponse(
        access_token  = create_access_token(user.id),
        refresh_token = create_refresh_token(user.id),
        user          = user_dict(user),
    )


@router.post("/logout", status_code=204)
async def logout():
    return  # stateless JWT — клиент удаляет токены


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    members = await db.scalars(select(ProjectMember).where(ProjectMember.user_id == current_user.id))
    return {
        **user_dict(current_user),
        "projects": [{"project_id": m.project_id, "role": m.role} for m in members],
    }


@router.patch("/me")
async def update_me(body: MeUpdate, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if body.name       is not None: current_user.name       = body.name
    if body.avatar_url is not None: current_user.avatar_url = body.avatar_url
    await db.commit()
    return user_dict(current_user)


@router.patch("/me/password", status_code=204)
async def change_password(body: PasswordChange, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not verify_password(body.old_password, current_user.password_hash):
        raise HTTPException(400, "Неверный текущий пароль")
    current_user.password_hash = hash_password(body.new_password)
    await db.commit()
