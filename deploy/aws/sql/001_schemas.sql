-- Four schemas for the FNOL SQL Server database.
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'enterprise') EXEC(N'CREATE SCHEMA [enterprise]');
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'input') EXEC(N'CREATE SCHEMA [input]');
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'output') EXEC(N'CREATE SCHEMA [output]');
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'trace') EXEC(N'CREATE SCHEMA [trace]');
GO
