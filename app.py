import streamlit as st
from openai import OpenAI
import json, os, httpx, asyncio
import requests, time
#from data_extractor import extract_data
#from rda import find_nutrition
from typing import Dict, Any
#from calc_cosine_similarity import  find_relevant_file_paths
import pickle
from calc_consumption_context import get_consumption_context
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

#Used the @st.cache_resource decorator on this function. 
#This Streamlit decorator ensures that the function is only executed once and its result (the OpenAI client) is cached. 
#Subsequent calls to this function will return the cached client, avoiding unnecessary recreation.

@st.cache_resource
def get_openai_client():
    #Enable debug mode for testing only
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


#@st.cache_resource
#def get_backend_urls():
#    data_extractor_url = "https://data-extractor-67qj89pa0-sonikas-projects-9936eaad.vercel.app/"
#    return data_extractor_url

client = get_openai_client()

async def extract_data_from_product_image(image_links):
    print(f"DEBUG - image links are {image_links}")
    async with httpx.AsyncClient() as client_api:
        try:
            response = await client_api.post(
                "https://foodlabelanalyzer-api.onrender.com/data_extractor/api/extract-data", 
                json = image_links,
                headers = {
                "Content-Type": "application/json"
                },
                timeout=10.0
            )
            response.raise_for_status()  # Raise an exception for HTTP errors
            return response.json()
        except httpx.RequestError as e:
            print(f"Request error occurred: {e.request.url} - {e}")
            return None
        except httpx.HTTPStatusError as e:
            print(f"HTTP error occurred: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            return None
            
#def get_product_list(product_name_by_user):
#    response = find_product(product_name_by_user)
#    return response

async def get_product_list(product_name_by_user):
    print("calling find-product api")
    async with httpx.AsyncClient() as client_api:
        try:
            response = await client_api.get(
                "https://foodlabelanalyzer-api.onrender.com/data_extractor/api/find-product", 
                params={"product_name": product_name_by_user},
                timeout=httpx.Timeout(
                    connect=100.0,
                    read=500.0,
                    pool=50.0,
                    write=10.0
                )
            )
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            print(f"An error occurred: {e}")
            return None

async def get_product(product_name):
    print("calling get-product api")
    async with httpx.AsyncClient() as client_api:
        try:
            response = await client_api.get(
                "https://foodlabelanalyzer-api.onrender.com/data_extractor/api/get-product", 
                params={"product_name": product_name},
                timeout=httpx.Timeout(
                    connect=300.0,
                    read=700.0,
                    pool=50.0,
                    write=10.0
                )
            )
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException as e:
            print(f"The request timed out : {e}")
            return None
        except httpx.RequestError as e:
            print(f"An error occurred: {e}")
            return None 
    
async def analyze_nutrition_using_icmr_rda(product_info_from_db):
    print(f"Calling analyze_nutrition_icmr_rda api - product_info_from_db : {type(product_info_from_db)}")
    async with httpx.AsyncClient() as client_api:
        try:
            response = await client_api.post(
                "https://foodlabelanalyzer-api.onrender.com/nutrient_analyzer/api/nutrient-analysis", 
                json=product_info_from_db
            )
            response.raise_for_status()
            print(f"response.text : {response.text}")
            return response.text
        except httpx.RequestError as e:
            print(f"An error occurred: {e}")
            return None

def generate_final_analysis(
    brand_name: str,
    product_name: str,
    nutritional_level: str,
    processing_level: str,
    all_ingredient_analysis: str,
    claims_analysis: str,
    refs: list
):
    print(f"Calling cumulative-analysis API with refs : {refs}")
    
    # Create a client with a longer timeout (120 seconds)
    with httpx.Client() as client_api:
        try:
            # Convert the refs list to a JSON string
            refs_str = ",".join(refs)
            print(f"sending refs to API for product {product_name} by {brand_name} - {refs_str}")
            
            response = client_api.get(
                "https://foodlabelanalyzer-api.onrender.com/cumulative_analysis/api/cumulative-analysis",
                params={
                    "brand_name": brand_name,
                    "product_name": product_name,
                    "nutritional_level": nutritional_level,
                    "processing_level": processing_level,
                    "all_ingredient_analysis": all_ingredient_analysis,
                    "claims_analysis": claims_analysis,
                    "refs": refs_str
                },
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=500.0,
                    write=10.0,
                    pool=10.0
                )
            )
            response.raise_for_status()
            formatted_response = response.text.replace('\\n', '\n')
            return formatted_response
            
        except httpx.TimeoutException as e:
            print(f"Request timed out: {e}")
            return None
        except Exception as e:
            print(f"An error occurred: {e}")
            return None


