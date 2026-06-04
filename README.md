# Feller's Ranch Data Funnel

ETL pipeline that pulls data from **Shopify** (and eventually **Airtable** for SKU mapping), normalizes it for analytics, runs QA checks, and will load into **Google BigQuery**.

---

### Data flow

```mermaid
flowchart LR
    subgraph sources [Sources]
        Shopify[Shopify GraphQL]
        Airtable[Airtable SKU map]
    end

    subgraph extract [Extract]
        E1[extract_orders]
        E2[extract_customers]
        E3[extract_products]
        E4[extract_inventory]
    end

    subgraph transform [Transform]
        T1[normalize_orders]
        T2[normalize_customers]
        T3[normalize_products]
        T4[variable_weight]
        T5[qa_checks]
    end

    subgraph load [Load - planned]
        BQ[BigQuery]
    end

    Shopify --> E1 & E2 & E3 & E4
    Airtable -.-> T3
    E1 --> T1
    E2 --> T2
    E3 --> T3
    T1 --> T4 --> T5
    T2 & T3 --> T5
    T5 --> BQ
```

---

## Project structure

```
Feller's Ranch Data Funnel/
├── .env                    # Secrets (not committed) — Shopify credentials per store
├── .env.example            # Template for environment variables (to be filled in)
├── .gitignore
├── README.md
├── requirements.txt        # Python dependencies (to be pinned)
│
├── auth/
│   ├── __init__.py
│   └── token_manager.py    # Multi-store Shopify credential loader from .env
│
├── extract/
│   ├── __init__.py
│   ├── shopify_client.py   # GraphQL client wrapper (API 2024-01)
│   ├── extract_orders.py   # Paginated order + line item extraction
│   ├── extract_customers.py
│   ├── extract_products.py
│   ├── extract_inventory.py
│   └── airtable_client.py  # SKU mapping from Airtable (stub)
│
├── transform/
│   ├── __init__.py
│   ├── normalize_orders.py     # → fact_orders, fact_order_lines
│   ├── normalize_customers.py  # → dim_customers
│   ├── normalize_products.py   # → dim_products (+ unmapped list)
│   ├── variable_weight.py      # Flags temp per-lb / by-weight line items
│   └── qa_checks.py            # Pre-load data quality report
│
├── load/                   # Planned
│   ├── __init__.py
│   ├── bigquery_client.py
│   ├── load_dims.py
│   └── load_facts.py
│
└── pipeline/               # Planned
    ├── __init__.py
    ├── run_pipeline.py     # End-to-end ETL entry point
    └── scheduler.py        # Scheduled runs
```

---

## Module reference

### `auth/`

| File | Purpose |
|------|---------|
| `token_manager.py` | Loads per-store credentials from `.env` using prefix keys. Supports multiple Shopify stores via `STORE_PREFIXES`. |

**Supported stores** (extend in `STORE_PREFIXES`):

| Store key | Env prefix |
|-----------|------------|
| `fellers_ranch` | `FLRS` |
| `conger_pos_1` | `CGAL1` |
| `conger_pos_2` | `CGAL2` |
| `conger_online` | `CGAL3` |

---

### `extract/`

| File | Purpose | CLI |
|------|---------|-----|
| `shopify_client.py` | `run_query(query, variables, store)` — POST to Shopify GraphQL | `python -m extract.shopify_client` |
| `extract_orders.py` | Orders + line items (50/page, cursor pagination) | `python -m extract.extract_orders` |
| `extract_customers.py` | Customers (25/page, 0.5s delay for rate limits) | `python -m extract.extract_customers` |
| `extract_products.py` | Products + variants + weight | `python -m extract.extract_products` |
| `extract_inventory.py` | Inventory items, levels, locations | `python -m extract.extract_inventory` |
| `airtable_client.py` | Canonical SKU mapping (not implemented) | — |

Default store for all extractors: `fellers_ranch` (via `shopify_client.run_query`).

---

### `transform/`

| File | Input | Output |
|------|-------|--------|
| `normalize_orders.py` | Raw Shopify orders | `fact_orders`, `fact_order_lines` |
| `normalize_customers.py` | Raw customers | `dim_customers` (dedupe by email, skip empty email) |
| `normalize_products.py` | Raw products + optional `sku_mapping` | Mapped products + `unmapped_products` |
| `variable_weight.py` | `fact_order_lines` | `(standard_lines, variable_weight_lines)` |
| `qa_checks.py` | All normalized datasets | QA report dict (`passed`, `issues`, `warnings`, `summary`) |

| Module | CLI |
|--------|-----|
| Any transform module | `python -m transform.<module_name>` |

**QA behavior:** Pipeline **fails** if any products lack a canonical SKU (`unmapped_products`). Warnings cover missing customers, $0 revenue, missing SKUs on lines, draft products, etc.

---

### `load/` (planned)

