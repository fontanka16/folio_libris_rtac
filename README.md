# FOLIO LIBRIS RTAC

acts as a RTAC API for the Swedish union catalog Libris. The following screen cast shows the RTAC response displayed in Librs
![screen shot of RTAC](docs/libris_rtac.gif)

# Configuring indicators
TBA

# Installation
This project uses [uv](https://docs.astral.sh/uv/) for dependency management.
- Install uv (see the link above).
- Clone the repository
- Run `uv sync` to create the virtual environment and install dependencies. uv will pick the Python version from `.python-version` (3.12).
- Configure one or more libraries. Each library is identified by its *sigel* and configured in `libraries/<sigel>/settings.json` — copy `libraries/example.settings.json` to `libraries/<sigel>/settings.json` and fill in the FOLIO connection and identifier-type UUIDs. See [libraries/README.md](libraries/README.md).
- Make sure the FOLIO user has valid permissions.Below is a good start:
```
{
  "permissionNames": [
    "inventory.all",
    "inventory.instances.collection.get",
    "rtac.all",
    "inventory-storage.holdings.collection.get",
    "perms.users.get",
    "users.collection.get",
    "inventory-storage.location-units.libraries.collection.get",
    "circulation.loans.collection.get",
    "circulation.requests.collection.get",
    "inventory-storage.items.collection.get",
    "inventory-storage.instances.collection.get",
    "circulation-storage.loans.collection.get",
    "orders.collection.get",
    "inventory-storage.instances.item.get",
    "scheduled-notice-storage.scheduled-notices.collection.get",
    "users.item.get",
    "email.message.collection.get"
  ],
  "totalRecords": 17
}
```   
- run the app with `uv run uvicorn application:application --reload --port 5000` (or `uv run python application.py`).
- every endpoint is scoped to a library sigel as the first path segment. The RTAC endpoint is available at http://127.0.0.1:5000/<sigel>/rtac?Bib_ID=<libris-id> (also accepts `ONR`, `ISSN`, `ISBN`) and returns an XML response.
- check a library's FOLIO connection at http://127.0.0.1:5000/<sigel>/validate-folio-connection (200 if it can log in, 404 for an unknown sigel, 503 if settings are missing, 502 if FOLIO is unreachable).
- the list of configured sigels is at http://127.0.0.1:5000/ and interactive API docs at http://127.0.0.1:5000/docs.
