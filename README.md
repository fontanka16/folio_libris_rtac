# FOLIO LIBRIS RTAC

Acts as an RTAC (Real Time Availability Check) API for the Swedish union
catalog **Libris**, backed by one or more **FOLIO** tenants. The screen cast
below shows the RTAC response displayed in Libris:

![screen shot of RTAC](docs/libris_rtac.gif)

## What it does

Libris asks an external system whether a given title is available and where it
is held. This service answers that question by talking to FOLIO and returning
the XML document Libris expects.

- **Multi-tenant.** Each library is identified by its *sigel* and every request
  is scoped to one, e.g. `GET /<sigel>/rtac?ISBN=...`. A sigel maps to its own
  FOLIO connection and identifier configuration under `libraries/<sigel>/`.
- **Identifier lookup.** A request carries one or more identifiers
  (`Bib_ID`, `ONR`, `ISSN`, `ISBN`). Each is translated into a CQL query against
  FOLIO's `instance-storage/instances`, using the per-library FOLIO
  *identifier-type* UUIDs configured for that parameter.
- **Availability.** For the first matching instance the service calls FOLIO's
  `/rtac/{instanceId}` endpoint and maps the returned holdings into the RTAC
  `<Item_Information>` XML document (location, call number, status, due date …).
- **Always answers.** When nothing matches — or FOLIO errors — it returns a
  valid XML document with a single `Okänd` ("Unknown") placeholder item rather
  than an error, so Libris always gets a well-formed response.

### Request flow

```
Libris ──GET /<sigel>/rtac?ISBN=…──▶ this service
                                       │  1. load libraries/<sigel>/settings.json
                                       │  2. build CQL from configured identifier-type UUIDs
                                       │  3. FOLIO: find instance ──▶ /rtac/{id} for holdings
                                       ▼
Libris ◀──── <Item_Information> XML ───┘
```

## What changed since the fork

This repository began life as
[`FOLIO-FSE/folio_stats`](https://github.com/FOLIO-FSE) — a small Flask app for
collecting and displaying statistics from a FOLIO instance. Since the fork it
has been repurposed into a dedicated Libris RTAC service. The main work:

- **Repurposed the app.** Replaced the FOLIO-statistics Flask app with a focused
  **FastAPI** RTAC API (`application.py`) that serves the Libris availability
  use case.
- **Multi-tenant by sigel.** Introduced per-library configuration under
  `libraries/<sigel>/settings.json` (FOLIO connection + identifier-type UUIDs),
  with the sigel as the first path segment of every endpoint. Added the index
  (`GET /`) and a `GET /<sigel>/validate-folio-connection` health/diagnostics
  endpoint.
- **Configurable identifier mapping.** Each query parameter (`Bib_ID`, `ONR`,
  `ISSN`, `ISBN`) maps to one or more FOLIO identifier-type UUIDs, OR-joined
  into a single CQL query; an empty list disables an identifier per library.
- **Security hardening.** Added input validation that doubles as a
  **CQL-injection guard** (identifier values and configured UUIDs are
  pattern-checked before interpolation), and a **path-traversal guard** on the
  sigel (only configured sigels resolve to a settings file).
- **Resilience & DoS resistance.** Added a per-sigel cached, logged-in
  `FolioClient` with a TTL and per-sigel locking so a burst of requests triggers
  a single FOLIO login instead of one per request; automatic re-login on a
  401/403 (expired token); a global socket timeout so a hung FOLIO connection
  can't tie up a worker; and graceful error handling that still returns valid
  RTAC XML.
- **Modern tooling.** Moved dependency management to [uv](https://docs.astral.sh/uv/)
  (`pyproject.toml` / `uv.lock`) and pinned Python 3.12.
- **Containerised & deployable.** Added a non-root `Dockerfile`, a
  `docker-compose.yml` with resource limits and a health check, and
  [DEPLOY.md](DEPLOY.md) describing deployment behind a Caddy reverse proxy.
  Credentials live only in mounted, gitignored `settings.json` files — never in
  the image.
- **Test suite.** Added `pytest` coverage for the identifier/CQL builder,
  injection and path-traversal guards, the client cache and auth-retry logic,
  XML generation, settings loading, and the HTTP endpoints.

## Configuring libraries

Each library is configured in `libraries/<sigel>/settings.json`. Copy
`libraries/example.settings.json` to `libraries/<sigel>/settings.json` and fill
in the FOLIO connection and the identifier-type UUIDs. See
[libraries/README.md](libraries/README.md) for the full field reference.

Real `settings.json` files contain credentials and are gitignored; the location
of the directory can be overridden with the `LIBRARIES_PATH` environment
variable.

### FOLIO permissions

Make sure the FOLIO user has valid permissions. Below is a good start:

```json
{
  "permissionNames": [
    "TO BE ADDED LATER"
  ],
  "totalRecords": 17
}
```

## Installation

This project uses [uv](https://docs.astral.sh/uv/) for dependency management.

- Install uv (see the link above).
- Clone the repository.
- Run `uv sync` to create the virtual environment and install dependencies. uv
  will pick the Python version from `.python-version` (3.12).
- Configure one or more libraries (see [Configuring libraries](#configuring-libraries)).
- Run the app with `uv run uvicorn application:application --reload --port 5000`
  (or `uv run python application.py`).

## Endpoints

Every endpoint is scoped to a library sigel as the first path segment.

- `GET /<sigel>/rtac?Bib_ID=<libris-id>` — the RTAC lookup. Also accepts `ONR`,
  `ISSN`, and `ISBN`. Returns an XML `<Item_Information>` response.
- `GET /<sigel>/validate-folio-connection` — checks a library's FOLIO
  connection: `200` if it can log in, `404` for an unknown sigel, `503` if
  settings are missing, `502` if FOLIO is unreachable.
- `GET /` — an HTML landing page describing the service (in Swedish), with a
  link to the Libris documentation, onboarding instructions for libraries, and
  the list of configured sigels.
- `GET /docs` — interactive API documentation.

## Deployment

See [DEPLOY.md](DEPLOY.md) for running in Docker behind a Caddy reverse proxy.

## Tests

Run the test suite with `uv run pytest`.
