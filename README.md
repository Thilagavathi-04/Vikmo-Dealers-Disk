# Vikmo DealerDesk

Vikmo DealerDesk is a Django REST API for automotive parts dealer operations. It supports product catalogue management, inventory updates, dealer management, draft orders, an LLM-powered assistant, demand forecasting, and reorder suggestions.

## Technology Stack

- **Backend:** Python, Django, Django REST Framework
- **Database:** PostgreSQL
- **LLM provider:** Groq
- **Forecasting:** Python, CSV-based demand forecasts, historical sales data, and baseline evaluation
- **Configuration:** Environment variables loaded from `.env`

## Features

- Browse, search, filter, create, and update products.
- Manage dealer records.
- Update inventory quantities with a reason.
- Create and retrieve draft orders using current catalogue prices.
- Use the AI assistant to search parts, check stock, and create draft orders.
- Retrieve per-SKU forecasts and reorder suggestions based on forecast demand, supplier lead times, safety stock, and current inventory.
- Seed product and dealer data repeatedly without creating duplicates.

## Requirements

- Python 3.11 or later
- PostgreSQL
- A Groq API key for live assistant requests

## Setup

Clone the repository and enter the project directory:

```bash
git clone https://github.com/Jslxh/vikmo.git
cd vikmo
```

Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

On Windows, activate the environment with:

```powershell
.venv\Scripts\activate
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Create the local environment file:

```bash
cp .env.example .env
```

Edit `.env` and configure the required values:

- `DATABASE_URL` — PostgreSQL connection URL.
- `GROQ_API_KEY` — API key for live assistant requests.
- `DJANGO_SECRET_KEY` — private Django secret key.
- Supplier-related settings, if the supplier integration is enabled.

Use the actual environment variable names and formats documented in `.env.example` and the application settings. Never commit `.env` or real credentials.

## Database Setup

Make sure PostgreSQL is running and the configured database exists.

Apply database migrations:

```bash
python manage.py migrate --noinput
```

Seed the initial product catalogue and dealer data:

```bash
python manage.py seed_data
```

Run the seed command again to check repeatability:

```bash
python manage.py seed_data
```

The seed command is intended to be idempotent: repeated execution should not create duplicate seeded records.

## Run the Server

Start the Django development server:

```bash
python manage.py runserver 0.0.0.0:8000
```

Check the health endpoint:

```bash
curl http://localhost:8000/api/health/
```

Expected response:

```json
{"status":"ok"}
```

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health/` | Health check |
| GET, POST | `/api/products/` | List or create products |
| GET, PATCH | `/api/products/<sku>/` | Retrieve or update a product |
| PUT | `/api/inventory/<sku>/` | Update inventory |
| GET, POST | `/api/dealers/` | List or create dealers |
| GET | `/api/dealers/<dealer_id>/` | Retrieve a dealer |
| GET, POST | `/api/orders/` | List or create draft orders |
| GET | `/api/orders/<order_number>/` | Retrieve an order |
| POST | `/api/assistant/chat/` | Chat with the AI assistant |
| GET | `/api/forecast/<sku>/` | Retrieve SKU forecasts and reorder calculations |
| GET | `/api/reorder-suggestions/` | List products needing replenishment |

List endpoints support pagination where implemented.

For request fields, response formats, validation rules, and error codes, refer to [`API_CONTRACT.md`](API_CONTRACT.md).

## AI Assistant

The assistant uses Groq tool calling to perform supported DealerDesk operations.

Supported tools:

- `search_parts` — search the parts catalogue.
- `check_stock` — check current inventory.
- `create_draft_order` — create a draft order using application data.

Product prices and stock quantities should be grounded in the application's catalogue and inventory records rather than invented by the language model.

The assistant creates draft orders; it does not directly confirm or fulfil orders.

Configure `GROQ_API_KEY` in `.env` before testing live assistant requests. Assistant behavior depends on the configured model, tool implementations, application validation, and provider availability.

## Forecasting

The generated forecast file is `ml/forecast.csv`.

It contains these columns:

- `sku`
- `week_start`
- `forecast_units`

The current dataset contains 40 SKUs and four forecast weeks per SKU, for a total of 160 rows.

Regenerate the forecast file with:

```bash
python manage.py generate_forecast
```

