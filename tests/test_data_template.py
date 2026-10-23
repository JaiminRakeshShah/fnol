"""Static checks for the RDS template. No AWS account required."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = (ROOT / "deploy" / "aws" / "data.yaml").read_text()
FOUNDATION = (ROOT / "deploy" / "aws" / "foundation.yaml").read_text()


class DataTemplateTests(unittest.TestCase):
    def test_database_is_private_encrypted_and_backed_up(self):
        self.assertIn("PubliclyAccessible: false", DATA)
        self.assertIn("StorageEncrypted: true", DATA)
        self.assertIn("ManageMasterUserPassword: true", DATA)
        self.assertIn("EnableIAMDatabaseAuthentication: true", DATA)
        self.assertIn("BackupRetentionPeriod:", DATA)
        self.assertIn("MinValue: 7", DATA)
        self.assertNotIn("0.0.0.0/0", DATA)
        self.assertNotRegex(DATA, r"(?m)^\s*MasterUserPassword:")

    def test_multi_az_is_a_parameter(self):
        self.assertIn("MultiAZ:", DATA)
        self.assertIn('Default: "false"', DATA)

    def test_foundation_key_allows_rds_and_secrets(self):
        self.assertIn("AllowRdsInAccount", FOUNDATION)
        self.assertIn("AllowSecretsManager", FOUNDATION)
        self.assertIn("deploy/aws/data.yaml", FOUNDATION)


if __name__ == "__main__":
    unittest.main()