def analyze_processing_level_and_ingredients(product_info_from_db):
    print("calling processing level and ingredient_analysis api")
    
    request_payload = {
        "product_info_from_db": product_info_from_db
    }
    
    try:
        with httpx.Client() as client_api:
            response = client_api.post(
                "https://foodlabelanalyzer-api.onrender.com/ingredient_analysis/api/processing_level-ingredient-analysis", 
                json=request_payload,
                headers={
                    "Content-Type": "application/json"
                },
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=600.0,
                    write=10.0,
                    pool=10.0
                )
            )
            response.raise_for_status()
            return response.json()
    except httpx.TimeoutException as e:
            print(f"The request timed out : {e}")
            return None
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
            print(f"API call error: {e}")
            return None

def analyze_claims(product_info_from_db):
    print("calling processing level and ingredient_analysis api")
    
    request_payload = {
        "product_info_from_db": product_info_from_db
    }
    
    try:
        with httpx.Client() as client_api:
            response = client_api.post(
                "https://foodlabelanalyzer-api.onrender.com/claims_analysis/api/claims-analysis", 
                json=request_payload,
                headers={
                    "Content-Type": "application/json"
                },
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=150.0,
                    write=10.0,
                    pool=10.0
                )
            )
            response.raise_for_status()
            return response.json()
    
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"API call error: {e}")
        return None 
            
    
async def analyze_product(product_info_from_db):
    
    global assistant1, assistant3
    
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
        processing_level = ""
        all_ingredient_analysis = ""
        claims_analysis = ""
        refs = []

        nutritional_level = await analyze_nutrition_using_icmr_rda(product_info_from_db)
        
        refs_all_ingredient_analysis_processing_level_json = analyze_processing_level_and_ingredients(product_info_from_db)
        refs = refs_all_ingredient_analysis_processing_level_json["refs"]
        all_ingredient_analysis = refs_all_ingredient_analysis_processing_level_json["all_ingredient_analysis"]
        processing_level = refs_all_ingredient_analysis_processing_level_json["processing_level"]
        
        if len(claims_list) > 0:                    
            claims_analysis_json = analyze_claims(product_info_from_db)
            claims_analysis = claims_analysis_json["claims_analysis"]
            
        final_analysis = generate_final_analysis(brand_name, product_name, nutritional_level, processing_level, all_ingredient_analysis, claims_analysis, refs)

        return final_analysis
    #else:
    #    return "I'm sorry, product information could not be extracted from the url."    

# Streamlit app
# Initialize session state
if 'messages' not in st.session_state:
    st.session_state.messages = []

