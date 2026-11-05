import os

os.environ["PYAPPIFY_PYTHON_TEST"] = "1"
# Outside the PyAppify launcher PYAPPIFY_VERSION is unset, and get_version_list() rejects
# that before it reaches its test-mode mock. Pretend to be a version that supports checks.
os.environ.setdefault("PYAPPIFY_VERSION", "1.2.2")
if __name__ == '__main__':
    from config import config
    from ok import OK

    config = config
    config['debug'] = True
    # config['click_screenshots_folder'] = "click_screenshots"  # debug用 点击后截图文件夹]
    ok = OK(config)
    ok.start()
