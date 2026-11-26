# Backups: never lose patient data

Clinora backs itself up automatically. You don't need to do anything for the basic setup.

## What happens by itself

- Every **24 hours** Clinora makes one backup file in `data/backups/`, for example `clinora-20261126-093710.tar.gz`.
- Each file holds the **whole database** (accounts, doctors, bookings, messages, reviews, reminders, reports...) plus **profile photos, work photos and verification certificates**.
- The newest **14** are kept; older ones are deleted.
- The copy is made safely while people use the site (SQLite's own backup), and checked for errors.
- Videos are **not** included by default, because they are big. Add `BACKUP_VIDEOS=1` to `.env` to include them.

In the **Clinic Dashboard** (log in as admin) the **💾 Backups** box shows the last backup, any error, and lets you **Back up now** or **Download** a backup.

You can also make one from the Terminal:

```
.venv/bin/python server.py --backup
```

## Settings (`.env`, all optional)

```
BACKUP_EVERY_HOURS=24
BACKUP_KEEP=14
BACKUP_VIDEOS=0
```

---

## Strongly recommended: a cloud copy

Backups in `data/backups/` sit on the **same disk** as the database. If that disk or server is lost, the backups are lost too. A cloud copy fixes that. Each new backup is then also uploaded to your own private storage.

### Option A: Cloudflare R2 (10 GB free, recommended)

1. Sign up at **https://dash.cloudflare.com** → **R2 Object Storage** → **Create bucket**. Name: `clinora-backups`. Keep it **private** (never make it public).
2. **R2 → Manage R2 API Tokens → Create API token**:
   - Permission: **Object Read & Write**, only for the `clinora-backups` bucket.
   - Copy the **Access Key ID**, **Secret Access Key**, and the **endpoint** (`https://<account-id>.r2.cloudflarestorage.com`).
3. Add to `.env` (or to Render's Environment settings when live):
   ```
   BACKUP_S3_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com
   BACKUP_S3_BUCKET=clinora-backups
   BACKUP_S3_REGION=auto
   BACKUP_S3_KEY_ID=your-access-key-id
   BACKUP_S3_SECRET=your-secret-access-key
   ```
4. In R2, open the bucket → **Settings → Object lifecycle rules** → delete objects after **30 days**, so old copies don't pile up.

### Option B: Backblaze B2 (10 GB free)

1. Sign up at **https://www.backblaze.com/b2** → **Create a Bucket**, name `clinora-backups`, **Private**.
2. **Application Keys → Add a New Application Key**, only for that bucket, Read and Write.
3. The bucket page shows the **Endpoint**, e.g. `s3.us-west-004.backblazeb2.com`. Then:
   ```
   BACKUP_S3_ENDPOINT=https://s3.us-west-004.backblazeb2.com
   BACKUP_S3_BUCKET=clinora-backups
   BACKUP_S3_REGION=us-west-004
   BACKUP_S3_KEY_ID=your-keyID
   BACKUP_S3_SECRET=your-applicationKey
   ```
4. In bucket **Lifecycle Settings**, keep only the last 30 days.

AWS S3, Wasabi and MinIO work the same way (any "S3-compatible" storage).

### Check it works

Restart Clinora, open the Clinic Dashboard and tap **💾 Back up now**. "Cloud copy" should show ✓ with the time. The Terminal shows `[backup] uploaded ...`, or `[backup] UPLOAD FAILED` with the reason.

---

## Free hosting: keep your data across deploys

On Render's **free plan** (and similar hosts) the disk is wiped on every deploy and restart. With the cloud copy above turned on, Clinora handles that by itself:

1. **When the host stops Clinora** (a redeploy, a restart, the free plan going to sleep), it makes one last backup and uploads it. Hosts send a stop signal (`SIGTERM`) first, so this happens before the disk is wiped.
2. **When Clinora starts on an empty disk**, it downloads the newest cloud backup and restores it before opening the doors.

So patients, doctors, bookings and records survive deploys **for free**. Add on Render → your service → **Environment**:

| Key | Value |
|---|---|
| `BACKUP_S3_ENDPOINT`, `BACKUP_S3_BUCKET`, `BACKUP_S3_KEY_ID`, `BACKUP_S3_SECRET` | from Option A or B above |
| `BACKUP_EVERY_HOURS` | `1` (on free hosting, so at most an hour is at risk if the server crashes instead of stopping) |

Turn these off only if you have a reason: `BACKUP_AUTO_RESTORE=0`, `BACKUP_ON_SHUTDOWN=0`.

The log shows `[restore] empty disk: brought back clinora-….tar.gz from cloud storage` when it worked.

> The paid plan with a disk ($7/month on Render) is still the most solid choice for real patients: no wiping at all, and the cloud copy becomes a true off-site backup.

## Restore a backup

Only do this if data was lost or broken.

1. **Stop Clinora** (Ctrl+C in its window, or suspend the service on Render).
2. If the backup is in the cloud, download it first and put it in `data/backups/`.
3. Run:
   ```
   .venv/bin/python server.py --restore data/backups/clinora-20261126-093710.tar.gz
   ```
4. Start Clinora again and check everything looks right.

Your data from just before the restore is **not deleted**. It is moved to `data/before-restore-<date>/`, so you can go back. Delete that folder once you are sure.

**Practise once:** restore a backup on your own Mac, so you know it works before you ever need it.

## Keep backups safe

- Backups contain **private patient data**. Never share them, email them or put them on GitHub. (`data/backups/` is already in `.gitignore`.)
- Keep the cloud bucket **private** and the keys only in `.env` / Render settings.
- Only the clinic **admin** can see and download backups in the dashboard.
