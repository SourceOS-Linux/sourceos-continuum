package main

import (
  "context"
  "fmt"
  "log"
  "os"
  "time"

  metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
  "k8s.io/client-go/kubernetes"
  "k8s.io/client-go/rest"
)

func getenv(k, d string) string { if v := os.Getenv(k); v != "" { return v }; return d }
func getenvInt(k string, d int) int { if v := os.Getenv(k); v != "" { var i int; _, _ = fmt.Sscanf(v, "%d", &i); return i }; return d }

func main() {
  ns := getenv("NAMESPACE", "devtools")
  idleMins := getenvInt("IDLE_AFTER_MINUTES", 60)
  idle := time.Duration(idleMins) * time.Minute

  cfg, err := rest.InClusterConfig()
  if err != nil { log.Fatalf("InClusterConfig: %v", err) }
  cs, err := kubernetes.NewForConfig(cfg)
  if err != nil { log.Fatalf("NewForConfig: %v", err) }

  ticker := time.NewTicker(3 * time.Minute)
  for range ticker.C {
    ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
    deps, err := cs.AppsV1().Deployments(ns).List(ctx, metav1.ListOptions{LabelSelector: "app.kubernetes.io/name=cloudshell"})
    cancel()
    if err != nil { log.Printf("list deployments: %v", err); continue }

    now := time.Now().UTC()
    for _, d := range deps.Items {
      ls := d.Annotations["cloudshell/lastSeen"]
      last := d.CreationTimestamp.Time
      if ls != "" {
        if t, err := time.Parse(time.RFC3339, ls); err == nil {
          last = t
        }
      }
      if now.Sub(last) > idle {
        log.Printf("culling idle shell: %s (idle=%s)", d.Name, now.Sub(last))
        ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
        _ = cs.AppsV1().Deployments(ns).Delete(ctx, d.Name, metav1.DeleteOptions{})
        cancel()
      }
    }
  }
}
