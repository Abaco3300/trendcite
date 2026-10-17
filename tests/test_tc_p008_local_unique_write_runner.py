"""Local proof runner must reject non-disposable database targets."""

import pytest
from scripts.tc_p008_local_unique_write import run_local


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://postgres@remote.example.com/tc_p008_local",
        "postgresql://postgres@127.0.0.1/postgres",
        "postgresql://postgres@127.0.0.1/trendcite",
        "host=127.0.0.1 dbname=production",
        "postgresql://postgres@127.0.0.1/tc_p008_local?host=remote.example.com",
        "postgresql://postgres@127.0.0.1/tc_p008_local?dbname=production",
        "postgresql://postgres@127.0.0.1/tc_p008_local?hostaddr=203.0.113.10",
        "postgresql://postgres@127.0.0.1/tc_p008_local#unexpected",
    ],
)
def test_non_disposable_target_rejected_before_sql(dsn: str) -> None:
    with pytest.raises(RuntimeError, match="local loopback DSN"):
        run_local(dsn)
