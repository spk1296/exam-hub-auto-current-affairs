# Current Affairs Auto-Updater (for Android App / Firebase)

Automatically fetches the latest India current affairs every day and
uploads them to **Firebase Realtime Database**, pre-categorized into
20 competitive-exam nodes, ready to be consumed directly by your Android app.

Runs on a daily schedule via **GitHub Actions** — no server required.

---

## 1. Folder Structure

```
.
├── .github/workflows/update-current-affairs.yml   # Daily GitHub Actions job
├── main.py                                        # Fetch → categorize → upload pipeline
├── requirements.txt                                # Python dependencies
└── README.md
```

## 2. How It Works

1. **Fetch** — Calls the NewsData.io `latest` endpoint (Free Plan) across
   several categories (top, politics, world, business, science, education,
   sports, technology) filtered to India + English, with automatic retry
   on network errors, timeouts, and rate limits.
2. **Normalize** — Converts every article into the schema:
   ```json
   {
     "title": "",
     "date": "",
     "category": "",
     "description": "",
     "source": "",
     "url": ""
   }
   ```
3. **Deduplicate** — Removes duplicate articles (by URL) both within the
   day's fetch and against what's already stored in Firebase.
4. **Categorize** — Every article is scanned for exam-specific keywords
   (e.g. "SSC CGL", "IBPS PO") and broader current-affairs topics
   (government schemes, defence, economy, science, sports, education
   policy, Bihar state affairs, awards & appointments). It is uploaded to
   **every matching exam node**, plus always to `All Exams`.
5. **Sort & Trim** — Each exam node is sorted by date (newest first) and
   trimmed to the latest **100** items.
6. **Upload** — Written to Firebase Realtime Database using the Firebase
   Admin SDK.

## 3. Firebase Database Structure

```
current_affairs
 ├── UPSC
 ├── SSC CGL
 ├── SSC CHSL
 ├── SSC GD
 ├── Railway NTPC
 ├── Railway Group D
 ├── Bihar Police
 ├── Bihar SI
 ├── BPSC
 ├── CTET
 ├── STET
 ├── UGC NET
 ├── CDS
 ├── NDA
 ├── IBPS PO
 ├── SBI PO
 ├── JEE
 ├── NEET
 ├── CUET
 └── All Exams
```

Each exam node is a **JSON array** of news items (latest 100), e.g.:

```json
[
  {
    "title": "RBI keeps repo rate unchanged at 6.5%",
    "date": "2026-07-05 09:12:00",
    "category": "business, top",
    "description": "The Reserve Bank of India's Monetary Policy Committee...",
    "source": "the_hindu",
    "url": "https://example.com/article"
  }
]
```

## 4. Setup Instructions

### Step 1 — Get a NewsData.io API Key
1. Sign up at https://newsdata.io
2. Copy your API key from the dashboard (Free Plan works fine).

### Step 2 — Get Firebase Credentials
1. Go to the [Firebase Console](https://console.firebase.google.com/) →
   your project → **Project Settings → Service Accounts**.
2. Click **Generate New Private Key** — this downloads a JSON file.
3. Go to **Realtime Database** and copy your database URL
   (e.g. `https://your-project-id-default-rtdb.firebaseio.com`).
4. Make sure Realtime Database rules allow writes from the Admin SDK
   (Admin SDK bypasses security rules by default, so default rules are fine).

### Step 3 — Add GitHub Secrets
In your GitHub repo, go to **Settings → Secrets and variables → Actions →
New repository secret**, and add:

| Secret Name                | Value                                                   |
|-----------------------------|----------------------------------------------------------|
| `NEWSDATA_API_KEY`          | Your NewsData.io API key                                 |
| `FIREBASE_SERVICE_ACCOUNT`  | The **entire contents** of the downloaded service account JSON file (paste as-is) |
| `FIREBASE_DATABASE_URL`     | Your Firebase Realtime Database URL                       |

### Step 4 — Push This Project to GitHub
```bash
git init
git add .
git commit -m "Initial commit: Current Affairs auto-updater"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

### Step 5 — Run It
- The workflow runs automatically every day at **02:00 UTC (07:30 AM IST)**.
- To test immediately, go to **Actions → Update Current Affairs → Run workflow**.

## 5. Android App Integration

In your Android app, read from Firebase like any other Realtime Database node:

```kotlin
val database = FirebaseDatabase.getInstance().reference
database.child("current_affairs").child("UPSC")
    .addListenerForSingleValueEvent(object : ValueEventListener {
        override fun onDataChange(snapshot: DataSnapshot) {
            for (item in snapshot.children) {
                val title = item.child("title").getValue(String::class.java)
                val date = item.child("date").getValue(String::class.java)
                val description = item.child("description").getValue(String::class.java)
                val source = item.child("source").getValue(String::class.java)
                val url = item.child("url").getValue(String::class.java)
                // Bind to your RecyclerView adapter
            }
        }
        override fun onCancelled(error: DatabaseError) {}
    })
```

## 6. Customizing Categorization

All categorization logic lives in `main.py`:
- `EXAM_SPECIFIC_RULES` — keywords that name a specific exam directly.
- `TOPIC_RULES` — broader GK topics mapped to a group of relevant exams.

To add a new exam:
1. Add its name to `EXAM_LIST`.
2. Add a keyword entry in `EXAM_SPECIFIC_RULES` (and optionally reference it
   inside relevant `TOPIC_RULES`).

## 7. NewsData.io Free Plan Notes

- Free plan allows up to **10 results per request** and a limited number of
  API credits per day (check your current quota on the NewsData.io
  dashboard, as limits are occasionally revised by the provider).
- This script spreads requests across 8 categories per run (8 requests/day),
  well within free-plan limits.
- If you hit rate limits, reduce `NEWSDATA_CATEGORIES` in `main.py`.

## 8. Error Handling & Logging

- Every network call to NewsData.io retries up to 3 times with exponential
  backoff on timeouts, connection errors, and HTTP 429/5xx responses.
- Missing required secrets cause an immediate, clearly logged failure
  (the Action run will show as failed in the GitHub Actions tab).
- Firebase read/write failures for one exam node are logged but do not stop
  processing of the remaining exam nodes.
- All logs include timestamps and are visible in the GitHub Actions run log.

## 9. License

Free to use and modify for your own Android app / project.
