# HIT Checker — Complete App & API Documentation

This document is intended to help an AI assistant guide users of the **HIT Checker** web dashboard and Telegram bot. It covers every feature, how to use it, common issues, and how to resolve them.

---

## 1. What is HIT Checker?

HIT Checker is a payment gateway testing platform with two interfaces:

- **Web Dashboard** — available at `hitchecker.replit.app` (or your custom domain)
- **Telegram Bot** — `@HitChkBot` — for checking cards directly via Telegram chat

It lets users test credit/debit cards against multiple payment gateways (Stripe, Braintree, PayPal, Razorpay, Shopify, and more), generate test cards, find gateway types on websites, check accounts, scrape Stripe SK keys, and run automated mass hits.

---

## 2. Login & Authentication

### How Login Works
Login is Telegram-based OTP. There is no password.

1. Go to the web app.
2. Enter your **Telegram User ID** (numeric, e.g., `1517013110`).
3. Click **Send OTP** — a 6-digit code is sent to your Telegram via the bot.
4. Enter the code on the web app and click **Verify & Login**.

### How to Get Your Telegram User ID
1. Open the Telegram bot (`@HitChkBot`) and send `/start`.
2. The bot replies with your User ID.
3. Copy and paste it into the login form.

### Common Login Issues

| Problem | Cause | Fix |
|---|---|---|
| "User not found" | You haven't started the bot yet | Open `@HitChkBot` on Telegram and send `/start` |
| No OTP received | Bot is offline or you're not registered | Check bot is online; try `/start` on Telegram |
| "Please wait Xs before requesting another OTP" | Rate limited (30s per IP, 60s per user) | Wait the specified time |
| "Login successful" but still on login page | Session cache issue (older versions) | Hard-refresh the page (Ctrl+Shift+R) |
| OTP expired | OTPs expire after a few minutes | Click "Resend OTP" to get a new one |

---

## 3. Membership Plans & Limits

There are 3 tiers: **Free**, **Silver**, and **Gold**.

| Feature | Free | Silver ($5 / 7 days) | Gold ($7 / 7 days) |
|---|---|---|---|
| Daily CC Checks | 500 | 5,000 | Unlimited |
| Batch Check (max cards) | 50 cards | 1,000 cards | 5,000 cards |
| Auto Hitter (daily) | 2 hits | Unlimited | Unlimited |
| Shopify Checks (daily) | 1,000 | 10,000 | Unlimited |
| Account Checker | Single only | Mass (up to 500) | Mass (up to 1,000) |
| Gateway Finder | Not available | 3 searches/day | 10 searches/day |
| Parallel Workers | 1 | 3 | 5 |
| Sites / Proxy / SK Keys | Unlimited | Unlimited | Unlimited |

### How to Upgrade
1. Go to **Plans & Pricing** in the sidebar.
2. Click **Buy Now** on your desired plan.
3. This opens a Telegram chat with the admin — send the message to request activation.
4. Once the admin activates your plan, it appears under your profile.

### How to Redeem a Code
1. Go to **Plans & Pricing** (or your profile/dashboard).
2. Enter your redeem code in the redeem field and submit.
3. The plan activates immediately if the code is valid.

---

## 4. Card Checker (Single Check)

**Page:** Checker → Single Check tab

### What It Does
Checks a single credit/debit card against a specific payment gateway to see if it is live (charged/authenticated) or dead (declined).

### Card Format
All cards must be in this format:
```
CARDNUMBER|MM|YY|CVV
```
Examples:
```
4111111111111111|12|26|123
5500005555555559|06|25|123
```

### Available Gateways
- **Stripe Auth** — Tests Stripe authentication (no charge)
- **Stripe Charge** — Attempts a small charge via Stripe
- **Braintree** — Tests Braintree gateway
- **PayPal** — Tests PayPal gateway
- **Razorpay** — Tests Razorpay gateway
- **Shopify (shp_...)** — Tests against a specific Shopify store
- **Auto** — Automatically selects the best gateway

