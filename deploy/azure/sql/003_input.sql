IF OBJECT_ID(N'input.input_revisions', N'U') IS NULL
CREATE TABLE input.input_revisions (
  case_id NVARCHAR(64) NOT NULL,
  revision INT NOT NULL,
  ingested_at NVARCHAR(64) NOT NULL,
  document_set_sha256 NVARCHAR(64) NOT NULL,
  trace_id NVARCHAR(64) NULL,
  intake_source NVARCHAR(256) NULL,
  account_text NVARCHAR(MAX) NULL,
  incident_timestamp NVARCHAR(64) NULL,
  policy_number NVARCHAR(64) NULL,
  vehicle_id NVARCHAR(64) NULL,
  loss_type NVARCHAR(64) NULL,
  driver_name NVARCHAR(256) NULL,
  driver_name_supplied INT NULL,
  incident_location NVARCHAR(512) NULL,
  incident_location_supplied INT NULL,
  injury_reported_raw NVARCHAR(64) NULL,
  injury_reported INT NULL,
  vehicle_drivable_raw NVARCHAR(64) NULL,
  vehicle_drivable INT NULL,
  referral_indicator NVARCHAR(128) NULL,
  loss_reference NVARCHAR(128) NULL,
  intake_sha256 NVARCHAR(64) NULL,
  raw_intake NVARCHAR(MAX) NULL,
  intake_notes NVARCHAR(MAX) NULL,
  estimate_source_id NVARCHAR(128) NULL,
  estimate_sha256 NVARCHAR(64) NULL,
  estimate_reference NVARCHAR(128) NULL,
  estimate_vehicle NVARCHAR(128) NULL,
  repair_amount NVARCHAR(64) NULL,
  estimate_prepared_by NVARCHAR(256) NULL,
  estimate_notes NVARCHAR(MAX) NULL,
  raw_estimate NVARCHAR(MAX) NULL,
  report_source_id NVARCHAR(128) NULL,
  report_sha256 NVARCHAR(64) NULL,
  report_vehicle_reference NVARCHAR(128) NULL,
  report_incident_timestamp NVARCHAR(64) NULL,
  reported_loss_type NVARCHAR(64) NULL,
  report_notes NVARCHAR(MAX) NULL,
  raw_report NVARCHAR(MAX) NULL,
  repeated_fields NVARCHAR(MAX) NULL,
  extra_fields NVARCHAR(MAX) NULL,
  injection_field_status NVARCHAR(32) NULL,
  injection_model_status NVARCHAR(32) NULL,
  CONSTRAINT PK_input_revisions PRIMARY KEY (case_id, revision)
);
GO

IF COL_LENGTH(N'input.input_revisions', N'extra_fields') IS NULL
ALTER TABLE input.input_revisions ADD extra_fields NVARCHAR(MAX) NULL;
IF COL_LENGTH(N'input.input_revisions', N'injection_field_status') IS NULL
ALTER TABLE input.input_revisions ADD injection_field_status NVARCHAR(32) NULL;
IF COL_LENGTH(N'input.input_revisions', N'injection_model_status') IS NULL
ALTER TABLE input.input_revisions ADD injection_model_status NVARCHAR(32) NULL;
GO

IF OBJECT_ID(N'input.trg_input_revisions_no_update', N'TR') IS NULL
EXEC(N'
CREATE TRIGGER input.trg_input_revisions_no_update ON input.input_revisions
INSTEAD OF UPDATE AS
BEGIN
  RAISERROR(''input_revisions is append-only'', 16, 1);
  ROLLBACK TRANSACTION;
END');
GO

IF OBJECT_ID(N'input.trg_input_revisions_no_delete', N'TR') IS NULL
EXEC(N'
CREATE TRIGGER input.trg_input_revisions_no_delete ON input.input_revisions
INSTEAD OF DELETE AS
BEGIN
  RAISERROR(''input_revisions is append-only'', 16, 1);
  ROLLBACK TRANSACTION;
END');
GO

IF OBJECT_ID(N'input.procedure_sources', N'U') IS NULL
CREATE TABLE input.procedure_sources (
  source_id NVARCHAR(128) NOT NULL PRIMARY KEY,
  sha256 NVARCHAR(64) NOT NULL,
  loaded_at NVARCHAR(64) NOT NULL
);

IF OBJECT_ID(N'input.tool_payloads', N'U') IS NULL
CREATE TABLE input.tool_payloads (
  case_id NVARCHAR(64) NOT NULL,
  input_revision INT NOT NULL,
  tool NVARCHAR(64) NOT NULL,
  raw_json NVARCHAR(MAX) NOT NULL,
  sha256 NVARCHAR(64) NOT NULL,
  stored_at NVARCHAR(64) NOT NULL,
  PRIMARY KEY (case_id, input_revision, tool)
);
GO

IF OBJECT_ID(N'input.trg_tool_payloads_no_update', N'TR') IS NULL
EXEC(N'
CREATE TRIGGER input.trg_tool_payloads_no_update ON input.tool_payloads
INSTEAD OF UPDATE AS
BEGIN
  RAISERROR(''tool_payloads is append-only'', 16, 1);
  ROLLBACK TRANSACTION;
END');
GO

IF OBJECT_ID(N'input.trg_tool_payloads_no_delete', N'TR') IS NULL
EXEC(N'
CREATE TRIGGER input.trg_tool_payloads_no_delete ON input.tool_payloads
INSTEAD OF DELETE AS
BEGIN
  RAISERROR(''tool_payloads is append-only'', 16, 1);
  ROLLBACK TRANSACTION;
END');
GO

IF OBJECT_ID(N'input.decisions', N'U') IS NULL
CREATE TABLE input.decisions (
  case_id NVARCHAR(64) NOT NULL,
  input_revision INT NOT NULL,
  kind NVARCHAR(32) NOT NULL,
  body_json NVARCHAR(MAX) NOT NULL,
  policy_sha256 NVARCHAR(64) NULL,
  claims_sha256 NVARCHAR(64) NULL,
  stored_at NVARCHAR(64) NOT NULL,
  PRIMARY KEY (case_id, input_revision, kind)
);
GO

IF OBJECT_ID(N'input.trg_decisions_no_update', N'TR') IS NULL
EXEC(N'
CREATE TRIGGER input.trg_decisions_no_update ON input.decisions
INSTEAD OF UPDATE AS
BEGIN
  RAISERROR(''decisions is append-only'', 16, 1);
  ROLLBACK TRANSACTION;
END');
GO

IF OBJECT_ID(N'input.trg_decisions_no_delete', N'TR') IS NULL
EXEC(N'
CREATE TRIGGER input.trg_decisions_no_delete ON input.decisions
INSTEAD OF DELETE AS
BEGIN
  RAISERROR(''decisions is append-only'', 16, 1);
  ROLLBACK TRANSACTION;
END');
GO
