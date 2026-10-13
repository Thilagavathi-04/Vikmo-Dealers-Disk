# Vikmo DealerDesk — AI/ML Technical Decisions

## 1. Schema and Data Relationships

The backend uses Django models with PostgreSQL as the persistent database. The core domain covers products, inventory, dealers, orders, and order items.

- **Product:** Catalogue information and SKU identity.
- **Inventory:** Stock information used by inventory and reorder operations.
- **Dealer:** Dealer records associated with orders.
- **Order:** Order ownership, status, and order-level information.
- **OrderItem:** Individual products, quantities, and the applicable catalogue price captured when an order is created.

The schema separates catalogue data, stock data, and order data to keep their responsibilities clear. Order items preserve the price applicable at creation time rather than relying on a later catalogue price.

**Code evidence to verify:** `core/models.py` — cite the exact model definitions, every foreign key, and its `on_delete` choice. Explain each deletion policy using the actual implementation.

## 2. Retrieval: Design, Ranking, and Limitations

The assistant retrieves relevant catalogue products for natural-language requests instead of relying solely on the language model's internal knowledge. The retrieval design should prioritize relevant products while leaving current prices and stock to database-backed operations.

The main trade-off is simplicity versus retrieval quality. Catalogue search can fail when descriptions are sparse, product terminology differs from a dealer's wording, or several products have similar names. Retrieval results must therefore be treated as candidates, not proof that a product is an exact match.

**Code evidence to verify:** cite the actual product-search or retrieval implementation, including any embedding model, similarity calculation, database query, filtering, or ranking logic. Do not claim embeddings, a vector index, or a particular ranking method unless the code implements it.

## 3. Assistant Tool-Calling Loop

The assistant supports three business operations:

1. `search_parts` — find candidate catalogue products.
2. `check_stock` — retrieve stock information.
3. `create_draft_order` — request creation of a draft order.

The intended flow is: receive the user's message and session identifier, send the request to the configured LLM, execute requested tools through backend functions, return tool results to the model, and produce a final reply. Tool-call details should be included in the API response.

The model proposes tool calls; application code must validate arguments and enforce business rules. Creating a draft must not implicitly confirm an order.

**Code evidence to verify:** cite the assistant API view, LLM/tool-calling loop, tool definitions and dispatch logic, and the draft-order service. Confirm that every call is actually executed and reported as required by the API contract.

## 4. Live Price and Stock Grounding

Prices and inventory are dynamic business data. The assistant should obtain them from the database when the relevant tool executes instead of asking the LLM to recall or generate figures.

A retrieved product description or previous conversation is not an authoritative source for current price or stock. If the database operation fails or a product cannot be identified unambiguously, the assistant should report the uncertainty rather than invent a number.

Draft-order creation must also use backend validation and applicable business rules.

**Code evidence to verify:** cite `check_stock`, `search_parts`, and the draft-order service. Confirm exactly where database queries occur and whether the returned values—not model-generated values—are used in responses.

## 5. Untrusted Catalogue Data and Prompt Injection

Catalogue descriptions and supplier-provided text must be treated as untrusted data, not as instructions to the assistant. The assistant should remain within its supported DealerDesk operations and should not follow instructions embedded in product descriptions.

Tool allowlisting and backend validation can restrict which operations the model requests. However, these controls alone do not prove that prompt injection is fully prevented. If retrieved text is passed into the model's context, a malicious description may still influence its natural-language response.

The security boundary is therefore the application layer: validate tool arguments, enforce permissions and business rules in backend functions, restrict side effects to supported operations, and avoid treating catalogue content as trusted instructions.

**Code evidence to verify:** cite the actual system prompt, tool allowlist or dispatch logic, input validation, and any catalogue-content handling. Clearly distinguish implemented defenses from recommended improvements.

## 6. Demand Forecasting and Historical Validation

The forecasting command generates four weekly predictions for each of the 40 SKUs in `data/lead_times.csv`, for the weeks beginning 2026-09-28, 2026-10-05, 2026-10-12, and 2026-10-19.