### Result Statuses
| Status | Meaning |
|---|---|
| `hit` / `charged` / `live` | Card is valid and charged/authenticated |
| `declined` | Card was declined by the bank |
| `error` | Gateway error, not a card status |
| `dead` | Card is invalid/expired |

### Rate Limits
- Max **10 checks per minute** per IP
- Daily check limits apply based on your tier

### Common Issues

| Problem | Fix |
|---|---|
| "Invalid card format" | Use `CC\|MM\|YY\|CVV` format with pipes (`\|`) |
| "Daily check limit reached" | Wait until midnight (limits reset daily) or upgrade plan |
| "Server busy. Try again shortly" | Concurrent check slots full — retry in a few seconds |
| Check takes very long | Normal — gateway checks can take 30–70 seconds |

---

## 5. Card Checker (Batch / Mass Check)

**Page:** Checker → Batch Check tab

### What It Does
Checks multiple cards at once against a gateway. Results stream in real time.

### How to Use
1. Paste cards in the text area — one card per line in `CC|MM|YY|CVV` format.
2. Select a gateway.
3. Click **Start Batch Check**.
4. Results appear in real time with Hit/Dead/Error labels.
5. Click **Stop** to cancel a running batch.

### Limits by Plan
| Plan | Max cards per batch | Parallel workers |
|---|---|---|
| Free | 50 | 1 |
| Silver | 1,000 | 3 |
| Gold | 5,000 | 5 |

### Common Issues
| Problem | Fix |
|---|---|
| "You already have a running check" | Wait for the current batch to finish or stop it first |
| Some cards skipped | Cards not matching `CC\|MM\|YY\|CVV` format are auto-removed |
| "Daily check limit reached" | Daily limit hit — wait until midnight or upgrade |

---

## 6. Auto Hitter (Stripe CO / Stripe Billing)

**Page:** Auto Hitter

### What It Does
Automatically hits cards via Stripe Checkout or Stripe Billing using your configured SK keys. Used for automated card testing at scale.

### How to Use
1. Add your Stripe SK key(s) in **Settings → SK Keys**.
2. Go to **Auto Hitter**.
3. Enter cards in `CC|MM|YY|CVV` format (one per line).
4. Choose mode: **Stripe CO** or **Stripe Billing**.
5. Click **Start Hitting**.

### Daily Hit Limits
| Plan | Daily Auto Hits |
|---|---|
| Free | 2 per day |
| Silver | Unlimited |
| Gold | Unlimited |

### Common Issues
| Problem | Fix |
|---|---|
| "Daily hitter limit reached (2)" | Free plan limit — upgrade to Silver or Gold |
| "No SK key configured" | Add a Stripe SK key in Settings |
| Hit fails immediately | SK key may be invalid or restricted |

---

## 7. CC Generator

**Page:** Tools → CC Generator

### What It Does
Generates test credit card numbers based on a BIN (Bank Identification Number — first 6+ digits of a card).

### How to Use
1. Enter a BIN (minimum 6 digits). Use `x` for random digits, e.g., `41111x`.
2. Set quantity (1–100 cards).
3. Optionally set fixed month, year, or CVV.
4. Click **Generate**.

### Output Format
Generated cards are in `CC|MM|YY|CVV` format, ready to copy and paste into the checker.

---

## 8. CC Filter

**Page:** Tools → CC Filter

### What It Does
Cleans and deduplicates a list of cards. Removes invalid formats, duplicates, and malformed entries.

### How to Use
1. Paste raw card data (any format — the filter attempts to parse them).
2. Click **Filter**.
3. Get clean, deduplicated output in `CC|MM|YY|CVV` format.

---

## 9. Gateway Finder (Find Site)

**Page:** Tools → Gateway Finder

### What It Does
Scans a website URL to identify which payment gateway it uses (Stripe, Braintree, PayPal, Razorpay, Shopify, etc.).

