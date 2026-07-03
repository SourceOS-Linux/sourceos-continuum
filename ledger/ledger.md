# Running Ledger (deduplicated)

This ledger merges all items mentioned in the chat into one deduplicated table.

## Counts by kind and classification

| kind              | classification   |   count |
|:------------------|:-----------------|--------:|
| internal_artifact | core             |       4 |
| internal_artifact | profile          |       1 |
| upload            | core             |      21 |
| upload            | inspiration      |       2 |
| upload            | pending          |       1 |
| upload            | profile          |      28 |
| url               | core             |       2 |
| url               | inspiration      |       1 |
| url               | pending          |       9 |
| url               | profile          |       7 |

## Notes

- Uploaded zip files are listed for tracking but are not currently present in this bundle filesystem.

- `coreos/toolbox` is tracked for lessons but upstream marks it deprecated in favor of `containers/toolbox`.
