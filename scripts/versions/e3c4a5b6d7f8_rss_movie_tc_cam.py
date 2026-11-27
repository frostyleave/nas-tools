"""电影订阅增加枪版尝鲜开关

RSS_MOVIES.TC_CAM 为 1 时允许下载 TC-CAM 摄录版本，默认 0 表示排除。

Revision ID: e3c4a5b6d7f8
Revises: d9e2f4a7b8c1
Create Date: 2026-11-27 10:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'e3c4a5b6d7f8'
down_revision = 'd9e2f4a7b8c1'
branch_labels = None
depends_on = None


def _table_info(conn, table):
    return conn.exec_driver_sql(f'PRAGMA table_info("{table}")').fetchall()


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_info(conn, "RSS_MOVIES"):
        return
    columns = {row[1] for row in _table_info(conn, "RSS_MOVIES")}
    if "TC_CAM" not in columns:
        conn.exec_driver_sql(
            'ALTER TABLE "RSS_MOVIES" ADD COLUMN "TC_CAM" INTEGER DEFAULT 0')


def downgrade() -> None:
    pass
