import streamlit as st
from openai import OpenAI
import json, os, httpx, asyncio
import requests, time
from typing import Dict, Any
import pickle
from api.calc_consumption_context import get_consumption_context
from tenacity import retry, stop_after_attempt, wait_exponential
from pydantic import BaseModel  # Import BaseModel for creating request body
from api.nutrient_analyzer import get_nutrient_analysis
from api.data_extractor import extract_data, find_product, get_product
from api.ingredients_analysis import get_ingredient_analysis
from api.claims_analysis import get_claims_analysis
#Used the @st.cache_resource decorator on this function. 
#This Streamlit decorator ensures that the function is only executed once and its result (the OpenAI client) is cached. 
#Subsequent calls to this function will return the cached client, avoiding unnecessary recreation.

@st.cache_resource
def get_openai_client():
    #Enable debug mode for testing only
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

client = get_openai_client()

@st.cache_resource
def create_assistant_and_embeddings():

    global client
    
    assistant1 = client.beta.assistants.create(
      name="Processing Level",
      instructions="You are an expert dietician. Use your knowledge base to answer questions about the processing level of food product.",
      model="gpt-4o",
      tools=[{"type": "file_search"}],
      temperature=0,
      top_p = 0.85
      )

      # Create a vector store
    vector_store1 = client.beta.vector_stores.create(name="Processing Level Vec")
    
    # Ready the files for upload to OpenAI
    file_paths = ["docs/Processing_Level.docx"]
    file_streams = [open(path, "rb") for path in file_paths]
    
    # Use the upload and poll SDK helper to upload the files, add them to the vector store,
    # and poll the status of the file batch for completion.
    file_batch1 = client.beta.vector_stores.file_batches.upload_and_poll(
      vector_store_id=vector_store1.id, files=file_streams
    )
    
    # You can print the status and the file counts of the batch to see the result of this operation.
    print(file_batch1.status)
    print(file_batch1.file_counts)

    #Processing Level
    assistant1 = client.beta.assistants.update(
      assistant_id=assistant1.id,
      tool_resources={"file_search": {"vector_store_ids": [vector_store1.id]}},
    )

    return assistant1
    
assistant_p = create_assistant_and_embeddings()

def extract_data_from_product_image(image_links):
    raw_response = extract_data({"image_links" : image_links})
    return raw_response 
            
def get_product_list(product_name_by_user):
    raw_response = find_product(product_name_by_user)
    return raw_response

def get_product_info(product_name):
    print(f"getting product info from mongodb for {product_name}")
    product_info = get_product(product_name)
    return product_info

# Define a sample request body that matches NutrientAnalysisRequest
class NutrientAnalysisRequest(BaseModel):
    product_info_from_db: dict
    
async def analyze_nutrition_using_icmr_rda(product_info_from_db):
    raw_response = await get_nutrient_analysis(NutrientAnalysisRequest(product_info_from_db=product_info_from_db))
    return raw_response

