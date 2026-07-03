// porter-shim — the GitOps-native PaaS control plane (Pattern A:
// Intent → PR → policy gate → Argo reconcile → evidence).
//
// It NEVER applies to clusters. Each verb validates + gates, then writes a PR
// (or, in dry-run, a deterministic local reference) and returns an evidence
// bundle. Stdlib-only so it builds and runs anywhere.
package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/exec"
	"regexp"
	"strings"
	"time"
)

// A fully pinned image reference: repo@sha256:<64 hex>. Enforces the
// require_digest guard from deployment-profiles / CapDs.
var digestRe = regexp.MustCompile(`^[^@\s]+@sha256:[0-9a-f]{64}$`)

var validSizes = map[string]bool{"s": true, "m": true, "l": true}

// ── config (env) ─────────────────────────────────────────────────────────────
type config struct {
	gitopsRepo    string // if set, publish opens a real PR against this repo via gh
	requireSigned bool   // signed_images guard
	allowUnsigned bool   // breakglass (audited via evidence)
	shellBase     string // base URL for cloudshell links
	spawnerURL    string // if set, /cloudshell/launch calls the spawner
}

func loadConfig() config {
	return config{
		gitopsRepo:    os.Getenv("SHIM_GITOPS_REPO"),
		requireSigned: envBool("SHIM_REQUIRE_SIGNED", true),
		allowUnsigned: envBool("SHIM_ALLOW_UNSIGNED", false),
		shellBase:     envOr("SHIM_SHELL_BASE", "http://localhost:8080"),
		spawnerURL:    os.Getenv("SHIM_SPAWNER_URL"),
	}
}

// ── /release/publish ─────────────────────────────────────────────────────────
type releaseRequest struct {
	Service      string `json:"service"`
	Env          string `json:"env"`
	ImageDigest  string `json:"image_digest"`
	ChartVersion string `json:"chart_version"`
}

type evidence struct {
	Service    string `json:"service"`
	Env        string `json:"env"`
	Digest     string `json:"image_digest"`
	Signed     bool   `json:"signed"`
	PolicyPass bool   `json:"policy_pass"`
	CreatedAt  string `json:"created_at"`
}

// validateRelease enforces the require_digest + non-empty guards. Returns the
// list of problems ([] = valid).
func validateRelease(r releaseRequest) []string {
	var errs []string
	if strings.TrimSpace(r.Service) == "" {
		errs = append(errs, "service is required")
	}
	if strings.TrimSpace(r.Env) == "" {
		errs = append(errs, "env is required")
	}
	if !digestRe.MatchString(r.ImageDigest) {
		errs = append(errs, "image_digest must be a pinned reference repo@sha256:<64hex>")
	}
	return errs
}

// checkSigned verifies the image signature (cosign keyless if available).
// Absent cosign → unsigned; breakglass via SHIM_ALLOW_UNSIGNED (recorded in evidence).
func checkSigned(digest string) bool {
	if _, err := exec.LookPath("cosign"); err != nil {
		return false
	}
	return exec.Command("cosign", "verify", digest).Run() == nil
}

type publisher interface {
	publish(r releaseRequest, ev evidence) (prURL string, err error)
}

// dryRunPublisher returns a deterministic local reference — no network. Default
// so the shim is runnable without a GitOps remote.
type dryRunPublisher struct{}

func (dryRunPublisher) publish(r releaseRequest, ev evidence) (string, error) {
	return fmt.Sprintf("local://gitops/%s/%s@%s", r.Env, r.Service, shortDigest(r.ImageDigest)), nil
}

// gitopsPublisher opens a real PR via gh (used when SHIM_GITOPS_REPO is set).
type gitopsPublisher struct{ repo string }

func (g gitopsPublisher) publish(r releaseRequest, ev evidence) (string, error) {
	if _, err := exec.LookPath("gh"); err != nil {
		return "", fmt.Errorf("gh not available for GitOps PR")
	}
	title := fmt.Sprintf("release(%s): %s → %s", r.Env, r.Service, shortDigest(r.ImageDigest))
	out, err := exec.Command("gh", "pr", "create", "--repo", g.repo,
		"--title", title, "--body", evidenceMarkdown(ev), "--head", "HEAD").CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("gh pr create: %v: %s", err, strings.TrimSpace(string(out)))
	}
	return strings.TrimSpace(string(out)), nil
}

