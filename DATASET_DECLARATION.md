# Dataset Declaration

**Project:** SaayaShift - Heat-Aware Shift Planner (Karachi-first)  
**Primary user:** A supervisor scheduling outdoor field work in Karachi.

## Declared datasets

### 1. Open-Meteo weather data

- **Publisher:** Open-Meteo
- **Sources:** [Historical Forecast API](https://open-meteo.com/en/docs/historical-forecast-api) for hourly history (2023-01-01 to 2025-12-31); [Forecast API](https://open-meteo.com/en/docs) for a rolling 72-hour outlook. These endpoints are one source, not two independent sources.
- **Licence:** API data under [CC BY 4.0](https://open-meteo.com/en/licence). The free API is for non-commercial use; attribution will be shown with weather data.
- **Collection/update:** Fetch the historical archive during the event. Fetch and retain the live forecast hourly during the event; record each request and fetch time.
- **Expected volume:** Approximately 26,304 hourly records per distinct returned weather grid cell for 2023-2025. Deduplicate locations using the grid coordinates returned by the API.

- **Update frequency:** Follows the selected weather model's update cycle, typically every few hours and model-dependent; the historical archive gains data as model runs are archived. Hourly fetches may therefore return no new forecast run. See [model update information](https://open-meteo.com/en/docs/model-updates).

### 2. OpenStreetMap Karachi features

- **Publisher:** OpenStreetMap contributors; queried through the [Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API/Language_Guide).
- **Data used:** Karachi roads and mapped parks/green spaces or facilities relevant to outdoor work zones. These features provide geographic context; they are not heat measurements or worker counts.
- **Licence:** [Open Database License (ODbL)](https://www.openstreetmap.org/copyright). Attribution and applicable share-alike requirements will be followed.
- **Collection/update:** Save a Karachi-area extract during the event, together with the exact query and fetch time. This is a snapshot, not an hourly-updating source.

- **Update frequency:** OSM edits are replicated continuously (minutely replication), and Overpass typically lags by a few minutes. The project takes a snapshot, not a live feed, and saves the response's `osm_base` timestamp.
  
**Independent source outside the climate-track suggestions:** OpenStreetMap. It is a separately maintained, contributor-built geospatial database used here for local work-zone context. It is credible for mapped geographic context because contributor edits and histories are publicly inspectable. Karachi coverage may be incomplete, so mapped features are treated as context only.

## Additional RAG reference sources

The planned guidance corpus includes [PMD Sindh Heatwave Bulletins](https://weather.gov.pk/regional/Sindh/heatwave-bulletin) and the [NDMA Heat Wave Survival Guide](https://ndma.gov.pk/storage/publications/September2025/h1HygK0WyGmzlPF2CXjj.pdf). Their reuse licences/terms must be confirmed with the publishers before downloading or ingesting them. If permission cannot be confirmed, these documents will be omitted or replaced with sources whose reuse terms are clear. They are guidance references, not training labels, and are not used to claim the minimum-volume requirement.

## Fit, collection and evaluation

The hourly weather data supports comparing candidate shift windows. OpenStreetMap supplies local work-zone context. The system reports a weather-based heat-exposure proxy and does not predict individual illness or declare a shift medically safe.

All selected data will be collected during the event under the applicable licences and terms. Raw responses/files will be preserved unchanged. `manifest.csv` will record each raw file's source, exact query or URL, fetch time, SHA-256 hash and licence.

## Baseline declared before evaluation

For each target hour **H** and zone, predict apparent temperature as the value 24 hours earlier (the same local hour on the previous day; Pakistan has no daylight saving, so this is exactly H − 24 h). Forecasts for H are issued at T = H − 24 h and may use only data timestamped at or before T. Use 2023-2024 for development (train on 2023, validate on 2024) and hold 2025 out as the chronological test period; do not tune on the test period. Report mean absolute error (MAE) in degrees Celsius.
