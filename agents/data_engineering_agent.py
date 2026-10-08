from analytics.profiler import profile_dataset
from analytics.data_quality import generate_quality_report


class DataEngineeringAgent:
    """
    Agent responsable des opérations de Data Engineering.
    """

    def __init__(self, name="Data Engineering Agent"):
        self.name = name

    def analyze(self, file_path: str) -> dict:
        """
        Analyse automatiquement un dataset :

        - profiling
        - qualité des données
        """

        print(
            f"[{self.name}] "
            "Starting dataset analysis..."
        )

        profile = profile_dataset(file_path)

        quality = generate_quality_report(file_path)

        print(
            f"[{self.name}] "
            "Dataset analysis completed."
        )

        return {
            "profile": profile,
            "quality": quality
        }