async def chatbot_response(image_urls_str, product_name_by_user, extract_info = True):
    # Process the user input and generate a response
    processing_level = ""
    harmful_ingredient_analysis = ""
    claims_analysis = ""
    image_urls = []
    if product_name_by_user != "":
        similar_product_list_json = await get_product_list(product_name_by_user)
        
        if similar_product_list_json and extract_info == False:
            with st.spinner("Fetching product information from our database... This may take a moment."):
                print(f"similar_product_list_json : {similar_product_list_json}")
                if 'error' not in similar_product_list_json.keys():
                    similar_product_list = similar_product_list_json['products']
                    return similar_product_list, "Product list found from our database"
                else:
                    return [], "Product list not found"
            
        elif extract_info == True:
            with st.spinner("Analyzing the product... This may take a moment."):
                product_info_raw = await get_product(product_name_by_user)
                print(f"DEBUG product_info_raw from name: {type(product_info_raw)} {product_info_raw}")
                if not product_info_raw:
                    return [], "product not found because product information in the db is corrupt"
                if 'error' not in product_info_raw.keys():
                    final_analysis = await analyze_product(product_info_raw)
                    return [], final_analysis
                else:
                    return [], f"Product information could not be extracted from our database because of {product_info_raw['error']}"
                
        else:
            return [], "Product not found in our database."
                
    elif "http:/" in image_urls_str.lower() or "https:/" in image_urls_str.lower():
        # Extract image URL from user input
        if "," not in image_urls_str:
            image_urls.append(image_urls_str)
        else:
            for url in image_urls_str.split(","):
                if "http:/" in url.lower() or "https:/" in url.lower():
                    image_urls.append(url)

        with st.spinner("Analyzing the product... This may take a moment."):
            product_info_raw = await extract_data_from_product_image(image_urls)
            print(f"DEBUG product_info_raw from image : {product_info_raw}")
            if 'error' not in product_info_raw.keys():
                final_analysis = await analyze_product(product_info_raw)
                return [], final_analysis
            else:
                return [], f"Product information could not be extracted from the image because of {json.loads(product_info_raw)['error']}"

            
    else:
        return [], "I'm here to analyze food products. Please provide an image URL (Example : http://example.com/image.jpg) or product name (Example : Harvest Gold Bread)"

class SessionState:
    """Handles all session state variables in a centralized way"""
    @staticmethod
    def initialize():
        initial_states = {
            "messages": [],
            "product_selected": False,
            "product_shared": False,
            "analyze_more": True,
            "welcome_shown": False,
            "yes_no_choice": None,
            "welcome_msg": "Welcome to ConsumeWise! What product would you like me to analyze today? Example : Noodles, Peanut Butter etc",
            "similar_products": [],
            "awaiting_selection": False,
            "current_user_input": "",
            "selected_product": None
        }
        
        for key, value in initial_states.items():
            if key not in st.session_state:
                st.session_state[key] = value

class ProductSelector:
    """Handles product selection logic"""
    @staticmethod
    async def handle_selection():
        if st.session_state.similar_products:
            # Create a container for the selection UI
            selection_container = st.container()
            
            with selection_container:
                # Radio button for product selection
                choice = st.radio(
                    "Select a product:",
                    st.session_state.similar_products + ["None of the above"],
                    key="product_choice"
                )
                
                # Confirm button
                confirm_clicked = st.button("Confirm Selection")
                
                # Only process the selection when confirm is clicked
                msg = ""
                if confirm_clicked:
                    st.session_state.awaiting_selection = False
                    if choice != "None of the above":
                        #st.session_state.selected_product = choice
                        st.session_state.messages.append({"role": "assistant", "content": f"You selected {choice}"})
                        _, msg = await chatbot_response("", choice.split(" by ")[0], extract_info=True)
                        #Check if analysis couldn't be done because db had incomplete information
                        if msg != "product not found because product information in the db is corrupt":
                            #Only when msg is acceptable
                            st.session_state.messages.append({"role": "assistant", "content": msg})
                            with st.chat_message("assistant"):
                                st.markdown(msg)
                                
                            st.session_state.product_selected = True
                            
                            keys_to_keep = ["messages", "welcome_msg"]
                            keys_to_delete = [key for key in st.session_state.keys() if key not in keys_to_keep]
                        
                            for key in keys_to_delete:
                                del st.session_state[key]
                            st.session_state.welcome_msg = "What product would you like me to analyze next?"
                            
                    if choice == "None of the above" or msg == "product not found because product information in the db is corrupt":
                        st.session_state.messages.append(
                            {"role": "assistant", "content": "Please provide the image URL of the product to analyze based on the latest information."}
                        )
                        with st.chat_message("assistant"):
                            st.markdown("Please provide the image URL of the product to analyze based on the latest information.")
                        #st.session_state.selected_product = None
                        
                    st.rerun()
                
                # Prevent further chat input while awaiting selection
                return True  # Indicates selection is in progress
            
        return False  # Indicates no selection in progress

