if __name__ == '__main__':
    from src.process_name import ensure_process_name
    from src.pyappify_dev import ensure_pyappify_env

    # Outside the PyAppify launcher PYAPPIFY_VERSION is unset; fake a supporting version.
    ensure_pyappify_env()
    ensure_process_name()
    from config import config
    from ok import OK

    config = config
    config['debug'] = True
    # config['click_screenshots_folder'] = "click_screenshots"  # debug用 点击后截图文件夹]
    ok = OK(config)
    ok.start()
