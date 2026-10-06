from fastapi import FastAPI, HTTPException


# Initialize the API app
app = FastAPI()

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
def create_item(name: str, description: str = none):
    try:
        response = supabase.table("items").insert({"name":name, "description": description}).execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))





















        