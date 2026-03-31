
import os.path
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# Scopes for Google Sheets and Drive
SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']

def main():
    creds = None
    # The file token.json stores the user's access and refresh tokens.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Use the actual filename the user has
            client_secret_file = 'client_secret.json'
            if not os.path.exists(client_secret_file):
                # Check for the typo version if the user didn't rename
                if os.path.exists('clienr_secret.json'):
                    client_secret_file = 'clienr_secret.json'
                else:
                    print(f"Error: {client_secret_file} not found. Please ensure your JSON file is in this folder.")
                    return

            flow = InstalledAppFlow.from_client_secrets_file(client_secret_file, SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    
    print("✅ Авторизация успешна! Файл token.json создан.")

if __name__ == '__main__':
    main()
