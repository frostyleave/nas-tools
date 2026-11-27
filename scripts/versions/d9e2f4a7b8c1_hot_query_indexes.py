"""为高频查询补充索引

RSS_MOVIES.TMDBID、RSS_HISTORY.TMDBID/SEASON、TRANSFER_HISTORY.TMDBID、
DOWNLOAD_HISTORY(DOWNLOADER, DOWNLOAD_ID) 在搜索、订阅判断与转移记录查询中被频繁过滤。

Revision ID: d9e2f4a7b8c1
Revises: b7f4d2c9a1e3
Create Date: 2026-11-26 10:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'd9e2f4a7b8c1'
down_revision = 'b7f4d2c9a1e3'
branch_labels = None
depends_on = None


INDEXES = [
    ("ix_RSS_MOVIES_TMDBID", "RSS_MOVIES", '"TMDBID"'),
    ("ix_RSS_HISTORY_TMDBID", "RSS_HISTORY", '"TMDBID"'),
    ("ix_RSS_HISTORY_SEASON", "RSS_HISTORY", '"SEASON"'),
    ("ix_TRANSFER_HISTORY_TMDBID", "TRANSFER_HISTORY", '"TMDBID"'),
    ("ix_DOWNLOAD_HISTORY_DOWNLOADER_DOWNLOAD_ID", "DOWNLOAD_HISTORY",
     '"DOWNLOADER", "DOWNLOAD_ID"'),
]


def _table_exists(conn, table):
    return bool(conn.exec_driver_sql(f'PRAGMA table_info("{table}")').fetchall())


def upgrade() -> None:
    conn = op.get_bind()
    for name, table, columns in INDEXES:
        if not _table_exists(conn, table):
            continue
        conn.exec_driver_sql(
            f'CREATE INDEX IF NOT EXISTS "{name}" ON "{table}" ({columns})')


def downgrade() -> None:
    pass
