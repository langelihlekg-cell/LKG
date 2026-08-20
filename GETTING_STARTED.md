# Getting Started — From Zero to Running This Project

# Getting Started — From Zero to Running This Project

**On a restricted computer (e.g. a school PC) that won't let you install
things or download files?** Use `START_HERE.md` instead — it does
everything through a free GitHub Codespace in your browser, no installs or
downloads beyond one small one-time file. This guide assumes a normal
personal computer where you can install Python etc. freely.

Written for: you've never developed or launched an API before. Every command
below is something you type into a terminal and press Enter — nothing here
assumes prior coding experience. Where Mac/Linux and Windows differ, both
are given.

---

## 0. What you're actually building, in one paragraph

An **API** is just a program that sits and waits for other programs to send
it requests, and sends back answers. This project has one that takes an
album cover image, generates a short looping animated version of it, checks
that the animation meets Apple's technical rules, and hands the result back.
A **server** is the running copy of that program. Right now you'll run it on
your own computer (`localhost` — a fancy word for "this machine, not the
internet") and talk to it yourself, the same way a real distributor's
system eventually would.

---

## 1. Install the tools you need (one-time setup)

You need three things: a code editor, Python, and a way to open a terminal.

**VS Code** (the editor) — download from https://code.visualstudio.com and
install it like any other application.

**Python 3.11 or newer** — check if you already have it:
- Mac/Linux: open Terminal (Mac: press `Cmd+Space`, type "Terminal", hit
  Enter. Linux: usually `Ctrl+Alt+T`) and type `python3 --version`
- Windows: open Command Prompt (press `Win`, type "cmd", hit Enter) and type
  `python --version`

If you see `Python 3.11` or higher, you're set. If not, or if you get
"command not found": Mac → install from https://python.org/downloads (or
`brew install python3` if you have Homebrew); Windows → install from
https://python.org/downloads and **check the box that says "Add Python to
PATH"** during install, this trips people up more than anything else on this
list; Linux → `sudo apt install python3 python3-venv` (Ubuntu/Debian) or
your distro's equivalent.

**ffmpeg** — the video encoder this project uses. Mac: `brew install
ffmpeg`. Windows: download from https://ffmpeg.org/download.html and add it
to your PATH, or use `winget install ffmpeg`. Linux: `sudo apt install
ffmpeg`. Verify with `ffmpeg -version` — you just need to see version info
print, not understand it.

You do **not** need to install Docker, Postgres, or Redis for anything in
this guide — those are only for the production path, covered briefly at the
end.

---

## 2. Get the project onto your computer

1. Download `motion-artwork-api.zip` from the chat and unzip it (double-click
   it on Mac, right-click → "Extract All" on Windows).
2. Open VS Code. Go to **File → Open Folder**, and select the unzipped
   `motion-artwork-api` folder.
3. Open a terminal *inside* VS Code: **Terminal → New Terminal** in the top
   menu. This opens a terminal already pointed at the right folder, which
   saves you a `cd` command.

From here, every command in this guide is typed into that VS Code terminal.

---

## 3. Set up an isolated Python environment

This step keeps this project's packages separate from anything else on your
computer, so nothing conflicts. It's standard practice, not optional-fancy.