The current generator uses recent historical sales observations to calculate a per-SKU average and writes forecasts for the four configured weeks. Review `core/management/commands/generate_forecast.py` for the exact implementation.

Reorder calculations use forecast demand over the supplier lead time, safety stock based on historical sales variability, and current inventory. Refer to `API_CONTRACT.md` and the implementation for the exact reorder formula.

## Forecast Evaluation

A rolling-origin historical backtest compared three baseline forecasting methods across four forecast horizons. All methods used the same eligible forecast origins.

| Method | MAE | WAPE |
|---|---:|---:|
| Last observed value | 13.583 | 38.22% |
| 12-observation average | 10.998 | 30.95% |
| Same week last year (52-observation lag) | 12.686 | 35.70% |

The evaluation used:

- 1,862 historical forecast origins.
- Four forecast horizons per origin.
- 7,448 predictions per method.
- A common evaluation set requiring 52 prior weekly observations and four subsequent actual observations.

The 12-observation average achieved the lowest overall MAE and WAPE among the three evaluated methods. Its MAE was approximately 19.0% lower than the last-observation baseline.

The backtest is implemented in `ml/backtest_four_week.py` and can be run with:

```bash
python ml/backtest_four_week.py
```

### Evaluation Limitations

- Results describe the available historical dataset and do not guarantee future forecast accuracy.
- The comparison evaluates baseline methods, not every possible forecasting model.
- Promotions, festive demand spikes, new SKUs, and intermittent demand need additional targeted evaluation.
- Historical backtest results do not establish that the forecast performs equally well for every individual SKU.
- The four-week backtest is distinct from the currently generated forecast file; its metrics should not be interpreted as a guarantee of the generated predictions.

## Validation and Smoke Testing

Run Django's system checks:

```bash
python manage.py check
```

Check whether model changes require new migrations:

```bash
python manage.py makemigrations --check --dry-run
```

Run the API smoke test against a running server:

```bash
python smoke_test.py --base-url http://localhost:8000 --track aiml
```

The smoke test checks core API contract behavior, assistant response shape, and forecast endpoints. In the latest recorded run, all **10 of 10 smoke checks passed**.

The smoke test is not a complete evaluation of assistant answer quality, tool-call correctness, forecast accuracy, or every business rule.

The Django test command was also run:

```bash
python manage.py test
```

That run discovered **zero tests**. Therefore, it should not be interpreted as a passing automated unit-test suite. Additional automated tests should be added for critical business logic, tool execution, and forecasting.

## Clean-Clone Verification

For a reproducible setup:

1. Clone the repository into a clean directory.
2. Create and activate a virtual environment.
3. Install dependencies from `requirements.txt`.
4. Configure `.env` using `.env.example`.
5. Create or configure the PostgreSQL database.
6. Run `python manage.py migrate --noinput`.
7. Run `python manage.py seed_data` twice and verify that duplicate records are not created.
8. Start the server and execute the smoke test.
9. Run the forecast generator and confirm the output contains the expected SKUs and forecast dates.

The repository should contain the required migrations, data files, forecast CSV, and setup documentation. A clean-clone procedure is considered verified only after it has actually been executed successfully.

## Project Decisions

See [`DECISIONS.md`](DECISIONS.md) for the design rationale, retrieval and assistant decisions, forecasting trade-offs, known limitations, and future improvements.

## Security

- Keep `.env` out of version control.
- Use placeholder values in `.env.example`.
- Never commit API keys, database passwords, or production secret keys.
- Validate user input on the server.
- Keep order creation constrained to the supported draft-order workflow.
- Treat catalogue content and other retrieved text as data, not as trusted instructions to the assistant.

## Demo Video

**Demo video:** https://drive.google.com/file/d/1HF0P6v0Ghq3R25kwLBkqxxjJHXg5XZ4S/view?usp=drive_link

The demonstration should show:

1. Application setup and health check.
2. Part search and stock lookup.
3. An assistant interaction that invokes the appropriate tools.
4. Draft-order creation and confirmation that the order remains a draft.
5. Forecast retrieval and reorder suggestions.
6. A brief explanation of the forecasting backtest and its limitations.

Use your own explanation to describe the implementation and be prepared to discuss the code and design decisions.