### How to Use
1. Enter a website URL (e.g., `https://example.com`).
2. Select which gateway to look for (or scan all).
3. Click **Find**.
4. Results show detected gateway information.

### Limits by Plan
| Plan | Daily searches |
|---|---|
| Free | Not available |
| Silver | 3 per day |
| Gold | 10 per day |

---

## 10. Account Checker

**Page:** Tools → Account Checker

### What It Does
Checks login credentials (username:password or email:password) against supported services to verify if accounts are valid.

### How to Use
1. Paste accounts in `email:password` or `username:password` format — one per line.
2. Select the service/target.
3. Click **Check**.

### Limits by Plan
| Plan | Mode |
|---|---|
| Free | Single account only |
| Silver | Mass check, up to 500 accounts |
| Gold | Mass check, up to 1,000 accounts |

---

## 11. SK Checker / Scraper

**Page:** Tools → SK Checker

### What It Does
- **SK Checker**: Validates Stripe SK (secret) keys to confirm if they are live and what their restrictions are.
- **Scraper**: Scrapes and extracts Stripe SK keys from websites, Pastebin, GitHub, etc.

### SK Key Format
Stripe SK keys start with `sk_live_` (live) or `sk_test_` (test).
Example: `sk_live_abc123...`

### How to Use SK Checker
1. Paste SK keys — one per line.
2. Click **Check SK Keys**.
3. Results show: Live / Dead / Restricted.

---

## 12. Shopify Gate

**Page:** Shopify Gate (or Auto Shopify)

### What It Does
Tests cards against Shopify stores using the Shopify payment API. You manage a list of Shopify sites to check against.

### How to Manage Sites
- **Add site**: Enter the Shopify store URL and click Add. Sites are added directly without validation.
- **Delete site**: Click the delete icon next to a site.
- **Delete all**: Use the "Delete All" button.

### How to Check Cards
1. Select a site from your list.
2. Enter cards in `CC|MM|YY|CVV` format.
3. Click **Check**.

---

## 13. Skool Gate

**Page:** Skool Gate

### What It Does
Tests cards against Stripe-powered Skool.com payment flows (internal feature, shown as "Stripe" to end users).

---

## 14. User Settings

**Page:** Settings (accessible from sidebar or profile)

### Proxy Settings
- Add proxies to route your checks through them.
- Format: `host:port` or `host:port:user:pass`
- Add single proxy or bulk-paste multiple proxies.
- Validate proxies before use.

### SK Key Settings
- Add Stripe SK keys for Auto Hitter and SK-based checks.
- Multiple keys supported.
- Keys are stored securely per user.

---

## 15. Referral Program

**Page:** Referral & Earn (in sidebar or on homepage banner)

### What It Does
Earn real money by sharing the app. Every new user who joins using your referral link earns you **$0.40**. Once you've collected enough balance, redeem it directly for a plan — no payment needed.

### Earnings & Redemption
| Referrals | Balance | Unlock |
|---|---|---|
| 13 referrals | $5.20 | Silver Plan (7 days) |
| 18 referrals | $7.20 | Gold Plan (7 days) |

| Plan | Cost from Balance |
|---|---|
| Silver (7 days) | $5.00 |
| Gold (7 days) | $7.00 |

### How to Share
1. Go to **Referral & Earn** from the sidebar or homepage banner.
2. Copy your unique referral link (e.g., `https://hitchecker.replit.app/?ref=REF1517013110`).
3. Share it anywhere — Telegram, Discord, social media, etc.
4. When a new user registers using your link, $0.40 is instantly added to your balance.

### How to Redeem Balance
1. Go to **Referral & Earn**.
2. When your balance reaches $5 or $7, the **Silver** or **Gold** redeem button becomes active.
3. Click the button to activate the plan instantly.

### Referral Code Format
- Your code is `REF` followed by your Telegram User ID
- Example: `REF1517013110`
- Your link: `https://hitchecker.replit.app/?ref=REF1517013110`

### Rules
- Each new user can only be referred once
- You cannot refer yourself
- Balance carries over if you don't redeem immediately
- Redemption history is visible on the Referral page

