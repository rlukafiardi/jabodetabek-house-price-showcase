# Model card: Jabodetabek house asking-price estimator

Status: 2026-10-30, final model scored once on the holdout. Nothing here is a valuation or financial advice.

## What it estimates
The asking price a Portal listing for a house like the one described would carry, in Rp, and the same per m² of land.
It is **not** a transaction price, an appraisal or a mortgage valuation. Asking prices run above what houses sell for.

## Intended use
Getting a rough sense of where a house sits in the Jabodetabek market (buyers, sellers, curious public) and comparing areas.
Not for loans, tax, insurance, legal disputes or automated decisions about people.

## Inputs
A point in Jabodetabek, land area, building area, bedrooms and bathrooms; optional floors, specs (electricity capacity, carport,
car access, garage, maid rooms, furnished level, piped water) and notes on the house in free text (for example furnished, new,
gated). The service derives distances to the nearest rail station, MRT/LRT, busway stop and Monas, the flood hazard index, the
OpenStreetMap context and the kecamatan from the point. The land title (SHM, HGB and others) is not a model input.

## Model
Mean of three regressors (XGBoost, extra trees, ridge) predicting log price per m² of land, using location and distance
features, size and room counts, floors, listing age, keywords from the title and description, the agent-filled specs
(electricity capacity, carport, furnished level and similar), OpenStreetMap context within and around the site (distance to
major roads, land-use shares within 500 m, rivers, rail and power lines, distance to the nearest of three CBD cores and to
business centres) and a text model score. 48 features plus the text score. Price = land area x prediction.
Code: `src/modeling/ensemble.py`. Range: `src/modeling/intervals.py`.

## Training data
Portal secondary-market house listings created 2025-04 to 2026-08 (still-active listings only: the months of mid-2025 hold about 105 to 126 listings each against about 250 in 2026, so older listings have mostly sold or been withdrawn), collected by polite scraping (3 s per request) of listing
pages, plus OpenStreetMap, BIG boundaries and BNPB flood hazard. 4,031 usable listings after cleaning: 3,469 for training
and 562 held out and scored once. Listings are sampled by place names in the listing slug, so houses whose slug names only a street or a cluster
are under-represented, and rural kecamatan have few or no listings.

## Performance
Median absolute percentage error of price (half of the estimates are closer than this); all out-of-fold on training data
unless marked holdout.

| Measure | Value |
|---|---|
| Random 5x5 CV, median error | 20.3% (3,469 training listings) |
| Spatial-block CV (unseen areas), median error | 23.1% |
| Mean error (tail check) | 30.9% random, 33.5% spatial |
| **Holdout (562 listings, scored once), median error** | **22.7%** (95% interval 20.9 to 25.1) |
| Holdout mean error | 34.3% (29.6 to 39.7) |
| Share within ±20% of the asking price | 45% |
| Coverage of the 80% range on the holdout | 80.6% (target 80%) |
| Coverage of the 50% range on the holdout | 52.3% (target 50%) |
| Baselines (holdout) | kecamatan median 28.0% (25.5 to 29.6), city median 35.8% (31.5 to 39.8) |
| Previous single tuned XGBoost (holdout) | 25.1% (22.2 to 28.8) |

Checks (`src/analysis/audit.py`): 43 holdout listings have a same-house listing in training; without them the holdout median is
22.9% (21.1 to 25.4%), so that leak is small. Portal's own estimate has a median error of 23.4% against 20.1% for this model on
the same training listings (it is level with the model, 15.1% against 15.8%, on the listings it does not flag as low accuracy);
whether its model saw the asking price is unknown. The 20 usable random pages score 17.8%, too few to conclude.

By city on the holdout (22 to 91 listings each, so rough): best Jakarta Timur 15.9% and Depok 17.8%; worst Kab. Bogor 29.1%
and Kota Bogor 30.6%. Listings at a district centroid score the same as those with their own coordinates (22.7% against 22.8%).
Learning curve (3 repeats): under random CV the error keeps falling with more rows (21.9% at 693 rows to 20.2% at 2,775),
under spatial CV it has flattened since about 2,000 rows, so more data helps known areas and not unseen ones.

Earlier data versions (1,249 listings, single XGBoost, 18.1% on its test set) are not comparable: the larger sample includes
harder outer areas.

## Known limitations
- **Asking prices, not sale prices.** The same house is listed at different prices by different agents; from same-house pairs
  that noise is about 6%, small next to the model error.
- **Regression to the mean.** The cheapest listings are over-estimated and the dearest under-estimated (on the first test
  set: +16% and -24% for the extreme quarters).
- **Thin coverage:** 23 of 183 kecamatan have 1 to 4 listings and 13 have none (all remote parts of Kab. Bogor, Kab. Tangerang
  and Kab. Bekasi); estimates there extrapolate and the range is wider.
- **The text score is the strongest single input** (about 32% mean SHAP effect). It mostly encodes place names and wording
  (neighbourhoods, "mewah", "subsidi", "murah"), learned from full listing descriptions. A short note typed into the app is not
  the same kind of text, so the score is unreliable there; the app should treat it as optional.
- **Unobserved house quality** (condition, finish, street width, exact position) is not captured; no photos are used.
- **District-centroid coordinates:** about a third of listings gave no coordinate of their own; the model learned from them.
- **Take-over (over kredit) listings and houses with more than 8 bedrooms or bathrooms are out of scope.**
- **Time:** trained on a 17-month window of still-active listings (no sold or withdrawn ones, so slow-selling and overpriced houses may be over-represented in the older months); prices drift, so the estimate is refreshed monthly and its live error is
  published on the About page.

## Ranges
Each estimate is shown with two ranges from out-of-fold errors under spatial-block CV, by city: a 50% range (likely) and an
80% range (possible). Final all-cities 80% range: 0.64x to 1.67x of the estimate (50%: 0.82x to 1.32x); by city the 80% range runs from 0.51x to
1.76x (Kab. Bogor) up to 0.69x to 2.24x (Jakarta Pusat). Table: `reports/tables/prediction_ranges.csv`.

## Monitoring and refresh
Weekly: the live model is scored on listings first seen after its training cutoff. Monthly: a challenger is trained and
replaces the live model only if it is better than the noise on identical folds and in no city worse by more than a set margin.


## Data
No listing-level data, descriptions or page contents are published, in this repository or on the site: only kecamatan and H3 aggregates (at least 5 listings per area) and model estimates.
