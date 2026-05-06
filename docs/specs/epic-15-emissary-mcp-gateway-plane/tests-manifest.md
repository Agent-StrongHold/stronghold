# Epic 15: Tests Manifest

149 contract tests landed across the plane. Story numbers refer to README.md.

## Story 15.1 — ToolCatalog + ToolFingerprinter

| Test path                                       | Test function                                                         | Tier     |
|-------------------------------------------------|------------------------------------------------------------------------|----------|
| tests/security/test_tool_fingerprint.py         | test_same_input_produces_same_fingerprint                              | critical |
| tests/security/test_tool_fingerprint.py         | test_key_order_does_not_change_fingerprint                             | critical |
| tests/security/test_tool_fingerprint.py         | test_description_change_changes_fingerprint                            | critical |
| tests/security/test_tool_fingerprint.py         | test_schema_change_changes_both_value_and_schema_hash                  | critical |
| tests/security/test_tool_fingerprint.py         | test_name_change_keeps_schema_hash_stable                              | happy    |
| tests/security/test_tool_fingerprint.py         | test_openai_function_format_matches_flat_format                        | happy    |
| tests/security/test_tool_fingerprint.py         | test_unicode_normalization_in_description                              | happy    |
| tests/security/test_tool_catalog.py             | test_unknown_fingerprint_returns_none                                  | critical |
| tests/security/test_tool_catalog.py             | test_org_scope_visible_to_org_member                                   | critical |
| tests/security/test_tool_catalog.py             | test_org_scope_invisible_to_other_org                                  | critical |
| tests/security/test_tool_catalog.py             | test_team_scope_invisible_to_other_team_in_same_org                    | critical |
| tests/security/test_tool_catalog.py             | test_user_scope_invisible_to_other_user_in_same_team                   | critical |
| tests/security/test_tool_catalog.py             | test_platform_scope_visible_to_all_members                             | happy    |
| tests/security/test_tool_catalog.py             | test_system_principal_sees_everything_regardless_of_scope              | critical |
| tests/security/test_tool_catalog.py             | test_approvals_for_returns_the_union_across_scope_chain                | happy    |
| tests/security/test_tool_catalog.py             | test_revoke_at_scope_only_removes_that_scope                           | critical |
| tests/security/test_tool_catalog.py             | test_revoke_without_scope_removes_all_approvals                        | critical |
| tests/security/test_tool_catalog.py             | test_subscribe_changes_fires_on_approve_and_revoke                     | happy    |
| tests/security/test_tool_catalog.py             | test_unsubscribe_stops_callbacks                                       | happy    |
| tests/security/test_tool_catalog.py             | test_fingerprints_with_name_supports_rug_pull_diagnostics              | critical |

## Story 15.2 — Sentinel ToolDeclarationValidator + chat-edge hook

| Test path                                            | Test function                                                            | Tier     |
|------------------------------------------------------|---------------------------------------------------------------------------|----------|
| tests/security/test_sentinel_tool_declarations.py    | test_all_approved_tools_pass                                              | happy    |
| tests/security/test_sentinel_tool_declarations.py    | test_empty_tools_array_is_allowed                                         | happy    |
| tests/security/test_sentinel_tool_declarations.py    | test_unknown_tool_blocks_with_submit_url                                  | critical |
| tests/security/test_sentinel_tool_declarations.py    | test_schema_drift_reported_as_mismatch_not_unapproved                     | critical |
| tests/security/test_sentinel_tool_declarations.py    | test_mixed_approved_and_unapproved_blocks_entire_request                  | critical |
| tests/security/test_sentinel_tool_declarations.py    | test_tool_order_does_not_change_decision                                  | happy    |
| tests/security/test_sentinel_tool_declarations.py    | test_catalog_unavailable_fails_closed                                     | critical |
| tests/security/test_sentinel_tool_declarations.py    | test_openai_function_format_is_canonicalised                              | happy    |
| tests/api/test_chat_tool_declarations.py             | test_inbound_tools_without_validator_does_not_block                       | happy    |
| tests/api/test_chat_tool_declarations.py             | test_inbound_no_tools_field_skips_validation                              | happy    |
| tests/api/test_chat_tool_declarations.py             | test_inbound_empty_tools_array_skips_validation                           | happy    |
| tests/api/test_chat_tool_declarations.py             | test_inbound_unapproved_tool_returns_403                                  | critical |
| tests/api/test_chat_tool_declarations.py             | test_inbound_approved_tool_passes_validation                              | happy    |
| tests/api/test_chat_tool_declarations.py             | test_inbound_mixed_blocks_on_first_unapproved                             | critical |

## Story 15.3 — Keyward

