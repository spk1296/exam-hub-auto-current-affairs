# ExamHub India Current Affairs Automation

Automatically fetches India's latest current affairs every day from
multiple news APIs with automatic failover, filters out irrelevant
content, removes duplicates, generates short summaries, extracts
important keywords, categorizes each article exam-wise, and uploads
everything to Firebase Realtime Database — fully automated via GitHub
Actions.

---

## How It Works

Every day (and on-demand), the pipeline:

1. **Fetches** India-only, English-language news across 8 categories (Top,
   Politics, Business, Science, Technology, Education, Sports, World) using
   **automatic multi-source failover**: NewsData.io is tried first, and if
   it fails, returns nothing, or hits its rate limit, the pipeline
   automatically falls back to GNews, then Mediastack, then TheNewsAPI —
   whichever sources you've configured.
2. **Handles rate limits gracefully** — an HTTP 429 from any source
   triggers a 60-second cool-down before retrying, and a 2-second delay is
   added between paginated NewsData.io requests to stay well within free
   API quotas.
3. **Filters out** entertainment/spam content (Bollywood, Hollywood,
   celebrity news, gossip, ads, etc.).
4. **Removes duplicates** — both within the same run (by URL and by
   normalized title) and against what's already stored in Firebase (by a
   hash of the article URL), regardless of whether Firebase returns that
   data as a dict, a list, or a dict with numeric-string keys.
5. **Generates a 2–3 line summary** for each article.
6. **Extracts important keywords** based on a curated vocabulary of exam
   syllabus-relevant topics (RBI, ISRO, Parliament, Budget, etc.).
7. **Maps each article to every relevant exam** (an article can belong to
   multiple exams) and always adds it to `All Exams`.
8. **Uploads to Firebase**, merging with existing data, keeping only the
   newest 100 articles per exam node, sorted newest-first (with safe,
   timezone-aware date comparison so mixed naive/aware dates never crash
   the sort).
9. **Logs every step** — fetched, filtered, deduplicated, uploaded, failed,
   and total execution time.

The script is written to **never crash**: every stage (fetch, filter,
build, upload) is wrapped in error handling so a single bad article, a
missing field, or a temporary API/Firebase hiccup does not stop the whole
run. Failed HTTP and Firebase calls are automatically retried with
backoff.

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

### 1. Get News API Key(s)

You need **at least one** of the following. Configuring more than one is
recommended — it enables automatic failover if a source hits its free-tier
rate limit.

| Provider    | Sign up at              | Role                          |
|-------------|--------------------------|-------------------------------|
| NewsData.io | https://newsdata.io      | Primary source (supports pagination) |
| GNews       | https://gnews.io         | Fallback source               |
| Mediastack  | https://mediastack.com   | Fallback source               |
| TheNewsAPI  | https://www.thenewsapi.com | Fallback source            |

Copy the API key from each dashboard you sign up for.

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
repository secret**. Add the two required Firebase secrets, plus whichever
news API key(s) you signed up for:

| Secret Name                | Value                                              | Required? |
|-----------------------------|-----------------------------------------------------|-----------|
| `FIREBASE_SERVICE_ACCOUNT`  | The full raw JSON content of your service account key | Yes |
| `FIREBASE_DATABASE_URL`     | Your Firebase Realtime Database URL                 | Yes |
| `NEWSDATA_API_KEY`          | Your NewsData.io API key                            | At least one of these four |
| `GNEWS_API_KEY`             | Your GNews API key                                  | ” |
| `MEDIASTACK_API_KEY`        | Your Mediastack API key                             | ” |
| `THENEWS_API_KEY`           | Your TheNewsAPI key                                 | ” |

The workflow file already passes all six of these through as environment
variables — any secret you don't create is simply left blank and that
source is skipped automatically.

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

export NEWSDATA_API_KEY="your_key"        # optional if you set another below
export GNEWS_API_KEY="your_key"           # optional
export MEDIASTACK_API_KEY="your_key"      # optional
export THENEWS_API_KEY="your_key"         # optional
export FIREBASE_SERVICE_ACCOUNT='{"type": "service_account", ...}'
export FIREBASE_DATABASE_URL="https://your-project-default-rtdb.firebaseio.com"

# Optional tuning (defaults shown)
export MAX_ARTICLES_PER_CATEGORY="150"
export PAGE_DELAY_SECONDS="2"
export RATE_LIMIT_SLEEP_SECONDS="60"

python main.py
```

Watch the console output — every step (fetch, filter, dedupe, upload) is
logged with counts and a final execution time summary. You'll also see
which news source was used for each category, and any automatic failover
that happened.

---

## Notes & Limitations

- **Automatic failover**: NewsData.io is tried first for every category. If
  it fails, hits its rate limit, or returns no results, the pipeline
  automatically moves to GNews, then Mediastack, then TheNewsAPI — using
  whichever of these you've configured a key for. You only need one key to
  run the project, but more keys mean more resilience.
- **Rate limit handling**: any HTTP 429 response triggers a 60-second
  cool-down (`RATE_LIMIT_SLEEP_SECONDS`) before retrying, and NewsData.io's
  paginated requests are spaced 2 seconds apart (`PAGE_DELAY_SECONDS`) to
  avoid tripping rate limits in the first place.
- **Configurable fetch cap**: `MAX_ARTICLES_PER_CATEGORY` (default 150)
  controls how many articles are collected per category before the
  pipeline moves on — lower this (e.g. to 50 or 100) if you're on a very
  restrictive free plan.
- Keyword-to-exam mapping uses rule-based matching (no external AI
  service required), so it works out of the box with zero extra cost
  beyond whichever news API and Firebase you use.
- Summaries are generated by extracting the first 2–3 sentences of the
  article description — no external LLM call is required, keeping the
  pipeline fast, free, and dependency-light.
