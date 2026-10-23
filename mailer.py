#!/usr/bin/env python3
"""Emails the current alert (alert.md) to everyone signed up.

Sign-ups come from a Google Form whose responses sheet is published as CSV.
The latest answer per email wins, so people can unsubscribe with the same form.
Secrets (set in GitHub): GMAIL_ADDRESS, GMAIL_APP_PASSWORD, SUBSCRIBERS_CSV_URL
"""
import csv, io, json, os, re, smtplib, sys, urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

HERE = os.path.dirname(os.path.abspath(__file__))
EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
BATCH = 90  # recipients per message (kept under Gmail's per-message limit)


def subscribers(csv_url):
    if not csv_url:
        return []
    req = urllib.request.Request(csv_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        rows = list(csv.reader(io.StringIO(r.read().decode("utf-8-sig"))))
    if not rows:
        return []
    head = [h.lower() for h in rows[0]]
    e_col = next((i for i, h in enumerate(head) if "email" in h), None)
    s_col = next((i for i, h in enumerate(head) if "subscribe" in h or "alerts" in h), None)
    if e_col is None:
        return []
    status = {}
    for row in rows[1:]:
        if e_col >= len(row):
            continue
        email = row[e_col].strip().lower()
        if not EMAIL_RE.match(email):
            continue
        choice = row[s_col].lower() if s_col is not None and s_col < len(row) else ""
        status[email] = "unsubscribe" not in choice and "stop" not in choice
    return sorted(e for e, on in status.items() if on)


def md_to_html(md):
    out = []
    for line in md.splitlines():
        if line.startswith("### "):
            out.append(f'<h3 style="margin:20px 0 6px">{line[4:]}</h3>')
            continue
        line = re.sub(r"\*\*\[([^\]]+)\]\(([^)]+)\)\*\*", r'<a href="\2" style="color:#111;font-weight:600">\1</a>', line)
        line = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', line)
        line = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", line)
        line = re.sub(r"^@\S+$", "", line)  # drop the GitHub mention
        if line.strip():
            out.append(f'<div style="margin:0 0 12px">{line}</div>')
    return "\n".join(out)


def main():
    sender = os.environ.get("GMAIL_ADDRESS", "").strip()
    password = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    if not sender or not password:
        print("Email not set up yet (missing GMAIL_ADDRESS / GMAIL_APP_PASSWORD), skipping")
        return
    title = open(os.path.join(HERE, "alert_title.txt")).read().strip()
    body_md = open(os.path.join(HERE, "alert.md")).read()
    cfg = json.load(open(os.path.join(HERE, "config.json")))
    form = cfg.get("signup_form_url", "")

    people = subscribers(os.environ.get("SUBSCRIBERS_CSV_URL", "").strip())
    if sender.lower() not in people:
        people.insert(0, sender.lower())

    footer = (f'<p style="color:#888;font-size:12px;margin-top:24px">You signed up for ASOS Sample Sale alerts.'
              + (f' <a href="{form}">Unsubscribe or share the sign-up link</a>.' if form else "") + "</p>")
    html = (f'<div style="font-family:-apple-system,Helvetica,Arial,sans-serif;font-size:14px;max-width:640px">'
            f"{md_to_html(body_md)}{footer}</div>")

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s:
        s.starttls()
        s.login(sender, password)
        for i in range(0, len(people), BATCH):
            batch = people[i:i + BATCH]
            msg = MIMEMultipart("alternative")
            msg["Subject"] = title
            msg["From"] = f"ASOS Sample Sale alerts <{sender}>"
            msg["To"] = sender
            msg.attach(MIMEText(html, "html", "utf-8"))
            s.sendmail(sender, batch, msg.as_string())  # everyone is BCC'd
    print(f"emailed {len(people)} people")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"email error: {e}")
        sys.exit(1)
