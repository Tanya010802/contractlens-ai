# ContractLens AI

ContractLens compares an old and a new OpenAPI specification and shows where a change may affect existing API clients. Each finding links back to the relevant location in both JSON documents. The dashboard can also ask a configured model to propose test ideas for one verified finding.

## Run locally

Use Python 3.12+ and Node.js 22+. From the project root:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
npm --prefix frontend ci
npm --prefix frontend run build
python -m uvicorn contractlens.api:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>, click **Load sample**, then **Compare specifications**. The sample shows **POST /users** adding a required `phoneNumber` field. Use **View spec evidence** to inspect the corresponding JSON Pointers or **Download JSON** to save the report. Interactive API documentation is at <http://127.0.0.1:8000/docs>.

The CLI needs only Python's standard library:

```sh
python -m contractlens examples/before.json examples/after.json
python -m contractlens examples/before.json examples/after.json --fail-on-high
```

The CLI returns 0 after generating a report, 1 when `--fail-on-high` finds a high-priority result, and 2 for invalid input.

## Optional AI test ideas

Set `OPENAI_API_KEY` and `OPENAI_MODEL` in the server environment before starting Uvicorn. Use a model with Structured Outputs support. The server sends only the selected finding’s rule, operation, location, fields, and impact to the OpenAI Responses API, and validates the structured response. Generating a suggestion does not execute the proposed tests. Keep the AI endpoint local or put it behind authentication and rate limits before exposing it publicly.

## Checks

```sh
python -m unittest discover -s tests -v
npm --prefix frontend run build
```

GitHub Actions runs those checks and the example CLI on pushes and pull requests. To try the Docker build:

```sh
docker build -t contractlens-ai .
docker run --rm -p 127.0.0.1:8000:8000 contractlens-ai
```

## Comparison scope

The engine handles OpenAPI 3.0 and 3.1 JSON. It detects removed operations, newly required request fields, removed declared response fields, and selected incompatible explicit type changes. It walks nested properties and array items for request and response schemas and resolves same-document JSON Pointer references. Evidence values summarize what the comparison observed at each pointer. For removed or absent definitions the pointer refers to the nearest inspected container.

The report covers selected compatibility rules. It does not validate OpenAPI documents exhaustively, resolve external references, evaluate schema composition, or test a running API. Warnings identify skipped reference and schema branches. A report with zero findings is limited to the rules and schema branches this version checks.
