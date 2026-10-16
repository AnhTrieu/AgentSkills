import pandas as pd
from sqlalchemy import create_engine


def sync_csv(path, database_url):
    rows = pd.read_csv(path)
    rows.to_sql('exports', create_engine(database_url), if_exists='append', index=False)
    return len(rows)
