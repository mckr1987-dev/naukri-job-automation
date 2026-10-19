# 🚀 Naukri AI Auto-Apply & Recruiter Email Automation

An autonomous, cloud-hosted AI recruitment pipeline that monitors Gmail for inbound recruiter emails from Naukri, evaluates job descriptions against your resume using **Google Gemini 3.8 Flash**, automatically replies with a tailored pitch and your PDF resume attached when the match is **≥ 85%**, and sends real-time alerts to your **Telegram** with support for on-demand `/scan` triggers.

---

## 🌟 Key Features

- **Smart Gmail Monitoring:** Scans unread emails from `naukri.com` received within the last 24–48 hours (`today` & `yesterday`).
- **Spam & Alert Filtering:** Automatically bypasses promotional job digests and newsletters (`alerts@`, `noreply`, `mailer@naukri.com`) to target direct recruiter reach-outs.
- **Deep Resume Matching (Gemini 3.8 Flash):** Parses your PDF resume, evaluates technical fit against the Job Description, assigns a match score (0–100%), and writes a personalized cover note.
- **In-Thread Auto-Reply & Attachment:** Sends a threaded reply to the recruiter with your `resume.pdf` attached and marks the email as read (can be safely simulated using `DRY_RUN=True`).
- **Telegram Bot Integration:**
  - Pings your phone immediately whenever a high-scoring role is matched/applied to.
  - Sends scan summary reports after each run.
  - Supports live on-demand commands (`/scan`, `/status`, `/help`) right from your mobile chat.
- **24/7 Cloud Architecture (AWS EC2):** Deployed as a persistent Linux `systemd` background daemon with an automated hourly `cron` job.

---

## 🏗️ Architecture Overview

```text
[Recruiter Email] ──> [Gmail Inbox]
                             │
            (Hourly Cron OR Telegram /scan)
                             │
                             ▼
              [naukri_auto_apply.py (AWS EC2)]
                             │
              ┌──────────────┴──────────────┐
              ▼                             ▼
       [Extract Email Body]         [Parse resume.pdf]
              │                             │
              └──────────────┬──────────────┘
                             │
                             ▼
              [Google Gemini 3.8 Flash API]
               (Match Score 0-100% + Pitch)
                             │
               ┌─────────────┴─────────────┐
               ▼                           ▼
        [Score < 85%]               [Score ≥ 85%]
               │                           │
          (Log & Skip)            [Send Threaded Reply]
                                           │
                                  [Attach resume.pdf]
                                           │
                                   [Mark Email as Read]
                                           │
                                           ▼
                           [Send Telegram Notification]