
import gspread
from google.oauth2.service_account import Credentials
from pathlib import Path
import os

def check_quota():
    credentials_file = Path("credentials.json")
    if not credentials_file.exists():
        print("Error: credentials.json not found")
        return

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    try:
        creds = Credentials.from_service_account_file(credentials_file, scopes=scopes)
        client = gspread.authorize(creds)
        
        print(f"Service Account Email: {creds.service_account_email}")
        
        # Try to list files owned by the service account
        files = client.list_spreadsheet_files()
        print(f"Number of spreadsheets owned by bot: {len(files)}")
        for f in files[:5]:
            print(f"- {f['name']} (ID: {f['id']})")
            
        # Try to check about() for quota (Drive API v3)
        from googleapiclient.discovery import build
        drive_service = build('drive', 'v3', credentials=creds)
        about = drive_service.about().get(fields="storageQuota, user").execute()
        
        print("\n--- Quota Info ---")
        quota = about.get('storageQuota', {})
        limit = int(quota.get('limit', 0))
        usage = int(quota.get('usage', 0))
        
        print(f"Limit: {limit / (1024*1024):.2f} MB")
        print(f"Usage: {usage / (1024*1024):.2f} MB")
        
        if limit == 0:
            print("WARNING: This service account has 0 bytes of storage quota.")
        elif usage >= limit:
            print("WARNING: Storage is full.")
            
    except Exception as e:
        print(f"Error during check: {e}")

if __name__ == "__main__":
    check_quota()
