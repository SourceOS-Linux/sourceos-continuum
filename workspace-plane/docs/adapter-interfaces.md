# Adapter Interfaces v0

The platform should be implemented behind narrow interfaces.

## Compiler

Responsibilities:
- parse authoring inputs
- normalize into `WorkspaceGraph`
- compile `WorkspaceSync`
- emit diagnostics and evidence

Interface sketch:

```text
Compile(inputs: AuthoringBundle, options: CompileOptions) ->
  { graph: WorkspaceGraph, sync: WorkspaceSync, diagnostics: Diagnostic[], evidence: WorkspaceEvidence }
```

## LocalRuntimeAdapter

Responsibilities:
- realize graph on rootless Podman
- attach bind mounts / named volumes
- expose forwarded ports
- report runtime IDs and health

```text
RealizeLocal(graph: WorkspaceGraph) -> LocalRuntimePlan
```

## KubernetesRuntimeAdapter

Responsibilities:
- attach to an existing namespace/workload or materialize new workloads
- enforce `portable-restricted` defaults
- shape manifests after normalization
- expose runtime IDs and service endpoints

```text
RealizeCluster(graph: WorkspaceGraph, mode: attach|materialize) -> ClusterRuntimePlan
```

## SyncAdapter

Responsibilities:
- execute `WorkspaceSync`
- manage checkpoints
- emit conflicts and acknowledgements
- respect authority classes

```text
StartSync(sync: WorkspaceSync, plan: RuntimePlan) -> SyncSession
```

## AttachBroker

Responsibilities:
- broker LSP/DAP/terminal/preview access
- keep auth, port forwarding, and capability grants separate from sync

```text
Attach(graph: WorkspaceGraph, plan: RuntimePlan, client: IDEClient) -> AttachSession
```

## EvidenceEmitter

Responsibilities:
- persist compile and runtime evidence
- expose replay-friendly records

```text
Emit(record: WorkspaceEvidence | Diagnostic | RuntimeEvent) -> void
```
