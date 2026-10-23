#!/usr/bin/env python3
"""Turns alert.md into alerts/latest.json for the Google Sheet script to email out.

The sign-up list lives only in Leah's Google Sheet. The script there checks this
file every few minutes and emails each new alert to everyone signed up.
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def md_to_html(md):
    out = []
    for line in md.splitlines():
        if line.startswith("### "):
            out.append(f'<h3 style="margin:20px 0 6px">{line[4:]}</h3>')
            continue
        line = re.sub(r"\*\*\[([^\]]+)\]\(([^)]+)\)\*\*", r'<a href="\2" style="color:#111;font-weight:600">\1</a>', line)
        line = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', line)
        line = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", line)
        if line.strip():
            out.append(f'<div style="margin:0 0 12px">{line}</div>')
    return ('<div style="font-family:-apple-system,Helvetica,Arial,sans-serif;font-size:14px;max-width:640px">'
            + "\n".join(out) + "</div>")


def main():
    title = open(os.path.join(HERE, "alert_title.txt")).read().strip()
    body = open(os.path.join(HERE, "alert.md")).read()
    os.makedirs(os.path.join(HERE, "alerts"), exist_ok=True)
    data = {"id": os.environ.get("GITHUB_RUN_ID", "local"), "title": title, "html": md_to_html(body)}
    with open(os.path.join(HERE, "alerts", "latest.json"), "w") as f:
        json.dump(data, f, ensure_ascii=False)
    print("alert published:", title)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("publish error:", e)
        sys.exit(1)
