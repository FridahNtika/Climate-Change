import os
import json
import csv
import re
from bs4 import BeautifulSoup


def convert_k_notation(value):
    try:
        value = value.lower().replace(',', '')
        if 'k' in value:
            return int(float(value.replace('k', '')) * 1000)
        elif 'm' in value:
            return int(float(value.replace('m', '')) * 1_000_000)
        return int(value)
    except:
        return 0

def parse_tweet_html(tweet_html_path, meta_path):
    with open(tweet_html_path, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')

    with open(meta_path, 'r', encoding='utf-8') as f:
        metadata = json.load(f)

    data = {
        "display_name": "",
        "username": metadata.get("username", ""),
        "verified": False,
        "profile_image_url": "",
        "text": "",
        "datetime": "",
        # FIX: Construct the URL from the filename
        "tweet_url": metadata.get("tweet_url", ""),
        #"tweet_url": f"https://x.com/{metadata.get('username', '')}/status/{os.path.basename(tweet_html_path).replace('tweet_', '').replace('.html', '')}",
        "image_urls": [],
        "replies": 0,
        "retweets": 0,
        "likes": 0,
        "views": 0,
        "profile": ""
    }


    # Author info
    author_elem = soup.find('div', {'data-testid': 'User-Name'})
    if author_elem:
        spans = author_elem.find_all('span')
        if len(spans) >= 2:
            data["display_name"] = spans[0].text
            data["username"] = spans[1].text.replace('@', '')
        data["verified"] = bool(author_elem.find('svg', {'aria-label': 'Verified account'}))

    # Profile image
    img_elem = soup.find('img', {'alt': 'Image'})
    if img_elem:
        data["profile_image_url"] = img_elem.get('src', '')

    # Tweet text
    tweet_text = soup.find('div', {'data-testid': 'tweetText'})
    if tweet_text:
        data["text"] = tweet_text.get_text(separator=" ")

    # Datetime
    time_elem = soup.find('time')
    if time_elem:
        data["datetime"] = time_elem.get('datetime', '')

    # Media images
    media_imgs = soup.find_all('img', {'alt': 'Image'})
    for img in media_imgs:
        src = img.get('src')
        if src and 'profile_images' not in src:
            data["image_urls"].append(src)

    # parsing from aria-label
    found_counts = False
    aria_divs = soup.find_all(attrs={'aria-label': True})
    for div in aria_divs:
        label = div['aria-label'].replace('\u202f', ' ')  # normalize narrow spaces
        label = label.lower()

        # Try to extract each metric individually
        replies_match = re.search(r'([\d.,KkMm]+)\s+repl(?:y|ies)', label)
        reposts_match = re.search(r'([\d.,KkMm]+)\s+reposts?', label)
        likes_match = re.search(r'([\d.,KkMm]+)\s+likes?', label)
        views_match = re.search(r'([\d.,KkMm]+)\s+views?', label)

        if replies_match or reposts_match or likes_match or views_match:
            if replies_match:
                data['replies'] = convert_k_notation(replies_match.group(1))
            if reposts_match:
                data['retweets'] = convert_k_notation(reposts_match.group(1))
            if likes_match:
                data['likes'] = convert_k_notation(likes_match.group(1))
            if views_match:
                data['views'] = convert_k_notation(views_match.group(1))
            found_counts = True
            break

    if not found_counts:
        print(f" Metrics not found in aria-label for: {tweet_url}")

    if data["username"]:
        data["profile"] = f"https://twitter.com/{data['username']}"

    return data

def extract_all_tweets_to_csv(root_dir, output_csv):
    tweet_rows = []
    for root, _, files in os.walk(root_dir):
        for file in files:
            if file.endswith('.html') and file.startswith('tweet_'):
                tweet_id = file.replace('tweet_', '').replace('.html', '')
                html_path = os.path.join(root, file)
                meta_path = os.path.join(root, f"tweet_{tweet_id}.meta.json")
                if os.path.exists(meta_path):
                    try:
                        tweet_data = parse_tweet_html(html_path, meta_path)
                        tweet_rows.append(tweet_data)
                    except Exception as e:
                        print(f" Error parsing {html_path}: {e}")

    fieldnames = [
        "display_name", "username", "verified", "profile_image_url",
        "text", "datetime", "tweet_url", "image_urls",
        "replies", "retweets", "likes", "views", "profile"
    ]

    with open(output_csv, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in tweet_rows:
            row["image_urls"] = ', '.join(row["image_urls"])
            writer.writerow(row)

    print(f" Extracted {len(tweet_rows)} tweets to {output_csv}")

if __name__ == "__main__":
    extract_all_tweets_to_csv("tweets_html", "parsed_tweets_output.csv")











































































































