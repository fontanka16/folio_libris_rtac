import json
import logging
import os

from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse
from folioclient.FolioClient import FolioClient
from lxml import etree

logger = logging.getLogger("rtac")

application = FastAPI()

LIBRARIES_DIR = os.environ.get("LIBRARIES_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "libraries"
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


def get_folio_client(settings):
    return FolioClient(
        settings["okapi_url"],
        settings["tenant_id"],
        settings["username"],
        settings["password"],
    )


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


def _type_id_list(configured):
    """Normalise a configured identifier-type UUID setting to a list.

    Accepts a list of UUIDs, a single UUID string, or a comma-separated string.
    Missing/empty values (and empty entries) yield an empty list.
    """
    if not configured:
        return []
    if isinstance(configured, str):
        configured = configured.split(",")
    return [str(type_id).strip() for type_id in configured if str(type_id).strip()]


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
        for type_id in _type_id_list(identifier_type_ids.get(name)):
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


@application.get("/")
def index():
    return {"app": "RTAC app from FOLIO", "libraries": available_sigels()}


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

    folio_client = get_folio_client(settings)
    holdings = create_rtac_response(folio_client, query)
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
        folio_client = get_folio_client(settings)
    except Exception as e:
        logger.error(
            "FOLIO connection validation failed for %s: %s", sigel, e, exc_info=e
        )
        return JSONResponse(
            {"status": "error", "detail": "Could not connect to FOLIO: {}".format(e)},
            status_code=502,
        )
    return {
        "status": "ok",
        "sigel": sigel,
        "okapi_url": folio_client.okapi_url,
        "tenant": folio_client.tenant_id,
    }


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
