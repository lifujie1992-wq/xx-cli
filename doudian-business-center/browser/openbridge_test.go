package browser

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func newOpenBridgeTestClient(server *httptest.Server) *Client {
	return &Client{
		baseURL: server.URL,
		session: "test-session",
		http: &http.Client{
			Timeout: 2 * time.Second,
		},
	}
}

func decodeOpenBridgeTestRequest(t *testing.T, r *http.Request) (string, map[string]any, map[string]any) {
	t.Helper()
	var body map[string]any
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		t.Fatalf("decode request: %v", err)
	}
	toolName, _ := body["toolName"].(string)
	args, _ := body["args"].(map[string]any)
	return toolName, args, body
}

func writeOpenBridgeTestJSON(t *testing.T, w http.ResponseWriter, status int, value any) {
	t.Helper()
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(value); err != nil {
		t.Fatalf("encode response: %v", err)
	}
}

func TestOpenBridgeEvaluateTranslatesProtocolAndAsyncResult(t *testing.T) {
	var evaluateCalls int
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		toolName, args, body := decodeOpenBridgeTestRequest(t, r)
		if _, exists := body["sessionId"]; exists {
			t.Fatalf("logical session must not be sent as top-level OpenBridge sessionId")
		}
		switch toolName {
		case "browser_find_tab":
			if args["sessionId"] != "test-session" {
				t.Fatalf("find sessionId = %v", args["sessionId"])
			}
			writeOpenBridgeTestJSON(t, w, http.StatusOK, map[string]any{"data": map[string]any{"tabs": []any{map[string]any{"tabId": 7}}, "count": 1}})
		case "browser_select_tab":
			if args["sessionId"] != "test-session" || args["tabId"] != float64(7) {
				t.Fatalf("select args = %#v", args)
			}
			writeOpenBridgeTestJSON(t, w, http.StatusOK, map[string]any{"data": map[string]any{"tabId": 7}})
		case "browser_evaluate":
			evaluateCalls++
			expression, _ := args["expression"].(string)
			if _, exists := args["code"]; exists {
				t.Fatalf("OpenBridge evaluate must use expression, not code")
			}
			if args["sessionId"] != "test-session" {
				t.Fatalf("evaluate sessionId = %v", args["sessionId"])
			}
			if evaluateCalls == 1 {
				if !strings.Contains(expression, "Promise.resolve") {
					t.Fatalf("wrapped expression does not contain original code: %s", expression)
				}
				writeOpenBridgeTestJSON(t, w, http.StatusOK, map[string]any{"data": map[string]any{"result": map[string]any{"state": "pending", "key": "test"}, "type": "object"}})
				return
			}
			writeOpenBridgeTestJSON(t, w, http.StatusOK, map[string]any{"data": map[string]any{"result": map[string]any{"state": "fulfilled", "type": "string", "value": "ok"}, "type": "object"}})
		default:
			t.Fatalf("unexpected tool %q", toolName)
		}
	}))
	defer server.Close()

	raw, err := newOpenBridgeTestClient(server).Call("evaluate", map[string]any{"code": "Promise.resolve('ok')"})
	if err != nil {
		t.Fatalf("Call(evaluate): %v", err)
	}
	var envelope struct {
		Type  string `json:"type"`
		Value string `json:"value"`
	}
	if err := json.Unmarshal(raw, &envelope); err != nil {
		t.Fatalf("decode compatibility envelope: %v", err)
	}
	if envelope.Type != "string" || envelope.Value != "ok" {
		t.Fatalf("envelope = %#v", envelope)
	}
	if evaluateCalls != 2 {
		t.Fatalf("evaluate calls = %d, want 2", evaluateCalls)
	}
}

func TestOpenBridgeFindTabAdoptsMatchingChromeTab(t *testing.T) {
	var calls int
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		toolName, args, _ := decodeOpenBridgeTestRequest(t, r)
		switch calls {
		case 1:
			if toolName != "browser_find_tab" || args["urlContains"] != "example.com" {
				t.Fatalf("find request = %q %#v", toolName, args)
			}
			if _, exists := args["sessionId"]; exists {
				t.Fatalf("find_tab must search unassigned Chrome tabs too: %#v", args)
			}
			writeOpenBridgeTestJSON(t, w, http.StatusOK, map[string]any{"data": map[string]any{"tabs": []any{map[string]any{"tabId": 9}}, "count": 1}})
		case 2:
			if toolName != "browser_select_tab" || args["sessionId"] != "test-session" || args["tabId"] != float64(9) {
				t.Fatalf("select request = %q %#v", toolName, args)
			}
			writeOpenBridgeTestJSON(t, w, http.StatusOK, map[string]any{"data": map[string]any{"tabId": 9}})
		default:
			t.Fatalf("unexpected call %d", calls)
		}
	}))
	defer server.Close()

	if _, err := newOpenBridgeTestClient(server).Call("find_tab", map[string]any{"url": "example.com", "active": false}); err != nil {
		t.Fatalf("Call(find_tab): %v", err)
	}
	if calls != 2 {
		t.Fatalf("calls = %d, want 2", calls)
	}
}

func TestOpenBridgeNavigateCreatesSessionTabWhenMissing(t *testing.T) {
	var calls int
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		toolName, args, _ := decodeOpenBridgeTestRequest(t, r)
		switch calls {
		case 1:
			if toolName != "browser_find_tab" || args["sessionId"] != "test-session" {
				t.Fatalf("session lookup = %q %#v", toolName, args)
			}
			writeOpenBridgeTestJSON(t, w, http.StatusOK, map[string]any{"data": map[string]any{"tabs": []any{}, "count": 0}})
		case 2:
			if toolName != "browser_navigate" || args["newTab"] != true || args["sessionId"] != "test-session" {
				t.Fatalf("navigate request = %q %#v", toolName, args)
			}
			writeOpenBridgeTestJSON(t, w, http.StatusOK, map[string]any{"data": map[string]any{"tabId": 11, "loaded": true}})
		default:
			t.Fatalf("unexpected call %d", calls)
		}
	}))
	defer server.Close()

	if _, err := newOpenBridgeTestClient(server).Call("navigate", map[string]any{"url": "https://example.com", "newTab": false}); err != nil {
		t.Fatalf("Call(navigate): %v", err)
	}
}

func TestOpenBridgeReturnsStructuredCommandError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		toolName, _, _ := decodeOpenBridgeTestRequest(t, r)
		if toolName == "browser_find_tab" {
			writeOpenBridgeTestJSON(t, w, http.StatusBadRequest, map[string]any{"error": map[string]any{"code": "NOT_PAIRED", "message": "No browser extension connected"}})
			return
		}
		t.Fatalf("unexpected tool %q", toolName)
	}))
	defer server.Close()

	_, err := newOpenBridgeTestClient(server).Call("navigate", map[string]any{"url": "https://example.com", "newTab": false})
	if err == nil || !strings.Contains(err.Error(), "NOT_PAIRED") {
		t.Fatalf("error = %v", err)
	}
}
