from neo4j import GraphDatabase

from . import config

_driver = None


def get_driver():
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))
    return _driver


def close_driver():
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


def read(fn, *args, **kwargs):
    with get_driver().session(database=config.NEO4J_DATABASE) as s:
        return s.execute_read(fn, *args, **kwargs)


def write(fn, *args, **kwargs):
    with get_driver().session(database=config.NEO4J_DATABASE) as s:
        return s.execute_write(fn, *args, **kwargs)


def ping():
    try:
        get_driver().verify_connectivity()
        return True, None
    except Exception as e:  # noqa: BLE001 - we want to report any connection problem
        return False, str(e)


def rows(tx, query, **params):
    """Run a query and return a list of plain dicts."""
    return tx.run(query, **params).data()
