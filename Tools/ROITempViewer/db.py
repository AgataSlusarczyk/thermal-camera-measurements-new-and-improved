import psycopg2
import pandas as pd
from datetime import timezone


def _ensure_aware_utc(dt):
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class DatabaseClient:

    def __init__(self, conn_str: str):
        self.conn_str = conn_str

    # SESSIONS

    def get_sessions(self):
        q = """
        SELECT session_id, started_utc, ended_utc, aborted
        FROM public.sessions
        ORDER BY started_utc DESC;
        """
        with psycopg2.connect(self.conn_str) as conn:
            with conn.cursor() as cur:
                cur.execute(q)
                rows = cur.fetchall()

        sessions = []
        for row in rows:
            session_id, started_utc, ended_utc, aborted = row
            started_utc = _ensure_aware_utc(started_utc)
            ended_utc = _ensure_aware_utc(ended_utc)
            sessions.append(
                {
                    "session_id": str(session_id),
                    "started_utc": started_utc,
                    "ended_utc": ended_utc,
                    "aborted": aborted,
                }
            )
        return sessions

    def delete_session(self, session_id: str):
        with psycopg2.connect(self.conn_str) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM public.samples WHERE session_id = %s;",
                    (session_id,),
                )
                cur.execute(
                    "DELETE FROM public.sessions WHERE session_id = %s;",
                    (session_id,),
                )
            conn.commit()

    def get_db_size_pretty(self) -> str:
        q = "SELECT pg_size_pretty(pg_database_size(current_database())) AS size;"
        with psycopg2.connect(self.conn_str) as conn:
            with conn.cursor() as cur:
                cur.execute(q)
                row = cur.fetchone()
        return row[0] if row else "?"

    # SAMPLES

    def get_samples(
        self,
        session_id: str,
        start_s: int | None = None,
        end_s: int | None = None,
        columns=("t_s", "temp_r1", "temp_r2", "temp_r3"),
    ) -> pd.DataFrame:
        base_q = f"""
        SELECT {", ".join(columns)}
        FROM public.samples
        WHERE session_id = %s
        """
        params = [session_id]

        if start_s is not None:
            base_q += " AND t_s >= %s"
            params.append(start_s)
        if end_s is not None and end_s > 0:
            base_q += " AND t_s <= %s"
            params.append(end_s)

        base_q += " ORDER BY t_s ASC;"

        with psycopg2.connect(self.conn_str) as conn:
            df = pd.read_sql(base_q, conn, params=tuple(params))

        for col in ("t_s", "temp_r1", "temp_r2", "temp_r3"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        return df
