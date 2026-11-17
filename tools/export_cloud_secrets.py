"""
Helper tool to generate the exact TOML snippet needed for Streamlit Community Cloud.
Merges local .streamlit/secrets.toml and credentials.json into a single copy-pasteable
TOML block for the Streamlit Cloud Secrets Manager.
"""
import json
from pathlib import Path
import tomllib


def main():
    root = Path(__file__).resolve().parent.parent
    secrets_path = root / ".streamlit" / "secrets.toml"
    creds_path = root / "credentials.json"

    if not secrets_path.exists():
        print("Error: .streamlit/secrets.toml not found.")
        return

    if not creds_path.exists():
        print("Error: credentials.json not found in project root.")
        return

    with open(secrets_path, "rb") as f:
        secrets = tomllib.load(f)

    with open(creds_path, "r", encoding="utf-8") as f:
        creds = json.load(f)

    print("=" * 70)
    print("STREAMLIT COMMUNITY CLOUD SECRETS (Copy everything below):")
    print("=" * 70)

    # top-level settings
    backend = secrets.get("backend", "google_sheets")
    price = secrets.get("price_per_pass", 16.0)
    print(f'backend = "{backend}"')
    print(f"price_per_pass = {price}\n")

    # auth users
    print("[auth]")
    print("[auth.users]")
    users = secrets.get("auth", {}).get("users", {})
    for user, pw_hash in users.items():
        print(f'{user} = "{pw_hash}"')
    print()

    # google sheets config
    gs = secrets.get("google_sheets", {})
    print("[google_sheets]")
    print(f'spreadsheet_id = "{gs.get("spreadsheet_id", "")}"')
    print(f'all_members_spreadsheet_id = "{gs.get("all_members_spreadsheet_id", "")}"')
    print(f'tier_2_spreadsheet_id = "{gs.get("tier_2_spreadsheet_id", "")}"\n')

    # embedded service account credentials
    print("[google_sheets.service_account]")
    for k, v in creds.items():
        if isinstance(v, str):
            # escape special characters and quotes
            escaped_v = json.dumps(v)
            print(f"{k} = {escaped_v}")
        else:
            print(f"{k} = {json.dumps(v)}")

    print("=" * 70)
    print("Paste this block into: App Settings -> Secrets on Streamlit Community Cloud.")
    print("=" * 70)


if __name__ == "__main__":
    main()
