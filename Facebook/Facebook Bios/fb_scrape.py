import os
import csv
from lxml import html

# === CONFIGURATION ===
HTML_DIR = 'fb_profiles_html'
OUTPUT_FILE = 'fb_bios.csv'

# XPaths for Facebook profile data
XPATHS = {
    'Username': '//*[@id="mount_0_0_tE"]/div/div[1]/div/div[3]/div/div/div[1]/div[1]/div/div/div[1]/div[2]/div/div/div/div[3]/div/div/div[1]/div/div/span/h1/text()',
    'Username_Alt': '//h1/text()',  # Fallback
    
    'Followers': '//*[@id="mount_0_0_tE"]/div/div[1]/div/div[3]/div/div/div[1]/div[1]/div/div/div[1]/div[2]/div/div/div/div[3]/div/div/div[2]/span/a[1]/strong/text()',
    'Followers_Alt': '//a[contains(@href, "/followers")]/strong/text()',  # Fallback
    
    'Following': '//*[@id="mount_0_0_tE"]/div/div[1]/div/div[3]/div/div/div[1]/div[1]/div/div/div[1]/div[2]/div/div/div/div[3]/div/div/div[2]/span/a[2]/strong/text()',
    'Following_Alt': '//a[contains(@href, "/following")]/strong/text()',  # Fallback
    
    'Intro': '//*[@id="mount_0_0_tE"]/div/div[1]/div/div[3]/div/div/div[1]/div[1]/div/div/div[4]/div[2]/div/div[1]/div[2]/div/div[1]/div/div/div/div/div[2]/div[1]/div/div/span/text()',
    'Intro_Alt': '//div[contains(@class, "intro")]//span/text()',  # Fallback
}


def clean_number(text):
    """
    Clean follower/following numbers from Facebook format.
    Examples: '1.2K' -> '1200', '15M' -> '15000000', '523' -> '523'
    """
    if not text:
        return ''
    
    text = text.strip().upper()
    
    # Remove commas
    text = text.replace(',', '')
    
    # Handle K (thousands)
    if 'K' in text:
        try:
            num = float(text.replace('K', ''))
            return str(int(num * 1000))
        except:
            return text
    
    # Handle M (millions)
    if 'M' in text:
        try:
            num = float(text.replace('M', ''))
            return str(int(num * 1000000))
        except:
            return text
    
    return text


def extract_with_fallback(tree, primary_xpath, fallback_xpath):
    """
    Try primary XPath first, then fallback if nothing found.
    Returns the first match or empty string.
    """
    try:
        result = tree.xpath(primary_xpath)
        if result and isinstance(result, list) and len(result) > 0:
            return result[0].strip() if isinstance(result[0], str) else str(result[0]).strip()
    except Exception:
        pass
    
    try:
        result = tree.xpath(fallback_xpath)
        if result and isinstance(result, list) and len(result) > 0:
            return result[0].strip() if isinstance(result[0], str) else str(result[0]).strip()
    except Exception:
        pass
    
    return ''


def extract_profile_data(filepath, username_from_dir):
    """
    Extract Facebook profile data from saved HTML file.
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        tree = html.fromstring(content)
        data = {}
        
        # Username from directory name as fallback
        data['Account'] = username_from_dir
        
        # Extract username (display name)
        username = extract_with_fallback(tree, XPATHS['Username'], XPATHS['Username_Alt'])
        data['Username'] = username if username else username_from_dir
        
        # Extract followers
        followers = extract_with_fallback(tree, XPATHS['Followers'], XPATHS['Followers_Alt'])
        data['Followers'] = clean_number(followers)
        
        # Extract following
        following = extract_with_fallback(tree, XPATHS['Following'], XPATHS['Following_Alt'])
        data['Following'] = clean_number(following)
        
        # Extract intro/bio
        intro = extract_with_fallback(tree, XPATHS['Intro'], XPATHS['Intro_Alt'])
        # If intro is actually a list of text nodes, join them
        if not intro:
            try:
                intro_nodes = tree.xpath(XPATHS['Intro'])
                if intro_nodes:
                    intro = ' '.join(node.strip() for node in intro_nodes if isinstance(node, str) and node.strip())
            except Exception:
                pass
        data['Intro'] = intro

        return data
        
    except Exception as e:
        print(f"[ERROR] Failed to parse {filepath}: {e}")
        return None


def main():
    """
    Main function to scrape all saved Facebook profile HTMLs.
    """
    if not os.path.exists(HTML_DIR):
        print(f"[ERROR] Directory '{HTML_DIR}' not found!")
        return
    
    # Find all user directories
    user_dirs = [d for d in os.listdir(HTML_DIR) 
                 if os.path.isdir(os.path.join(HTML_DIR, d))]
    
    print(f"[INFO] Found {len(user_dirs)} user directories to process.")

    all_data = []
    
    for user_dir in user_dirs:
        user_path = os.path.join(HTML_DIR, user_dir)
        
        # Find HTML file in user directory
        html_files = [f for f in os.listdir(user_path) if f.endswith('.html')]
        
        if not html_files:
            print(f"[WARN] No HTML file found in {user_dir}")
            continue
        
        # Use first HTML file found
        html_file = html_files[0]
        filepath = os.path.join(user_path, html_file)
        
        print(f"[PROCESSING] {user_dir}/{html_file}")
        
        data = extract_profile_data(filepath, user_dir)
        if data:
            all_data.append(data)
            print(f"  ✓ Extracted: {data['Username']} | Followers: {data['Followers']} | Following: {data['Following']}")
        else:
            print(f"  ✗ Failed to extract data")

    # Write to CSV
    if all_data:
        fieldnames = ['Account', 'Username', 'Followers', 'Following', 'Intro']
        
        with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_data)
        
        print(f"\n✓ [DONE] Data saved to {OUTPUT_FILE}")
        print(f"   Total profiles processed: {len(all_data)}")
    else:
        print("\n[WARN] No data extracted.")


if __name__ == '__main__':
    main()
