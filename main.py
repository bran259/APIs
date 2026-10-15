import os
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, NoReturn
from uuid import UUID
from fastapi import FastAPI, HTTPException, Depends, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, Field, model_validator
from starlette.exceptions import HTTPException as StarletteHTTPException
from supabase import (
    AuthError,
    Client,
    ClientOptions,
    PostgrestAPIError,
    create_client,
)
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file
logger = logging.getLogger(__name__)

#Securely load the keys (.env file)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing critical Supabase environment variables.")

#Initialize the Supabase Client
supabase : Client = create_client(SUPABASE_URL, SUPABASE_KEY)

CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://localhost:5173",
    ).split(",")
    if origin.strip()
]

# Initialize the API app
app = FastAPI()


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class ItemResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    created_at: datetime | None = None
    user_id: str | None = None


class ItemEnvelope(BaseModel):
    data: ItemResponse


class PaginationResponse(BaseModel):
    limit: int
    offset: int
    next_offset: int | None


class ItemCollectionResponse(BaseModel):
    data: list[ItemResponse]


class ItemPageResponse(ItemCollectionResponse):
    pagination: PaginationResponse


class UserSignupResponse(BaseModel):
    message: str
    user_id: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"]
    user_id: str


ERROR_RESPONSES = {
    code: {"model": ErrorResponse}
    for code in (400, 401, 403, 404, 405, 409, 422, 429, 500, 503)
}


ERROR_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_server_error",
    503: "service_unavailable",
}


@app.exception_handler(StarletteHTTPException)
async def handle_http_exception(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    logger.debug(
        "Handled HTTP error %s for %s %s",
        exc.status_code,
        request.method,
        request.url.path,
    )
    message = (
        exc.detail
        if isinstance(exc.detail, str)
        else "The request could not be completed."
    )
    body = ErrorResponse(
        error=ErrorDetail(
            code=ERROR_CODES.get(exc.status_code, "http_error"),
            message=message,
        )
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=body.model_dump(),
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    logger.info(
        "Request validation failed for %s %s (%d errors)",
        request.method,
        request.url.path,
        len(exc.errors()),
    )
    body = ErrorResponse(
        error=ErrorDetail(
            code="validation_error",
            message="Request validation failed.",
        )
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=body.model_dump(),
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unhandled request error for %s %s",
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    body = ErrorResponse(
        error=ErrorDetail(
            code="internal_server_error",
            message="An unexpected error occurred.",
        )
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=body.model_dump(),
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

#FastAPI security scheme to extract the "Bearer <token>" header
security = HTTPBearer()


def database_http_exception(operation: str, exc: Exception) -> HTTPException:
    if isinstance(exc, PostgrestAPIError):
        if exc.code == "42501":
            logger.warning("Database denied operation %s (code=%s)", operation, exc.code)
            return HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not allowed to perform this operation.",
            )
        if exc.code in {"23503", "23505"}:
            logger.warning("Database rejected operation %s (code=%s)", operation, exc.code)
            return HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The operation conflicts with existing data.",
            )
        if exc.code and exc.code.startswith("22"):
            logger.warning("Database rejected operation %s (code=%s)", operation, exc.code)
            return HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The submitted data is invalid.",
            )

    logger.exception("Database operation %s failed", operation)
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="The database service is temporarily unavailable.",
    )


def authentication_http_exception(
    exc: AuthError, operation: str
) -> HTTPException:
    error_code = getattr(exc, "code", None)
    error_status = getattr(exc, "status", None)

    if error_code in {"bad_jwt", "invalid_jwt", "user_not_found", "invalid_credentials"}:
        detail = (
            "Invalid email or password."
            if operation == "login" and error_code == "invalid_credentials"
            else "Invalid or expired authentication credentials."
        )
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"} if operation == "validate_token" else None,
        )
    if error_code in {"email_exists", "user_already_exists"}:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Unable to create an account with the provided details.",
        )
    if error_code == "weak_password":
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The password does not meet the required strength.",
        )
    if error_code in {"signup_disabled", "email_not_confirmed"}:
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This authentication action is not permitted.",
        )
    if error_status == status.HTTP_429_TOO_MANY_REQUESTS:
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication requests. Please try again later.",
        )
    if isinstance(error_status, int) and error_status >= 500:
        logger.exception("Supabase authentication operation %s failed", operation)
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The authentication service is temporarily unavailable.",
        )
    if operation == "validate_token":
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if operation == "login":
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Unable to create an account with the provided details.",
    )


