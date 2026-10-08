"""Phase 5: shared server-side search/sort/pagination for list endpoints.

Pagination is OPT-IN via query params (`page`, `page_size`) — an endpoint
that gets neither keeps returning its full, unpaginated list exactly as
before. Several existing pages (dashboard summaries, borrower/loan
pickers in other forms, the approvals queue) already depend on these same
endpoints returning EVERYTHING; making pagination the default would
silently break them. Only the five pages Phase 5 names (loans, borrowers,
repayments, users, audit log) pass these params at all.
"""
from sqlalchemy import or_

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


def paginate(query, args, searchable=(), sortable=(), default_sort=None):
    """args: a Flask request.args-like mapping.
    searchable: column attributes ILIKE-matched (OR'd) against `q`.
    sortable: {name: column_attribute} map; `sort`/`order` (asc/desc) pick one.
    default_sort: a column attribute (or None) used when `sort` is absent/
    invalid — applied AFTER filtering, since callers often need their own
    dominant ordering otherwise.

    Returns (items, pagination_dict_or_None). pagination is None when
    neither `page` nor `page_size` was supplied — the caller's existing
    unpaginated behaviour (whatever ordering it already applies) is
    preserved untouched in that case.
    """
    q = (args.get("q") or "").strip()
    if q and searchable:
        like = f"%{q}%"
        query = query.filter(or_(*(col.ilike(like) for col in searchable)))

    sort_key = args.get("sort")
    order = (args.get("order") or "asc").lower()
    sort_column = sortable.get(sort_key) if sortable else None
    if sort_column is not None:
        query = query.order_by(sort_column.desc() if order == "desc" else sort_column.asc())
    elif default_sort is not None:
        query = query.order_by(default_sort)

    page_param = args.get("page")
    page_size_param = args.get("page_size")
    if page_param is None and page_size_param is None:
        return query.all(), None

    try:
        page = max(1, int(page_param or 1))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = int(page_size_param or DEFAULT_PAGE_SIZE)
    except (TypeError, ValueError):
        page_size = DEFAULT_PAGE_SIZE
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))

    total = query.order_by(None).count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    total_pages = max(1, (total + page_size - 1) // page_size)
    return items, {"page": page, "page_size": page_size, "total": total, "total_pages": total_pages}
