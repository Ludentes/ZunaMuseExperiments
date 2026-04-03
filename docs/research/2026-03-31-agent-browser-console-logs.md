# Research: Capturing Browser Console Logs from agent-browser CLI

**Date:** 2026-03-31
**Purpose:** Determine how to pipe/capture browser `console.log` output from the agent-browser CLI tool for better automation debugging. Evaluate built-in capabilities, CDP-based approaches, and JavaScript injection workarounds.
**Sources:** 15+ (see bottom)

---

## Executive Summary

**agent-browser does not have a dedicated `console.log` capture command**, but provides three viable paths to get browser console output:

1. **`agent-browser eval` (simplest):** Inject JavaScript that overrides `console.log` to buffer messages into a global array, then periodically retrieve the buffer with another `eval` call. Works today, no extra dependencies.
2. **`agent-browser get cdp-url` + direct CDP WebSocket (most powerful):** Get the CDP WebSocket URL from agent-browser, connect to it with a separate script (Python/Node), enable `Runtime.consoleAPICalled` events, and receive every console message in real time. Full fidelity, but requires a sidecar process.
3. **`agent-browser stream enable` + dashboard (visual only):** The agent-browser dashboard (port 4848) shows live console output, but this is a visual monitoring tool, not a programmatic capture mechanism.

**Recommended approach for automation debugging:** Use Method 1 (eval-based injection) for quick ad-hoc debugging. Use Method 2 (CDP sidecar) when you need comprehensive, real-time log capture in a CI/testing pipeline.

---

## 1. agent-browser Built-in Capabilities

### 1.1 The `eval` Command

The `eval` command executes arbitrary JavaScript in the page context and returns the result:

```bash
# Simple expression — returns the result directly
agent-browser eval 'document.title'

# Complex expression — use --stdin to avoid shell quoting issues
agent-browser eval --stdin <<'EVALEOF'
JSON.stringify(
  Array.from(document.querySelectorAll("img"))
    .filter(i => !i.alt)
    .map(i => ({ src: i.src.split("/").pop(), width: i.width }))
)
EVALEOF

# Base64 encoding for complex JS
agent-browser eval -b "$(echo -n 'your code here' | base64)"
```

**Key limitation:** `eval` returns the *expression result*, not console output. If your code does `console.log("hello")`, the `eval` result is `undefined`, not `"hello"`.

### 1.2 Getting the CDP URL

```bash
agent-browser get cdp-url
# Returns: ws://127.0.0.1:<port>/devtools/browser/<guid>
```

This gives you the WebSocket endpoint for raw CDP access — the foundation of Method 2.

### 1.3 Streaming and Dashboard

```bash
agent-browser stream enable                  # Start WebSocket stream (auto port)
agent-browser stream enable --port 9223      # Specific port
agent-browser stream status                  # Check state
agent-browser stream disable                 # Stop
```

The dashboard (port 4848) provides live browser viewport, command activity, and console output for all sessions. Useful for visual debugging but not programmatic capture.

### 1.4 Other Useful Debugging Commands

```bash
agent-browser inspect                        # Open Chrome DevTools
agent-browser screenshot --annotate          # Annotated screenshot with element refs
agent-browser network requests               # Inspect tracked network requests
agent-browser profiler start                 # Start performance profiling
agent-browser profiler stop trace.json       # Stop and save trace
```

---

## 2. Method 1: Console Capture via `eval` Injection

The simplest approach — inject a console override into the page, then poll it.

### Step 1: Inject the Override

```bash
agent-browser eval --stdin <<'EVALEOF'
(function() {
  if (window.__consoleLogs) return 'already installed';
  window.__consoleLogs = [];
  const orig = {
    log: console.log.bind(console),
    warn: console.warn.bind(console),
    error: console.error.bind(console),
    info: console.info.bind(console)
  };
  ['log', 'warn', 'error', 'info'].forEach(level => {
    console[level] = function(...args) {
      window.__consoleLogs.push({
        level,
        ts: Date.now(),
        msg: args.map(a => {
          try { return JSON.stringify(a); }
          catch { return String(a); }
        }).join(' ')
      });
      orig[level](...args);
    };
  });
  return 'console capture installed';
})()
EVALEOF
```

### Step 2: Retrieve Captured Logs

```bash
agent-browser eval 'JSON.stringify(window.__consoleLogs.splice(0))'
```

The `splice(0)` drains the buffer, so subsequent calls only return new messages.

### Step 3: Automate in a Shell Loop

```bash
# Poll every 2 seconds and append to a log file
while true; do
  logs=$(agent-browser eval 'JSON.stringify(window.__consoleLogs.splice(0))' 2>/dev/null)
  if [ "$logs" != "[]" ] && [ -n "$logs" ]; then
    echo "$logs" >> /tmp/browser-console.log
  fi
  sleep 2
done
```

