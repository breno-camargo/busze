import sys
from pathlib import Path

# Permite `import analysis.x` rodando pytest de dentro de spike/.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
