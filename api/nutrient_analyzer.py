from nutrient_analyzer import analyze_nutrients
from rda import find_nutrition
import os
import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any
from openai import OpenAI

app = FastAPI(title="Nutrition Analysis API

debug_mode = True
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY")
                
# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def find_product_nutrients(product_info_from_db):
    #GET Response: {'_id': '6714f0487a0e96d7aae2e839',
    #'brandName': 'Parle', 'claims': ['This product does not contain gold'],
    #'fssaiLicenseNumbers': [10013022002253],
    #'ingredients': [{'metadata': '', 'name': 'Refined Wheat Flour (Maida)', 'percent': '63%'}, {'metadata': '', 'name': 'Sugar', 'percent': ''}, {'metadata': '', 'name': 'Refined Palm Oil', 'percent': ''}, {'metadata': '(Glucose, Levulose)', 'name': 'Invert Sugar Syrup', 'percent': ''}, {'metadata': 'I', 'name': 'Sugar Citric Acid', 'percent': ''}, {'metadata': '', 'name': 'Milk Solids', 'percent': '1%'}, {'metadata': '', 'name': 'Iodised Salt', 'percent': ''}, {'metadata': '503(I), 500 (I)', 'name': 'Raising Agents', 'percent': ''}, {'metadata': '1101 (i)', 'name': 'Flour Treatment Agent', 'percent': ''}, {'metadata': 'Diacetyl Tartaric and Fatty Acid Esters of Glycerol (of Vegetable Origin)', 'name': 'Emulsifier', 'percent': ''}, {'metadata': 'Vanilla', 'name': 'Artificial Flavouring Substances', 'percent': ''}],
    
    #'nutritionalInformation': [{'name': 'Energy', 'unit': 'kcal', 'values': [{'base': 'per 100 g','value': 462}]},
    #{'name': 'Protein', 'unit': 'g', 'values': [{'base': 'per 100 g', 'value': 6.7}]},
    #{'name': 'Carbohydrate', 'unit': 'g', 'values': [{'base': 'per 100 g', 'value': 76.0}, {'base': 'of which sugars', 'value': 26.9}]},
    #{'name': 'Fat', 'unit': 'g', 'values': [{'base': 'per 100 g', 'value': 14.6}, {'base': 'Saturated Fat', 'value': 6.8}, {'base': 'Trans Fat', 'value': 0}]},
    #{'name': 'Total Sugars', 'unit': 'g', 'values': [{'base': 'per 100 g', 'value': 27.7}]},
    #{'name': 'Added Sugars', 'unit': 'g', 'values': [{'base': 'per 100 g', 'value': 26.9}]},
    #{'name': 'Cholesterol', 'unit': 'mg', 'values': [{'base': 'per 100 g', 'value': 0}]},
    #{'name': 'Sodium', 'unit': 'mg', 'values': [{'base': 'per 100 g', 'value': 281}]}],
    
    #'packagingSize': {'quantity': 82, 'unit': 'g'},
    #'productName': 'Parle-G Gold Biscuits',
    #'servingSize': {'quantity': 18.8, 'unit': 'g'},
    #'servingsPerPack': 3.98,
    #'shelfLife': '7 months from packaging'}

    product_type = None
    calories = None
    sugar = None
    total_sugar = None
    added_sugar = None
    salt = None
    serving_size = None

    if product_info_from_db["servingSize"]["unit"].lower() == "g":
        product_type = "solid"
    elif product_info_from_db["servingSize"]["unit"].lower() == "ml":
        product_type = "liquid"
    serving_size = product_info_from_db["servingSize"]["quantity"]

    for item in product_info_from_db["nutritionalInformation"]:
        if 'energy' in item['name'].lower():
            calories = item['values'][0]['value']
        if 'total sugar' in item['name'].lower():
            total_sugar = item['values'][0]['value']
        if 'added sugar' in item['name'].lower():
            added_sugar = item['values'][0]['value']
        if 'sugar' in item['name'].lower() and 'added sugar' not in item['name'].lower() and 'total sugar' not in item['name'].lower():
            sugar = item['values'][0]['value']
        if 'salt' in item['name'].lower():
            if salt is None:
                salt = 0
            salt += item['values'][0]['value']

    if salt is None:
        salt = 0
        for item in product_info_from_db["nutritionalInformation"]:
            if 'sodium' in item['name'].lower():
                salt += item['values'][0]['value']

    if added_sugar is not None and added_sugar > 0 and sugar is None:
        sugar = added_sugar
    elif total_sugar is not None and total_sugar > 0 and added_sugar is None and sugar is None:
        sugar = total_sugar

    return product_type, calories, sugar, salt, serving_size


async def rda_analysis(product_info_from_db_nutritionalInformation: Dict[str, Any], 
                product_info_from_db_servingSize: float) -> Dict[str, Any]:
    """
    Analyze nutritional information and return RDA analysis data in a structured format.
    
    Args:
        product_info_from_db_nutritionalInformation: Dictionary containing nutritional information
        product_info_from_db_servingSize: Serving size value
        
    Returns:
        Dictionary containing nutrition per serving and user serving size
    """
    nutrient_name_list = [
        'energy', 'protein', 'carbohydrates', 'addedSugars', 'dietaryFiber',
        'totalFat', 'saturatedFat', 'monounsaturatedFat', 'polyunsaturatedFat',
        'transFat', 'sodium'
    ]

    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": """You will be given nutritional information of a food product. 
                                Return the data in the exact JSON format specified in the schema, 
                                with all required fields."""
                },
                {
                    "role": "user",
                    "content": f"Nutritional content of food product is {json.dumps(product_info_from_db_nutritionalInformation)}. "
                              f"Extract the values of the following nutrients: {', '.join(nutrient_name_list)}."
                }
            ],
        response_format={"type": "json_schema", "json_schema": {
            "name": "Nutritional_Info_Label_Reader",
            "schema": {
                "type": "object",
                "properties": {
                    "energy": {"type": "number"},
                    "protein": {"type": "number"},
                    "carbohydrates": {"type": "number"},
                    "addedSugars": {"type": "number"},
                    "dietaryFiber": {"type": "number"},
                    "totalFat": {"type": "number"},
                    "saturatedFat": {"type": "number"},
                    "monounsaturatedFat": {"type": "number"},
                    "polyunsaturatedFat": {"type": "number"},
                    "transFat": {"type": "number"},
                    "sodium": {"type": "number"},
                    "servingSize": {"type": "number"},
                },
                "required": nutrient_name_list + ["servingSize"],
                "additionalProperties": False
            },
            "strict": True
        }}
        )
        
        # Parse the JSON response
        nutrition_data = json.loads(response.choices[0].message.content)
        
        # Validate that all required fields are present
        missing_fields = [field for field in nutrient_name_list + ["servingSize"] 
                         if field not in nutrition_data]
        if missing_fields:
            print(f"Missing required fields in API response: {missing_fields}")
        
        # Validate that all values are numbers
        non_numeric_fields = [field for field, value in nutrition_data.items() 
                            if not isinstance(value, (int, float))]
        if non_numeric_fields:
            raise ValueError(f"Non-numeric values found in fields: {non_numeric_fields}")
        
        return {
            'nutritionPerServing': nutrition_data,
            'userServingSize': product_info_from_db_servingSize
        }
        
    except Exception as e:
        # Log the error and raise it for proper handling
        print(f"Error in RDA analysis: {str(e)}")
        raise


async def analyze_nutrition_icmr_rda(nutrient_analysis, nutrient_analysis_rda):
    global debug_mode, client
    system_prompt = """
Task: Analyze the nutritional content of the food item and compare it to the Recommended Daily Allowance (RDA) or threshold limits defined by ICMR. Provide practical, contextual insights based on the following nutrients:

Nutrient Breakdown and Analysis:
Calories:

Compare the calorie content to a well-balanced meal.
Calculate how many meals' worth of calories the product contains, providing context for balanced eating.
Sugar & Salt:

Convert the amounts of sugar and salt into teaspoons to help users easily understand their daily intake.
Explain whether the levels exceed the ICMR-defined limits and what that means for overall health.
Fat & Calories:

Analyze fat content, specifying whether it is high or low in relation to a balanced diet.
Offer insights on how the fat and calorie levels may impact the user’s overall diet, including potential risks or benefits.
Contextual Insights:
For each nutrient, explain how its levels (whether high or low) affect health and diet balance.
Provide actionable recommendations for the user, suggesting healthier alternatives or adjustments to consumption if necessary.
Tailor the advice to the user's lifestyle, such as recommending lower intake if sedentary or suggesting other dietary considerations based on the product's composition.

Output Structure:
For each nutrient (Calories, Sugar, Salt, Fat), specify if the levels exceed or are below the RDA or ICMR threshold.
Provide clear, concise comparisons (e.g., sugar exceeds the RDA by 20%, equivalent to X teaspoons).    
    """

    user_prompt = f"""
Nutrition Analysis :
{nutrient_analysis}
{nutrient_analysis_rda}
"""
    if debug_mode:
        print(f"\nuser_prompt : \n {user_prompt}")
        
    completion = await client.chat.completions.create(
        model="gpt-4o",  # Make sure to use an appropriate model
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    )

    return completion.choices[0].message.content

@app.get("/api/nutrient-analysis")
async def nutrient_analysis(product_info_from_db):
    if product_info_from_db:
      brand_name = product_info_from_db.get("brandName", "")
      product_name = product_info_from_db.get("productName", "")
      ingredients_list = [ingredient["name"] for ingredient in product_info_from_db.get("ingredients", [])]
      claims_list = product_info_from_db.get("claims", [])
      nutritional_information = product_info_from_db['nutritionalInformation']
      serving_size = product_info_from_db["servingSize"]["quantity"]
    
      nutrient_analysis_rda = ""
      nutrient_analysis = ""
      nutritional_level = ""
            
      if nutritional_information:
          product_type, calories, sugar, salt, serving_size = find_product_nutrients(product_info_from_db)
          if product_type is not None and serving_size is not None and serving_size > 0:                                                          
              nutrient_analysis = await analyze_nutrients(product_type, calories, sugar, salt, serving_size)                       
          else:                                                                                                              
              return "product not found because product information in the db is corrupt"   
          print(f"DEBUG ! nutrient analysis is {nutrient_analysis}")
    
          nutrient_analysis_rda_data = await rda_analysis(nutritional_information, serving_size)
          print(f"DEBUG ! Data for RDA nutrient analysis is of type {type(nutrient_analysis_rda_data)} - {nutrient_analysis_rda_data}")
          print(f"DEBUG : nutrient_analysis_rda_data['nutritionPerServing'] : {nutrient_analysis_rda_data['nutritionPerServing']}")
          print(f"DEBUG : nutrient_analysis_rda_data['userServingSize'] : {nutrient_analysis_rda_data['userServingSize']}")
                
          nutrient_analysis_rda = await find_nutrition(nutrient_analysis_rda_data)
          print(f"DEBUG ! RDA nutrient analysis is {nutrient_analysis_rda}")
                
          #Call GPT for nutrient analysis
          nutritional_level = await analyze_nutrition_icmr_rda(nutrient_analysis, nutrient_analysis_rda)

          return nutritional_level