### Pros and Cons

| Pros | Cons |
|------|------|
| No extra dependencies | Polling-based, not real-time |
| Works with agent-browser as-is | Lost on page navigation (must re-inject) |
| Simple shell scripting | Misses early logs before injection |
| Can filter by log level | Serialization may lose complex objects |

---

## 3. Method 2: Direct CDP Console Capture

Connect directly to the browser's CDP WebSocket and subscribe to `Runtime.consoleAPICalled` events for real-time, full-fidelity console capture.

### 3.1 CDP Console Events

Two CDP domains provide console access:

| Domain / Event | What It Captures |
|---|---|
| `Runtime.consoleAPICalled` | All `console.*` calls (log, warn, error, info, debug, table, etc.) |
| `Log.entryAdded` | Browser-level log entries (network errors, security warnings, etc.) |

`Runtime.consoleAPICalled` is the one you want for application-level `console.log` output.

### 3.2 Python Sidecar Script

```python
#!/usr/bin/env python3
"""CDP console log capture sidecar for agent-browser."""
import asyncio
import json
import subprocess
import websockets

async def capture_console():
    # Get CDP URL from agent-browser
    result = subprocess.run(
        ["agent-browser", "get", "cdp-url"],
        capture_output=True, text=True
    )
    cdp_url = result.stdout.strip()
    print(f"Connecting to {cdp_url}")

    async with websockets.connect(cdp_url) as ws:
        msg_id = 0

        async def send_cdp(method, params=None):
            nonlocal msg_id
            msg_id += 1
            await ws.send(json.dumps({
                "id": msg_id,
                "method": method,
                "params": params or {}
            }))

        # Enable Runtime domain to receive consoleAPICalled events
        await send_cdp("Runtime.enable")
        # Also enable Log domain for browser-level logs
        await send_cdp("Log.enable")

        print("Listening for console messages...")
        async for message in ws:
            data = json.loads(message)

            # Skip command responses (they have an "id" field)
            if "id" in data:
                continue

            method = data.get("method", "")

            if method == "Runtime.consoleAPICalled":
                params = data["params"]
                log_type = params["type"]       # "log", "warn", "error", etc.
                args = params.get("args", [])
                text_parts = []
                for arg in args:
                    if "value" in arg:
                        text_parts.append(str(arg["value"]))
                    elif "description" in arg:
                        text_parts.append(arg["description"])
                    else:
                        text_parts.append(arg.get("type", "?"))
                print(f"[{log_type}] {' '.join(text_parts)}")

            elif method == "Log.entryAdded":
                entry = data["params"]["entry"]
                print(f"[browser:{entry['level']}] {entry['text']}")

if __name__ == "__main__":
    asyncio.run(capture_console())
```

### 3.3 Node.js Sidecar Script

```javascript
const { execSync } = require('child_process');
const WebSocket = require('ws');

const cdpUrl = execSync('agent-browser get cdp-url').toString().trim();
const ws = new WebSocket(cdpUrl);
let msgId = 0;

ws.on('open', () => {
  ws.send(JSON.stringify({ id: ++msgId, method: 'Runtime.enable' }));
  ws.send(JSON.stringify({ id: ++msgId, method: 'Log.enable' }));
  console.log('Listening for console messages...');
});

ws.on('message', (raw) => {
  const data = JSON.parse(raw);
  if (data.id) return; // skip responses

  if (data.method === 'Runtime.consoleAPICalled') {
    const { type, args } = data.params;
    const text = args.map(a => a.value ?? a.description ?? a.type).join(' ');
    console.log(`[${type}] ${text}`);
  }

  if (data.method === 'Log.entryAdded') {
    const { level, text } = data.params.entry;
    console.log(`[browser:${level}] ${text}`);
  }
});
```

### 3.4 Playwright CDPSession (Alternative)

If you already use Playwright in your stack, you can attach a CDPSession to capture logs without raw WebSocket handling:

```typescript
// Attach CDP session to a page
const client = await page.context().newCDPSession(page);

// Enable console event domain
await client.send('Runtime.enable');

// Listen for console calls
client.on('Runtime.consoleAPICalled', (event) => {
  const { type, args } = event;
  const text = args.map(a => a.value ?? a.description ?? a.type).join(' ');
  console.log(`[${type}] ${text}`);
});
```

For worker contexts (Service Workers, Shared Workers), you need the more complex `Target.attachToTarget` approach with a nested session — see the `playwright-worker-console-logs` repo for a full example.

### Pros and Cons

