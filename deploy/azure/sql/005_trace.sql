IF OBJECT_ID(N'trace.trace_events', N'U') IS NULL
CREATE TABLE trace.trace_events (
  event_id NVARCHAR(64) NOT NULL PRIMARY KEY,
  trace_id NVARCHAR(64) NOT NULL,
  span_id NVARCHAR(64) NOT NULL,
  parent_span_id NVARCHAR(64) NULL,
  case_id NVARCHAR(64) NULL,
  input_revision INT NULL,
  draft_id NVARCHAR(64) NULL,
  step NVARCHAR(32) NOT NULL,
  actor NVARCHAR(64) NOT NULL,
  rule_version NVARCHAR(64) NULL,
  started_at NVARCHAR(64) NOT NULL,
  duration_ms INT NULL,
  attempt INT NULL,
  status NVARCHAR(32) NOT NULL,
  error_code NVARCHAR(64) NULL,
  mock_http_status INT NULL,
  input_sha256 NVARCHAR(64) NULL,
  output_sha256 NVARCHAR(64) NULL,
  model_id NVARCHAR(128) NULL,
  input_tokens INT NULL,
  output_tokens INT NULL,
  shadow_narrative NVARCHAR(MAX) NULL,
  shadow_safety_status NVARCHAR(32) NULL,
  event NVARCHAR(64) NULL,
  prev_hash NVARCHAR(64) NULL,
  event_hash NVARCHAR(64) NULL
);
GO

IF OBJECT_ID(N'trace.trg_trace_events_no_update', N'TR') IS NULL
EXEC(N'
CREATE TRIGGER trace.trg_trace_events_no_update ON trace.trace_events
INSTEAD OF UPDATE AS
BEGIN
  RAISERROR(''trace_events is append-only'', 16, 1);
  ROLLBACK TRANSACTION;
END');
GO

IF OBJECT_ID(N'trace.trg_trace_events_no_delete', N'TR') IS NULL
EXEC(N'
CREATE TRIGGER trace.trg_trace_events_no_delete ON trace.trace_events
INSTEAD OF DELETE AS
BEGIN
  RAISERROR(''trace_events is append-only'', 16, 1);
  ROLLBACK TRANSACTION;
END');
GO
