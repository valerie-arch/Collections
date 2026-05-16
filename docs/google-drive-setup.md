# Connect the platform to your Google Drive folder

You only need to do this once. After it's set up, clicking **Sync Drive** on the Reports page will pull new invoice CSVs from the folder automatically.

**Total time:** ~10 minutes.

---

## What you're doing, in plain English

The platform needs its own "robot Google account" (a service account) that has read access to the invoice folder. You'll create that robot account in Google Cloud, give it permission to read your Drive folder, and download its key file.

---

## Step 1 — Create the robot account

1. Open https://console.cloud.google.com
2. Top-left, click the project dropdown → **New Project**
   - Name: `wahu-collections`
   - Click **Create**
3. Once the project is created, click on it so it's selected
4. In the left sidebar (you may need to click the ☰ menu), go to **APIs & Services → Library**
5. Search for **Google Drive API**, click it, then click **Enable**
6. Now go to **APIs & Services → Credentials** in the left sidebar
7. Click **+ Create Credentials → Service account**
   - Service account name: `collections-platform`
   - Click **Create and Continue**
   - Skip "Grant this service account access to project" (just click **Continue**)
   - Skip "Grant users access" (click **Done**)
8. You'll see your new service account listed. **Copy its email address** — it looks like `collections-platform@wahu-collections.iam.gserviceaccount.com`. You'll need it in Step 3.

## Step 2 — Download the key file

1. Still in **Credentials**, click your service account's email
2. Go to the **Keys** tab
3. Click **Add Key → Create new key**
4. Select **JSON** and click **Create**
5. A file will download to your Mac, named something like `wahu-collections-abc123.json`

Move that file into the project:

```
mkdir -p /Users/valerielabi/Downloads/Collections/secrets
mv ~/Downloads/wahu-collections-*.json /Users/valerielabi/Downloads/Collections/secrets/google-service-account.json
```

⚠️ **Never commit this file to git.** The `.gitignore` already excludes `secrets/`.

## Step 3 — Share the Drive folder with the robot

1. Open the invoices folder: https://drive.google.com/drive/folders/19fd10Y4AZ8evazSh6SKFTurRam-vPYM1
2. Click **Share** (top right)
3. Paste the service account email from Step 1 into the "Add people" box
4. Set permission to **Viewer** (read-only is fine)
5. **Uncheck** "Notify people" (robot accounts can't read email)
6. Click **Share**

## Step 4 — Tell the platform where the key is

Open the `.env` file at the project root and confirm it has these two lines (the example file already has them):

```
ZOHO_INVOICES_DRIVE_FOLDER_ID=19fd10Y4AZ8evazSh6SKFTurRam-vPYM1
GOOGLE_SERVICE_ACCOUNT_FILE=./secrets/google-service-account.json
```

If `.env` doesn't exist yet:

```
cp .env.example .env
```

## Step 5 — Restart the backend and try it

In the Terminal window running the FastAPI backend (Window 2):

1. Press `Ctrl+C` to stop it
2. Then run:
   ```
   uvicorn api.main:app --reload --port 8000
   ```
3. Wait for `Application startup complete.`

Now open **http://localhost:3000/reports** and click **Sync Drive** at the top right. After a few seconds you'll see "Synced X new, Y up-to-date".

---

## Troubleshooting

**"Sync failed: 403 — does not have storage.objects.list access"**
→ The robot account email isn't shared on the folder. Go back to Step 3 and double-check the email.

**"Sync failed: Could not load file: secrets/google-service-account.json"**
→ The file isn't where the platform expects. Run `ls /Users/valerielabi/Downloads/Collections/secrets/` — you should see `google-service-account.json`.

**"Google Drive sync needs GOOGLE_SERVICE_ACCOUNT_FILE pointing at..."**
→ Either `.env` doesn't have the variable, or the path is wrong. Run `cat /Users/valerielabi/Downloads/Collections/.env | grep GOOGLE` to check.

**The Sync button works but Reports still shows no data**
→ The 15 invoice CSVs we already bootstrapped should already show up. Confirm they're there: `ls sample_inputs/zoho/invoices/`. You should see 15 files.

---

## How sync works (for context)

- "Sync Drive" lists every file in the configured folder, filters to ones with "Invoice" in the title
- Downloads only files that are new or whose Drive `modifiedTime` has changed since last sync
- Saves to `sample_inputs/zoho/invoices/`
- A small `.sync_state.json` in that folder tracks what's already been pulled, so re-syncing is cheap
