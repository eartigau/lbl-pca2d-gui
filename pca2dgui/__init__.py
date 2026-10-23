"""lbl-pca2d-gui: a browser window that builds, runs and follows LBL wraps
with the PCA2D precleaning (LBL's lbl-pca2d branch).

    lbl-gui                    # opens the window in the browser

The window writes an ordinary LBL wrap (wrap.py, which runs by hand too) for
the targets and options picked, runs it in the environment LBL is installed
in, one run at a time, and shows its log as it goes; its history and what its
products weigh on disk are read back from the data folder.
"""

__version__ = "0.1.0"
