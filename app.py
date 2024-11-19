import streamlit as st
from openai import OpenAI
import json, os, httpx, asyncio
import requests, time
from data_extractor import extract_data
from rda import find_nutrition
from typing import Dict, Any
from calc_cosine_similarity import find_cosine_similarity, find_embedding , find_relevant_file_paths
import pickle
from calc_consumption_context import get_consumption_context

#Used the @st.cache_resource decorator on this function. 
#This Streamlit decorator ensures that the function is only executed once and its result (the OpenAI client) is cached. 
#Subsequent calls to this function will return the cached client, avoiding unnecessary recreation.

@st.cache_resource
def get_openai_client():
    #Enable debug mode for testing only
    return True, OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


#@st.cache_resource
#def get_backend_urls():
#    data_extractor_url = "https://data-extractor-67qj89pa0-sonikas-projects-9936eaad.vercel.app/"
#    return data_extractor_url

debug_mode, client = get_openai_client()
#data_extractor_url = get_backend_urls()
assistant_default_doc = None

#def extract_data_from_product_image(image_links):
#    response = extract_data(image_links)
#    return response

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
                params={"product_name": product_name_by_user}
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
                params={"product_name": product_name}
            )
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            print(f"An error occurred: {e}")
            return None
    
# Initialize assistants and vector stores
# Function to initialize vector stores and assistants
@st.cache_resource
def initialize_assistants_and_vector_stores():
    #Processing Level
    global client
    assistant1 = client.beta.assistants.create(
      name="Processing Level",
      instructions="You are an expert dietician. Use your knowledge base to answer questions about the processing level of food product.",
      model="gpt-4o",
      tools=[{"type": "file_search"}],
      temperature=0,
      top_p = 0.85
      )
    
    #Harmful Ingredients
    assistant3 = client.beta.assistants.create(
      name="Misleading Claims",
      instructions="You are an expert dietician. Use your knowledge base to answer questions about the misleading claims about food product.",
      model="gpt-4o",
      tools=[{"type": "file_search"}],
      temperature=0,
      top_p = 0.85
      )
    
    # Create a vector store
    vector_store1 = client.beta.vector_stores.create(name="Processing Level Vec")
    
    # Ready the files for upload to OpenAI
    file_paths = ["Processing_Level.docx"]
    file_streams = [open(path, "rb") for path in file_paths]
    
    # Use the upload and poll SDK helper to upload the files, add them to the vector store,
    # and poll the status of the file batch for completion.
    file_batch1 = client.beta.vector_stores.file_batches.upload_and_poll(
      vector_store_id=vector_store1.id, files=file_streams
    )
    
    # You can print the status and the file counts of the batch to see the result of this operation.
    print(file_batch1.status)
    print(file_batch1.file_counts)
    
    # Create a vector store
    vector_store3 = client.beta.vector_stores.create(name="Misleading Claims Vec")
    
    # Ready the files for upload to OpenAI
    file_paths = ["MisLeading_Claims.docx"]
    file_streams = [open(path, "rb") for path in file_paths]
    
    # Use the upload and poll SDK helper to upload the files, add them to the vector store,
    # and poll the status of the file batch for completion.
    file_batch3 = client.beta.vector_stores.file_batches.upload_and_poll(
      vector_store_id=vector_store3.id, files=file_streams
    )
    
    # You can print the status and the file counts of the batch to see the result of this operation.
    print(file_batch3.status)
    print(file_batch3.file_counts)
    
    #Processing Level
    assistant1 = client.beta.assistants.update(
      assistant_id=assistant1.id,
      tool_resources={"file_search": {"vector_store_ids": [vector_store1.id]}},
    )
    
    
    #Misleading Claims
    assistant3 = client.beta.assistants.update(
      assistant_id=assistant3.id,
      tool_resources={"file_search": {"vector_store_ids": [vector_store3.id]}},
    )

    embeddings_titles_1 = []

    print("Reading embeddings.pkl")
    # Load both sentences and embeddings
    with open('embeddings.pkl', 'rb') as f:
        loaded_data_1 = pickle.load(f)
    embeddings_titles_1 = loaded_data_1['embeddings']

    embeddings_titles_2 = []
    print("Reading embeddings_harvard.pkl")
    # Load both sentences and embeddings
    with open('embeddings_harvard.pkl', 'rb') as f:
        loaded_data_2 = pickle.load(f)
    embeddings_titles_2 = loaded_data_2['embeddings']

    return assistant1, assistant3, embeddings_titles_1, embeddings_titles_2
    

