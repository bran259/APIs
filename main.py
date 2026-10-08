import os
from fastapi import FastAPI, HTTPException
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field
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
@app.get("/")
def read_root():
    try:
        response = supabase.table("items").select("*").execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=400, detail=(e))
   


#POST: Add a new item directly via the SDK
#POST endpoint using the Pydantic model for request validation
@app.post("/items/")
def create_item(item: ItemCreate):
    try:
               # item.dict() converts the Pydantic object into a clean Python dictionary
        response = supabase.table("items").insert(item.dict()).execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))





















        