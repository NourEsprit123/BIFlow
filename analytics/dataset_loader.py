from pathlib import Path
import pandas as pd


DATA_DIR = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "raw"
)


def list_datasets():
    """Retourne tous les datasets disponibles dans data/raw."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    datasets = []
    datasets.extend(DATA_DIR.glob("*.csv"))
    datasets.extend(DATA_DIR.glob("*.xlsx"))
    datasets.extend(DATA_DIR.glob("*.xls"))

    return sorted(datasets)


def load_dataset(file_path: str) -> pd.DataFrame:
    """Charge un dataset CSV, XLSX ou XLS."""
    if not file_path:
        raise ValueError("Le chemin du fichier est vide.")

    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(
            f"Dataset introuvable : {file_path}"
        )

    extension = file_path.suffix.lower()

    try:
        if extension == ".csv":
            df = pd.read_csv(
                file_path,
                keep_default_na=False
            )

        elif extension in [".xlsx", ".xls"]:
            df = pd.read_excel(file_path)

        else:
            raise ValueError(
                "Format non supporté. Utilisez CSV, XLSX ou XLS."
            )

    except Exception as error:
        raise ValueError(
            f"Impossible de charger le dataset : {error}"
        )

    if df.empty:
        raise ValueError("Le dataset est vide.")

    return df