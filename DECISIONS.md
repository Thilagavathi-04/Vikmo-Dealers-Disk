
# Vikmo DealerDesk — Technical Decisions

## 1. Backend Architecture

The application uses Django and Django REST Framework to expose APIs for the dealer inventory and ordering workflow. Django provides a structured backend, ORM-based database access, request validation, and a maintainable way to separate business logic from API views.

Business rules are kept in backend services rather than relying on frontend calculations. This allows inventory checks, forecast generation, and reorder suggestions to be reused consistently by API endpoints and other backend components.

The AI/ML track integrates the assistant, inventory data, forecasting, and reorder suggestions into the existing application instead of maintaining separate, disconnected implementations.

## 2. Data Management and Order Integrity

Inventory and product information are treated as the source of truth for stock availability and pricing. The assistant must not invent product prices, SKU details, or stock quantities.

Order creation follows a draft-first approach. The assistant can prepare a draft order, but the draft is not equivalent to a confirmed or fulfilled order. This reduces the risk of unintended purchasing actions and gives the user an opportunity to review the details before proceeding.

Database operations should validate product identifiers and quantities before persisting order data. Invalid SKUs, unavailable products, and invalid quantities should produce clear errors instead of silently creating incorrect records.

Seed operations should be repeatable without duplicating the same baseline data. Environment-specific secrets must remain outside version control, while `.env.example` documents the required configuration using placeholders.

## 3. AI Assistant Architecture and Tool Calling

The assistant uses tool calling to interact with application data and business operations. Instead of asking the language model to guess inventory details or perform database operations directly, the application exposes narrowly defined tools.

The principal tools are:

- `search_parts`: searches for relevant parts using the available catalogue.
- `check_stock`: retrieves current stock information for the requested items.
- `create_draft_order`: creates a draft order after the necessary details have been collected and validated.

The model is responsible for understanding the user's request, deciding which tool is relevant, collecting missing information, and presenting the results clearly. The backend remains responsible for retrieving authoritative data and enforcing business rules.

Tool calls should be executed only when appropriate for the user's request. The assistant should use returned tool results rather than inventing successful operations or presenting unverified results as completed actions.

## 4. Data Grounding, Clarification, and Conversation Context

The assistant should answer inventory and pricing questions using retrieved application data. If the available information is insufficient, it should explain the limitation or ask a clarification question rather than fabricate an answer.

For order-related requests, the assistant should collect the required details before creating a draft. These may include the requested part, SKU, quantity, and any other fields required by the backend contract.

Conversation context should be used to resolve relevant follow-up messages. For example, if the user specifies a quantity after discussing a particular part, the assistant should retain the relevant context when it is unambiguous. If multiple interpretations remain possible, it should ask the user to clarify.

The assistant should remain focused on the dealer inventory and ordering use case. Unrelated requests should not trigger inventory operations or draft-order creation.

## 5. Prompt Injection and Security Boundaries

Catalogue descriptions, product names, retrieved documents, and other external data must be treated as data, not as instructions that can override the assistant's rules.

The assistant must not follow instructions embedded in catalogue content that attempt to change its role, disclose secrets, bypass validation, or trigger unauthorized actions.

Security-sensitive operations must be enforced by the backend rather than by relying only on the language model's instructions. Tool inputs should be validated, and database access should be restricted to the operations required by each tool.

The application should not expose API keys, credentials, environment variables, or other secrets in model prompts, user-facing responses, logs, or committed configuration files.

## 6. Demand Forecasting Approach

The forecasting workflow uses historical sales data from `ml/sales_history.csv` and the forecast input data from `ml/forecast.csv`.

The current baseline forecasting implementation is based on the mean of the most recent 12 available historical observations for each SKU. The generated value is rounded to an integer, constrained to be non-negative, and used for the four forecast weeks.

This approach provides a simple and reproducible baseline that can be evaluated against other forecasting methods. It does not require a complex model to be trained before the application can produce a forecast.

Three methods were considered during historical evaluation:

1. **Last-value baseline:** uses the latest observed sales quantity.
2. **Recent-average baseline:** uses the mean of the most recent 12 observations available at the forecast origin.
3. **Same-week-last-year baseline:** uses the historical observation corresponding to the same seasonal week, when available.

The recent-average baseline performed best on the common historical evaluation set described in Section 7. This supports using it as the current baseline, but it does not establish that it will be the best method for every SKU or business condition.

Known promotions, festival demand such as Diwali, intermittent sales, and new SKUs require additional evaluation. The current baseline does not explicitly model these effects.

## 7. Historical Backtest and Evaluation Results

The forecasting methods were compared using a rolling-origin historical backtest. Each forecast origin used only observations available before that origin, and the predictions were compared with subsequent actual sales.

The common evaluation set required at least 52 prior weekly observations and four subsequent actual observations. The evaluation covered 1,862 forecast origins and four forecast horizons, producing 7,448 predictions per method.

### Overall results

| Method | MAE | WAPE | Predictions |
|---|---:|---:|---:|
| Last value | 13.583 | 38.22% | 7,448 |
| 12-observation average | 10.998 | 30.95% | 7,448 |
| Same week last year | 12.686 | 35.70% | 7,448 |

MAE is the mean absolute error between predicted and actual quantities. Lower MAE indicates smaller average absolute prediction errors.

