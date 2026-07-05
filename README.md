# ExamHub India Current Affairs Automation

Automatically fetches India's latest current affairs every day, filters out
irrelevant content, removes duplicates, generates short summaries, extracts
important keywords, categorizes each article exam-wise, and uploads
everything to Firebase Realtime Database — fully automated via GitHub
Actions.

---

## How It Works

Every day (and on-demand), the pipeline:

1. **Fetches** India-only, English-language news from NewsData.io across 8
   categories: Top, Politics, Business, Science, Technology, Education,
   Sports, World.
2. **Filters out** entertainment/spam content (Bollywood, Hollywood,
   celebrity news, gossip, ads, etc.).
3. **Removes duplicates** — both within the same run (by URL and by
   normalized title) and against what's already stored in Firebase (by a
   hash of the article URL).
4. **Generates a 2–3 line summary** for each article.
5. **Extracts important keywords** based on a curated vocabulary of exam
   syllabus-relevant topics (RBI, ISRO, Parliament, Budget, etc.).
6. **Maps each article to every relevant exam** (an article can belong to
   multiple exams) and always adds it to `All Exams`.
7. **Uploads to Firebase**, merging with existing data, keeping only the
   newest 100 articles per exam node, sorted newest-first.
8. **Logs every step** — fetched, filtered, deduplicated, uploaded, failed,
   and total execution time.

The script is written to **never crash**: every stage (fetch, filter,
build, upload) is wrapped in error handling so a single bad article or a
temporary API/Firebase hiccup does not stop the whole run. Failed HTTP and
Firebase calls are automatically retried with backoff.

---

## Project Structure

```
.
├── .github/workflows/update-current-affairs.yml   # Daily + manual GitHub Action
├── main.py                                        # Complete automation pipeline
├── requirements.txt                               # Python dependencies
└── README.md
```

---

## Setup Instructions

### 1. Get a NewsData.io API Key

1. Sign up for free at https://newsdata.io
2. Copy your API key from the dashboard.

### 2. Get a Firebase Service Account Key

1. Go to your Firebase project → **Project Settings** → **Service Accounts**.
2. Click **Generate new private key**. This downloads a JSON file.
3. Open the JSON file and copy its **entire raw content** (you'll paste this
   whole JSON blob as one GitHub secret).
4. Make sure **Realtime Database** is enabled in your Firebase project, and
   note your database URL (looks like
   `https://your-project-id-default-rtdb.firebaseio.com`).

### 3. Add GitHub Secrets

In your repository: **Settings → Secrets and variables → Actions → New
repository secret**. Add these three secrets:

| Secret Name                | Value                                              |
|-----------------------------|-----------------------------------------------------|
| `NEWSDATA_API_KEY`          | Your NewsData.io API key                            |
| `FIREBASE_SERVICE_ACCOUNT`  | The full raw JSON content of your service account key |
| `FIREBASE_DATABASE_URL`     | Your Firebase Realtime Database URL                 |

### 4. Set Firebase Realtime Database Rules

For the Admin SDK (server-side) to write, and for your Android app to read,
set rules appropriate to your security needs. A minimal example that allows
authenticated read and server-only write:

```json
{
  "rules": {
    "current_affairs": {
      ".read": true,
      ".write": false
    }
  }
}
```

The Admin SDK uses your service account credentials and bypasses these
rules automatically, so `.write: false` is safe — only your GitHub Action
(using the service account) can write, while your Android app can read.

### 5. Push to GitHub

Commit and push this project to your repository. The workflow will:

- Run automatically every day at **01:00 UTC (06:30 AM IST)**.
- Also be runnable manually anytime from the **Actions** tab →
  **Update Current Affairs** → **Run workflow**.

---

## Firebase Database Structure

```
current_affairs/
├── UPSC/
│   ├── <md5-hash-of-url-1>/
│   │   ├── title
│   │   ├── description
│   │   ├── summary
│   │   ├── date
│   │   ├── category
│   │   ├── source
│   │   ├── url
│   │   ├── imageUrl
│   │   ├── country
│   │   ├── language
│   │   ├── importantKeywords: [...]
│   │   ├── examNames: [...]
│   │   ├── createdAt
│   │   └── updatedAt
│   └── ...
├── SSC CGL/
├── Bihar Police/
├── IBPS PO/
├── ... (all other supported exams)
└── All Exams/
```

Each exam node keeps at most the **latest 100 articles**, sorted
newest-first. Older articles are automatically dropped once the limit is
exceeded.

---

## Supported Exams

UPSC, BPSC, Bihar Police, Bihar SI, SSC CGL, SSC CHSL, SSC GD, Railway NTPC,
Railway Group D, RRB ALP, RRB JE, IBPS PO, IBPS Clerk, SBI PO, SBI Clerk,
RBI Grade B, NABARD, LIC AAO, EPFO, ESIC, CTET, STET, UGC NET, CSIR NET,
NDA, CDS, AFCAT, CAPF, JEE Main, JEE Advanced, NEET UG, NEET PG, CUET UG,
CUET PG, CLAT, AILET, CAT, MAT, XAT, GMAT, GATE, IES, State PSC, and
**All Exams**.

---

## Local Testing

You can run the script locally before relying on the scheduled workflow:

```bash
pip install -r requirements.txt

export NEWSDATA_API_KEY="your_key"
export FIREBASE_SERVICE_ACCOUNT='{"type": "service_account", ...}'
export FIREBASE_DATABASE_URL="https://your-project-default-rtdb.firebaseio.com"

python main.py
```

Watch the console output — every step (fetch, filter, dedupe, upload) is
logged with counts and a final execution time summary.

---

## Notes & Limitations

- The **free NewsData.io plan** has a daily request quota. This script
  makes one request per category (8 total) per run to stay well within
  free-tier limits. If you upgrade your plan, you can extend
  `NewsDataFetcher` to paginate for more results per category.
- Keyword-to-exam mapping uses rule-based matching (no external AI
  service required), so it works out of the box with zero extra cost or
  API keys beyond NewsData.io and Firebase.
- Summaries are generated by extracting the first 2–3 sentences of the
  article description — no external LLM call is required, keeping the
  pipeline fast, free, and dependency-light.
