
#set the api key by the following to the terminal $env:GOOGLE_API_KEY = "API_KEY"

import requests
import json
import pandas as pd
import time
import os

# The rest of the functions (analyze_tweet_with_gemini and process_tweets_from_csv)
# remain the same as they correctly use standard libraries (requests, json, pandas, os, time).

def analyze_tweet_with_gemini(tweet_text, api_key):
    # ... (function body is identical to your provided code) ...
    """
    Analyzes a single tweet using the Google Gemini API with retry logic for rate limits.

    Args:
        tweet_text (str): The text of the tweet to analyze.
        api_key (str): Your Google Gemini API key.

    Returns:
        dict: A dictionary containing the analysis result (label and translation),
              or an error message if the API call fails after all retries.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent?key={api_key}"

    # Use a system instruction to define the persona and rules for the model.
    system_instruction = {
        "parts": [{
            "text": """You are an expert social media analyst specializing in environmental and climate-related content.
            Your task is to classify tweets based on their relevance to explicit climate or environmental issues and provide an English translation.
            You must return your response in a structured JSON format.
            The classification labels are:
            - "definitely yes": The tweet is **explicitly and directly** about **climate change**, global warming, carbon emissions, major pollution (e.g., oil spill, massive wildfire), specific environmental policy, or a clear climate-related disaster.
            - "somewhat likely": The tweet mentions a theme that is adjacent to climate or environment (e.g., **"drought," "extreme heat," "water scarcity," or "deforestation"**) but does not explicitly connect it to climate change. **DO NOT** use this label for general, non-specific public health issues like "cholera" or general infrastructure problems unless a clear environmental factor (like extreme weather or water pollution) is the primary focus.
            - "unlikely": The tweet has **no discernible connection** to an explicit or adjacent environmental or climate issue. This is the default label for any tweet that requires significant **over-interpretation** to link to climate change (e.g., a tweet about a common illness, a political tweet about the economy without mentioning environmental policy, etc.).
            """
        }]
    }

    # Use a specific user prompt to ask the model to perform the task.
    user_prompt = f"""
    Analyze the following tweet text and provide a classification and an English translation.
    Tweet text: "{tweet_text}"
    """

    payload = {
        "contents": [{"parts": [{"text": user_prompt}]}],
        "systemInstruction": system_instruction,
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "classification": {"type": "STRING", "enum": ["definitely yes", "somewhat likely", "unlikely"]},
                    "english_translation": {"type": "STRING"}
                }
            }
        }
    }

    headers = {'Content-Type': 'application/json'}

    max_retries = 5
    base_delay = 2 # seconds

    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload))
            response.raise_for_status()

            data = response.json()
            raw_text = data['candidates'][0]['content']['parts'][0]['text']
            return json.loads(raw_text)

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                delay = base_delay * (2 ** attempt)
                print(f"Rate limit hit. Retrying in {delay} seconds... (Attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
            else:
                print(f"Error making API request: {e}")
                return {"classification": "unlikely", "english_translation": "Error: API request failed."}
        except (KeyError, json.JSONDecodeError) as e:
            print(f"Error parsing API response: {e}")
            return {"classification": "unlikely", "english_translation": "Error: Response parsing failed."}

    # If all retries fail
    print(f"Failed to analyze tweet after {max_retries} attempts due to rate limiting.")
    return {"classification": "unlikely", "english_translation": "Error: Max retries exceeded due to rate limit."}

def process_tweets_from_csv(input_file, output_file, api_key):
    # ... (function body is identical to your provided code) ...
    """
    Reads tweets from a CSV, analyzes them, and saves the results to a new CSV
    after each successful API call, enabling progress saving.

    Args:
        input_file (str): Path to the input CSV file.
        output_file (str): Path to the output CSV file.
        api_key (str): Your Google Gemini API key.
    """
    # --- 1. Load Input Data ---
    if not os.path.exists(input_file):
        print(f"Error: Input file '{input_file}' not found.")
        return

    try:
        input_df = pd.read_csv(input_file)
    except pd.errors.EmptyDataError:
        print(f"Error: Input file '{input_file}' is empty.")
        return
    except FileNotFoundError:
        # This should have been caught by os.path.exists, but included for robustness
        print(f"Error: Input file '{input_file}' not found.")
        return

    if 'tweet_text' not in input_df.columns:
        print("Error: The CSV must contain a column named 'tweet_text'.")
        return

    # Check for tweet_url (optional unique identifier)
    use_tweet_url = 'tweet_url' in input_df.columns
    if not use_tweet_url:
        print("Warning: The CSV does not contain a 'tweet_url' column. Cannot use it for progress tracking.")

    # --- 2. Load Existing Output Data for Progress Tracking ---
    try:
        output_df = pd.read_csv(output_file)
        print(f"Found existing output file '{output_file}' with {len(output_df)} processed tweets.")
    except (FileNotFoundError, pd.errors.EmptyDataError):
        output_df = pd.DataFrame(columns=list(input_df.columns) + ['climate_relevance_label', 'english_translation'])
        print(f"No existing output file or file is empty. Starting from scratch.")

    # --- 3. Determine Tweets to Process ---
    if use_tweet_url:
        # Identify tweets in the input file that are NOT in the output file based on 'tweet_url'
        processed_urls = set(output_df['tweet_url'].astype(str).tolist())
        tweets_to_process = input_df[~input_df['tweet_url'].astype(str).isin(processed_urls)].reset_index(drop=True)
        # Handle cases where input_df and output_df have duplicate URLs, by ensuring we only process unique new ones
        tweets_to_process.drop_duplicates(subset=['tweet_url'], keep='first', inplace=True)
    else:
        # Without a unique ID, we just skip the number of rows already processed.
        # This is less robust but still allows for checkpointing.
        start_index = len(output_df)
        tweets_to_process = input_df.iloc[start_index:].reset_index(drop=True)

    total_to_process = len(tweets_to_process)
    start_count = len(input_df) - total_to_process

    if total_to_process == 0:
        print("All tweets appear to be processed. Analysis complete.")
        return

    print(f"Starting analysis. Processing {total_to_process} new tweets (starting from global index {start_count})...")

    # --- 4. Process and Save (Row by Row) ---
    for index, row in tweets_to_process.iterrows():
        # Global index for logging clarity
        global_index = start_count + index + 1

        tweet_text = str(row['tweet_text'])
        tweet_url = str(row['tweet_url']) if use_tweet_url else f"No URL (Index {global_index})"

        # Log the tweet being analyzed
        print(f"[{global_index}/{len(input_df)}] Analyzing tweet: '{tweet_text[:50]}...' (URL: {tweet_url})")

        # 1. Analyze
        result = analyze_tweet_with_gemini(tweet_text, api_key)

        # 2. Create the result row
        result_row = row.copy()
        result_row['climate_relevance_label'] = result.get('classification')
        result_row['english_translation'] = result.get('english_translation')

        # 3. Append to output file
        # Check if the file exists to write the header only once
        file_exists = os.path.exists(output_file)

        # Convert the single result row to a DataFrame for easy CSV append
        result_df = pd.DataFrame([result_row])
        result_df.to_csv(output_file, mode='a', index=False, header=not file_exists)

        # 4. Add a small delay to avoid hitting API rate limits.
        time.sleep(0.01)

    print(f"\nAnalysis complete. Results for all {len(input_df)} tweets saved to '{output_file}'.")


if __name__ == "__main__":
    INPUT_CSV = "angola_tweets.csv"
    OUTPUT_CSV = "analyzed_angola_tweets.csv"

    # Get API key from environment variable
    API_KEY = os.getenv('GOOGLE_API_KEY')

    if not API_KEY:
        print("Error: API key not found.")
        print("Please set your Gemini API key as an environment variable named 'GOOGLE_API_KEY'.")
    else:
        process_tweets_from_csv(INPUT_CSV, OUTPUT_CSV, API_KEY)