assistant1, assistant3, embeddings_titles_1, embeddings_titles_2 = initialize_assistants_and_vector_stores()

def get_files_with_ingredient_info(ingredient, N=1):
    #Find embedding for title of all files
    global embeddings_titles_1, embeddings_titles_2

    with open('titles.txt', 'r') as file:
        lines = file.readlines()
    
    titles = [line.strip() for line in lines]
    folder_name_1 = "articles"
    #Apply cosine similarity between embedding of ingredient name and title of all files
    file_paths_abs_1, file_titles_1, refs_1 = find_relevant_file_paths(ingredient, embeddings_titles_1, titles, folder_name_1, journal_str = ".ncbi.", N=N)

    with open('titles_harvard.txt', 'r') as file:
        lines = file.readlines()
    
    titles = [line.strip() for line in lines]
    folder_name_2 = "articles_harvard"
    #Apply cosine similarity between embedding of ingredient name and title of all files
    file_paths_abs_2, file_titles_2, refs_2 = find_relevant_file_paths(ingredient, embeddings_titles_2, titles, folder_name_1, N=N)

    #Fine top N titles that are the most similar to the ingredient's name
    #Find file names for those titles
    file_paths = []
    refs = []
    if len(file_paths_abs_1) == 0 and len(file_paths_abs_2) == 0:
        file_paths.append("Ingredients.docx")
    else:
        for file_path in file_paths_abs_1:
            file_paths.append(file_path)
        refs.extend(refs_1)
        for file_path in file_paths_abs_2:
            file_paths.append(file_path)
        refs.extend(refs_2)

        print(f"Titles are {file_titles_1} and {file_titles_2}")
            
    return file_paths, refs
    
def get_assistant_for_ingredient(ingredient, N=2):
    global client
    global assistant_default_doc
    
    #Harmful Ingredients
    assistant2 = client.beta.assistants.create(
      name="Harmful Ingredients",
      instructions=f"You are an expert dietician. Use your knowledge base to answer questions about the ingredient {ingredient} in a food product.",
      model="gpt-4o",
      tools=[{"type": "file_search"}],
      temperature=0,
      top_p = 0.85
      )

    # Create a vector store
    vector_store2 = client.beta.vector_stores.create(
     name="Harmful Ingredients Vec",
     chunking_strategy={
        "type": "static",
        "static": {
            "max_chunk_size_tokens": 400,  # Set your desired max chunk size
            "chunk_overlap_tokens": 200    # Set your desired overlap size
        }
    }
    )
    
    # Ready the files for upload to OpenAI.     
    file_paths, refs = get_files_with_ingredient_info(ingredient, N)
    if file_paths[0] == "Ingredients.docx" and assistant_default_doc:
        #print(f"Using Ingredients.docx for analyzing ingredient {ingredient}")
        return assistant_default_doc, refs
        
    print(f"DEBUG : Creating vector store for files {file_paths} to analyze ingredient {ingredient}")
    
    file_streams = [open(path, "rb") for path in file_paths]
    
    # Use the upload and poll SDK helper to upload the files, add them to the vector store,
    # and poll the status of the file batch for completion.
    file_batch2 = client.beta.vector_stores.file_batches.upload_and_poll(
      vector_store_id=vector_store2.id, files=file_streams
    )
    
    # You can print the status and the file counts of the batch to see the result of this operation.
    print(file_batch2.status)
    print(file_batch2.file_counts)

    #harmful Ingredients
    assistant2 = client.beta.assistants.update(
      assistant_id=assistant2.id,
      tool_resources={"file_search": {"vector_store_ids": [vector_store2.id]}},
    )

    if file_paths[0] == "Ingredients.docx" and assistant_default_doc is None:
        assistant_default_doc = assistant2
        
    return assistant2, refs

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
    
