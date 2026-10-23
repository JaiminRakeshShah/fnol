IF OBJECT_ID(N'output.drafts', N'U') IS NULL
CREATE TABLE output.drafts (
  draft_id NVARCHAR(64) NOT NULL PRIMARY KEY,
  case_id NVARCHAR(64) NOT NULL,
  input_revision INT NULL,
  draft_json NVARCHAR(MAX) NOT NULL,
  draft_hash NVARCHAR(64) NOT NULL,
  status NVARCHAR(32) NOT NULL,
  created_at NVARCHAR(64) NOT NULL,
  review_id NVARCHAR(64) NULL,
  outcome NVARCHAR(64) NULL
);
GO

IF OBJECT_ID(N'output.trg_drafts_body_immutable', N'TR') IS NULL
EXEC(N'
CREATE TRIGGER output.trg_drafts_body_immutable ON output.drafts
AFTER UPDATE AS
BEGIN
  IF UPDATE(draft_json) OR UPDATE(draft_hash)
  BEGIN
    RAISERROR(''draft_json and draft_hash are immutable'', 16, 1);
    ROLLBACK TRANSACTION;
  END
END');
GO
