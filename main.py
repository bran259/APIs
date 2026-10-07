import os
from fastapi import FastAPI, HTTPException
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

#Define the Pydantic Validation Schema
class ItemCreate(BaseModel):
    name: str = Field(..., min_lenght=1, max_lenght=100, description="The name of the item")
    description: str | None = Field(None, max_leght=500, description="An optional detailed description")


#GET
@app.get("/")
def read_root():
    try:
        response = supabase.table("items").select("*").execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=400, detail=(e))
   


#POST: Add a new item directly via the SDK
@app.post("/items/")
def create_item(name: str, description: str = None):
    try:
        response = supabase.table("items").insert({"name":name, "description": description}).execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))





















        