def analyze_processing_level(ingredients, assistant_id):
    global debug_mode, client
    thread = client.beta.threads.create(
        messages=[
            {
                "role": "user",
                "content": "Categorize food product that has following ingredients: " + ', '.join(ingredients) + " into Group A, Group B, or Group C based on the document. The output must only be the group category name (Group A, Group B, or Group C) alongwith the reason behind assigning that respective category to the product. If the group category cannot be determined, output 'NOT FOUND'.",
            }
        ]
    )
    
    run = client.beta.threads.runs.create_and_poll(
        thread_id=thread.id,
        assistant_id=assistant_id,
        include=["step_details.tool_calls[*].file_search.results[*].content"]
    )

    # Polling loop to wait for a response in the thread
    messages = []
    max_retries = 10  # You can set a maximum retry limit
    retries = 0
    wait_time = 2  # Seconds to wait between retries

    while retries < max_retries:
        messages = list(client.beta.threads.messages.list(thread_id=thread.id, run_id=run.id))
        if messages:  # If we receive any messages, break the loop
            break
        retries += 1
        time.sleep(wait_time)

    # Check if we got the message content
    if not messages:
        raise TimeoutError("Processing Level : No messages were returned after polling.")
        
    message_content = messages[0].content[0].text
    annotations = message_content.annotations
    #citations = []
    for index, annotation in enumerate(annotations):
        message_content.value = message_content.value.replace(annotation.text, "")
        #if file_citation := getattr(annotation, "file_citation", None):
        #    cited_file = client.files.retrieve(file_citation.file_id)
        #    citations.append(f"[{index}] {cited_file.filename}")

    if debug_mode:
        print(message_content.value)
    processing_level_str = message_content.value
    return processing_level_str

def analyze_harmful_ingredients(ingredient, assistant_id):
    global debug_mode, client
    is_ingredient_not_found_in_doc = False
    
    thread = client.beta.threads.create(
        messages=[
            {
                "role": "user",
                "content": "A food product has the ingredient: " + ingredient + ". Is this ingredient safe to eat? The output must be in JSON format: {<ingredient_name>: <information from the document about why ingredient is harmful>}. If information about an ingredient is not found in the documents, the value for that ingredient must start with the prefix '(NOT FOUND IN DOCUMENT)' followed by the LLM's response based on its own knowledge.",
            }
        ]
    )
    
    run = client.beta.threads.runs.create_and_poll(
        thread_id=thread.id,
        assistant_id=assistant_id,
        include=["step_details.tool_calls[*].file_search.results[*].content"],
        tools=[{
        "type": "file_search",
        "file_search": {
            "max_num_results": 5
        }
        }]
    )
    
    
    ## List run steps to get step IDs
    #run_steps = client.beta.threads.runs.steps.list(
    #    thread_id=thread.id,
    #    run_id=run.id
    #)
    
    ## Initialize a list to store step IDs and their corresponding run steps
    #all_steps_info = []
    
    ## Iterate over each step in run_steps.data
    #for step in run_steps.data:  # Access each RunStep object
    #    step_id = step.id  # Get the step ID (use 'step_id' instead of 'id')
    
        ## Retrieve detailed information for each step using its ID
        #run_step_detail = client.beta.threads.runs.steps.retrieve(
        #    thread_id=thread.id,
        #    run_id=run.id,
        #    step_id=step_id,
        #    include=["step_details.tool_calls[*].file_search.results[*].content"]
        #)
    
        ## Append a tuple of (step_id, run_step_detail) to the list
        #all_steps_info.append((step_id, run_step_detail))
    
    ## Print all step IDs and their corresponding run steps
    #for step_id, run_step_detail in all_steps_info:
    #    print(f"Step ID: {step_id}")
    #    print(f"Run Step Detail: {run_step_detail}\n")
    
    # Polling loop to wait for a response in the thread
    messages = []
    max_retries = 10  # You can set a maximum retry limit
    retries = 0
    wait_time = 2  # Seconds to wait between retries

    while retries < max_retries:
        messages = list(client.beta.threads.messages.list(thread_id=thread.id, run_id=run.id))
        if messages:  # If we receive any messages, break the loop
            break
        retries += 1
        time.sleep(wait_time)

    # Check if we got the message content
    if not messages:
        raise TimeoutError("Processing Ingredients : No messages were returned after polling.")
        
    message_content = messages[0].content[0].text
    annotations = message_content.annotations

    #citations = []

    #print(f"Length of annotations is {len(annotations)}")

    for index, annotation in enumerate(annotations):
      if file_citation := getattr(annotation, "file_citation", None):
          #cited_file = client.files.retrieve(file_citation.file_id)
          #citations.append(f"[{index}] {cited_file.filename}")
          message_content.value = message_content.value.replace(annotation.text, "")
  
    if debug_mode:
      ingredients_not_found_in_doc = []        
      print(message_content.value)
      for key, value in json.loads(message_content.value.replace("```", "").replace("json", "")).items():
          if value.startswith("(NOT FOUND IN DOCUMENT)"):
              ingredients_not_found_in_doc.append(key)
              is_ingredient_not_found_in_doc = True
          print(f"Ingredients not found in database {','.join(ingredients_not_found_in_doc)}")
    
    harmful_ingredient_analysis = json.loads(message_content.value.replace("```", "").replace("json", "").replace("(NOT FOUND IN DOCUMENT) ", ""))
        
    harmful_ingredient_analysis_str = ""
    for key, value in harmful_ingredient_analysis.items():
      harmful_ingredient_analysis_str += f"{key}: {value}\n"
    return harmful_ingredient_analysis_str, is_ingredient_not_found_in_doc

