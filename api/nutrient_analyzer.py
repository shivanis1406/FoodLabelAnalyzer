import logging
import traceback
import sys
from functools import wraps
from .icmr import analyze_nutrients
from .rda import find_nutrition
import os
import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any
from openai import OpenAI
from typing import Dict, Any

# Set up logging with file name and line numbers
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)

# Create an error handling decorator
def log_exceptions(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            # Get the current stack trace
            exc_info = sys.exc_info()
            # Get the full stack trace as a string
            stack_trace = ''.join(traceback.format_exception(*exc_info))
            
            logger.error(
                f"Exception in {func.__name__}: {str(e)}\n"
                f"Stack trace:\n{stack_trace}"
            )
            raise
    return wrapper

app = FastAPI(debug=True)

# Apply the decorator to your endpoint
@app.post("/api/nutrient-analysis")
@log_exceptions
async def get_nutrient_analysis(product_info: Dict[str, Any]):
    try:
        nutritional_information = product_info.nutritionalInformation
        logger.debug(f"Processing nutritional information: {nutritional_information}")
        
        serving_size = product_info.servingSize.quantity
        logger.debug(f"Serving size: {serving_size}")
        
        nutrient_analysis_rda = ""
        nutrient_analysis = ""
        nutritional_level = ""
                
        if nutritional_information:
            try:
                product_type, calories, sugar, salt, serving_size = find_product_nutrients(product_info.dict())
                logger.info(
                    "find_product_nutrients successful",
                    extra={
                        'product_type': product_type,
                        'calories': calories,
                        'sugar': sugar,
                        'salt': salt,
                        'serving_size': serving_size
                    }
                )
            except Exception as e:
                logger.error(f"Error in find_product_nutrients: {str(e)}", exc_info=True)
                raise
                
            if product_type is not None and serving_size is not None and serving_size > 0:
                try:
                    nutrient_analysis = await analyze_nutrients(product_type, calories, sugar, salt, serving_size)
                    logger.debug(f"Nutrient analysis completed: {nutrient_analysis}")
                except Exception as e:
                    logger.error(f"Error in analyze_nutrients: {str(e)}", exc_info=True)
                    raise
            else:
                error_msg = "Product information in the db is corrupt"
                logger.error(error_msg, extra={
                    'product_type': product_type,
                    'serving_size': serving_size
                })
                raise HTTPException(status_code=400, detail=error_msg)

            try:
                nutrient_analysis_rda_data = await rda_analysis(nutritional_information, serving_size)
                logger.debug(
                    "RDA analysis data retrieved",
                    extra={
                        'data_type': type(nutrient_analysis_rda_data),
                        'nutrition_per_serving': nutrient_analysis_rda_data['nutritionPerServing'],
                        'user_serving_size': nutrient_analysis_rda_data['userServingSize']
                    }
                )
            except Exception as e:
                logger.error(f"Error in rda_analysis: {str(e)}", exc_info=True)
                raise

            try:
                nutrient_analysis_rda = await find_nutrition(nutrient_analysis_rda_data)
                logger.debug(f"RDA nutrient analysis completed: {nutrient_analysis_rda}")
            except Exception as e:
                logger.error(f"Error in find_nutrition: {str(e)}", exc_info=True)
                raise
                    
            try:
                nutritional_level = await analyze_nutrition_icmr_rda(nutrient_analysis, nutrient_analysis_rda)
                logger.info("Analysis completed successfully")
                return nutritional_level
            except Exception as e:
                logger.error(f"Error in analyze_nutrition_icmr_rda: {str(e)}", exc_info=True)
                raise
                
        else:
            error_msg = "Nutritional information is required"
            logger.error(error_msg)
            raise HTTPException(status_code=400, detail=error_msg)

    except HTTPException as http_ex:
        logger.warning(
            f"HTTP error occurred: {http_ex.detail}",
            extra={'status_code': http_ex.status_code}
        )
        raise http_ex
        
    except Exception as e:
        logger.error("Unexpected error occurred", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
