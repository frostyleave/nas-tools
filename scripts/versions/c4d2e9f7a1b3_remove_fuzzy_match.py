"""移除模糊匹配订阅字段

模糊匹配功能已下线，清理相关的历史订阅数据并删除 FUZZY_MATCH 字段。

Revision ID: c4d2e9f7a1b3
Revises: a19a48dbb41b
Create Date: 2026-11-05 20:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'c4d2e9f7a1b3'
down_revision = 'a19a48dbb41b'
branch_labels = None
depends_on = None


def _has_column(conn, table, column):
    try:
        rows = conn.exec_driver_sql(f'PRAGMA table_info("{table}")').fetchall()
    except Exception:
        return False
    return any(row[1] == column for row in rows)


def upgrade() -> None:
    conn = op.get_bind()
    # 模糊匹配订阅没有 TMDBID，正常订阅必然带有 TMDBID；
    # 删除这些已经无法继续处理的订阅，避免其一直停留在 RSS 状态
    # FUZZY_MATCH 列在首次执行后即被删除，后续启动时按列是否存在拼接条件
    for table in ("RSS_MOVIES", "RSS_TVS"):
        condition = "TMDBID IS NULL OR TRIM(TMDBID) = ''"
        if _has_column(conn, table, "FUZZY_MATCH"):
            condition = f"FUZZY_MATCH = 1 OR {condition}"
        try:
            conn.exec_driver_sql(f'DELETE FROM "{table}" WHERE {condition}')
        except Exception:
            pass
    for table in ("RSS_MOVIES", "RSS_TVS"):
        if not _has_column(conn, table, "FUZZY_MATCH"):
            continue
        try:
            with op.batch_alter_table(table) as batch_op:
                batch_op.drop_column('FUZZY_MATCH')
        except Exception:
            pass


def downgrade() -> None:
    pass
