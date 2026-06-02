# Deploying to room40 (SSH + docker compose, behind Caddy)

The app runs as a single container, binds to `127.0.0.1:5000` on room40, and
sits behind the existing **Caddy** reverse proxy (Caddy terminates TLS and
forwards to the app). Caddy automatically sets the `X-Forwarded-*` headers that
the app trusts (uvicorn is started with `--proxy-headers`).

## First-time setup

1. SSH to room40 and get the code:

       git clone <repo-url> folio_libris_rtac
       cd folio_libris_rtac

2. Create the per-library settings on the server (these are gitignored and live
   only on room40):

       mkdir -p libraries/<sigel>
       cp libraries/example.settings.json libraries/<sigel>/settings.json
       # edit libraries/<sigel>/settings.json: FOLIO connection + identifier UUIDs

   Repeat for each library / sigel.

3. Build and start:

       docker compose up --build -d
       docker compose ps          # should show "healthy" after ~15s

4. Add a site to the existing Caddyfile and reload Caddy:

       rtac.room40.example {
           reverse_proxy 127.0.0.1:5000
       }

       caddy reload --config /etc/caddy/Caddyfile    # or: systemctl reload caddy

   Requests then look like:
   `https://rtac.room40.example/<sigel>/rtac?ISBN=...`

## Updating

       git pull
       docker compose up --build -d
       docker compose logs -f rtac

## Notes

- `libraries/` is gitignored; the `settings.json` files (with credentials) exist
  only on room40 and are mounted read-only into the container.
- Settings are read per request, so editing a `settings.json` takes effect
  without a rebuild (a `docker compose restart rtac` is harmless if you prefer).
- Verify a library after deploy:
  `curl https://rtac.room40.example/<sigel>/validate-folio-connection`
- If Caddy itself runs as a Docker container, drop the `ports` block in
  `docker-compose.yml`, attach the app to Caddy's Docker network, and use
  `reverse_proxy rtac:5000` instead of `127.0.0.1:5000`.