| Test path                            | Test function                                                | Tier     |
|--------------------------------------|--------------------------------------------------------------|----------|
| tests/security/test_keyward.py       | test_issue_for_approved_tool_returns_signed_token            | critical |
| tests/security/test_keyward.py       | test_refuse_unapproved_tool                                  | critical |
| tests/security/test_keyward.py       | test_refuse_audience_outside_allowed_set                     | critical |
| tests/security/test_keyward.py       | test_refuse_scope_escalation                                 | critical |
| tests/security/test_keyward.py       | test_default_ttl_15_minutes                                  | happy    |
| tests/security/test_keyward.py       | test_per_audience_ttl_override                               | happy    |
| tests/security/test_keyward.py       | test_revoke_by_token_id_marks_introspection                  | critical |
| tests/security/test_keyward.py       | test_revoke_by_tool_revokes_all_active_for_that_tool         | critical |
| tests/security/test_keyward.py       | test_revoke_is_idempotent                                    | happy    |
| tests/security/test_keyward.py       | test_introspect_unknown_token_returns_none                   | happy    |
| tests/security/test_keyward.py       | test_keyward_refuses_to_start_without_signing_key            | critical |

## Story 15.4 — Composer

| Test path                          | Test function                                                          | Tier     |
|------------------------------------|-------------------------------------------------------------------------|----------|
| tests/mcp/test_composer.py         | test_single_step_executes_and_returns_outputs                           | happy    |
| tests/mcp/test_composer.py         | test_args_template_resolves_caller_args_and_step_outputs                | critical |
| tests/mcp/test_composer.py         | test_step_call_id_is_namespaced_under_composite                         | happy    |
| tests/mcp/test_composer.py         | test_abort_on_error_stops_execution_and_marks_partial                   | critical |
| tests/mcp/test_composer.py         | test_skip_on_error_continues_to_next_step                               | critical |
| tests/mcp/test_composer.py         | test_retry_on_error_attempts_twice                                      | critical |
| tests/mcp/test_composer.py         | test_step_returning_is_error_marks_partial_and_aborts_by_default        | critical |
| tests/mcp/test_composer.py         | test_unregistered_composite_raises                                      | critical |
| tests/mcp/test_composer.py         | test_is_registered_reflects_register                                    | happy    |

## Story 15.5 — Emissary + HTTP binding + outbound MCPClient + invokers

