# Libraries (tenants)

Each library is identified by its *sigel* and configured in
`libraries/<sigel>/settings.json`. The sigel becomes the first path segment of
every request, e.g. `GET /<sigel>/rtac?ISBN=...`.

To add a library, copy `example.settings.json` to `<sigel>/settings.json` and
fill in the values:

- `okapi_url`, `tenant_id`, `username`, `password` — the FOLIO connection.
- `identifier_type_ids` — a list of FOLIO identifier-type UUIDs for each
  supported query parameter (`Bib_ID`, `ONR`, `ISSN`, `ISBN`). A value can map
  to several identifier types — list each UUID and the search ORs them together.
  Use an empty list `[]` to disable searching by that identifier for this
  library. (A single UUID string or a comma-separated string also works.)
- `fast_track_token` — an optional secret that exempts requests from rate
  limiting. The `/<sigel>/rtac` endpoint is rate-limited per client IP; a
  request whose `?token=` matches this value is never throttled. Bake it into
  the status URL you register for this library in Biblioteksdatabasen
  (`https://<host>/<sigel>/rtac?token=<value>`) so Libris always has the fast
  lane. Leave it empty (`""`) to keep the library public-but-rate-limited.
  Generate one with `python scripts/issue_token.py <sigel>`.

The list of configured sigels is available at `GET /`, and a library's FOLIO
connection can be checked at `GET /<sigel>/validate-folio-connection`.

Real `settings.json` files contain credentials and are gitignored
(`libraries/*/`). Override the location of this directory with the
`LIBRARIES_PATH` environment variable if needed.