WAPE is the sum of absolute errors divided by the sum of actual quantities, expressed as a percentage. Lower WAPE indicates a smaller aggregate absolute error relative to actual demand.

On this evaluation set, the 12-observation average achieved the lowest MAE and WAPE among the three methods. Its MAE was approximately 19% lower than the last-value baseline.

### Results by forecast horizon

| Horizon | Method | MAE | WAPE | Predictions |
|---|---|---:|---:|---:|
| Week 1 | Last value | 13.412 | 37.18% | 1,862 |
| Week 1 | 12-observation average | 11.096 | 30.76% | 1,862 |
| Week 1 | Same week last year | 12.719 | 35.26% | 1,862 |
| Week 2 | Last value | 13.259 | 37.00% | 1,862 |
| Week 2 | 12-observation average | 11.169 | 31.16% | 1,862 |
| Week 2 | Same week last year | 12.779 | 35.65% | 1,862 |
| Week 3 | Last value | 14.054 | 39.70% | 1,862 |
| Week 3 | 12-observation average | 11.027 | 31.15% | 1,862 |
| Week 3 | Same week last year | 12.660 | 35.76% | 1,862 |
| Week 4 | Last value | 13.605 | 39.05% | 1,862 |
| Week 4 | 12-observation average | 10.699 | 30.71% | 1,862 |
| Week 4 | Same week last year | 12.589 | 36.13% | 1,862 |

The recent-average method outperformed the other two methods at each of the four forecast horizons in this backtest.

These results apply to the common evaluation set and the tested baseline implementations. They should not be interpreted as proof of performance for new SKUs, promotions, festival periods, or other conditions not separately evaluated.

## 8. Reorder Suggestions and Inventory Planning

Reorder suggestions combine demand estimates with current inventory and supplier lead-time information. The reorder API should use the formula defined in `API_CONTRACT.md` as the authoritative contract.

The implementation should use live stock values from the application rather than assuming that historical stock values are still current. Forecast demand and stock information serve different purposes: forecasts estimate future demand, while inventory data indicates current availability.

Where the contract uses a service factor of 1.65 and sample standard deviation, those values should be applied consistently with the contract's safety-stock and lead-time calculations. The square root of lead time is relevant when calculating safety stock under the corresponding statistical assumptions.

Reorder quantities must not be negative. Missing lead times, insufficient sales history, and invalid inventory data should be handled explicitly instead of producing misleading recommendations.

Forecast and reorder outputs should remain distinct. A demand forecast estimates expected sales, while a reorder suggestion considers the forecast together with stock position, lead time, and the agreed replenishment policy.

## 9. Configuration and Reproducibility

Configuration should be provided through environment variables where appropriate. The repository should include `.env.example` with placeholder values and setup instructions without exposing real credentials.

The virtual environment should not be committed. Dependency installation and application startup should follow the instructions in the README.

Database migrations should be included in version control so that a clean environment can reproduce the schema. Seed commands should be safe to run repeatedly.

The project should be tested from a clean setup where practical. This helps identify dependencies on local files, uncommitted configuration, or data that exists only in the developer's environment.

## 10. Testing and Validation Evidence

The following checks were performed during development:

- `python manage.py check` completed successfully.
- The forecast CSV validation confirmed 160 rows, 40 unique SKUs, four forecast dates, and non-negative quantities.
- `python smoke_test.py --base-url http://127.0.0.1:8000 --track aiml` passed all 10 checks.
- The historical rolling-origin backtest completed for the three forecasting baselines.
- `python manage.py test` completed but discovered zero tests.

The smoke test validates expected API response shapes and basic endpoint behavior. Passing these checks does not prove that all assistant responses are correct, that the forecasting model performs well in every situation, or that the application is secure against every attack.

Because the Django test command discovered zero tests, automated unit and integration test coverage remains an area for improvement. Dedicated tests should be added for tool argument validation, inventory edge cases, draft-order creation, forecast generation, and reorder calculations.

## 11. Current Limitations and Future Improvements

The current forecasting implementation is intentionally simple. It provides a reproducible baseline, but it does not explicitly account for trends, promotions, festival effects, stockouts, or intermittent demand.

Potential improvements include:

- Evaluate forecasting methods separately for intermittent-demand and high-volume SKUs.
- Add promotion and festival features when reliable historical information is available.
- Evaluate new-SKU handling and insufficient-history behavior.
- Add automated tests for forecasting, inventory calculations, and assistant tool calls.
- Track forecast errors over time and compare future models against the current baseline.
- Add clearer handling for missing or inconsistent inventory and supplier data.
- Expand security tests for malicious instructions embedded in retrieved catalogue content.
- Verify all reorder calculations against the exact API contract and its expected examples.

These are proposed improvements and should not be treated as already implemented.

## 12. Implementation References

The following files are relevant to the decisions described above:

- `ml/forecast.csv` — forecast input data.
- `ml/sales_history.csv` — historical sales data used for forecasting evaluation.
- `ml/backtest_four_week.py` — rolling-origin historical comparison of forecasting baselines.
- `core/management/commands/generate_forecast.py` — forecast generation command.
- `API_CONTRACT.md` — API behavior and reorder calculation contract.
- `smoke_test.py` — API smoke-test script.
- `.env.example` — example environment configuration.
- `README.md` — setup and execution instructions.