| Test path                              | Test function                                                                  | Tier     |
|----------------------------------------|---------------------------------------------------------------------------------|----------|
| tests/mcp/test_emissary.py             | test_unknown_tool_raises_unauthorized                                           | critical |
| tests/mcp/test_emissary.py             | test_approved_tool_with_no_backend_raises_missing_backend                       | critical |
| tests/mcp/test_emissary.py             | test_local_host_dispatch_invokes_local_invoker                                  | happy    |
| tests/mcp/test_emissary.py             | test_remote_proxy_dispatch_invokes_remote_invoker                               | happy    |
| tests/mcp/test_emissary.py             | test_first_party_dispatch_invokes_first_party_invoker                           | happy    |
| tests/mcp/test_emissary.py             | test_call_records_keyward_token_id_on_result                                    | happy    |
| tests/mcp/test_emissary.py             | test_keyward_audience_denied_propagates_as_unauthorized                         | critical |
| tests/mcp/test_emissary.py             | test_warden_block_returns_error_result_not_raw_content                          | critical |
| tests/mcp/test_emissary.py             | test_warden_revoke_directive_calls_keyward_revoke                               | critical |
| tests/mcp/test_emissary.py             | test_warden_sanitize_returns_sanitised_wrapper                                  | happy    |
| tests/mcp/test_emissary.py             | test_session_lookup_by_wrong_principal_refused                                  | critical |
| tests/mcp/test_emissary.py             | test_session_idle_timeout_expires_session                                       | critical |
| tests/mcp/test_emissary.py             | test_session_affinity_routes_to_same_instance                                   | happy    |
| tests/mcp/test_emissary.py             | test_idempotency_key_same_args_returns_cached                                   | happy    |
| tests/mcp/test_emissary.py             | test_idempotency_key_different_args_raises_conflict                             | critical |
| tests/mcp/test_emissary.py             | test_backend_exception_raises_backend_unavailable                               | critical |
| tests/mcp/test_emissary.py             | test_list_tools_returns_only_authorized                                         | critical |
| tests/mcp/test_emissary.py             | test_composite_dispatch_routes_through_composer_and_back_to_atomic_steps        | critical |
| tests/mcp/test_emissary.py             | test_idempotency_cache_evicts_expired_entries_on_write                          | happy    |
| tests/mcp/test_emissary.py             | test_idempotency_cache_does_not_evict_unexpired_entries                         | happy    |
| tests/mcp/test_http_binding.py         | test_prm_served_at_well_known_uri                                               | critical |
| tests/mcp/test_http_binding.py         | test_prm_served_at_subpath                                                      | happy    |
| tests/mcp/test_http_binding.py         | test_unauthenticated_request_returns_401_with_prm_pointer                       | critical |
| tests/mcp/test_http_binding.py         | test_token_with_wrong_audience_rejected_as_invalid                              | critical |
| tests/mcp/test_http_binding.py         | test_unknown_token_rejected                                                     | critical |
| tests/mcp/test_http_binding.py         | test_authenticated_tools_list_returns_authorized_set                            | happy    |
| tests/mcp/test_http_binding.py         | test_authenticated_tools_call_dispatches_to_emissary                            | happy    |
| tests/mcp/test_http_binding.py         | test_unknown_tool_call_returns_jsonrpc_error_not_500                            | happy    |
| tests/mcp/test_http_binding.py         | test_method_not_found_returns_jsonrpc_minus_32601                               | happy    |
| tests/mcp/test_mcp_client.py           | test_discover_parses_prm_and_caches                                             | happy    |
| tests/mcp/test_mcp_client.py           | test_discover_rejects_non_https_outside_dev_mode                                | critical |
| tests/mcp/test_mcp_client.py           | test_discover_allows_localhost_in_dev_mode                                      | happy    |
| tests/mcp/test_mcp_client.py           | test_malformed_prm_raises_typed_error                                           | critical |
| tests/mcp/test_mcp_client.py           | test_prm_invalidated_on_401                                                     | critical |
| tests/mcp/test_mcp_client.py           | test_token_passthrough_audience_mismatch_refused_before_network                 | critical |
| tests/mcp/test_mcp_client.py           | test_call_tool_returns_result_content                                           | happy    |
| tests/mcp/test_mcp_client.py           | test_list_tools_returns_descriptors                                             | happy    |
| tests/mcp/test_mcp_client.py           | test_403_insufficient_scope_parses_required                                     | critical |
| tests/mcp/test_mcp_client.py           | test_jsonrpc_error_raises_remote_tool_error                                     | critical |
| tests/mcp/test_mcp_client.py           | test_500_response_raises_remote_tool_error                                      | happy    |
| tests/mcp/test_mcp_client.py           | test_prm_ttl_expires_and_is_refreshed                                           | happy    |
| tests/mcp/test_invokers.py             | test_remote_invoker_dispatches_via_client                                       | happy    |
| tests/mcp/test_invokers.py             | test_remote_invoker_missing_server_uri_raises                                   | critical |
| tests/mcp/test_invokers.py             | test_local_host_invoker_dispatches_to_endpoint                                  | happy    |
| tests/mcp/test_invokers.py             | test_local_host_invoker_pending_status_raises_not_running                       | critical |
| tests/mcp/test_invokers.py             | test_local_host_invoker_failed_status_calls_health_then_raises                  | critical |
| tests/mcp/test_invokers.py             | test_local_host_invoker_unregistered_server_raises                              | critical |
| tests/mcp/test_invokers.py             | test_local_host_invoker_missing_server_name_metadata_raises                     | critical |
| tests/mcp/test_invokers.py             | test_local_host_invoker_500_endpoint_raises_backend_unavailable                 | critical |
| tests/mcp/test_invokers.py             | test_local_host_invoker_jsonrpc_error_raises_remote_tool_error                  | critical |

## Story 15.6 — Admin API + YAML loader

