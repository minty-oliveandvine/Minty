# 🐳 Docker Guide (for beginners, using VS Code)

This guide is for anyone who has **never used Docker before**. Follow it top to
bottom and you'll have the whole app — the Flask website **and** its PostgreSQL
database — running on your machine, without installing Python or Postgres.

> **What is Docker, in one sentence?** It runs the app inside a self-contained
> "box" (a *container*) that already has the right Python, database, and
> libraries baked in — so it works the same on everyone's laptop.

---

## 1. Install what you need (one time)

1. **Docker Desktop** — download and install from
   <https://www.docker.com/products/docker-desktop/> (Mac, Windows, or Linux).
   - After installing, **open Docker Desktop and leave it running.** It must be
     running in the background for any Docker command to work. You'll see a
     little whale icon 🐳 in your menu bar / system tray when it's ready.
   - You do **not** need to create a Docker account or sign in. Just close any
     sign-in prompt if you like.

2. **VS Code** — you already have it. Optionally install these extensions
   (open the Extensions panel with `Cmd/Ctrl + Shift + X` and search):
   - **Docker** (by Microsoft) — adds a whale icon to VS Code's sidebar so you
     can see and control containers with clicks instead of commands.
   - **Dev Containers** (optional, more advanced) — not required for this guide.

---

## 2. Get the project open in VS Code

1. Open VS Code.
2. `File → Open Folder…` and choose the project folder (the one that contains
   the `docker/` folder — **not** the `docker/` folder itself).
3. Open the built-in terminal: **`Ctrl + \`` `** (backtick), or menu
   `Terminal → New Terminal`. This is where you'll type commands.

---

## 3. Create your settings file (one time)

The app reads secrets and settings from a file called `.env`. There's a template
already in the repo. In the VS Code terminal, from the project root, run:

```bash
cp .env.example .env
```

That's it — the defaults work for local development. (On Windows PowerShell, use
`copy .env.example .env` instead.)

---

## 4. Start the app 🚀

In the VS Code terminal, move into the `docker` folder and start everything:

```bash
cd docker
docker compose up --build
```

**What this does** (it's normal for the first run to take a few minutes):
- Builds the app "image" from the `Dockerfile` (installs Python + dependencies).
- Starts a **PostgreSQL database** container.
- Waits for the database to be ready, then runs database migrations.
- Starts the app.

You'll know it's ready when the terminal keeps scrolling logs and shows the app
running. **Leave this terminal open** — closing it or pressing `Ctrl + C` stops
the app.

### Open the app in your browser

👉 <http://localhost:5001>

---

## 5. Editing code while it runs

You don't need to restart anything for normal code changes. This project mounts
your local code into the container, so **when you save a file, the app reloads
automatically.** Just edit in VS Code and refresh your browser.

(You only need to rebuild — step 7 — if you change *dependencies*, e.g.
`pyproject.toml` / `requirements.txt`, or the `Dockerfile`.)

---

## 6. Stopping the app

- **Quick stop:** click into the running terminal and press `Ctrl + C`.
- **Full stop / cleanup** (from the `docker/` folder):
  ```bash
  docker compose down
  ```
  This stops and removes the containers. Your database data is **kept** for next
  time.

---

## 7. Everyday commands (run these from the `docker/` folder)

| I want to… | Command |
|------------|---------|
| Start and watch logs | `docker compose up` |
| Start in the background (frees the terminal) | `docker compose up -d` |
| Rebuild after changing dependencies | `docker compose up --build` |
| Stop the app | `docker compose down` |
| Stop **and wipe the database** (fresh start) | `docker compose down -v` |
| See the app's logs | `docker compose logs -f app` |
| Open a terminal *inside* the app container | `docker compose exec app sh` |
| Run database migrations manually | `docker compose exec app flask --app main.py db upgrade` |

> ⚠️ `docker compose down -v` **deletes all local database data.** Use it only
> when you want a clean database.

---

## 8. Doing it all with clicks (VS Code Docker extension)

If you installed the **Docker** extension, you can avoid the terminal for many
tasks:

1. Click the **whale icon 🐳** in the left sidebar.
2. Under **Containers** you'll see `minty-ref-app` (the website) and
   `minty-ref-db` (the database) once they're running.
3. **Right-click a container** to Start, Stop, Restart, View Logs, or open a
   shell inside it.

You still start the whole stack with the `docker compose up` command in step 4,
but the extension is handy for watching logs and stopping things.

---

## 9. Ports (what runs where)

| Service | Address | What it is |
|---------|---------|------------|
| App (website) | http://localhost:5001 | The Flask app you open in the browser |
| Database | `localhost:5432` | PostgreSQL — connect a DB tool here if needed |

---

## 9b. How this fits with the other repos

This repository is **one piece of a larger system** made of separate repos:

| Repo | What it is | Typical local port |
|------|------------|--------------------|
| **This repo** (pettycash) | Flask backend + database | app `5001`, db `5432` |
| Billing backend | Django API (Module 2) | `8000` (`BILLING_APP_URL`) |
| Billing frontend | Next.js UI (Module 2) | `3000` (`FRONTEND_APP_URL`) |
| Onboarding frontend | Next.js UI | `3001` (`ONBOARDING_APP_URL`) |

The Docker setup in **this** folder starts **only this repo** (the Flask app and
its database) — handy when you're working on Module 1 alone.

**Want all four at once?** Use [`stack/`](stack/README.md) instead:

```bash
cd docker/stack
cp .env.example .env
docker compose up --build
```

That brings up the Flask app, the billing backend, both Next.js UIs and one
shared database, already wired to each other. It expects the four repos to be
checked out side by side under a common parent folder.

**Important — shared secret:** the billing backend must use the **same
`SECRET_KEY`** as this repo, or JWTs won't verify across the two services. If you
run billing locally too, make sure the `SECRET_KEY` in your `.env` here matches
the one in the billing backend's config. (The `stack/` setup handles this for
you — it injects one key into both.)

> The two setups use **separate database volumes**, so data does not carry over
> between them. Pick one and stick with it.

---

## 10. Troubleshooting

**"Cannot connect to the Docker daemon" / "docker: command not found"**
→ Docker Desktop isn't running (or isn't installed). Open Docker Desktop and
wait for the whale icon to say it's running, then try again.

**"port is already allocated" or `5001`/`5432` in use**
→ Something else on your machine is using that port (maybe a previous run, or a
local Postgres). Stop it, or run `docker compose down` first.

**The app shows an old version of my code**
→ Make sure you saved the file. If it still won't update, restart:
`docker compose restart app`.

**Migrations failed / database looks broken**
→ Reset the database with a clean start (this deletes local DB data):
```bash
docker compose down -v
docker compose up --build
```

**First build is very slow**
→ That's normal — it downloads Python and installs dependencies once. Later
starts are much faster because Docker caches these.

**Still stuck?**
→ Copy the last ~20 lines from the terminal and share them with the team. The
error is almost always in there.

---

## Quick reference (TL;DR)

```bash
# one time
cp .env.example .env

# every time (from the project root)
cd docker
docker compose up --build     # start
# open http://localhost:5001
# Ctrl + C to stop, or:
docker compose down           # stop + clean up
```
