if __name__ == "__main__":
    from src.process_name import ensure_process_name
    from src.pyappify_dev import ensure_pyappify_env

    ensure_pyappify_env()
    ensure_process_name()
    from config import config
    from ok import OK

    config = config
    config["debug"] = True
    config["gui"] = {
        "type": "web",
        "launch_mode": "pywebview",  # default
    }
    ok = OK(config)
    ok.start()