| Test path                                  | Test function                                                          | Tier     |
|--------------------------------------------|-------------------------------------------------------------------------|----------|
| tests/mcp/test_registration_loader.py      | test_loads_remote_proxy_entry                                           | happy    |
| tests/mcp/test_registration_loader.py      | test_loads_multiple_entries                                             | happy    |
| tests/mcp/test_registration_loader.py      | test_missing_file_raises                                                | critical |
| tests/mcp/test_registration_loader.py      | test_malformed_yaml_raises                                              | critical |
| tests/mcp/test_registration_loader.py      | test_top_level_not_a_list_raises                                        | critical |
| tests/mcp/test_registration_loader.py      | test_entry_missing_name_raises                                          | critical |
| tests/mcp/test_registration_loader.py      | test_entry_missing_audiences_raises                                     | critical |
| tests/mcp/test_registration_loader.py      | test_invalid_target_kind_raises                                         | critical |
| tests/mcp/test_registration_loader.py      | test_partial_application_does_not_leak_on_failure                       | critical |
| tests/mcp/test_registration_loader.py      | test_reloading_same_file_is_idempotent                                  | happy    |
| tests/api/test_mcp_admin_routes.py         | test_list_returns_503_when_plane_not_wired                              | critical |
| tests/api/test_mcp_admin_routes.py         | test_list_without_auth_is_401                                           | critical |
| tests/api/test_mcp_admin_routes.py         | test_list_returns_seeded_tool                                           | happy    |
| tests/api/test_mcp_admin_routes.py         | test_list_empty_when_no_tools_approved                                  | happy    |
| tests/api/test_mcp_admin_routes.py         | test_get_one_returns_full_entry                                         | happy    |
| tests/api/test_mcp_admin_routes.py         | test_get_unknown_fingerprint_404                                        | critical |
| tests/api/test_mcp_admin_routes.py         | test_approve_creates_catalog_entry_and_backend                          | critical |
| tests/api/test_mcp_admin_routes.py         | test_approve_missing_name_returns_400                                   | critical |
| tests/api/test_mcp_admin_routes.py         | test_approve_invalid_target_kind_returns_400                            | critical |
| tests/api/test_mcp_admin_routes.py         | test_approve_empty_audiences_returns_400                                | critical |
| tests/api/test_mcp_admin_routes.py         | test_revoke_removes_catalog_entry                                       | critical |
| tests/api/test_mcp_admin_routes.py         | test_revoke_unknown_fingerprint_404                                     | critical |
| tests/container/test_container_coverage.py | TestContainerEmissaryPlane::test_mcp_tool_catalog_is_real_inmemory_catalog | critical |
| tests/container/test_container_coverage.py | TestContainerEmissaryPlane::test_keyward_refuses_unapproved_tool        | critical |
| tests/container/test_container_coverage.py | TestContainerEmissaryPlane::test_composer_is_a_real_composer            | happy    |
| tests/container/test_container_coverage.py | TestContainerEmissaryPlane::test_mcp_client_is_real_client              | happy    |
| tests/container/test_container_coverage.py | TestContainerEmissaryPlane::test_emissary_lists_tools_empty_for_system  | happy    |
| tests/container/test_container_coverage.py | TestContainerEmissaryPlane::test_tool_declaration_validator_passes_empty_tools_array | happy    |
| tests/container/test_container_coverage.py | TestContainerEmissaryPlane::test_tool_declaration_validator_blocks_unapproved_tool   | critical |

## Story 15.7 — Postgres persistence

| Test path                            | Test function                                                          | Tier     |
|--------------------------------------|-------------------------------------------------------------------------|----------|
| tests/persistence/test_pg_mcp.py     | test_catalog_approve_emits_upsert_sql                                   | critical |
| tests/persistence/test_pg_mcp.py     | test_catalog_revoke_with_scope_targets_one_row                          | critical |
| tests/persistence/test_pg_mcp.py     | test_catalog_revoke_without_scope_drops_all                             | critical |
| tests/persistence/test_pg_mcp.py     | test_catalog_load_all_round_trips_a_row                                 | critical |
| tests/persistence/test_pg_mcp.py     | test_registration_upsert_writes_audiences_as_json                       | critical |
| tests/persistence/test_pg_mcp.py     | test_registration_remove_deletes_by_fingerprint                         | critical |
| tests/persistence/test_pg_mcp.py     | test_registration_load_all_round_trips                                  | happy    |
| tests/persistence/test_pg_mcp.py     | test_revocation_add_persists_token_id_and_context                       | critical |
| tests/persistence/test_pg_mcp.py     | test_revocation_is_revoked_returns_true_when_row_exists                 | happy    |
| tests/persistence/test_pg_mcp.py     | test_revocation_is_revoked_returns_false_when_no_row                    | happy    |
| tests/persistence/test_pg_mcp.py     | test_revocation_load_active_returns_token_id_set                        | happy    |
| tests/persistence/test_pg_mcp.py     | test_revocation_purge_older_than_returns_count                          | happy    |
| tests/persistence/test_pg_mcp.py     | test_composite_upsert_persists_steps_as_json                            | critical |
| tests/persistence/test_pg_mcp.py     | test_composite_load_all_reconstructs_step_graph                         | critical |
| tests/persistence/test_pg_mcp.py     | test_inmemory_catalog_calls_write_through_on_approve_and_revoke         | critical |
| tests/persistence/test_pg_mcp.py     | test_inmemory_catalog_hydrate_skips_write_through                       | critical |

## Pending stories

Stories 15.8 (Redis persistence), 15.9 (agent-side integration),
15.10 (promotion workflow), 15.11 (hardening), and 15.12 (BDD + real-DB
integration) have no tests yet.
