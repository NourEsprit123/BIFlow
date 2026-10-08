from pathlib import Path
import pandas as pd


DATA_DIR = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "raw"
)


def list_datasets():
    """
    Retourne tous les fichiers CSV présents
    dans data/raw/.
    """

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    return sorted(
        DATA_DIR.glob("*.csv")
    )


def load_dataset(file_path: str) -> pd.DataFrame:
    """
    Charge un dataset CSV à partir de son chemin.
    """

    if not file_path:
        raise ValueError(
            "Le chemin du fichier est vide."
        )

    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(
            f"Dataset introuvable : {file_path}"
        )

    if file_path.suffix.lower() != ".csv":
        raise ValueError(
            "Le fichier doit être au format CSV."
        )

    try:
        df = pd.read_csv(
            file_path,
            keep_default_na=False
        )

    except Exception as e:
        raise ValueError(
            f"Impossible de charger le dataset : {e}"
        )

    if df.empty:
        raise ValueError(
            "Le dataset est vide."
        )

    return df