# Gym Pass Tracker

An internal audit and debt tracking web application built for the Climbers SUTD Executive Committee (Exco). The tool ingests gym pass history reports, automatically reconciles usage against account pool adjustments, tracks passes owed per member, and manages pass payment settlement.

---

## Features

- **Automated Report Ingestion**: Uploads official PDF pass history reports with coordinate-based layout parsing that cleanly handles adjacent column overflows and continuous account histories.
- **Occurrence-Based Deduplication**: Preserves legitimate duplicate passes on the same day while skipping previously imported records via multiset frequency comparison.
- **Member Debt Overview**: Tracks outstanding passes and dollar debt per member with instant filtering, Altair charts, and drill-down history.
- **Pass Settlement Workflow**: Provides one-click full settlement (*Mark All Paid*), custom partial pass payment amounts, and individual pass toggles with full exco user and timestamp audit logging.
- **Gym Pool Management**: Allows exco to update the current total available passes in the gym pool and track pool adjustments.
- **Multi-Gym Extensibility**: Modular gym tabs architecture designed to add more gym locations without refactoring.
- **Pluggable Storage Backends**: Uses local CSV files in `data/` for local development and tests, with built-in support for Google Sheets.

---

## Quick Start (Local Setup)

The application requires Python 3.11+ and PowerShell on Windows.

### 1. Create and Activate Virtual Environment

In your PowerShell terminal:

```powershell
python -m venv .env
.env\Scripts\Activate.ps1
```

### 2. Install Dependencies

Install pinned production and development packages:

```powershell
.env\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
```

### 3. Configure Exco User Accounts

To create an exco account with a secure bcrypt password, run the interactive account creator:

```powershell
.env\Scripts\python.exe tools\make_password_hash.py
```

Enter your desired username and password. The tool will automatically hash your password and save it into `.streamlit/secrets.toml`.

### 4. Run the Application

```powershell
.env\Scripts\python.exe -m streamlit run app.py
```

---

## Data Model

The application stores data across three entities:

### 1. Records
Stores all individual pass usage events and account pool adjustments.
- `record_id`: Unique record identifier (e.g. `rec_a1b2c3d4e5f6`).
- `gym`: Gym identifier (e.g. `Boulder +`).
- `row_kind`: `usage` (member pass used) or `topup` (gym pool adjustment).
- `person`: Member name in normalized title case (`Last, First`).
- `usage_date`: Date of pass usage in day-first format (`d/m/yyyy`).
- `adj`: Pass adjustment value (e.g. `-1` for usage, `+50` for top-up).
- `gym_staff`: Gym staff employee name.
- `remarks`: Report remarks (if any).
- `source_upload_id`: ID of the upload that imported this record.
- `status`: Settlement status (`unpaid` or `paid`).
- `made_by`: Username of exco member who recorded payment.
- `made_at`: Timestamp when pass was marked paid.
- `row_key`: Deterministic canonical key used for multiset deduplication.

### 2. Uploads
Audit trail of imported PDF reports.
- `upload_id`: Unique upload identifier (e.g. `upl_20261117_01`).
- `gym`: Target gym identifier.
- `filename`: Original PDF filename.
- `uploaded_by`: Username of uploader.
- `uploaded_at`: Upload timestamp.
- `report_prepared_at`: Generation timestamp extracted from PDF footer.
- `rows_parsed`: Total rows parsed from the document.
- `usage_rows`: Count of usage rows added.
- `topup_rows`: Count of top-up rows added.
- `rows_added`: New rows inserted into storage.
- `rows_skipped`: Redundant rows skipped via deduplication.
- `earliest_date`: Oldest pass date in file.
- `latest_date`: Newest pass date in file.

### 3. Members (Optional)
Directory for resolving spelling variants to canonical names.
- `canonical_name`: Standard member name.
- `aliases`: Semicolon-separated name variants.

---

## How Deduplication Works

Because gym reports contain the full cumulative account history (dating back to 2019), each new file overlaps heavily with previous uploads. Furthermore, members can legitimately use multiple passes on a single day, producing genuinely identical rows.

A standard set-based or row-hash deduplication would incorrectly drop legitimate repeats. Instead, this app uses **multiset frequency difference**:

1. A deterministic `row_key` is generated from: `usage_date|normalised_customer|adj|gym_staff|remarks`.
2. The system counts the occurrences of each `row_key` in the stored database and in the newly uploaded file.
3. Only the positive frequency difference (`file_occurrences - stored_occurrences`) is inserted.
4. Re-uploading the exact same report adds 0 rows and skips all rows.

---

## Connecting Google Sheets

The app is built to connect seamlessly to your existing Google Spreadsheet format:

