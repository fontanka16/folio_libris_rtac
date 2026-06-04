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
- `edge_rtac_url` — optional base URL of FOLIO's **edge-rtac** service. When set,
  holdings are fetched from edge-rtac's `getInstanceRtac` (authenticated with the
  library's okapi token — no edge API key). Leave it empty to use **mod-rtac**'s
  `GET /rtac/{id}` via the gateway instead — the fallback for environments where
  edge-rtac is not deployed (e.g. the FOLIO reference/demo environments). A
  global default can be set with the `EDGE_RTAC_URL` environment variable.
- `full_periodicals` — boolean (default `false`), passed to edge-rtac as
  `fullPeriodicals`. Only used when `edge_rtac_url` is set.
- `lang` — optional language code passed to edge-rtac as `lang` (e.g. `"sv"`).
  Omitted when empty. Only used when `edge_rtac_url` is set.

The list of configured sigels is available at `GET /`, and a library's FOLIO
connection can be checked at `GET /<sigel>/validate-folio-connection`.

Real `settings.json` files contain credentials and are gitignored
(`libraries/*/`). Override the location of this directory with the
`LIBRARIES_PATH` environment variable if needed.
