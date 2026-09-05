package browser

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"sync/atomic"
	"time"
)

const openBridgeURLEnv = "OPENBRIDGE_URL"

var openBridgeEvaluateSequence atomic.Uint64

type openBridgeError struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

type openBridgeResponse struct {
	Data  json.RawMessage  `json:"data"`
	Error *openBridgeError `json:"error"`
}

type openBridgeHealth struct {
	OK                bool     `json:"ok"`
	Port              int      `json:"port"`
	ConnectedSessions []string `json:"connectedSessions"`
	Paused            bool     `json:"paused"`
	EnabledTools      []string `json:"enabledTools"`
}

type openBridgeEvaluateResult struct {
	Result json.RawMessage `json:"result"`
	Type   string          `json:"type"`
}

type openBridgeEvaluateState struct {
	State   string          `json:"state"`
	Key     string          `json:"key"`
	Type    string          `json:"type"`
	Value   json.RawMessage `json:"value"`
	Message string          `json:"message"`
}

func openBridgeURL() string {
	if value := strings.TrimSpace(os.Getenv(openBridgeURLEnv)); value != "" {
		return strings.TrimRight(value, "/")
	}
	return DefaultDaemonURL
}

func cloneArgs(args map[string]any) map[string]any {
	cloned := make(map[string]any, len(args)+1)
	for key, value := range args {
		cloned[key] = value
	}
	return cloned
}

func (c *Client) callOpenBridge(action string, args map[string]any) (json.RawMessage, error) {
	mapped := cloneArgs(args)
	if c.session != "" {
		mapped["sessionId"] = c.session
	}

	switch action {
	case "evaluate":
		if c.session != "" {
			found, err := c.selectOpenBridgeSessionTab(context.Background())
			if err != nil {
				return nil, err
			}
			if !found {
				return nil, fmt.Errorf("TAB_NOT_FOUND: no OpenBridge tab is assigned to session %q", c.session)
			}
		}
		expression, ok := mapped["code"].(string)
		if !ok {
			return nil, fmt.Errorf("OpenBridge browser_evaluate requires a string code argument")
		}
		delete(mapped, "code")
		return c.evaluateOpenBridge(expression, mapped)
	case "find_tab":
		// Search all Chrome tabs first. OpenBridge's args.sessionId filters to
		// already-managed tabs, while the legacy find_tab could adopt an existing tab.
		delete(mapped, "sessionId")
		if url, ok := mapped["url"].(string); ok {
			mapped["urlContains"] = url
			delete(mapped, "url")
		}
		activate, _ := mapped["active"].(bool)
		delete(mapped, "active")
		mapped["activate"] = false

		data, err := c.doOpenBridgeCommand(context.Background(), "browser_find_tab", mapped)
		if err != nil {
			return nil, err
		}

		var result struct {
			Tabs []struct {
				TabID int `json:"tabId"`
			} `json:"tabs"`
		}
		if err := json.Unmarshal(data, &result); err != nil {
			return nil, fmt.Errorf("decode OpenBridge browser_find_tab response: %w", err)
		}
		if len(result.Tabs) == 0 {
			return nil, fmt.Errorf("TAB_NOT_FOUND: OpenBridge found no tab matching the requested URL")
		}
		selectArgs := map[string]any{"tabId": result.Tabs[0].TabID}
		if c.session != "" {
			selectArgs["sessionId"] = c.session
		}
		if _, err := c.doOpenBridgeCommand(context.Background(), "browser_select_tab", selectArgs); err != nil {
			return nil, err
		}
		_ = activate // OpenBridge must activate a tab in order to attach its debugger.
		return data, nil
	default:
		if action == "navigate" {
			newTab, _ := mapped["newTab"].(bool)
			if !newTab && c.session != "" {
				found, err := c.selectOpenBridgeSessionTab(context.Background())
				if err != nil {
					return nil, err
				}
				if !found {
					mapped["newTab"] = true
				}
			}
		} else if c.session != "" {
			found, err := c.selectOpenBridgeSessionTab(context.Background())
			if err != nil {
				return nil, err
			}
			if !found {
				return nil, fmt.Errorf("TAB_NOT_FOUND: no OpenBridge tab is assigned to session %q", c.session)
			}
		}

		toolName := action
		if !strings.HasPrefix(toolName, "browser_") {
			toolName = "browser_" + toolName
		}
		return c.doOpenBridgeCommand(context.Background(), toolName, mapped)
	}
}

func (c *Client) selectOpenBridgeSessionTab(ctx context.Context) (bool, error) {
	data, err := c.doOpenBridgeCommand(ctx, "browser_find_tab", map[string]any{
		"sessionId": c.session,
		"activate":  false,
	})
	if err != nil {
		return false, err
	}
	var result struct {
		Tabs []struct {
			TabID int `json:"tabId"`
		} `json:"tabs"`
	}
	if err := json.Unmarshal(data, &result); err != nil {
		return false, fmt.Errorf("decode OpenBridge session tab response: %w", err)
	}
	if len(result.Tabs) == 0 {
		return false, nil
	}
	_, err = c.doOpenBridgeCommand(ctx, "browser_select_tab", map[string]any{
		"tabId":     result.Tabs[0].TabID,
		"sessionId": c.session,
	})
	if err != nil {
		return false, err
	}
	return true, nil
}

