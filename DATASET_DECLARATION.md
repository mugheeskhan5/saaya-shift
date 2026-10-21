# Dataset Declaration

**Project:** SaayaShift - Heat-Aware Shift Planner (Karachi-first)  
**Primary user:** A supervisor scheduling outdoor field work in Karachi.

## Source 1: Open-Meteo weather data

- **Source and publisher:** Open-Meteo Historical Forecast API for historical hourly forecasts and Open-Meteo Forecast API for the current outlook. These endpoints are one publisher and count as one source.
- **URLs:** [Historical Forecast API documentation](https://open-meteo.com/en/docs/historical-forecast-api) and [Forecast API documentation](https://open-meteo.com/en/docs); data endpoints are `https://historical-forecast-api.open-meteo.com/v1/forecast` and `https://api.open-meteo.com/v1/forecast`.
- **Licence and terms:** Weather data is provided under [CC BY 4.0](https://open-meteo.com/en/licence), with attribution. The free API is for non-commercial use under [Open-Meteo's terms](https://open-meteo.com/en/terms); this hackathon project will use it non-commercially and display attribution with weather data.
- **Update frequency:** The live forecast follows the selected weather model's update cycle, typically every few hours and model-dependent. The historical archive gains data as model runs are archived. The project will record the requested model (where available) and fetch time; repeated hourly checks do not imply a new forecast run each hour. See [model update information](https://open-meteo.com/en/docs/model-updates).
- **Expected volume:** Request hourly data for 2023-01-01 through 2025-12-31. This is approximately **26,304 hourly records per distinct returned grid cell** (three years, including leap year 2024), exceeding the two-year hourly-data threshold on its own. Duplicate coordinates that resolve to the same returned grid cell will be deduplicated.

## Source 2: OpenStreetMap Karachi features

- **Source and publisher:** OpenStreetMap (OSM), published and maintained by the OpenStreetMap Foundation with data contributed by the mapping community; Karachi features will be queried through the [Overpass API](https://overpass-api.de/api/interpreter). The [Overpass API guide](https://wiki.openstreetmap.org/wiki/Overpass_API) documents the query service.
- **Licence and terms:** OSM data is available under the [Open Database License (ODbL)](https://www.openstreetmap.org/copyright). The project will attribute “© OpenStreetMap contributors” and comply with applicable ODbL share-alike requirements.
- **Update frequency:** OSM edits are replicated continuously; OSM provides minutely replication updates, while Overpass commonly has a short replication delay of a few minutes. This project will collect a Karachi-area snapshot during the event and save the response's `osm_base` timestamp, exact query, and fetch time. It is a snapshot, not a continuously refreshed project feed.
- **Expected volume:** The number of returned road, park/green-space, and relevant facility features depends on the exact Karachi-area query and will be reported in the manifest after collection. This source supplements the weather data; the volume threshold is met by Source 1 alone.

**Source outside the climate-track suggestions:** OpenStreetMap is the selected outside-track-list source. It is a separate, contributor-maintained geographic database rather than a weather/climate API. It is credible for mapped geographic context because contributors maintain map objects and their edit histories are publicly inspectable ([OSM contributor information](https://wiki.openstreetmap.org/wiki/Contributors)). Karachi coverage may be incomplete, so the project will treat mapped features as context, not as proof of shade, heat exposure, worker presence, or safety.

## Fit to the problem and primary user

Hourly apparent temperature from Open-Meteo lets a Karachi supervisor compare proposed outdoor shift windows using a consistent weather-based heat-exposure proxy. OSM roads and mapped green spaces or facilities can help locate supervisor-selected work zones and relevant nearby context. OSM does not measure local temperature or establish that a route or worksite is safe. SaayaShift will explain its data limits and will not predict individual illness or declare a shift medically safe.

## Baseline declared before evaluation

Before viewing any evaluation results, freeze this baseline: for each target hour **H**, predict apparent temperature as the value for the same local hour on the previous day (**H minus 24 hours**). Use 2023-2024 for development and hold 2025 out as the chronological test period; do not tune on the test period. Report mean absolute error (MAE) in degrees Celsius.

## Collection and provenance

Selected data will be fetched during the event under the stated licences and terms. Raw responses will be preserved unchanged. `manifest.csv` will record each raw file's source, exact URL/query, fetch time, SHA-256 hash, licence, and (for OSM) the `osm_base` timestamp.

Potential PMD or NDMA heat-safety documents are not part of the declared dataset or RAG corpus unless their publishers' reuse terms or permission are confirmed before collection. If reuse cannot be confirmed, they will be omitted or replaced with material whose terms permit the intended use.
