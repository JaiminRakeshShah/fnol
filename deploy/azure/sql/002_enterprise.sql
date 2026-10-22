-- Mock / enterprise ledger (reviews, records, idempotency, audit).
IF OBJECT_ID(N'enterprise.reviews', N'U') IS NULL
CREATE TABLE enterprise.reviews (
  id NVARCHAR(64) NOT NULL PRIMARY KEY,
  case_id NVARCHAR(64) NOT NULL,
  draft NVARCHAR(MAX) NOT NULL,
  hash NVARCHAR(64) NOT NULL,
  status NVARCHAR(32) NOT NULL,
  reviewer NVARCHAR(256) NULL
);

IF OBJECT_ID(N'enterprise.records', N'U') IS NULL
CREATE TABLE enterprise.records (
  id NVARCHAR(64) NOT NULL PRIMARY KEY,
  case_id NVARCHAR(64) NOT NULL UNIQUE,
  draft NVARCHAR(MAX) NOT NULL,
  review_id NVARCHAR(64) NOT NULL
);

IF OBJECT_ID(N'enterprise.keys', N'U') IS NULL
CREATE TABLE enterprise.keys (
  [key] NVARCHAR(128) NOT NULL PRIMARY KEY,
  hash NVARCHAR(64) NOT NULL,
  response NVARCHAR(MAX) NOT NULL
);

IF OBJECT_ID(N'enterprise.calls', N'U') IS NULL
CREATE TABLE enterprise.calls (
  case_id NVARCHAR(64) NOT NULL,
  tool NVARCHAR(64) NOT NULL,
  n INT NOT NULL,
  PRIMARY KEY (case_id, tool)
);

IF OBJECT_ID(N'enterprise.audit', N'U') IS NULL
CREATE TABLE enterprise.audit (
  seq INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
  at NVARCHAR(64) NOT NULL,
  event NVARCHAR(64) NOT NULL,
  case_id NVARCHAR(64) NULL,
  detail NVARCHAR(MAX) NULL
);
GO
