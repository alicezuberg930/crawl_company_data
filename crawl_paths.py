from pathlib import Path


CRAWL_DATA_DIR = Path("crawl_data")


def crawl_data_path(name: str) -> Path:
    return CRAWL_DATA_DIR / name


def resolve_json_path(path: Path) -> Path:
    if (
        path.is_absolute()
        or path.parent != Path(".")
        or path.suffix.lower() != ".json"
    ):
        return path
    return crawl_data_path(path.name)
