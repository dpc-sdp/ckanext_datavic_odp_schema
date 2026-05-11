# ckanext-datavic-odp-schema

CKAN extension providing the DataVic Open Data Portal (ODP) dataset and organisation schemas, CLI management commands, and related helpers.

---

## CLI commands

All commands run under the `datavic-odp` group:

```sh
ckan -c $CKAN_INI datavic-odp --help
```

### `migrate-from-data-gov-au` (DATAVIC-923)

Migrates Victorian local council orgs, datasets, and resources from data.gov.au into DataVic. Safe to re-run — existing DV datasets (matched by preserved DGA id) are skipped.

```sh
ckan -c $CKAN_INI datavic-odp migrate-from-data-gov-au [OPTIONS]

Options:
  --org SLUG            Org slug(s) to migrate (repeatable). Omit to migrate all 39 councils.
  --max-filesize-mb N   Files larger than N MB are stored as DGA URLs (default: 100).
  --csv-path PATH       Path to council list CSV (default: /app/ckan/default/vic-councils.csv).
  --report-dir PATH     Directory for the per-run audit CSV (default: /app/filestore/datagov_migration).
```

---

## Running tests

### Prerequisites

Tests run inside the `ckan` container where the full CKAN stack (PostgreSQL, Solr, virtualenv) is available. Ensure the stack is up before running any integration tests.

From `datavic_ckan_odp_lagoon/`:

```sh
# Start all services
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d

# Verify the ckan container is running
docker compose -f docker-compose.yml -f docker-compose.local.yml ps
```

Or using ahoy (if installed):

```sh
ahoy up
```

### Installing the `ckanapi` dependency

`ckanapi` is listed in `requirements.txt` and is installed automatically when the extension is built into the image. If you are iterating on a running container without a rebuild, install it manually:

```sh
docker compose -f docker-compose.yml -f docker-compose.local.yml exec ckan sh -c \
  '. /app/ckan/default/bin/activate && pip install "ckanapi>=4.7"'
```

### Initialising the test database

The integration tests use CKAN's `clean_db` fixture, which requires a `ckan_test` database. Create it and initialise the schema once per environment (or after `down --volumes`):

```sh
# 1. Create the test database
docker compose -f docker-compose.yml -f docker-compose.local.yml exec postgres \
  psql postgresql://ckan:ckan@postgres/postgres -c "CREATE DATABASE ckan_test OWNER ckan;"

# 2. Initialise CKAN tables in the test database
docker compose -f docker-compose.yml -f docker-compose.local.yml exec ckan sh -c \
  '. /app/ckan/default/bin/activate && \
   ckan -c /app/src/ckanext-datavic-odp-schema/test.ini db init'
```

### Running the test suite

Shell into the `ckan` container. `ahoy ckan` activates the venv automatically; otherwise activate it manually:

```sh
# ahoy — opens an interactive shell with venv pre-activated
ahoy ckan

# docker compose — activate the venv manually after entering
docker compose -f docker-compose.yml -f docker-compose.local.yml exec ckan sh
. /app/ckan/default/bin/activate
```

Then navigate to the extension and run pytest:

```sh
cd /app/src/ckanext-datavic-odp-schema
```

**All extension tests:**

```sh
pytest ckanext/datavic_odp_schema/tests/ -v
```

**Migration tests only (`test_migrate_from_dga.py`):**

```sh
pytest ckanext/datavic_odp_schema/tests/cli/test_migrate_from_dga.py -v
```

**Unit tests only (no DB required — mapping logic, CSV loader):**

```sh
pytest ckanext/datavic_odp_schema/tests/cli/test_migrate_from_dga.py -v \
  -k "not TestMigrateCommand"
```

`setup.cfg` configures pytest to use `test.ini` automatically (`addopts = --ckan-ini test.ini`), so no extra `-p` flag is needed.

### Test structure

| Module | Type | Requires DB |
| --- | --- | --- |
| `tests/cli/test_migrate_from_dga.py::TestLicenseMap` | Unit | No |
| `tests/cli/test_migrate_from_dga.py::TestFrequencyMap` | Unit | No |
| `tests/cli/test_migrate_from_dga.py::TestBuildDatasetPayload` | Unit | No |
| `tests/cli/test_migrate_from_dga.py::TestTagString` | Unit | No |
| `tests/cli/test_migrate_from_dga.py::TestResourceName` | Unit | No |
| `tests/cli/test_migrate_from_dga.py::TestLoadCouncils` | Unit | No |
| `tests/cli/test_migrate_from_dga.py::TestMigrateCommand` | Integration | Yes (`clean_db`) |
| `tests/test_helpers.py` | Unit + Integration | Some |

### One-liner (from the host)

Run just the unit tests without entering the container:

```sh
# docker compose
docker compose -f docker-compose.yml -f docker-compose.local.yml exec -T ckan sh -c \
  '. /app/ckan/default/bin/activate && \
   cd /app/src/ckanext-datavic-odp-schema && \
   pytest ckanext/datavic_odp_schema/tests/cli/test_migrate_from_dga.py -v -k "not TestMigrateCommand"'

# ahoy
ahoy run ckan '. /app/ckan/default/bin/activate && cd /app/src/ckanext-datavic-odp-schema && pytest ckanext/datavic_odp_schema/tests/cli/test_migrate_from_dga.py -v -k "not TestMigrateCommand"'
```