| File | Intended role |
|------|----------------|
| `bigquery_client.py` | Authenticate and run BQ jobs |
| `load_dims.py` | Load `dim_customers`, product dimension |
| `load_facts.py` | Load `fact_orders`, `fact_order_lines` |

---

### `pipeline/` (planned)

| File | Intended role |
|------|----------------|
| `run_pipeline.py` | Extract → transform → QA → load in one run |
| `scheduler.py` | Cron / scheduled execution |

---

## Output schemas (normalized)

### `fact_orders`

| Field | Type | Notes |
|-------|------|-------|
| `order_id` | string | Shopify GID |
| `order_name` | string | e.g. `#1001` |
| `created_at` | string | ISO timestamp |
| `financial_status` | string | |
| `fulfillment_status` | string | |
| `total_revenue` | float | |
| `subtotal` | float | |
| `currency` | string | |
| `customer_id` | string \| null | |
| `customer_email` | string \| null | |
| `store` | string | Currently `"fellers_ranch"` |
| `channel` | string | Currently `"online"` |

### `fact_order_lines`

| Field | Type |
|-------|------|
| `order_id`, `line_item_id`, `product_title`, `variant_id`, `sku` | string |
| `quantity` | int |
| `unit_price`, `line_revenue` | float |
| `store` | string |
| `is_variable_weight` | bool (added by `variable_weight.py`) |

### `dim_customers`

| Field | Type |
|-------|------|
| `customer_id`, `email`, `full_name`, `first_name`, `last_name`, `phone` | string |
| `city`, `province`, `country` | string \| null |
| `number_of_orders` | int |
| `total_spent` | float |
| `currency`, `created_at`, `updated_at`, `store` | string |

### Normalized products

| Field | Type |
|-------|------|
| `shopify_product_id`, `shopify_variant_id`, `raw_name`, `canonical_sku` | string |
| `variant_title`, `product_type`, `vendor`, `status` | string |
| `price`, `inventory_quantity`, `weight_value` | number |
| `weight_unit`, `created_at`, `updated_at`, `store` | string |

---

## Setup

### Prerequisites

- Python 3.12+
- Shopify Admin API access (custom app or OAuth token)
- (Future) Google Cloud project + BigQuery dataset
- (Future) Airtable base for SKU mapping

### Installation

```bash
cd "Feller's Ranch Data Funnel"
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**Current dependencies** (from venv usage in code):

- `requests`
- `python-dotenv`
- `google-cloud-bigquery` (for planned load stage)

Pin these in `requirements.txt` when you formalize the environment.

### Environment variables

Copy `.env.example` to `.env` and set values per store prefix.

For **Feller's Ranch** (`FLRS`):

```env
FLRS_TOKEN=shpat_...
FLRS_URL=your-store.myshopify.com
FLRS_SHOPIFY_CLIENT_ID=...
FLRS_SHOPIFY_CLIENT_SECRET=...
```

Repeat the same four variables for `CGAL1`, `CGAL2`, `CGAL3` when enabling Conger stores.

> **Security:** Never commit `.env`. Rotate any token that was ever committed or shared.

---

## Running the pipeline (today)

Run from the **project root** so imports resolve (`auth`, `extract`, `transform`).

```bash
# Test Shopify connection
python -m extract.shopify_client

# Extract only
python -m extract.extract_orders
python -m extract.extract_customers
python -m extract.extract_products
python -m extract.extract_inventory

# Transform + sample output (each module re-extracts live data)
python -m transform.normalize_orders
python -m transform.normalize_customers
python -m transform.normalize_products
python -m transform.variable_weight

# Full QA report (extract + transform + checks)
python -m transform.qa_checks
```

---

## Business logic notes

### Variable weight products

Shopify POS uses temporary products (often titled with `per lb`, `/lb`, `variable`, etc.) that can expire ~12 hours after creation. `variable_weight.py` tags these line items so they can be handled separately before they disappear from the catalog.

### Product SKU mapping

`normalize_products.py` accepts a `sku_mapping` dict (`raw_name` or `raw_sku` → `canonical_sku`). Without Airtable, it falls back to the variant SKU or flags rows as **unmapped** (QA failure).

### Multi-store

`shopify_client.run_query(..., store="conger_pos_1")` switches stores. Normalizers currently hardcode `store: "fellers_ranch"` — update when loading multiple channels.

---

## Roadmap

- [ ] Implement `extract/airtable_client.py` and wire SKU mapping into `normalize_products`
- [ ] Implement `load/bigquery_client.py`, `load_dims.py`, `load_facts.py`
- [ ] Implement `pipeline/run_pipeline.py` (stop on QA failure)
- [ ] Implement `pipeline/scheduler.py`
- [ ] Populate `requirements.txt` and `.env.example`
- [ ] Parameterize `store` / `channel` in normalizers for Conger POS + online

---

## License

Private / internal — Feller's Ranch.