### Google Sheet Format Supported
- **`Pricing` Tab**: Defines pass rates per gym and member tier:
  - Column A: Gym display name (`Boulder +`, `Boulder Planet`, `Fitbloc`, `BFF`).
  - Column B: `Tier 1` rate (e.g. `$18`).
  - Column C: `Tier 2` rate (e.g. `$16`).
- **Gym Tabs** (e.g. `Boulder Plus`):
  - Row 1: Gym title in A1 (`BOULDER PLUS`), `Last Updated:` in B1, Date in C1 (`15/06/2026`).
  - `Tier 1` and `Tier 2` sections listing members: `Name`, `Passes Used`, `Total Cost ($)`.
  - The app reads this layout before any PDF upload, automatically populating the Overview dashboard with accurate member tallies, pass debts, dollar debt amounts, and the last updated date.

To connect live to Google Sheets:

### Step 1: Google Cloud Setup
1. Open Google Cloud Console and create or select a GCP project.
2. Enable the **Google Sheets API** and **Google Drive API**.
3. Navigate to **IAM & Admin > Service Accounts** and create a service account.
4. Under the **Keys** tab, click **Add Key > Create new key > JSON**. Save the downloaded JSON file locally (ensure it is never committed).

### Step 2: Share Google Spreadsheet
1. Open your existing Google Sheet in Google Drive.
2. Note the spreadsheet ID from the URL (`https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit`).
3. Click **Share** and add the service account email (from your JSON file) as an **Editor**.

### Step 3: Configure Streamlit Secrets
In `.streamlit/secrets.toml`, set:

```toml
backend = "google_sheets"

[auth.users]
exco_admin = "<bcrypt_hash>"

[google_sheets]
spreadsheet_id = "<SPREADSHEET_ID>"

[google_sheets.service_account]
type = "service_account"
project_id = "your-project-id"
private_key_id = "your-key-id"
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "your-service-account@your-project.iam.gserviceaccount.com"
client_id = "your-client-id"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/..."
```

*(Note: During local development without Google service account credentials, the app defaults to `backend = "local_csv"` and automatically seeds the exact baseline debts and rates from your spreadsheet snapshot).*

---

## How to Add Another Gym

The architecture is built to support multiple gyms without modifying existing schemas:

1. Create a new parser in `parsers/<new_gym>.py` inheriting from `BaseGymParser`.
2. Implement `extract_pdf_elements` (Layer A), `elements_to_raw_rows` (Layer B), and `raw_rows_to_dataframe` (Layer C).
3. Register the new parser with `register_parser(YourGymParser())`.
4. In `app.py`, add the new gym display name to `CONFIGURED_GYMS = ["Boulder +", "New Gym"]`.
5. The UI automatically generates a dedicated top-level tab for the new gym with the exact same Overview, Upload, Mark as Paid, and History sections.

---

## Deploying Online (Streamlit Community Cloud)

This app is ready for zero-cost cloud deployment on Streamlit Community Cloud:

1. **Push to GitHub**:
   - Push this workspace to your private (or public) GitHub repository.
   - Note: `.gitignore` automatically prevents your credentials (`.streamlit/secrets.toml`, `*.json`), PDF reports, and local data from being uploaded to GitHub.

2. **Deploy on Streamlit Community Cloud**:
   - Go to [share.streamlit.io](https://share.streamlit.io/) and sign in with GitHub.
   - Click **Create app** > **I already have an app**.
   - Select your repository, branch (`main`), and set **Main file path** to `app.py`.

3. **Configure Secrets in Cloud Settings**:
   - Click **Advanced settings** (or go to App Settings > Secrets after creation).
   - Paste the contents of your `.streamlit/secrets.toml` into the **Secrets** editor:
     ```toml
     backend = "google_sheets"
     price_per_pass = 16.0

     [auth.users]
     your_username = "$2b$12$..."

     [google_sheets]
     spreadsheet_id = "your_spreadsheet_id"

     [google_sheets.service_account]
     type = "service_account"
     project_id = "your-gcp-project"
     private_key_id = "..."
     private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
     client_email = "..."
     client_id = "..."
     auth_uri = "https://accounts.google.com/o/oauth2/auth"
     token_uri = "https://oauth2.googleapis.com/token"
     auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
     client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/..."
     ```
   - Click **Save**.

4. **Launch**:
   - Streamlit Cloud will install `requirements.txt` and launch your app with a public/private URL.
   - Exco members can now sign in from any phone or laptop to view debts, upload PDF audit files, and mark passes as paid live!

---

## Running the Test Suite

Run all unit and integration tests using pytest in the virtual environment:

```powershell
.env\Scripts\pytest.exe -v
```
