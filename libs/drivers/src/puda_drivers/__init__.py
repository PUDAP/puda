# # Initialize
# import os
# import sys
# import numpy as np
#
# # Add the external libraries path to sys.path
# external_libs = os.path.join(os.path.dirname(__file__), "external")
# sys.path.insert(0, external_libs)
# del sys, os, external_libs
#
# # Set numpy print options to 1.21
# np.set_printoptions(legacy="1.21")
# del np


import sys
from pathlib import Path

# Add src directory to Python path for local imports
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))