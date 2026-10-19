import os
import json
import time
import random
import requests
from pypdf import PdfReader
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from google import genai
from google.genai import types

load_dotenv()

# Configuration from .env
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
RESUME_PATH = os.getenv("RESUME_PATH", "resume.pdf")
MATCH_THRESHOLD = int(os.getenv("MATCH_THRESHOLD", 85))
DRY_RUN = os.getenv("DRY_RUN", "False").lower() in ("true", "1", "yes")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

STATE_FILE = "linkedin_state.json"
HISTORY_FILE = "applied_jobs.json"
MAX_JOBS_PER_RUN = 10  # Safe batch size per execution

ai_client = genai.Client(api_key=GEMINI_API_KEY)


def send_telegram(message: str):
    """Sends a notification to your Telegram chat."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")


def load_history():
    """Loads previously processed Job IDs to prevent duplicate evaluations."""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def save_history(processed_ids):
    """Saves evaluated Job IDs to disk."""
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(list(processed_ids), f, indent=2)
    except Exception as e:
        print(f"Failed to save job history: {e}")


def get_resume_text():
    if not os.path.exists(RESUME_PATH):
        raise FileNotFoundError(f"Resume not found at {RESUME_PATH}")
    reader = PdfReader(RESUME_PATH)
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""
    return text.strip()


def evaluate_with_gemini(job_title, company, jd_text, resume_text, retries=3):
    """Evaluates technical fit with Gemini 3.8 Flash, retrying if busy."""
    prompt = f"""
You are a senior recruiter evaluating a LinkedIn job application for an Enterprise Integration and AI Architect.

Candidate Resume:
\"\"\"{resume_text[:3500]}\"\"\"

Job Title: {job_title}
Company: {company}
Job Description:
\"\"\"{jd_text[:3500]}\"\"\"

