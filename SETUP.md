# Setup Guide

## 1. Telegram Bot — BotFather

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts (choose a name and username ending in `bot`)
3. Copy the **API token** — you'll need it as `TELEGRAM_BOT_TOKEN`

---

## 2. Google Sheets API Credentials

### Create a Google Cloud project
1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (or reuse one)
3. Enable **Google Sheets API** and **Google Drive API**

### Create a Service Account
1. Go to **IAM & Admin → Service Accounts → Create Service Account**
2. Give it any name, click **Create and Continue**, then **Done**
3. Click the new service account → **Keys** tab → **Add Key → JSON**
4. A `credentials.json` file will download — place it in the project root

### Create the Google Sheet
1. Go to [sheets.google.com](https://sheets.google.com) and create a new sheet named **Tasks**
2. Copy the Sheet ID from the URL:
   `https://docs.google.com/spreadsheets/d/**THIS_PART**/edit`
3. Share the sheet with the service account email (found in `credentials.json` under `client_email`) — give it **Editor** access
4. For the dashboard to work publicly, also share via **File → Share → Anyone with the link → Viewer**

---

## 3. OpenAI API Key

1. Go to [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. Create a new secret key
3. Copy it as `OPENAI_API_KEY`

---

## 4. Local Development

```bash
# Clone and enter the repo
git clone https://github.com/maruchipereda/to-dos-maru.git
cd to-dos-maru

# Install dependencies
pip install -r requirements.txt

# Copy and fill in env file
cp .env.example .env
# Edit .env with your tokens

# Place credentials.json in the project root

# Run the bot
python bot.py
```

---

## 5. Deploy to Railway (free tier)

1. Go to [railway.app](https://railway.app) and sign in with GitHub
2. Click **New Project → Deploy from GitHub repo** → select `to-dos-maru`
3. Railway will detect the `Procfile` automatically
4. Go to **Variables** and add:
   - `TELEGRAM_BOT_TOKEN`
   - `OPENAI_API_KEY`
   - `GOOGLE_SHEET_ID`
   - `GOOGLE_CREDENTIALS_PATH` = `credentials.json`
5. Upload `credentials.json` as a Railway volume or encode it as an env variable:
   ```bash
   # Encode to base64 and set as GOOGLE_CREDENTIALS_B64
   base64 -i credentials.json
   ```
   Then update `sheets.py` to decode it if using base64 approach (see note below)
6. Click **Deploy** — the worker will start automatically

> **Tip for credentials on Railway:** Instead of uploading a file, set `GOOGLE_CREDENTIALS_JSON` as an environment variable with the full JSON content. Then in `sheets.py` replace the `from_service_account_file` call with:
> ```python
> import json
> creds_dict = json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON"))
> creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
> ```

---

## 6. GitHub Pages Dashboard

1. In your GitHub repo, go to **Settings → Pages**
2. Set **Source** to `Deploy from a branch` → branch `main` → folder `/ (root)`
3. Click **Save**
4. Open `dashboard.html` and replace `YOUR_GOOGLE_SHEET_ID` with your actual Sheet ID
5. Commit and push — the dashboard will be live at:
   `https://maruchipereda.github.io/to-dos-maru/dashboard.html`

> The dashboard reads data from Google Sheets via the public gviz API — no server required.

---

## Bot Commands Reference

| Command | Description |
|---------|-------------|
| `/add task\|priority\|category\|owner` | Add a task manually |
| `/list` | Show all open tasks |
| `/done <id>` | Mark a task as done |
| `/help` | Show help message |
| Free text | AI extracts task details automatically |

**Categories:** work / yango / gr / finance / personal  
**Priorities:** high / medium / low

Yandex Tracker codes like `FLEETSUPPORT-2323` are auto-detected and linked to `https://st.yandex-team.ru/`.
