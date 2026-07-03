package main

import (
  "context"
  "crypto/sha1"
  "encoding/hex"
  "encoding/json"
  "fmt"
  "log"
  "net/http"
  "os"
  "time"

  "github.com/gorilla/mux"
  appsv1 "k8s.io/api/apps/v1"
  corev1 "k8s.io/api/core/v1"
  rbacv1 "k8s.io/api/rbac/v1"
  metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
  "k8s.io/apimachinery/pkg/api/resource"
  "k8s.io/apimachinery/pkg/util/intstr"
  "k8s.io/client-go/kubernetes"
  "k8s.io/client-go/rest"
)

type Size struct {
  CPU    string `json:"cpu"`
  Memory string `json:"memory"`
  PVC    string `json:"pvc"`
}

type LaunchRequest struct {
  Repo string `json:"repo,omitempty"`
  Ref  string `json:"ref,omitempty"`
  Cmd  string `json:"cmd,omitempty"`
  Size string `json:"size,omitempty"` // s|m|l
}

func firstNonEmpty(vs ...string) string {
  for _, v := range vs {
    if v != "" {
      return v
    }
  }
  return ""
}

func hashUser(u string) string {
  h := sha1.Sum([]byte(u))
  return hex.EncodeToString(h[:])[:10]
}

func getenv(k, d string) string {
  if v := os.Getenv(k); v != "" {
    return v
  }
  return d
}

func main() {
  ns := getenv("NAMESPACE", "devtools")
  image := getenv("SHELL_IMAGE", "ghcr.io/your-org/cloud-shell@sha256:REPLACE")
  // Spawned shells run as this UID so images defaulting to root (e.g. public
  // ttyd) satisfy runAsNonRoot. 0 = leave unset.
  var runAsUser int64
  if v := os.Getenv("SHELL_RUN_AS_USER"); v != "" {
    _, _ = fmt.Sscanf(v, "%d", &runAsUser)
  }
  sizes := map[string]Size{
    "s": {CPU: "250m", Memory: "512Mi", PVC: "5Gi"},
    "m": {CPU: "500m", Memory: "1Gi", PVC: "10Gi"},
    "l": {CPU: "2", Memory: "4Gi", PVC: "20Gi"},
  }

  cfg, err := rest.InClusterConfig()
  if err != nil {
    log.Fatalf("InClusterConfig: %v", err)
  }
  cs, err := kubernetes.NewForConfig(cfg)
  if err != nil {
    log.Fatalf("NewForConfig: %v", err)
  }

  r := mux.NewRouter()
  r.HandleFunc("/launch", func(w http.ResponseWriter, req *http.Request) {
    user := firstNonEmpty(
      req.Header.Get("X-Auth-Request-Email"),
      req.Header.Get("X-Forwarded-Email"),
      req.Header.Get("X-Auth-Request-User"),
      req.Header.Get("X-Forwarded-User"),
      req.Header.Get("X-Forwarded-Preferred-Username"),
    )
    if user == "" {
      http.Error(w, "missing auth identity headers", http.StatusUnauthorized)
      return
    }

var lr LaunchRequest
    _ = json.NewDecoder(req.Body).Decode(&lr)
    if lr.Size == "" {
      lr.Size = "s"
    }
    sz, ok := sizes[lr.Size]
    if !ok {
      sz = sizes["s"]
    }

    uid := "u-" + hashUser(user)
    sa := uid + "-sa"
    pvc := uid + "-home"
    dep := uid + "-shell"
    svc := uid

    ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
    defer cancel()

    ensureServiceAccount(ctx, cs, ns, sa)
    ensureRole(ctx, cs, ns)                    // cloudshell-view role
    ensureRoleBinding(ctx, cs, ns, uid, sa)    // bind SA to role
    ensurePVC(ctx, cs, ns, pvc, sz.PVC)
    ensureDeployment(ctx, cs, ns, dep, image, sa, pvc, uid, sz, runAsUser)
    patchLastSeen(ctx, cs, ns, dep)
    ensureService(ctx, cs, ns, svc, dep)

    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(map[string]string{
      "user": user,
      "uid": uid,
      "service": svc,
      "deployment": dep,
      "pvc": pvc,
      "sa": sa,
    })
  }).Methods("POST")

  log.Printf("cloudshell-spawner listening on :8080 (namespace=%s)", ns)
  log.Fatal(http.ListenAndServe(":8080", r))
}