| Pros | Cons |
|------|------|
| Real-time, zero latency | Requires a sidecar process |
| Captures ALL console messages | More complex setup |
| Survives page navigation | CDP URL may change between sessions |
| Full object serialization possible | Needs `websockets` (Python) or `ws` (Node) |
| Also captures browser-level logs | |

---

## 4. Method 3: Connect to Existing Chrome via CDP

If you use `agent-browser --cdp 9222` to connect to an already-running Chrome instance, you can also connect your sidecar to the same Chrome:

```bash
# Start Chrome with remote debugging
google-chrome --remote-debugging-port=9222

# Agent-browser connects to it
agent-browser --cdp 9222 open https://example.com

# Your sidecar also connects (get page-level WS URL)
curl -s http://localhost:9222/json | python3 -c "
import json, sys
targets = json.load(sys.stdin)
for t in targets:
    if t['type'] == 'page':
        print(t['webSocketDebuggerUrl'])
        break
"
```

Then use the page-level WebSocket URL with the Python/Node sidecar scripts from Method 2.

---

## 5. Comparison Matrix

| Criteria | eval Injection | CDP Sidecar | Dashboard |
|----------|---------------|-------------|-----------|
| **Setup complexity** | Low | Medium | Low |
| **Real-time** | No (polling) | Yes | Yes (visual) |
| **Programmatic output** | Yes (JSON) | Yes (JSON) | No |
| **Survives navigation** | No (re-inject) | Yes | Yes |
| **Captures early logs** | No | Yes | Yes |
| **Extra dependencies** | None | websockets/ws | None |
| **CI/pipeline friendly** | Partial | Yes | No |

---

## 6. Practical Recommendations

### For Quick Debugging During Development

Use **eval injection** (Method 1). Install the override once at the start of your automation flow, retrieve logs when something fails:

```bash
# After a failed step, grab the console buffer
agent-browser eval 'JSON.stringify(window.__consoleLogs || [])'
```

### For CI/Test Pipelines

Use the **CDP sidecar** (Method 2). Start it as a background process before the test run, pipe output to a file, and include it in test artifacts:

```bash
python3 cdp_console_capture.py > /tmp/console.log 2>&1 &
CDP_PID=$!

# ... run your agent-browser automation ...

kill $CDP_PID
cat /tmp/console.log
```

### For Interactive Monitoring

Use `agent-browser inspect` to open Chrome DevTools, or the agent-browser dashboard on port 4848.

---

## Sources

### agent-browser Documentation
- [agent-browser GitHub repo (Vercel Labs)](https://github.com/vercel-labs/agent-browser)
- [agent-browser SKILL.md](https://github.com/vercel-labs/agent-browser/blob/main/skills/agent-browser/SKILL.md)
- [agent-browser CDP Mode](https://agent-browser.dev/cdp-mode)
- [agent-browser official site](https://agent-browser.dev/)
- [Complete Guide to agent-browser (Apiyi)](https://help.apiyi.com/en/agent-browser-ai-browser-automation-cli-guide-en.html)
- [Browser Automation CLI for AI Agents (Medium)](https://medium.com/@bytefer/browser-automation-cli-designed-for-ai-agents-has-arrived-0b8181613669)

### Chrome DevTools Protocol
- [Chrome DevTools Protocol spec](https://chromedevtools.github.io/devtools-protocol/)
- [Getting Started with CDP](https://github.com/aslushnikov/getting-started-with-cdp)
- [CDP — The Hidden Hero Behind browser-use](https://supercodepower.com/en/chrome-devtools-protocol/)
- [PyCDP Runtime documentation](https://py-cdp.readthedocs.io/en/latest/api/runtime.html)

### Playwright CDP Sessions
- [Playwright CDPSession API](https://playwright.dev/docs/api/class-cdpsession)
- [Playwright Worker Console Logs example](https://github.com/mxschmitt/playwright-worker-console-logs)
- [Supercharging Playwright with CDP (The Green Report)](https://www.thegreenreport.blog/articles/supercharging-playwright-tests-with-chrome-devtools-protocol/supercharging-playwright-tests-with-chrome-devtools-protocol.html)

### Puppeteer Console Capture
- [Puppeteer Debugging Guide](https://pptr.dev/guides/debugging)
- [Puppeteer page.on console (Adam Cameron)](https://blog.adamcameron.me/2021/01/listening-to-console-log-of-page-loaded.html)
- [Logs and Debugging for Playwright and Puppeteer (Browserless)](https://www.browserless.io/blog/logs-and-debugging-for-playwright-and-puppeteer)

### Console Override Techniques
- [Taking Over console.log (Toby Ho)](https://tobyho.com/2012/07/27/taking-over-console-log/)
- [Capturing Browser Console Logs (CyberAngles)](https://www.cyberangles.org/blog/capturing-javascript-console-log/)
