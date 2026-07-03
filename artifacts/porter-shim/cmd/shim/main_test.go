package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

const goodDigest = "ghcr.io/socioprophet/api@sha256:" + "abc123def456abc123def456abc123def456abc123def456abc123def4560000"

func TestValidateRelease(t *testing.T) {
	cases := []struct {
		name    string
		req     releaseRequest
		wantErr bool
	}{
		{"valid", releaseRequest{Service: "api", Env: "dev", ImageDigest: goodDigest}, false},
		{"unpinned tag", releaseRequest{Service: "api", Env: "dev", ImageDigest: "ghcr.io/x/api:latest"}, true},
		{"missing service", releaseRequest{Env: "dev", ImageDigest: goodDigest}, true},
		{"missing env", releaseRequest{Service: "api", ImageDigest: goodDigest}, true},
		{"bad digest len", releaseRequest{Service: "api", Env: "dev", ImageDigest: "x@sha256:abc"}, true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			errs := validateRelease(tc.req)
			if (len(errs) > 0) != tc.wantErr {
				t.Fatalf("wantErr=%v got errs=%v", tc.wantErr, errs)
			}
		})
	}
}

func post(t *testing.T, mux *http.ServeMux, path, body string, hdr map[string]string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(http.MethodPost, path, strings.NewReader(body))
	for k, v := range hdr {
		req.Header.Set(k, v)
	}
	rr := httptest.NewRecorder()
	mux.ServeHTTP(rr, req)
	return rr
}

func TestReleasePublish_DryRun_AllowUnsigned(t *testing.T) {
	// Local dev posture: unsigned allowed (breakglass), dry-run publisher.
	c := config{requireSigned: true, allowUnsigned: true, shellBase: "http://localhost:8080"}
	mux := newMux(c)

	rr := post(t, mux, "/release/publish",
		`{"service":"api","env":"dev","image_digest":"`+goodDigest+`"}`, nil)
	if rr.Code != http.StatusOK {
		t.Fatalf("want 200 got %d: %s", rr.Code, rr.Body.String())
	}
	var resp struct {
		PrURL    string   `json:"pr_url"`
		Evidence evidence `json:"evidence_bundle"`
	}
	if err := json.Unmarshal(rr.Body.Bytes(), &resp); err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(resp.PrURL, "local://gitops/dev/api@") {
		t.Errorf("unexpected pr_url %q", resp.PrURL)
	}
	if resp.Evidence.Digest != goodDigest || !resp.Evidence.PolicyPass {
		t.Errorf("evidence not populated: %+v", resp.Evidence)
	}
}

func TestReleasePublish_BadDigest_400(t *testing.T) {
	mux := newMux(config{allowUnsigned: true})
	rr := post(t, mux, "/release/publish", `{"service":"api","env":"dev","image_digest":"api:latest"}`, nil)
	if rr.Code != http.StatusBadRequest {
		t.Fatalf("want 400 got %d", rr.Code)
	}
}

func TestReleasePublish_UnsignedRequired_403(t *testing.T) {
	// require_signed and no breakglass; cosign absent → unsigned → blocked.
	mux := newMux(config{requireSigned: true, allowUnsigned: false})
	rr := post(t, mux, "/release/publish", `{"service":"api","env":"prod","image_digest":"`+goodDigest+`"}`, nil)
	if rr.Code != http.StatusForbidden {
		t.Fatalf("want 403 got %d: %s", rr.Code, rr.Body.String())
	}
}

func TestCloudshellLaunch(t *testing.T) {
	mux := newMux(config{shellBase: "http://localhost:8080"})

	// Bad size → 400.
	if rr := post(t, mux, "/cloudshell/launch", `{"size":"xl"}`, nil); rr.Code != http.StatusBadRequest {
		t.Fatalf("bad size want 400 got %d", rr.Code)
	}
	// Identity-correct workspace from the forwarded user.
	rr := post(t, mux, "/cloudshell/launch", `{"repo":"x","size":"m"}`,
		map[string]string{"X-Forwarded-User": "Ada.Lovelace"})
	if rr.Code != http.StatusOK {
		t.Fatalf("want 200 got %d", rr.Code)
	}
	var resp struct {
		ShellURL    string `json:"shell_url"`
		WorkspaceID string `json:"workspace_id"`
	}
	_ = json.Unmarshal(rr.Body.Bytes(), &resp)
	if resp.WorkspaceID != "u-ada-lovelace" {
		t.Errorf("workspace not identity-derived: %q", resp.WorkspaceID)
	}
	if !strings.HasSuffix(resp.ShellURL, "/u/u-ada-lovelace") {
		t.Errorf("shell_url wrong: %q", resp.ShellURL)
	}
}

func TestHealthz(t *testing.T) {
	rr := httptest.NewRecorder()
	newMux(config{}).ServeHTTP(rr, httptest.NewRequest(http.MethodGet, "/healthz", nil))
	if rr.Code != http.StatusOK {
		t.Fatalf("healthz want 200 got %d", rr.Code)
	}
}