func (c *Client) doOpenBridgeCommand(ctx context.Context, toolName string, args map[string]any) (json.RawMessage, error) {
	body, err := json.Marshal(map[string]any{
		"toolName": toolName,
		"args":     args,
	})
	if err != nil {
		return nil, fmt.Errorf("encode OpenBridge command: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/command", bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("create OpenBridge request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("OpenBridge daemon unreachable at %s: %w", c.baseURL, err)
	}
	defer resp.Body.Close()

	responseBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read OpenBridge response: %w", err)
	}
	var result openBridgeResponse
	if err := json.Unmarshal(responseBody, &result); err != nil {
		return nil, fmt.Errorf("decode OpenBridge response (HTTP %d): %w (body=%s)", resp.StatusCode, err, string(responseBody))
	}
	if result.Error != nil {
		return nil, fmt.Errorf("%s: %s", result.Error.Code, result.Error.Message)
	}
	if resp.StatusCode < http.StatusOK || resp.StatusCode >= http.StatusMultipleChoices {
		return nil, fmt.Errorf("OpenBridge returned HTTP %d without error detail (body=%s)", resp.StatusCode, string(responseBody))
	}
	if len(result.Data) == 0 {
		return json.RawMessage("null"), nil
	}
	return result.Data, nil
}

func (c *Client) openBridgeHealth() (*openBridgeHealth, error) {
	resp, err := c.http.Get(c.baseURL + "/health")
	if err != nil {
		return nil, fmt.Errorf("OpenBridge daemon unreachable at %s: %w", c.baseURL, err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read OpenBridge health response: %w", err)
	}
	var health openBridgeHealth
	if err := json.Unmarshal(body, &health); err != nil {
		return nil, fmt.Errorf("parse OpenBridge health: %w (body=%s)", err, string(body))
	}
	if resp.StatusCode < http.StatusOK || resp.StatusCode >= http.StatusMultipleChoices {
		return nil, fmt.Errorf("OpenBridge health returned HTTP %d (body=%s)", resp.StatusCode, string(body))
	}
	return &health, nil
}

func (c *Client) evaluateOpenBridge(expression string, args map[string]any) (json.RawMessage, error) {
	timeout := c.http.Timeout
	if timeout <= 0 {
		timeout = 90 * time.Second
	}
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()

	sequence := openBridgeEvaluateSequence.Add(1)
	key := fmt.Sprintf("__xcli_openbridge_%d_%d", time.Now().UnixNano(), sequence)
	expressionJSON, _ := json.Marshal(expression)
	keyJSON, _ := json.Marshal(key)
	wrapped := fmt.Sprintf(`(() => {
  const __key = %s;
  const __pack = value => ({state: "fulfilled", type: value === null ? "object" : typeof value, value: value === undefined ? null : value});
  try {
    const __value = (0, eval)(%s);
    if (__value && typeof __value.then === "function") {
      globalThis[__key] = {state: "pending", key: __key};
      Promise.resolve(__value).then(
        value => { globalThis[__key] = __pack(value); },
        error => { globalThis[__key] = {state: "rejected", message: String(error && (error.stack || error.message) || error)}; }
      );
      return globalThis[__key];
    }
    return __pack(__value);
  } catch (error) {
    return {state: "rejected", message: String(error && (error.stack || error.message) || error)};
  }
})()`, string(keyJSON), string(expressionJSON))

	mapped := cloneArgs(args)
	mapped["expression"] = wrapped
	state, err := c.runOpenBridgeEvaluate(ctx, mapped)
	if err != nil {
		return nil, err
	}

	for state.State == "pending" {
		select {
		case <-ctx.Done():
			return nil, fmt.Errorf("OpenBridge browser_evaluate timed out waiting for async JavaScript: %w", ctx.Err())
		case <-time.After(50 * time.Millisecond):
		}

		pollExpression := fmt.Sprintf(`(() => {
  const __key = %s;
  const __value = globalThis[__key];
  if (!__value) return {state: "rejected", message: "async evaluation state was lost"};
  if (__value.state !== "pending") delete globalThis[__key];
  return __value;
})()`, string(keyJSON))
		pollArgs := cloneArgs(args)
		pollArgs["expression"] = pollExpression
		state, err = c.runOpenBridgeEvaluate(ctx, pollArgs)
		if err != nil {
			return nil, err
		}
	}

	if state.State == "rejected" {
		return nil, fmt.Errorf("OpenBridge JavaScript evaluation failed: %s", state.Message)
	}
	if state.State != "fulfilled" {
		return nil, fmt.Errorf("OpenBridge returned unknown evaluate state %q", state.State)
	}

	var value any
	if len(state.Value) > 0 && string(state.Value) != "null" {
		if err := json.Unmarshal(state.Value, &value); err != nil {
			return nil, fmt.Errorf("decode OpenBridge evaluate value: %w", err)
		}
	}
	return json.Marshal(map[string]any{
		"type":  state.Type,
		"value": value,
	})
}

func (c *Client) runOpenBridgeEvaluate(ctx context.Context, args map[string]any) (*openBridgeEvaluateState, error) {
	data, err := c.doOpenBridgeCommand(ctx, "browser_evaluate", args)
	if err != nil {
		return nil, err
	}
	var result openBridgeEvaluateResult
	if err := json.Unmarshal(data, &result); err != nil {
		return nil, fmt.Errorf("decode OpenBridge browser_evaluate response: %w", err)
	}
	var state openBridgeEvaluateState
	if err := json.Unmarshal(result.Result, &state); err != nil {
		return nil, fmt.Errorf("decode OpenBridge evaluate compatibility envelope: %w (result=%s)", err, string(result.Result))
	}
	return &state, nil
}
