import html
import json
import logging
import math
import os
import re
import threading
import time

from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from folioclient import (
    FolioAuthenticationError,
    FolioClient,
    FolioPermissionError,
)
from lxml import etree

logger = logging.getLogger("rtac")

application = FastAPI()

LIBRARIES_DIR = os.environ.get("LIBRARIES_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "libraries"
)

def _positive_float_env(name, default):
    """Read a positive, finite float from the environment.

    Falls back to `default` (with a warning) on anything that would be a
    footgun: a non-numeric value would otherwise crash at import, and a value
    <= 0 / non-finite would break things — e.g. a 0 timeout makes every FOLIO
    request time out immediately.
    """
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using default %s", name, raw, default)
        return default
    if not math.isfinite(value) or value <= 0:
        logger.warning(
            "Invalid %s=%r (must be > 0); using default %s", name, raw, default
        )
        return default
    return value


# Bound how long a hung FOLIO call can tie up a worker thread. Passed to each
# FolioClient as its (httpx) request timeout.
FOLIO_TIMEOUT = _positive_float_env("FOLIO_TIMEOUT", 15.0)

# Cache one logged-in FolioClient per sigel so a burst of requests does not turn
# into a burst of FOLIO logins (DoS amplification). A per-sigel lock serialises
# the login so a cold-cache burst for one sigel triggers a single login, not N.
FOLIO_CLIENT_TTL = _positive_float_env("FOLIO_CLIENT_TTL", 300.0)
_client_cache = {}
_client_cache_lock = threading.Lock()
_client_locks = {}
_client_locks_guard = threading.Lock()

# Accepted characters in an identifier value before it is interpolated into the
# CQL query. The end is anchored with \Z (not $, which also matches before a
# trailing newline) and the '"' that would break out of the quoted term is
# excluded, to prevent CQL injection.
_VALID_IDENTIFIER = re.compile(r"^[A-Za-z0-9 ._:/-]{1,128}\Z")

# Configured identifier-type ids must be canonical UUIDs. This catches config
# mistakes (with a clear log line) and, like the value guard above, keeps a
# stray '"' from being interpolated into the CQL query.
_VALID_TYPE_ID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

ITEM_FIELDS = [
    "Item_no",
    "UniqueItemId",
    "Location",
    "Call_No",
    "Loan_Policy",
    "Status",
    "Status_Date_Description",
    "Status_Date",
]


def available_sigels():
    """Return the configured library sigels (sub-dirs holding a settings.json)."""
    if not os.path.isdir(LIBRARIES_DIR):
        return []
    return sorted(
        name
        for name in os.listdir(LIBRARIES_DIR)
        if os.path.isfile(os.path.join(LIBRARIES_DIR, name, "settings.json"))
    )


