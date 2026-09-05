# OpenBridge Site Exploration Protocol

Run this protocol for every planned feature before implementation. The examples assume `OPENBRIDGE_URL=http://127.0.0.1:10088` and session `example-cli`.

```bash
export OPENBRIDGE_URL=${OPENBRIDGE_URL:-http://127.0.0.1:10088}
export OPENBRIDGE_SESSION=example-cli
```

OpenBridge requests use `{"toolName":"browser_*","args":{...}}`. The xx-cli logical session belongs in `args.sessionId`; do not put it in the request's top level.

## 1. Navigate using a managed tab

```bash
curl -sS -X POST "$OPENBRIDGE_URL/command" \
  -H 'Content-Type: application/json' \
  -d '{"toolName":"browser_navigate","args":{"url":"<TARGET_URL>","newTab":true,"sessionId":"example-cli","groupTitle":"example-cli"}}'
```

The generated CLI adapter can later reuse this logical session. If it needs to adopt an already-open login tab, it first calls `browser_find_tab` with `urlContains`, then `browser_select_tab` with the returned `tabId` and its `sessionId`.

## 2. Snapshot and inspect the DOM

```bash
curl -sS -X POST "$OPENBRIDGE_URL/command" \
  -H 'Content-Type: application/json' \
  -d '{"toolName":"browser_snapshot","args":{"sessionId":"example-cli"}}'
```

Inspect the returned accessibility tree and refs. Prefer stable roles, accessible names, `data-*` attributes, and URL patterns over generated CSS classes.

For a synchronous DOM probe:

```bash
curl -sS -X POST "$OPENBRIDGE_URL/command" \
  -H 'Content-Type: application/json' \
  -d '{"toolName":"browser_evaluate","args":{"sessionId":"example-cli","expression":"JSON.stringify({title:document.title,url:location.href})"}}'
```

`browser_evaluate` is disabled by default in some OpenBridge setups; enable it in the extension popup.

## 3. Capture network activity

Start capture:

```bash
curl -sS -X POST "$OPENBRIDGE_URL/command" \
  -H 'Content-Type: application/json' \
  -d '{"toolName":"browser_network","args":{"action":"start","sessionId":"example-cli"}}'
```

Trigger the feature manually in Chrome, then stop and read recent events:

```bash
curl -sS -X POST "$OPENBRIDGE_URL/command" \
  -H 'Content-Type: application/json' \
  -d '{"toolName":"browser_network","args":{"action":"stop","sessionId":"example-cli"}}'

curl -sS -X POST "$OPENBRIDGE_URL/command" \
  -H 'Content-Type: application/json' \
  -d '{"toolName":"browser_network","args":{"action":"get","limit":200,"sessionId":"example-cli"}}'
```

Record the endpoint, method, query/body, required headers, and response shape. Clear between experiments with `action:"clear"`.

## 4. Prove the authenticated request in page context

Prefer page-side `fetch`, because it reuses the real tab's cookies, origin, CSRF state, and site-generated headers.

OpenBridge's raw `browser_evaluate` does not reliably await a returned Promise. For direct archaeology, start an async probe and poll a global result:

```bash
curl -sS -X POST "$OPENBRIDGE_URL/command" \
  -H 'Content-Type: application/json' \
  -d '{"toolName":"browser_evaluate","args":{"sessionId":"example-cli","expression":"(()=>{globalThis.__xcliProbe={state:\"pending\"};fetch(\"<API_URL>\",{credentials:\"include\"}).then(async r=>({status:r.status,body:await r.text()})).then(value=>globalThis.__xcliProbe={state:\"fulfilled\",value}).catch(error=>globalThis.__xcliProbe={state:\"rejected\",message:String(error)});return globalThis.__xcliProbe})()"}}'

curl -sS -X POST "$OPENBRIDGE_URL/command" \
  -H 'Content-Type: application/json' \
  -d '{"toolName":"browser_evaluate","args":{"sessionId":"example-cli","expression":"globalThis.__xcliProbe"}}'
```

The repository's Go and Python compatibility clients perform this start/poll sequence automatically, so business code can continue to pass async IIFEs.

## 5. Record archaeology evidence

For each command, save:

- target page and same-origin requirements;
- login and CAPTCHA behavior;
- verified endpoint or DOM operation;
- exact input/output samples with secrets removed;
- pagination, rate-limit, and destructive-action risks;
- the final expression that worked through OpenBridge.

Only then implement the CLI command.