def analyze_claims(claims, ingredients, assistant_id):
    global debug_mode, client
    thread = client.beta.threads.create(
        messages=[
            {
                "role": "user",
                "content": "A food product named has the following claims: " + ', '.join(claims) + " and ingredients: " + ', '.join(ingredients) + """. Please evaluate the validity of each claim as well as assess if the product name is misleading.
The output must be in JSON format as follows: 

{
  <claim_name>: {
    'Verdict': <A judgment on the claim's accuracy, ranging from 'Accurate' to varying degrees of 'Misleading'>,
    'Why?': <A concise, bulleted summary explaining the specific ingredients or aspects contributing to the discrepancy>,
    'Detailed Analysis': <An in-depth explanation of the claim, incorporating relevant regulatory guidelines and health perspectives to support the verdict>
  }
}
"""
            }
                ]
    )
    
    run = client.beta.threads.runs.create_and_poll(
        thread_id=thread.id,
        assistant_id=assistant_id,
        include=["step_details.tool_calls[*].file_search.results[*].content"]
    )
    
    # Polling loop to wait for a response in the thread
    messages = []
    max_retries = 10  # You can set a maximum retry limit
    retries = 0
    wait_time = 2  # Seconds to wait between retries

    while retries < max_retries:
        messages = list(client.beta.threads.messages.list(thread_id=thread.id, run_id=run.id))
        if messages:  # If we receive any messages, break the loop
            break
        retries += 1
        time.sleep(wait_time)

    # Check if we got the message content
    if not messages:
        raise TimeoutError("Processing Claims : No messages were returned after polling.")
        
    message_content = messages[0].content[0].text
    
      
    annotations = message_content.annotations
    
    #citations = []
    
    #print(f"Length of annotations is {len(annotations)}")
    
    for index, annotation in enumerate(annotations):
          if file_citation := getattr(annotation, "file_citation", None):
              #cited_file = client.files.retrieve(file_citation.file_id)
              #citations.append(f"[{index}] {cited_file.filename}")
              message_content.value = message_content.value.replace(annotation.text, "")
      
    #if debug_mode:
    #    claims_not_found_in_doc = []
    #    print(message_content.value)
    #    for key, value in json.loads(message_content.value.replace("```", "").replace("json", "")).items():
    #          if value.startswith("(NOT FOUND IN DOCUMENT)"):
    #              claims_not_found_in_doc.append(key)
    #    print(f"Claims not found in the doc are {','.join(claims_not_found_in_doc)}")
    #claims_analysis = json.loads(message_content.value.replace("```", "").replace("json", "").replace("(NOT FOUND IN DOCUMENT) ", ""))
    claims_analysis = {}
    if message_content.value != "":
        claims_analysis = json.loads(message_content.value.replace("```", "").replace("json", ""))

    claims_analysis_str = ""
    for key, value in claims_analysis.items():
      claims_analysis_str += f"{key}: {value}\n"
    
    return claims_analysis_str

