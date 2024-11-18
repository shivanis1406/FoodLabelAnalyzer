from fastapi import FastAPI

# Import your individual API apps
from api.data_extractor import app as data_extractor_app
from api.nutrient_analyzer import app as nutrient_analyzer_app

main_app = FastAPI()

# Mount individual apps
main_app.mount("/", data_extractor_app)
main_app.mount("/", nutrient_analyzer_app)

# Optional: Add a root endpoint
@main_app.get("/")
async def root():
    return {"message": "Main application"}