async def generate_final_analysis(
    brand_name: str,
    product_name: str,
    nutritional_level: str,
    processing_level: str,
    all_ingredient_analysis: str,
    claims_analysis: str,
    refs: list
):
    print(f"Calling cumulative-analysis API with refs : {refs}")
    global render_host_url
    # Create a client with a longer timeout (120 seconds)
    async with httpx.AsyncClient() as client_api:
        try:
            # Convert the refs list to a JSON string
            print(f"sending refs to API for product {product_name} by {brand_name} - {refs}")
            
            response = await client_api.post(
                f"{render_host_url}/cumulative_analysis/api/cumulative-analysis",
                json={
                    "brand_name": brand_name,
                    "product_name": product_name,
                    "nutritional_level": nutritional_level,
                    "processing_level": processing_level,
                    "all_ingredient_analysis": all_ingredient_analysis,
                    "claims_analysis": claims_analysis,
                    "refs": refs
                },
                headers={
                    "Content-Type": "application/json"
                },
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=800.0,
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


async def analyze_processing_level_and_ingredients(product_info_from_db, assistant_p_id):
    print("calling processing level and ingredient_analysis func")
    print(f"assistant_p_id is of type {type(assistant_p_id)}")

    request_payload = {
        "product_info_from_db": product_info_from_db,
        "assistant_p_id": assistant_p_id
    }
    
    raw_response = await get_ingredient_analysis(request_payload)
    return raw_response

def analyze_claims(product_info_from_db):
    print("calling processing level and ingredient_analysis func")
    raw_response = get_claims_analysis(product_info_from_db)
    return raw_response
  
async def analyze_product(product_info_from_db):
    global assistant_p
    
    if product_info_from_db:
        brand_name = product_info_from_db.get("brandName", "")
        product_name = product_info_from_db.get("productName", "")
        start_time = time.time()

        # Verify each function is async and returns a coroutine
        coroutines = []
        
        # Ensure each function is an async function and returns a coroutine
        nutrition_coro = analyze_nutrition_using_icmr_rda(product_info_from_db)
        processing_coro = analyze_processing_level_and_ingredients(product_info_from_db, assistant_p.id)
        
        coroutines.append(nutrition_coro)
        coroutines.append(processing_coro)

        # Conditionally add claims analysis
        # You can use asyncio.to_thread() to run the synchronous analyze_claims function in a separate thread, allowing it to run in parallel with your other asynchronous functions. Here’s how you can do it:
        if product_info_from_db.get("claims"):
            claims_coro = asyncio.to_thread(analyze_claims(product_info_from_db))
            coroutines.append(claims_coro)

        # Debug: Print coroutine types to verify
        print("Coroutines:", [type(coro) for coro in coroutines])

        # Parallel API calls
        results = await asyncio.gather(*coroutines)

        # Unpack results based on the number of coroutines
        nutritional_level_json = results[0]
        refs_ingredient_analysis_json = results[1]
        claims_analysis_json = results[2] if len(results) > 2 else None
        

        # Extract data from API results
        nutritional_level = nutritional_level_json["nutrition_analysis"]
        refs = refs_ingredient_analysis_json["refs"]
        all_ingredient_analysis = refs_ingredient_analysis_json["all_ingredient_analysis"]
        processing_level = refs_ingredient_analysis_json["processing_level"]
        claims_analysis = claims_analysis_json["claims_analysis"] if claims_analysis_json else ""

        # Generate final analysis
        final_analysis = await generate_final_analysis(
            brand_name, 
            product_name, 
            nutritional_level, 
            processing_level, 
            all_ingredient_analysis, 
            claims_analysis, 
            refs
        )

        print(f"DEBUG - Cumulative analysis finished in {time.time() - start_time} seconds")
        return final_analysis
        
# Streamlit app
# Initialize session state
if 'messages' not in st.session_state:
    st.session_state.messages = []

def chatbot_response(image_urls_str, product_name_by_user, extract_info = True):
    # Process the user input and generate a response
    processing_level = ""
    harmful_ingredient_analysis = ""
    claims_analysis = ""
    image_urls = []
    if product_name_by_user != "":
        similar_product_list_json = get_product_list(product_name_by_user)
        
        if similar_product_list_json and extract_info == False:
            with st.spinner("Fetching product information from our database... This may take a moment."):
                print(f"similar_product_list_json : {similar_product_list_json}")
                if 'error' not in similar_product_list_json.keys():
                    similar_product_list = similar_product_list_json['products']
                    return similar_product_list, "Product list found from our database"
                else:
                    return [], "Product list not found"
            
        elif extract_info == True:
            with st.spinner("Analyzing product using data from 3,000+ peer-reviewed journal papers..."):
                st.caption("This may take a few minutes")
                
                product_info_raw = get_product_info(product_name_by_user)
                print(f"DEBUG product_info_raw from name: {type(product_info_raw)} {product_info_raw}")
                if not product_info_raw:
                    return [], "product not found because product information in the db is corrupt"
                if 'error' not in product_info_raw.keys():
                    final_analysis = asyncio.run(analyze_product(product_info_raw))
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
            product_info_raw = extract_data_from_product_image(image_urls)
            print(f"DEBUG product_info_raw from image : {product_info_raw}")
            if 'error' not in product_info_raw.keys():
                final_analysis = asyncio.run(analyze_product(product_info_raw))
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
    def handle_selection():
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
                print(f"Is Selection made by user ? : {confirm_clicked}")

                # Only process the selection when confirm is clicked
                msg = ""
                if confirm_clicked:
                    st.session_state.awaiting_selection = False
                    if choice != "None of the above":
                        #st.session_state.selected_product = choice
                        st.session_state.messages.append({"role": "assistant", "content": f"You selected {choice}"})
                        print(f"Selection made by user : {choice}")
                        _, msg = chatbot_response("", choice.split(" by ")[0], extract_info=True)
                        print(f"msg is {msg}")
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
    def process_response(user_input):
        if not st.session_state.product_selected:
            if "http:/" not in user_input and "https:/" not in user_input:
                response, status = ChatManager._handle_product_name(user_input)
            else:
                response, status = ChatManager._handle_product_url(user_input)
                
        return response, status

    @staticmethod
    def _handle_product_name(user_input):
        st.session_state.product_shared = True
        st.session_state.current_user_input = user_input
        similar_products, _ = chatbot_response(
            "", user_input, extract_info=False
        )
        
        
        if len(similar_products) > 0:
            st.session_state.similar_products = similar_products
            st.session_state.awaiting_selection = True
            return "Here are some similar products from our database. Please select:", "no success"
            
        return "Product not found in our database. Please provide the image URL of the product.", "no success"

    @staticmethod
    def _handle_product_url(user_input):
        is_valid_url = (".jpeg" in user_input or ".jpg" in user_input) and \
                       ("http:/" in user_input or "https:/" in user_input)
        
        if not st.session_state.product_shared:
            return "Please provide the product name first"
        
        if is_valid_url and st.session_state.product_shared:
            _, msg = chatbot_response(
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

def main():
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
        print("Awaiting selection")
        selection_in_progress = ProductSelector.handle_selection()
    
    # Only show chat input if not awaiting selection
    if not selection_in_progress:
        user_input = st.chat_input("Enter your message:", key="user_input")
        if user_input:
            # Add user message to chat
            st.session_state.messages.append({"role": "user", "content": user_input})
            with st.chat_message("user"):
                st.markdown(user_input)
            
            # Process response
            response, status = ChatManager.process_response(user_input)

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
# def run_main():
#    run_async(main())

# Call the wrapper function in Streamlit
if __name__ == "__main__":
    main()
