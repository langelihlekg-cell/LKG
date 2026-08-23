# Start Here — Building This With No Installs and No Downloads

This is written assuming you've never built or launched anything like this
before, and that you're often working from a computer where you can't
install software or save downloaded files. Every technical word gets
explained the first time it shows up. Follow this top to bottom.

---

## The one thing I need you to check first

Everything below needs you to download **one** small file, **one** time —
the project code itself (a `.zip`, basically a folder squeezed into a single
file — a few hundred KB of text, not a video). After that one download,
you'll never need to download anything else again, including the animated
covers themselves — more on why below.

**If that one small download doesn't work either**, skip to
**"Plan B: zero downloads, ever"** near the end — it's slower but works
around it completely. If you're not sure, just try the download in Part 2
and come back here if it's blocked.

---

## Part 1: Two ideas that make everything else make sense

**A "repository" (or "repo")** is just a project folder that lives on a
website called GitHub instead of on your own computer. Anyone can open it
from any browser, on any device, and it remembers everything.

**A "Codespace"** is a real computer that GitHub lets you borrow, for free,
that lives on the internet and that you control entirely through your
browser — a code editor, a terminal, real internet access, all of it,
without installing a single thing on the machine you're sitting at. This is
the part that solves your school-PC problem: the "computer" doing the actual
work is GitHub's, not the school's. Your browser is just a window into it.

Why this over Base44: Base44 built you an app, but it's a black box you
can't fully control or fix. A Codespace runs the actual code we've already
built and *tested* (the one that hit 18/18 real compliance checks) — you're
not depending on a no-code tool guessing correctly at Apple's technical spec.

---

## Part 2: Get a free GitHub account and grab the code

1. Go to **github.com** and click **Sign up** (top right). Free, just needs
   an email address.
2. Download the project zip from this chat (the file called
   `motion-artwork-api.zip`) — tap/click it, then whatever your browser's
   save/download option is. **This is the one download this whole guide
   needs.**
3. Unzip it. Windows: right-click the file → **Extract All**. Chromebook/
   Mac: double-click it. You'll get a folder called `motion-artwork-api`.

---

## Part 3: Put the code on GitHub (still just clicking, no terminal yet)

1. On github.com, click the **+** icon top-right → **New repository**.
2. Name it anything (e.g. `motion-artwork-api`). Leave everything else
   default. Click **Create repository**.
3. On the new (empty) repo page, click **uploading an existing file**.
4. Open the unzipped folder from Part 2 on your computer, select
   *everything inside it*, and drag it into the browser window.