def load_settings(sigel):
    """Load settings.json for a library sigel.

    The sigel is validated against the configured libraries, which also guards
    against path traversal: an unknown or malicious sigel is never in the list.
    """
    if sigel not in available_sigels():
        raise FileNotFoundError("Unknown library sigel: {}".format(sigel))
    path = os.path.join(LIBRARIES_DIR, sigel, "settings.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _new_folio_client(settings):
    """Construct (and log in) a fresh FolioClient from settings.

    The settings' "okapi_url" is the FOLIO gateway / Okapi base URL; FOLIO_TIMEOUT
    bounds each request.
    """
    return FolioClient(
        settings["okapi_url"],
        settings["tenant_id"],
        settings["username"],
        settings["password"],
        timeout=FOLIO_TIMEOUT,
    )


def _sigel_lock(sigel):
    """Return a per-sigel lock, creating it on first use."""
    with _client_locks_guard:
        lock = _client_locks.get(sigel)
        if lock is None:
            lock = threading.Lock()
            _client_locks[sigel] = lock
        return lock


def get_folio_client(sigel, settings):
    """Return a cached FolioClient for the sigel, logging in only when needed.

    Reuses a client for up to FOLIO_CLIENT_TTL seconds so a burst of requests
    does not each trigger a FOLIO login. The per-sigel lock plus the re-check
    inside it mean a cold-cache burst for one sigel triggers a single login.
    """
    now = time.monotonic()
    with _client_cache_lock:
        cached = _client_cache.get(sigel)
        if cached and cached[1] > now:
            return cached[0]
    with _sigel_lock(sigel):
        now = time.monotonic()
        with _client_cache_lock:
            cached = _client_cache.get(sigel)
            if cached and cached[1] > now:
                return cached[0]
        client = _new_folio_client(settings)
        with _client_cache_lock:
            _client_cache[sigel] = (client, now + FOLIO_CLIENT_TTL)
        return client


def _close_client(client):
    """Best-effort close of a FolioClient's underlying httpx connection pool."""
    try:
        client.close()
    except Exception:
        pass


def _invalidate_client(sigel):
    """Drop (and close) any cached client for the sigel, e.g. after an auth failure."""
    with _client_cache_lock:
        cached = _client_cache.pop(sigel, None)
    if cached is not None:
        _close_client(cached[0])


def append_item(root, values):
    """Append an <Item> element with the standard RTAC fields to `root`."""
    item = etree.SubElement(root, "Item")
    for tag in ITEM_FIELDS:
        value = values.get(tag, "")
        etree.SubElement(item, tag).text = "" if value is None else str(value)
    return item


def holding_values(holding):
    return {
        "Item_no": "1",
        "UniqueItemId": holding.get("id", ""),
        "Location": holding.get("location", ""),
        "Call_No": holding.get("callNumber", ""),
        "Loan_Policy": "",
        "Status": holding.get("status", ""),
        "Status_Date_Description": "",
        "Status_Date": holding.get("dueDate", "")[:10],
    }


def empty_item_information():
    """Build an <Item_Information> document with a single 'Okänd' placeholder."""
    root = etree.Element("Item_Information")
    append_item(root, {"Status": "Okänd"})
    return root


def _type_id_list(configured, name=None):
    """Normalise a configured identifier-type UUID setting to a list.

    Accepts a list of UUIDs, a single UUID string, or a comma-separated string.
    Missing/empty values (and empty entries) yield an empty list — they simply
    do not count. Non-empty entries that are not canonical UUIDs are dropped
    with a warning (a config mistake, and a CQL-injection guard). `name` is the
    identifier this setting belongs to, used only for the log line.
    """
    if not configured:
        return []
    if isinstance(configured, str):
        configured = configured.split(",")
    type_ids = []
    for type_id in configured:
        if type_id is None:
            continue
        type_id = str(type_id).strip()
        if not type_id:
            continue
        if not _VALID_TYPE_ID.match(type_id):
            logger.warning(
                "Ignoring invalid identifier-type UUID for %s: %r",
                name or "?",
                type_id,
            )
            continue
        type_ids.append(type_id)
    return type_ids


def build_identifier_query(identifiers, identifier_type_ids):
    """Build the CQL instance query from the supplied identifier values.

    `identifiers` maps a query-parameter name (Bib_ID, ONR, ISSN, ISBN) to its
    value. `identifier_type_ids` maps the same names to the library's
    identifier-type UUID(s) — a list, a single UUID string, or a comma-separated
    string. For each value that is set, one OR-clause is added per configured
    UUID; values without any configured UUID are skipped. Returns None when no
    clause could be built.
    """
    clauses = []
    for name, value in identifiers.items():
        if not value:
            continue
        if not _VALID_IDENTIFIER.match(value):
            logger.warning("Ignoring invalid %s identifier value: %r", name, value)
            continue
        for type_id in _type_id_list(identifier_type_ids.get(name), name):
            clauses.append(
                'identifiers=/@value/@identifierTypeId="{}" "{}"'.format(type_id, value)
            )
    if not clauses:
        return None
    return "?query=(" + " or ".join(clauses) + ")"


def create_rtac_response(folio_client, query):
    """Return the holdings for the first matching instance.

    Uses folio_get_single_object (which, unlike folio_get, does not treat an
    empty result list as an error) so that "no matching instance" and "instance
    with no holdings" return an empty list instead of raising.
    """
    search = folio_client.folio_get_single_object("/instance-storage/instances" + query)
    instances = search.get("instances", [])
    if not instances:
        return []
    instance_id = instances[0]["id"]
    rtac = folio_client.folio_get_single_object("/rtac/{}".format(instance_id))
    return rtac.get("holdings", [])


def _is_auth_error(exc):
    """True if the exception is a FOLIO 401/403 (e.g. an expired token)."""
    if isinstance(exc, (FolioAuthenticationError, FolioPermissionError)):
        return True
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None) in (401, 403)


def fetch_holdings(sigel, settings, query):
    """Run the FOLIO lookup, refreshing the cached client once on an auth error.

    A cached client whose token has expired yields 401/403; drop it and retry
    with a fresh login so a stale token does not wedge a sigel until the TTL.
    """
    client = get_folio_client(sigel, settings)
    try:
        return create_rtac_response(client, query)
    except Exception as exc:
        if not _is_auth_error(exc):
            raise
        logger.warning(
            "Auth error for %s; refreshing FOLIO client and retrying", sigel
        )
        _invalidate_client(sigel)
        client = get_folio_client(sigel, settings)
        return create_rtac_response(client, query)


