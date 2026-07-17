from pathlib import Path

from yt_forensics import runtime_paths


def test_default_config_path_exists_in_dev():
    path = runtime_paths.default_config_path()
    assert path.is_file()
    assert path.name == "settings.yaml"


def test_dashboard_static_dir_exists_in_dev():
    static = runtime_paths.dashboard_static_dir()
    assert static.is_dir()
    assert (static / "index.html").is_file() or any(static.iterdir())


def test_app_root_points_at_repo_in_dev():
    root = runtime_paths.app_root()
    assert (root / "config" / "settings.yaml").is_file() or (root / "src").is_dir()