Tasks:
1. Evaluate candidate technical alignment (0 to 100).
2. If match_score >= {MATCH_THRESHOLD}, write a crisp 2-sentence cover pitch emphasizing core alignments.
3. Return ONLY a valid JSON object matching this schema:
{{
  "match_score": <int>,
  "reasoning": "<concise 1-2 sentence explanation>",
  "cover_pitch": "<pitch or empty string if < {MATCH_THRESHOLD}>"
}}
"""
    for attempt in range(retries):
        try:
            response = ai_client.models.generate_content(
                model="gemini-3.8-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            return json.loads(response.text)
        except Exception as e:
            if "503" in str(e) and attempt < retries - 1:
                time.sleep(2)
            else:
                raise e


def attempt_easy_apply(page, dry_run=True):
    """Attempts the Easy Apply flow or returns status."""
    easy_apply_btn = page.locator("button:has-text('Easy Apply')").first
    if not easy_apply_btn.is_visible():
        return "Button not visible"

    if dry_run:
        return "DRY_RUN (Simulated)"

    try:
        easy_apply_btn.click()
        time.sleep(2)

        # Look for submit button directly on 1-step forms
        submit_btn = page.locator("button:has-text('Submit application')").first
        if submit_btn.is_visible():
            submit_btn.click()
            time.sleep(2)
            return "Submitted (1-Step)"

        # For multi-step forms with screening questions, close and alert user to finish
        dismiss_btn = page.locator("button[aria-label='Dismiss'], button[data-test-modal-close-btn]").first
        if dismiss_btn.is_visible():
            dismiss_btn.click()
            time.sleep(1)
            discard_btn = page.locator("button[data-control-name='discard_application_confirm_btn']").first
            if discard_btn.is_visible():
                discard_btn.click()
        return "Requires Custom Answers (Direct link sent)"
    except Exception as e:
        return f"Form error: {e}"


def run_linkedin_automation(keywords="Enterprise Architect", location="India", headless=True):
    resume_text = get_resume_text()
    history = load_history()

    print("=" * 60)
    print("🚀 Starting LinkedIn Easy Apply Automation")
    print(f"• Keywords:        {keywords}")
    print(f"• Location:        {location}")
    print(f"• Threshold:       {MATCH_THRESHOLD}%")
    print(f"• Dry Run:         {DRY_RUN}")
    print(f"• Known Job IDs:   {len(history)}")
    print("=" * 60)

    # Search URL filtered for: Easy Apply (f_AL=true) and Past 24 Hours (f_TPR=r86400)
    search_url = (
        f"https://www.linkedin.com/jobs/search/?"
        f"keywords={keywords.replace(' ', '%20')}&"
        f"location={location}&"
        f"f_AL=true&"
        f"f_TPR=r86400"
    )

    evaluated_count = 0
    matched_count = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            storage_state=STATE_FILE,
            viewport={"width": 1400, "height": 900}
        )
        page = context.new_page()

        print("Navigating to LinkedIn Jobs (Past 24 Hours)...")
        page.goto(search_url, wait_until="domcontentloaded")
        time.sleep(5)

        # Scroll to render job cards
        for _ in range(3):
            page.mouse.wheel(0, 800)
            time.sleep(1.2)

        # Collect unique job links
        all_anchors = page.locator("a[href*='/jobs/view/']").all()
        candidates = []
        seen_links = set()

        for a in all_anchors:
            href = (a.get_attribute("href") or "").split("?")[0]
            txt = a.inner_text().strip()
            # Extract job ID from URL
            job_id = href.rstrip("/").split("/")[-1]

            if job_id.isdigit() and job_id not in history and href not in seen_links and len(txt) > 3:
                seen_links.add(href)
                candidates.append((job_id, txt, href, a))

        print(f"\nDiscovered {len(candidates)} new job(s) posted in the past 24 hours.\n")

        # Process up to MAX_JOBS_PER_RUN
        for job_id, title_text, job_url, anchor in candidates[:MAX_JOBS_PER_RUN]:
            evaluated_count += 1
            print(f"\n[{evaluated_count}/{min(len(candidates), MAX_JOBS_PER_RUN)}] Evaluating: '{title_text}'")
            print(f"URL: {job_url}")

            try:
                # Click to inspect
                anchor.scroll_into_view_if_needed()
                anchor.click()
                time.sleep(2.5)

                # Extract Company
                company_elem = page.locator("a[href*='/company/']").first
                company = company_elem.inner_text().strip() if company_elem.count() > 0 else "Unknown Company"

                # Check Easy Apply button
                easy_apply_btn = page.locator("button:has-text('Easy Apply')").first
                has_easy_apply = easy_apply_btn.is_visible() if easy_apply_btn.count() > 0 else False

                if not has_easy_apply:
                    print("→ Easy Apply no longer active for this post. Skipping.")
                    history.add(job_id)
                    continue

                # Expand description
                see_more = page.locator("button:has-text('Show more'), button:has-text('See more'), button[aria-label*='more description']").first
                if see_more.count() > 0 and see_more.is_visible():
                    try:
                        see_more.click()
                        time.sleep(0.5)
                    except Exception:
                        pass

                # Extract JD
                jd_text = ""
                about_landmark = page.locator("text='About the job'").first
                if about_landmark.count() > 0:
                    container = about_landmark.locator("xpath=ancestor::div[contains(@class, 'jobs-description') or contains(@class, 'job-details') or position()=2]").first
                    jd_text = container.inner_text().strip()

                if len(jd_text) < 100:
                    body_elem = page.locator("article, main section").first
                    jd_text = body_elem.inner_text().strip() if body_elem.count() > 0 else ""

                if len(jd_text) < 100:
                    print("→ Insufficient JD extracted. Skipping.")
                    history.add(job_id)
                    continue

                # Gemini Evaluation
                eval_res = evaluate_with_gemini(title_text, company, jd_text, resume_text)
                score = eval_res.get("match_score", 0)
                reason = eval_res.get("reasoning", "")
                pitch = eval_res.get("cover_pitch", "")
                print(f"→ Match Score: {score}% | {reason}")

                if score >= MATCH_THRESHOLD:
                    matched_count += 1
                    print(f"★ Strong Match (>= {MATCH_THRESHOLD}%)!")

                    apply_status = attempt_easy_apply(page, dry_run=DRY_RUN)
                    print(f"→ Application Action: {apply_status}")

                    # Instant Telegram Notification
                    tg_msg = (
                        f"🎯 LinkedIn Job Match ({score}%)\n\n"
                        f"• Role: {title_text}\n"
                        f"• Company: {company}\n"
                        f"• Status: {apply_status}\n"
                        f"• Direct Link: {job_url}\n\n"
                        f"💡 Analysis: {reason}\n\n"
                        f"📝 Tailored Pitch:\n\"{pitch}\""
                    )
                    send_telegram(tg_msg)

                # Record job in history
                history.add(job_id)
                save_history(history)

                # Safe human delay between jobs (2 to 4 seconds)
                time.sleep(random.uniform(2.0, 4.0))

            except Exception as e:
                print(f"Error evaluating job {job_id}: {e}")

        browser.close()

    # Final Run Summary to Telegram
    summary_text = (
        f"📊 LinkedIn Scan Completed\n\n"
        f"• New Jobs Discovered: {len(candidates)}\n"
        f"• Evaluated This Run: {evaluated_count}\n"
        f"• High Matches Found: {matched_count}"
    )
    send_telegram(summary_text)
    print("\n✓ LinkedIn run completed successfully.")


if __name__ == "__main__":
    # Test locally with headless=False so you can watch it evaluate the batch
    run_linkedin_automation(headless=False)