# Libris documentation for the loan-status ("lånestatus") gateway this service
# implements. The page hosts the technical PDF and explains how a library
# registers its status-gateway URL in Biblioteksdatabasen.
LIBRIS_DOCS_URL = (
    "https://www.kb.se/samverkan-och-utveckling/libris/librissamarbetet/"
    "librissystemen/om-biblioteksdatabasen.html"
)

# A ready-to-use, hosted instance of this service that libraries can try out and
# have operated for them.
HOSTED_SERVICE_URL = "https://rtac.bibliotekarien.se"

# Source code, for libraries that want to run the service themselves.
SOURCE_CODE_URL = "https://github.com/fontanka16/folio_libris_rtac"

_INDEX_PAGE = """<!DOCTYPE html>
<html lang="sv">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FOLIO Libris RTAC – lånestatus-gateway</title>
  <style>
    :root { color-scheme: light dark; }
    body { font-family: system-ui, -apple-system, sans-serif; line-height: 1.6;
           max-width: 46rem; margin: 2rem auto; padding: 0 1rem; }
    h1 { margin-bottom: 0.2rem; }
    .lead { color: #666; font-size: 1.15rem; margin-top: 0; }
    h2 { margin-top: 2rem; }
    code { background: rgba(127,127,127,0.18); padding: 0.1em 0.35em;
           border-radius: 3px; font-size: 0.95em; }
    ol li, ul li { margin-bottom: 0.4rem; }
    a { color: #0b69c7; }
    footer { margin-top: 3rem; padding-top: 1rem; border-top: 1px solid #ccc;
             color: #888; font-size: 0.85rem; }
  </style>
</head>
<body>
  <h1>FOLIO Libris RTAC</h1>
  <p class="lead">En lånestatus-gateway som visar bibliotekets bestånd i Libris,
     med FOLIO som källa.</p>

  <h2>Vad tjänsten gör</h2>
  <p>
    Tjänsten besvarar Libris förfrågningar om <strong>lånestatus</strong> &ndash;
    den realtidskoll som i Libris webbsök visar om ett exemplar är inne eller
    utlånat. När någon tittar på en titel i Libris anropas Libris status-gateway
    (<code>status.libris.kb.se</code>), som i sin tur skickar förfrågan vidare
    till bibliotekets registrerade status-URL: den här tjänsten.
  </p>
  <p>
    Förfrågan bär en identifierare (<code>Bib_ID</code>, <code>ONR</code>,
    <code>ISSN</code> eller <code>ISBN</code>). Tjänsten slår upp titeln i
    bibliotekets <strong>FOLIO</strong> och svarar med bestånd &ndash; placering,
    hyllsignum, lånestatus och eventuellt återlämningsdatum &ndash; som det
    XML-svar Libris förväntar sig. Hittas ingen träff returneras en
    <code>Okänd</code>-platshållare.
  </p>
  <p>
    Mer om lånestatus och Biblioteksdatabasen finns i
    <a href="__DOCS_URL__">Kungliga bibliotekets dokumentation</a>.
  </p>

  <h2>Så ansluter ert bibliotek</h2>
  <p>Varje bibliotek identifieras av sitt <em>sigel</em>. För att bli uppsatt:</p>
  <ol>
    <li>Ha ett FOLIO-tenant som tjänsten kan nå.</li>
    <li>Skapa en FOLIO-användare med <strong>enbart läsbehörigheter</strong>
        (bl.a. <code>rtac.all</code> samt läsrättigheter på inventory, holdings
        och items).</li>
    <li>Ta reda på vilka FOLIO <em>identifier-type</em>-UUID:n som motsvarar de
        identifierare ni vill kunna söka på (<code>Bib_ID</code>,
        <code>ONR</code>, <code>ISSN</code>, <code>ISBN</code>).</li>
    <li>Skicka ert <strong>sigel</strong>, FOLIO-uppgifter
        (<code>okapi_url</code>, <code>tenant_id</code>, användarnamn och
        lösenord) samt UUID:na ovan till tjänstens förvaltare.</li>
    <li>Förvaltaren lägger upp er. Anslutningen kan därefter verifieras på
        <code>/&lt;sigel&gt;/validate-folio-connection</code>.</li>
    <li>Registrera tjänstens status-URL för ert sigel i
        <strong>Biblioteksdatabasen</strong> hos KB, så att Libris anropar den.</li>
  </ol>
  <p>
    När allt är på plats nås beståndskollen på
    <code>/&lt;sigel&gt;/rtac?Bib_ID=&lt;libris-id&gt;</code>
    (även <code>ONR</code>, <code>ISSN</code> och <code>ISBN</code> fungerar).
  </p>

__LIBRARIES__
  <h2>Testa eller få tjänsten driftad</h2>
  <p>
    Vill ni prova tjänsten eller slippa drifta den själva? En färdig, driftad
    instans finns på <a href="__HOSTED_URL__">__HOSTED_URL__</a> &ndash; testa
    den där, eller hör av er för att få ert bibliotek uppsatt och driftat.
    Vill ni drifta tjänsten själva hämtar ni källkoden på
    <a href="__SOURCE_URL__">github.com/fontanka16/folio_libris_rtac</a>.
  </p>
  <footer>FOLIO Libris RTAC</footer>
</body>
</html>
"""