5. Scroll down, click **Commit changes**. ("Commit" just means "save this
   as a permanent version.") Wait for the upload to finish.

Your code now lives on GitHub. You will never need to touch the original
zip file or your computer's downloads folder again.

---

## Part 4: Open a Codespace (this is where you'll actually work from now on)

1. On your repo's page, click the green **Code** button.
2. Click the **Codespaces** tab, then **Create codespace on main**.
3. Wait about 30-60 seconds. A full VS Code editor opens *inside your
   browser tab* — same interface either way, just running on GitHub's
   computer instead of yours. You'll see a file list on the left and can
   open a **terminal** (a black box you type commands into) via
   **Terminal → New Terminal** in the top menu.

You get 120 free hours of this per month on a free GitHub account — plenty
to build this over weeks of part-time work. It pauses automatically when
you're not using it, so you're not burning hours while you're in class.

From here on, every command below is typed into that terminal, then you
press Enter.

---

## Part 5: Install the project's packages (one-time, only 4 lines)

```bash
python3 -m venv venv
source venv/bin/activate
pip install flask requests opencv-python-headless numpy scipy pillow
sudo apt-get update && sudo apt-get install -y ffmpeg
```

What just happened: line 1 made a clean, isolated space just for this
project's tools so nothing conflicts with anything else. Line 2 switched
into it — you'll know it worked because your terminal prompt now starts
with `(venv)`. Line 3 installed the 5 small libraries the code needs. Line
4 installed `ffmpeg`, the tool that actually builds the video files. This
all runs on GitHub's computer, using GitHub's internet — nothing is being
downloaded to the school PC.

You'll need to repeat lines 1-2 (not 3-4) each time you come back to a
*new* Codespace session — takes 2 seconds, it's not re-downloading anything.

---

## Part 6: Prove it works

```bash
python3 tests/test_pipeline.py
```
This generates a test animation and checks it against Apple's actual rules
— no website involved yet, just the core engine. Look for `All tests
passed.` at the end.

```bash
python3 devserver/live_demo.py
```
This is the big one: it starts the real API, creates a job, watches it
render and get checked automatically, and confirms a notification was
delivered — takes about 40 seconds. Look for `RESULT: 18/18 checks passed`
at the end.

If either shows `FAIL` instead, copy the red error text and either paste it
back to me, or — since you're already in a real dev environment now — you
can literally ask a Claude Code extension inside this same Codespace to
read the error and fix it. (Install the "Claude Code" or "Anthropic" 
extension from the Extensions icon on the left sidebar if you want that.)

---

## Part 7: Watch it actually work, with zero downloads — this is the part
## that fixes your original problem

Start the real server:
```bash
python3 devserver/app.py 9000
```
Leave it running. A little popup will appear ("Your application running on
port 9000 is available") — click **Open in Browser**. That opens a page
confirming the server's up (if you land on a bare "404 not found" instead,
you're on an older copy of the code — re-download the zip).

Open a **second terminal** (click the `+` in the terminal panel) and make
yourself a login key:
```bash
source venv/bin/activate
python3 devserver/seed_dev_key.py
```
Copy the key it prints.

Now generate one. **Use your forwarded address here, not `127.0.0.1`** — find
it in the **Ports** tab (it looks like `https://something-9000.app.github.dev`).
This is the one detail that matters: whichever address you put right after
`curl` is the address the server will use when it builds the video links it
hands back to you — use the forwarded one and those links open directly in
your own browser with no extra steps. (`cover_art_url` and `callback_url`
inside the `-d '...'` part can stay as `127.0.0.1` — those are only used
internally, by the server talking to itself.)
```bash
curl -X POST https://YOUR-FORWARDED-ADDRESS/v1/motion-artwork/jobs \
  -H "Authorization: Bearer PASTE_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"release_id":"test1","cover_art_url":"http://127.0.0.1:9000/test-assets/cover.png","tier":"parametric","callback_url":"http://127.0.0.1:9000/v1/health"}'
```
This prints back a `job_id`. Check on it — same forwarded address — a few
times, a couple seconds apart, until `"status"` says `complete`:
```bash
curl https://YOUR-FORWARDED-ADDRESS/v1/motion-artwork/jobs/PASTE_JOB_ID -H "Authorization: Bearer PASTE_YOUR_KEY"
```
Once it's complete, the response includes a `"preview_url"` — because you
used the forwarded address above, it's already a real, clickable
`https://...app.github.dev` link. **Paste it into a new browser tab and the
animated cover just plays, no download button anywhere.** That was the
actual fix for your school-PC problem: the video was never something you
needed to save to disk, only something you needed to *watch*.

---

## Part 8: What to do with this once it works

You now have the real thing running, provably working, in a place you can
reach from any school, library, or home computer with just a browser —
bookmark your Codespace's URL (github.com/codespaces shows all of yours).
From here, the honest next steps (not urgent, for when you're ready):

- Everything the fuller `README.md` describes about going from "runs in my
  Codespace" to "a real product" still applies — a small always-on server,
  managed database hosting, and eventually a GPU rental for the real depth
  model. None of that needs to happen before you've shown this to people
  and gotten real interest.
- A Codespace isn't meant to run 24/7 as your actual product — it's your
  *workshop*, not the storefront. When you're ready for that step, come
  back and we'll map out cheap, real hosting.

---

## Plan B: zero downloads, ever

If even the one small zip download in Part 2 is blocked: do that single
step from any other device you have occasional access to — a phone, a
library computer, a friend's laptop, even for two minutes — just to get the
code onto GitHub once. Every step after Part 3 never needs a download
again, on any computer, including the school PC, forever. If truly no
device is ever available to you for that one step, tell me and I'll write
out the core files as plain text you can copy and paste directly into
GitHub's own "Create new file" button in the browser — slower, but it needs
nothing more than typing.