```bash
python3 -m venv venv
```
(Windows: use `python` instead of `python3` if that's what step 1 showed you.)

Activate it — you'll do this every time you open a new terminal for this project:
```bash
# Mac/Linux:
source venv/bin/activate

# Windows (Command Prompt):
venv\Scripts\activate.bat

# Windows (PowerShell):
venv\Scripts\Activate.ps1
```
You'll know it worked because your terminal prompt now starts with `(venv)`.

Install the packages the demo needs:
```bash
pip install flask requests opencv-python-headless numpy scipy pillow
```
This downloads and installs about 5 small libraries — takes under a minute
on a normal connection.

---

## 4. Run the automated test suite (proves the core logic works)

```bash
python3 tests/test_pipeline.py
```
This takes an image, generates the animation, and checks it against Apple's
rules — no server involved yet, just the core logic. You should see three
lines ending in `[PASS]` and `All tests passed.` If you see `FAIL` or a long
red error instead, jump to **Troubleshooting** at the bottom before continuing.

---

## 5. Run the full live demo (this is the main event)

```bash
python3 devserver/live_demo.py
```

What happens, in order: it starts two small web servers on your machine (one
is the actual API, the other pretends to be a music distributor receiving
results), creates a test job over real HTTP, waits for a background worker
to render and check the animation, downloads the result back, and confirms
a notification ("webhook") was delivered and cryptographically signed. It
runs several more scenarios after that, including one deliberately broken
file to prove the checker actually rejects bad output rather than
rubber-stamping everything.

Takes about 40 seconds. You're looking for:
```
RESULT: 18/18 checks passed
```
at the very end. That means the whole system — API, background processing,
file generation, compliance checking, and notifications — works end to end,
on your machine, for real.

---

## 6. Run it yourself and poke at it with real requests

This is optional but worth doing once — it's the difference between reading
about an API and actually using one.

**Terminal 1** — start the API:
```bash
python3 devserver/app.py 9000
```
Leave this running. It'll print a line each time it receives a request.

**Terminal 2** — open a *second* terminal (VS Code: click the `+` in the
terminal panel) and activate the venv again (`source venv/bin/activate`),
then create yourself a login key:
```bash
python3 -c "
import sys; sys.path.insert(0, 'devserver')
import db, uuid, hashlib
db.init_db(fresh=False)
org = db.create_org('My Test Org')
key = uuid.uuid4().hex
db.create_api_key(org['id'], hashlib.sha256(key.encode()).hexdigest())
print('Your API key:', key)
"
```
Copy the key it prints out — you'll paste it into the next command.

Now ask the API to generate an animation from the test cover image, using
`curl` (a tool for sending web requests from the terminal — already
installed on Mac/Linux; Windows 10/11 has it built in too):
```bash
curl -X POST http://127.0.0.1:9000/v1/motion-artwork/jobs \
  -H "Authorization: Bearer PASTE_YOUR_KEY_HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "release_id": "my-first-test",
    "cover_art_url": "http://127.0.0.1:9000/test-assets/cover.png",
    "tier": "parametric",
    "callback_url": "http://127.0.0.1:9000/v1/health"
  }'
```
You'll get back something like `{"job_id": "...", "status": "queued", ...}`.
Copy that `job_id`, then check on it:
```bash
curl http://127.0.0.1:9000/v1/motion-artwork/jobs/PASTE_JOB_ID_HERE \
  -H "Authorization: Bearer PASTE_YOUR_KEY_HERE"
```
Run that same command again a few times, a couple seconds apart — you'll
watch `"status"` change from `queued` → `processing` → `complete`, and once
complete, real download URLs appear. Paste one into your browser and the
animated video will actually play.

*(Prefer a visual tool over typing curl commands? Postman
(postman.com, free) or Insomnia are the same idea with buttons instead of
flags — either works fine here.)*

To stop the servers: click into their terminal and press `Ctrl+C`.

---

## 7. A guided tour of what you just ran

- **`generation/`** — turns a flat image into a moving one. This is the
  actual "product."
- **`qc/`** — checks the output against Apple's technical rules
  automatically, so a human doesn't have to watch every video.
- **`devserver/`** — the version of the API you just ran: real, but built
  from simple parts (Flask, sqlite) so it runs on a bare laptop with no
  extra setup.
- **`api/`** — the same API rebuilt on production-grade parts (Postgres
  database, Celery for background jobs). This is what you'd actually deploy
  — see step 8.
- **`tests/`** and **`devserver/live_demo.py`** — automated proof that
  things work, so you don't have to manually re-check by hand every time
  you change something.
- **`README.md`** — a denser, more technical version of this document, with
  the full phase-by-phase status.

---

## 8. From "runs on my laptop" to "a real product" — what's actually different

This demo proves the *logic* works. Turning it into something real requires
things no guide can fully hand you, because they involve accounts, money, or
hardware decisions only you can make:

1. **A place to run it 24/7** — a small cloud server (e.g. a $5-6/month
   box from DigitalOcean, Hetzner, or similar) for the API itself.
2. **A real database and job queue** — Postgres and Redis, both of which
   have free/cheap managed hosting tiers (e.g. Neon or Supabase for
   Postgres, Upstash for Redis) — you don't need to run these yourself.
3. **GPU access for the real depth model** — your laptop almost certainly
   doesn't have one suited to this. Cheapest path: rent one by the hour from
   RunPod or Modal (both were already the plan for Phase 5), or start on
   Google Colab for free to experiment before paying for anything.
4. **File storage** — Cloudflare R2, already the plan; sign-up is free and
   the free tier covers early testing.
5. **Actually talking to a distributor and Apple** — the one step nobody
   can script for you. It means real accounts, real legal terms, and
   patience.

None of this needs to happen at once — steps 1-4 are each an afternoon of
following that service's own quickstart, not a rebuild of anything here.

---

## 9. Troubleshooting

- **"command not found: python3"** (Mac/Linux) — Python isn't installed or
  isn't on your PATH; revisit step 1.
- **"python3 is not recognized..."** (Windows) — same issue; reinstall
  Python and make sure "Add to PATH" is checked.
- **`pip install` fails with a permissions error** — you likely forgot to
  activate the virtual environment (step 3) before running it; check for
  `(venv)` at the start of your prompt.
- **"Address already in use" / port 9000 busy** — something's already using
  that port (maybe a previous run you forgot to stop). Either close that
  terminal, or use a different port: `python3 devserver/app.py 9050` (and
  adjust the URLs in step 6 to match).
- **`ffmpeg: command not found`** — ffmpeg isn't installed or isn't on your
  PATH; revisit step 1.
- **`live_demo.py` hangs or times out** — check `devserver/app.log` and
  `devserver/distributor.log` (created after you run it) for the actual
  error underneath.
- **Nothing above matches your error** — copy the full red error text and
  paste it back into a chat with Claude (or ask Claude Code to read the log
  files directly, see below) — a full error message is almost always enough
  to diagnose immediately.

---

## 10. If you want Claude to run these steps *for* you

Everything in this guide is also something Claude Code can do on your
behalf if you install it and point it at this folder — including installing
packages, running the demo, reading error output, and fixing bugs it finds,
directly on your machine. That's a genuinely different setup than this chat,
covered in the next message.