def index_html(sigels):
    """Render the public landing page describing the service and onboarding.

    `sigels` (trusted, from the filesystem) are still HTML-escaped on principle
    before being interpolated into the page.
    """
    if sigels:
        items = "\n".join(
            '      <li><code>{0}</code> &ndash; '
            '<a href="/{1}/validate-folio-connection">kontrollera '
            "FOLIO-anslutning</a></li>".format(html.escape(s), html.escape(s, quote=True))
            for s in sigels
        )
        libraries = (
            "  <h2>Anslutna bibliotek</h2>\n  <ul>\n" + items + "\n  </ul>\n"
        )
    else:
        libraries = (
            "  <h2>Anslutna bibliotek</h2>\n"
            "  <p>Inga bibliotek är konfigurerade ännu.</p>\n"
        )
    return (
        _INDEX_PAGE.replace("__DOCS_URL__", LIBRIS_DOCS_URL)
        .replace("__HOSTED_URL__", HOSTED_SERVICE_URL)
        .replace("__SOURCE_URL__", SOURCE_CODE_URL)
        .replace("__LIBRARIES__", libraries)
    )


@application.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(index_html(available_sigels()))


@application.get("/{sigel}/rtac")
def rtac(
    sigel: str,
    Bib_ID: str = Query(None),
    ONR: str = Query(None),
    ISSN: str = Query(None),
    ISBN: str = Query(None),
):
    settings = load_settings(sigel)
    query = build_identifier_query(
        {"Bib_ID": Bib_ID, "ONR": ONR, "ISSN": ISSN, "ISBN": ISBN},
        settings.get("identifier_type_ids", {}),
    )
    if query is None:
        raise ValueError(
            "No searchable identifier provided (a value with a configured UUID)."
        )

    holdings = fetch_holdings(sigel, settings, query)
    if not holdings:
        root = empty_item_information()
    else:
        root = etree.Element("Item_Information")
        for holding in holdings:
            append_item(root, holding_values(holding))
    return Response(etree.tostring(root), media_type="text/xml")


@application.get("/{sigel}/validate-folio-connection")
def validate_folio_connection(sigel: str):
    if sigel not in available_sigels():
        return JSONResponse(
            {"status": "error", "detail": "Unknown library sigel: {}".format(sigel)},
            status_code=404,
        )
    settings = load_settings(sigel)
    required = ["okapi_url", "tenant_id", "username", "password"]
    missing = [key for key in required if not settings.get(key)]
    if missing:
        return JSONResponse(
            {"status": "error", "detail": "Missing settings: " + ", ".join(missing)},
            status_code=503,
        )
    try:
        folio_client = _new_folio_client(settings)
    except Exception as e:
        logger.error(
            "FOLIO connection validation failed for %s: %s", sigel, e, exc_info=e
        )
        return JSONResponse(
            {"status": "error", "detail": "Could not connect to FOLIO: {}".format(e)},
            status_code=502,
        )
    # This client is one-shot (not cached), so close its connection pool once
    # we've read what we need — otherwise every validate call leaks a pool.
    try:
        return {
            "status": "ok",
            "sigel": sigel,
            "okapi_url": folio_client.gateway_url,
            "tenant": folio_client.tenant_id,
        }
    finally:
        _close_client(folio_client)


@application.exception_handler(Exception)
def handle_error(request: Request, e: Exception):
    logger.error("Error while serving %s: %s", request.url, e, exc_info=e)
    if request.url.path.endswith("/rtac"):
        return Response(
            etree.tostring(empty_item_information()), media_type="text/xml"
        )
    return JSONResponse({"error": str(e)}, status_code=500)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("application:application", host="0.0.0.0", port=5000)