def generate_final_analysis(brand_name, product_name, nutritional_level, processing_level, all_ingredient_analysis, claims_analysis, refs):
    global debug_mode, client
    consumption_context = get_consumption_context(f"{product_name} by {brand_name}", client)
    
    system_prompt = """Tell the consumer whether the product is a healthy option at the assumed functionality along with the reasoning behind why it is a good option or not. Refer to Consumption Context as a guide for generating a recommendation. 

Additionally , these are the standard rules to follow.
If the product is very obviously junk like chocolates, chips, cola drinks then highlight the risk in a way that you're contextualising it for people.
If not necessarily perceived as a harmful product, then the job is to highlight the risk that is not very obvious and the user maybe missing
If the product is promoted as a healthier alternative on the brand packaging, then specifically check for hidden harms using the misleading claims framework
If the product is good, then highlight the most relevant benefit

Your source for deciding whether the user is thinking the product is healthy or not is two
- Check the 'perceived health benefit' column of category sheet 
- check if there is any information on the packaging that would make the user think otherwise

Only highlight the most relevant & insightful part of your analysis which may not be very obvious to user. If your decision is based on nutrition analysis, talk about that and give your analysis doing social math. If ingredients is the biggest positive or hazard, mention the ingredients with benefit or harm. If the analysis is based on processing level, mention that is good or bad on account of being minimally or highly processes respectively. If the decision is based on any misleading claims present, then talk about that.

This is how you will generate the response:

1. Recommendation
Restrict your answer to 30-50 words. If the answer is that it is a good option then generate a happy emoji and if it is not a good option then generate a sad emoji.

2. Risk Analysis 

A. Nutrition Analysis 

Case 1: If sugar, salt, calories and are high in quantity, 
Mention that along with RDA at the user’s serving size or ICMR values. Do social math here and contextualise the information of slat and sugar in teaspoons and calories equivalent to no of whole and healthy nutritious meals.
For sugar - also separately mention RDA from Total added sugar( added separately)  & naturally occurring sugars  (naturally part of the ingredients used)

Case 2: If good nutrients like protein & micronutrients, dietary fibre  are present in a good quantity, mention that. Highlight the presence of good nutrients - protein or micronutrients. give RDA values  at the user’s serving size. Do social match and contextualise the information. 

Case 3: For fat, explain the kind of fats present (trans, MUFA, PUFA), and whether it is good or bad. and what is the benefit or harm. 
 give RDA values, do social match and contextualise the information. 

Case 4: If it is a carbohydrates dense products, mention that. 
Mention RDA at user’s serving size.Do social math here and contextualise the information of the carbs equivalent to no of whole and healthy nutritious meals.

restrict your answer to 50 words, 2-3 sentence. 

B. Ingredeint Analysis 
Highlight the good or bad ingredients along with harm/benefit . Mention the ingredeint names. Provide the harm or benefit along with citations from the research paper. 

C. Misleading Claims 
Highlight the misleading claim identified along with the reason."""

    user_prompt = f"""
Brand Name : {brand_name}
Product Name: {product_name}

Consumption Context of the product is as follows -> 
{consumption_context}

Nutrition Analysis for the product is as follows ->
{nutritional_level}

Processing Level Analysis for the product is as follows ->
{processing_level}

Ingredient Analysis for the product is as follows ->
{all_ingredient_analysis}

Claims Analysis for the product is as follows ->
{claims_analysis}
"""
    if debug_mode:
        print(f"\nuser_prompt : \n {user_prompt}")
        
    completion = client.chat.completions.create(
        model="gpt-4o",  # Make sure to use an appropriate model
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    )

    if len(refs) > 0:
        L = min(2, len(refs))
        return f"Brand: {brand_name}\n\nProduct: {product_name}\n\nAnalysis:\n\n{completion.choices[0].message.content}\n\nTop Citations:\n\n{'\n'.join(refs[0:L])}"
    else:
        return f"Brand: {brand_name}\n\nProduct: {product_name}\n\nAnalysis:\n\n{completion.choices[0].message.content}"


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
        
        if len(ingredients_list) > 0:
            processing_level = analyze_processing_level(ingredients_list, assistant1.id) if ingredients_list else ""
            for ingredient in ingredients_list:
                assistant_id_ingredient, refs_ingredient = get_assistant_for_ingredient(ingredient, 2)
                ingredient_analysis, is_ingredient_in_doc = analyze_harmful_ingredients(ingredient, assistant_id_ingredient.id)
                all_ingredient_analysis += ingredient_analysis + "\n"
                if is_ingredient_in_doc:
                    refs.extend(refs_ingredient)
        
        if len(claims_list) > 0:                    
            claims_analysis = analyze_claims(claims_list, ingredients_list, assistant3.id) if claims_list else ""
                
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
