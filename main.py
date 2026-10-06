from fastapi import FastAPI

# Initialize the API app
app = FastAPI()

#GET
@app.get("/")
def read_root():
    return {"message": "welcome to the API!"}