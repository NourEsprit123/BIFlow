import sys
from pathlib import Path


# Racine du projet BIFlow
ROOT_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT_DIR))


from analytics.dataset_loader import list_datasets
from agents.data_engineering_agent import DataEngineeringAgent


print("\n===================================")
print("             BIFlow")
print("       Dataset Discovery")
print("===================================\n")


# Chercher automatiquement les datasets
datasets = list_datasets()


if not datasets:
    print("Aucun dataset CSV trouvé dans data/.")
    print(
        "\nAjoutez un fichier CSV dans :"
        "\nD:\\BIFlow\\data"
    )

    sys.exit()


print("Datasets disponibles :\n")

for index, dataset in enumerate(datasets, start=1):
    print(f"{index}. {dataset.name}")


# Pour le moment, on analyse automatiquement
# le premier dataset trouvé.
selected_dataset = datasets[0]

print(
    f"\nDataset sélectionné : "
    f"{selected_dataset.name}"
)

print(
    f"Chemin : "
    f"{selected_dataset}"
)


# Lancer le Data Engineering Agent
agent = DataEngineeringAgent()

result = agent.analyze(
    str(selected_dataset)
)


# Afficher le profil
print("\n===================================")
print("             PROFILE")
print("===================================")

print(
    "Rows:",
    result["profile"]["rows"]
)

print(
    "Columns:",
    result["profile"]["columns"]
)

print(
    "Numerical columns:",
    result["profile"]["numerical_columns"]
)

print(
    "Categorical columns:",
    result["profile"]["categorical_columns"]
)


# Afficher la qualité
print("\n===================================")
print("             QUALITY")
print("===================================")

print(
    "Quality score:",
    result["quality"]["quality_score"]
)

print(
    "Missing values:",
    result["quality"]["missing_values"]
)

print(
    "Duplicates:",
    result["quality"]["duplicates"]
)

print("\nBIFlow analysis completed.")
