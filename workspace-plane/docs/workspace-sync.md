# WorkspaceSync v0alpha1

`WorkspaceSync` is the compiled sync contract derived from `WorkspaceGraph`.

## Default posture

- single writer by default
- two-way sync is opt-in and narrow
- authoritative side wins, but rejected changes can be preserved in a shadow conflict bundle
- caches, secrets, and stateful data are normally excluded from source sync

## Protocol phases

1. negotiate
2. seed
3. watch
4. journal
5. apply
6. ack
7. checkpoint

## Change operations

The canonical wire primitive is `ChangeOp`.

Fields:
- root
- seq
- side
- kind
- path
- oldPath
- baseDigest
- newDigest
- metadata

## Conflict policies

- `authoritative-wins-with-shadow`
- `manual-merge`
- `deny-on-divergence`

## Path safety rules

- safe relative symlinks only unless profile explicitly allows more
- execute-bit preservation can be constrained to an `exec-bit-only` policy
- delete propagation is an explicit property, never implicit
