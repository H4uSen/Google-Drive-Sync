from pathlib import Path
from src.utils.paths import get_filters_file_path

DEFAULT_FILTER_RULES = [
    "# Exclusiones estrictas para coexistencia con Git/GitHub",
    "- .git/**",
    "- .gitignore",
    "# Exclusiones de archivos volátiles de Obsidian",
    "- .obsidian/workspace.json",
    "- .obsidian/workspace-mobile.json",
    "- .obsidian/cache/**",
    "- *.tmp",
    "# Inclusión explícita de notas, adjuntos, plugins, temas y libros",
    "+ *",
]

def get_default_filter_rules() -> list[str]:
    return list(DEFAULT_FILTER_RULES)

def write_filters_file(destination_path: Path | None = None) -> Path:
    target = destination_path or get_filters_file_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write("\n".join(DEFAULT_FILTER_RULES) + "\n")
    return target
