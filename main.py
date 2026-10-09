import os
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, Field
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file

#Securely load the keys (.env file)
SUPABASE_URL = "https://rdkakvhrdrhpvvelmmtu.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJka2FrdmhyZHJocHZ2ZWxtbXR1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTEyODQwMjksImV4cCI6MjEwNjg2MDAyOX0.zmGkdjtTpYryGAkPhrPJgGIl9TkzB6U3OgJvTfySJZE"

#Initialize the Supabase Client
supabase : Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# Initialize the API app
app = FastAPI()

#FastAPI security scheme to extract the "Bearer <token>" header
security = HTTPBearer()

#Define the Pydantic Validation Schema
class User(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)
    
class ItemCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)

#  AUTH DEPENDENCY: Verifies incoming JWT with Supabase
def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials  # Extracts the clean text token
    try:
        # Ask Supabase to validate this token against its database
        user_response = supabase.auth.get_user(token)
        return user_response.user  # Returns user profile if valid
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

#GET
#PUBLIC ROUTE: Read items
@app.get("/")
def read_root():
    try:
        response = supabase.table("items").select("*").execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    
#  PUBLIC ROUTE: User Registration
@app.post("/auth/signup")
def sign_up(user: User):
    try:
        response = supabase.auth.sign_up({
            "email": user.email,
            "password": user.password
        })
        return{"message": "Registartion succesful! Please check your email for confirmation.", "user_id": response.user.id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

#  PUBLIC ROUTE: User Login (Generates your access token)
@app.post("/auth/login")
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
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


#POST: Add a new item directly via the SDK
#POST endpoint using the Pydantic model for request validation
#  PROTECTED ROUTE: Only accessible with a valid token
# Notice: 'current_user' is added as a Dependency injection
@app.post("/items/")
def create_item(item: ItemCreate, current_user: dict = Depends(get_current_user)):
    try:
        # You can now access 'current_user.id' to stamp who created the row!
        item_data = item.dict()
        
        response = supabase.table("items").insert(item_data).execute()
        return {
            "message": "Item successfully created by authenticated user!",
            "author_id": current_user.id,
            "data": response.data
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


#PUT: Update an existing item by its ID
@app.put("/items/{item_id}")
def update_item(item_id: int, item: ItemCreate, current_user=Depends(get_current_user)):
    try:
        # Update the row where the 'id' column matches the path parameter
        response = supabase.table("items")\
            .update(item.dict())\
            .eq("id", item_id)\
            .execute()

        # If no rows were affected,   the item doesn't exist
        if not response.data:
            raise HTTPException(status_code=404, detail="Item not found")
        return{
            "meassage": f"item {item_id} succesfully updated by user {current_user.id}","
            "data":response.data
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
        

















        