def service_unavailable(operation: str) -> NoReturn:
    logger.exception("Supabase operation %s failed", operation)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="A required service is temporarily unavailable.",
    )


#Define the Pydantic Validation Schema
class User(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)
    
class ItemCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)


class ItemPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def require_patchable_fields(self):
        if not self.model_fields_set:
            raise ValueError("At least one item field must be provided.")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("Item name cannot be null.")
        return self


@dataclass
class AuthenticatedUser:
    id: str
    database: Client


def create_user_database_client(token: str) -> Client:
    client = create_client(
        SUPABASE_URL,
        SUPABASE_KEY,
        options=ClientOptions(auto_refresh_token=False, persist_session=False),
    )
    client.postgrest.auth(token)
    return client


#  AUTH DEPENDENCY: Verifies incoming JWT with Supabase
def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> AuthenticatedUser:
    token = credentials.credentials  # Extracts the clean text token
    try:
        # Ask Supabase to validate this token against its database
        user_response = supabase.auth.get_user(token)
    except AuthError as exc:
        raise authentication_http_exception(exc, "validate_token") from exc
    except Exception:
        service_unavailable("validate_token")

    if user_response.user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        database = create_user_database_client(token)
    except Exception:
        service_unavailable("create_user_database_client")

    return AuthenticatedUser(id=user_response.user.id, database=database)


#GET
# PROTECTED ROUTE: Read only the authenticated user's items
@app.get(
    "/items/",
    response_model=ItemPageResponse,
    responses=ERROR_RESPONSES,
)
def read_all_items(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    try:
        response = (
            current_user.database.table("items")
            .select("*")
            .eq("user_id", current_user.id)
            .order("id")
            .range(offset, offset + limit)
            .execute()
        )
        items = response.data[:limit]
        next_offset = offset + limit if len(response.data) > limit else None
        return {
            "data": items,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "next_offset": next_offset,
            },
        }
    except Exception as exc:
        raise database_http_exception("read_all_items", exc) from exc

# PROTECTED ROUTE: Read items belonging to the authenticated user
@app.get(
    "/items/user/{user_id}",
    response_model=ItemCollectionResponse,
    responses=ERROR_RESPONSES,
)
def read_user_items(
    user_id: UUID, current_user: AuthenticatedUser = Depends(get_current_user)
):
    if str(user_id) != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    try:
        response = (
            current_user.database.table("items")
            .select("*")
            .eq("user_id", current_user.id)
            .execute()
        )
        return {"data": response.data}
    except Exception as exc:
        raise database_http_exception("read_user_items", exc) from exc

# PROTECTED ROUTE: Read a single item owned by the authenticated user
@app.get(
    "/items/{item_id}",
    response_model=ItemEnvelope,
    responses=ERROR_RESPONSES,
)
def read_single_item(
    item_id: int, current_user: AuthenticatedUser = Depends(get_current_user)
):
    try:
        response = (
            current_user.database.table("items")
            .select("*")
            .eq("id", item_id)
            .eq("user_id", current_user.id)
            .execute()
        )
        if not response.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
        return {"data": response.data[0]}
    except HTTPException:
        raise
    except Exception as exc:
        raise database_http_exception("read_single_item", exc) from exc
    
