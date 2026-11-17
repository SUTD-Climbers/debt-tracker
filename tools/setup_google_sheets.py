import argparse
import json
import os
from pathlib import Path
import sys


import argparse
import json
import os
from pathlib import Path
import re
import sys


def extract_spreadsheet_id(input_str: str) -> str:
    # extract spreadsheet id from raw string or full google sheets url
    input_str = input_str.strip()
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", input_str)
    if match:
        return match.group(1)
    return input_str


def setup_and_test_google_sheets(
    key_file_path: str,
    spreadsheet_input: str,
    update_secrets: bool = True,
) -> None:
    # verify service account json key and test connection to live google sheet
    key_path = Path(key_file_path)
    if not key_path.exists():
        print(f"Error: Service account file '{key_file_path}' does not exist.")
        sys.exit(1)

    try:
        with open(key_path, "r", encoding="utf-8") as f:
            sa_data = json.load(f)
    except Exception as e:
        print(f"Error reading JSON file: {e}")
        sys.exit(1)

    client_email = sa_data.get("client_email", "")
    if not client_email:
        print("Error: JSON key file is missing 'client_email'. Is it a Google service account key?")
        sys.exit(1)

    spreadsheet_id = extract_spreadsheet_id(spreadsheet_input)

    print(f"\n=======================================================")
    print(f" Service Account Email: {client_email}")
    print(f" Target Spreadsheet ID: {spreadsheet_id}")
    print(f"=======================================================\n")
    print("Testing connection to Google Sheets API...")

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]

        credentials = Credentials.from_service_account_file(str(key_path), scopes=scopes)
        client = gspread.authorize(credentials)
        spreadsheet = client.open_by_key(spreadsheet_id)

        print(f"[OK] Successfully connected to spreadsheet: '{spreadsheet.title}'")

        worksheets = [ws.title for ws in spreadsheet.worksheets()]
        print(f"[OK] Detected worksheets: {worksheets}")

        if "Pricing" in worksheets:
            print("  - [Found] 'Pricing' tab")
        else:
            print("  - [Notice] 'Pricing' tab not found in spreadsheet.")

        if "Boulder Plus" in worksheets:
            print("  - [Found] 'Boulder Plus' tab")
        elif "Boulder +" in worksheets:
            print("  - [Found] 'Boulder +' tab")
        else:
            print("  - [Notice] 'Boulder Plus' tab not found. It will be created on initial sync.")

    except Exception as e:
        print("\n[ERROR] Connection failed!")
        print(f"Details: {e}\n")
        print("Please check:")
        print(f"1. Did you share the Google Sheet with '{client_email}' as Editor?")
        print(f"2. Are the Google Sheets API and Google Drive API enabled in Google Cloud Console?")
        print(f"3. Is the spreadsheet ID '{spreadsheet_id}' correct?")
        sys.exit(1)

    if update_secrets:
        secrets_dir = Path(".streamlit")
        secrets_dir.mkdir(parents=True, exist_ok=True)
        secrets_file = secrets_dir / "secrets.toml"

        current_content = ""
        if secrets_file.exists():
            current_content = secrets_file.read_text(encoding="utf-8")

        # preserve existing [auth.users] section if present
        auth_section = ""
        if "[auth.users]" in current_content:
            parts = current_content.split("[auth.users]")
            users_block = parts[1].split("\n[")[0].strip()
            if users_block:
                auth_section = f"\n[auth.users]\n{users_block}\n"

        if not auth_section:
            auth_section = """
[auth.users]
exco_admin = "$2b$12$e868k.o4c0vEFrk1Hw9V.OGhG7J8hM0mO7rGvG8Kx8kO0rGvG8Kx8"
test_admin = "$2b$12$o1YFEyUny8EKHPkbKvL82e9HNpFCn5q48PsvtHElnlaBtLllr84ta"
"""

        new_secrets_content = f"""# storage backend choice: "local_csv" or "google_sheets"
backend = "google_sheets"

# gym pass default pricing (optional, can be overridden per member tier)
price_per_pass = 16.0

[auth]
# exco user accounts with bcrypt hashed passwords
{auth_section.strip()}

[google_sheets]
spreadsheet_id = "{spreadsheet_id}"
service_account_file = "{key_file_path.replace('\\', '/')}"
"""
        secrets_file.write_text(new_secrets_content, encoding="utf-8")

        print(f"\n[OK] Configuration successfully updated!")
        print(f"  - Backend switched to: google_sheets")
        print(f"  - Spreadsheet ID: {spreadsheet_id}")
        print(f"  - Key file: {key_file_path}")
        print(f"  - Saved to: .streamlit/secrets.toml")
        print("\nYour website is now linked to your Google Sheet! Start it with:")
        print("  .env\\Scripts\\python.exe -m streamlit run app.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test and link Google Sheets to Gym Pass Tracker.")
    parser.add_argument("key_file", nargs="?", default="", help="Path to service account JSON (e.g. credentials.json)")
    parser.add_argument("spreadsheet_id", nargs="?", default="", help="Google Spreadsheet ID or URL")
    parser.add_argument("--no-secrets", action="store_true", help="Do not write .streamlit/secrets.toml")

    args = parser.parse_args()

    key_path = args.key_file
    if not key_path:
        if Path("credentials.json").exists():
            key_path = "credentials.json"
        elif (Path(".streamlit") / "credentials.json").exists():
            key_path = ".streamlit/credentials.json"
        elif (Path(".streamlit") / "service_account.json").exists():
            key_path = ".streamlit/service_account.json"
        elif Path("service_account.json").exists():
            key_path = "service_account.json"
        else:
            key_path = input("Enter path to service account JSON key file: ").strip()

    sheet_id_or_url = args.spreadsheet_id
    if not sheet_id_or_url:
        sheet_id_or_url = input("Enter your Google Spreadsheet ID or URL: ").strip()

    if not key_path or not sheet_id_or_url:
        print("Error: Both key file and spreadsheet ID/URL are required.")
        sys.exit(1)

    setup_and_test_google_sheets(key_path, sheet_id_or_url, update_secrets=not args.no_secrets)
