CREATE INDEX IF NOT EXISTS ix_session_trace_time ON conversation_turn_traces (session_id, created_at)