#  PUBLIC ROUTE: User Registration
@app.post(
    "/auth/signup",
    status_code=status.HTTP_201_CREATED,
    response_model=UserSignupResponse,
    responses=ERROR_RESPONSES,
)
def sign_up(user: User):
    try:
        response = supabase.auth.sign_up({
            "email": user.email,
            "password": user.password
        })
        return {
            "message": "Registration successful! Please check your email for confirmation.",
            "user_id": response.user.id,
        }
    except AuthError as exc:
        raise authentication_http_exception(exc, "signup") from exc
    except Exception:
        service_unavailable("signup")

#  PUBLIC ROUTE: User Login (Generates your access token)
@app.post(
    "/auth/login",
    response_model=LoginResponse,
    responses=ERROR_RESPONSES,
)
def login(user: User):
    try:
        response = supabase.auth.sign_in_with_password({
            "email": user.email,
            "password": user.password
        })
          # This access_token is what your frontend uses to make secure API calls
        return {
            "access_token": response.session.access_token,
            "token_type": "bearer",
            "user_id": response.user.id
        }
    except AuthError as exc:
        raise authentication_http_exception(exc, "login") from exc
    except Exception:
        service_unavailable("login")


#POST: Add a new item directly via the SDK
#POST endpoint using the Pydantic model for request validation
#  PROTECTED ROUTE: Only accessible with a valid token
# Notice: 'current_user' is added as a Dependency injection
@app.post(
    "/items/",
    status_code=status.HTTP_201_CREATED,
    response_model=ItemEnvelope,
    responses=ERROR_RESPONSES,
)
def create_item(
    item: ItemCreate, current_user: AuthenticatedUser = Depends(get_current_user)
):
    try:
        item_data = item.model_dump()  # Note: .dict() is deprecated in Pydantic v2, use .model_dump()
        item_data["user_id"] = current_user.id  # Automatically tie this item to the creator's ID
        
        response = current_user.database.table("items").insert(item_data).execute()
        return {"data": response.data[0]}
    except Exception as exc:
        raise database_http_exception("create_item", exc) from exc

#PUT: Update an existing item by its ID
@app.put(
    "/items/{item_id}",
    response_model=ItemEnvelope,
    responses=ERROR_RESPONSES,
)
def update_item(
    item_id: int,
    item: ItemCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    try:
        # ENHANCED: We verify that the item's ID matches AND it belongs to the active logged-in user
        response = current_user.database.table("items")\
            .update(item.model_dump())\
            .eq("id", item_id)\
            .eq("user_id", current_user.id)\
            .execute()

        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="Item not found or you do not have permission to modify it"
            )
        return {"data": response.data[0]}
    except HTTPException:
        raise
    except Exception as exc:
        raise database_http_exception("update_item", exc) from exc


@app.patch(
    "/items/{item_id}",
    response_model=ItemEnvelope,
    responses=ERROR_RESPONSES,
)
def patch_item(
    item_id: int,
    item: ItemPatch,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    try:
        response = (
            current_user.database.table("items")
            .update(item.model_dump(exclude_unset=True))
            .eq("id", item_id)
            .eq("user_id", current_user.id)
            .execute()
        )
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Item not found or you do not have permission to modify it.",
            )
        return {"data": response.data[0]}
    except HTTPException:
        raise
    except Exception as exc:
        raise database_http_exception("patch_item", exc) from exc


# DELETE ROUTE: Remove an item by its ID
@app.delete(
    "/items/{item_id}",
    response_model=ItemEnvelope,
    responses=ERROR_RESPONSES,
)
def delete_item(
    item_id: int, current_user: AuthenticatedUser = Depends(get_current_user)
):
    try:
        #Delete the row where the 'id' column matches the path parameter
        response = current_user.database.table("items")\
            .delete()\
            .eq("id", item_id)\
            .eq("user_id", current_user.id)\
            .execute()
        if not response.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found or you do not have permission to delete it")
        return {"data": response.data[0]}
    except HTTPException:
        raise
    except Exception as exc:
        raise database_http_exception("delete_item", exc) from exc
















        