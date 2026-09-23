# MindLoop EvoMap Bridge

Minimal FastAPI integration for the EvoMap hackathon API.

## 1. Register a test-mode app

Open <https://evomap.ai/dev/portal> and create an app with:

- Redirect URI: `http://localhost:8000/oauth/callback`
- Test mode: enabled
- Scopes: `recipe:read gene:read reuse:query recipe:write recipe:publish`

## 2. Configure

```bash
cd backend
cp .env.example .env
```

Fill `EVOMAP_CLIENT_ID` and `EVOMAP_CLIENT_SECRET`. Never commit `.env`.

If you already have a short-lived access token, set `EVOMAP_TOKEN` and skip OAuth.

## 3. Run

Requires Python 3.11 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Visit the pendant simulator at <http://localhost:8000/> or use the interactive
API at <http://localhost:8000/docs>. OAuth setup starts at
<http://localhost:8000/oauth/start>.

## 4. Verify recipe search

```bash
curl -G 'http://localhost:8000/api/evomap/recipes/search' \
  --data-urlencode 'q=task initiation' \
  --data-urlencode 'limit=5'
```

## Privacy boundary for MindLoop

Only send abstract, non-medical context to EvoMap, for example:

`task initiation + unclear first step + creative writing`

Do not send names, diagnoses, raw speech, physiological signals, exact tasks, locations, or timestamps.

## Publishing safety

Draft creation is available at `POST /api/evomap/recipes/draft`.

Test publishing is disabled by default. It requires:

```bash
EVOMAP_ALLOW_TEST_PUBLISH=true
```

and an `evm_client_test_...` credential. Live-mode publishing is intentionally blocked by this bridge.

## MindLoop demo loop

Put the ID of your approved test Recipe in `.env` and restart Uvicorn:

```bash
EVOMAP_RECIPE_ID=recipe_test_your_id
```

Start a session:

```bash
curl -X POST 'http://localhost:8000/api/mindloop/start' \
  -H 'Content-Type: application/json' \
  -d '{"task":"我要开始写路演方案，但不知道从哪里开始"}'
```

Copy the returned `session_id`, then send wearable feedback:

```bash
curl -X POST 'http://localhost:8000/api/mindloop/feedback' \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"session_replace_me","result":"stuck"}'
```

Use `done` to advance to the next stored step without another model call. A
`stuck` response immediately inserts a smaller local step while preserving the
original current and remaining steps; AI refinement then runs in the background. The
returned `wearable_command` can be sent over USB serial/BLE. Anonymous metrics
are available at `GET /api/mindloop/metrics`; recent events are at
`GET /api/mindloop/events`. Raw task text is never stored.

The task is complete only after the final stored step is marked `done`.

The frontend polls `GET /api/mindloop/session/{session_id}` after Stuck and
applies a background AI refinement only if the user has not already moved on.

## AI-generated task plans

The model gateway is separate from the Recipe OAuth credentials. Configure it
only in the local `.env` file:

```bash
AI_BASE_URL=https://api.evomap.ai/v1
AI_API_KEY=sk-evomap-your-key
AI_MODEL=evomap-deepseek-v4-flash
AI_TIMEOUT_SECONDS=40
AI_MAX_RETRIES=1
AI_FALLBACK_ENABLED=true
```

`POST /api/mindloop/start` asks the model for a complete ordered plan and shows
only its first step. A `stuck` response asks for a smaller current step and an
updated remaining plan while preserving all completed steps.
Invalid JSON, timeouts, and gateway errors fall back to deterministic rules.
The response field `step_source` is `ai` when the model was used and
`rules_fallback` when the fallback handled the request.

Transient timeouts, network failures, HTTP 429/5xx responses, and invalid JSON
are retried once. Validation failures trigger one plan-repair request. Failure
logs contain only the error category and model name, never the API key.

## Anonymous personalization memory

MindLoop does not store chat history or raw task text. It learns from compact
behavioral evidence grouped by task type: Done/Stuck counts, time to action,
preferred step duration, inferred tool preference, frequent stuck position,
re-plan count, and recent effective or ineffective actions. This
profile is injected into the next AI request so repeated Stuck feedback leads
to smaller, lower-decision actions. Inspect it with:

```text
GET /api/mindloop/memory?task_type=writing
```

This URL intentionally returns raw JSON for debugging. It is not the product
UI; open `/` for the pendant experience.

## Tests

```bash
python -m unittest test_mindloop.py test_atomic_step_agent.py
python -m pytest test_client.py -q
```

The retained early modular prototype lives under `app/` with its own tests
under `tests/`. The current EvoMap + AI demo entry point is `main.py`.
