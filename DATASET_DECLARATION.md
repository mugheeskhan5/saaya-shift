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

### 2. OpenStreetMap Karachi features

- **Publisher:** OpenStreetMap contributors; queried through the [Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API/Language_Guide).
- **Data used:** Karachi roads and mapped parks/green spaces or facilities relevant to outdoor work zones. These features provide geographic context; they are not heat measurements or worker counts.
- **Licence:** [Open Database License (ODbL)](https://www.openstreetmap.org/copyright). Attribution and applicable share-alike requirements will be followed.
- **Collection/update:** Save a Karachi-area extract during the event, together with the exact query and fetch time. This is a snapshot, not an hourly-updating source.

**Independent source outside the climate-track suggestions:** OpenStreetMap. It is a separately maintained, contributor-built geospatial database used here for local work-zone context.

## Additional RAG reference sources

The planned guidance corpus includes [PMD Sindh Heatwave Bulletins](https://weather.gov.pk/regional/Sindh/heatwave-bulletin) and the [NDMA Heat Wave Survival Guide](https://ndma.gov.pk/storage/publications/September2025/h1HygK0WyGmzlPF2CXjj.pdf). Their reuse licences/terms must be confirmed with the publishers before downloading or ingesting them. If permission cannot be confirmed, these documents will be omitted or replaced with sources whose reuse terms are clear. They are guidance references, not training labels, and are not used to claim the minimum-volume requirement.

## Fit, collection and evaluation

The hourly weather data supports comparing candidate shift windows. OpenStreetMap supplies local work-zone context. The system reports a weather-based heat-exposure proxy and does not predict individual illness or declare a shift medically safe.

All selected data will be collected during the event under the applicable licences and terms. Raw responses/files will be preserved unchanged. `manifest.csv` will record each raw file's source, exact query or URL, fetch time, SHA-256 hash and licence.

**Declared baseline:** Predict next-hour apparent temperature using the value from the same hour on the previous day. Evaluate on a later, time-held-out period using MAE in degrees Celsius.
