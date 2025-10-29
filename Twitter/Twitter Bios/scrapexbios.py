import os
import csv
from lxml import html

# === CONFIGURATION ===
HTML_DIR = 'profiles_html'
OUTPUT_FILE = 'x_bios.csv'

# XPaths
XPATHS = {
    'Bio': '//*[@id="react-root"]/div/div/div[2]/main/div/div/div/div/div/div[3]/div/div/div[1]/div/div[3]/div/div/span/text()',
    'Date Joined': '//*[@id="react-root"]/div/div/div[2]/main/div/div/div/div/div/div[3]/div/div/div[1]/div/div[4]/div/span[2]/span/text()',
    'Following': '//*[@id="react-root"]/div/div/div[2]/main/div/div/div/div/div/div[3]/div/div/div[1]/div/div[5]/div[1]/a/span[1]/span/text()',
    'Followers': '//*[@id="react-root"]/div/div/div[2]/main/div/div/div/div/div/div[3]/div/div/div[1]/div/div[5]/div[2]/a/span[1]/span/text()',
    'Posts': '//*[@id="react-root"]/div/div/div[2]/main/div/div/div/div/div/div[1]/div[1]/div/div/div/div/div/div[2]/div/div/text()',
}


def extract_profile_data(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        tree = html.fromstring(content)
        data = {}
        
        # Extract username from filename
        data['Username'] = os.path.splitext(os.path.basename(filepath))[0]

        # Extract verification status
        verified = False
        if 'aria-label="Verified account"' in content or 'aria-label="Verified"' in content:
            verified = True
        data['Verified'] = verified

        # Extract data via XPath
        for key, xp in XPATHS.items():
            try:
                value = tree.xpath(xp)
                if isinstance(value, list):
                    value = ' '.join(v.strip() for v in value if v.strip())
                data[key] = value.strip() if isinstance(value, str) else ''
            except Exception:
                data[key] = ''

        return data
    except Exception as e:
        print(f"[ERROR] Failed to parse {filepath}: {e}")
        return None


def main():
    files = [f for f in os.listdir(HTML_DIR) if f.endswith('.html')]
    print(f"[INFO] Found {len(files)} HTML files to process.")

    all_data = []
    for file in files:
        path = os.path.join(HTML_DIR, file)
        data = extract_profile_data(path)
        if data:
            all_data.append(data)

    # Write to CSV
    if all_data:
        with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=list(all_data[0].keys()))
            writer.writeheader()
            writer.writerows(all_data)
        print(f"[DONE] Data saved to {OUTPUT_FILE}")
    else:
        print("[WARN] No data extracted.")


if __name__ == '__main__':
    main()