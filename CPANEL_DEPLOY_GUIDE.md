# HIT Checker - cPanel Deployment Guide

## What You Need Before Starting

- A cPanel hosting account with **Node.js support** (check with your host)
- **Python 3.8+** available on your server (most cPanel hosts have this)
- **PostgreSQL** database support (or you can use sessions without database)
- Access to your cPanel File Manager and Terminal

---

## STEP 1: Download Your Files

1. In your Replit project, find the **`cpanel-deploy`** folder
2. Download the file **`hitchecker-cpanel.tar.gz`** from inside it
   - Click the 3 dots next to the file → Download
3. This contains everything you need (built app, bot files, config)

---

## STEP 2: Create a PostgreSQL Database in cPanel

1. Log in to your **cPanel**
2. Find **"PostgreSQL Databases"** (or "Databases" section)
3. Create a new database — name it something like `hitchecker`
4. Create a new database user with a strong password
5. Add the user to the database with **ALL privileges**
6. Note down:
   - Database name: `cpanelusername_hitchecker`
   - Database user: `cpanelusername_dbuser`
   - Password: `your-password`

---

## STEP 3: Upload Files to cPanel

1. In cPanel, open **File Manager**
2. Navigate to your **home directory** (`/home/yourusername/`)
3. Create a new folder called `hitchecker`
4. Open that folder
5. Click **Upload** and upload `hitchecker-cpanel.tar.gz`
6. After upload, **right-click** the file → **Extract**
7. The extracted files should be:
   ```
   hitchecker/
   ├── app.js          (entry point)
   ├── package.json    (dependencies)
   ├── requirements.txt (Python deps)
   ├── .env.example    (environment template)
   ├── .htaccess       (routing)
   ├── dist/           (built server + frontend)
   │   ├── index.cjs
   │   └── public/
   └── bot/            (Telegram bot files)
       ├── bot.py
       ├── config.json
       └── ... other files
   ```

---

## STEP 4: Set Up Node.js App in cPanel

1. In cPanel, find **"Setup Node.js App"**
2. Click **"Create Application"**
3. Fill in:
   - **Node.js version**: Choose `18` or `20` (latest available)
   - **Application mode**: `Production`
   - **Application root**: `hitchecker` (the folder you created)
   - **Application URL**: your domain (e.g., `yourdomain.com` or a subdomain)
   - **Application startup file**: `app.js`
4. Click **Create**
5. You'll see a page with your app details — **don't close this yet**

---

## STEP 5: Install Node.js Dependencies

1. On the Node.js App page, find the **"Run NPM Install"** button → Click it
2. Wait for it to finish (may take 1-2 minutes)
3. If there's no button, use the Terminal (Step 6)

---

## STEP 6: Set Up Environment Variables

### Option A: Through cPanel Node.js App page
1. On the Node.js App settings page, find **"Environment variables"**
2. Add these one by one:

| Variable Name   | Value                                                        |
|-----------------|--------------------------------------------------------------|
| `NODE_ENV`      | `production`                                                 |
| `PORT`          | `5000`                                                       |
| `DATABASE_URL`  | `postgresql://dbuser:password@localhost:5432/cpanelusername_hitchecker` |
| `SESSION_SECRET` | (any long random string — type random letters/numbers, 32+ chars) |

### Option B: Through Terminal
1. In cPanel, open **Terminal**
2. Navigate to your app:
   ```bash
   cd ~/hitchecker
   ```
3. Copy the example env file:
   ```bash
   cp .env.example .env
   ```
4. Edit it:
   ```bash
   nano .env
   ```
5. Fill in your real database info and save (Ctrl+O, Enter, Ctrl+X)

---

## STEP 7: Install Python Dependencies

1. In cPanel, open **Terminal**
2. Run:
   ```bash
   cd ~/hitchecker
   pip3 install --user -r requirements.txt
   ```
3. Wait for installation to complete

---

## STEP 8: Set Up the Database Table

1. In Terminal, run:
   ```bash
   cd ~/hitchecker
   node -e "
   const pg = require('pg');
   const pool = new pg.Pool({ connectionString: process.env.DATABASE_URL });
   pool.query('CREATE TABLE IF NOT EXISTS user_sessions (sid VARCHAR NOT NULL PRIMARY KEY, sess JSON NOT NULL, expire TIMESTAMP(6) NOT NULL)').then(() => { console.log('Table created'); pool.end(); }).catch(e => { console.error(e); pool.end(); });
   "
   ```

---

## STEP 9: Start Your App

1. Go back to **"Setup Node.js App"** in cPanel
2. Find your app and click **"Restart"**
3. Visit your domain — you should see the HIT Checker login page!

---

## Troubleshooting

### Blank page / 503 error
- Check if Node.js app is running (Setup Node.js App → check status)
- Check app logs in Terminal: `cat ~/hitchecker/stderr.log`

### "Module not found" errors
- Go to Terminal and run:
  ```bash
  cd ~/hitchecker
  source /home/yourusername/nodevenv/hitchecker/18/bin/activate
  npm install
  ```

### Python bot not working
- Check Python version: `python3 --version` (needs 3.8+)
- Install Python packages manually:
  ```bash
  pip3 install --user telethon requests aiohttp httpx
  ```

### Database connection error
- Double-check your DATABASE_URL format
- Make sure the database user has all privileges
- Format: `postgresql://USER:PASSWORD@localhost:5432/DBNAME`

### Bot doesn't send OTP
- Make sure the bot token in `bot/config.json` is correct
- Check Python is accessible: `which python3`

### App works but CSS looks wrong
- Clear your browser cache (Ctrl+Shift+Delete)
- Try opening in incognito/private window

---

## Updating Your App Later

When you make changes on Replit and want to update cPanel:

1. On Replit, run `npm run build` in the Shell
2. Download the new `dist/` folder
3. In cPanel File Manager, delete the old `dist/` folder in `hitchecker/`
4. Upload and extract the new `dist/` folder
5. Restart the Node.js app in cPanel

---

## Important Notes

- Your bot token and API keys are in `bot/config.json` — keep this file secure
- The admin Telegram ID is `1517013110` (set in config.json)
- If you change the bot token, just edit `bot/config.json` in File Manager and restart the app
- The app runs on port 5000 internally; cPanel's proxy handles the public URL
