if __name__ == '__main__':
    from src.process_name import ensure_process_name
    from src.pyappify_dev import ensure_pyappify_env

    ensure_pyappify_env()
    ensure_process_name()
    from config import config
    from ok import OK

    config = config
    ok = OK(config)
    ok.start()
