#!/usr/bin/env python3
"""Local mirror + profile query for the RDS `job_registry` jobs DB.

Run with a Postgres driver available, e.g.:
    uv run --with 'psycopg[binary]' python jobs.py <schema|sync|query>

Subcommands:
    schema  - introspect the RDS jobs DB (tables, columns, chosen jobs table)
    sync    - incremental top-up of the local mirror from RDS (watermark-based)
    query   - profile filter over the local mirror -> relevant_jobs.csv

Config comes from a sibling .env file:
    RDS_DSN=postgresql://...@.../job_registry?sslmode=require
    LOCAL_DSN=postgresql://postgres:localjobs@127.0.0.1:5433/job_registry
The one-time full clone is done with pg_dump | psql (see README.md), which
creates the schema + all rows locally; sync/query operate on that.
"""
import os, sys, csv, pathlib

HERE = pathlib.Path(__file__).parent


def load_env():
    envf = HERE / ".env"
    if not envf.exists():
        return
    for line in envf.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


load_env()
SRC = os.environ.get("RDS_DSN")     # source: RDS job_registry
DST = os.environ.get("LOCAL_DSN")   # dest:   local Docker Postgres mirror

import psycopg  # noqa: E402  (after load_env so a missing driver message is clear)

JOBWORDS = ("job", "listing", "posting", "vacanc", "opportunit",
            "position", "opening", "gig", "req")


def _tables(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT table_schema, table_name FROM information_schema.tables
            WHERE table_type='BASE TABLE'
              AND table_schema NOT IN ('pg_catalog','information_schema')
            ORDER BY 1,2;
        """)
        return cur.fetchall()


def _columns(conn, s, n):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position;
        """, (s, n))
        return cur.fetchall()


def _count(conn, s, n):
    with conn.cursor() as cur:
        cur.execute(f'SELECT count(*) FROM "{s}"."{n}";')
        return cur.fetchone()[0]


def _pick_jobs_table(conn):
    """Prefer the normalized jobs table (has a `title` column) over raw/staging."""
    best = None
    for s, n in _tables(conn):
        colnames = [c.lower() for c, _ in _columns(conn, s, n)]
        has_title = 1 if "title" in colnames else 0
        jobword = 1 if any(w in n.lower() for w in JOBWORDS) else 0
        not_raw = 0 if any(x in n.lower() for x in ("raw", "staging", "_tmp", "_stg")) else 1
        sc = (has_title, jobword, not_raw, _count(conn, s, n))
        if best is None or sc > best[0]:
            best = (sc, (s, n))
    return best[1]


