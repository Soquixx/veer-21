"""One shared FILE database for every test. The solver runs in a separate (spawned) process, so an
in-memory database would be invisible to it. Env vars are set before backend.settings is imported."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="airops-test-")
os.environ["AIROPS_DATABASE_URL"] = "sqlite+pysqlite:///" + os.path.join(_tmp, "test.db").replace("\\", "/")
os.environ["AIROPS_JWT_SECRET"] = "test-secret-" + "x" * 40
os.environ["AIROPS_ENVIRONMENT"] = "development"
