# Chat API Selection Decoupling

## Goal

Treat `server_api` and the selected upstream as independent choices on the Chat page.
`server_api` defines the Rosetta client-facing request and response format, while an
upstream's `native_api` defines the format Rosetta uses with that upstream.

## Interaction

- The Upstream dropdown always lists every available upstream.
- Remove the `show all` control and format-based filtering.
- Changing `server_api` preserves the currently selected upstream.
- The upstream label remains `name(model+native_api)` so translation intent is visible.
- The path indicator continues to show direct forwarding or translation through IR.

## Routing

An explicitly selected upstream is sent in `x-rosetta-upstream` regardless of its
`native_api`. The server forwards directly when both API types match and translates
requests and responses when they differ.

When no upstream is selected, existing server fallback behavior remains unchanged:
the server resolves the enabled default upstream matching `server_api`.

## Verification

- Frontend type checking passes.
- A selected upstream remains selected after changing `server_api`.
- All upstreams remain visible for every `server_api` value.
- Direct and translated Chat requests continue to use the existing dataplane paths.