### Common Issues
| Problem | Fix |
|---|---|
| Referral not credited | Make sure the new user used your link before logging in |
| "You cannot refer yourself" | You shared your own link — it won't work for yourself |
| "You have already used a referral code" | Each account can only be referred once |
| Balance not enough | Share more — you need 13 referrals for Silver, 18 for Gold |

---

## 16. User Dashboard

**Page:** Dashboard (home after login)

Shows:
- Your current plan/tier and expiry date
- Daily usage stats (checks used today vs limit)
- Recent activity feed
- Quick links to all tools

---

## 16. Telegram Bot Commands

The bot (`@HitChkBot`) supports these commands:

| Command | Description |
|---|---|
| `/start` | Register and get your User ID |
| `/check CC\|MM\|YY\|CVV` | Check a single card |
| `/gen BIN` | Generate cards from a BIN |
| `/help` | Show all commands |
| `/plan` | Check your current plan |

---

## 17. Common Errors & Solutions (Quick Reference)

| Error Message | Meaning | Fix |
|---|---|---|
| "User not found. Start the bot with /start first." | Not registered | Open `@HitChkBot` on Telegram, send `/start` |
| "Invalid card format. Use: CC\|MM\|YY\|CVV" | Wrong card format | Reformat as `4111111111111111\|12\|26\|123` |
| "Daily check limit reached (X)" | Hit daily quota | Wait until midnight UTC or upgrade your plan |
| "Rate limit exceeded. Max 10 checks per minute." | Too many checks too fast | Wait 60 seconds before continuing |
| "Server busy. Try again shortly." | All check slots occupied | Wait a few seconds and retry |
| "You already have a running check" | Batch still in progress | Wait for it to finish or click Stop |
| "No SK key configured" | Auto Hitter has no key | Go to Settings and add a Stripe SK key |
| "Daily hitter limit reached (2)" | Free plan auto-hit quota used | Upgrade to Silver or Gold |
| "Your X plan allows max Y cards per batch" | Batch too large for plan | Reduce batch size or upgrade plan |
| "Gateway Finder not available on your plan" | Free plan restriction | Upgrade to Silver or Gold |
| "Please wait Xs before requesting another OTP" | OTP rate limited | Wait the specified number of seconds |
| "Login successful" but stays on login page | Browser cache issue | Hard-refresh (Ctrl+Shift+R) or clear cookies |

---

## 18. Plan Upgrade & Billing FAQ

**Q: How do I buy a plan?**
Go to Plans & Pricing and click "Buy Now". This sends a message to the admin on Telegram. The admin manually activates your plan.

**Q: How long do plans last?**
Both Silver and Gold plans last **7 days** per purchase.

**Q: How do I redeem a code?**
Enter the code in the redeem field on the Plans & Pricing page and click Submit.

**Q: What happens when my plan expires?**
You revert to the Free plan automatically. Your data, saved sites, and settings are preserved.

**Q: Can I upgrade mid-plan?**
Yes. Contact the admin on Telegram.

---

## 19. Architecture Notes (for Technical AI Understanding)

- **Backend**: Express.js (Node.js) server on port 5000
- **Frontend**: React (Vite) SPA, served by the Express backend
- **Bot**: Python 3 Telegram bot, runs as a child process managed by the web server
- **Database**: PostgreSQL for session store and JSON data persistence
- **Auth**: Telegram OTP-based — no passwords
- **Card checking**: Python scripts (`web_checker.py`, `web_tools.py`, etc.) spawned per request
- **Rate limits**: In-memory Maps (reset on server restart) + daily limits in JSON files
- **Gateways**: Stripe, Braintree, PayPal, Razorpay, Shopify, and many others via `bot/gates/`
- **Tiers**: Stored in `bot/user_tiers.json` — `free`, `silver`, `gold`
- **Plans**: Silver = $5/7 days, Gold = $7/7 days

---

*Last updated: March 2026*
