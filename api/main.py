from fastapi import FastAPI

# Import your individual API apps
from api.data_extractor import app as data_extractor_app
from api.another_app import app as another_app

main_app = FastAPI()

# Mount individual apps
main_app.mount("/data-extractor", data_extractor_app)
main_app.mount("/another-app", another_app)

# Optional: Add a root endpoint
@main_app.get("/")
async def root():
    return {"message": "Main application"}