func ensureServiceAccount(ctx context.Context, cs *kubernetes.Clientset, ns, name string) {
  _, err := cs.CoreV1().ServiceAccounts(ns).Get(ctx, name, metav1.GetOptions{})
  if err == nil {
    return
  }
  _, _ = cs.CoreV1().ServiceAccounts(ns).Create(ctx, &corev1.ServiceAccount{
    ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: ns},
  }, metav1.CreateOptions{})
}

func ensureRole(ctx context.Context, cs *kubernetes.Clientset, ns string) {
  name := "cloudshell-view"
  _, err := cs.RbacV1().Roles(ns).Get(ctx, name, metav1.GetOptions{})
  if err == nil {
    return
  }
  _, _ = cs.RbacV1().Roles(ns).Create(ctx, &rbacv1.Role{
    ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: ns},
    Rules: []rbacv1.PolicyRule{
      {APIGroups: []string{"", "apps", "batch", "extensions"}, Resources: []string{"pods", "pods/log", "services", "deployments", "replicasets", "jobs", "cronjobs", "configmaps"}, Verbs: []string{"get", "list", "watch"}},
    },
  }, metav1.CreateOptions{})
}

func ensureRoleBinding(ctx context.Context, cs *kubernetes.Clientset, ns, uid, sa string) {
  name := uid + "-rb"
  _, err := cs.RbacV1().RoleBindings(ns).Get(ctx, name, metav1.GetOptions{})
  if err == nil {
    return
  }
  _, _ = cs.RbacV1().RoleBindings(ns).Create(ctx, &rbacv1.RoleBinding{
    ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: ns},
    Subjects: []rbacv1.Subject{{Kind: "ServiceAccount", Name: sa, Namespace: ns}},
    RoleRef:  rbacv1.RoleRef{Kind: "Role", Name: "cloudshell-view", APIGroup: "rbac.authorization.k8s.io"},
  }, metav1.CreateOptions{})
}

func ensurePVC(ctx context.Context, cs *kubernetes.Clientset, ns, name, size string) {
  _, err := cs.CoreV1().PersistentVolumeClaims(ns).Get(ctx, name, metav1.GetOptions{})
  if err == nil {
    return
  }
  q := resource.MustParse(size)
  _, _ = cs.CoreV1().PersistentVolumeClaims(ns).Create(ctx, &corev1.PersistentVolumeClaim{
    ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: ns},
    Spec: corev1.PersistentVolumeClaimSpec{
      AccessModes: []corev1.PersistentVolumeAccessMode{corev1.ReadWriteOnce},
      Resources: corev1.VolumeResourceRequirements{
        Requests: corev1.ResourceList{"storage": q},
      },
    },
  }, metav1.CreateOptions{})
}