class ChatManager:
    """Manages chat interactions and responses"""
    @staticmethod
    async def process_response(user_input):
        if not st.session_state.product_selected:
            if "http:/" not in user_input and "https:/" not in user_input:
                response, status = await ChatManager._handle_product_name(user_input)
            else:
                response, status = await ChatManager._handle_product_url(user_input)
                
        return response, status

    @staticmethod
    async def _handle_product_name(user_input):
        st.session_state.product_shared = True
        st.session_state.current_user_input = user_input
        similar_products, _ = await chatbot_response(
            "", user_input, extract_info=False
        )
        
        
        if len(similar_products) > 0:
            st.session_state.similar_products = similar_products
            st.session_state.awaiting_selection = True
            return "Here are some similar products from our database. Please select:", "no success"
            
        return "Product not found in our database. Please provide the image URL of the product.", "no success"

    @staticmethod
    async def _handle_product_url(user_input):
        is_valid_url = (".jpeg" in user_input or ".jpg" in user_input) and \
                       ("http:/" in user_input or "https:/" in user_input)
        
        if not st.session_state.product_shared:
            return "Please provide the product name first"
        
        if is_valid_url and st.session_state.product_shared:
            _, msg = await chatbot_response(
                user_input, "", extract_info=True
            )
            st.session_state.product_selected = True
            if msg != "product not found because image is not clear" and "Product information could not be extracted from the image" not in msg:
                response = msg
                status = "success"
            elif msg == "product not found because image is not clear":
                response = msg + ". Please share clear image URLs!"
                status = "no success"
            else:
                response = msg + ".Please re-try!!"
                status = "no success"
                
            return response, status
                
        return "Please provide valid image URL of the product.", "no success"

async def main():
    # Initialize session state
    SessionState.initialize()
    
    # Display title
    st.title("ConsumeWise - Your Food Product Analysis Assistant")
    
    # Show welcome message
    if not st.session_state.welcome_shown:
        st.session_state.messages.append({
            "role": "assistant", 
            "content": st.session_state.welcome_msg
        })
        st.session_state.welcome_shown = True
    
    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    
    # Handle product selection if awaiting
    selection_in_progress = False
    if st.session_state.awaiting_selection:
        selection_in_progress = await ProductSelector.handle_selection()
    
    # Only show chat input if not awaiting selection
    if not selection_in_progress:
        user_input = st.chat_input("Enter your message:", key="user_input")
        if user_input:
            # Add user message to chat
            st.session_state.messages.append({"role": "user", "content": user_input})
            with st.chat_message("user"):
                st.markdown(user_input)
            
            # Process response
            response, status = await ChatManager.process_response(user_input)

            st.session_state.messages.append({"role": "assistant", "content": response})
            with st.chat_message("assistant"):
                st.markdown(response)
                    
            if status == "success":               
                SessionState.initialize()  # Reset states for next product
                #st.session_state.welcome_msg = "What is the next product you would like me to analyze today?"
                keys_to_keep = ["messages", "welcome_msg"]
                keys_to_delete = [key for key in st.session_state.keys() if key not in keys_to_keep]
                    
                for key in keys_to_delete:
                    del st.session_state[key]
                st.session_state.welcome_msg = "What product would you like me to analyze next?"
                
            #else:
            #    print(f"DEBUG : st.session_state.awaiting_selection : {st.session_state.awaiting_selection}")
            st.rerun()
    else:
        # Disable chat input while selection is in progress
        st.chat_input("Please confirm your selection above first...", disabled=True)
    
    # Clear chat history button
    if st.button("Clear Chat History"):
        st.session_state.clear()
        st.rerun()

# Create a wrapper function to run the async main
def run_main():
    asyncio.run(main())

# Call the wrapper function in Streamlit
if __name__ == "__main__":
    run_main()
