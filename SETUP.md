# Dashboard Setup Guide — For Anushia

This guide walks you through the 5 steps needed to get the live dashboard running.
**I do all the technical work. You just need to copy some keys and click a few things.**

---

## Step 1 — GitHub Account (IT to create)

Ask your IT to create a GitHub account at github.com with your work email.
Once you have login details, share the GitHub username with me so I can push the code.

---

## Step 2 — Create a new GitHub repository

Once logged in to GitHub:

1. Click the **+** button in the top right → **New repository**
2. Name it: `permea-ih-dashboard`
3. Set to **Public**
4. Leave everything else as default → click **Create repository**
5. Send me the URL (it will look like `github.com/yourname/permea-ih-dashboard`)

I will push all the code to this repository for you.

---

## Step 3 — Add API keys as GitHub Secrets

This is where you add the passwords/keys for each platform. They are stored encrypted — nobody can see them, not even you once saved.

**How to reach the Secrets page:**
1. Go to your repository on GitHub
2. Click **Settings** (top menu, right side)
3. In the left sidebar: **Secrets and variables** → **Actions**
4. Click **New repository secret** for each key below

**Keys to add:**

| Secret Name | Where to find it | Platform |
|-------------|-----------------|----------|
| `CIO_API_KEY` | Customer.io → Settings → API Credentials → **Reporting API** section → copy key | Customer.io |
| `HUBSPOT_TOKEN` | HubSpot → Settings (gear icon) → Integrations → **Private Apps** → Create a new app → give it read access to CRM + Marketing → copy the token | HubSpot |
| `HUBSPOT_PIPELINE_ID` | HubSpot → CRM → Deals → click the pipeline dropdown → Settings → copy the Pipeline ID | HubSpot |
| `POSTHOG_API_KEY` | PostHog → Settings → Project → **Project API Key** | PostHog |
| `POSTHOG_PROJECT_ID` | PostHog → Settings → Project → **Project ID** (a number) | PostHog |
| `LEMLIST_API_KEY` | Lemlist → Settings (bottom left) → **Integrations** → API → copy key | Lemlist |

**For PostHog event names** — add these once the product team confirms the exact event names:

| Secret Name | Default value (ask product team to confirm) |
|-------------|---------------------------------------------|
| `POSTHOG_EVENT_ACCOUNT_CREATED` | `account_created` |
| `POSTHOG_EVENT_WIDGET_CLICK` | `widget_clicked` |
| `POSTHOG_EVENT_SEGMENT_SUBMIT` | `segment_submitted` |
| `POSTHOG_EVENT_CTA_CLICK` | `cta_clicked_commercial` |

If the product team confirms the default names above are correct, you don't need to add these — the scripts use the defaults automatically.

---

## Step 4 — Enable GitHub Pages

This makes the dashboard available at a public URL.

1. In your repository, click **Settings**
2. In the left sidebar: **Pages**
3. Under **Source**: select **Deploy from a branch**
4. Branch: **main**, Folder: **/ (root)**
5. Click **Save**

Your dashboard URL will be: `https://[your-github-username].github.io/permea-ih-dashboard`

It may take 2–3 minutes to appear after first enabling.

---

## Step 5 — Run the first data fetch

1. In your repository, click the **Actions** tab
2. Click **Fetch Campaign Metrics** in the left sidebar
3. Click **Run workflow** → **Run workflow** (green button)
4. Watch it run — it should take about 1–2 minutes
5. When complete (green checkmark), refresh your dashboard URL

The dashboard now shows live data. After this, it updates automatically every morning at 7am UTC.

---

## LinkedIn Ads (separate process)

LinkedIn requires an app approval before we can connect automatically.
I will walk you through submitting the LinkedIn Developer App application separately.
While waiting for approval, the dashboard shows "LinkedIn data pending."

---

## Troubleshooting

**Dashboard shows "Error loading data"**
→ Open the browser console (F12), check the error. Usually means metrics.json didn't load.

**GitHub Actions fails (red X)**
→ Click the failed run → click the step that failed → read the error message → send it to me.

**A metric shows 0 or null**
→ Either the API key is wrong, or the data doesn't exist yet (campaign not started, or event not tracked).
→ Check the Actions run log for error messages.

**"No campaigns found matching Insight Hub"**
→ The campaign name in the tool doesn't exactly contain "Insight Hub". Let me know and I'll update the filter.