func ensureDeployment(ctx context.Context, cs *kubernetes.Clientset, ns, name, image, sa, pvc, uid string, sz Size, runAsUser int64) {
  _, err := cs.AppsV1().Deployments(ns).Get(ctx, name, metav1.GetOptions{})
  if err == nil {
    return
  }
  cpu := resource.MustParse(sz.CPU)
  mem := resource.MustParse(sz.Memory)

  replicas := int32(1)
  dep := &appsv1.Deployment{
    ObjectMeta: metav1.ObjectMeta{
      Name:      name,
      Namespace: ns,
      Labels: map[string]string{
        "app.kubernetes.io/name": "cloudshell",
        "cloudshell/user":        uid,
      },
      Annotations: map[string]string{
        "cloudshell/lastSeen": time.Now().UTC().Format(time.RFC3339),
      },
    },
    Spec: appsv1.DeploymentSpec{
      Replicas: &replicas,
      Selector: &metav1.LabelSelector{MatchLabels: map[string]string{"app": "cloudshell", "cloudshell/user": uid}},
      Template: corev1.PodTemplateSpec{
        ObjectMeta: metav1.ObjectMeta{Labels: map[string]string{"app": "cloudshell", "cloudshell/user": uid, "app.kubernetes.io/name": "cloudshell"}},
        Spec: corev1.PodSpec{
          ServiceAccountName: sa,
          SecurityContext: &corev1.PodSecurityContext{
            RunAsNonRoot: func() *bool { b := true; return &b }(),
            RunAsUser: func() *int64 { if runAsUser > 0 { u := runAsUser; return &u }; return nil }(),
            FSGroup:   func() *int64 { if runAsUser > 0 { u := runAsUser; return &u }; return nil }(),
            SeccompProfile: &corev1.SeccompProfile{Type: corev1.SeccompProfileTypeRuntimeDefault},
          },
          Containers: []corev1.Container{{
            Name:  "shell",
            Image: image,
            Ports: []corev1.ContainerPort{{Name: "http", ContainerPort: 7681}},
            Resources: corev1.ResourceRequirements{
              Requests: corev1.ResourceList{corev1.ResourceCPU: cpu, corev1.ResourceMemory: mem},
              Limits:   corev1.ResourceList{corev1.ResourceCPU: cpu, corev1.ResourceMemory: mem},
            },
            SecurityContext: &corev1.SecurityContext{
              RunAsNonRoot:             func() *bool { b := true; return &b }(),
              RunAsUser:                func() *int64 { if runAsUser > 0 { u := runAsUser; return &u }; return nil }(),
              AllowPrivilegeEscalation: func() *bool { b := false; return &b }(),
              Capabilities:             &corev1.Capabilities{Drop: []corev1.Capability{"ALL"}},
            },
            VolumeMounts: []corev1.VolumeMount{{Name: "home", MountPath: "/home/cloud"}},
            ReadinessProbe: &corev1.Probe{
              ProbeHandler: corev1.ProbeHandler{HTTPGet: &corev1.HTTPGetAction{Path: "/", Port: intstr.FromString("http")}},
              InitialDelaySeconds: 3,
              PeriodSeconds:       10,
            },
          }},
          Volumes: []corev1.Volume{{Name: "home", VolumeSource: corev1.VolumeSource{PersistentVolumeClaim: &corev1.PersistentVolumeClaimVolumeSource{ClaimName: pvc}}}},
        },
      },
    },
  }
  _, _ = cs.AppsV1().Deployments(ns).Create(ctx, dep, metav1.CreateOptions{})
}


func patchLastSeen(ctx context.Context, cs *kubernetes.Clientset, ns, depName string) {
  // Best-effort: update Deployment annotation so the culler doesn't delete recently used shells.
  // This is *not* a perfect activity signal; the real solution is a heartbeat (auth_request or metrics-based).
  d, err := cs.AppsV1().Deployments(ns).Get(ctx, depName, metav1.GetOptions{})
  if err != nil { return }
  if d.Annotations == nil { d.Annotations = map[string]string{} }
  d.Annotations["cloudshell/lastSeen"] = time.Now().UTC().Format(time.RFC3339)
  _, _ = cs.AppsV1().Deployments(ns).Update(ctx, d, metav1.UpdateOptions{})
}
func ensureService(ctx context.Context, cs *kubernetes.Clientset, ns, name, depName string) {
  _, err := cs.CoreV1().Services(ns).Get(ctx, name, metav1.GetOptions{})
  if err == nil {
    return
  }
  _, _ = cs.CoreV1().Services(ns).Create(ctx, &corev1.Service{
    ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: ns},
    Spec: corev1.ServiceSpec{
      Selector: map[string]string{"app": "cloudshell", "cloudshell/user": name},
      Ports:    []corev1.ServicePort{{Name: "http", Port: 80, TargetPort: intstr.FromInt(7681)}},
    },
  }, metav1.CreateOptions{})
}
