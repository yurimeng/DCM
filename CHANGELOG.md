# Changelog

All notable changes to this project will be documented in this file.

## [v3.2] - 2026-04-14

### Added
- **NodeStatusStore Integration**: Matching service now reads node state from NodeStatusStore instead of local memory
- **Debug Mode**: Configurable debug mode (`debug: bool = True`) for detailed error reporting
- **Model Prefix Matching**: Support for model prefix matching (e.g., `qwen` → `qwen2.5:7b`)
- **Optional model/model_family**: Jobs can now be created without specifying model (system assigns best match)

### Changed
- **Refactored poll_node()**: Removed dependency on local `_online_nodes`, now reads from NodeStatusStore
- **Removed register/unregister methods**: Node registration no longer needed in matching_service
- **Debug always shows details**: `_debug_error()` always shows full traceback (no longer gated by debug flag)

### Fixed
- `JobDB` model now includes `user_id` field
- `JobRepository.create()` saves `user_id` to database
- `submit_result` now constructs Job with `user_id`
- `actual_tokens` instead of `actual_output_tokens` in settlement
- `release_node()` no longer references deleted `_online_nodes`
- `get_pending_jobs()` filters completed jobs
- `poll_node` skips already matched jobs

### Removed
- `_online_nodes` dictionary from MatchingService
- `register_node`, `update_node_status`, `unregister_node` methods
- `queue_info` dependency in `_create_match`

## [v3.1] - 2026-04-13

### Added
- Pre-Lock mechanism for job reservation
- Layer 1 and Layer 2 verification
- Escrow settlement with automatic refund

### Fixed
- Job matching logic for model compatibility
- Price comparison (bid_price vs ask_price)

## [v3.0] - 2026-04-12

### Added
- Initial DCM implementation
- Job submission and matching
- Node registration and heartbeat
- Basic escrow system

---

## Commit History (Recent)

```
c6977e98 fix: support model prefix matching in _can_match
71db0915 fix: filter completed jobs in get_pending_jobs
c3dc4e0d fix: use actual_tokens instead of actual_output_tokens
b1efc8ff fix: remove _online_nodes reference in release_node
5bffc28e fix: always show debug info in _debug_error
c2cc68cd fix: add user_id to JobDB model and repository
9c99b879 chore: enable debug mode
21a708d9 fix: make model/model_family optional in JobCreate
cc017a54 refactor: matching_service reads from NodeStatusStore
```
