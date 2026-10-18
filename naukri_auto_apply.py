import os
import json
import base64
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from pypdf import PdfReader
from dotenv import load_dotenv

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google import genai
from google.genai import types

load_dotenv()

# Configuration from .env
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
RESUME_PATH = os.getenv("RESUME_PATH", "resume.pdf")
MATCH_THRESHOLD = int(os.getenv("MATCH_THRESHOLD", 85))
DRY_RUN = os.getenv("DRY_RUN", "False").lower() in ("true", "1", "yes")

SCOPES = ['https://mail.google.com/']

# Initialize Gemini Client
ai_client = genai.Client(api_key=GEMINI_API_KEY)


def get_gmail_service():
    """Authenticates and returns the Gmail service."""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('gmail', 'v1', credentials=creds)


def extract_resume_text(pdf_path: str) -> str:
    """Extracts text content from your PDF resume."""
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"Resume file not found at: {pdf_path}")
    reader = PdfReader(pdf_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""
    return text.strip()


def extract_email_body(payload: dict) -> str:
    """Recursively decodes the text body of an email."""
    body = ""
    if 'parts' in payload:
        for part in payload['parts']:
            mime_type = part.get('mimeType', '')
            if mime_type == 'text/plain' and 'data' in part.get('body', {}):
                return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
            elif mime_type == 'text/html' and not body and 'data' in part.get('body', {}):
                body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
            elif 'parts' in part:
                sub_body = extract_email_body(part)
                if sub_body:
                    return sub_body
    elif 'body' in payload and 'data' in payload['body']:
        return base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='ignore')
    return body


def evaluate_job_match(email_content: str, resume_text: str) -> dict:
    """Analyzes JD fit and drafts an application response using Gemini."""
    prompt = f"""
You are a senior recruitment partner helping an Enterprise Integration & AI Architect evaluate inbound recruiter emails.

Candidate Resume:
\"\"\"{resume_text[:4000]}\"\"\"

Email Content (Job Opportunity):
\"\"\"{email_content[:4000]}\"\"\"

Tasks:
1. Extract the core requirements from the email.
2. Compare them against the candidate's skills and 13+ years of experience.
3. Assign a strict match percentage from 0 to 100.
4. If match_score >= {MATCH_THRESHOLD}, write a crisp, professional reply email:
   - Addressed to the recruiter.
   - Mention key alignments (e.g., SAP BTP / Integration / AI Automation).
   - Express interest in discussing the role and mention the attached resume.

Return ONLY a valid JSON object matching this schema:
{{
  "match_score": <int>,
  "reasoning": "<short sentence>",
  "reply_body": "<plain text email body or empty string if < {MATCH_THRESHOLD}>"
}}
"""
    response = ai_client.models.generate_content(
        model="gemini-3.8-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json"
        )
    )
    return json.loads(response.text)


def send_reply_with_resume(service, original_msg_id: str, thread_id: str, to_address: str, subject: str, body_text: str):
    """Sends a threaded reply email with resume.pdf attached."""
    message = MIMEMultipart()
    message['to'] = to_address
    message['subject'] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    message['In-Reply-To'] = original_msg_id
    message['References'] = original_msg_id

    # Attach message body
    message.attach(MIMEText(body_text, 'plain'))

    # Attach PDF resume
    if os.path.exists(RESUME_PATH):
        with open(RESUME_PATH, 'rb') as f:
            pdf_attachment = MIMEApplication(f.read(), _subtype="pdf")
            pdf_attachment.add_header('Content-Disposition', 'attachment', filename=os.path.basename(RESUME_PATH))
            message.attach(pdf_attachment)

    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
    service.users().messages.send(
        userId='me',
        body={'raw': raw_message, 'threadId': thread_id}
    ).execute()


def run_automation():
    service = get_gmail_service()
    resume_text = extract_resume_text(RESUME_PATH)
    print("✓ Resume loaded successfully.")
    print(f"✓ Match threshold set to: {MATCH_THRESHOLD}%")
    if DRY_RUN:
        print("⚠️  DRY_RUN is enabled. No actual emails will be sent.\n")

    # Search for unread emails from naukri
    # Restrict search to today and yesterday (-1 day)
    since_date = (datetime.now() - timedelta(days=1)).strftime('%Y/%m/%d')
    query = f'from:naukri.com is:unread after:{since_date}'
    
    print(f"Searching unread emails received since {since_date} (today and yesterday)...")
    results = service.users().messages().list(userId='me', q=query).execute()
    messages = results.get('messages', [])

    if not messages:
        print("No unread emails from Naukri found.")
        return

    print(f"Found {len(messages)} unread email(s) from Naukri.\n" + "=" * 50)

    for item in messages:
        msg = service.users().messages().get(userId='me', id=item['id'], format='full').execute()
        headers = {h['name'].lower(): h['value'] for h in msg['payload']['headers']}

        sender = headers.get('from', '')
        reply_to = headers.get('reply-to', sender)
        subject = headers.get('subject', 'Job Application')
        thread_id = msg['threadId']

        # Skip transactional/alert emails
        if any(unwanted in reply_to.lower() for unwanted in ["noreply", "alerts@", "mailer@naukri.com"]):
            print(f"Skipping generic alert email from: {reply_to}\nSubject: {subject}\n")
            continue

        body = extract_email_body(msg['payload'])
        if len(body.strip()) < 50:
            print(f"Skipping email (insufficient content to parse). Subject: {subject}\n")
            continue

        print(f"Analyzing recruiter email from: {reply_to}")
        print(f"Subject: {subject}")

        # AI Evaluation
        try:
            eval_result = evaluate_job_match(body, resume_text)
            score = eval_result.get("match_score", 0)
            reason = eval_result.get("reasoning", "")
            print(f"→ Match Score: {score}% | {reason}")

            if score >= MATCH_THRESHOLD:
                print(f"★ Strong Match (>= {MATCH_THRESHOLD}%). Prepared Reply Body:\n")
                print(eval_result.get("reply_body"))
                print("-" * 40)

                if DRY_RUN:
                    print("→ [DRY RUN] Would send reply and attach resume.pdf.")
                else:
                    send_reply_with_resume(service, item['id'], thread_id, reply_to, subject, eval_result.get("reply_body"))
                    print(f"✓ Reply and resume sent successfully to {reply_to}!")

                    # Mark email as read
                    service.users().messages().modify(
                        userId='me',
                        id=item['id'],
                        body={'removeLabelIds': ['UNREAD']}
                    ).execute()
            else:
                print(f"✗ Score below threshold ({score}% < {MATCH_THRESHOLD}%). No reply sent.")

        except Exception as e:
            print(f"Error evaluating email: {e}")

        print("=" * 50)


if __name__ == "__main__":
    run_automation()