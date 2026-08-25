import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.ai_fleet.storage.migrations import AGENT_COLUMNS, MIGRATIONS, Migration, MigrationRunner


class MigrationRunnerTests(unittest.TestCase):
    def create_legacy_database(self, path: Path):
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE agents (id TEXT PRIMARY KEY, name TEXT NOT NULL, cli_command TEXT NOT NULL, is_installed BOOLEAN DEFAULT 0, status TEXT DEFAULT 'ready')")
        connection.execute("INSERT INTO agents(id, name, cli_command, is_installed, status) VALUES ('legacy', 'Legacy Agent', 'legacy.exe', 1, 'ready')")
        connection.execute("CREATE TABLE task_runs (id TEXT PRIMARY KEY, prompt TEXT NOT NULL)")
        connection.execute("CREATE TABLE models (id TEXT PRIMARY KEY, name TEXT NOT NULL, provider TEXT NOT NULL)")
        connection.execute("INSERT INTO models(id, name, provider) VALUES ('legacy-model', 'Legacy Model', 'catalog')")
        connection.commit()
        connection.close()

    def test_legacy_upgrade_preserves_data_and_adds_agent_schema(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "legacy.db"
            self.create_legacy_database(path)
            applied = MigrationRunner(path).migrate()
            connection = sqlite3.connect(path)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(agents)")}
            agent = connection.execute("SELECT name, cli_command FROM agents WHERE id='legacy'").fetchone()
            model = connection.execute("SELECT registry_state, availability_state, capability_provenance FROM models WHERE id='legacy-model'").fetchone()
            versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]
            connection.close()

        self.assertEqual(applied, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41])
        self.assertTrue(set(AGENT_COLUMNS) <= columns)
        self.assertEqual(agent, ("Legacy Agent", "legacy.exe"))
        self.assertEqual(model, ("catalog", "unknown", "unknown"))
        self.assertEqual(versions, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41])

    def test_migrations_are_idempotent_and_backup_is_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fleet.db"
            self.create_legacy_database(path)
            runner = MigrationRunner(path, backup_limit=1)
            self.assertEqual(runner.migrate(), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41])
            self.assertEqual(runner.migrate(), [])
            backups = list((path.parent / "backups").glob("*.db"))
            self.assertLessEqual(len(backups), 1)
            metadata = json.loads((path.parent / "migration-recovery.json").read_text())
            self.assertEqual(metadata["state"], "completed")

    def test_failed_migration_restores_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "failure.db"
            self.create_legacy_database(path)
            original = path.read_bytes()

            def fail(connection):
                connection.execute("ALTER TABLE agents ADD COLUMN transient TEXT")
                raise RuntimeError("injected failure")

            import core.ai_fleet.storage.migrations as module

            existing = module.MIGRATIONS
            module.MIGRATIONS = [Migration(99, "failure_injection", fail)]
            try:
                with self.assertRaises(RuntimeError):
                    MigrationRunner(path).migrate()
            finally:
                module.MIGRATIONS = existing
            connection = sqlite3.connect(path)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(agents)")}
            connection.close()
            metadata = json.loads((path.parent / "migration-recovery.json").read_text())

        self.assertNotIn("transient", columns)
        self.assertEqual(metadata["state"], "restored_after_failure")
        self.assertTrue(original)


if __name__ == "__main__":
    unittest.main()
