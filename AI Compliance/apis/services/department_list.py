"""Department names for UI dropdowns — fixed whitelist from `department_catalog` only."""

_CATALOG_ORDER_SQL = """
SELECT name FROM department_catalog
ORDER BY
  CASE name
    WHEN 'Marketing' THEN 1
    WHEN 'Compliance' THEN 2
    WHEN 'Super Admin' THEN 3
    WHEN 'SME Department' THEN 4
    ELSE 99
  END,
  name
"""


async def fetch_all_department_names(db) -> list[str]:
    rows = await db.fetch(_CATALOG_ORDER_SQL)
    return [str(r["name"]) for r in rows]