The current implementation uses a simple recent-average baseline:

1. Load sales history from `data/sales_history.csv`.
2. Sort each SKU's observations chronologically.
3. Take the last 12 observed sales values, or all available observations when fewer than 12 exist.
4. Calculate their mean, round it to a non-negative whole number, and repeat that prediction for all four forecast weeks.
5. Write the results to `ml/forecast.csv`.

This is intentionally simple and reproducible, but it does not explicitly model promotions, changing festive demand, intermittent sales, or SKU-specific seasonality. Repeating the same prediction for all four horizons also cannot capture week-to-week changes.

Historical evaluation should use rolling chronological cutoffs: each prediction must use only observations available before its forecast origin. The existing `ml/evaluate_forecast.py` evaluates one-week-ahead predictions against naïve, 12-observation-average, and seasonal-naïve baselines. Its reported results are not four-week-horizon accuracy and must not be presented as such.

The existing one-week-ahead evaluation reported:

| Method | MAE | WAPE |
|---|---:|---:|
| Naïve, common evaluation set | 13.288 | 36.91% |
| 12-observation average, common evaluation set | 10.998 | 30.55% |
| Seasonal naïve, common evaluation set | 12.741 | 35.39% |
| 12-observation average, wider eligible set | 9.951 | 29.31% |

The first three methods use a common evaluation set requiring 52 prior observations. The wider-set result uses more eligible observations and is not a like-for-like comparison with those three figures.

**Limitation:** these results validate one-step-ahead predictions only. A rolling four-week backtest using identical forecast origins and all four future targets is still required before making claims about four-week performance. No actual future sales have been used to tune the forecast.

**Code evidence:** `core/management/commands/generate_forecast.py` — cite the history loading, chronological sorting, last-12-observation selection, mean calculation, and forecast-week loop. `ml/evaluate_forecast.py` — cite the historical cutoff and baseline calculations.

## 7. Difficult SKU Cases and Reorder Decisions

The forecasting implementation uses a common method for every SKU. This makes the output easy to reproduce, but it does not fully address the assignment's difficult cases:

- **Promotions:** known promotion information is not currently included in the described forecasting calculation.
- **Festive lift:** no explicit calendar or Diwali-related adjustment is applied.
- **Rarely sold SKUs:** a recent average can smooth intermittent demand and produce non-zero predictions even when sales are infrequent.
- **Short histories and newer SKUs:** the mean uses all available observations when fewer than 12 are available. With very little history, that estimate is less reliable.

The reorder service uses forecast demand and current stock to calculate replenishment suggestions. Its safety-stock and reorder-point calculations should follow the exact formula specified in `API_CONTRACT.md`; the formula and rounding should be documented directly from the implementation rather than inferred.

**Code evidence to verify:** cite `core/services/forecasting.py` for the actual reorder formula and live-stock lookup. Cite `core/management/commands/generate_forecast.py` for the short-history behavior. Promotion, festive, and intermittent-demand handling should be described as limitations unless separate code implements them.

## 8. Weakest Area and Next Improvements

The weakest area is the forecasting approach and its validation. The current 12-observation average is a transparent baseline, but it repeats a constant prediction across four weeks and does not explicitly account for promotion effects, festive demand, or intermittent sales. The current evaluation reports one-week-ahead results rather than a complete four-week backtest.

With two additional days, I would:

1. Implement a leakage-free rolling four-week backtest and compare the recent-average method against last-value and same-week-last-year baselines on identical forecast origins.
2. Evaluate errors separately for each horizon and for rare, new, and promotion-affected SKUs.
3. Incorporate known promotion and calendar features where the provided data supports them.
4. Add targeted tests for assistant tool validation, live price/stock grounding, and malicious catalogue descriptions.
5. Re-run the assignment's smoke test and verify clean-clone reproducibility.

The priority is to improve measurable correctness and reliability before adding model complexity or more interface features.