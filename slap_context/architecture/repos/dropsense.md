# `dropsense` — repo skill (auto-generated)

_Last refreshed: 2026-07-07 06:30 UTC_

## At a glance

- **Owner team**: Backend-Labs
- **Declared stack** (from repos.json): js
- **Production branch**: `main`
- **Remote**: https://github.fkinternal.com/Flipkart/dropsense.git
- **Source files** (filtered to relevant extensions): 272

**Stated purpose** (from manifest):
> FTUE (first-time user experience) and Styledrops feature service. Generates Style Drops, handles drop liking and the FTUE journey.

**Owns these features:**
- Style Drops
- Styledrops
- FTUE
- drop generation
- liked drops

## Build / dependency files present

- `pom.xml` → Java (Maven)
- `Dockerfile` → containerised service

## Language breakdown

Source-file counts by extension (top 8):

- `.java`: 271 files
- `.sh`: 1 files

## Module map — top directories with mined symbols

Symbols below are extracted from real class-file names / grep output on the current clone. Each list is capped to keep the skill file readable (limit: 20 per bucket).

### `src/` — 271 source files
- **Services** (15): `AutoQCService`, `AvatarGenService`, `CatalogueService`, `DailyDropTriggerService`, `DrapingService`, `DynamicPromptService`, `FdpService`, `GcsService`, `GcsStorageService`, `GraySkullService`, `PersonaService`, `PushNotificationService`, `StorageService`, `StyleDropJobService`, `StyleDropOptOutService`
- **HTTP entry points** (1): `GlobalExceptionHandler`
- **Exceptions** (23): `AutoQCApiException`, `AutoQCValidationException`, `AvatarGenApiException`, `AvatarGenValidationException`, `AvatarStoreException`, `CatalogueServiceException`, `CircuitBreakerOpenException`, `DrapingApiException`, `DrapingValidationException`, `DropsenseException`, `DynamicPromptApiException`, `DynamicPromptValidationException`, `GcsOperationException`, `GenvoyRateLimitException`, `InvalidRequestException`, `JobNotFoundException`, `NpsApiException`, `PersonaApiException`, `PersonaValidationException`, `PipelineDataNotFoundException` _(+3 more)_
- **Enums** (11): `AggFragmentType`, `AvatarStatus`, `Gender`, `JobMode`, `NotificationStatus`, `OptOutStatus`, `PipelineStatus`, `PipelineTopic`, `StageStatus`, `StyleDropStatus`, `VTONAggFragmentType`
- **Data contracts**: 19 DTO / Request / Response classes

### `infra/` — 1 source files

### `charts/` — 0 source files

### `config/` — 0 source files

## HTTP routes (15 @*Mapping annotations found)

| Verb | Path |
|---|---|
| `REQUEST` | `/api/v1/health` |
| `REQUEST` | `/api/v1/styledrops/job` |
| `POST` | `/dispatch-cohort-tick` |
| `GET` | `/drapes` |
| `POST` | `/mark-failed` |
| `POST` | `/opt-out` |
| `GET` | `/stuck` |
| `GET` | `/test/invalid-request` |
| `GET` | `/test/job-not-found` |
| `GET` | `/test/raw-image-not-found` |
| `POST` | `/trigger` |
| `POST` | `/trigger-daily-drop` |
| `GET` | `/{jobId}/trace` |
| `GET` | `/{userId}/daily-drops` |
| `GET` | `/{userId}/jobs` |

## Config files present (2 Spring/YAML)

- `src/main/resources/application-local.yml`
- `src/main/resources/application.yml`

## Recent commits (1 most recent)

| Date | Author | Subject |
|---|---|---|
| 2026-06-24 | Kuldeep SinghBhandari | Merge pull request #57 from Flipkart/feat/jvm-metrics-jmx |

## README excerpt (first ~3 KB)

> # Dropsense
>
> StyleDrops FTUE optimization pipeline — Pulsar event-driven fan-out with Java producer-consumer constructs.
>
> ## Local Development Setup
>
> > **Note:** This section is for local development only. Production infrastructure is managed separately and is not affected by any of the files or steps below.
>
> ### Prerequisites
>
> - Docker and Docker Compose installed
> - Java 21
> - Maven 3.9+
>
> ### Start Infrastructure
>
> ```bash
> docker compose up -d
> ```
>
> This starts three containers:
>
> | Container | Purpose | Port |
> |---|---|---|
> | `dropsense-aerospike` | Aerospike (namespace: `dropsense`, in-memory, 512MB) | `3100` |
> | `dropsense-pulsar` | Apache Pulsar standalone | `6650` (binary), `8080` (admin) |
> | `dropsense-pulsar-init` | Creates pipeline topics, then exits | — |
>
> Pulsar topics are created automatically once the broker is healthy. The init container exits after setup.
>
> ### Verify Services
>
> Aerospike CLI tools (`asinfo`, `aql`) are not bundled with Docker. On macOS, install them separately:
>
> - [Download Aerospike Tools for macOS](https://download.aerospike.com/artifacts/aerospike-tools/latest/aerospike-tools_13.0.0_macOS_x86_64.pkg)
>
> ```bash
> # Aerospike (requires aerospike-tools installed)
> asinfo -h localhost -p 3100 -v status
>
> # Pulsar broker
> curl -s http://localhost:8080/admin/v2/brokers/healthcheck
>
> # List topics (after init container completes)
> docker exec dropsense-pulsar bin/pulsar-admin topics list public/default
> ```
>
> ### Stop Infrastructure
>
> ```bash
> docker compose down        # stop containers, keep data volumes
> docker compose down -v     # stop containers and delete data volumes
> ```
>
> ### Configuration
>
> The local Aerospike config is at `infra/aerospike.conf`. The topic list is in `infra/init-topics.sh`. These files are only used by Docker Compose and do not affect production.
>
> ## Build & Test
>
> ```bash
> mvn clean install    # build
> mvn test             # run tests
> ```

---

_This file is auto-generated by `build_repo_skills.py` from the live clone. Re-run that script to refresh._