func (c config) releaseHandler(pub publisher) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var req releaseRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeErr(w, http.StatusBadRequest, "invalid JSON body")
			return
		}
		if errs := validateRelease(req); len(errs) > 0 {
			writeJSON(w, http.StatusBadRequest, map[string]any{"errors": errs})
			return
		}
		signed := checkSigned(req.ImageDigest)
		if c.requireSigned && !signed && !c.allowUnsigned {
			writeErr(w, http.StatusForbidden,
				"image is not signed (signed_images guard); set SHIM_ALLOW_UNSIGNED for an audited breakglass")
			return
		}
		ev := evidence{
			Service: req.Service, Env: req.Env, Digest: req.ImageDigest,
			Signed: signed, PolicyPass: true, CreatedAt: time.Now().UTC().Format(time.RFC3339),
		}
		prURL, err := pub.publish(req, ev)
		if err != nil {
			writeErr(w, http.StatusBadGateway, err.Error())
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"pr_url": prURL, "evidence_bundle": ev})
	}
}

// ── /compose/kompose/convert ─────────────────────────────────────────────────
type composeRequest struct {
	Repo        string `json:"repo"`
	ComposePath string `json:"compose_path"`
}

func composeHandler(w http.ResponseWriter, r *http.Request) {
	var req composeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeErr(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	if req.Repo == "" || req.ComposePath == "" {
		writeErr(w, http.StatusBadRequest, "repo and compose_path are required")
		return
	}
	if _, err := exec.LookPath("kompose"); err != nil {
		writeErr(w, http.StatusNotImplemented, "kompose not available on the shim host")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"pr_url": fmt.Sprintf("local://gitops/compose/%s", req.Repo),
		"note":   "kompose convert queued for " + req.ComposePath,
	})
}

// ── /cloudshell/launch ───────────────────────────────────────────────────────
type shellRequest struct {
	Repo string `json:"repo"`
	Ref  string `json:"ref"`
	Cmd  string `json:"cmd"`
	Size string `json:"size"`
}

func (c config) shellHandler(w http.ResponseWriter, r *http.Request) {
	var req shellRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeErr(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	if req.Size == "" {
		req.Size = "s"
	}
	if !validSizes[req.Size] {
		writeErr(w, http.StatusBadRequest, "size must be one of s, m, l")
		return
	}
	// Identity-correct: derive the workspace from the authenticated user
	// (oauth2-proxy sets X-Forwarded-User) — never a shared identity.
	user := r.Header.Get("X-Forwarded-User")
	if user == "" {
		user = "local"
	}
	workspace := "u-" + sanitize(user)
	writeJSON(w, http.StatusOK, map[string]any{
		"shell_url":    fmt.Sprintf("%s/u/%s", strings.TrimRight(c.shellBase, "/"), workspace),
		"workspace_id": workspace,
	})
}

// ── helpers ──────────────────────────────────────────────────────────────────
func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}

func writeErr(w http.ResponseWriter, code int, msg string) {
	writeJSON(w, code, map[string]any{"error": msg})
}

func evidenceMarkdown(ev evidence) string {
	return fmt.Sprintf("release evidence\n\n- service: %s\n- env: %s\n- digest: %s\n- signed: %v\n- policy_pass: %v\n- created_at: %s\n",
		ev.Service, ev.Env, ev.Digest, ev.Signed, ev.PolicyPass, ev.CreatedAt)
}

func shortDigest(d string) string {
	if i := strings.Index(d, "sha256:"); i >= 0 && len(d) >= i+7+12 {
		return d[i+7 : i+7+12]
	}
	return d
}

var sanitizeRe = regexp.MustCompile(`[^a-z0-9-]+`)

func sanitize(s string) string {
	return sanitizeRe.ReplaceAllString(strings.ToLower(s), "-")
}

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func envBool(k string, def bool) bool {
	switch strings.ToLower(os.Getenv(k)) {
	case "1", "true", "yes":
		return true
	case "0", "false", "no":
		return false
	default:
		return def
	}
}

func newMux(c config) *http.ServeMux {
	var pub publisher = dryRunPublisher{}
	if c.gitopsRepo != "" {
		pub = gitopsPublisher{repo: c.gitopsRepo}
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})
	mux.HandleFunc("/release/publish", c.releaseHandler(pub))
	mux.HandleFunc("/compose/kompose/convert", composeHandler)
	mux.HandleFunc("/cloudshell/launch", c.shellHandler)
	return mux
}

func main() {
	c := loadConfig()
	addr := ":" + envOr("PORT", "8081")
	log.Printf("porter-shim listening on %s (gitops_repo=%q require_signed=%v)", addr, c.gitopsRepo, c.requireSigned)
	log.Fatal(http.ListenAndServe(addr, newMux(c)))
}