def _pk_column(conn, s, n):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT a.attname FROM pg_index i
            JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = %s::regclass AND i.indisprimary;
        """, (f'"{s}"."{n}"',))
        r = cur.fetchall()
        return r[0][0] if r else None


def _watermark_col(cols, pk):
    names = [c for c, _ in cols]
    # ingestion-time columns first (monotonic for incremental sync); posted last
    for key in ("date_created", "created_at", "created", "ingested", "fetched",
                "normalized", "inserted", "date_posted", "posted", "published"):
        for c in names:
            if key in c.lower():
                return c
    return pk


def cmd_schema():
    with psycopg.connect(SRC, connect_timeout=20) as conn:
        for s, n in _tables(conn):
            print(f"\n-- {s}.{n} ({_count(conn, s, n)} rows)")
            for c, t in _columns(conn, s, n):
                print(f"     {c}: {t}")
        s, n = _pick_jobs_table(conn)
        cols = _columns(conn, s, n)
        pk = _pk_column(conn, s, n)
        print(f"\nMAIN JOBS TABLE: {s}.{n}")
        print(f"  primary key : {pk}")
        print(f"  watermark   : {_watermark_col(cols, pk)}")


def cmd_sync(batch=5000):
    with psycopg.connect(SRC) as src, psycopg.connect(DST) as dst:
        s, n = _pick_jobs_table(src)
        cols = _columns(src, s, n)
        colnames = [c for c, _ in cols]
        pk = _pk_column(src, s, n)
        if not pk:
            sys.exit(f"no primary key on {s}.{n}; cannot upsert safely")
        wm = _watermark_col(cols, pk)
        with dst.cursor() as dc:
            dc.execute(f'SELECT max("{wm}") FROM "{s}"."{n}";')
            last = dc.fetchone()[0]
        print(f"jobs table {s}.{n}; pk={pk}; watermark={wm}; local max={last}")

        collist = ",".join(f'"{c}"' for c in colnames)
        placeholders = ",".join(["%s"] * len(colnames))
        setlist = ",".join(f'"{c}"=EXCLUDED."{c}"' for c in colnames if c != pk)
        upsert = (f'INSERT INTO "{s}"."{n}" ({collist}) VALUES ({placeholders}) '
                  f'ON CONFLICT ("{pk}") DO UPDATE SET {setlist}')
        where = f'WHERE "{wm}" > %s' if last is not None else ""
        params = (last,) if last is not None else ()

        total = 0
        with src.cursor(name="sync_src") as sc:
            sc.itersize = batch
            sc.execute(f'SELECT {collist} FROM "{s}"."{n}" {where} ORDER BY "{wm}" ASC', params)
            buf = []
            with dst.cursor() as dc:
                for row in sc:
                    buf.append(row)
                    if len(buf) >= batch:
                        dc.executemany(upsert, buf)
                        dst.commit()
                        total += len(buf)
                        buf = []
                        print(f"  ...{total}")
                if buf:
                    dc.executemany(upsert, buf)
                    dst.commit()
                    total += len(buf)
        print(f"synced {total} new/updated rows")


# ---- profile filter (tune after `schema` confirms column names) ----
# NOTE: these run under Postgres regex (~*), where \y is a word boundary (\b is backspace).
INCLUDE = (r"(software|engineer|developer|backend|back[- ]?end|full[- ]?stack|"
           r"frontend|front[- ]?end|\ysde\y|\yml\y|machine learning|\yai\y|"
           r"react native|mobile developer|data engineer|platform engineer)")
EXCLUDE = (r"(senior|staff|principal|\ylead\y|director|head of|\yvp\y|"
           r"vice president|architect|manager|10\+|[89]\+ years|"
           r"facilities|field engineer|quality engineer|mechanical|electrical|"
           r"civil|chemical|biomedical|hardware|manufacturing|sales engineer|"
           r"data center|lab automation|process engineer|network engineer|"
           r"validation engineer|test engineer|controls engineer)")
NOSPONSOR = (r"(no sponsorship|not able to sponsor|will not sponsor|no visa|"
             r"without sponsorship|must be a us citizen|security clearance)")
SENIORITY_BAD = r"(senior|staff|principal|lead|director|executive|manager)"
# Harsh's stack (for fit ranking). Short tokens use \y word boundaries (Postgres).
STACK = ["typescript", "javascript", "python", "react native", "reactjs", "react",
         "next", "node", "nestjs", "fastapi", "express", "graphql", "grpc", "kafka",
         "postgres", "mongo", "redis", "dynamodb", "aws", "docker", "kubernetes",
         "terraform", "pulumi", "langchain", "qdrant", "bedrock", "electron", "bazel",
         r"\ygo\y", r"\yrag\y", r"\yml\y", r"\yai\y"]
CANADA_REMOTE = (r"(canada|ontario|british columbia|vancouver|toronto|kelowna|"
                 r"remote|anywhere|work from home)")
# Hard blockers for a Canadian who cannot get US clearance/citizenship.
CLEARANCE = (r"(clearance|polygraph|ts/sci|\ytop secret\y|\ysecret\y|"
             r"u\.?s\.? citizen|citizenship required|must be a citizen|"
             r"green card|gc holder)")
# Eligibility for a Canada-authorized candidate (no US sponsorship). See
# work-auth memory: US-remote-no-sponsor roles empirically reject him.
ELIGIBLE_GEO = (r"(canada|worldwide|world wide|everywhere|anywhere|"
                r"other countries|north america|globally|global remote|latam|emea)")
US_ONLY = (r"(u\.?s\.? citizen|american citizen|authorized to work in the u\.?s|"
           r"authorized to work in the united states|u\.?s\.? work authorization|"
           r"green card|based in the u\.?s|based in the united states|"
           r"work from any (u\.?s\.? )?state|u\.?s\.?-based|located in the united states|"
           r"within the united states|must reside in the u)")


def cmd_query(limit=500, dsn=None):
    with psycopg.connect(dsn or DST) as conn:
        s, n = _pick_jobs_table(conn)
        cols = [c for c, _ in _columns(conn, s, n)]

        def find(*keys):
            for c in cols:
                if any(k in c.lower() for k in keys):
                    return c
            return None

        title = find("title", "job_title")
        company = find("organization", "company", "employer")
        loc = find("location", "city", "region", "country")
        posted = find("date_posted", "posted", "date_created", "created")
        seniority = find("seniority")
        exp = find("experience_level", "experience")
        visa = find("visa_sponsorship", "sponsor")
        salary = find("salary", "compensation", "pay")
        url = find("url", "link", "apply")

        clauses, params = [], []
        if title:
            clauses.append(f'"{title}" ~* %s'); params.append(INCLUDE)
            clauses.append(f'NOT ("{title}" ~* %s)'); params.append(EXCLUDE)
        if seniority:
            clauses.append(f'COALESCE("{seniority}"::text,\'\') !~* %s'); params.append(SENIORITY_BAD)
        if posted:
            clauses.append(f'"{posted}" >= now() - interval \'30 days\'')
        where = " AND ".join(clauses) if clauses else "TRUE"

        sel = [c for c in (posted, title, company, loc, seniority, exp, visa, salary, url) if c] or cols[:6]
        order = f'"{posted}" DESC NULLS LAST' if posted else "1"
        sel_sql = ",".join(f'"{c}"' for c in sel)
        q = f'SELECT {sel_sql} FROM "{s}"."{n}" WHERE {where} ORDER BY {order} LIMIT {limit}'
        with conn.cursor() as cur:
            cur.execute(q, params)
            rows = cur.fetchall()

        out = HERE / "relevant_jobs.csv"
        with out.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(sel)
            w.writerows(rows)
        print(f"table={s}.{n}  columns={sel}")
        print(f"matched {len(rows)} jobs -> {out}")
        for r in rows[:20]:
            print("  ", " | ".join(str(x)[:50] for x in r))


def cmd_shortlist(dsn=None, limit=25, eligible=False):
    with psycopg.connect(dsn or DST) as conn:
        s, n = _pick_jobs_table(conn)
        cols = [c for c, _ in _columns(conn, s, n)]

        def find(*keys):
            for c in cols:
                if any(k in c.lower() for k in keys):
                    return c
            return None

        title = find("title", "job_title")
        desc = find("description", "summary")
        skills = find("skills")
        loc = find("location", "city", "region")
        posted = find("date_posted", "posted", "date_created", "created")
        seniority = find("seniority")
        org = find("organization", "company", "employer")
        exp = find("experience_level", "experience")
        visa = find("visa_sponsorship", "sponsor")
        salary = find("salary", "compensation")
        url = find("url", "link", "apply")

        text = (f'(coalesce("{title}"::text,\'\')'
                + (f'||\' \'||coalesce("{desc}",\'\')' if desc else '')
                + (f'||\' \'||coalesce(array_to_string("{skills}",\' \'),\'\')' if skills else '')
                + ')')
        score_terms = "+".join([f"({text} ~* %s)::int" for _ in STACK])
        loc_bonus = f'(coalesce("{loc}"::text,\'\') ~* %s)::int*3' if loc else "0"
        score_expr = f"({score_terms})+{loc_bonus}"
        sel_params = list(STACK) + ([CANADA_REMOTE] if loc else [])

        clauses, fparams = [], []
        if title:
            clauses.append(f'"{title}" ~* %s'); fparams.append(INCLUDE)
            clauses.append(f'NOT ("{title}" ~* %s)'); fparams.append(EXCLUDE)
        if seniority:
            clauses.append(f'COALESCE("{seniority}"::text,\'\') !~* %s'); fparams.append(SENIORITY_BAD)
        clauses.append(f'NOT ({text} ~* %s)'); fparams.append(CLEARANCE)   # drop clearance-gated roles
        if eligible:
            elig = []
            if visa:
                elig.append(f'"{visa}" = true')                            # employer sponsors (reliable)
            if loc:
                elig.append(f'"{loc}"::text ~* \'canada\'')                # or the role is in Canada
            if elig:
                clauses.append("(" + " OR ".join(elig) + ")")
            if desc:                                                       # still drop explicit US-only auth
                clauses.append(f'COALESCE("{desc}",\'\') !~* %s'); fparams.append(US_ONLY)
        if posted:
            clauses.append(f'"{posted}" >= now() - interval \'30 days\'')
        where = " AND ".join(clauses) if clauses else "TRUE"

        fp = find("fingerprint")
        summary = [c for c in (posted, title, org, loc, seniority, exp, visa, salary, url) if c]
        allcols = summary + [c for c in (desc, fp) if c and c not in summary]
        sel_sql = ",".join(f'"{c}"' for c in allcols)
        order = f'fit DESC, "{posted}" DESC NULLS LAST' if posted else "fit DESC"
        # over-fetch, then dedup to `limit` unique roles
        q = (f'SELECT {score_expr} AS fit, {sel_sql} FROM "{s}"."{n}" '
             f'WHERE {where} ORDER BY {order} LIMIT {limit * 6}')
        with conn.cursor() as cur:
            cur.execute(q, sel_params + fparams)
            raw = cur.fetchall()

        names = ["fit"] + allcols
        ix = {c: names.index(c) for c in names}
        seen, uniq = set(), []
        for row in raw:
            key = (row[ix[fp]] if fp and row[ix[fp]]
                   else (str(row[ix[title]]).lower(), str(row[ix[org]]).lower()))
            if key in seen:
                continue
            seen.add(key)
            uniq.append(row)
            if len(uniq) >= limit:
                break

        csv_cols = ["fit"] + summary
        cidx = [ix[c] for c in csv_cols]
        out = HERE / "shortlist_top25.csv"
        with out.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(csv_cols)
            for row in uniq:
                w.writerow([row[i] for i in cidx])

        import json
        jobs = []
        for row in uniq:
            jobs.append({
                "fit_signal": row[0],
                "title": row[ix[title]] if title else None,
                "organization": row[ix[org]] if org else None,
                "location": row[ix[loc]] if loc else None,
                "seniority": row[ix[seniority]] if seniority else None,
                "experience_level": row[ix[exp]] if exp else None,
                "visa_sponsorship": row[ix[visa]] if visa else None,
                "salary": row[ix[salary]] if salary else None,
                "url": row[ix[url]] if url else None,
                "description": (str(row[ix[desc]])[:2500] if desc and row[ix[desc]] else ""),
            })
        jout = HERE / "top25.json"
        jout.write_text(json.dumps(jobs, default=str, indent=1))
        print(f"unique top {len(uniq)} -> {out} + {jout}\n")
        for row in uniq:
            print("  ", " | ".join(str(row[i])[:44] for i in cidx))


def cmd_count(dsn=None):
    with psycopg.connect(dsn or DST) as conn:
        s, n = _pick_jobs_table(conn)
        cols = [c for c, _ in _columns(conn, s, n)]

        def find(*keys):
            for c in cols:
                if any(k in c.lower() for k in keys):
                    return c
            return None

        title = find("title", "job_title")
        seniority = find("seniority")
        posted = find("date_posted", "posted", "date_created", "created")

        clauses, params = [], []
        if title:
            clauses.append(f'"{title}" ~* %s'); params.append(INCLUDE)
            clauses.append(f'NOT ("{title}" ~* %s)'); params.append(EXCLUDE)
        if seniority:
            clauses.append(f'COALESCE("{seniority}"::text,\'\') !~* %s'); params.append(SENIORITY_BAD)
        where = " AND ".join(clauses) if clauses else "TRUE"

        with conn.cursor() as cur:
            total = _count(conn, s, n)
            cur.execute(f'SELECT count(*) FROM "{s}"."{n}" WHERE {where}', params)
            match_all = cur.fetchone()[0]
            match_30 = None
            if posted:
                cur.execute(f'SELECT count(*) FROM "{s}"."{n}" '
                            f'WHERE {where} AND "{posted}" >= now() - interval \'30 days\'', params)
                match_30 = cur.fetchone()[0]
        print(f"table={s}.{n}")
        print(f"total rows                 : {total}")
        print(f"profile matches (all time) : {match_all}")
        print(f"profile matches (30 days)  : {match_30}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "schema"
    if cmd in ("schema", "sync") and not SRC:
        sys.exit("RDS_DSN not set in .env")
    if cmd in ("sync", "query") and not DST:
        sys.exit("LOCAL_DSN not set in .env")
    dispatch = {"schema": cmd_schema, "sync": cmd_sync, "query": cmd_query,
                "count": cmd_count, "shortlist": cmd_shortlist, "eligible": cmd_shortlist}
    if cmd not in dispatch:
        sys.exit(f"unknown command {cmd!r}; use: schema | sync | query | count | shortlist | eligible")
    use_rds = len(sys.argv) > 2 and sys.argv[2] == "rds"
    lim = next((int(a) for a in sys.argv[2:] if a.isdigit()), None)
    if cmd == "query":
        cmd_query(limit=lim or 500, dsn=SRC if use_rds else None)
    elif cmd in ("shortlist", "eligible"):
        cmd_shortlist(dsn=SRC if use_rds else None, limit=lim or 25, eligible=(cmd == "eligible"))
    elif cmd == "count" and use_rds:
        cmd_count(dsn=SRC)
    else:
        dispatch[cmd]()
