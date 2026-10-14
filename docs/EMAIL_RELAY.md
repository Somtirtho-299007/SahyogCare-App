# Free email through your own Gmail (Google Apps Script relay)

Render's free plan blocks SMTP, and Brevo's emails from a rewritten Gmail address can get
stuck before Gmail. This relay sends SahyogCare emails **from your own Gmail account**, over
HTTPS, for free (about 100 emails a day on a normal Gmail account). Gmail-to-Gmail mail
lands in the inbox.

## 1. Make the relay (5 minutes, once)

1. Open <https://script.google.com> while signed in to the Gmail you want to send from.
2. **New project**. Delete what is there and paste this. Change the SECRET line to a long
   random password of your own (letters and numbers, 30+ characters):

```javascript
const SECRET = 'PUT-A-LONG-RANDOM-SECRET-HERE';

function doPost(e) {
  try {
    const d = JSON.parse(e.postData.contents);
    if (d.secret !== SECRET) return ContentService.createTextOutput('denied');
    MailApp.sendEmail({ to: d.to, subject: d.subject, body: d.text, name: 'SahyogCare' });
    return ContentService.createTextOutput('ok');
  } catch (err) {
    return ContentService.createTextOutput('error: ' + err);
  }
}
```

3. Click **Save** (name it "SahyogCare mail").
4. **Deploy → New deployment** → the gear icon → **Web app**.
   - Execute as: **Me**
   - Who has access: **Anyone** (not "Anyone with Google account", which makes the server get a
     Google sign-in page instead of "ok")
5. **Deploy** → **Authorize access** → choose your Gmail → "Advanced" → "Go to SahyogCare
   mail (unsafe)" → **Allow**. (It is your own script; Google shows this for every new script.)
6. Copy the **Web app URL** (it ends in `/exec`).

## 2. Tell the server

In Render → SahyogCare-Api → **Environment**, add:

| Key | Value |
|---|---|
| `SAHYOG_EMAIL_RELAY_URL` | the Web app URL from step 6 |
| `SAHYOG_EMAIL_RELAY_SECRET` | the same SECRET you put in the script |

Save; Render redeploys. From then on, login codes and other emails go through your Gmail.
Brevo stays as it is but is no longer used while the relay is set. Remove the two keys to go
back to Brevo.

## Check it

Open the `/exec` URL in a **private / incognito window** (signed out of Google). It must show
"Script function not found: doGet". If it asks you to sign in or shows a Google page, access is
not "Anyone": fix it in **Deploy → Manage deployments → Edit (pencil) → Who has access: Anyone →
Version: New version → Deploy**.

## Notes

- Keep the secret private (it is only in the script and in Render). Without it the relay sends nothing.
- If you change the script later, use **Deploy → Manage deployments → Edit → New version**, so the URL stays the same.
- Gmail's daily limit for scripts is about 100 recipients on a normal account. Enough for a test day; for more, use your own domain with Brevo.
- If an email fails, Render → Logs shows "Email relay did not send: …" with the reason.
